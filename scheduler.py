
from pathlib import Path

import pandas as pd


# Project paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

PROGRAMS_FILE = DATA_DIR / "programs.csv"
VENUES_FILE = DATA_DIR / "venues.csv"


class SchedulingDataError(Exception):
    """Raised when scheduling input data is invalid."""


def load_data():
    """Load programs and venues from CSV files."""

    if not PROGRAMS_FILE.exists():
        raise FileNotFoundError(
            f"Programs file not found: {PROGRAMS_FILE}"
        )

    if not VENUES_FILE.exists():
        raise FileNotFoundError(
            f"Venues file not found: {VENUES_FILE}"
        )

    programs = pd.read_csv(PROGRAMS_FILE)
    venues = pd.read_csv(VENUES_FILE)

    return programs, venues


def validate_data(programs, venues):
    """Validate the basic structure and values of input data."""

    required_program_columns = {
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
    }

    required_venue_columns = {
        "venue_id",
        "venue_name",
        "capacity",
        "equipment",
        "min_setup_time_min",
        "status",
    }

    missing_program_columns = (
        required_program_columns - set(programs.columns)
    )

    missing_venue_columns = (
        required_venue_columns - set(venues.columns)
    )

    if missing_program_columns:
        raise SchedulingDataError(
            f"Missing program columns: "
            f"{sorted(missing_program_columns)}"
        )

    if missing_venue_columns:
        raise SchedulingDataError(
            f"Missing venue columns: "
            f"{sorted(missing_venue_columns)}"
        )

    if programs["program_id"].isna().any():
        raise SchedulingDataError(
            "Every program must have a program_id."
        )

    if programs["program_id"].duplicated().any():
        raise SchedulingDataError(
            "program_id values must be unique."
        )

    if venues["venue_id"].isna().any():
        raise SchedulingDataError(
            "Every venue must have a venue_id."
        )

    if venues["venue_id"].duplicated().any():
        raise SchedulingDataError(
            "venue_id values must be unique."
        )

    if not programs["attendance_mode"].isin(
        ["confirmed", "estimated"]
    ).all():
        raise SchedulingDataError(
            "attendance_mode must be confirmed or estimated."
        )

    if not programs["time_type"].isin(
        ["fixed", "flexible"]
    ).all():
        raise SchedulingDataError(
            "time_type must be fixed or flexible."
        )

    if not venues["status"].isin(
        ["available", "under_maintenance", "closed"]
    ).all():
        raise SchedulingDataError(
            "Invalid venue status."
        )

    for column in ["duration_min", "attendance_value"]:
        values = pd.to_numeric(
            programs[column], errors="coerce"
        )

        if values.isna().any() or (values < 0).any():
            raise SchedulingDataError(
                f"{column} must contain non-negative numbers."
            )

    for column in ["capacity", "min_setup_time_min"]:
        values = pd.to_numeric(
            venues[column], errors="coerce"
        )

        if values.isna().any() or (values < 0).any():
            raise SchedulingDataError(
                f"{column} must contain non-negative numbers."
            )

    if (programs["duration_min"] <= 0).any():
        raise SchedulingDataError(
            "Program duration must be greater than zero."
        )

    if (venues["capacity"] <= 0).any():
        raise SchedulingDataError(
            "Venue capacity must be greater than zero."
        )

    if (programs["attendance_value"] % 1 != 0).any():
        raise SchedulingDataError(
            "Attendance values must be whole numbers."
        )

    if (venues["capacity"] % 1 != 0).any():
        raise SchedulingDataError(
            "Venue capacities must be whole numbers."
        )

    # Every fixed program needs a complete fixed assignment.
    fixed_programs = programs[
        programs["time_type"] == "fixed"
    ]

    fixed_columns = [
        "fixed_date",
        "fixed_start_time",
        "fixed_venue_id",
    ]

    if fixed_programs[fixed_columns].isna().any().any():
        raise SchedulingDataError(
            "Fixed programs need a date, start time, "
            "and venue ID."
        )

    known_venue_ids = set(venues["venue_id"].astype(str))

    fixed_venue_ids = set(
        fixed_programs["fixed_venue_id"].astype(str)
    )

    unknown_venues = fixed_venue_ids - known_venue_ids

    if unknown_venues:
        raise SchedulingDataError(
            f"Unknown fixed venue IDs: {sorted(unknown_venues)}"
        )

    return True


def main():
    """Load and validate data."""

    try:
        programs, venues = load_data()
        validate_data(programs, venues)

        print("Input data loaded successfully.")
        print(f"Programs: {len(programs)}")
        print(f"Venues: {len(venues)}")
        print("Data validation passed.")

    except (FileNotFoundError, SchedulingDataError) as error:
        print(f"Scheduling setup error: {error}")


if __name__ == "__main__":
    main()
