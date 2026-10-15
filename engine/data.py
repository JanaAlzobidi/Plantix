"""Input parsing and validation.

Every problem found is recorded in an IssueLog instead of raising on the first
one, so the manager sees all data problems at once. Any "error" stops the run;
"warning" entries are shown but do not block scheduling.
"""

from __future__ import annotations

import numbers
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time

import pandas as pd

from .config import (
    ADMISSION_ALIASES,
    ADMISSION_OPEN,
    AVAILABLE_STATUS,
    STATUS_LABELS_AR,
    FIXED,
    FLEXIBLE,
    VENUE_STATUSES,
    EngineConfig,
)


PROGRAM_COLUMNS = (
    "program_id", "program_name", "duration_min", "attendance_value",
    "venue_requirements", "time_type", "fixed_date", "fixed_start_time",
    "fixed_venue_id", "preferred_dates", "preferred_time_slots",
)
VENUE_COLUMNS = (
    "venue_id", "venue_name", "capacity", "equipment",
    "min_setup_time_min", "status",
)
SCHEDULE_COLUMNS = ("program_id", "date", "start_time", "venue_id")


# ---------------------------------------------------------------- issues

@dataclass
class Issue:
    severity: str  # "error" | "warning"
    code: str
    message: str
    program_id: str | None = None
    venue_id: str | None = None


class IssueLog:
    def __init__(self):
        self.items: list[Issue] = []

    def error(self, code, message, program_id=None, venue_id=None):
        self.items.append(Issue("error", code, message, program_id, venue_id))

    def warning(self, code, message, program_id=None, venue_id=None):
        self.items.append(Issue("warning", code, message, program_id, venue_id))

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.items)

    def count(self, severity: str) -> int:
        return sum(issue.severity == severity for issue in self.items)


# ---------------------------------------------------------------- domain

@dataclass(frozen=True)
class Venue:
    venue_id: str
    name: str
    capacity: int
    equipment: frozenset[str]
    setup_min: int
    status: str

    @property
    def available(self) -> bool:
        return self.status == AVAILABLE_STATUS


@dataclass(frozen=True)
class Program:
    program_id: str
    name: str
    duration: int
    attendance: int
    requirements: frozenset[str]
    time_type: str
    fixed_date: date | None = None
    fixed_start: int | None = None
    fixed_venue_id: str | None = None
    preferred_dates: frozenset[date] = frozenset()
    preferred_slots: tuple[tuple[int, int], ...] = ()
    track: str = ""
    admission: str = ADMISSION_OPEN

    @property
    def is_fixed(self) -> bool:
        return self.time_type == FIXED


@dataclass(frozen=True)
class Assignment:
    """An event's placement in the approved (current) schedule."""
    program_id: str
    date: date
    start: int
    venue_id: str
    program_name: str = ""


@dataclass
class Inputs:
    programs: dict[str, Program] = field(default_factory=dict)
    venues: dict[str, Venue] = field(default_factory=dict)
    existing: dict[str, Assignment] = field(default_factory=dict)
    removed: dict[str, Assignment] = field(default_factory=dict)
    reference_date: date | None = None
    freeze_window_days: int = 0


# ---------------------------------------------------------------- parsing helpers

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LIST_SPLIT_RE = re.compile(r"[;,]")


