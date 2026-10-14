ExpoWise — Complex Scheduler Test Dataset
==========================================

Files
-----
- programs_complex.csv: 20 programs (10 intended existing IDs E001-E010, 10 new flexible IDs N001-N010)
- venues_complex.csv: 8 venues with varied capacity, equipment, setup times, and operational status

IMPORTANT
---------
These are synthetic test data. Keep a backup of your current data/programs.csv,
data/venues.csv, and data/schedule_output.csv before trying them.

Compatibility note:
The column names follow the current ExpoWise schema discussed in this project
(time_type, fixed_date, fixed_start_time, fixed_venue_id, preferred_dates,
preferred_time_slots; venue capacity/equipment/min_setup_time_min/status/zone).
Before replacing production files, check scheduler.py's validate_data() to ensure
its accepted status values and required columns match these headers.

Scenarios represented
---------------------
1. Fixed events: E001, E004, E007, E010.
2. Flexible existing events: E002, E003, E005, E006, E008, E009.
3. New flexible events: N001-N010. Their dates cover the full scheduling horizon;
   use them to test the freeze-window filter when their IDs are absent from the
   prior schedule.
4. Hard capacity constraints: several small rooms and large attendance values.
5. Equipment compatibility: VR, computers, stage, microphones, accessibility,
   display booths, lighting, and power requirements.
6. Setup buffers: venues use different setup durations to exercise overlap checks.
7. Unavailable venue: V08 is under maintenance and should not be selected.
8. Soft preferences: programs have preferred dates and morning/afternoon slots.
9. Confirmed versus estimated attendance: both modes are represented; attendance
   remains a supplied value and is not predicted by this dataset.

Suggested test sequence
-----------------------
A. Back up the current data files.
B. Copy programs_complex.csv to data/programs.csv and venues_complex.csv to data/venues.csv.
C. Keep a copy of the original schedule as the prior schedule, and ensure the
   existing IDs E001-E010 are represented in it if you want to test "existing"
   versus "new" program behavior.
D. Set Freeze Window to 3 days. With reference_date=2026-10-15, the current
   filter excludes new flexible assignments dated 2026-10-15 through 2026-10-18
   (inclusive); since this scheduling horizon starts on 2026-10-17, new flexible
   programs should only be eligible on 2026-10-19, if a compatible option exists.
E. Set Freeze Window to 0 and generate again; new flexible programs can use all
   eligible dates.
F. Inspect Review for unscheduled programs and test the reason shown. The current
   app may only display unscheduled program rows, not a detailed reason.
G. Try a separate negative test by temporarily increasing one program's attendance
   above every available venue's capacity or requesting equipment no venue has.
   This may currently raise SchedulingDataError instead of returning a partial
   schedule; that is a useful limitation to document and improve.

Fixed-event note
----------------
The fixed assignments in this dataset are deliberately valid in isolation. If a
fixed event has no compatible venue/time, or fixed events conflict, the current
scheduler may raise an error rather than produce a partial schedule.
