"""A test run must exit cleanly once its tests pass. Headless Qt (the offscreen platform the
tests use) crashed while Python shut down if the clipboard still held copied cards, so CI
reported a failure with every test passing. The real Windows platform doesn't crash."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_a_run_that_copies_cards_exits_cleanly(tmp_path):
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:cacheprovider",
         f"--basetemp={tmp_path / 'inner'}", "tests/test_paste_action.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    # (the crash came after the tests ran, and could lose the buffered summary with it)
    assert run.returncode == 0, f"exit code {run.returncode}:\n{run.stdout}{run.stderr}"
    assert "2 passed" in run.stdout