def is_blank(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


def text(value) -> str:
    return "" if is_blank(value) else str(value).strip()


def parse_int(value) -> int | None:
    if is_blank(value) or isinstance(value, bool):
        return None
    if isinstance(value, numbers.Integral):
        return int(value)
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return int(number) if number.is_integer() else None


def parse_date(value) -> date | None:
    """None for blank; ValueError for anything that is not YYYY-MM-DD."""
    if is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not _DATE_RE.fullmatch(raw):
        raise ValueError(raw)
    return date.fromisoformat(raw)


def parse_minutes(value) -> int | None:
    """'HH:MM' -> minutes since midnight. None for blank; ValueError if invalid."""
    if is_blank(value):
        return None
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    match = _TIME_RE.fullmatch(str(value).strip())
    if not match:
        raise ValueError(value)
    hours, minutes = int(match[1]), int(match[2])
    seconds = int(match[3]) if match[3] else 0
    if hours > 23 or minutes > 59 or seconds != 0:
        raise ValueError(value)
    return hours * 60 + minutes


def fmt_minutes(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def split_list(value) -> list[str]:
    if is_blank(value):
        return []
    items = []
    for part in _LIST_SPLIT_RE.split(str(value)):
        part = part.strip()
        if part and part not in items:
            items.append(part)
    return items


def normalize_item(value: str) -> str:
    return " ".join(value.casefold().split())


def format_items(items) -> str:
    return "، ".join(sorted(items))


# ---------------------------------------------------------------- validation

def _check_columns(df, required, label, log) -> bool:
    if not isinstance(df, pd.DataFrame):
        log.error("INVALID_TABLE", f"{label} يجب أن يكون جدول بيانات (DataFrame).")
        return False
    missing = [col for col in required if col not in df.columns]
    if missing:
        log.error(
            "MISSING_COLUMNS",
            f"{label}: أعمدة إلزامية ناقصة: {', '.join(missing)}.",
        )
        return False
    return True


def _parse_reference_date(value, log):
    if is_blank(value):
        log.error(
            "REFERENCE_DATE_MISSING",
            "التاريخ المرجعي مطلوب لحساب نافذة التجميد بشكل قابل لإعادة الإنتاج.",
        )
        return None
    try:
        return parse_date(value)
    except ValueError:
        log.error(
            "INVALID_REFERENCE_DATE",
            f"التاريخ المرجعي «{value}» غير صالح. الصيغة المطلوبة YYYY-MM-DD.",
        )
        return None


def _parse_freeze_days(value, log) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, numbers.Integral)
        or value < 0
    ):
        log.error(
            "INVALID_FREEZE_WINDOW",
            f"عدد أيام نافذة التجميد يجب أن يكون عددًا صحيحًا غير سالب (القيمة: {value!r}).",
        )
        return 0
    return int(value)


def _parse_venues(df, log) -> tuple[dict[str, Venue], set[str]]:
    venues: dict[str, Venue] = {}
    seen: set[str] = set()
    reported_dups: set[str] = set()

    for position, row in enumerate(df.to_dict("records")):
        line = position + 2
        vid = text(row["venue_id"])
        if not vid:
            log.error("VENUE_ID_MISSING", f"قاعة بدون معرّف في السطر {line} من ملف القاعات.")
            continue
        if vid in seen:
            if vid not in reported_dups:
                log.error("DUPLICATE_VENUE_ID", f"معرّف القاعة {vid} مكرر.", venue_id=vid)
                reported_dups.add(vid)
            venues.pop(vid, None)
            continue
        seen.add(vid)

        ok = True

        def err(code, message):
            nonlocal ok
            ok = False
            log.error(code, f"القاعة {vid}: {message}", venue_id=vid)

        name = text(row["venue_name"])
        if not name:
            err("VENUE_NAME_MISSING", "اسم القاعة فارغ.")

        capacity = parse_int(row["capacity"])
        if capacity is None or capacity <= 0:
            err("INVALID_CAPACITY", f"السعة يجب أن تكون عددًا صحيحًا موجبًا (القيمة: «{text(row['capacity'])}»).")

        setup = parse_int(row["min_setup_time_min"])
        if setup is None or setup < 0:
            err(
                "INVALID_SETUP_TIME",
                f"وقت التجهيز يجب أن يكون عددًا صحيحًا غير سالب بالدقائق (القيمة: «{text(row['min_setup_time_min'])}»).",
            )

        status = text(row["status"]).casefold()
        if status not in VENUE_STATUSES:
            err(
                "INVALID_VENUE_STATUS",
                f"الحالة «{text(row['status'])}» غير معروفة. القيم المسموحة: {', '.join(sorted(VENUE_STATUSES))}.",
            )

        if ok:
            venues[vid] = Venue(
                venue_id=vid,
                name=name,
                capacity=capacity,
                equipment=frozenset(normalize_item(x) for x in split_list(row["equipment"])),
                setup_min=setup,
                status=status,
            )

    return venues, seen


