from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from scheduler import (
    SchedulingDataError,
    optimize_schedule,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROGRAMS_PATH = DATA_DIR / "programs.csv"
VENUES_PATH = DATA_DIR / "venues.csv"
OUTPUT_PATH = DATA_DIR / "schedule_output.csv"

st.set_page_config(
    page_title="ExpoWise | Manager Dashboard",
    page_icon="📅",
    layout="wide",
)

st.title("ExpoWise")
st.subheader("Manager Dashboard")
st.caption(
    "Manage event scheduling, review assignments, "
    "and monitor venue allocation."
)


@st.cache_data
def load_data():
    programs = pd.read_csv(PROGRAMS_PATH, keep_default_na=False)
    venues = pd.read_csv(VENUES_PATH, keep_default_na=False)
    return programs, venues


def load_previous_schedule():
    if OUTPUT_PATH.exists():
        try:
            return pd.read_csv(OUTPUT_PATH, keep_default_na=False)
        except (OSError, pd.errors.ParserError):
            return pd.DataFrame()
    return pd.DataFrame()


try:
    programs, venues = load_data()
except (OSError, pd.errors.ParserError) as exc:
    st.error(f"Could not load project data: {exc}")
    st.stop()


with st.sidebar:
    st.header("Scheduling Settings")
    freeze_window_days = st.number_input(
        "Freeze window (days)",
        min_value=0,
        max_value=30,
        value=3,
        step=1,
        help=(
            "The intended policy protects near-term assignments. "
            "Freeze-window integration is being developed."
        ),
    )

    st.info(
        "Current version: the freeze-window setting is displayed "
        "but is not yet applied when scheduling."
    )

    run_schedule = st.button(
        "Generate Schedule",
        type="primary",
        use_container_width=True,
    )


previous_schedule = load_previous_schedule()

if run_schedule:
    try:
        with st.spinner("Generating the schedule..."):

            schedule, solver_status = optimize_schedule(
                programs,
                venues,
                current_schedule=previous_schedule,
                freeze_window_days=int(freeze_window_days),
                reference_date=date.today(),
            )

            schedule.to_csv(OUTPUT_PATH, index=False)

        st.session_state["schedule"] = schedule
        st.session_state["solver_status"] = solver_status
        st.session_state["schedule_error"] = None

    except SchedulingDataError as exc:
        st.session_state["schedule_error"] = str(exc)


schedule = st.session_state.get("schedule")

if schedule is None:
    schedule = previous_schedule

error_message = st.session_state.get("schedule_error")
if error_message:
    st.error(error_message)

if schedule.empty:
    st.warning(
        "No schedule is available yet. Click Generate Schedule to begin."
    )
    st.stop()


scheduled_count = schedule["program_id"].nunique()
total_count = len(programs)
unscheduled_count = total_count - scheduled_count
fixed_count = (
    schedule["time_type"].eq("fixed").sum()
    if "time_type" in schedule.columns
    else 0
)

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Programs", total_count)
col2.metric("Scheduled", scheduled_count)
col3.metric("Unscheduled", unscheduled_count)
col4.metric("Fixed Assignments", int(fixed_count))

st.divider()

tab_schedule, tab_programs, tab_venues, tab_review = st.tabs(
    [
        "Schedule",
        "Programs",
        "Venues",
        "Review",
    ]
)

with tab_schedule:
    st.subheader("Event Schedule")

    display_columns = [
        column
        for column in [
            "date",
            "start_time",
            "end_time",
            "program_name",
            "venue_name",
            "attendance",
            "time_type",
        ]
        if column in schedule.columns
    ]

    st.dataframe(
        schedule[display_columns].sort_values(
            ["date", "start_time"]
        ),
        use_container_width=True,
        hide_index=True,
    )

    csv_data = schedule.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Schedule CSV",
        data=csv_data,
        file_name="schedule_output.csv",
        mime="text/csv",
    )

with tab_programs:
    st.subheader("Program Requests")
    st.dataframe(
        programs,
        use_container_width=True,
        hide_index=True,
    )

with tab_venues:
    st.subheader("Venue Availability")
    st.dataframe(
        venues,
        use_container_width=True,
        hide_index=True,
    )

with tab_review:
    st.subheader("Scheduling Review")

    scheduled_ids = set(schedule["program_id"])
    unscheduled = programs[
        ~programs["program_id"].isin(scheduled_ids)
    ]

    if unscheduled.empty:
        st.success("All programs are scheduled.")
    else:
        st.warning(
            f"{len(unscheduled)} program(s) need manual review."
        )
        st.dataframe(
            unscheduled[
                ["program_id", "program_name", "time_type"]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.caption(
        "Approval workflows, change previews, and freeze-window "
        "enforcement will be added in the next iteration."
    )

st.divider()
st.caption("ExpoWise • Intelligent Event Planning and Scheduling")
