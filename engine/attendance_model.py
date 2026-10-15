"""Attendance forecasting: a linear regression trained on past editions.

What it predicts
    For an open (walk-in) event, the expected increase over the owner's own
    estimate:  increase = actual / expected - 1   (0.30 means 30% more people).

What it learns from
    data/attendance_history.csv, one row per past event:
    edition, program_name, field, audience, admission, duration_min,
    expected_attendance, actual_attendance

Features
    field (المجال), audience (الفئة المستهدفة), and their combination. An event
    may have several domains or audiences ("تقنية;ابتكار"), so each group is
    multi-hot encoded and averaged: one domain gets weight 1, two domains get
    1/2 each. A one-domain, one-audience event is plain one-hot encoding. The
    combination columns (every domain × audience pair) are what let the model
    learn "entrepreneurship for students overflows" even when neither
    entrepreneurship nor students does on its own.

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

from .config import ADMISSION_ALIASES, ADMISSION_OPEN
from .data import is_blank, normalize_item, parse_int, split_list, text

HISTORY_COLUMNS = ("edition", "field", "audience", "expected_attendance", "actual_attendance")
ALPHA = 1.0
PART_LABELS = {"field": "المجال", "audience": "الفئة المستهدفة", "combo": "المزيج بينهما"}


def admission_of(record) -> str:
    """open unless the row says registration; unknown or empty values count as open."""
    value = record.get("admission") if hasattr(record, "get") else None
    if value is None or is_blank(value):
        return ADMISSION_OPEN
    return ADMISSION_ALIASES.get(normalize_item(text(value)), ADMISSION_OPEN)


def values(cell) -> list[str]:
    """'تقنية;ابتكار' -> ['تقنية', 'ابتكار'], keeping order and dropping repeats."""
    if isinstance(cell, (list, tuple)):
        items = [text(x) for x in cell]
    else:
        items = split_list(cell) if not is_blank(cell) else []
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def label(fields, audiences) -> str:
    return f"{'، '.join(fields)} × {'، '.join(audiences)}"


class Encoder:
    """Averaged multi-hot encoding of domains, audiences and their pairs."""

    def __init__(self, rows):
        self.vocab = {"field": [], "audience": [], "combo": []}
        for fields, audiences in rows:
            for key, items in (("field", fields), ("audience", audiences),
                               ("combo", [(f, a) for f in fields for a in audiences])):
                for item in items:
                    if item not in self.vocab[key]:
                        self.vocab[key].append(item)
        self.offset, n = {}, 0
        for key in ("field", "audience", "combo"):
            self.offset[key] = n
            n += len(self.vocab[key])
        self.index = {key: {v: i for i, v in enumerate(self.vocab[key])} for key in self.vocab}
        self.width = n

    def known(self, fields, audiences):
        return ([f for f in fields if f in self.index["field"]],
                [a for a in audiences if a in self.index["audience"]])

    def row(self, fields, audiences) -> np.ndarray:
        x = np.zeros(self.width)
        pairs = [(f, a) for f in fields for a in audiences]
        for key, items in (("field", fields), ("audience", audiences), ("combo", pairs)):
            hits = [self.index[key][i] for i in items if i in self.index[key]]
            for h in hits:
                x[self.offset[key] + h] += 1 / len(items)
        return x

    def matrix(self, rows) -> np.ndarray:
        return np.array([self.row(f, a) for f, a in rows]) if rows else np.zeros((0, self.width))


def training_rows(history: pd.DataFrame) -> tuple[list[dict], int]:
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
        fields, audiences = values(r["field"]), values(r["audience"])
        if not expected or expected <= 0 or actual is None or actual < 0 or not fields or not audiences:
            continue
        rows.append({"edition": text(r["edition"]), "fields": fields, "audiences": audiences,
                     "expected": expected, "actual": actual, "increase": actual / expected - 1})
    return rows, excluded


def _fit(rows: list[dict], alpha: float):
    pairs = [(r["fields"], r["audiences"]) for r in rows]
    encoder = Encoder(pairs)
    model = Ridge(alpha=alpha).fit(encoder.matrix(pairs), np.array([r["increase"] for r in rows]))
    return encoder, model


@dataclass
class Forecast:
    increase: float          # 0.30 = 30% more than expected
    predicted: int           # expected * (1 + increase), rounded up
    parts: list[dict]        # [{"label", "points"}], sums to the increase in percentage points
    evidence: dict           # past events sharing a domain × audience pair
    combo: str               # readable "domains × audiences"


@dataclass
class AttendanceModel:
    encoder: Encoder
    regressor: Ridge
    rows: list[dict]
    card: dict = dc_field(default_factory=dict)

    @property
    def fields(self) -> list[str]:
        return sorted(self.encoder.vocab["field"])

    @property
    def audiences(self) -> list[str]:
        return sorted(self.encoder.vocab["audience"])

    def knows(self, fields, audiences) -> bool:
        f, a = self.encoder.known(values(fields), values(audiences))
        return bool(f) and bool(a)

    def increase(self, fields, audiences) -> float:
        f, a = self.encoder.known(values(fields), values(audiences))
        return float(self.regressor.predict(self.encoder.row(f, a)[None, :])[0])

    def explain(self, fields, audiences) -> list[dict]:
        """The prediction split into baseline + domain + audience + combination, in points."""
        f, a = self.encoder.known(values(fields), values(audiences))
        x, coef = self.encoder.row(f, a), self.regressor.coef_
        parts = [{"label": "متوسط الدورات السابقة", "points": round(100 * float(self.regressor.intercept_), 1)}]
        for key in ("field", "audience", "combo"):
            lo = self.encoder.offset[key]
            hi = lo + len(self.encoder.vocab[key])
            parts.append({"label": PART_LABELS[key], "points": round(100 * float(np.dot(coef[lo:hi], x[lo:hi])), 1)})
        return parts

    def evidence(self, fields, audiences) -> dict:
        pairs = {(f, a) for f in fields for a in audiences}
        hits = [r for r in self.rows if pairs & {(f, a) for f in r["fields"] for a in r["audiences"]}]
        return {"events": len(hits), "above": sum(r["actual"] > r["expected"] for r in hits),
                "mean_increase": round(float(np.mean([r["increase"] for r in hits])), 3) if hits else None}

    def forecast(self, record) -> Forecast | None:
        """None for registration events, unknown domain/audience, or a missing estimate."""
        if admission_of(record) != ADMISSION_OPEN:
            return None
        f, a = self.encoder.known(values(record.get("field", "")), values(record.get("audience", "")))
        expected = parse_int(record.get("attendance_value", record.get("expected_attendance")))
        if not expected or not f or not a:
            return None
        inc = self.increase(f, a)
        return Forecast(increase=inc, predicted=math.ceil(expected * (1 + inc) - 1e-9),
                        parts=self.explain(f, a), evidence=self.evidence(f, a), combo=label(f, a))


def train(history: pd.DataFrame, alpha: float = ALPHA) -> AttendanceModel:
    rows, excluded = training_rows(history)
    if len(rows) < 5:
        raise ValueError("attendance_history.csv: أقل من 5 فعاليات حضور عام صالحة للتدريب.")

    # honest score: hold out the latest edition
    editions = sorted({r["edition"] for r in rows})
    test = None
    if len(editions) >= 2:
        held_out = editions[-1]
        train_part = [r for r in rows if r["edition"] != held_out]
        test_part = [r for r in rows if r["edition"] == held_out]
        enc, reg = _fit(train_part, alpha)
        pred = reg.predict(enc.matrix([(r["fields"], r["audiences"]) for r in test_part]))
        truth = np.array([r["increase"] for r in test_part])
        test = {"edition": held_out, "events": len(test_part),
                "mae_points": round(100 * mean_absolute_error(truth, pred), 1),
                "baseline_mae_points": round(100 * mean_absolute_error(truth, np.zeros_like(truth)), 1),
                "r2": round(float(r2_score(truth, pred)), 2)}

    encoder, regressor = _fit(rows, alpha)
    card = {"algorithm": "Linear Regression (Ridge)", "features": ["المجال", "الفئة المستهدفة", "المزيج بينهما"],
            "trained_events": len(rows), "excluded_registration": int(excluded),
            "editions": editions, "test": test}
    return AttendanceModel(encoder=encoder, regressor=regressor, rows=rows, card=card)


def load(path) -> AttendanceModel | None:
    """Train from a history file; None when the file does not exist."""
    from .storage import read_csv

    path = Path(path)
    if not path.exists():
        return None
    return train(read_csv(path))
