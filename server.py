"""Plantix — the program organizer's interface, served on top of the real engine.

    pip install -r requirements.txt
    python server.py                    # opens http://127.0.0.1:8000

Every action in the page (add, edit, delete, lock, live check, what-if,
approve) runs engine.generate_schedule on a working copy of data/ kept in
runtime/. data/ itself is never modified, so restarting the server gives a
clean demo again.
"""

from __future__ import annotations

import argparse
import html
import io
import math
import shutil
import threading
import webbrowser
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import attendance_model
from engine import (
    ApprovalError,
    DataPaths,
    EngineConfig,
    approve_proposal,
    generate_schedule,
    in_freeze_window,
    load_inputs,
    save_proposal,
)
from engine.config import ADMISSION_ALIASES, ADMISSION_OPEN, AVAILABLE_STATUS
from engine.data import normalize_item, parse_int, split_list, text
from engine.storage import read_csv

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
RUNTIME_MARKER = ".plantix-runtime"
HISTORY_FILE = "attendance_history.csv"
# choices offered in the add-event forms; the model adds any value it learned from the history
CATEGORIES = ["ورشة عمل", "محاضرة", "جلسة حوارية", "ندوة", "عرض", "معرض", "لقاء", "مؤتمر صحفي", "حفل", "مسابقة"]
DOMAINS = ["تقنية", "ريادة أعمال", "ابتكار", "تصميم", "إعلام", "مراسم", "تعليم", "استدامة", "صحة", "ثقافة وفنون"]
AUDIENCES = ["طلاب", "مهنيون", "رواد أعمال", "مستثمرون", "الجمهور العام", "إعلاميون", "جهات حكومية", "أطفال وعائلات"]
TIME_SLOTS = ["09:00-12:00", "12:00-15:00", "15:00-18:00"]
ALERT_MIN_INCREASE = 0.15  # alerts start at a predicted 15% over the owner's estimate

DAY_NAMES = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو",
          "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
EQUIPMENT_AR = {
    "projector": "بروجكتر", "microphone": "ميكروفون", "sound system": "نظام صوت", "stage": "منصة",
    "computers": "أجهزة حاسب", "whiteboard": "سبورة", "video conferencing": "اتصال مرئي",
    "3d printer": "طابعة ثلاثية الأبعاد",
}
VENUE_STATUS_AR = {"available": "متاحة", "maintenance": "تحت الصيانة", "unavailable": "مغلقة"}
REASON_LABELS = {
    "CAPACITY": "السعة", "EQUIPMENT": "المعدات", "CAPACITY_AND_EQUIPMENT": "السعة والمعدات",
    "VENUE_UNAVAILABLE": "القاعة غير متاحة", "FREEZE_WINDOW": "نافذة التجميد", "NO_TIME_SLOT": "الوقت",
    "BLOCKED_BY_FIXED": "فعاليات ثابتة", "CONFLICTS": "التعارضات", "SOLVER_TIME_LIMIT": "مهلة الحل",
    "NO_VENUES": "لا توجد قاعات",
}


# ---------------------------------------------------------------- request bodies

class ProgramIn(BaseModel):
    name: str
    duration: int
    attendance: int
    equipment: list[str] = []
    time_type: str = "flexible"
    admission: str = ADMISSION_OPEN
    preferred_dates: list[str] = []
    preferred_slot: str = ""          # one slot (older pages); merged with preferred_slots
    preferred_slots: list[str] = []
    fixed_date: str | None = None
    fixed_start: str | None = None
    fixed_venue: str | None = None
    owner: str | None = None  # the requesting party; None keeps the current owner
    # None keeps the current value on an edit. field and audience may hold several values.
    field: list[str] | str | None = None     # مجال الفعالية
    audience: list[str] | str | None = None  # الجمهور المستهدف
    category: str | None = None              # التصنيف: ورشة عمل، جلسة حوارية…
    description: str | None = None           # الوصف

    def slots(self) -> list[str]:
        out = [x for x in self.preferred_slots if x]
        if self.preferred_slot and self.preferred_slot not in out:
            out.insert(0, self.preferred_slot)
        return out


class DecisionIn(BaseModel):
    note: str = ""


class ReportIn(BaseModel):
    venue_id: str
    kind: str  # equipment | closed
    equipment: str | None = None
    note: str = ""


class CheckIn(BaseModel):
    program_id: str | None = None
    program: ProgramIn


class LockIn(BaseModel):
    locked: bool


class ScenarioIn(BaseModel):
    kind: str  # close_venue | open_venue | attendance | hours | add_day
    venue_id: str | None = None
    program_id: str | None = None
    value: int | None = None
    day_end: str | None = None


# ---------------------------------------------------------------- helpers

