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


# ---------------------------------------------------------------- the three roles

def test_owner_request_is_recorded_under_the_owner(client):
    body = flexible(owner="حاضنة ريادة الأعمال")
    res = client.post("/api/programs", json=body).json()
    p = next(x for x in res["state"]["programs"] if x["id"] == res["program_id"])
    assert p["owner"] == "حاضنة ريادة الأعمال"
    assert "حاضنة ريادة الأعمال" in res["state"]["owners"]


def test_organizer_edit_keeps_the_owner(client):
    client.put("/api/programs/P07", json=flexible(name="جلسة ريادة الأعمال", attendance=80))
    s = client.get("/api/state").json()
    assert next(p for p in s["programs"] if p["id"] == "P07")["owner"] == "حاضنة ريادة الأعمال"


def test_report_preview_changes_nothing(client):
    before = client.get("/api/state").json()["schedule"]
    pv = client.post("/api/reports/preview", json={"venue_id": "V03", "kind": "equipment", "equipment": "microphone"}).json()
    assert pv["ok"] and pv["title"] == "عطل ميكروفون في قاعة المؤتمرات B"
    assert "جلسة ريادة الأعمال" in [a["name"] for a in pv["affected"]]
    assert client.get("/api/state").json()["schedule"] == before


def test_report_moves_events_and_explains_why(client):
    r = client.post("/api/reports", json={"venue_id": "V03", "kind": "equipment", "equipment": "microphone"}).json()
    assert r["report"]["status"] == "open" and r["report"]["affected"]
    s = r["state"]
    assert not any(x["venue_id"] == "V03" and x["program_id"] in ("P07", "P16", "P18") for x in s["schedule"])
    moved = next(c for c in s["changes"] if c["program_id"] == "P07")
    assert moved["type"] == "moved" and "بسبب عطل ميكروفون" in moved["message"]
    assert moved["owner"] == "حاضنة ريادة الأعمال"


def test_report_rejects_equipment_the_venue_does_not_have(client):
    res = client.post("/api/reports", json={"venue_id": "V03", "kind": "equipment", "equipment": "stage"})
    assert res.status_code == 400


def test_approval_notifies_owners_and_venue_supervisor(client):
    client.post("/api/reports", json={"venue_id": "V03", "kind": "equipment", "equipment": "microphone"})
    s = client.post("/api/approve").json()["state"]
    assert s["reports"][0]["status"] == "approved"
    venue_notes = [n for n in s["notifications"] if n["to"] == "venue"]
    assert len(venue_notes) == 1 and "اعتمد فريق البرامج" in venue_notes[0]["text"]
    owner_notes = [n for n in s["notifications"] if n["to"] == "owner" and n["owner"] == "حاضنة ريادة الأعمال"]
    assert any("جلسة ريادة الأعمال" in n["text"] for n in owner_notes)


def test_resolving_a_report_restores_the_venue(client):
    client.post("/api/reports", json={"venue_id": "V03", "kind": "equipment", "equipment": "microphone"})
    s = client.post("/api/reports/R1/resolve").json()["state"]
    v3 = next(v for v in s["venues"] if v["id"] == "V03")
    assert "microphone" in v3["equipment"] and s["reports"][0]["status"] == "resolved"


def test_closing_a_venue_with_fixed_events_needs_the_organizer(client):
    r = client.post("/api/reports", json={"venue_id": "V01", "kind": "closed"}).json()
    assert r["report"]["errors"]  # fixed events there cannot move on their own
    assert r["state"]["summary"]["can_approve"] is False
    s = client.post("/api/reports/R1/resolve").json()["state"]
    assert s["summary"]["can_approve"] is True


def test_role_pages_are_served(client):
    for path in ("/", "/owner", "/venue"):
        assert client.get(path).status_code == 200


# ---------------------------------------------------------------- owner requests wait for the organizer

