import time as clock
from datetime import date, time

import pandas as pd
import pytest

from engine import (
    ApprovalError,
    DataPaths,
    EngineConfig,
    approve_proposal,
    generate_schedule,
    load_inputs,
    save_proposal,
)
from engine.data import PROGRAM_COLUMNS, VENUE_COLUMNS


# ------------------------------------------------------------------ helpers

def program(pid, duration=60, attendance=10, req="projector", time_type="flexible",
            fixed_date="", fixed_start="", fixed_venue="", pdates="", pslots="", name=None):
    return {
        "program_id": pid, "program_name": name or f"Program {pid}",
        "duration_min": str(duration), "attendance_value": str(attendance),
        "venue_requirements": req, "time_type": time_type,
        "fixed_date": fixed_date, "fixed_start_time": fixed_start, "fixed_venue_id": fixed_venue,
        "preferred_dates": pdates, "preferred_time_slots": pslots,
    }


def fixed(pid, day, start, venue, **kw):
    return program(pid, time_type="fixed", fixed_date=day, fixed_start=start, fixed_venue=venue, **kw)


def venue(vid, capacity=50, equipment="projector", setup=0, status="available"):
    return {
        "venue_id": vid, "venue_name": f"Venue {vid}", "capacity": str(capacity),
        "equipment": equipment, "min_setup_time_min": str(setup), "status": status,
    }


def approved(*rows):
    return pd.DataFrame(
        [{"program_id": p, "date": d, "start_time": s, "venue_id": v} for p, d, s, v in rows],
        columns=["program_id", "date", "start_time", "venue_id"],
    )


def config(start="2026-10-17", end="2026-10-17", open_=9, close=11, **kw):
    return EngineConfig(
        start_date=date.fromisoformat(start), end_date=date.fromisoformat(end),
        day_start=time(open_), day_end=close if isinstance(close, time) else time(close),
        solver_time_limit_seconds=10, **kw,
    )


def run(programs, venues, current=None, ref="2026-10-01", freeze=0, cfg=None):
    return generate_schedule(
        pd.DataFrame(programs, columns=PROGRAM_COLUMNS),
        pd.DataFrame(venues, columns=VENUE_COLUMNS),
        current,
        reference_date=ref,
        freeze_window_days=freeze,
        config=cfg or config(),
    )


def placed(result, pid):
    rows = result.schedule[result.schedule["program_id"] == pid]
    return None if rows.empty else rows.iloc[0].to_dict()


def reason(result, pid):
    rows = result.unscheduled[result.unscheduled["program_id"] == pid]
    return None if rows.empty else rows.iloc[0].to_dict()


def codes(result, severity=None):
    issues = result.issues
    if severity:
        issues = issues[issues["severity"] == severity]
    return set(issues["code"])


def change(result, pid):
    return result.changes.set_index("program_id").loc[pid].to_dict()


# ------------------------------------------------------------------ fixed events

def test_fixed_event_keeps_its_date_time_and_venue():
    result = run(
        [fixed("F", "2026-10-17", "10:00", "V2"), program("X")],
        [venue("V1"), venue("V2")],
    )
    row = placed(result, "F")
    assert (row["date"], row["start_time"], row["venue_id"]) == ("2026-10-17", "10:00", "V2")


def test_setup_time_blocks_the_venue_after_an_event():
    # F ends 10:00 and V1 needs 30 min setup. Closing at 11:30 leaves exactly
    # one valid start for a 60-min event: 10:30 (10:15 would break the setup).
    result = run(
        [fixed("F", "2026-10-17", "09:00", "V1"), program("X")],
        [venue("V1", setup=30)],
        cfg=config(close=time(11, 30)),
    )
    assert placed(result, "X")["start_time"] == "10:30"


def test_off_grid_fixed_start_is_handled_exactly():
    result = run(
        [fixed("F", "2026-10-17", "09:10", "V1", duration=50), program("X")],
        [venue("V1")],
        cfg=config(close=11),
    )
    assert placed(result, "X")["start_time"] == "10:00"


