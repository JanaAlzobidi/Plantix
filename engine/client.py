"""One expo = one client folder. The engine adapts to each client's rules.

clients/<name>/
  client.json             the expo's own rules (below)
  programs.csv            its programs; optional columns: category (feeds the
                          attendance model), admission (open | registration)
  venues.csv              its venues
  history.csv             optional: past editions, for attendance learning
  approved_schedule.csv   its approved schedule, once there is one

client.json holds every rule profile.py understands, plus a name and the AI
alert settings:
  {
    "name": "...",
    "start_date": "2026-10-17", "end_date": "2026-10-20",
    "day_start": "10:00", "day_end": "20:00",
    "slot_minutes": 15,
    "freeze_window_days": 3,
    "allow_setup_after_close": true,
    "priorities": ["keep_approved", "schedule_count", "stability", "preferences", "room_fit"],
    "attendance_alerts": {"enabled": true, "min_history": 3}
  }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import EngineConfig
from .profile import ProfileError, profile_from_dict
from .storage import DataPaths


REQUIRED_KEYS = ("name", "start_date", "end_date", "day_start", "day_end")
CLIENT_ONLY_KEYS = ("name", "attendance_alerts")


class ClientConfigError(ValueError):
    """client.json is missing or invalid."""


@dataclass(frozen=True)
class Client:
    name: str
    folder: Path
    config: EngineConfig
    freeze_window_days: int
    alerts_enabled: bool = True
    alerts_min_history: int = 3
    raw: dict = field(default_factory=dict)

    @property
    def paths(self) -> DataPaths:
        return DataPaths(self.folder)

    @property
    def history_path(self) -> Path:
        return self.folder / "history.csv"


def load_client(folder) -> Client:
    folder = Path(folder)
    path = folder / "client.json"
    if not path.exists():
        raise ClientConfigError(f"لا يوجد ملف client.json في {folder}.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ClientConfigError(f"client.json غير صالح: {exc}") from exc

    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        raise ClientConfigError(f"client.json: حقول ناقصة: {', '.join(missing)}.")

    rules = {k: v for k, v in raw.items() if k not in CLIENT_ONLY_KEYS}
    try:
        profile = profile_from_dict(rules)
    except ProfileError as exc:
        raise ClientConfigError("client.json: " + " ".join(exc.problems)) from exc

    alerts = raw.get("attendance_alerts", {}) or {}
    return Client(
        name=str(raw["name"]),
        folder=folder,
        config=profile.config,
        freeze_window_days=profile.freeze_window_days,
        alerts_enabled=bool(alerts.get("enabled", True)),
        alerts_min_history=int(alerts.get("min_history", 3)),
        raw=raw,
    )