def _flag(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return bool(value)


def _to_min(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _day_label(day: date) -> str:
    return f"{DAY_NAMES[day.weekday()]} {day.day}"


def _day_long(day: date) -> str:
    return f"{DAY_NAMES[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"


def _slot_map(result) -> dict[str, tuple[str, str, str]]:
    return {
        row.program_id: (row.date, row.start_time, row.venue_id)
        for row in result.schedule.itertuples()
    }


def _errors(result) -> list[str]:
    issues = result.issues
    if issues.empty:
        return []
    return issues.loc[issues["severity"] == "error", "message"].tolist()


def _conflicts(result) -> int:
    rows = [(r.date, r.venue_id, _to_min(r.start_time), _to_min(r.venue_busy_until))
            for r in result.schedule.itertuples()]
    found = 0
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a[0] == b[0] and a[1] == b[1] and a[2] < b[3] and b[2] < a[3]:
                found += 1
    return found


def _events_noun(n: int) -> str:
    """Arabic counted noun: 3-10 take the plural, everything else the singular."""
    return "فعاليات" if 3 <= n % 100 <= 10 else "فعالية"


def _change_words(pct: int | None, prefix: str = "") -> str:
    """'زيادة 52٪' / 'انخفاض 21٪' — words instead of a sign, which reorders badly in RTL text."""
    if pct is None:
        return ""
    if pct == 0:
        return "دون تغيير"
    return f"{prefix}{'زيادة' if pct > 0 else 'انخفاض'} {abs(pct)}٪"


def _missing_fields(p) -> list[str]:
    """Required fields of an owner request (marked * in the form)."""
    out = []
    if not p.name.strip():
        out.append("اسم الفعالية")
    if not (p.owner or "").strip():
        out.append("الجهة المنظِّمة")
    if not (p.category or "").strip():
        out.append("التصنيف")
    if p.duration < 15:
        out.append("المدة")
    if p.attendance < 1:
        out.append("عدد الحضور")
    if not (p.description or "").strip():
        out.append("الوصف")
    if not attendance_model.values(p.audience or []):
        out.append("الجمهور المستهدف")
    if not attendance_model.values(p.field or []):
        out.append("مجال الفعالية")
    if p.time_type == "fixed" and not (p.fixed_date and p.fixed_start and p.fixed_venue):
        out.append("تاريخ الفعالية ووقتها وقاعتها")
    return out


def _ratio(value: str) -> tuple[int, int]:
    met, total = (value or "0/0").split("/")
    return int(met), int(total)


class Workspace:
    """The organizer's working state: inputs in runtime/, the latest proposal, locks."""

    def __init__(self, data_dir, runtime_dir, reference_date: str, freeze_days: int):
        self.source = Path(data_dir)
        self.runtime = Path(runtime_dir)
        self.reference_date = reference_date
        self.freeze_days = freeze_days
        self.lock = threading.RLock()
        self.model, self.model_error = None, None
        try:
            self.model = attendance_model.load(self.source / HISTORY_FILE)
        except ValueError as exc:
            self.model_error = str(exc)
        self.reset()

    # ---- setup

    def reset(self):
        with self.lock:
            if self.runtime.exists():
                if any(self.runtime.iterdir()) and not (self.runtime / RUNTIME_MARKER).exists():
                    raise RuntimeError(f"{self.runtime} ليس مجلد تشغيل Plantix؛ لن يُمسح.")
                shutil.rmtree(self.runtime)
            self.runtime.mkdir(parents=True)
            (self.runtime / RUNTIME_MARKER).write_text("working copy of data/, safe to delete\n")
            for name in ("programs.csv", "venues.csv", "approved_schedule.csv"):
                if (self.source / name).exists():
                    shutil.copy2(self.source / name, self.runtime / name)
            self.paths = DataPaths.at(self.runtime)
            self.programs, self.venues, self.approved = load_inputs(self.paths)
            if "admission" not in self.programs.columns:
                self.programs["admission"] = ADMISSION_OPEN
            for column in ("owner", "category", "field", "audience", "description"):
                if column not in self.programs.columns:
                    self.programs[column] = ""
            self.config = EngineConfig()
            self.lock_slots: dict[str, tuple[str, str, str]] = {}
            self.notified: set[str] = set()
            self.owner_of: dict[str, str] = dict(zip(self.programs["program_id"], self.programs["owner"]))
            self.reports: list[dict] = []
            self.notifications: list[dict] = []
            self.requests: list[dict] = []   # owner requests waiting for the organizer
            self.version = 0                 # bumps on every recompute; keys the request previews
            self.previews: dict[str, tuple[int, dict]] = {}
            self.alert_decisions: dict[str, dict] = {}   # pid -> {"status", "attendance"}
            self.forecast_applied: dict[str, dict] = {}  # pid -> {"from", "to", "forecast"}
            self.refresh()

    # ---- engine

    def engine_programs(self, df: pd.DataFrame) -> pd.DataFrame:
        """Locked flexible events go to the engine as fixed at their locked slot."""
        df = df.copy()
        for pid, (day, start, venue) in self.lock_slots.items():
            mask = df["program_id"] == pid
            if mask.any():
                df.loc[mask, ["time_type", "fixed_date", "fixed_start_time", "fixed_venue_id"]] = [
                    "fixed", day, start, venue]
        return df

    def run(self, programs: pd.DataFrame, venues: pd.DataFrame, config: EngineConfig):
        return generate_schedule(
            self.engine_programs(programs), venues, self.approved,
            reference_date=self.reference_date, freeze_window_days=self.freeze_days, config=config,
        )

    def refresh(self):
        self.programs.to_csv(self.paths.programs, index=False, encoding="utf-8-sig")
        self.venues.to_csv(self.paths.venues, index=False, encoding="utf-8-sig")
        self.result = self.run(self.programs, self.venues, self.config)
        save_proposal(self.result, self.paths)
        self.version = getattr(self, "version", 0) + 1

    # ---- serialization

    def days_json(self, config: EngineConfig) -> list[dict]:
        ref = date.fromisoformat(self.reference_date)
        return [
            {"date": d.isoformat(), "label": _day_label(d), "long": _day_long(d),
             "frozen": in_freeze_window(d, ref, self.freeze_days)}
            for d in config.horizon_days()
        ]

    def venues_json(self, venues: pd.DataFrame) -> list[dict]:
        out = []
        for r in venues.to_dict("records"):
            status = normalize_item(text(r["status"])) or AVAILABLE_STATUS
            out.append({
                "id": r["venue_id"], "name": r["venue_name"], "capacity": parse_int(r["capacity"]) or 0,
                "equipment": [normalize_item(x) for x in split_list(r["equipment"])],
                "setup": parse_int(r["min_setup_time_min"]) or 0,
                "status": status, "status_label": VENUE_STATUS_AR.get(status, status),
            })
        return out

    def programs_json(self, programs: pd.DataFrame) -> list[dict]:
        out = []
        for r in programs.to_dict("records"):
            pid = r["program_id"]
            fixed = normalize_item(text(r["time_type"])) == "fixed"
            admission = ADMISSION_ALIASES.get(normalize_item(text(r.get("admission", ""))), ADMISSION_OPEN)
            out.append({
                "id": pid, "name": text(r["program_name"]),
                "duration": parse_int(r["duration_min"]) or 0,
                "attendance": parse_int(r["attendance_value"]) or 0,
                "equipment": [normalize_item(x) for x in split_list(r["venue_requirements"])],
                "time_type": "fixed" if fixed else "flexible",
                "admission": admission,
                "preferred_dates": split_list(r["preferred_dates"]),
                "preferred_slots": split_list(r["preferred_time_slots"]),
                "fixed": {"date": text(r["fixed_date"]), "start": text(r["fixed_start_time"]),
                          "venue_id": text(r["fixed_venue_id"])} if fixed else None,
                "locked": pid in self.lock_slots,
                "owner": text(r.get("owner", "")),
                "fields": attendance_model.values(r.get("field", "")),
                "audiences": attendance_model.values(r.get("audience", "")),
                "category": text(r.get("category", "")), "description": text(r.get("description", "")),
                "forecast": self.forecast_json(r),
            })
        return out

    # ---- attendance forecast

    def forecast_json(self, record) -> dict | None:
        """The model's view of one event; for an accepted alert, the forecast it was based on."""
        pid = record.get("program_id")
        applied = self.forecast_applied.get(pid)
        attendance = parse_int(record.get("attendance_value")) or 0
        if applied and applied["to"] == attendance:
            return dict(applied["forecast"], applied=True, original=applied["from"])
        if self.model is None:
            return None
        f = self.model.forecast(record)
        if f is None:
            return None
        ev = f.evidence
        return {"increase_pct": round(100 * f.increase), "predicted": f.predicted, "expected": attendance,
                "parts": f.parts, "evidence": {"events": ev["events"], "above": ev["above"],
                                               "mean_pct": None if ev["mean_increase"] is None else round(100 * ev["mean_increase"])},
                "combo": f.combo,
                "applied": False, "original": None}

    def alerts_json(self, programs_json, venues_json, schedule_json) -> list[dict]:
        """Open events whose predicted crowd outgrows the room they are scheduled in."""
        venues = {v["id"]: v for v in venues_json}
        slots = {s["program_id"]: s for s in schedule_json}
        out = []
        for p in programs_json:
            f = p["forecast"]
            if not f or f["applied"] or f["increase_pct"] < 100 * ALERT_MIN_INCREASE or p["id"] not in slots:
                continue
            decision = self.alert_decisions.get(p["id"])
            if decision and decision["attendance"] == p["attendance"]:
                continue
            venue = venues.get(slots[p["id"]]["venue_id"])
            if venue is None or f["predicted"] <= venue["capacity"]:
                continue
            need = set(p["equipment"])
            bigger = [v["name"] for v in venues_json if v["status"] == AVAILABLE_STATUS
                      and v["capacity"] >= f["predicted"] and need <= set(v["equipment"])]
            if p["time_type"] == "fixed":
                kind, suggestion = "fixed", "موعدها وقاعتها ثابتان: جهّز شاشة عرض خارج القاعة، أو اقترح على صاحبها التسجيل المسبق."
            elif p["locked"]:
                kind, suggestion = "locked", "الموعد مقفل: فُكّ القفل أولًا ليتمكن المحرك من نقلها إلى قاعة أكبر."
            elif not bigger:
                kind, suggestion = "no_room", "لا توجد قاعة متاحة تتسع لهذا العدد: اقترح على صاحبها التسجيل المسبق."
            else:
                kind = "flexible"
                suggestion = (f"إذا قبلت، يصبح الحضور {f['predicted']} ويختار المحرك قاعة تتسع "
                              f"({'، '.join(bigger)}).")
            ev = f["evidence"]
            evidence = (f"في الدورات السابقة: {ev['above']} من أصل {ev['events']} {_events_noun(ev['events'])} بمزيج "
                        f"«{f['combo']}» تجاوزت العدد المتوقع، {_change_words(ev['mean_pct'], 'بمتوسط ')}." if ev["events"] else
                        f"لا توجد فعاليات سابقة بالمزيج «{f['combo']}»؛ التوقع من المجال والفئة كلٌّ على حدة.")
            out.append({
                "program_id": p["id"], "name": p["name"], "kind": kind, "can_apply": kind == "flexible",
                "expected": p["attendance"], "predicted": f["predicted"], "increase_pct": f["increase_pct"],
                "venue_id": venue["id"], "venue_name": venue["name"], "capacity": venue["capacity"],
                "bigger_venues": bigger, "combo": f["combo"], "parts": f["parts"],
                "message": (f"يتوقع النموذج نحو {f['predicted']} شخصًا بدل {p['attendance']} "
                            f"({_change_words(f['increase_pct'])})، و{venue['name']} تتسع لـ{venue['capacity']} فقط."),
                "evidence": evidence, "suggestion": suggestion,
            })
        return out

    def forecast_state(self, world) -> dict:
        return {
            "enabled": self.model is not None, "error": self.model_error,
            "card": self.model.card if self.model else None,
            "fields": self.model.fields if self.model else [],
            "audiences": self.model.audiences if self.model else [],
            "min_increase_pct": round(100 * ALERT_MIN_INCREASE),
            "alerts": self.alerts_json(world["programs"], world["venues"], world["schedule"]),
        }

    # ---- owner requests: wait for the organizer before they enter the schedule

    def submit_request(self, p: ProgramIn) -> dict:
        with self.lock:
            missing = _missing_fields(p)
            if missing:
                raise HTTPException(422, {"message": "أكمل الحقول الإلزامية: " + "، ".join(missing) + ".",
                                          "errors": ["حقل إلزامي: " + m for m in missing]})
            pid = self.next_id()
            check = self.check(pid, p)
            if not check["ok"]:
                raise HTTPException(422, {"message": "لم يُرسل الطلب: فيه مشكلة.", "errors": check["errors"]})
            req = {"id": pid, "status": "pending", "owner": p.owner.strip(), "name": p.name.strip(),
                   "time": datetime.now().strftime("%H:%M"), "note": "", "body": p.model_dump()}
            self.requests.append(req)
            return req

    def find_request(self, rid: str, status: str | None = "pending") -> dict:
        for r in self.requests:
            if r["id"] == rid and (status is None or r["status"] == status):
                return r
        raise HTTPException(404, "لا يوجد طلب بانتظار القرار بهذا الرقم.")

    def preview_request(self, req) -> dict:
        cached = self.previews.get(req["id"])
        if cached and cached[0] == self.version:
            return cached[1]
        check = self.check(req["id"], ProgramIn(**req["body"]))
        self.previews[req["id"]] = (self.version, check)
        return check

    def requests_json(self) -> list[dict]:
        out = []
        for req in self.requests:
            item = {k: v for k, v in req.items() if k != "body"}
            row = self.with_program(req["id"], ProgramIn(**req["body"]))
            item["program"] = self.programs_json(row.loc[row["program_id"] == req["id"]])[0]
            if req["status"] == "pending":
                item["preview"] = self.preview_request(req)
            out.append(item)
        return out

    def accept_request(self, rid: str) -> dict:
        with self.lock:
            req = self.find_request(rid)
            p = ProgramIn(**req["body"])
            df = self.with_program(rid, p)
            result = self.run(df, self.venues, self.config)
            if result.status == "INVALID_DATA":
                raise HTTPException(409, {"message": "لا يمكن قبوله الآن: تعارض مع الجدول الحالي.", "errors": _errors(result)})
            self.programs = df
            self.owner_of[rid] = req["owner"]
            req["status"] = "accepted"
            req["decided_time"] = datetime.now().strftime("%H:%M")
            self.notifications.append({"to": "owner", "owner": req["owner"], "time": req["decided_time"],
                                       "title": "قُبل طلبك", "program_id": rid,
                                       "text": f"قبل فريق البرامج «{req['name']}» وأدخلها في الجدولة، وسيصلك موعدها عند اعتماد الجدول."})
            self.refresh()
            return req

    def reject_request(self, rid: str, note: str) -> dict:
        with self.lock:
            req = self.find_request(rid)
            req["status"] = "rejected"
            req["note"] = " ".join(note.split())
            req["decided_time"] = datetime.now().strftime("%H:%M")
            self.notifications.append({"to": "owner", "owner": req["owner"], "time": req["decided_time"],
                                       "title": "اعتذر فريق البرامج عن طلبك", "program_id": rid,
                                       "text": f"اعتذر فريق البرامج عن «{req['name']}»" + (f": {req['note']}" if req["note"] else ".")})
            return req

    def withdraw_request(self, rid: str):
        with self.lock:
            req = self.find_request(rid)
            self.requests.remove(req)
            self.previews.pop(rid, None)

    def options_json(self) -> dict:
        def merge(base, learned):
            return base + [x for x in sorted(learned) if x not in base]
        return {"categories": merge(CATEGORIES, set(self.programs["category"]) - {""}),
                "domains": merge(DOMAINS, self.model.fields if self.model else []),
                "audiences": merge(AUDIENCES, self.model.audiences if self.model else []),
                "learned_domains": self.model.fields if self.model else [],
                "learned_audiences": self.model.audiences if self.model else [],
                "time_slots": TIME_SLOTS}

    def find_alert(self, pid: str) -> dict:
        world = self.world_json(self.result, self.programs, self.venues, self.config)
        for a in self.alerts_json(world["programs"], world["venues"], world["schedule"]):
            if a["program_id"] == pid:
                return a
        raise HTTPException(404, "لا يوجد تنبيه حضور لهذه الفعالية.")

    def accept_alert(self, pid: str) -> dict:
        with self.lock:
            alert = self.find_alert(pid)
            if not alert["can_apply"]:
                raise HTTPException(400, alert["suggestion"])
            record = self.programs.loc[self.programs["program_id"] == pid].iloc[0].to_dict()
            forecast = self.forecast_json(record)
            df = self.programs.copy()
            df.loc[df["program_id"] == pid, "attendance_value"] = str(alert["predicted"])
            result = self.run(df, self.venues, self.config)
            if result.status == "INVALID_DATA":
                raise HTTPException(422, {"message": "تعذّر تطبيق التوقع.", "errors": _errors(result)})
            before = _slot_map(self.result).get(pid)
            self.programs = df
            self.forecast_applied[pid] = {"from": alert["expected"], "to": alert["predicted"], "forecast": forecast}
            self.alert_decisions[pid] = {"status": "accepted", "attendance": alert["predicted"]}
            self.refresh()
            after = _slot_map(self.result).get(pid)
            vnames = dict(zip(self.venues["venue_id"], self.venues["venue_name"]))
            return {"name": alert["name"], "predicted": alert["predicted"],
                    "moved": before != after, "scheduled": after is not None,
                    "venue_name": vnames.get(after[2], after[2]) if after else None}

    def dismiss_alert(self, pid: str):
        with self.lock:
            alert = self.find_alert(pid)
            self.alert_decisions[pid] = {"status": "dismissed", "attendance": alert["expected"]}

    def forecast_for_check(self, df: pd.DataFrame, pid: str, placement, venues_json) -> dict | None:
        if self.model is None:
            return None
        record = df.loc[df["program_id"] == pid].iloc[0].to_dict()
        if attendance_model.admission_of(record) != ADMISSION_OPEN:
            return {"status": "registration"}
        if not self.model.knows(record.get("field", ""), record.get("audience", "")):
            return {"status": "unknown"}
        f = self.model.forecast(record)
        capacity = None
        if placement:
            capacity = next((v["capacity"] for v in venues_json if v["id"] == placement["venue_id"]), None)
        return {"status": "ok", "increase_pct": round(100 * f.increase), "predicted": f.predicted,
                "capacity": capacity, "over": capacity is not None and f.predicted > capacity
                and f.increase >= ALERT_MIN_INCREASE}

    def schedule_json(self, result) -> list[dict]:
        kinds = dict(zip(result.changes["program_id"], result.changes["change_type"])) if not result.changes.empty else {}
        return [
            {"program_id": r["program_id"], "date": r["date"], "start": r["start_time"], "end": r["end_time"],
             "venue_id": r["venue_id"], "busy_until": r["venue_busy_until"],
             "pref_date_met": _flag(r["preferred_date_met"]), "pref_time_met": _flag(r["preferred_time_met"]),
             "status": kinds.get(r["program_id"], "new")}
            for r in result.schedule.to_dict("records")
        ]

    def unscheduled_json(self, result, programs_json, venues_json) -> list[dict]:
        progs = {p["id"]: p for p in programs_json}
        out = []
        for r in result.unscheduled.to_dict("records"):
            pid, code = r["program_id"], r["reason_code"]
            p = progs.get(pid)
            fix = None
            if p and code == "VENUE_UNAVAILABLE":
                down = [v for v in venues_json if v["status"] != AVAILABLE_STATUS and v["capacity"] >= p["attendance"]
                        and set(p["equipment"]) <= set(v["equipment"])]
                if down:
                    fix = {"kind": "open_venue", "venue_id": down[0]["id"], "label": "جرّب إعادة تشغيل القاعة"}
            elif p and code == "CAPACITY":
                fits = [v["capacity"] for v in venues_json if set(p["equipment"]) <= set(v["equipment"])]
                if fits and p["time_type"] == "flexible":
                    fix = {"kind": "attendance", "program_id": pid, "value": max(fits), "label": "جرّب حضورًا أقل"}
            elif code in ("CONFLICTS", "NO_TIME_SLOT", "FREEZE_WINDOW", "BLOCKED_BY_FIXED"):
                fix = {"kind": "add_day", "label": "جرّب يومًا إضافيًا"}
            out.append({"program_id": pid, "name": r["program_name"], "reason_code": code,
                        "label": REASON_LABELS.get(code, code), "reason": r["reason"],
                        "suggestion": r["suggestion"], "fix": fix})
        return out

    def changes_json(self, result) -> list[dict]:
        """Every pending change, with its owner and the notification text they will get."""
        days = {d["date"]: d for d in self.days_json(self.config)}
        vnames = dict(zip(self.venues["venue_id"], self.venues["venue_name"]))
        ends = dict(zip(result.schedule["program_id"], result.schedule["end_time"])) if not result.schedule.empty else {}
        reasons = dict(zip(result.unscheduled["program_id"], result.unscheduled["reason"])) if not result.unscheduled.empty else {}
        open_reports = {r["venue_id"]: r for r in self.reports if r["status"] == "open"}
        out = []
        for r in result.changes.to_dict("records"):
            kind = r["change_type"]
            pid, name = r["program_id"], r["program_name"]
            if kind == "unchanged" or (kind == "not_scheduled" and pid in self.notified):
                continue

            def point(prefix):
                d = r[f"{prefix}_date"]
                if d is None or (isinstance(d, float) and math.isnan(d)):
                    return None
                return {"date": d, "start": r[f"{prefix}_start_time"], "venue_id": r[f"{prefix}_venue_id"]}

            old, new = point("old"), point("new")
            long = lambda p: days[p["date"]]["long"] if p["date"] in days else p["date"]
            because = ""
            if old and old["venue_id"] in open_reports:
                because = f" بسبب {open_reports[old['venue_id']]['title']}"
            elif pid in self.forecast_applied:
                because = " لاستيعاب زيادة الحضور المتوقعة"
            if kind == "new":
                message = (f"جُدولت «{name}» يوم {long(new)} من {new['start']} إلى {ends.get(pid, '')} "
                           f"في {vnames.get(new['venue_id'], new['venue_id'])}.")
            elif kind == "moved":
                if old["date"] == new["date"] and old["start"] == new["start"]:
                    message = (f"تغيّرت قاعة «{name}» إلى {vnames.get(new['venue_id'], new['venue_id'])} "
                               f"في الموعد نفسه{because}. لا يلزمك أي إجراء.")
                else:
                    message = (f"تغيّر موعد «{name}» إلى {long(new)} {new['start']} "
                               f"في {vnames.get(new['venue_id'], new['venue_id'])}{because}.")
            elif kind == "dropped":
                message = f"تعذّر إبقاء «{name}» في موعدها المعتمد{because}، وسيتواصل معك فريق البرامج لموعد بديل."
            elif kind == "not_scheduled":
                message = f"تعذّرت جدولة «{name}»: {reasons.get(pid, '')}"
            else:
                message = f"أُزيلت «{name}» من الجدول لأنها لم تعد ضمن البرامج."
            out.append({"program_id": pid, "name": name, "type": kind, "old": old, "new": new,
                        "in_freeze": bool(r["in_freeze_window"]), "owner": self.owner_of.get(pid, ""),
                        "message": message})
        return out

    def summary_json(self, result) -> dict:
        s = result.summary
        dm, dt = _ratio(s.get("preferred_date_met"))
        tm, tt = _ratio(s.get("preferred_time_met"))
        return {"status": result.status, "scheduled": s.get("scheduled", 0), "total": s.get("total_programs", 0),
                "date_met": dm, "date_total": dt, "time_met": tm, "time_total": tt,
                "conflicts": _conflicts(result), "solve_seconds": s.get("solve_seconds"),
                "can_approve": result.can_approve}

    def world_json(self, result, programs, venues, config) -> dict:
        p_json, v_json = self.programs_json(programs), self.venues_json(venues)
        return {
            "days": self.days_json(config), "day_start": config.day_start.strftime("%H:%M"),
            "day_end": config.day_end.strftime("%H:%M"),
            "venues": v_json, "programs": p_json, "schedule": self.schedule_json(result),
            "unscheduled": self.unscheduled_json(result, p_json, v_json),
            "summary": self.summary_json(result), "errors": _errors(result),
        }

    def state(self) -> dict:
        with self.lock:
            world = self.world_json(self.result, self.programs, self.venues, self.config)
            approved = {}
            if self.approved is not None:
                for r in self.approved.to_dict("records"):
                    approved[r["program_id"]] = {"date": r["date"], "start": r["start_time"], "venue_id": r["venue_id"]}
            catalog = []
            for item in [e for v in world["venues"] for e in v["equipment"]] + \
                        [e for p in world["programs"] for e in p["equipment"]]:
                if item not in catalog:
                    catalog.append(item)
            owners = sorted({o for o in self.programs["owner"] if text(o)})
            world.update({
                "reference_date": self.reference_date, "freeze_days": self.freeze_days,
                "owners": owners, "reports": self.reports, "requests": self.requests_json(), "notifications": self.notifications,
                "notified": sorted(self.notified),
                "approved": approved, "changes": self.changes_json(self.result),
                "forecast": self.forecast_state(world),
                "options": self.options_json(),
                "equipment": [{"id": e, "label": EQUIPMENT_AR.get(e, e)} for e in catalog],
                "warnings": self.result.issues.loc[self.result.issues["severity"] == "warning", "message"].tolist()
                if not self.result.issues.empty else [],
            })
            return world

    # ---- program edits

    def next_id(self) -> str:
        ids = set(self.programs["program_id"]) | {r["id"] for r in getattr(self, "requests", [])}
        if self.approved is not None:
            ids |= set(self.approved["program_id"])
        top = max([parse_int(i[1:]) or 0 for i in ids if i[:1].upper() == "P"] + [0])
        return f"P{top + 1:02d}"

    def with_program(self, pid: str, p: ProgramIn) -> pd.DataFrame:
        fixed = p.time_type == "fixed"
        row = {
            "program_id": pid, "program_name": p.name.strip(), "duration_min": str(p.duration),
            "attendance_value": str(p.attendance), "venue_requirements": ";".join(p.equipment),
            "time_type": "fixed" if fixed else "flexible",
            "fixed_date": (p.fixed_date or "") if fixed else "",
            "fixed_start_time": (p.fixed_start or "") if fixed else "",
            "fixed_venue_id": (p.fixed_venue or "") if fixed else "",
            "preferred_dates": "" if fixed else ";".join(p.preferred_dates),
            "preferred_time_slots": "" if fixed else ";".join(p.slots()),
            "admission": p.admission or ADMISSION_OPEN,
            "owner": (p.owner.strip() if p.owner is not None else self.owner_of.get(pid, "")),
        }
        for key in ("field", "audience"):
            value = getattr(p, key)
            if value is not None:
                row[key] = ";".join(attendance_model.values(value))
        for key in ("category", "description"):
            value = getattr(p, key)
            if value is not None:
                row[key] = " ".join(value.split())
        df = self.programs.copy()
        for column in row:
            if column not in df.columns:
                df[column] = ""
        hits = df.index[df["program_id"] == pid]
        if len(hits):
            for key, value in row.items():
                df.at[hits[0], key] = value
        else:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True).fillna("")
        return df

    def check(self, pid: str | None, p: ProgramIn) -> dict:
        with self.lock:
            target = pid or self.next_id()
            df = self.with_program(target, p)
            result = self.run(df, self.venues, self.config)
            venues = self.venues_json(self.venues)
            need = {normalize_item(e) for e in p.equipment}
            compatible = [v["name"] for v in venues if v["status"] == AVAILABLE_STATUS
                          and v["capacity"] >= p.attendance and need <= set(v["equipment"])]
            if result.status == "INVALID_DATA":
                return {"ok": False, "errors": _errors(result), "compatible": compatible,
                        "solve_seconds": None}
            before, after = _slot_map(self.result), _slot_map(result)
            names = dict(zip(df["program_id"], df["program_name"]))
            approved = set(self.approved["program_id"]) if self.approved is not None else set()
            others = [k for k in set(before) | set(after) if k != target]
            moved_approved = [names.get(k, k) for k in others if k in approved and before.get(k) != after.get(k)]
            rearranged = sum(1 for k in others if k not in approved and k in before and k in after and before[k] != after[k])
            lost = [names.get(k, k) for k in others if k in before and k not in after]
            placement = None
            if target in after:
                d, s, v = after[target]
                row = result.schedule.loc[result.schedule["program_id"] == target].iloc[0]
                placement = {"date": d, "start": s, "end": row["end_time"], "venue_id": v,
                             "same_as_before": before.get(target) == after[target]}
            reason = None
            if placement is None:
                miss = result.unscheduled.loc[result.unscheduled["program_id"] == target]
                if not miss.empty:
                    reason = {"reason": miss.iloc[0]["reason"], "suggestion": miss.iloc[0]["suggestion"],
                              "label": REASON_LABELS.get(miss.iloc[0]["reason_code"], "")}
            return {"ok": True, "errors": [], "compatible": compatible, "placement": placement,
                    "reason": reason, "moved_approved": moved_approved, "rearranged": rearranged,
                    "lost": lost, "solve_seconds": result.summary.get("solve_seconds"),
                    "forecast": self.forecast_for_check(df, target, placement, venues)}

    def save_program(self, pid: str | None, p: ProgramIn) -> str:
        with self.lock:
            target = pid or self.next_id()
            if pid and pid not in set(self.programs["program_id"]):
                raise HTTPException(404, "الفعالية غير موجودة.")
            df = self.with_program(target, p)
            result = self.run(df, self.venues, self.config)
            if result.status == "INVALID_DATA":
                raise HTTPException(422, {"message": "لم تُحفظ: البيانات فيها مشكلة.", "errors": _errors(result)})
            self.programs = df
            self.owner_of[target] = text(df.loc[df["program_id"] == target, "owner"].iloc[0])
            applied = self.forecast_applied.get(target)
            if applied and applied["to"] != p.attendance:
                self.forecast_applied.pop(target)
            self.notified.discard(target)
            self.refresh()
            return target

    def delete_program(self, pid: str):
        with self.lock:
            if pid not in set(self.programs["program_id"]):
                raise HTTPException(404, "الفعالية غير موجودة.")
            self.programs = self.programs[self.programs["program_id"] != pid].reset_index(drop=True)
            self.lock_slots.pop(pid, None)
            self.alert_decisions.pop(pid, None)
            self.forecast_applied.pop(pid, None)
            self.refresh()

    def set_lock(self, pid: str, locked: bool):
        with self.lock:
            if not locked:
                self.lock_slots.pop(pid, None)
            else:
                slot = _slot_map(self.result).get(pid)
                if slot is None:
                    raise HTTPException(400, "لا يمكن قفل فعالية غير مجدولة.")
                self.lock_slots[pid] = slot
            self.refresh()

    # ---- what-if

    def scenario_inputs(self, sc: ScenarioIn):
        programs, venues, config = self.programs.copy(), self.venues.copy(), self.config
        ids = set(venues["venue_id"])
        names = dict(zip(venues["venue_id"], venues["venue_name"]))
        if sc.kind in ("close_venue", "open_venue"):
            if sc.venue_id not in ids:
                raise HTTPException(400, "اختر القاعة.")
            closing = sc.kind == "close_venue"
            venues.loc[venues["venue_id"] == sc.venue_id, "status"] = "unavailable" if closing else AVAILABLE_STATUS
            label = ("أغلق " if closing else "أعد تشغيل ") + names[sc.venue_id]
        elif sc.kind == "attendance":
            if sc.program_id not in set(programs["program_id"]) or not sc.value or sc.value < 1:
                raise HTTPException(400, "اختر الفعالية والعدد الجديد.")
            programs.loc[programs["program_id"] == sc.program_id, "attendance_value"] = str(sc.value)
            name = programs.loc[programs["program_id"] == sc.program_id, "program_name"].iloc[0]
            label = f"حضور «{name}» = {sc.value}"
        elif sc.kind == "hours":
            try:
                end = time.fromisoformat(sc.day_end or "")
            except ValueError:
                raise HTTPException(400, "اختر وقت نهاية صحيحًا.")
            config = replace(config, day_end=end)
            if config.problems():
                raise HTTPException(400, " ".join(config.problems()))
            label = f"ساعات التشغيل حتى {end:%H:%M}"
        elif sc.kind == "add_day":
            config = replace(config, end_date=config.end_date + timedelta(days=1))
            label = "يوم إضافي: " + _day_long(config.end_date)
        else:
            raise HTTPException(400, "نوع تجربة غير معروف.")
        return programs, venues, config, label

    def whatif(self, sc: ScenarioIn) -> dict:
        with self.lock:
            programs, venues, config, label = self.scenario_inputs(sc)
            result = self.run(programs, venues, config)
            world = self.world_json(result, programs, venues, config)
            world["label"] = label
            if result.status == "INVALID_DATA":
                world.update({"ok": False, "affected": [], "notes": _errors(result)})
                return world
            before, after = _slot_map(self.result), _slot_map(result)
            names = dict(zip(programs["program_id"], programs["program_name"]))
            approved = set(self.approved["program_id"]) if self.approved is not None else set()
            vnames = dict(zip(venues["venue_id"], venues["venue_name"]))
            days = {d["date"]: d for d in world["days"]}
            affected = sorted(k for k in after if before.get(k) != after[k])
            newly = [k for k in after if k not in before]
            lost = [k for k in before if k not in after]
            moved_approved = [k for k in before if k in approved and before[k] != after.get(k)]
            frozen_moves = [k for k in moved_approved if days.get(before[k][0], {}).get("frozen")]
            rearranged = [k for k in before if k in after and k not in approved and before[k] != after[k]]

            def where(slot):
                return f"{days[slot[0]]['label']} {slot[1]} · {vnames[slot[2]]}"

            notes = []
            for k in newly:
                notes.append(f"تُجدول «{names[k]}»: {where(after[k])}.")
            for k in moved_approved:
                if k not in after:
                    notes.append(f"«{names[k]}» المعتمدة تخرج من الجدول.")
                elif before[k][:2] == after[k][:2]:
                    notes.append(f"«{names[k]}» تبقى في موعدها وتنتقل إلى {vnames[after[k][2]]}"
                                 + (" (يوم مجمّد: يُعلَّم للمراجعة ويُبلَّغ صاحبها)." if k in frozen_moves else "."))
                else:
                    notes.append(f"«{names[k]}» المعتمدة تتحرك إلى {where(after[k])}.")
            for k in lost:
                if k not in approved:
                    notes.append(f"«{names.get(k, k)}» تخرج من الجدول.")
            if not newly and not lost:
                remaining = set(result.unscheduled["reason_code"])
                if remaining and remaining <= {"CAPACITY", "EQUIPMENT", "CAPACITY_AND_EQUIPMENT", "VENUE_UNAVAILABLE"}:
                    notes.append("لا تُجدول فعاليات إضافية: ما ينقص هو القاعات والمعدات، لا الوقت.")
                elif not remaining:
                    notes.append("الجدولة مكتملة أصلًا، والتجربة لا تغيّر عدد المجدولة.")
                else:
                    notes.append("لا تُجدول فعاليات إضافية.")
            if not moved_approved:
                notes.append("لا تتحرك أي فعالية معتمدة.")
            world.update({
                "ok": True, "affected": affected, "notes": notes,
                "compare": {
                    "scheduled": [self.result.summary.get("scheduled", 0), result.summary.get("scheduled", 0)],
                    "preferences": [sum(_ratio(self.result.summary.get(k))[0] for k in ("preferred_date_met", "preferred_time_met")),
                                    sum(_ratio(result.summary.get(k))[0] for k in ("preferred_date_met", "preferred_time_met"))],
                    "approved_moved": len(moved_approved), "approved_moved_frozen": len(frozen_moves),
                    "rearranged": len(rearranged), "conflicts": _conflicts(result),
                },
            })
            return world

    def apply_whatif(self, sc: ScenarioIn):
        with self.lock:
            programs, venues, config, _ = self.scenario_inputs(sc)
            result = self.run(programs, venues, config)
            if result.status == "INVALID_DATA":
                raise HTTPException(422, {"message": "لا يمكن تطبيق التجربة.", "errors": _errors(result)})
            self.programs, self.venues, self.config = programs, venues, config
            self.refresh()

    # ---- venue reports (مشرف القاعات)

    def report_inputs(self, body: ReportIn):
        """The venues table after the reported problem, plus a title for the report."""
        venues = self.venues.copy()
        hits = venues.index[venues["venue_id"] == body.venue_id]
        if not len(hits):
            raise HTTPException(400, "اختر القاعة.")
        i = hits[0]
        name = venues.at[i, "venue_name"]
        if body.kind == "equipment":
            item = normalize_item(body.equipment or "")
            have = [normalize_item(x) for x in split_list(venues.at[i, "equipment"])]
            if item not in have:
                raise HTTPException(400, "اختر الجهاز المتعطل من معدات هذه القاعة.")
            venues.at[i, "equipment"] = ";".join(x for x in have if x != item)
            title = f"عطل {EQUIPMENT_AR.get(item, item)} في {name}"
        elif body.kind == "closed":
            venues.at[i, "status"] = "unavailable"
            title = f"إغلاق {name}"
        else:
            raise HTTPException(400, "نوع بلاغ غير معروف.")
        return venues, title

    def report_impact(self, venues, venue_id) -> dict:
        """Affected = events that were in the reported venue, plus approved events that move.
        New events the engine merely reshuffles elsewhere are counted apart (no one was told about them yet)."""
        result = self.run(self.programs, venues, self.config)
        if result.status == "INVALID_DATA":
            return {"ok": False, "errors": _errors(result), "affected": [], "rearranged": 0, "result": result}
        before, after = _slot_map(self.result), _slot_map(result)
        names = dict(zip(self.programs["program_id"], self.programs["program_name"]))
        approved = set(self.approved["program_id"]) if self.approved is not None else set()
        changed = [k for k in before if before[k] != after.get(k)]
        direct = [k for k in changed if before[k][2] == venue_id or k in approved]
        affected = [{"program_id": k, "name": names.get(k, k), "moved_to": after.get(k)} for k in direct]
        return {"ok": True, "errors": [], "affected": affected, "rearranged": len(changed) - len(direct), "result": result}

    def preview_report(self, body: ReportIn) -> dict:
        with self.lock:
            venues, title = self.report_inputs(body)
            impact = self.report_impact(venues, body.venue_id)
            return {"title": title, "ok": impact["ok"], "errors": impact["errors"],
                    "affected": impact["affected"], "rearranged": impact["rearranged"]}

    def submit_report(self, body: ReportIn) -> dict:
        with self.lock:
            venues, title = self.report_inputs(body)
            # A broken venue is a fact, not a choice: locks on it can no longer hold.
            for pid, slot in list(self.lock_slots.items()):
                if slot[2] == body.venue_id:
                    self.lock_slots.pop(pid)
            impact = self.report_impact(venues, body.venue_id)
            previous = text(self.venues.loc[self.venues["venue_id"] == body.venue_id, "status"].iloc[0])
            self.venues = venues
            report = {
                "id": f"R{len(self.reports) + 1}", "venue_id": body.venue_id,
                "venue_name": text(venues.loc[venues["venue_id"] == body.venue_id, "venue_name"].iloc[0]),
                "kind": body.kind, "equipment": normalize_item(body.equipment or "") or None,
                "equipment_label": EQUIPMENT_AR.get(normalize_item(body.equipment or ""), body.equipment or ""),
                "note": body.note.strip(), "title": title, "time": datetime.now().strftime("%H:%M"),
                "status": "open", "previous_status": previous,
                "affected": [a["name"] for a in impact["affected"]], "rearranged": impact["rearranged"],
                "errors": impact["errors"],
            }
            self.reports.append(report)
            self.refresh()
            return report

    def resolve_report(self, rid: str) -> dict:
        with self.lock:
            report = next((r for r in self.reports if r["id"] == rid), None)
            if report is None:
                raise HTTPException(404, "البلاغ غير موجود.")
            if report["status"] == "resolved":
                return report
            i = self.venues.index[self.venues["venue_id"] == report["venue_id"]][0]
            if report["kind"] == "equipment":
                have = [normalize_item(x) for x in split_list(self.venues.at[i, "equipment"])]
                if report["equipment"] not in have:
                    self.venues.at[i, "equipment"] = ";".join(have + [report["equipment"]])
            else:
                self.venues.at[i, "status"] = report["previous_status"] or AVAILABLE_STATUS
            report["status"] = "resolved"
            report["resolved_time"] = datetime.now().strftime("%H:%M")
            self.notifications.append({"to": "organizer", "owner": "", "time": report["resolved_time"],
                                       "title": "أُغلق بلاغ", "text": f"أُغلق بلاغ «{report['title']}»: القاعة جاهزة من جديد."})
            self.refresh()
            return report

    # ---- approval

    def approve(self) -> int:
        with self.lock:
            self.refresh()
            if not self.result.can_approve:
                raise HTTPException(400, "لا يمكن اعتماد المقترح لأن فيه أخطاء.")
            changes = self.changes_json(self.result)
            try:
                approve_proposal(self.paths)
            except ApprovalError as exc:
                raise HTTPException(409, str(exc))
            now = datetime.now().strftime("%H:%M")
            labels = {"new": "جُدولت فعاليتك", "moved": "تغيير في فعاليتك", "dropped": "فعاليتك تحتاج موعدًا بديلًا",
                      "not_scheduled": "تعذّرت جدولة فعاليتك", "removed": "أُزيلت فعاليتك"}
            for c in changes:
                self.notifications.append({"to": "owner", "owner": c["owner"], "time": now,
                                           "title": labels.get(c["type"], "تحديث"), "text": c["message"],
                                           "program_id": c["program_id"]})
            for r in self.reports:
                if r["status"] == "open":
                    r["status"] = "approved"
                    r["approved_time"] = now
                    moved = len(r["affected"])
                    self.notifications.append({"to": "venue", "owner": "", "time": now,
                                               "title": "اعتُمدت الخطة البديلة",
                                               "text": f"اعتمد فريق البرامج الخطة البديلة لبلاغ «{r['title']}»"
                                                       + (f"، وأُبلغ أصحاب {moved} من الفعاليات." if moved else ".")})
            self.approved = read_csv(self.paths.approved)
            self.notified |= set(self.result.unscheduled["program_id"])
            self.refresh()
            return len(changes)

    # ---- exports

    def schedule_csv(self) -> bytes:
        with self.lock:
            days = {d["date"]: d["long"] for d in self.days_json(self.config)}
            programs = {p["id"]: p for p in self.programs_json(self.programs)}
            rows = []
            for r in self.result.schedule.to_dict("records"):
                p = programs.get(r["program_id"], {})
                rows.append({
                    "رقم الفعالية": r["program_id"], "الفعالية": r["program_name"],
                    "اليوم": days.get(r["date"], r["date"]), "التاريخ": r["date"],
                    "البداية": r["start_time"], "النهاية": r["end_time"], "القاعة": r["venue_name"],
                    "الحضور": r["attendance"], "نوع الموعد": "ثابتة" if r["time_type"] == "fixed" else "مرنة",
                    "نوع الحضور": "تسجيل مسبق" if p.get("admission") == "registration" else "حضور عام",
                })
            buffer = io.StringIO()
            pd.DataFrame(rows).to_csv(buffer, index=False)
            return ("﻿" + buffer.getvalue()).encode("utf-8")

    def print_page(self) -> str:
        with self.lock:
            days = self.days_json(self.config)
            venues = self.venues_json(self.venues)
            sched = self.result.schedule
            e = html.escape
            pages = []
            for v in venues:
                rows = sched[sched["venue_id"] == v["id"]]
                body = []
                for d in days:
                    day_rows = rows[rows["date"] == d["date"]].sort_values("start_time")
                    items = "".join(
                        f"<tr><td>{e(r.start_time)}–{e(r.end_time)}</td><td>{e(r.program_name)}</td>"
                        f"<td>{int(r.attendance)}</td></tr>" for r in day_rows.itertuples())
                    body.append(f"<h3>{e(d['long'])}</h3>" + (
                        f"<table><thead><tr><th>الوقت</th><th>الفعالية</th><th>الحضور</th></tr></thead><tbody>{items}</tbody></table>"
                        if items else "<p class='empty'>لا فعاليات.</p>"))
                status = "" if v["status"] == AVAILABLE_STATUS else f" · {e(v['status_label'])}"
                pages.append(f"<section><header><b>Plantix</b><span>جدول القاعة</span></header>"
                             f"<h2>{e(v['name'])}</h2><p class='meta'>سعة {v['capacity']}{status}</p>{''.join(body)}</section>")
            return PRINT_TEMPLATE.replace("{{pages}}", "".join(pages))


PRINT_TEMPLATE = """<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>Plantix — جداول القاعات</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;600;700&display=swap">
<style>
body{margin:0;font-family:'IBM Plex Sans Arabic',Tahoma,sans-serif;color:#13202E;background:#fff}
section{padding:18mm 16mm;page-break-after:always;break-after:page}
section:last-child{page-break-after:auto;break-after:auto}
header{display:flex;justify-content:space-between;color:#0A6B4F;font-size:13px;border-bottom:2px solid #0A6B4F;padding-bottom:6px}
h2{font-size:28px;margin:18px 0 2px}.meta{color:#56636E;margin:0 0 10px}
h3{font-size:16px;margin:18px 0 6px}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:right;padding:7px 10px;border-bottom:1px solid #DFE5E2}th{background:#F3F5F4;font-weight:600}
td:first-child{white-space:nowrap;width:120px}.empty{color:#56636E}
.bar{position:fixed;top:12px;left:12px}.bar button{font:inherit;padding:8px 16px;border-radius:9px;border:0;background:#0A6B4F;color:#fff;cursor:pointer}
@media print{.bar{display:none}}
</style></head><body><div class="bar"><button onclick="print()">طباعة / حفظ PDF</button></div>{{pages}}
<script>window.addEventListener('load',()=>setTimeout(()=>print(),400))</script></body></html>"""


# ---------------------------------------------------------------- app

def create_app(data_dir=ROOT / "data", runtime_dir=ROOT / "runtime",
               reference_date="2026-10-15", freeze_days=2) -> FastAPI:
    ws = Workspace(data_dir, runtime_dir, reference_date, freeze_days)
    app = FastAPI(title="Plantix")
    app.state.workspace = ws

    @app.get("/api/state")
    def get_state():
        return ws.state()

    @app.post("/api/check")
    def check(body: CheckIn):
        return ws.check(body.program_id, body.program)

    @app.post("/api/programs")
    def add_program(body: ProgramIn):
        pid = ws.save_program(None, body)
        return {"program_id": pid, "state": ws.state()}

    @app.put("/api/programs/{pid}")
    def edit_program(pid: str, body: ProgramIn):
        ws.save_program(pid, body)
        return {"program_id": pid, "state": ws.state()}

    @app.delete("/api/programs/{pid}")
    def delete_program(pid: str):
        ws.delete_program(pid)
        return {"state": ws.state()}

    @app.post("/api/programs/{pid}/lock")
    def lock_program(pid: str, body: LockIn):
        ws.set_lock(pid, body.locked)
        return {"state": ws.state()}

    @app.post("/api/whatif")
    def whatif(body: ScenarioIn):
        return ws.whatif(body)

    @app.post("/api/whatif/apply")
    def apply_whatif(body: ScenarioIn):
        ws.apply_whatif(body)
        return {"state": ws.state()}

    @app.post("/api/approve")
    def approve():
        sent = ws.approve()
        return {"sent": sent, "state": ws.state()}

    @app.post("/api/reports/preview")
    def preview_report(body: ReportIn):
        return ws.preview_report(body)

    @app.post("/api/reports")
    def submit_report(body: ReportIn):
        report = ws.submit_report(body)
        return {"report": report, "state": ws.state()}

    @app.post("/api/reports/{rid}/resolve")
    def resolve_report(rid: str):
        report = ws.resolve_report(rid)
        return {"report": report, "state": ws.state()}

    @app.post("/api/requests")
    def submit_request(body: ProgramIn):
        req = ws.submit_request(body)
        return {"ok": True, "request_id": req["id"], "state": ws.state()}

    @app.delete("/api/requests/{rid}")
    def withdraw_request(rid: str):
        ws.withdraw_request(rid)
        return {"ok": True, "state": ws.state()}

    @app.post("/api/requests/{rid}/accept")
    def accept_request(rid: str):
        ws.accept_request(rid)
        return {"ok": True, "program_id": rid, "state": ws.state()}

    @app.post("/api/requests/{rid}/reject")
    def reject_request(rid: str, body: DecisionIn):
        ws.reject_request(rid, body.note)
        return {"ok": True, "state": ws.state()}

    @app.post("/api/alerts/{pid}/accept")
    def accept_alert(pid: str):
        result = ws.accept_alert(pid)
        return {"ok": True, **result, "state": ws.state()}

    @app.post("/api/alerts/{pid}/dismiss")
    def dismiss_alert(pid: str):
        ws.dismiss_alert(pid)
        return {"ok": True, "state": ws.state()}

    @app.post("/api/reset")
    def reset():
        ws.reset()
        return {"state": ws.state()}

    @app.get("/api/download/schedule.csv")
    def download_csv():
        return Response(ws.schedule_csv(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=plantix_schedule.csv"})

    @app.get("/print/venues", response_class=HTMLResponse)
    def print_venues():
        return ws.print_page()

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/owner")
    def owner_page():
        return FileResponse(WEB / "owner.html")

    @app.get("/venue")
    def venue_page():
        return FileResponse(WEB / "venue.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Plantix organizer interface")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--reference-date", default="2026-10-15", help="YYYY-MM-DD")
    parser.add_argument("--freeze-days", type=int, default=2)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    app = create_app(args.data_dir, ROOT / "runtime", args.reference_date, args.freeze_days)
    url = f"http://{args.host}:{args.port}"
    print(f"Plantix جاهز على {url}")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