def test_events_may_run_in_parallel_in_different_venues():
    result = run(
        [program("A", duration=120), program("B", duration=120)],
        [venue("V1"), venue("V2")],
    )
    assert placed(result, "A") and placed(result, "B")
    assert placed(result, "A")["venue_id"] != placed(result, "B")["venue_id"]


def test_conflicting_fixed_events_stop_the_run_with_a_clear_error():
    result = run(
        [fixed("F1", "2026-10-17", "09:00", "V1"), fixed("F2", "2026-10-17", "10:15", "V1")],
        [venue("V1", setup=30)],
        cfg=config(close=12),
    )
    assert result.status == "INVALID_DATA"
    assert "FIXED_CONFLICT" in codes(result, "error")
    assert result.schedule.empty and not result.can_approve


def test_fixed_events_back_to_back_with_setup_respected_are_fine():
    result = run(
        [fixed("F1", "2026-10-17", "09:00", "V1"), fixed("F2", "2026-10-17", "10:30", "V1")],
        [venue("V1", setup=30)],
        cfg=config(close=12),
    )
    assert result.can_approve and len(result.schedule) == 2


@pytest.mark.parametrize("case, expected", [
    (dict(fixed_start="17:30", duration=60), "FIXED_OUTSIDE_HOURS"),
    (dict(fixed_venue="NOPE"), "FIXED_VENUE_NOT_FOUND"),
    (dict(attendance=500), "FIXED_VENUE_TOO_SMALL"),
    (dict(req="projector;stage"), "FIXED_VENUE_MISSING_EQUIPMENT"),
    (dict(fixed_date="2026-11-01"), "FIXED_DATE_OUTSIDE_HORIZON"),
    (dict(fixed_start=""), "FIXED_TIME_MISSING"),
])
def test_invalid_fixed_events_are_reported(case, expected):
    args = dict(time_type="fixed", fixed_date="2026-10-17", fixed_start="09:00", fixed_venue="V1")
    args.update(case)
    result = run([program("F", **args)], [venue("V1")], cfg=config(close=18))
    assert result.status == "INVALID_DATA"
    assert expected in codes(result, "error")


def test_fixed_event_in_maintenance_venue_is_an_error():
    result = run([fixed("F", "2026-10-17", "09:00", "V1")], [venue("V1", status="maintenance")])
    assert "FIXED_VENUE_UNAVAILABLE" in codes(result, "error")


# ------------------------------------------------------------------ hard constraints for flexible events

def test_maintenance_venue_is_never_used():
    result = run(
        [program("A", attendance=40), program("B", attendance=40)],
        [venue("V1", capacity=100, status="maintenance"), venue("V2", capacity=50)],
    )
    assert set(result.schedule["venue_id"]) == {"V2"}


def test_only_suitable_venue_in_maintenance_gives_a_clear_reason():
    result = run([program("A", attendance=80)], [venue("V1", capacity=100, status="maintenance"), venue("V2", capacity=50)])
    assert reason(result, "A")["reason_code"] == "VENUE_UNAVAILABLE"


def test_capacity_is_respected():
    result = run([program("A", attendance=80)], [venue("V1", capacity=60)])
    assert reason(result, "A")["reason_code"] == "CAPACITY"


def test_all_equipment_is_required_and_the_gap_is_named():
    result = run([program("A", req="projector;microphone")], [venue("V1", equipment="projector")])
    info = reason(result, "A")
    assert info["reason_code"] == "EQUIPMENT"
    assert "microphone" in info["suggestion"]


def test_equipment_matching_ignores_case_and_spacing():
    result = run([program("A", req="Projector ; Sound  System")], [venue("V1", equipment="projector;sound system")])
    assert placed(result, "A")


def test_events_end_within_operating_hours():
    result = run([program("A", duration=120)], [venue("V1")], cfg=config(close=11))
    row = placed(result, "A")
    assert (row["start_time"], row["end_time"]) == ("09:00", "11:00")


def test_unschedulable_flexible_event_does_not_stop_the_others():
    result = run([program("BIG", attendance=999), program("OK")], [venue("V1")])
    assert placed(result, "OK") and reason(result, "BIG")
    assert result.can_approve


# ------------------------------------------------------------------ data validation

