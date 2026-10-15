"""EXPOWISE scheduling engine.

    from engine import generate_schedule
    result = generate_schedule(programs, venues, approved,
                               reference_date="2026-10-15", freeze_window_days=2)
    result.schedule, result.unscheduled, result.changes, result.issues, result.summary
"""

from __future__ import annotations

from .candidates import build_candidates
from .config import EngineConfig, in_freeze_window
from .data import IssueLog, prepare_inputs
from .report import CHANGE_LABELS_AR, ScheduleResult, build_failed_result, build_result
from .solver import solve
from .storage import ApprovalError, DataPaths, approve_proposal, load_inputs, save_proposal


def generate_schedule(programs, venues, current_schedule=None, *, reference_date,
                      freeze_window_days: int = 0, config: EngineConfig | None = None) -> ScheduleResult:
    """Builds a proposed schedule. Never writes files and never raises on bad data:
    data problems come back in result.issues with status INVALID_DATA."""
    config = config or EngineConfig()
    log = IssueLog()

    inputs = prepare_inputs(
        programs, venues, current_schedule, reference_date, freeze_window_days, config, log
    )
    if log.has_errors:
        return build_failed_result("INVALID_DATA", inputs, log, config)

    candidates, diagnoses = build_candidates(inputs, config)
    outcome = solve(inputs, candidates, config)
    if not outcome.ok:
        log.error("NO_SOLUTION", outcome.message)
        return build_failed_result(outcome.status, inputs, log, config)

    return build_result(inputs, candidates, diagnoses, outcome, log, config)


__all__ = [
    "ApprovalError", "CHANGE_LABELS_AR", "DataPaths", "EngineConfig", "ScheduleResult",
    "approve_proposal", "generate_schedule", "in_freeze_window", "load_inputs", "save_proposal",
]
