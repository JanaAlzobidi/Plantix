
import unittest

import pandas as pd

from scheduler import (
    SchedulingDataError,
    assignments_conflict,
    optimize_schedule,
    validate_data,
)


def sample_venues():
    return pd.DataFrame([
        {
            "venue_id": "V1",
            "venue_name": "Small Room",
            "capacity": 30,
            "equipment": "Projector;Wi-Fi",
            "min_setup_time_min": 15,
            "status": "available",
            "zone": "A",
        },
        {
            "venue_id": "V2",
            "venue_name": "Large Hall",
            "capacity": 100,
            "equipment": "Projector;Wi-Fi;Microphones",
            "min_setup_time_min": 30,
            "status": "available",
            "zone": "B",
        },
    ])


def sample_programs():
    return pd.DataFrame([
        {
            "program_id": "P1",
            "program_name": "Fixed Talk",
            "duration_min": 60,
            "attendance_value": 80,
            "attendance_mode": "confirmed",
            "venue_requirements": "Projector;Microphones",
            "time_type": "fixed",
            "fixed_date": "2026-10-17",
            "fixed_start_time": "09:00",
            "fixed_venue_id": "V2",
            "preferred_dates": "2026-10-17",
            "preferred_time_slots": "09:00-12:00",
        },
        {
            "program_id": "P2",
            "program_name": "Flexible Workshop",
            "duration_min": 90,
            "attendance_value": 20,
            "attendance_mode": "confirmed",
            "venue_requirements": "Projector;Wi-Fi;Microphones",
            "time_type": "flexible",
            "fixed_date": "",
            "fixed_start_time": "",
            "fixed_venue_id": "",
            "preferred_dates": "2026-10-17;2026-10-18",
            "preferred_time_slots": "09:00-12:00",
        },
    ])


def previous_schedule_for_p2():
    return pd.DataFrame([
        {
            "program_id": "P2",
            "program_name": "Flexible Workshop",
            "date": "2026-10-17",
            "start_time": "11:00",
            "end_time": "12:30",
            "occupied_end": "13:00",
            "venue_id": "V2",
            "venue_name": "Large Hall",
            "attendance": 20,
            "time_type": "flexible",
        }
    ])


class SchedulerTests(unittest.TestCase):

    def test_fixed_event_keeps_its_assignment(self):
        schedule, _ = optimize_schedule(
            sample_programs(),
            sample_venues(),
        )

        fixed = schedule[schedule["program_id"] == "P1"].iloc[0]

        self.assertEqual(fixed["date"], "2026-10-17")
        self.assertEqual(fixed["start_time"], "09:00")
        self.assertEqual(fixed["venue_id"], "V2")

    def test_incompatible_venue_is_not_selected(self):
        schedule, _ = optimize_schedule(
            sample_programs(),
            sample_venues(),
        )

        flexible = schedule[schedule["program_id"] == "P2"]

        if not flexible.empty:
            self.assertFalse((flexible["venue_id"] == "V1").any())

    def test_setup_time_prevents_conflict(self):
        first = {
            "venue_id": "V1",
            "date": "2026-10-17",
            "start_time": "09:00",
            "end_time": "10:00",
            "occupied_end": "10:15",
        }
        second = {
            "venue_id": "V1",
            "date": "2026-10-17",
            "start_time": "10:00",
            "end_time": "11:00",
            "occupied_end": "11:15",
        }

        self.assertTrue(assignments_conflict(first, second))

    def test_invalid_data_is_rejected(self):
        programs = sample_programs()
        programs.loc[0, "duration_min"] = -10

        with self.assertRaises(SchedulingDataError):
            validate_data(programs, sample_venues())

    def test_generated_schedule_has_no_venue_conflicts(self):
        schedule, _ = optimize_schedule(
            sample_programs(),
            sample_venues(),
        )

        for _, group in schedule.groupby(["venue_id", "date"]):
            events = group.sort_values("start_time").to_dict("records")

            for first, second in zip(events, events[1:]):
                self.assertGreaterEqual(
                    second["start_time"],
                    first["occupied_end"],
                )

    def test_existing_event_can_change_assignment_in_freeze_window(self):
        programs = sample_programs()
        venues = sample_venues()

        # Make the previous assignment conflict with the fixed event.
        # P2 must move from 11:00 to another feasible time.
        previous_schedule = previous_schedule_for_p2()

        schedule, _ = optimize_schedule(
            programs,
            venues,
            current_schedule=previous_schedule,
            freeze_window_days=3,
            reference_date="2026-10-14",
        )

        event = schedule[schedule["program_id"] == "P2"]

        self.assertEqual(len(event), 1)
        self.assertNotEqual(
            event.iloc[0]["start_time"],
            "11:00",
        )

    def test_new_flexible_event_is_not_scheduled_in_freeze_window(self):
        programs = sample_programs()
        venues = sample_venues()

        # P2 is new because it does not appear in the previous schedule.
        previous_schedule = pd.DataFrame(columns=[
            "program_id",
            "date",
            "start_time",
            "venue_id",
        ])

        schedule, _ = optimize_schedule(
            programs,
            venues,
            current_schedule=previous_schedule,
            freeze_window_days=3,
            reference_date="2026-10-14",
        )

        flexible = schedule[schedule["program_id"] == "P2"]

        if not flexible.empty:
            for event_date in flexible["date"]:
                days_until_event = (
                    pd.Timestamp(event_date).date()
                    - pd.Timestamp("2026-10-14").date()
                ).days

                self.assertFalse(0 <= days_until_event <= 3)

    def test_existing_event_does_not_create_venue_conflicts(self):
        schedule, _ = optimize_schedule(
            sample_programs(),
            sample_venues(),
            current_schedule=previous_schedule_for_p2(),
            freeze_window_days=3,
            reference_date="2026-10-14",
        )

        for _, group in schedule.groupby(["venue_id", "date"]):
            events = group.sort_values("start_time").to_dict("records")

            for first, second in zip(events, events[1:]):
                self.assertFalse(assignments_conflict(first, second))

    def test_invalid_freeze_window_is_rejected(self):
        with self.assertRaises(SchedulingDataError):
            optimize_schedule(
                sample_programs(),
                sample_venues(),
                freeze_window_days=-1,
                reference_date="2026-10-14",
            )


if __name__ == "__main__":
    unittest.main()
