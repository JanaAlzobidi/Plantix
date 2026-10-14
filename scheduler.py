
from pathlib import Path
from datetime import date, datetime, time, timedelta

import pandas as pd
from ortools.sat.python import cp_model


# =========================================================
# 1. CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

PROGRAMS_FILE = DATA_DIR / "programs.csv"
VENUES_FILE = DATA_DIR / "venues.csv"
OUTPUT_FILE = DATA_DIR / "schedule_output.csv"

START_DATE = date(2026, 10, 17)
END_DATE = date(2026, 10, 19)

DAY_START = time(9, 0)
DAY_END = time(18, 0)

SLOT_MINUTES = 15
SOLVER_TIME_LIMIT_SECONDS = 20


# =========================================================
# 2. DATA LOADING AND VALIDATION
# =========================================================

class SchedulingDataError(Exception):
    """Raised when scheduling data is invalid."""


def load_data():
    """Read the programs and venues CSV files."""

    if not PROGRAMS_FILE.exists():
        raise FileNotFoundError(f"Missing file: {PROGRAMS_FILE}")

    if not VENUES_FILE.exists():
        raise FileNotFoundError(f"Missing file: {VENUES_FILE}")

    programs = pd.read_csv(PROGRAMS_FILE)
    venues = pd.read_csv(VENUES_FILE)

    return programs, venues


def split_values(value):
    """Convert semicolon-separated values into a set."""

    if pd.isna(value) or not str(value).strip():
        return set()

    return {
        item.strip()
        for item in str(value).split(";")
        if item.strip()
    }


def parse_date(value):
    """Parse a date without treating blank values as dates."""

    if pd.isna(value) or not str(value).strip():
        return None

    return pd.to_datetime(value, errors="raise").date()


def parse_time(value):
    """Parse an HH:MM time."""

    if pd.isna(value) or not str(value).strip():
        return None

    return datetime.strptime(str(value).strip(), "%H:%M").time()


def validate_data(programs, venues):
    """Validate required columns and core scheduling values."""

    required_programs = {
        "program_id",
        "program_name",
        "duration_min",
        "attendance_value",
        "attendance_mode",
        "venue_requirements",
        "time_type",
        "fixed_date",
        "fixed_start_time",
        "fixed_venue_id",
        "preferred_dates",
        "preferred_time_slots",
    }

    required_venues = {
        "venue_id",
        "venue_name",
        "capacity",
        "equipment",
        "min_setup_time_min",
        "status",
    }

    missing_p = required_programs - set(programs.columns)
    missing_v = required_venues - set(venues.columns)

    if missing_p:
        raise SchedulingDataError(
            f"Missing program columns: {sorted(missing_p)}"
        )

    if missing_v:
        raise SchedulingDataError(
            f"Missing venue columns: {sorted(missing_v)}"
        )

    for df, column, label in [
        (programs, "program_id", "program"),
        (venues, "venue_id", "venue"),
    ]:
        if df[column].isna().any():
            raise SchedulingDataError(
                f"Every {label} needs an ID."
            )

        if df[column].astype(str).duplicated().any():
            raise SchedulingDataError(
                f"{column} values must be unique."
            )

    if not programs["attendance_mode"].isin(
        ["confirmed", "estimated"]
    ).all():
        raise SchedulingDataError("Invalid attendance_mode.")

    if not programs["time_type"].isin(
        ["fixed", "flexible"]
    ).all():
        raise SchedulingDataError("Invalid time_type.")

    if not venues["status"].isin(
        ["available", "under_maintenance", "closed"]
    ).all():
        raise SchedulingDataError("Invalid venue status.")

    for column in ["duration_min", "attendance_value"]:
        programs[column] = pd.to_numeric(
            programs[column], errors="raise"
        )

        if (
            programs[column].isna().any()
            or (programs[column] < 0).any()
        ):
            raise SchedulingDataError(
                f"{column} must be non-negative."
            )

    for column in ["capacity", "min_setup_time_min"]:
        venues[column] = pd.to_numeric(
            venues[column], errors="raise"
        )

        if (
            venues[column].isna().any()
            or (venues[column] < 0).any()
        ):
            raise SchedulingDataError(
                f"{column} must be non-negative."
            )

    if (programs["duration_min"] <= 0).any():
        raise SchedulingDataError(
            "Every duration_min must be greater than zero."
        )

    if (venues["capacity"] <= 0).any():
        raise SchedulingDataError(
            "Every venue capacity must be greater than zero."
        )

    if (
        programs["attendance_value"] % 1 != 0
    ).any():
        raise SchedulingDataError(
            "Attendance must be a whole number."
        )

    if (venues["capacity"] % 1 != 0).any():
        raise SchedulingDataError(
            "Venue capacities must be whole numbers."
        )

    return True


# =========================================================
# 3. CANDIDATE ASSIGNMENTS
# =========================================================

