"""The real ``scripts/setup_env.sh``, run as a real subprocess.

Every worker on this release is told to run that script, and its only failure path
is the one that matters on a host with the wrong Python: the guard that stops
before anything is created. U4 found that this path called a ``die`` that was
never defined, so the guard printed ``die: command not found`` and exited 127
instead of saying what was wrong.

The script is run for real, with a real interpreter standing in for the system
one, and the guard is made to fire: the stand-in reports Python 3.10, so the
script must print its version message and stop. Nothing else in the script runs,
which is exactly the point - a test that let the script continue would create a
virtualenv and install the package.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "setup_env.sh"

#: A stand-in interpreter old enough to fail the version guard. It only has to
#: answer the two things the script asks before it does anything: the version
#: test (which must fail) and ``-V`` (which must print a version).
OLD_PYTHON_STUB = """#!/usr/bin/env bash
for argument in "$@"; do
  case "$argument" in
    *version_info*) exit 1 ;;
  esac
done
echo "Python 3.10.12"
"""


@pytest.fixture
def old_python(tmp_path: Path) -> Path:
    """An executable stand-in for an interpreter older than 3.11."""
    stub = tmp_path / "old-python"
    stub.write_text(OLD_PYTHON_STUB)
    stub.chmod(0o755)
    return stub


def run_script(python: Path) -> subprocess.CompletedProcess[str]:
    """The real script, as a real subprocess, with ``PYTHON`` pointed at ``python``."""
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={**os.environ, "PYTHON": str(python)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_the_script_is_valid_bash() -> None:
    """``bash -n`` parses the whole script, guard included."""
    assert SCRIPT.exists(), f"the host plan's script is missing: {SCRIPT}"
    if shutil.which("bash") is None:  # pragma: no cover - bash is how it is invoked
        pytest.skip("no bash on this host")
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_the_python_guard_says_what_is_wrong(old_python: Path) -> None:
    """An old interpreter gets the version message, not a shell error.

    This is the defect: the guard called an undefined ``die``, so bash reported
    ``die: command not found`` (exit 127) and the operator was told nothing about
    which interpreter was too old.
    """
    started = time.monotonic()
    result = run_script(old_python)
    elapsed = time.monotonic() - started

    assert result.returncode != 0, f"an old interpreter must stop the script: {result}"
    assert result.returncode != 127, f"the guard called a missing command: {result.stderr}"
    assert "command not found" not in result.stderr, result.stderr
    assert "python 3.11+ is required" in result.stderr, result.stderr
    assert "3.10.12" in result.stderr, f"the message must name the version: {result.stderr}"
    assert str(old_python) in result.stderr, (
        f"the message must name the interpreter: {result.stderr}"
    )
    # The guard is the first thing after the shell options, so the script cannot
    # have created a virtualenv or installed anything on the way out.
    assert elapsed < 30, f"the guard should stop at once, took {elapsed:.1f}s"
    assert "installing chessleak" not in result.stderr, result.stderr


def test_the_guard_is_the_only_thing_between_the_options_and_the_work() -> None:
    """The guard runs before the virtualenv is created, in the script's own text.

    A behavioural test cannot see the ordering, and the ordering is the fix: a
    guard that fired after ``.venv`` was created would leave a half-made
    environment behind on the very hosts it is meant to stop.
    """
    lines = SCRIPT.read_text().splitlines()
    guard = next(i for i, line in enumerate(lines) if "3.11+ is required" in line)
    creates_venv = next(i for i, line in enumerate(lines) if "m venv .venv" in line)

    assert guard < creates_venv, "the version guard must run before the venv is created"
    assert any(line.strip().startswith("die()") for line in lines), (
        "the script must define die(); calling an undefined function is the defect"
    )
