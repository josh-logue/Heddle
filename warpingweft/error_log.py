"""Unexpected errors: logged to a file and reported, instead of vanishing.

The launcher runs the app with pythonw (no console), so an error inside a click or
key handler would otherwise be lost without a trace while the app carries on, maybe
with the board half-updated. install() makes every such error:

* append its traceback to error.log in the app's local data folder
  (%LOCALAPPDATA%\\WarpingWeft\\logs, or WARPINGWEFT_LOG_DIR), and
* show a dialog saying what happened and where the log is. The app keeps running;
  the dialog suggests saving a copy of the board, in case it's in a bad state.

A burst of errors shows only the first dialog (all are logged).
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .settings import APP_NAME

ENV_DIR = "WARPINGWEFT_LOG_DIR"   # overrides the folder (used by the tests)
LOG_NAME = "error.log"
MAX_LOG_BYTES = 1_000_000         # then the log is moved to error.log.old and started afresh
DIALOG_QUIET_S = 10.0             # after a dialog, further errors this soon are only logged

_last_dialog = 0.0
_dialog_open = False


def log_dir() -> Path:
    override = os.environ.get(ENV_DIR, "").strip()
    if override:
        return Path(override)
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    return Path(base) / APP_NAME / "logs"


def log_path() -> Path:
    return log_dir() / LOG_NAME


def write_log(text: str) -> Path | None:
    """Append an entry to the log; returns its path, or None if it couldn't be written."""
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            os.replace(path, path.with_name(LOG_NAME + ".old"))
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"===== {stamp} =====\n{text.rstrip()}\n\n")
        return path
    except OSError:
        return None


def report(exc_type, exc, tb) -> None:
    """Log an unexpected error and (unless one was just shown) tell the user."""
    global _last_dialog
    if issubclass(exc_type, KeyboardInterrupt):  # Ctrl+C in a terminal: quit as usual
        sys.__excepthook__(exc_type, exc, tb)
        return
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    if sys.stderr is not None:  # running from a terminal: show it there too
        try:
            sys.stderr.write(text)
        except (OSError, ValueError):
            pass
    path = write_log(text)
    if QApplication.instance() is None or _dialog_open:
        return
    now = time.monotonic()
    if now - _last_dialog < DIALOG_QUIET_S:
        return
    _last_dialog = now
    summary = f"{exc_type.__name__}: {exc}" if str(exc) else exc_type.__name__
    # Shown once the event loop is free, not from inside the code that failed.
    QTimer.singleShot(0, lambda: _show_dialog(summary, path))


def _show_dialog(summary: str, path: Path | None) -> None:
    global _dialog_open
    where = (f"The details were saved to:\n{path}" if path is not None
             else "The details couldn't be written to the log.")
    box = QMessageBox(QApplication.activeWindow())
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Something went wrong")
    box.setText("WarpingWeft hit an unexpected error. It's still running, but to be safe, "
                "consider saving a copy of your board (File → Save As…) and checking it.")
    box.setInformativeText(where)
    box.setDetailedText(summary)
    _dialog_open = True
    try:
        box.exec()
    finally:
        _dialog_open = False


def install() -> None:
    """Route uncaught errors (main thread and other threads) through report()."""
    sys.excepthook = report
    threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback)
