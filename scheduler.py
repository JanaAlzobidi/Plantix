from datetime import date, datetime, time, timedelta

import pandas as pd
from ortools.sat.python import cp_model


START_DATE = date(2026, 10, 17)
END_DATE = date(2026, 10, 19)
DAY_START = time(9, 0)
DAY_END = time(18, 0)
SLOT_MINUTES = 15
SOLVER_TIME_LIMIT_SECONDS = 20


class SchedulingDataError(ValueError):
    """Raised when event or venue data is invalid."""


def split_values(value):
    if pd.isna(value) or not str(value).strip():
        return set()
    return {part.strip() for part in str(value).split(";") if part.strip()}


def parse_date(value):
    if pd.isna(value) or not str(value).strip():
        return None
    return pd.to_datetime(value, errors="raise").date()


def parse_time(value):
    if pd.isna(value) or not str(value).strip():
        return None
    return pd.to_datetime(str(value), format="%H:%M", errors="raise").time()


def validate_data(programs, venues):
    required_program_columns = {
        "program_id", "program_name", "duration_min",
        "attendance_value", "venue_requirements", "time_type",
        "fixed_date", "fixed_start_time", "fixed_venue_id",
        "preferred_dates", "preferred_time_slots",
    }
    required_venue_columns = {
        "venue_id", "venue_name", "capacity", "equipment",
        "min_setup_time_min", "status",
    }

    missing_program = required_program_columns - set(programs.columns)
    missing_venue = required_venue_columns - set(venues.columns)

    if missing_program:
        raise SchedulingDataError(
            f"Missing program columns: {sorted(missing_program)}"
        )
    if missing_venue:
        raise SchedulingDataError(
            f"Missing venue columns: {sorted(missing_venue)}"
        )

    if programs["program_id"].duplicated().any():
        raise SchedulingDataError("Duplicate program_id found.")
    if venues["venue_id"].duplicated().any():
        raise SchedulingDataError("Duplicate venue_id found.")

    if programs["program_id"].isna().any() or venues["venue_id"].isna().any():
        raise SchedulingDataError("IDs cannot be empty.")

    for _, program in programs.iterrows():
        try:
            duration = int(program["duration_min"])
            attendance = int(program["attendance_value"])
        except (ValueError, TypeError):
            raise SchedulingDataError("Duration and attendance must be integers.")

        if duration <= 0 or duration % SLOT_MINUTES != 0:
            raise SchedulingDataError(
                f"{program['program_id']}: duration must be a positive "
                f"multiple of {SLOT_MINUTES} minutes."
            )
        if attendance < 0:
            raise SchedulingDataError(
                f"{program['program_id']}: attendance cannot be negative."
            )

        if program["time_type"] not in {"fixed", "flexible"}:
            raise SchedulingDataError(
                f"{program['program_id']}: time_type must be fixed or flexible."
            )

        if program["time_type"] == "fixed":
            if not str(program["fixed_venue_id"]).strip():
                raise SchedulingDataError(
                    f"{program['program_id']}: fixed venue is required."
                )
            try:
                event_date = parse_date(program["fixed_date"])
                start_time = parse_time(program["fixed_start_time"])
            except (ValueError, TypeError):
                raise SchedulingDataError(
                    f"{program['program_id']}: invalid fixed date or time."
                )
            if event_date is None or start_time is None:
                raise SchedulingDataError(
                    f"{program['program_id']}: fixed date and time are required."
                )

    for _, venue in venues.iterrows():
        try:
            capacity = int(venue["capacity"])
            setup = int(venue["min_setup_time_min"])
        except (ValueError, TypeError):
            raise SchedulingDataError("Venue capacity and setup must be integers.")

        if capacity <= 0 or setup < 0:
            raise SchedulingDataError(
                f"{venue['venue_id']}: invalid capacity or setup time."
            )


def venue_is_compatible(program, venue):
    if str(venue["status"]).strip().lower() != "available":
        return False

    if int(venue["capacity"]) < int(program["attendance_value"]):
        return False

    required = split_values(program["venue_requirements"])
    available = split_values(venue["equipment"])
    return required.issubset(available)


