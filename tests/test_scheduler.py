import unittest

import pandas as pd

from scheduler import (
    SchedulingDataError,
    assignments_conflict,
    generate_candidates,
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


class SchedulerTests(unittest.TestCase):

    def test_fixed_event_keeps_its_assignment(self):
        programs = sample_programs()
        venues = sample_venues()

        schedule, _ = optimize_schedule(programs, venues)

        fixed = schedule[schedule["program_id"] == "P1"].iloc[0]
        self.assertEqual(fixed["date"], "2026-10-17")
        self.assertEqual(fixed["start_time"], "09:00")
        self.assertEqual(fixed["venue_id"], "V2")

    def test_incompatible_venue_is_not_selected(self):
        programs = sample_programs()
        venues = sample_venues()

        schedule, _ = optimize_schedule(programs, venues)

        flexible = schedule[schedule["program_id"] == "P2"]
        self.assertFalse(
            (flexible["venue_id"] == "V1").any()
            if not flexible.empty else False
        )

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
        venues = sample_venues()
        programs.loc[0, "duration_min"] = -10

        with self.assertRaises(SchedulingDataError):
            validate_data(programs, venues)

    def test_generated_schedule_has_no_venue_conflicts(self):
        programs = sample_programs()
        venues = sample_venues()

        schedule, _ = optimize_schedule(programs, venues)

        for _, group in schedule.groupby(["venue_id", "date"]):
            events = group.sort_values("start_time").to_dict("records")

            for first, second in zip(events, events[1:]):
                self.assertGreaterEqual(
                    second["start_time"],
                    first["occupied_end"],
                )

    def test_frozen_event_keeps_previous_assignment(self):
        programs = sample_programs()
        venues = sample_venues()

        previous_schedule = pd.DataFrame([
            {
                "program_id": "P2",
                "program_name": "Flexible Workshop",
                "date": "2026-10-17",
                "start_time": "11:00",
                "end_time": "12:30",
                "occupied_end": "12:45",
                "venue_id": "V2",
                "venue_name": "Large Hall",
                "attendance": 20,
                "time_type": "flexible",
            }
        ])

        schedule, status = optimize_schedule(
            programs,
            venues,
            current_schedule=previous_schedule,
            freeze_window_days=3,
            reference_date="2026-10-14",
        )

        frozen = schedule[schedule["program_id"] == "P2"].iloc[0]
        self.assertEqual(frozen["date"], "2026-10-17")
        self.assertEqual(frozen["start_time"], "11:00")
        self.assertEqual(frozen["venue_id"], "V2")

    def test_frozen_event_blocks_same_venue_time(self):
        programs = sample_programs()
        venues = sample_venues()

        previous_schedule = pd.DataFrame([
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

        schedule, _ = optimize_schedule(
            programs,
            venues,
            current_schedule=previous_schedule,
            freeze_window_days=3,
            reference_date="2026-10-14",
        )

        frozen = schedule[schedule["program_id"] == "P2"].iloc[0]
        other_events = schedule[
            (schedule["venue_id"] == frozen["venue_id"])
            & (schedule["date"] == frozen["date"])
            & (schedule["program_id"] != "P2")
        ]

        for event in other_events.to_dict("records"):
            self.assertFalse(assignments_conflict(frozen.to_dict(), event))

    def test_invalid_freeze_window_is_rejected(self):
        programs = sample_programs()
        venues = sample_venues()

        with self.assertRaises(SchedulingDataError):
            optimize_schedule(
                programs,
                venues,
                freeze_window_days=-1,
                reference_date="2026-10-14",
            )


if __name__ == "__main__":
    unittest.main()