def test_all_data_errors_are_collected_in_one_run():
    result = run(
        [program("A"), program("A"), program("B", time_type="sometimes"), program("C", pslots="9-10"),
         program("D", duration=0)],
        [venue("V1"), venue("V2", capacity=0)],
    )
    found = codes(result, "error")
    assert {"DUPLICATE_PROGRAM_ID", "INVALID_TIME_TYPE", "INVALID_PREFERRED_SLOT",
            "INVALID_DURATION", "INVALID_CAPACITY"} <= found


def test_missing_columns_are_reported():
    result = generate_schedule(
        pd.DataFrame([{"program_id": "A"}]), pd.DataFrame(columns=VENUE_COLUMNS),
        reference_date="2026-10-01", config=config(),
    )
    assert "MISSING_COLUMNS" in codes(result, "error")


def test_reference_date_is_required():
    result = run([program("A")], [venue("V1")], ref=None)
    assert "REFERENCE_DATE_MISSING" in codes(result, "error")


def test_unknown_venue_status_is_rejected():
    result = run([program("A")], [venue("V1", status="booked")])
    assert "INVALID_VENUE_STATUS" in codes(result, "error")


# ------------------------------------------------------------------ preferences are soft

def test_preferred_date_is_used_when_free():
    result = run([program("A", pdates="2026-10-18")], [venue("V1")], cfg=config(end="2026-10-19"))
    row = placed(result, "A")
    assert row["date"] == "2026-10-18" and row["preferred_date_met"] is True


def test_blocked_preferred_date_moves_the_event_instead_of_dropping_it():
    result = run(
        [fixed("F", "2026-10-17", "09:00", "V1", duration=120), program("A", pdates="2026-10-17")],
        [venue("V1")],
        cfg=config(end="2026-10-18"),
    )
    row = placed(result, "A")
    assert row["date"] == "2026-10-18" and row["preferred_date_met"] is False


def test_preferred_slot_must_contain_the_whole_event():
    result = run([program("A", duration=90, pslots="09:00-10:00")], [venue("V1")], cfg=config(close=12))
    assert placed(result, "A")["preferred_time_met"] is False

    result = run([program("A", duration=60, pslots="10:00-11:00")], [venue("V1")], cfg=config(close=12))
    row = placed(result, "A")
    assert row["start_time"] == "10:00" and row["preferred_time_met"] is True


def test_scheduling_more_events_beats_honouring_preferences():
    result = run(
        [program("A", pslots="09:00-10:00"), program("B", pslots="09:00-10:00")],
        [venue("V1")],
    )
    assert len(result.schedule) == 2


def test_smallest_suitable_venue_is_preferred():
    result = run([program("A", attendance=15)], [venue("BIG", capacity=500), venue("SMALL", capacity=20)])
    assert placed(result, "A")["venue_id"] == "SMALL"


# ------------------------------------------------------------------ freeze window

THREE_DAYS = dict(start="2026-10-17", end="2026-10-19", close=12)


def test_new_flexible_event_is_kept_out_of_the_freeze_window():
    # ref 15, N=2 -> 15, 16, 17 frozen.
    result = run([program("NEW", pdates="2026-10-17")], [venue("V1")],
                 ref="2026-10-15", freeze=2, cfg=config(**THREE_DAYS))
    assert placed(result, "NEW")["date"] in {"2026-10-18", "2026-10-19"}
    assert result.summary["freeze_window_dates"] == ["2026-10-17"]


def test_existing_flexible_event_may_stay_inside_the_freeze_window():
    result = run([program("OLD")], [venue("V1")], approved(("OLD", "2026-10-17", "10:00", "V1")),
                 ref="2026-10-15", freeze=2, cfg=config(**THREE_DAYS))
    assert change(result, "OLD")["change_type"] == "unchanged"


def test_new_fixed_event_may_sit_inside_the_freeze_window():
    result = run([fixed("F", "2026-10-17", "09:00", "V1")], [venue("V1")],
                 ref="2026-10-15", freeze=2, cfg=config(**THREE_DAYS))
    assert placed(result, "F")["date"] == "2026-10-17"


