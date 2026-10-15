"""CP-SAT model: choose at most one candidate per flexible program.

Objective levels, highest first. Each level's weight exceeds the largest
possible total of every level below it, so a lower level can never buy a
loss on a higher one:

  1. KEEP   - keep every approved flexible event in the schedule
  2. COUNT  - schedule as many flexible events as possible
  3. STABLE - leave approved events where they are: same slot 3, same day
              and time in another room 2, same day another time 1, other
              day 0 (all doubled when the approved date is in the freeze window)
  4. PREF   - preferred date (2 points) and preferred time slot (1 point)
  5. FIT    - smallest suitable venue, keeping big halls free

Fixed events are not variables: they are always placed, and every flexible
option that would overlap one was already removed in candidates.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .candidates import Candidate
from .config import EngineConfig, in_freeze_window
from .data import Assignment, Inputs, Program, Venue


FIT_MAX = 10
PREF_MAX = 3
STAB_MAX = 6
MAX_SAFE_OBJECTIVE = 2 ** 62


def fit_points(program: Program, venue: Venue) -> int:
    return round(FIT_MAX * program.attendance / venue.capacity)


def preferred_date_met(program: Program, candidate: Candidate) -> bool | None:
    if not program.preferred_dates:
        return None
    return candidate.date in program.preferred_dates


def preferred_time_met(program: Program, candidate: Candidate) -> bool | None:
    """The whole event must sit inside one preferred slot."""
    if not program.preferred_slots:
        return None
    return any(
        slot_start <= candidate.start and candidate.end <= slot_end
        for slot_start, slot_end in program.preferred_slots
    )


def preference_points(program: Program, candidate: Candidate) -> int:
    return 2 * bool(preferred_date_met(program, candidate)) + bool(preferred_time_met(program, candidate))


def stability_points(candidate: Candidate, old: Assignment, inputs: Inputs) -> int:
    if candidate.date != old.date:
        base = 0
    elif candidate.start != old.start:
        base = 1  # same day, new time
    elif candidate.venue_id != old.venue_id:
        base = 2  # same day and time, new room
    else:
        base = 3  # untouched
    frozen = in_freeze_window(old.date, inputs.reference_date, inputs.freeze_window_days)
    return base * (2 if frozen else 1)


def level_weights(n_flexible: int, n_existing_flexible: int) -> dict[str, int]:
    """Lowest level first; each weight = (max total of all lower levels) + 1."""
    max_units = [
        ("fit", FIT_MAX * n_flexible),
        ("pref", PREF_MAX * n_flexible),
        ("stable", STAB_MAX * n_existing_flexible),
        ("count", n_flexible),
        ("keep", n_existing_flexible),
    ]
    weights, bound = {}, 0
    for name, units in max_units:
        weights[name] = bound + 1
        bound += weights[name] * units
    weights["_bound"] = bound
    return weights


@dataclass
class SolveOutcome:
    status: str
    ok: bool
    proven_optimal: bool
    chosen: dict[str, Candidate] = field(default_factory=dict)
    seconds: float = 0.0
    message: str = ""


def solve(inputs: Inputs, candidates: dict[str, list[Candidate]], config: EngineConfig) -> SolveOutcome:
    programs, venues = inputs.programs, inputs.venues

    chosen = {
        pid: options[0]
        for pid, options in candidates.items()
        if programs[pid].is_fixed
    }
    flexible = {
        pid: options
        for pid, options in candidates.items()
        if not programs[pid].is_fixed and options
    }
    if not flexible:
        return SolveOutcome("OPTIMAL", True, True, chosen)

    existing_flexible = [pid for pid in flexible if pid in inputs.existing]
    weights = level_weights(len(flexible), len(existing_flexible))
    if weights["_bound"] >= MAX_SAFE_OBJECTIVE:
        return SolveOutcome(
            "MODEL_TOO_LARGE", False, False, chosen,
            message="عدد الفعاليات أكبر من أن تُحسب أوزان الأهداف بدقة؛ يلزم الحل على مراحل.",
        )

    model = cp_model.CpModel()
    option_vars: dict[str, list[tuple[Candidate, cp_model.IntVar]]] = {}
    scheduled: dict[str, cp_model.IntVar] = {}
    rooms: dict[tuple, list[tuple[int, int, cp_model.IntVar]]] = {}
    terms = []

    for pid, options in flexible.items():
        program = programs[pid]
        old = inputs.existing.get(pid)
        is_scheduled = model.NewBoolVar(f"scheduled_{pid}")
        scheduled[pid] = is_scheduled

        pairs = []
        for index, candidate in enumerate(options):
            var = model.NewBoolVar(f"x_{pid}_{index}")
            pairs.append((candidate, var))
            rooms.setdefault((candidate.venue_id, candidate.date), []).append(
                (candidate.start, candidate.busy_until, var)
            )

            score = weights["fit"] * fit_points(program, venues[candidate.venue_id])
            score += weights["pref"] * preference_points(program, candidate)
            if old is not None:
                score += weights["stable"] * stability_points(candidate, old, inputs)
                if (candidate.date, candidate.start, candidate.venue_id) == (old.date, old.start, old.venue_id):
                    model.AddHint(var, 1)
            if score:
                terms.append(score * var)

        option_vars[pid] = pairs
        model.Add(sum(var for _, var in pairs) == is_scheduled)

        terms.append(weights["count"] * is_scheduled)
        if old is not None:
            terms.append(weights["keep"] * is_scheduled)

    # Two intervals overlap exactly when one contains the other's start, so one
    # "at most one" per distinct start time in each room-day is exact, even
    # for off-grid times and any setup length.
    for items in rooms.values():
        for t in sorted({start for start, _, _ in items}):
            covering = [var for start, busy, var in items if start <= t < busy]
            if len(covering) > 1:
                model.AddAtMostOne(covering)

    model.Maximize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.solver_time_limit_seconds
    solver.parameters.num_workers = config.solver_workers
    solver.parameters.random_seed = 0
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveOutcome(
            status_name, False, False, chosen, solver.WallTime(),
            message="لم يجد المحلل أي حل خلال المهلة المحددة؛ زد مهلة الحل أو قلّل حجم البيانات.",
        )

    for pid, pairs in option_vars.items():
        for candidate, var in pairs:
            if solver.Value(var):
                chosen[pid] = candidate
                break

    return SolveOutcome(status_name, True, status == cp_model.OPTIMAL, chosen, solver.WallTime())
