
import unittest
from datetime import date, time

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


if __name__ == "__main__":
    unittest.main()

