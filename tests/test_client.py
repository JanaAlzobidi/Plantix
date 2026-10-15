import json
from datetime import date, time
from pathlib import Path

import pandas as pd
import pytest

from engine import ClientConfigError, generate_schedule, load_client, load_inputs
from engine.data import PROGRAM_COLUMNS, VENUE_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "clients" / "riyadh_mini"
COLS = ["program_id", "program_name", "date", "start_time", "end_time", "venue_id", "venue_name"]


# ------------------------------------------------------------------ client configuration

def _write_client(folder, **overrides):
    folder.mkdir(parents=True, exist_ok=True)
    raw = {"name": "Test expo", "start_date": "2026-10-17", "end_date": "2026-10-18",
           "day_start": "10:00", "day_end": "20:00", "freeze_window_days": 1}
    raw.update(overrides)
    (folder / "client.json").write_text(json.dumps(raw), encoding="utf-8")
    return folder


def test_client_file_sets_the_engine_rules(tmp_path):
    client = load_client(_write_client(tmp_path, slot_minutes=30))
    assert client.config.day_start == time(10, 0) and client.config.day_end == time(20, 0)
    assert client.config.slot_minutes == 30
    assert client.config.horizon_days() == [date(2026, 10, 17), date(2026, 10, 18)]
    assert client.freeze_window_days == 1


@pytest.mark.parametrize("override, fragment", [
    ({"day_start": "25:00"}, "day_start"),
    ({"start_date": "17/10/2026"}, "start_date"),
    ({"day_start": "20:00", "day_end": "10:00"}, "ساعات التشغيل"),
    ({"freeze_window_days": -1}, "freeze_window_days"),
])
def test_invalid_client_files_are_explained(tmp_path, override, fragment):
    with pytest.raises(ClientConfigError, match=fragment):
        load_client(_write_client(tmp_path, **override))


def test_missing_client_file_is_explained(tmp_path):
    with pytest.raises(ClientConfigError):
        load_client(tmp_path)


def test_same_programs_follow_each_clients_hours(tmp_path):
    programs, venues, _ = load_inputs(load_client(MINI).paths)
    flexible = programs[programs["time_type"] == "flexible"]
    early = load_client(_write_client(tmp_path / "early", day_start="08:00", day_end="16:00"))
    late = load_client(_write_client(tmp_path / "late", day_start="12:00", day_end="22:00"))
    for client, open_, close in ((early, "08:00", "16:00"), (late, "12:00", "22:00")):
        result = generate_schedule(flexible, venues, reference_date="2026-10-01", config=client.config)
        assert (result.schedule["start_time"] >= open_).all()
        assert (result.schedule["end_time"] <= close).all()


def test_invalid_admission_value_is_a_data_error():
    row = {c: "" for c in PROGRAM_COLUMNS}
    row.update(program_id="A", program_name="A", duration_min="60", attendance_value="10",
               time_type="flexible", admission="maybe")
    result = generate_schedule(
        pd.DataFrame([row]),
        pd.DataFrame([{"venue_id": "V", "venue_name": "V", "capacity": "50", "equipment": "",
                       "min_setup_time_min": "0", "status": "available"}], columns=VENUE_COLUMNS),
        reference_date="2026-10-01",
    )
    assert "INVALID_ADMISSION" in set(result.issues["code"])


def test_client_file_accepts_every_profile_rule(tmp_path):
    client = load_client(_write_client(
        tmp_path,
        priorities=["keep_approved", "stability", "schedule_count", "preferences", "room_fit"],
    ))
    assert client.config.priorities[1] == "stability"


# ------------------------------------------------------------------ the 4-day demo scenario (scheduling only)

def test_mini_expo_scheduling_story_holds():
    client = load_client(MINI)
    programs, venues, _ = load_inputs(client.paths)
    today = dict(reference_date="2026-10-15", freeze_window_days=client.freeze_window_days, config=client.config)

    baseline = generate_schedule(programs, venues, reference_date="2026-10-01",
                                 freeze_window_days=client.freeze_window_days, config=client.config)
    assert baseline.summary["scheduled"] == 19
    assert list(baseline.unscheduled["program_id"]) == ["P11"]

    # Sound system fails in V02: two events move to another room at the same time;
    # the one on a frozen day is flagged, the one on an open day is not.
    broken = venues.copy()
    broken.loc[broken["venue_id"] == "V02", "equipment"] = "projector;microphone"
    after_incident = generate_schedule(programs, broken, baseline.schedule[COLS], **today)
    assert after_incident.summary["freeze_window_dates"] == ["2026-10-17", "2026-10-18"]
    moved = after_incident.changes[after_incident.changes["change_type"] == "moved"].set_index("program_id")
    assert set(moved.index) == {"P04", "P07"}
    assert set(moved["changed_fields"]) == {"venue"}
    assert bool(moved.loc["P04", "in_freeze_window"]) and not bool(moved.loc["P07", "in_freeze_window"])

    # A new request asking for a frozen day lands outside the freeze window.
    request = {c: "" for c in programs.columns}
    request.update(program_id="U01", program_name="new", category="ورشة برمجة", admission="open",
                   duration_min="90", attendance_value="30", venue_requirements="projector;computers",
                   time_type="flexible", preferred_dates="2026-10-17")
    with_request = pd.concat([programs, pd.DataFrame([request])], ignore_index=True)
    result = generate_schedule(with_request, broken, after_incident.schedule[COLS], **today)
    placed = result.schedule.set_index("program_id").loc["U01"]
    assert placed["date"] not in {"2026-10-17", "2026-10-18"}