def make_candidate(program, venue, event_date, start_time):
    """Build one possible program, date, time, and venue assignment."""

    start_dt = datetime.combine(event_date, start_time)
    end_dt = start_dt + timedelta(
        minutes=int(program["duration_min"])
    )

    return {
        "program_id": str(program["program_id"]),
        "program_name": str(program["program_name"]),
        "venue_id": str(venue["venue_id"]),
        "venue_name": str(venue["venue_name"]),
        "event_date": event_date,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "occupied_end": end_dt + timedelta(
            minutes=int(venue["min_setup_time_min"])
        ),
        "fixed": program["time_type"] == "fixed",
        "score": 0,
    }


def venue_is_compatible(program, venue):
    """Check the venue's availability, capacity, and equipment."""

    if venue["status"] != "available":
        return False

    if int(venue["capacity"]) < int(program["attendance_value"]):
        return False

    required = split_values(program["venue_requirements"])
    available = split_values(venue["equipment"])

    return required.issubset(available)


def preferred_score(program, event_date, start_dt, end_dt):
    """Score optional date and time preferences."""

    score = 0

    preferred_dates = {
        parse_date(value)
        for value in split_values(program["preferred_dates"])
    }

    if preferred_dates and event_date in preferred_dates:
        score += 1000

    preferred_slots = split_values(
        program["preferred_time_slots"]
    )

    for slot in preferred_slots:
        try:
            start_text, end_text = slot.split("-", 1)
            preferred_start = parse_time(start_text)
            preferred_end = parse_time(end_text)
        except (ValueError, TypeError):
            raise SchedulingDataError(
                f"Invalid preferred time slot: {slot}"
            )

        if (
            preferred_start <= start_dt.time()
            and end_dt.time() <= preferred_end
        ):
            score += 500
            break

    return score


def generate_candidates(programs, venues):
    """Generate valid scheduling choices for every program."""

    candidates = []
    candidates_by_program = {}

    all_dates = []
    current_date = START_DATE

    while current_date <= END_DATE:
        all_dates.append(current_date)
        current_date += timedelta(days=1)

    for _, program in programs.iterrows():
        program_id = str(program["program_id"])
        program_candidates = []

        if program["time_type"] == "fixed":
            event_date = parse_date(program["fixed_date"])
            start_time = parse_time(program["fixed_start_time"])
            venue_id = str(program["fixed_venue_id"])

            if event_date is None or start_time is None:
                raise SchedulingDataError(
                    f"{program_id} has incomplete fixed assignment."
                )

            if not START_DATE <= event_date <= END_DATE:
                raise SchedulingDataError(
                    f"{program_id} has a fixed date outside "
                    "the scheduling horizon."
                )

            matching_venues = venues[
                venues["venue_id"].astype(str) == venue_id
            ]

            if matching_venues.empty:
                raise SchedulingDataError(
                    f"{program_id} references unknown venue {venue_id}."
                )

            venue = matching_venues.iloc[0]

            if not venue_is_compatible(program, venue):
                raise SchedulingDataError(
                    f"{program_id} cannot use its fixed venue "
                    f"{venue_id}: check status, capacity, and equipment."
                )

            candidate = make_candidate(
                program, venue, event_date, start_time
            )

            if (
                start_time < DAY_START
                or candidate["end_dt"].time() > DAY_END
            ):
                raise SchedulingDataError(
                    f"{program_id} falls outside operating hours."
                )

            program_candidates.append(candidate)

        else:
            preferred_dates = {
                parse_date(value)
                for value in split_values(program["preferred_dates"])
            }

            dates_to_try = [
                d for d in all_dates
                if not preferred_dates or d in preferred_dates
            ]

            # Preferred dates are soft: if none of them are
            # in the scheduling horizon, consider every date.
            if not dates_to_try:
                dates_to_try = all_dates

            # Consider every date so preferences never make
            # an otherwise schedulable program impossible.
            dates_to_try = all_dates

            for _, venue in venues.iterrows():
                if not venue_is_compatible(program, venue):
                    continue

                for event_date in dates_to_try:
                    minutes = (
                        DAY_START.hour * 60 + DAY_START.minute
                    )
                    last_start = (
                        DAY_END.hour * 60 + DAY_END.minute
                    )

                    while minutes < last_start:
                        start_time = time(
                            minutes // 60, minutes % 60
                        )

                        candidate = make_candidate(
                            program, venue, event_date, start_time
                        )

                        if candidate["end_dt"].time() <= DAY_END:
                            candidate["score"] = preferred_score(
                                program,
                                event_date,
                                candidate["start_dt"],
                                candidate["end_dt"],
                            )
                            program_candidates.append(candidate)

                        minutes += SLOT_MINUTES

        candidates.extend(program_candidates)
        candidates_by_program[program_id] = program_candidates

    return candidates, candidates_by_program


# =========================================================
# 4. OPTIMIZATION MODEL
# =========================================================

