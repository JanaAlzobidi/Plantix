from scheduler import load_data, validate_data, optimize_schedule
import unittest
from datetime import date, time
from scheduler import check_fixed_conflicts, SchedulingDataError
import pandas as pd

from scheduler import (
    make_candidate,
    assignments_conflict,
    venue_is_compatible,
    generate_candidates,
)


class TestScheduler(unittest.TestCase):

    def setUp(self):
        self.venue = {
            "venue_id": "V002",
            "venue_name": "Main Auditorium",
            "capacity": 120,
            "equipment": "Projector;Wi-Fi;Sound System",
            "min_setup_time_min": 30,
            "status": "available",
        }

        self.program = {
            "program_id": "P001",
            "program_name": "Test Event",
            "duration_min": 60,
            "attendance_value": 100,
            "venue_requirements": "Projector;Wi-Fi",
            "time_type": "flexible",
        }

    def test_setup_time_prevents_conflict(self):
        """A second event cannot start before setup finishes."""

        first = make_candidate(
            self.program, self.venue, date(2026, 10, 17), time(9, 0)
        )

        second = make_candidate(
            self.program, self.venue, date(2026, 10, 17), time(10, 15)
        )

        self.assertTrue(assignments_conflict(first, second))

    def test_event_can_start_after_setup(self):
        """A 30-minute setup buffer is sufficient."""

        first = make_candidate(
            self.program, self.venue, date(2026, 10, 17), time(9, 0)
        )

        second = make_candidate(
            self.program, self.venue, date(2026, 10, 17), time(10, 30)
        )

        self.assertFalse(assignments_conflict(first, second))

    def test_incompatible_venue_is_rejected(self):
        """A venue must have all required equipment."""

        venue = self.venue.copy()
        venue["equipment"] = "Projector;Wi-Fi"

        program = self.program.copy()
        program["venue_requirements"] = "Projector;VR Headsets"

        self.assertFalse(venue_is_compatible(program, venue))

    def test_insufficient_capacity_is_rejected(self):
        """A venue must accommodate the expected attendance."""

        venue = self.venue.copy()
        venue["capacity"] = 50

        self.assertFalse(venue_is_compatible(self.program, venue))

    def test_unavailable_venue_is_rejected(self):
        """A closed or maintained venue cannot be assigned."""

        venue = self.venue.copy()
        venue["status"] = "under_maintenance"

        self.assertFalse(venue_is_compatible(self.program, venue))

    def test_fixed_event_keeps_its_assignment(self):
        """A fixed event must retain its specified date, time and venue."""

        program = {
            **self.program,
            "time_type": "fixed",
            "fixed_date": "2026-10-17",
            "fixed_start_time": "11:00",
            "fixed_venue_id": "V002",
            "preferred_dates": "",
            "preferred_time_slots": "",
        }

        programs = pd.DataFrame([program])
        venues = pd.DataFrame([self.venue])

        candidates, by_program = generate_candidates(programs, venues)

        self.assertEqual(len(candidates), 1)

        candidate = by_program["P001"][0]
        self.assertTrue(candidate["fixed"])
        self.assertEqual(candidate["event_date"], date(2026, 10, 17))
        self.assertEqual(candidate["start_dt"].time(), time(11, 0))
        self.assertEqual(candidate["venue_id"], "V002")


    def test_conflicting_fixed_events_are_rejected(self):
        """Two fixed events cannot overlap in the same venue."""

        first = {
            "program_id": "P001",
            "venue_id": "V002",
            "venue_name": "Main Auditorium",
            "start_dt": pd.Timestamp("2026-10-17 09:00"),
            "end_dt": pd.Timestamp("2026-10-17 10:00"),
            "occupied_end": pd.Timestamp("2026-10-17 10:30"),
            "fixed": True,
        }

        second = {
            "program_id": "P007",
            "venue_id": "V002",
            "venue_name": "Main Auditorium",
            "start_dt": pd.Timestamp("2026-10-17 10:15"),
            "end_dt": pd.Timestamp("2026-10-17 11:15"),
            "occupied_end": pd.Timestamp("2026-10-17 11:45"),
            "fixed": True,
        }

        with self.assertRaises(SchedulingDataError):
            check_fixed_conflicts([first, second])


    def test_generated_schedule_has_no_venue_conflicts(self):
        """The generated schedule must not contain venue conflicts."""

        programs, venues = load_data()
        validate_data(programs, venues)

        schedule, status = optimize_schedule(programs, venues)

        scheduled = schedule[
            schedule["status"] == "scheduled"
        ].copy()

        self.assertGreater(len(scheduled), 0)

        for venue_id, group in scheduled.groupby("venue_id"):
            venue = venues[
                venues["venue_id"].astype(str) == str(venue_id)
            ].iloc[0]

            setup_minutes = int(venue["min_setup_time_min"])

            for event_date, daily_events in group.groupby("date"):
                events = daily_events.sort_values("start_time")

                previous_occupied_end = None

                for _, event in events.iterrows():
                    start = pd.to_datetime(
                        f"{event_date} {event['start_time']}"
                    )

                    if previous_occupied_end is not None:
                        self.assertGreaterEqual(
                            start,
                            previous_occupied_end,
                            f"Venue conflict in {venue_id} on {event_date}",
                        )

                    end = pd.to_datetime(
                        f"{event_date} {event['end_time']}"
                    )

                    previous_occupied_end = (
                        end + pd.Timedelta(minutes=setup_minutes)
                    )



if __name__ == "__main__":
    unittest.main()