def make_candidate(program, venue, event_date, start_time):
    start_dt = datetime.combine(event_date, start_time)
    end_dt = start_dt + timedelta(minutes=int(program["duration_min"]))
    occupied_end_dt = end_dt + timedelta(
        minutes=int(venue["min_setup_time_min"])
    )

    return {
        "program_id": program["program_id"],
        "program_name": program["program_name"],
        "date": event_date.isoformat(),
        "start_time": start_dt.strftime("%H:%M"),
        "end_time": end_dt.strftime("%H:%M"),
        "occupied_end": occupied_end_dt.strftime("%H:%M"),
        "venue_id": venue["venue_id"],
        "venue_name": venue["venue_name"],
        "attendance": int(program["attendance_value"]),
        "time_type": program["time_type"],
    }


def preferred_score(program, event_date, start_time):
    score = 0

    preferred_dates = {
        str(d).strip()
        for d in split_values(program.get("preferred_dates", ""))
    }
    if event_date.isoformat() in preferred_dates:
        score += 1000

    time_range_score = 0
    for slot in split_values(program.get("preferred_time_slots", "")):
        try:
            start_text, end_text = slot.split("-", 1)
            preferred_start = parse_time(start_text.strip())
            preferred_end = parse_time(end_text.strip())
        except (ValueError, TypeError):
            continue

        if preferred_start <= start_time < preferred_end:
            time_range_score = max(time_range_score, 500)

    return score + time_range_score


def generate_candidates(programs, venues):
    candidates = {}
    candidate_lookup = {}

    for _, program in programs.iterrows():
        pid = program["program_id"]
        options = []

        compatible_venues = [
            venue for _, venue in venues.iterrows()
            if venue_is_compatible(program, venue)
        ]

        if program["time_type"] == "fixed":
            event_date = parse_date(program["fixed_date"])
            start_time = parse_time(program["fixed_start_time"])
            fixed_venue = venues[
                venues["venue_id"].astype(str)
                == str(program["fixed_venue_id"]).strip()
            ]

            if event_date is None or start_time is None:
                raise SchedulingDataError(f"{pid}: invalid fixed assignment.")

            if fixed_venue.empty:
                raise SchedulingDataError(f"{pid}: fixed venue does not exist.")

            venue = fixed_venue.iloc[0]
            if not venue_is_compatible(program, venue):
                raise SchedulingDataError(
                    f"{pid}: fixed venue is unavailable, too small, "
                    "or lacks required equipment."
                )

            if not START_DATE <= event_date <= END_DATE:
                raise SchedulingDataError(f"{pid}: fixed date is outside horizon.")

            candidate = make_candidate(program, venue, event_date, start_time)
            if (
                start_time < DAY_START
                or datetime.combine(event_date, start_time)
                + timedelta(minutes=int(program["duration_min"])) > datetime.combine(event_date, DAY_END)
            ):
                raise SchedulingDataError(
                    f"{pid}: fixed event is outside operating hours."
                )

            options.append(candidate)

        else:
            preferred_dates = split_values(program.get("preferred_dates", ""))
            dates = []
            current = START_DATE

            while current <= END_DATE:
                if not preferred_dates or current.isoformat() in preferred_dates:
                    dates.append(current)
                current += timedelta(days=1)

            for event_date in dates:
                current_time = datetime.combine(event_date, DAY_START)
                last_start = datetime.combine(event_date, DAY_END) - timedelta(
                    minutes=int(program["duration_min"])
                )

                while current_time <= last_start:
                    start_time = current_time.time()

                    for venue in compatible_venues:
                        options.append(
                            make_candidate(program, venue, event_date, start_time)
                        )

                    current_time += timedelta(minutes=SLOT_MINUTES)

        if not options:
            raise SchedulingDataError(
                f"{pid}: no feasible candidate exists. "
                "Check dates, requirements, capacity, and duration."
            )

        candidates[pid] = options

        for index, candidate in enumerate(options):
            candidate_lookup[(pid, index)] = candidate

    return candidates, candidate_lookup