def test_fully_frozen_horizon_leaves_new_flexible_unscheduled_with_reason():
    result = run(
        [program("NEW"), program("OLD")], [venue("V1"), venue("V2")],
        approved(("OLD", "2026-10-18", "09:00", "V1")),
        ref="2026-10-15", freeze=4, cfg=config(**THREE_DAYS),
    )
    assert reason(result, "NEW")["reason_code"] == "FREEZE_WINDOW"
    assert placed(result, "OLD")


def test_zero_freeze_days_means_no_freeze_even_on_the_reference_date():
    result = run([program("NEW", pdates="2026-10-17")], [venue("V1")],
                 ref="2026-10-17", freeze=0, cfg=config(**THREE_DAYS))
    assert placed(result, "NEW")["date"] == "2026-10-17"


def test_moving_an_approved_event_inside_the_freeze_window_is_flagged():
    result = run(
        [program("OLD"), fixed("F", "2026-10-17", "09:30", "V1")], [venue("V1")],
        approved(("OLD", "2026-10-17", "09:30", "V1")),
        ref="2026-10-16", freeze=1, cfg=config(close=12),
    )
    assert change(result, "OLD")["change_type"] == "moved"
    assert "CHANGE_IN_FREEZE_WINDOW" in codes(result, "warning")


# ------------------------------------------------------------------ objective order and stability

def test_approved_event_is_moved_when_that_lets_a_new_one_fit():
    # Window 09-11. OLD at 09:30 leaves no 60-min gap; moving it fits NEW too.
    result = run([program("OLD"), program("NEW")], [venue("V1")],
                 approved(("OLD", "2026-10-17", "09:30", "V1")))
    assert placed(result, "OLD") and placed(result, "NEW")
    assert change(result, "OLD")["change_type"] == "moved"


def test_approved_event_is_never_dropped_for_a_new_one():
    result = run([program("OLD"), program("NEW")], [venue("V1")],
                 approved(("OLD", "2026-10-17", "09:00", "V1")), cfg=config(close=10))
    assert change(result, "OLD")["change_type"] == "unchanged"
    info = reason(result, "NEW")
    assert info["reason_code"] == "CONFLICTS" and "OLD" in info["related_ids"]


def test_stability_beats_preferences():
    result = run([program("OLD", pslots="09:00-10:00")], [venue("V1")],
                 approved(("OLD", "2026-10-17", "10:00", "V1")))
    assert change(result, "OLD")["change_type"] == "unchanged"


def test_room_change_keeps_the_approved_time_when_possible():
    # V1 goes into maintenance; OLD should keep 10:00 in V2 rather than move in time.
    result = run([program("OLD")], [venue("V1", status="maintenance"), venue("V2")],
                 approved(("OLD", "2026-10-17", "10:00", "V1")), cfg=config(close=13))
    row = change(result, "OLD")
    assert (row["new_start_time"], row["new_venue_id"], row["changed_fields"]) == ("10:00", "V2", "venue")


def test_when_something_must_move_the_engine_moves_it_outside_the_freeze_window():
    # 17 is frozen, 18 is not. OLD17 and OLD18 each sit at 09:30 and block their
    # day; E (approved outside the horizon) must go on one of them, forcing a
    # move. E prefers the 17th, but moving a frozen event costs double, so the
    # engine must move OLD18 instead.
    result = run(
        [program("OLD17"), program("OLD18"), program("E", pdates="2026-10-17")],
        [venue("V1")],
        approved(("OLD17", "2026-10-17", "09:30", "V1"), ("OLD18", "2026-10-18", "09:30", "V1"),
                 ("E", "2026-10-25", "09:00", "V1")),
        ref="2026-10-16", freeze=1, cfg=config(end="2026-10-18"),
    )
    assert change(result, "OLD17")["change_type"] == "unchanged"
    assert change(result, "OLD18")["change_type"] == "moved"
    assert placed(result, "E")["date"] == "2026-10-18"