def request_body(**extra):
    body = {"name": "ورشة الواقع المعزز", "owner": "أكاديمية التقنية", "category": "ورشة عمل",
            "description": "تطبيق عملي على بناء تجربة واقع معزز بسيطة.", "duration": 60, "attendance": 25,
            "admission": "registration", "audience": ["طلاب"], "field": ["تقنية", "ابتكار"],
            "equipment": ["projector"], "time_type": "flexible", "preferred_dates": ["2026-10-19"],
            "preferred_slots": ["09:00-12:00", "12:00-15:00"]}
    body.update(extra)
    return body


def test_owner_request_waits_outside_the_schedule(client):
    r = client.post("/api/requests", json=request_body()).json()
    s = r["state"]
    rid = r["request_id"]
    assert rid not in {p["id"] for p in s["programs"]} and s["summary"]["total"] == 18
    req = next(x for x in s["requests"] if x["id"] == rid)
    assert req["status"] == "pending" and req["owner"] == "أكاديمية التقنية"
    assert req["preview"]["ok"] and req["preview"]["placement"]["date"] == "2026-10-19"
    assert req["program"]["fields"] == ["تقنية", "ابتكار"] and req["program"]["preferred_slots"] == ["09:00-12:00", "12:00-15:00"]


def test_owner_request_needs_every_required_field(client):
    res = client.post("/api/requests", json=request_body(category="", description=" ", audience=[], field=[]))
    assert res.status_code == 422
    msg = res.json()["detail"]["message"]
    for name in ("التصنيف", "الوصف", "الجمهور المستهدف", "مجال الفعالية"):
        assert name in msg
    res = client.post("/api/requests", json=request_body(time_type="fixed", fixed_date="2026-10-19"))
    assert res.status_code == 422 and "تاريخ الفعالية ووقتها وقاعتها" in res.json()["detail"]["message"]


def test_accepting_a_request_schedules_it_and_tells_the_owner(client):
    rid = client.post("/api/requests", json=request_body()).json()["request_id"]
    s = client.post(f"/api/requests/{rid}/accept").json()["state"]
    p = next(p for p in s["programs"] if p["id"] == rid)
    assert p["owner"] == "أكاديمية التقنية" and p["category"] == "ورشة عمل" and p["description"]
    assert rid in {x["program_id"] for x in s["schedule"]}
    assert next(c for c in s["changes"] if c["program_id"] == rid)["type"] == "new"
    note = s["notifications"][-1]
    assert note["owner"] == "أكاديمية التقنية" and note["title"] == "قُبل طلبك"
    assert client.post(f"/api/requests/{rid}/accept").status_code == 404  # decided once


def test_rejecting_a_request_sends_the_reason(client):
    rid = client.post("/api/requests", json=request_body()).json()["request_id"]
    s = client.post(f"/api/requests/{rid}/reject", json={"note": "خارج نطاق المعرض"}).json()["state"]
    req = next(x for x in s["requests"] if x["id"] == rid)
    assert req["status"] == "rejected" and req["note"] == "خارج نطاق المعرض"
    assert rid not in {p["id"] for p in s["programs"]}
    assert "خارج نطاق المعرض" in s["notifications"][-1]["text"]


def test_owner_can_withdraw_a_pending_request(client):
    rid = client.post("/api/requests", json=request_body()).json()["request_id"]
    s = client.delete(f"/api/requests/{rid}").json()["state"]
    assert rid not in {x["id"] for x in s["requests"]}
    second = client.post("/api/requests", json=request_body()).json()["request_id"]
    assert second not in {p["id"] for p in client.get("/api/state").json()["programs"]}


def test_fixed_request_on_a_taken_slot_is_refused(client):
    res = client.post("/api/requests", json=request_body(
        time_type="fixed", fixed_date="2026-10-19", fixed_start="16:00", fixed_venue="V01", attendance=100))
    assert res.status_code == 422  # the closing ceremony is fixed there