def _parse_programs(df, venues, venue_ids_seen, config, log) -> tuple[dict[str, Program], set[str]]:
    programs: dict[str, Program] = {}
    seen: set[str] = set()
    reported_dups: set[str] = set()
    horizon = (config.start_date, config.end_date)
    has_track = "track" in df.columns
    has_admission = "admission" in df.columns

    for position, row in enumerate(df.to_dict("records")):
        line = position + 2
        pid = text(row["program_id"])
        if not pid:
            log.error("PROGRAM_ID_MISSING", f"برنامج بدون معرّف في السطر {line} من ملف البرامج.")
            continue
        if pid in seen:
            if pid not in reported_dups:
                log.error("DUPLICATE_PROGRAM_ID", f"معرّف البرنامج {pid} مكرر.", program_id=pid)
                reported_dups.add(pid)
            programs.pop(pid, None)
            continue
        seen.add(pid)

        ok = True

        def err(code, message):
            nonlocal ok
            ok = False
            log.error(code, f"البرنامج {pid}: {message}", program_id=pid)

        def warn(code, message):
            log.warning(code, f"البرنامج {pid}: {message}", program_id=pid)

        name = text(row["program_name"])
        if not name:
            err("PROGRAM_NAME_MISSING", "اسم البرنامج فارغ.")

        duration = parse_int(row["duration_min"])
        if duration is None or duration <= 0:
            err("INVALID_DURATION", f"المدة يجب أن تكون عددًا صحيحًا موجبًا بالدقائق (القيمة: «{text(row['duration_min'])}»).")
            duration = None
        elif duration > config.day_length_min:
            err(
                "DURATION_EXCEEDS_DAY",
                f"المدة {duration} دقيقة أطول من ساعات التشغيل اليومية ({config.day_length_min} دقيقة).",
            )

        attendance = parse_int(row["attendance_value"])
        if attendance is None or attendance < 0:
            err("INVALID_ATTENDANCE", f"عدد الحضور يجب أن يكون عددًا صحيحًا غير سالب (القيمة: «{text(row['attendance_value'])}»).")

        time_type = text(row["time_type"]).casefold()
        if time_type not in (FIXED, FLEXIBLE):
            err("INVALID_TIME_TYPE", f"نوع الفعالية «{text(row['time_type'])}» غير صالح. القيم المسموحة: fixed أو flexible.")

        admission = ADMISSION_OPEN
        if has_admission and not is_blank(row["admission"]):
            admission = ADMISSION_ALIASES.get(normalize_item(text(row["admission"])))
            if admission is None:
                err(
                    "INVALID_ADMISSION",
                    f"نوع الحضور «{text(row['admission'])}» غير صالح. القيم المسموحة: open (حضور عام) "
                    "أو registration (تسجيل مسبق).",
                )

        requirements = frozenset(normalize_item(x) for x in split_list(row["venue_requirements"]))

        preferred_dates = set()
        for token in split_list(row["preferred_dates"]):
            try:
                day = parse_date(token)
            except ValueError:
                err("INVALID_PREFERRED_DATE", f"التاريخ المفضل «{token}» غير صالح. الصيغة المطلوبة YYYY-MM-DD.")
                continue
            if not horizon[0] <= day <= horizon[1]:
                warn("PREFERRED_DATE_OUTSIDE_HORIZON", f"التاريخ المفضل {day} خارج فترة الجدولة وسيتم تجاهله.")
            preferred_dates.add(day)

        preferred_slots = []
        for token in split_list(row["preferred_time_slots"]):
            parts = token.split("-")
            try:
                if len(parts) != 2:
                    raise ValueError(token)
                slot_start = parse_minutes(parts[0])
                slot_end = parse_minutes(parts[1])
                if slot_start is None or slot_end is None or slot_start >= slot_end:
                    raise ValueError(token)
            except ValueError:
                err(
                    "INVALID_PREFERRED_SLOT",
                    f"الفترة المفضلة «{token}» غير صالحة. الصيغة المطلوبة HH:MM-HH:MM والبداية قبل النهاية.",
                )
                continue
            if slot_end <= config.day_start_min or slot_start >= config.day_end_min:
                warn("PREFERRED_SLOT_OUTSIDE_HOURS", f"الفترة المفضلة {token} خارج ساعات التشغيل.")
            preferred_slots.append((slot_start, slot_end))

        fixed_date = fixed_start = None
        fixed_venue_id = None

        if time_type == FIXED:
            try:
                fixed_date = parse_date(row["fixed_date"])
                if fixed_date is None:
                    err("FIXED_DATE_MISSING", "الفعالية ثابتة لكن تاريخها غير محدد.")
                elif not horizon[0] <= fixed_date <= horizon[1]:
                    err(
                        "FIXED_DATE_OUTSIDE_HORIZON",
                        f"تاريخها {fixed_date} خارج فترة الجدولة ({horizon[0]} إلى {horizon[1]}).",
                    )
            except ValueError:
                err("INVALID_FIXED_DATE", f"التاريخ «{text(row['fixed_date'])}» غير صالح. الصيغة المطلوبة YYYY-MM-DD.")

            try:
                fixed_start = parse_minutes(row["fixed_start_time"])
                if fixed_start is None:
                    err("FIXED_TIME_MISSING", "الفعالية ثابتة لكن وقت بدايتها غير محدد.")
            except ValueError:
                err("INVALID_FIXED_TIME", f"وقت البداية «{text(row['fixed_start_time'])}» غير صالح. الصيغة المطلوبة HH:MM.")

            if fixed_start is not None and duration is not None:
                end = fixed_start + duration
                if fixed_start < config.day_start_min or end > config.day_end_min:
                    err(
                        "FIXED_OUTSIDE_HOURS",
                        f"موعدها من {fmt_minutes(fixed_start)} إلى {fmt_minutes(end)} يتجاوز ساعات التشغيل "
                        f"({fmt_minutes(config.day_start_min)}–{fmt_minutes(config.day_end_min)}).",
                    )

            fixed_venue_id = text(row["fixed_venue_id"])
            if not fixed_venue_id:
                err("FIXED_VENUE_MISSING", "الفعالية ثابتة لكن قاعتها غير محددة.")
            elif fixed_venue_id not in venue_ids_seen:
                err("FIXED_VENUE_NOT_FOUND", f"القاعة المحددة {fixed_venue_id} غير موجودة في ملف القاعات.")
            elif fixed_venue_id in venues:
                venue = venues[fixed_venue_id]
                if not venue.available:
                    err(
                        "FIXED_VENUE_UNAVAILABLE",
                        f"القاعة المحددة {venue.name} ({venue.venue_id}) حالتها «{STATUS_LABELS_AR.get(venue.status, venue.status)}» وليست متاحة.",
                    )
                if attendance is not None and venue.capacity < attendance:
                    err(
                        "FIXED_VENUE_TOO_SMALL",
                        f"القاعة المحددة {venue.name} سعتها {venue.capacity} والحضور المتوقع {attendance}.",
                    )
                missing = requirements - venue.equipment
                if missing:
                    err(
                        "FIXED_VENUE_MISSING_EQUIPMENT",
                        f"القاعة المحددة {venue.name} تنقصها المعدات: {format_items(missing)}.",
                    )
                if (
                    not config.allow_setup_after_close
                    and fixed_start is not None
                    and duration is not None
                    and fixed_start + duration + venue.setup_min > config.day_end_min
                ):
                    err(
                        "FIXED_SETUP_AFTER_CLOSE",
                        f"وقت تجهيز القاعة ({venue.setup_min} دقيقة) بعد نهايتها يتجاوز نهاية ساعات التشغيل.",
                    )

        elif time_type == FLEXIBLE:
            if any(not is_blank(row[col]) for col in ("fixed_date", "fixed_start_time", "fixed_venue_id")):
                warn(
                    "FIXED_FIELDS_IGNORED",
                    "الفعالية مرنة لكن لها تاريخ أو وقت أو قاعة ثابتة؛ سيتم تجاهلها. غيّر النوع إلى fixed إن كان الموعد محسومًا.",
                )

        if ok:
            programs[pid] = Program(
                program_id=pid,
                name=name,
                duration=duration,
                attendance=attendance,
                requirements=requirements,
                time_type=time_type,
                fixed_date=fixed_date,
                fixed_start=fixed_start,
                fixed_venue_id=fixed_venue_id,
                preferred_dates=frozenset(preferred_dates),
                preferred_slots=tuple(sorted(preferred_slots)),
                track=text(row["track"]) if has_track else "",
                admission=admission,
            )

    return programs, seen


