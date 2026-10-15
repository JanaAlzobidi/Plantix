"""Engine settings: scheduling horizon, operating hours and solver limits."""

from dataclasses import dataclass
from datetime import date, time, timedelta


AVAILABLE_STATUS = "available"
VENUE_STATUSES = frozenset({"available", "maintenance", "unavailable"})

FIXED = "fixed"
FLEXIBLE = "flexible"


@dataclass(frozen=True)
class EngineConfig:
    start_date: date = date(2026, 10, 17)
    end_date: date = date(2026, 10, 19)
    day_start: time = time(9, 0)
    day_end: time = time(18, 0)

    # Flexible events may start every `slot_minutes` from `day_start`.
    slot_minutes: int = 15

    # Venue setup time may run past closing time. The event itself never may.
    allow_setup_after_close: bool = True

    solver_time_limit_seconds: float = 20.0
    solver_workers: int = 8

    @property
    def day_start_min(self) -> int:
        return self.day_start.hour * 60 + self.day_start.minute

    @property
    def day_end_min(self) -> int:
        return self.day_end.hour * 60 + self.day_end.minute

    @property
    def day_length_min(self) -> int:
        return self.day_end_min - self.day_start_min

    def horizon_days(self) -> list[date]:
        days = []
        current = self.start_date
        while current <= self.end_date:
            days.append(current)
            current += timedelta(days=1)
        return days

    def problems(self) -> list[str]:
        found = []
        if self.start_date > self.end_date:
            found.append("تاريخ بداية فترة الجدولة بعد تاريخ نهايتها.")
        if self.day_start_min >= self.day_end_min:
            found.append("بداية ساعات التشغيل يجب أن تسبق نهايتها.")
        if self.slot_minutes <= 0:
            found.append("طول الشريحة الزمنية يجب أن يكون موجبًا.")
        if self.solver_time_limit_seconds <= 0:
            found.append("مهلة المحلل يجب أن تكون موجبة.")
        return found


def in_freeze_window(day: date, reference_date: date, freeze_window_days: int) -> bool:
    """A day is frozen when 0 <= (day - reference_date) <= N. N = 0 means no freeze."""
    if freeze_window_days <= 0:
        return False
    return 0 <= (day - reference_date).days <= freeze_window_days
