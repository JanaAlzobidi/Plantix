"""Command line for the scheduling engine.

    python run.py propose --reference-date 2026-10-15 --freeze-days 2
    python run.py approve
"""

import argparse
import sys
from dataclasses import replace

import pandas as pd

from engine import (
    CHANGE_LABELS_AR,
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
        print(frame[columns].astype(object).fillna("—").to_string(index=False))


def propose(args) -> int:
    paths = DataPaths.at(args.data_dir)
    programs, venues, approved = load_inputs(paths)
    config = replace(EngineConfig(), solver_time_limit_seconds=args.time_limit)

    result = generate_schedule(
        programs, venues, approved,
        reference_date=args.reference_date,
        freeze_window_days=args.freeze_days,
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

    print(f"\nحُفظ المقترح في {paths.proposal_dir}/ ولم يتغير الجدول المعتمد. للاعتماد: python run.py approve")
    return 0


def approve(args) -> int:
    paths = DataPaths.at(args.data_dir)
    try:
        target = approve_proposal(paths)
    except ApprovalError as exc:
        print(f"لم يتم الاعتماد: {exc}")
        return 1
    print(f"تم اعتماد الجدول المقترح في {target}. النسخة السابقة محفوظة في {paths.history_dir}/")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EXPOWISE scheduling engine")
    parser.add_argument("--data-dir", default="data")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("propose", help="إنشاء جدول مقترح دون تغيير الجدول المعتمد")
    p.add_argument("--reference-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--freeze-days", type=int, default=0)
    p.add_argument("--time-limit", type=float, default=EngineConfig().solver_time_limit_seconds)
    p.set_defaults(func=propose)

    a = sub.add_parser("approve", help="اعتماد آخر جدول مقترح")
    a.set_defaults(func=approve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
