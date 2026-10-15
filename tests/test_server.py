"""The organizer interface's API: every answer must come from the real engine."""

import pytest
from fastapi.testclient import TestClient

from server import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(runtime_dir=tmp_path / "runtime", reference_date="2026-10-15", freeze_days=2)
    return TestClient(app)


def flexible(name="ورشة اختبار", **extra):
    body = {"name": name, "duration": 60, "attendance": 25, "equipment": ["projector"],
            "time_type": "flexible", "preferred_dates": ["2026-10-19"], "preferred_slot": ""}
    body.update(extra)
    return body


def test_state_matches_the_engine_on_the_sample_data(client):
    s = client.get("/api/state").json()
    assert s["summary"]["scheduled"] == 15 and s["summary"]["total"] == 18
    assert s["summary"]["conflicts"] == 0
    assert {u["program_id"] for u in s["unscheduled"]} == {"P10", "P12", "P13"}
    assert [d["frozen"] for d in s["days"]] == [True, False, False]
    assert len(s["changes"]) == 13  # 9 new, 3 not scheduled, 1 removed (P20)


def test_inbox_suggests_a_runnable_what_if(client):
    s = client.get("/api/state").json()
    fixes = {u["program_id"]: u["fix"] for u in s["unscheduled"]}
    assert fixes["P10"]["kind"] == "open_venue" and fixes["P10"]["venue_id"] == "V06"
    assert fixes["P13"] == {"kind": "attendance", "program_id": "P13", "value": 500, "label": "جرّب حضورًا أقل"}
    result = client.post("/api/whatif", json=fixes["P13"]).json()
    assert result["ok"] and result["compare"]["scheduled"] == [15, 16]


def test_live_check_finds_a_slot_without_saving(client):
    res = client.post("/api/check", json={"program": flexible()}).json()
    assert res["ok"] and res["placement"]["date"] == "2026-10-19"
    assert client.get("/api/state").json()["summary"]["total"] == 18


def test_live_check_reports_fixed_conflicts_with_setup_time(client):
    body = flexible(time_type="fixed", fixed_date="2026-10-17", fixed_start="10:00", fixed_venue="V01")
    res = client.post("/api/check", json={"program": body}).json()
    assert not res["ok"] and any("التجهيز" in e for e in res["errors"])


def test_saving_an_invalid_event_is_refused_and_changes_nothing(client):
    body = flexible(time_type="fixed", fixed_date="2026-10-17", fixed_start="10:00", fixed_venue="V01")
    res = client.post("/api/programs", json=body)
    assert res.status_code == 422 and res.json()["detail"]["errors"]
    assert client.get("/api/state").json()["summary"]["total"] == 18


def test_add_edit_delete_round_trip(client):
    added = client.post("/api/programs", json=flexible()).json()
    pid = added["program_id"]
    assert pid == "P21"  # P20 still exists in the approved schedule
    assert added["state"]["summary"]["scheduled"] == 16

    edited = client.put(f"/api/programs/{pid}", json=flexible(attendance=600)).json()
    assert pid in {u["program_id"] for u in edited["state"]["unscheduled"]}

    removed = client.delete(f"/api/programs/{pid}").json()
    assert pid not in {p["id"] for p in removed["state"]["programs"]}


def test_deleting_an_approved_event_is_reported_as_removed(client):
    s = client.delete("/api/programs/P14").json()["state"]
    assert any(c["program_id"] == "P14" and c["type"] == "removed" for c in s["changes"])


def test_locked_event_stays_put_when_its_room_closes(client):
    s = client.get("/api/state").json()
    slot = next(r for r in s["schedule"] if r["program_id"] == "P16")
    client.post("/api/programs/P16/lock", json={"locked": True})
    # Reopening V06 reshuffles new events (P16 moved there when unlocked); locked, it must stay.
    result = client.post("/api/whatif", json={"kind": "open_venue", "venue_id": "V06"}).json()
    after = next(r for r in result["schedule"] if r["program_id"] == "P16")
    assert (after["date"], after["start"], after["venue_id"]) == (slot["date"], slot["start"], slot["venue_id"])


def test_what_if_never_changes_the_proposal(client):
    before = client.get("/api/state").json()
    result = client.post("/api/whatif", json={"kind": "close_venue", "venue_id": "V03"}).json()
    assert result["ok"] and result["compare"]["approved_moved"] == 1
    assert result["compare"]["approved_moved_frozen"] == 1
    assert client.get("/api/state").json()["schedule"] == before["schedule"]


def test_what_if_on_a_room_with_fixed_events_is_explained(client):
    result = client.post("/api/whatif", json={"kind": "close_venue", "venue_id": "V01"}).json()
    assert not result["ok"] and len(result["notes"]) == 3  # P01, P02, P04 are fixed there


def test_extra_hours_or_day_do_not_help_this_data(client):
    for body in ({"kind": "hours", "day_end": "20:00"}, {"kind": "add_day"}):
        result = client.post("/api/whatif", json=body).json()
        assert result["ok"] and result["compare"]["scheduled"] == [15, 15]
    assert len(client.post("/api/whatif", json={"kind": "add_day"}).json()["days"]) == 4


def test_apply_what_if_then_approve(client):
    applied = client.post("/api/whatif/apply", json={"kind": "open_venue", "venue_id": "V06"}).json()["state"]
    assert applied["summary"]["scheduled"] == 16
    approved = client.post("/api/approve").json()
    assert approved["sent"] == 13  # 10 new + 2 not scheduled + 1 removed (P20)
    state = approved["state"]
    assert state["changes"] == []
    assert set(state["approved"]) == {r["program_id"] for r in state["schedule"]}


def test_downloads(client):
    csv = client.get("/api/download/schedule.csv")
    assert csv.status_code == 200 and csv.content.startswith("﻿".encode())
    assert "حفل الافتتاح" in csv.content.decode("utf-8-sig")
    page = client.get("/print/venues").text
    assert page.count("<section>") == 6


def test_runtime_folder_without_marker_is_never_wiped(tmp_path):
    folder = tmp_path / "important"
    folder.mkdir()
    (folder / "keep.txt").write_text("x")
    with pytest.raises(RuntimeError):
        create_app(runtime_dir=folder)
    assert (folder / "keep.txt").exists()