def test_rerunning_with_the_approved_result_changes_nothing():
    programs = [program(f"P{i}", duration=60 + 15 * (i % 3), attendance=10 + i) for i in range(8)]
    venues = [venue("V1", capacity=30), venue("V2", capacity=50)]
    cfg = config(end="2026-10-18", close=13)
    first = run(programs, venues, cfg=cfg)
    current = first.schedule[["program_id", "date", "start_time", "venue_id"]]
    second = run(programs, venues, current, cfg=cfg)
    assert set(second.changes["change_type"]) == {"unchanged"}


# ------------------------------------------------------------------ change report

def test_change_report_covers_new_dropped_and_removed():
    result = run(
        [program("OLD", attendance=999), program("NEW")], [venue("V1")],
        approved(("OLD", "2026-10-17", "09:00", "V1"), ("GONE", "2026-10-17", "10:00", "V1")),
    )
    assert change(result, "OLD")["change_type"] == "dropped"
    assert change(result, "NEW")["change_type"] == "new"
    assert change(result, "GONE")["change_type"] == "removed"
    assert {"APPROVED_EVENT_DROPPED", "APPROVED_PROGRAM_REMOVED"} <= codes(result, "warning")


def test_fixed_event_that_differs_from_approved_is_flagged_and_follows_programs_file():
    result = run([fixed("F", "2026-10-17", "10:00", "V1")], [venue("V1")],
                 approved(("F", "2026-10-17", "09:00", "V1")))
    assert placed(result, "F")["start_time"] == "10:00"
    assert change(result, "F")["changed_fields"] == "start_time"
    assert "FIXED_ASSIGNMENT_CHANGED" in codes(result, "warning")


# ------------------------------------------------------------------ proposal vs approved files

def _write(paths, programs, venues):
    paths.root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(programs, columns=PROGRAM_COLUMNS).to_csv(paths.programs, index=False)
    pd.DataFrame(venues, columns=VENUE_COLUMNS).to_csv(paths.venues, index=False)


def _propose(paths):
    programs, venues, current = load_inputs(paths)
    result = generate_schedule(programs, venues, current, reference_date="2026-10-01", config=config())
    save_proposal(result, paths)
    return result


def test_proposal_does_not_touch_the_approved_schedule_until_approved(tmp_path):
    paths = DataPaths.at(tmp_path)
    _write(paths, [program("A"), program("B")], [venue("V1"), venue("V2")])

    _propose(paths)
    assert not paths.approved.exists()

    approve_proposal(paths)
    approved_df = pd.read_csv(paths.approved, dtype=str, encoding="utf-8-sig")
    assert set(approved_df["program_id"]) == {"A", "B"}

    with pytest.raises(ApprovalError):
        approve_proposal(paths)  # already approved

    second = _propose(paths)
    assert set(second.changes["change_type"]) == {"unchanged"}
    approve_proposal(paths)
    assert len(list(paths.history_dir.glob("approved_schedule_*.csv"))) == 1


def test_stale_or_invalid_proposals_cannot_be_approved(tmp_path):
    paths = DataPaths.at(tmp_path)
    _write(paths, [program("A")], [venue("V1")])
    _propose(paths)
    _write(paths, [program("A"), program("B")], [venue("V1")])
    with pytest.raises(ApprovalError):
        approve_proposal(paths)

    _write(paths, [program("A"), program("A")], [venue("V1")])
    _propose(paths)
    with pytest.raises(ApprovalError):
        approve_proposal(paths)


# ------------------------------------------------------------------ scale

def test_realistic_size_solves_quickly():
    programs = [
        program(f"P{i:02d}", duration=[45, 60, 90, 120][i % 4], attendance=[20, 35, 80, 150][i % 4],
                pdates=["2026-10-17", "2026-10-18", "", "2026-10-19"][i % 4],
                pslots=["09:00-12:00", "", "13:00-17:00", ""][i % 4])
        for i in range(60)
    ]
    venues = [venue(f"V{j}", capacity=[30, 40, 100, 120, 200, 60, 50, 300, 25, 80][j], setup=15) for j in range(10)]
    started = clock.monotonic()
    result = run(programs, venues, cfg=EngineConfig(solver_time_limit_seconds=20))
    assert result.can_approve
    assert len(result.schedule) == 60
    assert clock.monotonic() - started < 30
