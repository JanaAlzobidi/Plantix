"""Candidate (date, start, venue) options per program, and why a program has none."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .config import STATUS_LABELS_AR, EngineConfig, in_freeze_window
from .data import Inputs, Program, Venue, fmt_minutes, format_items


@dataclass(frozen=True)
class Candidate:
    program_id: str
    date: date
    start: int
    end: int
    busy_until: int  # end + venue setup time
    venue_id: str


@dataclass
class Diagnosis:
    code: str
    reason: str
    suggestion: str = ""
    related_ids: tuple[str, ...] = field(default_factory=tuple)


def overlaps(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and start_b < end_a


def compatible_venues(program: Program, venues: dict[str, Venue]) -> list[Venue]:
    return [
        venue for venue in venues.values()
        if venue.available
        and venue.capacity >= program.attendance
        and program.requirements <= venue.equipment
    ]


def allowed_days(program: Program, inputs: Inputs, config: EngineConfig) -> list[date]:
    """New flexible events may not use days inside the freeze window."""
    days = config.horizon_days()
    if program.program_id in inputs.existing:
        return days
    return [
        day for day in days
        if not in_freeze_window(day, inputs.reference_date, inputs.freeze_window_days)
    ]


def _venue_label(venue: Venue) -> str:
    return f"{venue.name} ({venue.venue_id})"


def _diagnose_no_venue(program: Program, venues: dict[str, Venue]) -> Diagnosis:
    all_venues = list(venues.values())
    if not all_venues:
        return Diagnosis("NO_VENUES", "لا توجد أي قاعات في ملف القاعات.", "أضف القاعات أولًا.")

    big_enough = [v for v in all_venues if v.capacity >= program.attendance]
    equipped = [v for v in all_venues if program.requirements <= v.equipment]
    both = [v for v in big_enough if program.requirements <= v.equipment]

    def fewest_missing(pool):
        return min(pool, key=lambda v: (len(program.requirements - v.equipment), v.capacity))

    if not big_enough:
        largest = max(all_venues, key=lambda v: v.capacity)
        return Diagnosis(
            "CAPACITY",
            f"لا توجد قاعة تتسع لـ{program.attendance} شخصًا؛ أكبر قاعة هي "
            f"{_venue_label(largest)} بسعة {largest.capacity}.",
            "خفّض عدد الحضور المتوقع، أو أضف قاعة أكبر، أو قسّم الفعالية إلى جلستين.",
        )

    if not equipped:
        closest = fewest_missing(big_enough)
        missing = program.requirements - closest.equipment
        return Diagnosis(
            "EQUIPMENT",
            f"لا توجد قاعة تحتوي على كل المعدات المطلوبة ({format_items(program.requirements)}).",
            f"أقرب قاعة هي {_venue_label(closest)} وتنقصها: {format_items(missing)}. "
            "وفّر هذه المعدات فيها أو راجع متطلبات الفعالية.",
            (closest.venue_id,),
        )

    if not both:
        closest = fewest_missing(big_enough)
        missing = program.requirements - closest.equipment
        roomiest_equipped = max(equipped, key=lambda v: v.capacity)
        return Diagnosis(
            "CAPACITY_AND_EQUIPMENT",
            "القاعات التي تتسع للحضور تنقصها معدات، والقاعات التي فيها المعدات أصغر من المطلوب.",
            f"أضف ({format_items(missing)}) إلى {_venue_label(closest)}، "
            f"أو خفّض الحضور إلى {roomiest_equipped.capacity} لتناسب {_venue_label(roomiest_equipped)}.",
            (closest.venue_id, roomiest_equipped.venue_id),
        )

    statuses = "، ".join(f"{_venue_label(v)}: {STATUS_LABELS_AR.get(v.status, v.status)}" for v in both)
    return Diagnosis(
        "VENUE_UNAVAILABLE",
        f"القاعات المناسبة لهذه الفعالية غير متاحة حاليًا ({statuses}).",
        "أعد تفعيل إحدى هذه القاعات إن انتهت صيانتها، أو أضف قاعة بديلة بالمواصفات نفسها.",
        tuple(v.venue_id for v in both),
    )


def _diagnose_frozen(inputs: Inputs, config: EngineConfig) -> Diagnosis:
    days = "، ".join(day.isoformat() for day in config.horizon_days())
    max_freeze = (config.end_date - inputs.reference_date).days - 1
    if max_freeze >= 1:
        hint = (
            f"قلّص نافذة التجميد إلى {max_freeze} يوم أو أقل ليصبح يوم {config.end_date} متاحًا، "
            "أو حوّلها إلى فعالية ثابتة إن كان موعدها محسومًا."
        )
    elif max_freeze == 0:
        hint = "ألغِ نافذة التجميد (0 يوم) أو حوّلها إلى فعالية ثابتة إن كان موعدها محسومًا."
    else:
        hint = "فترة الجدولة كلها في التاريخ المرجعي أو قبله؛ راجع التاريخ المرجعي أو فترة الجدولة."
    return Diagnosis(
        "FREEZE_WINDOW",
        f"فعالية مرنة جديدة وكل أيام فترة الجدولة ({days}) داخل نافذة التجميد "
        f"({inputs.freeze_window_days} يوم من {inputs.reference_date}).",
        hint,
    )


def build_candidates(inputs: Inputs, config: EngineConfig):
    """Returns ({program_id: [Candidate]}, {program_id: Diagnosis}).

    Flexible options that overlap a fixed event are dropped here, since fixed
    events are always placed. Programs left with no options get a Diagnosis.
    """
    programs, venues = inputs.programs, inputs.venues
    candidates: dict[str, list[Candidate]] = {}
    diagnoses: dict[str, Diagnosis] = {}

    fixed_busy: dict[tuple[str, date], list[tuple[int, int, str]]] = {}
    for program in programs.values():
        if not program.is_fixed:
            continue
        venue = venues[program.fixed_venue_id]
        start = program.fixed_start
        end = start + program.duration
        candidates[program.program_id] = [
            Candidate(program.program_id, program.fixed_date, start, end,
                      end + venue.setup_min, venue.venue_id)
        ]
        fixed_busy.setdefault((venue.venue_id, program.fixed_date), []).append(
            (start, end + venue.setup_min, program.program_id)
        )

    day_open, day_close = config.day_start_min, config.day_end_min

    for program in programs.values():
        if program.is_fixed:
            continue
        pid = program.program_id
        candidates[pid] = []

        rooms = compatible_venues(program, venues)
        if not rooms:
            diagnoses[pid] = _diagnose_no_venue(program, venues)
            continue

        days = allowed_days(program, inputs, config)
        if not days:
            diagnoses[pid] = _diagnose_frozen(inputs, config)
            continue

        options = []
        fits_hours = 0
        blocking_fixed: set[str] = set()

        for day in days:
            for start in range(day_open, day_close - program.duration + 1, config.slot_minutes):
                end = start + program.duration
                for venue in rooms:
                    busy_until = end + venue.setup_min
                    if not config.allow_setup_after_close and busy_until > day_close:
                        continue
                    fits_hours += 1
                    clashes = [
                        fixed_pid
                        for f_start, f_busy, fixed_pid in fixed_busy.get((venue.venue_id, day), ())
                        if overlaps(start, busy_until, f_start, f_busy)
                    ]
                    if clashes:
                        blocking_fixed.update(clashes)
                        continue
                    options.append(Candidate(pid, day, start, end, busy_until, venue.venue_id))

        candidates[pid] = options

        if options:
            continue
        if fits_hours == 0:
            diagnoses[pid] = Diagnosis(
                "NO_TIME_SLOT",
                f"لا يوجد وقت بداية يسمح بإنهاء الفعالية وتجهيز القاعة قبل "
                f"{fmt_minutes(day_close)}.",
                "قصّر مدة الفعالية أو اسمح بالتجهيز بعد نهاية ساعات التشغيل.",
            )
        else:
            names = "، ".join(f"{fid} ({programs[fid].name})" for fid in sorted(blocking_fixed))
            where = f"القاعات المناسبة ({', '.join(v.name for v in rooms)})"
            diagnoses[pid] = Diagnosis(
                "BLOCKED_BY_FIXED",
                f"كل الأوقات الممكنة تتعارض مع فعاليات ثابتة في {where}: {names}.",
                "أضف قاعة مناسبة أخرى، أو قصّر مدة الفعالية، أو راجع مواعيد الفعاليات الثابتة.",
                tuple(sorted(blocking_fixed)),
            )

    return candidates, diagnoses
