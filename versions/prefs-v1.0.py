"""User preferences — window state and the last-used rename settings.

JSON at ~/Library/Application Support/File Renamer/prefs.json, kept apart
from the SQLite history so UI state can be reset without losing the undo
record (or the other way round).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from database import app_dir


DEFAULTS: Dict[str, Any] = {
    "window":            {"x": None, "y": None, "w": 900, "h": 640},
    "remember_geometry": True,
    "last_tab_index":    0,
    "mode":              "random",     # random | numbered | keep
    "random_length":     8,
    "prefix":            "File",
    "start_number":      1,
    "pad":               0,            # 0 = pick a width from the file count
    "ext_mode":          "keep",       # keep | set
    "extension":         "",
    "recurse_folders":   False,
    "include_hidden":    False,
    "confirm_rename":    True,
    "last_dir":          "",
}


def prefs_path():
    return app_dir() / "prefs.json"


def _load_raw() -> Dict[str, Any]:
    path = prefs_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def load() -> Dict[str, Any]:
    """Full prefs dict with defaults filled in for anything missing."""
    data = dict(DEFAULTS)
    data["window"] = dict(DEFAULTS["window"])
    for key, value in _load_raw().items():
        if key == "window" and isinstance(value, dict):
            window = dict(DEFAULTS["window"])
            window.update(value)
            data["window"] = window
        elif key in DEFAULTS:
            data[key] = value
    return data


def save(prefs: Dict[str, Any]) -> None:
    """Write prefs atomically. Never fatal — settings are a convenience."""
    path = prefs_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
        os.replace(str(temp), str(path))
    except (OSError, TypeError, ValueError):
        pass


def set_value(key: str, value: Any) -> None:
    prefs = load()
    prefs[key] = value
    save(prefs)


def geometry_string(prefs: Dict[str, Any]) -> str:
    """Stored rect as a Tk geometry string; size only if never positioned."""
    window = prefs.get("window") or DEFAULTS["window"]
    width = int(window.get("w") or DEFAULTS["window"]["w"])
    height = int(window.get("h") or DEFAULTS["window"]["h"])
    base = "%dx%d" % (width, height)
    x, y = window.get("x"), window.get("y")
    if x is not None and y is not None and prefs.get("remember_geometry", True):
        base += "+%d+%d" % (int(x), int(y))
    return base


def capture_geometry(root) -> Dict[str, int]:
    root.update_idletasks()
    return {"x": root.winfo_x(), "y": root.winfo_y(),
            "w": root.winfo_width(), "h": root.winfo_height()}
