"""Persistent app log.

Normally this is written to ~/Library/Logs/Aliasx/ so entries also surface in
macOS Console.app.  Test and automation runs can set ALIASX_HOME (or the more
specific ALIASX_LOG_DIR) to keep every Aliasx side effect in their sandbox.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "Aliasx"


def _log_dir() -> Path:
    override = os.environ.get("ALIASX_LOG_DIR")
    if override:
        base = Path(override)
    elif os.environ.get("ALIASX_HOME"):
        # ALIASX_HOME is the application's established isolated-storage
        # switch.  Keep logs alongside it rather than touching the real user
        # Library during a self-test or an automated build.
        base = Path(os.environ["ALIASX_HOME"]) / "logs"
    else:
        base = Path.home() / "Library" / "Logs" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


LOG_DIR = _log_dir()
LOG_PATH = LOG_DIR / f"{APP_NAME}.log"

_logger = logging.getLogger(APP_NAME)
_logger.setLevel(logging.INFO)

if not _logger.handlers:
    try:
        _handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=2_000_000, backupCount=3,
        )
    except OSError:
        # Logging is diagnostic only.  A protected, unavailable, or full
        # Library folder must never stop the renamer from opening.
        _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(_handler)


def info(msg: str) -> None:
    _logger.info(msg)


def warning(msg: str) -> None:
    _logger.warning(msg)


def error(msg: str) -> None:
    _logger.error(msg)


def exception(msg: str) -> None:
    _logger.exception(msg)


def open_in_console() -> tuple[bool, str]:
    """Launch macOS Console.app pointed at this app's log file."""
    if sys.platform != "darwin":
        return False, "Console.app is only available on macOS."
    try:
        subprocess.run(["open", "-a", "Console", str(LOG_PATH)], check=True)
        return True, f"Opened {LOG_PATH} in Console"
    except Exception as e:
        return False, str(e)


def reveal_in_finder() -> tuple[bool, str]:
    """Reveal the log file in Finder."""
    if sys.platform != "darwin":
        return False, "Reveal in Finder is only available on macOS."
    try:
        subprocess.run(["open", "-R", str(LOG_PATH)], check=True)
        return True, f"Revealed {LOG_PATH} in Finder"
    except Exception as e:
        return False, str(e)
