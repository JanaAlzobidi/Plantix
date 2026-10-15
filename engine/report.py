"""Turn the solver outcome into the tables the manager reviews."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .candidates import Candidate, Diagnosis, allowed_days, overlaps
from .config import FIXED, EngineConfig, in_freeze_window
from .data import Inputs, IssueLog, fmt_minutes
from .solver import SolveOutcome, preferred_date_met, preferred_time_met


SCHEDULE_COLUMNS_OUT = [
    "program_id", "program_name", "date", "start_time", "end_time",
    "venue_id", "venue_name", "attendance", "venue_capacity", "time_type",
    "is_existing", "venue_busy_until", "preferred_date_met", "preferred_time_met",
]
UNSCHEDULED_COLUMNS = [
    "program_id", "program_name", "time_type", "is_existing",
    "reason_code", "reason", "suggestion", "related_ids",
]
CHANGE_COLUMNS = [
    "program_id", "program_name", "time_type", "change_type", "changed_fields",
    "old_date", "old_start_time", "old_venue_id",
    "new_date", "new_start_time", "new_venue_id", "in_freeze_window",
]
ISSUE_COLUMNS = ["severity", "code", "program_id", "venue_id", "message"]

CHANGE_LABELS_AR = {
    "new": "جديدة ومجدولة",
    "unchanged": "بدون تغيير",
    "moved": "تغيّر موعدها أو قاعتها",
    "dropped": "معتمدة سابقًا ولم تُجدول",
    "not_scheduled": "جديدة ولم تُجدول",
    "removed": "حُذفت من قائمة البرامج",
}


@dataclass
class ScheduleResult:
    status: str
    schedule: pd.DataFrame
    unscheduled: pd.DataFrame
    changes: pd.DataFrame
    issues: pd.DataFrame
    summary: dict

    @property
    def can_approve(self) -> bool:
        return bool(self.summary.get("can_approve"))


def _issues_frame(log: IssueLog) -> pd.DataFrame:
    rows = [
        {
            "severity": issue.severity,
            "code": issue.code,
            "program_id": issue.program_id,
            "venue_id": issue.venue_id,
            "message": issue.message,
        }
        for issue in log.items
    ]
    frame = pd.DataFrame(rows, columns=ISSUE_COLUMNS)
    if not frame.empty:
        order = frame["severity"].map({"error": 0, "warning": 1})
        frame = frame.assign(_o=order).sort_values("_o", kind="stable").drop(columns="_o")
    return frame.reset_index(drop=True)


def _freeze_dates(inputs: Inputs, config: EngineConfig) -> list[str]:
    if inputs.reference_date is None:
        return []
    return [
        day.isoformat() for day in config.horizon_days()
        if in_freeze_window(day, inputs.reference_date, inputs.freeze_window_days)
    ]


def build_failed_result(status: str, inputs: Inputs, log: IssueLog, config: EngineConfig) -> ScheduleResult:
    summary = {
        "solver_status": status,
        "proven_optimal": False,
        "reference_date": inputs.reference_date.isoformat() if inputs.reference_date else None,
        "freeze_window_days": inputs.freeze_window_days,
        "freeze_window_dates": _freeze_dates(inputs, config),
        "total_programs": len(inputs.programs),
        "scheduled": 0,
        "unscheduled": 0,
        "errors": log.count("error"),
        "warnings": log.count("warning"),
        "can_approve": False,
    }
    return ScheduleResult(
        status=status,
        schedule=pd.DataFrame(columns=SCHEDULE_COLUMNS_OUT),
        unscheduled=pd.DataFrame(columns=UNSCHEDULED_COLUMNS),
        changes=pd.DataFrame(columns=CHANGE_COLUMNS),
        issues=_issues_frame(log),
        summary=summary,
    )


def _diagnose_conflict(pid, inputs, candidates, chosen, proven_optimal, config) -> Diagnosis:
    """Program had valid options but none was selected."""
    program = inputs.programs[pid]
    options = candidates[pid]

    placed_by_room: dict[tuple, list[tuple[str, Candidate]]] = {}
    for other_pid, cand in chosen.items():
        placed_by_room.setdefault((cand.venue_id, cand.date), []).append((other_pid, cand))

    blockers: set[str] = set()
    free_option = False
    for option in options:
        hits = [
            other_pid
            for other_pid, cand in placed_by_room.get((option.venue_id, option.date), ())
            if overlaps(option.start, option.busy_until, cand.start, cand.busy_until)
        ]
        if not hits:
            free_option = True
        blockers.update(hits)

    if free_option:
        return Diagnosis(
            "SOLVER_TIME_LIMIT",
            "يوجد لها مكان متاح، لكن المحلل لم يصل إليه خلال المهلة المحددة.",
            "زد مهلة الحل (solver_time_limit_seconds) وأعد التشغيل.",
        )

    room_names = sorted({inputs.venues[o.venue_id].name for o in options})
    reason = (
        f"توجد خيارات متوافقة ({len(options)}) في {'، '.join(room_names)}، "
        "لكن كلها تتداخل مع فعاليات أخرى في الجدول المقترح"
    )
    reason += "، ولا يمكن إدخالها إلا على حساب فعالية أخرى." if proven_optimal else "."

    excluded = sorted(set(config.horizon_days()) - set(allowed_days(program, inputs, config)))
    if excluded:
        reason += (
            " كما أن أيام نافذة التجميد ("
            + "، ".join(day.isoformat() for day in excluded)
            + ") مستبعدة لأنها فعالية جديدة."
        )

    def label(other_pid):
        other = inputs.programs[other_pid]
        tag = " - ثابتة" if other.is_fixed else ""
        return f"{other_pid} ({other.name}{tag})"

    ordered = sorted(blockers)
    shown = "، ".join(label(b) for b in ordered[:5])
    if len(ordered) > 5:
        shown += f" و{len(ordered) - 5} غيرها"
    suggestion = (
        f"الفعاليات التي تشغل أوقاتها الممكنة: {shown}. "
        "يمكن إضافة قاعة مناسبة، أو تقصير مدة الفعالية، أو تمديد ساعات التشغيل أو أيام الجدولة."
    )
    return Diagnosis("CONFLICTS", reason, suggestion, tuple(ordered))


def build_result(inputs: Inputs, candidates, diagnoses, outcome: SolveOutcome,
                 log: IssueLog, config: EngineConfig) -> ScheduleResult:
    programs, venues, chosen = inputs.programs, inputs.venues, outcome.chosen
    ref, freeze = inputs.reference_date, inputs.freeze_window_days

    if not outcome.proven_optimal:
        log.warning(
            "NOT_PROVEN_OPTIMAL",
            "انتهت مهلة المحلل قبل إثبات أن هذا أفضل جدول ممكن. الجدول صالح، "
            "لكن زيادة المهلة قد تحسّنه.",
        )

    # ---- proposed schedule
    rows = []
    for pid, cand in chosen.items():
        program, venue = programs[pid], venues[cand.venue_id]
        rows.append({
            "program_id": pid,
            "program_name": program.name,
            "date": cand.date.isoformat(),
            "start_time": fmt_minutes(cand.start),
            "end_time": fmt_minutes(cand.end),
            "venue_id": venue.venue_id,
            "venue_name": venue.name,
            "attendance": program.attendance,
            "venue_capacity": venue.capacity,
            "time_type": program.time_type,
            "is_existing": pid in inputs.existing,
            "venue_busy_until": fmt_minutes(cand.busy_until),
            "preferred_date_met": preferred_date_met(program, cand),
            "preferred_time_met": preferred_time_met(program, cand),
        })
    schedule = pd.DataFrame(rows, columns=SCHEDULE_COLUMNS_OUT)
    if not schedule.empty:
        schedule = schedule.sort_values(["date", "start_time", "venue_name"]).reset_index(drop=True)

    # ---- unscheduled with reasons
    unscheduled_rows = []
    for pid, program in programs.items():
        if pid in chosen:
            continue
        diagnosis = diagnoses.get(pid) or _diagnose_conflict(
            pid, inputs, candidates, chosen, outcome.proven_optimal, config
        )
        unscheduled_rows.append({
            "program_id": pid,
            "program_name": program.name,
            "time_type": program.time_type,
            "is_existing": pid in inputs.existing,
            "reason_code": diagnosis.code,
            "reason": diagnosis.reason,
            "suggestion": diagnosis.suggestion,
            "related_ids": ";".join(diagnosis.related_ids),
        })
    unscheduled = pd.DataFrame(unscheduled_rows, columns=UNSCHEDULED_COLUMNS)

    # ---- changes against the approved schedule
    change_rows = []

    def change_row(pid, name, time_type, change_type, old=None, new=None, fields=""):
        touches = any(
            point is not None and in_freeze_window(point, ref, freeze)
            for point in (old.date if old else None, new.date if new else None)
        )
        return {
            "program_id": pid,
            "program_name": name,
            "time_type": time_type,
            "change_type": change_type,
            "changed_fields": fields,
            "old_date": old.date.isoformat() if old else None,
            "old_start_time": fmt_minutes(old.start) if old else None,
            "old_venue_id": old.venue_id if old else None,
            "new_date": new.date.isoformat() if new else None,
            "new_start_time": fmt_minutes(new.start) if new else None,
            "new_venue_id": new.venue_id if new else None,
            "in_freeze_window": touches,
        }

    for pid, program in programs.items():
        old, new = inputs.existing.get(pid), chosen.get(pid)
        if old and new:
            fields = [
                name for name, same in (
                    ("date", old.date == new.date),
                    ("start_time", old.start == new.start),
                    ("venue", old.venue_id == new.venue_id),
                ) if not same
            ]
            kind = "moved" if fields else "unchanged"
            change_rows.append(change_row(pid, program.name, program.time_type, kind, old, new, ";".join(fields)))
        elif old:
            change_rows.append(change_row(pid, program.name, program.time_type, "dropped", old=old))
        elif new:
            change_rows.append(change_row(pid, program.name, program.time_type, "new", new=new))
        else:
            change_rows.append(change_row(pid, program.name, program.time_type, "not_scheduled"))

    for pid, old in inputs.removed.items():
        change_rows.append(change_row(pid, old.program_name, None, "removed", old=old))

    changes = pd.DataFrame(change_rows, columns=CHANGE_COLUMNS)

    for row in change_rows:
        if row["change_type"] == "dropped":
            log.warning(
                "APPROVED_EVENT_DROPPED",
                f"الفعالية المعتمدة {row['program_id']} ({row['program_name']}) لم تعد مجدولة في الخطة المقترحة.",
                program_id=row["program_id"],
            )
        elif row["change_type"] == "moved" and row["in_freeze_window"]:
            log.warning(
                "CHANGE_IN_FREEZE_WINDOW",
                f"الفعالية المعتمدة {row['program_id']} ({row['program_name']}) تغيّر موعدها أو قاعتها "
                f"داخل نافذة التجميد: من {row['old_date']} {row['old_start_time']} ({row['old_venue_id']}) "
                f"إلى {row['new_date']} {row['new_start_time']} ({row['new_venue_id']}).",
                program_id=row["program_id"],
            )

    # ---- summary
    counts = changes["change_type"].value_counts().to_dict() if not changes.empty else {}
    with_date_pref = schedule["preferred_date_met"].notna() if not schedule.empty else pd.Series(dtype=bool)
    with_time_pref = schedule["preferred_time_met"].notna() if not schedule.empty else pd.Series(dtype=bool)

    summary = {
        "solver_status": outcome.status,
        "proven_optimal": outcome.proven_optimal,
        "solve_seconds": round(outcome.seconds, 2),
        "reference_date": ref.isoformat(),
        "freeze_window_days": freeze,
        "freeze_window_dates": _freeze_dates(inputs, config),
        "total_programs": len(programs),
        "fixed_programs": sum(p.time_type == FIXED for p in programs.values()),
        "flexible_programs": sum(p.time_type != FIXED for p in programs.values()),
        "scheduled": len(schedule),
        "unscheduled": len(unscheduled),
        "new_scheduled": counts.get("new", 0),
        "unchanged": counts.get("unchanged", 0),
        "moved": counts.get("moved", 0),
        "moved_in_freeze_window": int(
            ((changes["change_type"] == "moved") & changes["in_freeze_window"]).sum()
        ) if not changes.empty else 0,
        "dropped": counts.get("dropped", 0),
        "new_not_scheduled": counts.get("not_scheduled", 0),
        "removed_from_programs": counts.get("removed", 0),
        "preferred_date_met": f"{int(schedule.loc[with_date_pref, 'preferred_date_met'].astype(bool).sum())}/{int(with_date_pref.sum())}",
        "preferred_time_met": f"{int(schedule.loc[with_time_pref, 'preferred_time_met'].astype(bool).sum())}/{int(with_time_pref.sum())}",
        "errors": log.count("error"),
        "warnings": log.count("warning"),
    }
    summary["can_approve"] = summary["errors"] == 0

    return ScheduleResult(
        status=outcome.status,
        schedule=schedule,
        unscheduled=unscheduled,
        changes=changes,
        issues=_issues_frame(log),
        summary=summary,
    )
