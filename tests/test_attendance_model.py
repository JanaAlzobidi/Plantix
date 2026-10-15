"""The attendance forecast: a linear regression on past editions, open events only."""

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from engine import attendance_model
from engine.storage import read_csv
from server import create_app

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def model():
    return attendance_model.load(DATA / "attendance_history.csv")


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(runtime_dir=tmp_path / "runtime", reference_date="2026-10-15", freeze_days=2))


def history(rows):
    cols = ["edition", "field", "audience", "admission", "expected_attendance", "actual_attendance"]
    return pd.DataFrame([dict(zip(cols, map(str, r))) for r in rows])


# ---------------------------------------------------------------- the model

def test_registration_rows_are_left_out_of_training():
    rows = [("2024", "تقنية", "طلاب", "open", 100, 140)] * 4 + [("2025", "تقنية", "طلاب", "open", 100, 140)] * 2 \
        + [("2024", "تقنية", "طلاب", "registration", 100, 20)] * 6
    m = attendance_model.train(history(rows))
    assert m.card["trained_events"] == 6 and m.card["excluded_registration"] == 6
    assert m.increase("تقنية", "طلاب") == pytest.approx(0.40, abs=0.02)  # the 20% registration rows did not pull it down


def test_registration_events_get_no_forecast(model):
    record = {"field": "تقنية", "audience": "طلاب", "admission": "registration", "attendance_value": "40"}
    assert model.forecast(record) is None
    assert model.forecast(dict(record, admission="open")) is not None
    assert model.forecast(dict(record, admission="")) is not None  # empty admission means open


def test_unknown_field_or_audience_gets_no_forecast(model):
    assert model.forecast({"field": "طبخ", "audience": "طلاب", "attendance_value": "40"}) is None
    assert model.forecast({"field": "", "audience": "", "attendance_value": "40"}) is None


def test_model_learns_the_combination_not_just_the_parts(model):
    # entrepreneurship overflows with students, but not with investors
    assert model.increase("ريادة أعمال", "طلاب") > 0.40
    assert model.increase("ريادة أعمال", "مستثمرون") < 0.05
    assert model.increase("إعلام", "إعلاميون") < -0.10  # it predicts drops too


def test_explanation_adds_up_to_the_prediction(model):
    parts = model.explain("تقنية", "طلاب")
    assert [p["label"] for p in parts] == ["متوسط الدورات السابقة", "المجال", "الفئة المستهدفة", "المزيج بينهما"]
    assert sum(p["points"] for p in parts) == pytest.approx(100 * model.increase("تقنية", "طلاب"), abs=0.3)


def test_model_beats_trusting_the_owner_on_the_held_out_edition(model):
    test = model.card["test"]
    assert test["edition"] == "2025"
    assert test["mae_points"] < test["baseline_mae_points"] / 2
    assert test["r2"] > 0.6


def test_history_file_matches_the_generator(tmp_path, monkeypatch):
    import scripts.make_history as gen
    monkeypatch.setattr(gen, "OUT", tmp_path / "h.csv")
    gen.main()
    assert read_csv(tmp_path / "h.csv").equals(read_csv(DATA / "attendance_history.csv"))


# ---------------------------------------------------------------- organizer alerts

def test_alerts_flag_open_events_that_outgrow_their_room(client):
    fc = client.get("/api/state").json()["forecast"]
    assert fc["enabled"] and fc["card"]["algorithm"].startswith("Linear Regression")
    alerts = {a["program_id"]: a for a in fc["alerts"]}
    assert set(alerts) == {"P07", "P14"}
    a = alerts["P07"]
    assert (a["expected"], a["predicted"], a["capacity"]) == (80, 122, 120)
    assert a["can_apply"] and a["bigger_venues"] == ["القاعة الكبرى"]
    assert "زيادة 52٪" in a["message"] and "ريادة أعمال × طلاب" in a["evidence"]


def test_registration_events_never_alert_even_when_full(client):
    s = client.get("/api/state").json()
    reg = {p["id"] for p in s["programs"] if p["admission"] == "registration"}
    assert reg and all(p["forecast"] is None for p in s["programs"] if p["id"] in reg)
    assert not reg & {a["program_id"] for a in s["forecast"]["alerts"]}


def test_accepting_an_alert_moves_the_event_and_explains_why(client):
    r = client.post("/api/alerts/P07/accept").json()
    assert r["moved"] and r["venue_name"] == "القاعة الكبرى"
    s = r["state"]
    p07 = next(p for p in s["programs"] if p["id"] == "P07")
    assert p07["attendance"] == 122 and p07["forecast"]["applied"] and p07["forecast"]["original"] == 80
    assert "P07" not in {a["program_id"] for a in s["forecast"]["alerts"]}
    change = next(c for c in s["changes"] if c["program_id"] == "P07")
    assert change["type"] == "moved" and "لاستيعاب زيادة الحضور المتوقعة" in change["message"]


def test_ignoring_an_alert_changes_nothing(client):
    before = client.get("/api/state").json()
    s = client.post("/api/alerts/P14/dismiss").json()["state"]
    assert "P14" not in {a["program_id"] for a in s["forecast"]["alerts"]}
    assert s["schedule"] == before["schedule"]
    assert client.post("/api/alerts/P14/accept").status_code == 404


def test_new_owner_request_gets_a_forecast_in_the_live_check(client):
    body = {"name": "جلسة الطلاب", "duration": 60, "attendance": 100, "equipment": ["projector", "microphone"],
            "field": "ريادة أعمال", "audience": "طلاب", "owner": "حاضنة ريادة الأعمال"}
    fc = client.post("/api/check", json={"program": body}).json()["forecast"]
    assert fc["status"] == "ok" and fc["predicted"] > 140 and fc["over"]
    fc = client.post("/api/check", json={"program": dict(body, admission="registration")}).json()["forecast"]
    assert fc == {"status": "registration"}
    pid = client.post("/api/programs", json=body).json()["program_id"]
    s = client.get("/api/state").json()
    assert next(p for p in s["programs"] if p["id"] == pid)["fields"] == ["ريادة أعمال"]


def test_server_runs_without_a_history_file(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    for name in ("programs.csv", "venues.csv", "approved_schedule.csv"):
        (data / name).write_bytes((DATA / name).read_bytes())
    s = TestClient(create_app(data_dir=data, runtime_dir=tmp_path / "rt")).get("/api/state").json()
    assert s["forecast"]["enabled"] is False and s["forecast"]["alerts"] == []
    assert s["summary"]["scheduled"] == 15