def _warn_unknown_requirements(programs, venues, log):
    if not venues:
        return
    known = set().union(*(venue.equipment for venue in venues.values()))
    for program in programs.values():
        unknown = program.requirements - known
        if unknown:
            log.warning(
                "UNKNOWN_REQUIREMENT",
                f"البرنامج {program.program_id}: المتطلبات ({format_items(unknown)}) غير موجودة في أي قاعة. "
                "تحقق من كتابتها.",
                program_id=program.program_id,
            )


def _check_fixed_track_conflicts(programs, config, log):
    if not config.tracks_no_overlap:
        return
    by_track: dict[tuple, list] = {}
    for p in programs.values():
        if p.is_fixed and p.track:
            by_track.setdefault((p.track, p.fixed_date), []).append(p)
    for (track, day), items in by_track.items():
        items.sort(key=lambda p: p.fixed_start)
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if b.fixed_start >= a.fixed_start + a.duration:
                    break
                log.error(
                    "FIXED_TRACK_CONFLICT",
                    f"الفعاليتان الثابتتان {a.program_id} ({a.name}) و{b.program_id} ({b.name}) "
                    f"من نفس المسار «{track}» وتتزامنان يوم {day}؛ قاعدة العميل تمنع تزامن فعاليات المسار الواحد.",
                    program_id=a.program_id,
                )


