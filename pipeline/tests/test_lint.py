"""The CI lint gates, in the suite: every session runs pytest before it commits, so an
unformatted or lint-failing file fails here instead of turning main's checks red after
the push (2026-09-26: an unformatted sdb.py kept CI red for five commits)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]


def _ruff(*args: str) -> subprocess.CompletedProcess:
    exe = shutil.which("ruff")
    cmd = [exe] if exe else [sys.executable, "-m", "ruff"]
    return subprocess.run([*cmd, *args], cwd=PIPELINE, capture_output=True, text=True)


def _available() -> bool:
    try:
        return _ruff("--version").returncode == 0
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _available(), reason="ruff is not installed")


def test_ruff_format_is_clean():
    r = _ruff("format", "--check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_ruff_check_is_clean():
    r = _ruff("check", "-q")
    assert r.returncode == 0, r.stdout + r.stderr
