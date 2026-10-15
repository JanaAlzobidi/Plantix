import json
from datetime import date, time

import pandas as pd
import pytest

from engine import ClientConfigError, generate_schedule, load_client
from engine.data import PROGRAM_COLUMNS, VENUE_COLUMNS



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
    programs = pd.DataFrame([
        {**{c: "" for c in PROGRAM_COLUMNS}, "program_id": f"P{i}", "program_name": f"P{i}",
         "duration_min": "90", "attendance_value": "20", "time_type": "flexible"}
        for i in range(6)
    ], columns=PROGRAM_COLUMNS)
    venues = pd.DataFrame([
        {"venue_id": f"V{j}", "venue_name": f"V{j}", "capacity": "50", "equipment": "",
         "min_setup_time_min": "15", "status": "available"} for j in range(2)
    ], columns=VENUE_COLUMNS)
    early = load_client(_write_client(tmp_path / "early", day_start="08:00", day_end="16:00"))
    late = load_client(_write_client(tmp_path / "late", day_start="12:00", day_end="22:00"))
    for client, open_, close in ((early, "08:00", "16:00"), (late, "12:00", "22:00")):
        result = generate_schedule(programs, venues, reference_date="2026-10-01", config=client.config)
        assert len(result.schedule) == 6
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
