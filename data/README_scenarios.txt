ExpoWise Scheduler Scenario Pack
=================================

All data is synthetic. The files are split intentionally so a negative test
does not prevent the main dataset from being scheduled.

FILES
-----
programs_core.csv
  20 programs: four fixed assignments designed to be valid in isolation,
  ten flexible existing IDs (E002-E009 plus fixed IDs in the set), and ten
  new flexible programs N001-N010. Use this for the general dashboard test.

programs_freeze_window.csv
  Six new flexible programs N101-N106. Use this as a clean, isolated test of
  freeze-window behavior. For a meaningful existing-vs-new comparison, the
  prior schedule passed to optimize_schedule must contain the existing IDs;
  these N IDs should not appear in that prior schedule.

venues_complex.csv
  Eight venues with capacity/equipment/setup variation; V08 is under maintenance.

Negative tests (each is intentionally expected to fail or be unscheduled):
  test_unavailable_fixed_venue.csv — fixed program uses V08 under maintenance.
  test_over_capacity.csv — attendance exceeds every venue capacity.
  test_missing_equipment.csv — requires quantum_projector, absent everywhere.
  test_fixed_conflict.csv — two fixed programs overlap in V01.

IMPORTANT
---------
1. Back up data/programs.csv, data/venues.csv, and data/schedule_output.csv.
2. The repository's current app.py reads programs.csv and venues.csv, not
   programs_core.csv / venues_complex.csv. Either temporarily copy a selected
   test file to the expected filename after backup, or change paths temporarily.
3. Keep the original approved/previous schedule separate. Current app code may
   overwrite schedule_output.csv on generation.
4. Freeze Window logic in scheduler.py filters new flexible candidates from
   dates where 0 <= (candidate date - reference_date).days <= freeze_window_days.
   With reference date 2026-10-15 and freeze_window_days=3, dates 15-18 Oct are
   filtered; the configured horizon begins 17 Oct, so new flexible programs
   can only use 19 Oct if a compatible candidate exists.
5. Current generate_candidates treats preferred_dates as a hard date filter;
   preferred_time_slots are not currently applied by the shown code.
6. If no candidate exists, generate_candidates raises SchedulingDataError rather
   than returning a partial schedule. That is expected for negative tests.
7. This pack does not alter code and does not assert that every scenario passes.
