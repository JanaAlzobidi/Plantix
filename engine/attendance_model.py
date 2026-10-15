"""Attendance forecasting: a linear regression trained on past editions.

What it predicts
    For an open (walk-in) event, the expected increase over the owner's own
    estimate:  increase = actual / expected - 1   (0.30 means 30% more people).

What it learns from
    data/attendance_history.csv, one row per past event:
    edition, program_name, field, audience, admission, duration_min,
    expected_attendance, actual_attendance

Features
    field (المجال), audience (الفئة المستهدفة), and their combination, all
    one-hot encoded. The combination column is what lets the model learn
    "entrepreneurship for students overflows" even when neither entrepreneurship
    nor students does on its own.

Model
    scikit-learn Ridge: ordinary least squares with a small L2 penalty, so a
    combination seen only twice is pulled toward the field + audience estimate
    instead of trusting two events blindly. Every prediction is the sum of
    readable parts (baseline + field + audience + combination), which is how
    the organizer's alert explains itself.

Registration events
    Their count is the number of registered seats, not an estimate, so they are
    left out of training and never get a forecast.

Honest evaluation
    Before the final fit, the model is trained on every edition except the
    latest and scored on the latest one. The error is reported next to the
    error of simply trusting the owner's estimate (predicting 0% change).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.preprocessing import OneHotEncoder

from .config import ADMISSION_ALIASES, ADMISSION_OPEN
from .data import is_blank, normalize_item, parse_int, text

HISTORY_COLUMNS = ("edition", "field", "audience", "expected_attendance", "actual_attendance")
FEATURES = ("field", "audience", "combo")
ALPHA = 1.0


def admission_of(record) -> str:
    """open unless the row says registration; unknown or empty values count as open."""
    value = record.get("admission") if hasattr(record, "get") else None
    if value is None or is_blank(value):
        return ADMISSION_OPEN
    return ADMISSION_ALIASES.get(normalize_item(text(value)), ADMISSION_OPEN)


def _combo(field: str, audience: str) -> str:
    return f"{field} × {audience}"


def _frame(fields, audiences) -> pd.DataFrame:
    fields, audiences = list(fields), list(audiences)
    return pd.DataFrame({"field": fields, "audience": audiences,
                         "combo": [_combo(f, a) for f, a in zip(fields, audiences)]})


def training_rows(history: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Open events with usable numbers, and how many registration rows were left out."""
    missing = [c for c in HISTORY_COLUMNS if c not in history.columns]
    if missing:
        raise ValueError(f"attendance_history.csv: أعمدة ناقصة: {', '.join(missing)}.")
    rows, excluded = [], 0
    for r in history.to_dict("records"):
        if admission_of(r) != ADMISSION_OPEN:
            excluded += 1
            continue
        expected, actual = parse_int(r["expected_attendance"]), parse_int(r["actual_attendance"])
        f, a = text(r["field"]), text(r["audience"])
        if not expected or expected <= 0 or actual is None or actual < 0 or not f or not a:
            continue
        rows.append({"edition": text(r["edition"]), "field": f, "audience": a,
                     "expected": expected, "actual": actual, "increase": actual / expected - 1})
    return pd.DataFrame(rows, columns=["edition", "field", "audience", "expected", "actual", "increase"]), excluded


def _fit(rows: pd.DataFrame, alpha: float):
    encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    X = encoder.fit_transform(_frame(rows["field"], rows["audience"]))
    model = Ridge(alpha=alpha).fit(X, rows["increase"].to_numpy())
    return encoder, model


@dataclass
class Forecast:
    increase: float          # 0.30 = 30% more than expected
    predicted: int           # expected * (1 + increase), rounded up
    parts: list[dict]        # [{"label", "points"}], sums to the increase in percentage points
    evidence: dict           # past events with the same field and audience


