"""Files on disk. The proposal and the approved schedule never share a file.

data/
  programs.csv, venues.csv     inputs
  approved_schedule.csv        the approved schedule (read as "current")
  proposal/                    latest proposal: schedule, unscheduled, changes, issues, summary.json
  approved_history/            each approved schedule that was replaced, timestamped
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .report import ScheduleResult


APPROVED_COLUMNS = [
    "program_id", "program_name", "date", "start_time", "end_time", "venue_id", "venue_name",
]


class ApprovalError(RuntimeError):
    """The proposal cannot be approved as it stands."""


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @classmethod
    def at(cls, root="data") -> "DataPaths":
        return cls(Path(root))

    @property
    def programs(self) -> Path:
        return self.root / "programs.csv"

    @property
    def venues(self) -> Path:
        return self.root / "venues.csv"

    @property
    def approved(self) -> Path:
        return self.root / "approved_schedule.csv"

    @property
    def proposal_dir(self) -> Path:
        return self.root / "proposal"

    @property
    def history_dir(self) -> Path:
        return self.root / "approved_history"


def read_csv(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def load_inputs(paths: DataPaths):
    """Returns (programs, venues, approved_or_None)."""
    approved = read_csv(paths.approved) if paths.approved.exists() else None
    return read_csv(paths.programs), read_csv(paths.venues), approved


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, write) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        write(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    # utf-8-sig so Excel shows Arabic text correctly.
    _atomic_write(path, lambda tmp: frame.to_csv(tmp, index=False, encoding="utf-8-sig"))


def _input_fingerprint(paths: DataPaths) -> dict:
    return {
        "programs_sha256": file_sha256(paths.programs),
        "venues_sha256": file_sha256(paths.venues),
        "approved_sha256": file_sha256(paths.approved),
    }


def save_proposal(result: ScheduleResult, paths: DataPaths) -> Path:
    """Writes the proposal. The approved schedule is not touched."""
    out = paths.proposal_dir
    _write_csv(result.schedule, out / "schedule.csv")
    _write_csv(result.unscheduled, out / "unscheduled.csv")
    _write_csv(result.changes, out / "changes.csv")
    _write_csv(result.issues, out / "issues.csv")

    summary = dict(result.summary)
    summary["generated_at"] = datetime.now().isoformat(timespec="seconds")
    summary["inputs"] = _input_fingerprint(paths)
    summary["approved_at"] = None
    _atomic_write(
        out / "summary.json",
        lambda tmp: Path(tmp).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"),
    )
    return out


def approve_proposal(paths: DataPaths) -> Path:
    """Makes the saved proposal the approved schedule, keeping the old one in history."""
    summary_path = paths.proposal_dir / "summary.json"
    if not summary_path.exists():
        raise ApprovalError("لا يوجد جدول مقترح محفوظ لاعتماده.")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    if summary.get("approved_at"):
        raise ApprovalError(f"هذا المقترح اعتُمد مسبقًا ({summary['approved_at']}).")
    if not summary.get("can_approve"):
        raise ApprovalError("لا يمكن اعتماد المقترح لأنه يحتوي على أخطاء مانعة؛ راجع issues.csv.")
    if summary.get("inputs") != _input_fingerprint(paths):
        raise ApprovalError(
            "تغيّرت ملفات البرامج أو القاعات أو الجدول المعتمد بعد إنشاء هذا المقترح؛ أعد إنشاء المقترح ثم اعتمده."
        )

    proposed = read_csv(paths.proposal_dir / "schedule.csv")

    if paths.approved.exists():
        paths.history_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(paths.approved, paths.history_dir / f"approved_schedule_{stamp}.csv")

    _write_csv(proposed[APPROVED_COLUMNS], paths.approved)

    summary["approved_at"] = datetime.now().isoformat(timespec="seconds")
    _atomic_write(
        summary_path,
        lambda tmp: Path(tmp).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"),
    )
    return paths.approved