def assignments_conflict(a, b):
    """Check overlap, including the venue's setup buffer."""

    if a["venue_id"] != b["venue_id"]:
        return False

    return (
        a["start_dt"] < b["occupied_end"]
        and b["start_dt"] < a["occupied_end"]
    )


def check_fixed_conflicts(candidates):
    """Fail clearly if two fixed events conflict."""

    fixed = [c for c in candidates if c["fixed"]]

    for i, first in enumerate(fixed):
        for second in fixed[i + 1:]:
            if assignments_conflict(first, second):
                raise SchedulingDataError(
                    "Fixed-event conflict: "
                    f"{first['program_id']} and "
                    f"{second['program_id']} overlap at "
                    f"{first['venue_name']}."
                )


def optimize_schedule(programs, venues):
    """Find a valid schedule and maximize scheduled programs."""

    candidates, candidates_by_program = generate_candidates(
        programs, venues
    )

    check_fixed_conflicts(candidates)

    model = cp_model.CpModel()

    # Each candidate gets a Boolean decision variable.
    candidate_vars = {
        i: model.NewBoolVar(f"assignment_{i}")
        for i in range(len(candidates))
    }

    unscheduled_vars = {}

    # Each flexible program is scheduled once or marked unscheduled.
    # Fixed programs must retain their exact assignment.
    for _, program in programs.iterrows():
        program_id = str(program["program_id"])

        indices = [
            i for i, candidate in enumerate(candidates)
            if candidate["program_id"] == program_id
        ]

        if program["time_type"] == "fixed":
            model.AddExactlyOne(
                [candidate_vars[i] for i in indices]
            )
        else:
            unscheduled = model.NewBoolVar(
                f"unscheduled_{program_id}"
            )
            unscheduled_vars[program_id] = unscheduled

            model.AddExactlyOne(
                [candidate_vars[i] for i in indices]
                + [unscheduled]
            )

    # Two conflicting assignments cannot both be selected.
    for i, first in enumerate(candidates):
        for j in range(i + 1, len(candidates)):
            second = candidates[j]

            if assignments_conflict(first, second):
                model.Add(
                    candidate_vars[i] + candidate_vars[j] <= 1
                )

    # Scheduling a program is much more valuable than a preference.
    # Preferences are optimized only after maximizing coverage.
    objective_terms = []

    for i, candidate in enumerate(candidates):
        objective_terms.append(
            (1_000_000 + candidate["score"]) * candidate_vars[i]
        )

    for unscheduled in unscheduled_vars.values():
        objective_terms.append(-1_000_000 * unscheduled)

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = (
        SOLVER_TIME_LIMIT_SECONDS
    )
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingDataError(
            "No feasible schedule found. Check fixed events "
            "and the available scheduling window."
        )

    scheduled = []

    for i, candidate in enumerate(candidates):
        if solver.Value(candidate_vars[i]):
            scheduled.append({
                "program_id": candidate["program_id"],
                "program_name": candidate["program_name"],
                "date": candidate["event_date"].isoformat(),
                "start_time": candidate["start_dt"].strftime("%H:%M"),
                "end_time": candidate["end_dt"].strftime("%H:%M"),
                "venue_id": candidate["venue_id"],
                "venue_name": candidate["venue_name"],
                "time_type": (
                    "fixed" if candidate["fixed"] else "flexible"
                ),
                "status": "scheduled",
                "reason": "",
            })

    for program_id, unscheduled in unscheduled_vars.items():
        if solver.Value(unscheduled):
            program = programs[
                programs["program_id"].astype(str) == program_id
            ].iloc[0]

            reason = (
                "No compatible venue or time slot."
                if not candidates_by_program[program_id]
                else "Could not be scheduled without conflicts."
            )

            scheduled.append({
                "program_id": program_id,
                "program_name": str(program["program_name"]),
                "date": "",
                "start_time": "",
                "end_time": "",
                "venue_id": "",
                "venue_name": "",
                "time_type": "flexible",
                "status": "unscheduled",
                "reason": reason,
            })

    result = pd.DataFrame(scheduled)

    result = result.sort_values(
        by=["date", "start_time", "venue_id"],
        na_position="last",
    )

    return result, solver.StatusName(status)


# =========================================================
# 5. SAVE RESULTS
# =========================================================

def main():
    try:
        programs, venues = load_data()
        validate_data(programs, venues)

        schedule, solver_status = optimize_schedule(
            programs, venues
        )

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        schedule.to_csv(OUTPUT_FILE, index=False)

        print(f"Solver status: {solver_status}")
        print(f"Programs received: {len(programs)}")
        print(
            "Scheduled:",
            int((schedule["status"] == "scheduled").sum()),
        )
        print(
            "Unscheduled:",
            int((schedule["status"] == "unscheduled").sum()),
        )
        print(f"Output saved to: {OUTPUT_FILE}")

        print("\nSchedule preview:")
        print(schedule.to_string(index=False))

    except (FileNotFoundError, SchedulingDataError, ValueError) as error:
        print(f"Scheduling error: {error}")


if __name__ == "__main__":
    main()