@dataclass
class AttendanceModel:
    encoder: OneHotEncoder
    regressor: Ridge
    fields: list[str]
    audiences: list[str]
    combos: dict[str, dict]  # combo -> {"events", "mean_increase", "above"}
    card: dict = dc_field(default_factory=dict)

    def knows(self, field_: str, audience: str) -> bool:
        return text(field_) in self.fields and text(audience) in self.audiences

    def increase(self, field_: str, audience: str) -> float:
        X = self.encoder.transform(_frame([text(field_)], [text(audience)]))
        return float(self.regressor.predict(X)[0])

    def explain(self, field_: str, audience: str) -> list[dict]:
        """The prediction split into baseline + field + audience + combination, in points."""
        X = self.encoder.transform(_frame([text(field_)], [text(audience)]))[0]
        coef = self.regressor.coef_
        labels = {"field": "المجال", "audience": "الفئة المستهدفة", "combo": "المزيج بينهما"}
        parts = [{"label": "متوسط الدورات السابقة", "points": round(100 * float(self.regressor.intercept_), 1)}]
        offset = 0
        for name, cats in zip(FEATURES, self.encoder.categories_):
            width = len(cats)
            points = float(np.dot(coef[offset:offset + width], X[offset:offset + width]))
            parts.append({"label": labels[name], "points": round(100 * points, 1)})
            offset += width
        return parts

    def forecast(self, record) -> Forecast | None:
        """None for registration events, unknown field/audience, or a missing estimate."""
        if admission_of(record) != ADMISSION_OPEN:
            return None
        f, a = text(record.get("field", "")), text(record.get("audience", ""))
        expected = parse_int(record.get("attendance_value", record.get("expected_attendance")))
        if not expected or not self.knows(f, a):
            return None
        inc = self.increase(f, a)
        return Forecast(increase=inc, predicted=math.ceil(expected * (1 + inc) - 1e-9),
                        parts=self.explain(f, a),
                        evidence=self.combos.get(_combo(f, a), {"events": 0, "mean_increase": None, "above": 0}))


def train(history: pd.DataFrame, alpha: float = ALPHA) -> AttendanceModel:
    rows, excluded = training_rows(history)
    if len(rows) < 5:
        raise ValueError("attendance_history.csv: أقل من 5 فعاليات حضور عام صالحة للتدريب.")

    # honest score: hold out the latest edition
    editions = sorted(rows["edition"].unique())
    test = None
    if len(editions) >= 2:
        held_out = editions[-1]
        train_part, test_part = rows[rows["edition"] != held_out], rows[rows["edition"] == held_out]
        enc, reg = _fit(train_part, alpha)
        pred = reg.predict(enc.transform(_frame(test_part["field"], test_part["audience"])))
        truth = test_part["increase"].to_numpy()
        test = {"edition": held_out, "events": int(len(test_part)),
                "mae_points": round(100 * mean_absolute_error(truth, pred), 1),
                "baseline_mae_points": round(100 * mean_absolute_error(truth, np.zeros_like(truth)), 1),
                "r2": round(float(r2_score(truth, pred)), 2)}

    encoder, regressor = _fit(rows, alpha)
    combos = {}
    for (f, a), g in rows.groupby(["field", "audience"]):
        combos[_combo(f, a)] = {"events": int(len(g)), "mean_increase": round(float(g["increase"].mean()), 3),
                                "above": int((g["actual"] > g["expected"]).sum())}
    card = {"algorithm": "Linear Regression (Ridge)", "features": ["المجال", "الفئة المستهدفة", "المزيج بينهما"],
            "trained_events": int(len(rows)), "excluded_registration": int(excluded),
            "editions": editions, "test": test}
    return AttendanceModel(encoder=encoder, regressor=regressor,
                           fields=sorted(rows["field"].unique()), audiences=sorted(rows["audience"].unique()),
                           combos=combos, card=card)


def load(path) -> AttendanceModel | None:
    """Train from a history file; None when the file does not exist."""
    from .storage import read_csv

    path = Path(path)
    if not path.exists():
        return None
    return train(read_csv(path))
