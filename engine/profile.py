"""Client profiles: each expo's own rules, kept in a JSON file.

{
  "client_name": "...", "expo_name": "...", "description": "...",
  "start_date": "2026-11-10", "end_date": "2026-11-11",
  "day_start": "09:00", "day_end": "16:00", "slot_minutes": 15,
  "allow_setup_after_close": false,
  "priorities": ["keep_approved", "schedule_count", "stability", "preferences", "room_fit"],
  "freeze_window_days": 1
}
Every key is optional; missing ones take the engine defaults.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from .config import PRIORITY_LEVELS, EngineConfig
from .data import fmt_minutes, parse_minutes


class ProfileError(ValueError):
    """The profile has invalid values; .problems lists them in Arabic."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass
class ClientProfile:
    client_name: str
    expo_name: str
    description: str
    config: EngineConfig
    freeze_window_days: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        c = self.config
        return {
            "client_name": self.client_name,
            "expo_name": self.expo_name,
            "description": self.description,
            "start_date": c.start_date.isoformat(),
            "end_date": c.end_date.isoformat(),
            "day_start": fmt_minutes(c.day_start_min),
            "day_end": fmt_minutes(c.day_end_min),
            "slot_minutes": c.slot_minutes,
            "allow_setup_after_close": c.allow_setup_after_close,
            "priorities": list(c.priorities),
            "freeze_window_days": self.freeze_window_days,
            **self.extra,
        }


def _time(value, label, problems):
    try:
        minutes = parse_minutes(value)
        if minutes is None:
            raise ValueError
        return minutes
    except ValueError:
        problems.append(f"{label}: «{value}» ليس وقتًا صالحًا (HH:MM).")
        return None


def profile_from_dict(raw: dict, base: EngineConfig | None = None) -> ClientProfile:
    base = base or EngineConfig()
    problems: list[str] = []
    known = {
        "client_name", "expo_name", "description", "start_date", "end_date", "day_start",
        "day_end", "slot_minutes", "allow_setup_after_close",
        "priorities", "freeze_window_days",
    }
    changes = {}

    for key in ("start_date", "end_date"):
        if key in raw:
            try:
                changes[key] = date.fromisoformat(str(raw[key]))
            except ValueError:
                problems.append(f"{key}: «{raw[key]}» ليس تاريخًا صالحًا (YYYY-MM-DD).")

    for key in ("day_start", "day_end"):
        if key in raw:
            minutes = _time(raw[key], key, problems)
            if minutes is not None:
                from datetime import time
                changes[key] = time(minutes // 60, minutes % 60)

    if "slot_minutes" in raw:
        if isinstance(raw["slot_minutes"], int) and not isinstance(raw["slot_minutes"], bool) and raw["slot_minutes"] > 0:
            changes["slot_minutes"] = raw["slot_minutes"]
        else:
            problems.append("slot_minutes يجب أن يكون عددًا صحيحًا موجبًا.")

    for key in ("allow_setup_after_close",):
        if key in raw:
            if isinstance(raw[key], bool):
                changes[key] = raw[key]
            else:
                problems.append(f"{key} يجب أن تكون true أو false.")

    if "priorities" in raw:
        order = list(raw["priorities"] or [])
        if sorted(order) != sorted(PRIORITY_LEVELS):
            problems.append("priorities يجب أن تحتوي كل الأهداف مرة واحدة: " + "، ".join(PRIORITY_LEVELS) + ".")
        else:
            changes["priorities"] = tuple(order)

    freeze = raw.get("freeze_window_days", 0)
    if isinstance(freeze, bool) or not isinstance(freeze, int) or freeze < 0:
        problems.append("freeze_window_days يجب أن يكون عددًا صحيحًا غير سالب.")
        freeze = 0

    config = replace(base, **changes)
    problems.extend(config.problems())
    if problems:
        raise ProfileError(problems)

    return ClientProfile(
        client_name=str(raw.get("client_name", "")),
        expo_name=str(raw.get("expo_name", "")),
        description=str(raw.get("description", "")),
        config=config,
        freeze_window_days=freeze,
        extra={k: v for k, v in raw.items() if k not in known},
    )


def load_profile(path, base: EngineConfig | None = None) -> ClientProfile:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return profile_from_dict(raw, base)
