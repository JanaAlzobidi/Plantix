"""Command line for the scheduling engine.

    python run.py propose --reference-date 2026-10-15 --freeze-days 2
    python run.py approve

    # one expo (client) with its own rules and history:
    python run.py --client clients/riyadh_mini propose --reference-date 2026-10-15
    python run.py --client clients/riyadh_mini approve
"""

import argparse
import sys
from dataclasses import replace

import pandas as pd

from engine import (
    CHANGE_LABELS_AR,
    ClientConfigError,
    load_client,
    ApprovalError,
    DataPaths,
    EngineConfig,
    approve_proposal,
    generate_schedule,
    load_inputs,
    save_proposal,
)


def _print_table(title, frame, columns):
    print(f"\n=== {title} ({len(frame)}) ===")
    if frame.empty:
        print("لا يوجد.")
        return
    with pd.option_context("display.max_colwidth", 200, "display.width", 250):
        view = frame[columns].astype(object)
        print(view.where(view.notna(), "—").to_string(index=False))


def _attendance_module():
    """The attendance alerts module is optional; scheduling works without it."""
    try:
        from engine import insights
    except ImportError:
        return None
    return insights


def _setup(args):
    """(paths, config, default freeze days, client or None) for --client or --data-dir."""
    if args.client:
        client = load_client(args.client)
        return client.paths, client.config, client.freeze_window_days, client
    return DataPaths.at(args.data_dir), EngineConfig(), 0, None


def propose(args) -> int:
    try:
        paths, config, default_freeze, client = _setup(args)
    except ClientConfigError as exc:
        print(f"خطأ في إعدادات المعرض: {exc}")
        return 1
    if args.time_limit is not None:
        config = replace(config, solver_time_limit_seconds=args.time_limit)
    freeze = default_freeze if args.freeze_days is None else args.freeze_days
    programs, venues, approved = load_inputs(paths)

    if client:
        print(f"المعرض: {client.name} | {config.start_date} إلى {config.end_date} | "
              f"{config.day_start:%H:%M}–{config.day_end:%H:%M}")

    result = generate_schedule(
        programs, venues, approved,
        reference_date=args.reference_date,
        freeze_window_days=freeze,
        config=config,
    )
    save_proposal(result, paths)
    s = result.summary

    print(f"التاريخ المرجعي: {s['reference_date']} | نافذة التجميد: {s['freeze_window_days']} يوم "
          f"{s['freeze_window_dates'] or ''}")
    print(f"حالة الحل: {result.status}")

    if result.status == "INVALID_DATA" or not result.can_approve:
        _print_table("المشكلات", result.issues, ["severity", "code", "message"])
        print(f"\nلم يُنشأ جدول قابل للاعتماد. التفاصيل في {paths.proposal_dir}/issues.csv")
        return 1

    print(f"مجدولة {s['scheduled']} من {s['total_programs']} | غير مجدولة {s['unscheduled']} | "
          f"التفضيلات: التاريخ {s['preferred_date_met']}، الوقت {s['preferred_time_met']}")
    print(f"مقارنة بالمعتمد: جديدة {s['new_scheduled']}، بدون تغيير {s['unchanged']}، "
          f"تغيّرت {s['moved']} (منها داخل نافذة التجميد {s['moved_in_freeze_window']})، "
          f"أُسقطت {s['dropped']}")

    _print_table("الجدول المقترح", result.schedule,
                 ["program_id", "program_name", "date", "start_time", "end_time", "venue_name", "attendance", "time_type"])
    _print_table("غير المجدولة", result.unscheduled, ["program_id", "program_name", "reason", "suggestion"])

    changed = result.changes[result.changes["change_type"] != "unchanged"].copy()
    changed["change"] = changed["change_type"].map(CHANGE_LABELS_AR)
    _print_table("التغييرات", changed,
                 ["program_id", "program_name", "change", "old_date", "old_start_time", "old_venue_id",
                  "new_date", "new_start_time", "new_venue_id"])
    _print_table("تنبيهات", result.issues, ["code", "message"])

    insights = _attendance_module()
    if client and client.alerts_enabled and client.history_path.exists() and insights:
        from engine.storage import read_csv
        attendance_alerts = insights.attendance_alerts
        model = insights.learn_attendance(read_csv(client.history_path))
        alerts = attendance_alerts(model, programs, result.schedule, venues, client.alerts_min_history)
        alerts.to_csv(paths.proposal_dir / "attendance_alerts.csv", index=False, encoding="utf-8-sig")
        print(f"\n=== تنبيهات ذكية من الدورات السابقة ({len(alerts)}) ===")
        if alerts.empty:
            print("لا يُتوقع ازدحام يتجاوز سعة أي قاعة.")
        for alert in alerts.itertuples():
            print(f"- {alert.message}\n  ← {alert.suggestion}")

    client_flag = f"--client {args.client} " if args.client else ""
    print(f"\nحُفظ المقترح في {paths.proposal_dir}/ ولم يتغير الجدول المعتمد. "
          f"للاعتماد: python run.py {client_flag}approve")
    return 0


def approve(args) -> int:
    try:
        paths = _setup(args)[0]
    except ClientConfigError as exc:
        print(f"خطأ في إعدادات المعرض: {exc}")
        return 1
    try:
        target = approve_proposal(paths)
    except ApprovalError as exc:
        print(f"لم يتم الاعتماد: {exc}")
        return 1
    print(f"تم اعتماد الجدول المقترح في {target}. النسخة السابقة محفوظة في {paths.history_dir}/")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Plantix scheduling engine")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--client", help="مجلد معرض فيه client.json، مثل clients/riyadh_mini")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("propose", help="إنشاء جدول مقترح دون تغيير الجدول المعتمد")
    p.add_argument("--reference-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--freeze-days", type=int, default=None, help="الافتراضي: من إعدادات المعرض، أو 0")
    p.add_argument("--time-limit", type=float, default=None)
    p.set_defaults(func=propose)

    a = sub.add_parser("approve", help="اعتماد آخر جدول مقترح")
    a.set_defaults(func=approve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
