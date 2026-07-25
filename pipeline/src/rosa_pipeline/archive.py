"""Forecast archive - the memory that makes lead-time skill measurable (roadmap Stage 0).

The nowcast check in ``verify`` only scores ~0-lead skill (today's forecast vs recent obs).
To answer "how good is our *day-5* forecast?" we must have SAVED the forecast we made 5 days
ago, then compare it to what the buoy actually observed. This module is that store.

Each scheduled ``archive`` run appends, per buoy, the model's offshore field for every
forecast hour, stamped with the run time - one JSONL row per (run, valid) pair:
    {"run": "<iso>", "valid": "<iso>", "hs": float|None, "tp": float|None, "dir": float|None}
Lead time = valid - run. The clock can't be back-filled, so this starts accumulating now.

Storage is behind ``ArchiveStore`` so the local filesystem (today) and an S3-compatible
bucket (R2, when the pipeline moves off GitHub Actions) are the same code path - no rework.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import SpectralSea
from .verify import WavePoint


def rows_from_model(run_time: datetime, model: list[WavePoint]) -> list[dict]:
    """Shape a run's forecast into append-ready archive rows."""
    run_iso = run_time.isoformat(timespec="seconds")
    return [
        {
            "run": run_iso,
            "valid": p.time.isoformat(timespec="seconds"),
            "hs": p.hs,
            "tp": p.tp,
            "dir": p.dir,
        }
        for p in model
    ]


def rows_from_spectral(run_time: datetime, series: list[SpectralSea]) -> list[dict]:
    """ECMWF-member archive rows: the scorecard triple (tp = pp1d, a PEAK period) plus
    the consistency-proxy inputs mwp/mp2 - extra keys the scorecard simply ignores, but
    the Stage-3b model-vs-measured-spectra validation needs (verify --spectra)."""
    run_iso = run_time.isoformat(timespec="seconds")
    return [
        {
            "run": run_iso,
            "valid": s.time.isoformat(timespec="seconds"),
            "hs": s.swh,
            "tp": s.pp1d,
            "dir": s.mwd,
            "mwp": s.mwp,
            "mp2": s.mp2,
        }
        for s in series
    ]


class ArchiveStore(Protocol):
    def append(self, key: str, rows: list[dict]) -> None: ...

    def read(self, key: str) -> list[dict]: ...


class FileArchiveStore:
    """JSONL-per-key on the local filesystem. ``key`` is the buoy id.

    Append-only and newline-delimited so a run only ever adds bytes - cheap, and an
    interrupted write can at worst leave a trailing partial line, which ``read`` skips."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.jsonl"

    def append(self, key: str, rows: list[dict]) -> None:
        if not rows:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self._path(key).open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    def read(self, key: str) -> list[dict]:
        path = self._path(key)
        if not path.exists():
            return []
        rows: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # tolerate a trailing partial line from an interrupted append
        return rows
