"""Plantix scheduling engine.

    from engine import generate_schedule
    result = generate_schedule(programs, venues, approved,
                               reference_date="2026-10-15", freeze_window_days=2)
    result.schedule, result.unscheduled, result.changes, result.issues, result.summary

Attendance alerts (engine/insights.py) are a separate, optional module: the
scheduling engine works without it. Import it directly when present:

    from engine.insights import learn_attendance, attendance_alerts
"""

from __future__ import annotations

from .candidates import build_candidates
from .client import Client, ClientConfigError, load_client
from .config import (
    ADMISSION_LABELS_AR, ADMISSION_OPEN, ADMISSION_REGISTRATION, PRIORITY_LABELS_AR, PRIORITY_LEVELS,
    EngineConfig, in_freeze_window,
)
from .data import IssueLog, prepare_inputs
from .report import CHANGE_LABELS_AR, ScheduleResult, build_failed_result, build_result
from .profile import ClientProfile, ProfileError, load_profile, profile_from_dict
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
    "ADMISSION_LABELS_AR", "ADMISSION_OPEN", "ADMISSION_REGISTRATION",
    "ApprovalError", "CHANGE_LABELS_AR", "Client", "ClientConfigError",
    "ClientProfile", "DataPaths", "EngineConfig", "PRIORITY_LABELS_AR", "PRIORITY_LEVELS", "ProfileError",
    "ScheduleResult", "approve_proposal", "generate_schedule",
    "in_freeze_window", "load_client", "load_inputs", "load_profile",
    "profile_from_dict", "save_proposal",
]