def _check_fixed_conflicts(programs, venues, log):
    by_room: dict[tuple, list] = {}
    for program in programs.values():
        if not program.is_fixed:
            continue
        venue = venues[program.fixed_venue_id]
        start = program.fixed_start
        end = start + program.duration
        by_room.setdefault((program.fixed_venue_id, program.fixed_date), []).append(
            (start, end, end + venue.setup_min, program)
        )

    for (vid, day), items in by_room.items():
        items.sort(key=lambda item: item[0])
        venue = venues[vid]
        for i, (a_start, a_end, a_busy, a) in enumerate(items):
            for b_start, _, _, b in items[i + 1:]:
                if b_start >= a_busy:
                    break
                log.error(
                    "FIXED_CONFLICT",
                    f"تعارض بين فعاليتين ثابتتين في {venue.name} يوم {day}: "
                    f"{a.program_id} ({a.name}) من {fmt_minutes(a_start)} إلى {fmt_minutes(a_end)} "
                    f"والقاعة مشغولة بالتجهيز حتى {fmt_minutes(a_busy)}، "
                    f"بينما تبدأ {b.program_id} ({b.name}) الساعة {fmt_minutes(b_start)}. "
                    "يجب تعديل موعد أو قاعة إحداهما يدويًا.",
                    program_id=a.program_id,
                    venue_id=vid,
                )