def assignments_conflict(a, b):
    if a["venue_id"] != b["venue_id"] or a["date"] != b["date"]:
        return False

    a_start = datetime.strptime(a["start_time"], "%H:%M")
    a_end = datetime.strptime(a["occupied_end"], "%H:%M")
    b_start = datetime.strptime(b["start_time"], "%H:%M")
    b_end = datetime.strptime(b["occupied_end"], "%H:%M")

    return a_start < b_end and b_start < a_end


def check_fixed_conflicts(candidates, programs):
    fixed_ids = set(
        programs.loc[programs["time_type"] == "fixed", "program_id"]
    )
    fixed_candidates = [
        candidate
        for pid, options in candidates.items()
        if pid in fixed_ids
        for candidate in options
    ]

    for i, first in enumerate(fixed_candidates):
        for second in fixed_candidates[i + 1:]:
            if assignments_conflict(first, second):
                raise SchedulingDataError(
                    f"Fixed events conflict: {first['program_id']} and "
                    f"{second['program_id']}."
                )


def optimize_schedule(programs, venues):
    validate_data(programs, venues)
    candidates, lookup = generate_candidates(programs, venues)
    check_fixed_conflicts(candidates, programs)

    model = cp_model.CpModel()
    selected = {}
    scheduled = {}

    for pid, options in candidates.items():
        scheduled[pid] = model.NewBoolVar(f"scheduled_{pid}")
        vars_for_program = []

        for index, _ in enumerate(options):
            var = model.NewBoolVar(f"assign_{pid}_{index}")
            selected[(pid, index)] = var
            vars_for_program.append(var)

        model.Add(sum(vars_for_program) == scheduled[pid])

        program = programs.loc[programs["program_id"] == pid].iloc[0]
        if program["time_type"] == "fixed":
            model.Add(scheduled[pid] == 1)

    all_keys = list(selected.keys())

    for i, first_key in enumerate(all_keys):
        first = lookup[first_key]

        for second_key in all_keys[i + 1:]:
            second = lookup[second_key]

            if first["program_id"] == second["program_id"]:
                continue

            if assignments_conflict(first, second):
                model.Add(selected[first_key] + selected[second_key] <= 1)

    objective_terms = []

    for pid, options in candidates.items():
        objective_terms.append(1_000_000 * scheduled[pid])

        program = programs.loc[programs["program_id"] == pid].iloc[0]
        for index, candidate in enumerate(options):
            score = preferred_score(
                program,
                date.fromisoformat(candidate["date"]),
                parse_time(candidate["start_time"]),
            )
            if score:
                objective_terms.append(score * selected[(pid, index)])

    model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SECONDS
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingDataError(
            "No feasible schedule could be found for the fixed assignments."
        )

    rows = []
    for key, var in selected.items():
        if solver.Value(var):
            rows.append(lookup[key])

    schedule = pd.DataFrame(rows)
    if schedule.empty:
        schedule = pd.DataFrame(columns=[
            "program_id", "program_name", "date", "start_time",
            "end_time", "occupied_end", "venue_id", "venue_name",
            "attendance", "time_type",
        ])

    scheduled_ids = set(schedule["program_id"])
    unscheduled_ids = set(programs["program_id"]) - scheduled_ids

    unscheduled = pd.DataFrame([
        {
            "program_id": pid,
            "program_name": programs.loc[
                programs["program_id"] == pid, "program_name"
            ].iloc[0],
            "reason": "No conflict-free compatible time and venue found.",
        }
        for pid in sorted(unscheduled_ids)
    ])

    status_name = solver.StatusName(status)
    return schedule.sort_values(["date", "start_time"]).reset_index(drop=True), status_name


def load_data():
    programs = pd.read_csv("data/programs.csv", keep_default_na=False)
    venues = pd.read_csv("data/venues.csv", keep_default_na=False)
    return programs, venues


def main():
    programs, venues = load_data()
    schedule, status = optimize_schedule(programs, venues)

    schedule.to_csv("data/schedule_output.csv", index=False)

    print(f"Solver status: {status}")
    print(f"Scheduled programs: {len(schedule)}")
    print(schedule.to_string(index=False))


if __name__ == "__main__":
    main()