def _parse_existing(df, programs, program_ids_seen, venue_ids_seen, log):
    existing: dict[str, Assignment] = {}
    removed: dict[str, Assignment] = {}
    if df is None:
        return existing, removed
    if not _check_columns(df, SCHEDULE_COLUMNS, "الجدول المعتمد", log):
        return existing, removed

    seen: set[str] = set()
    has_names = "program_name" in df.columns

    for position, row in enumerate(df.to_dict("records")):
        line = position + 2
        pid = text(row["program_id"])
        if not pid:
            log.error("APPROVED_ID_MISSING", f"سطر بدون معرّف برنامج ({line}) في الجدول المعتمد.")
            continue
        if pid in seen:
            log.error("APPROVED_DUPLICATE", f"البرنامج {pid} مكرر في الجدول المعتمد.", program_id=pid)
            continue
        seen.add(pid)

        try:
            day = parse_date(row["date"])
            start = parse_minutes(row["start_time"])
            if day is None or start is None:
                raise ValueError
        except ValueError:
            log.error(
                "INVALID_APPROVED_ROW",
                f"تاريخ أو وقت البرنامج {pid} في الجدول المعتمد غير صالح "
                f"(«{text(row['date'])}» «{text(row['start_time'])}»).",
                program_id=pid,
            )
            continue

        vid = text(row["venue_id"])
        assignment = Assignment(
            program_id=pid,
            date=day,
            start=start,
            venue_id=vid,
            program_name=text(row["program_name"]) if has_names else "",
        )

        if vid not in venue_ids_seen:
            log.warning(
                "APPROVED_VENUE_UNKNOWN",
                f"البرنامج {pid} معتمد في القاعة {vid or '(فارغة)'} وهي غير موجودة في ملف القاعات.",
                program_id=pid,
                venue_id=vid or None,
            )

        if pid not in program_ids_seen:
            removed[pid] = assignment
            log.warning(
                "APPROVED_PROGRAM_REMOVED",
                f"البرنامج {pid} موجود في الجدول المعتمد لكنه لم يعد في قائمة البرامج؛ لن يظهر في الجدول المقترح.",
                program_id=pid,
            )
            continue

        program = programs.get(pid)
        if program is None:
            continue  # the program row has its own errors

        if program.is_fixed and (
            program.fixed_date != day
            or program.fixed_start != start
            or program.fixed_venue_id != vid
        ):
            log.warning(
                "FIXED_ASSIGNMENT_CHANGED",
                f"الفعالية الثابتة {pid}: موعدها في ملف البرامج يختلف عن الجدول المعتمد؛ "
                "سيُستخدم ما في ملف البرامج.",
                program_id=pid,
            )

        existing[pid] = assignment

    return existing, removed


def prepare_inputs(programs_df, venues_df, current_df, reference_date,
                   freeze_window_days, config: EngineConfig, log: IssueLog) -> Inputs:
    inputs = Inputs()

    for problem in config.problems():
        log.error("INVALID_CONFIG", problem)

    inputs.reference_date = _parse_reference_date(reference_date, log)
    inputs.freeze_window_days = _parse_freeze_days(freeze_window_days, log)

    programs_ok = _check_columns(programs_df, PROGRAM_COLUMNS, "ملف البرامج", log)
    venues_ok = _check_columns(venues_df, VENUE_COLUMNS, "ملف القاعات", log)
    if not (programs_ok and venues_ok) or log.has_errors:
        return inputs

    venues, venue_ids = _parse_venues(venues_df, log)
    programs, program_ids = _parse_programs(programs_df, venues, venue_ids, config, log)
    inputs.venues = venues
    inputs.programs = programs

    _warn_unknown_requirements(programs, venues, log)
    if not log.has_errors:
        _check_fixed_conflicts(programs, venues, log)
        _check_fixed_track_conflicts(programs, config, log)

    if current_df is not None and isinstance(current_df, pd.DataFrame) and current_df.empty:
        current_df = None
    inputs.existing, inputs.removed = _parse_existing(
        current_df, programs, program_ids, venue_ids, log
    )
    return inputs
