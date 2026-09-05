"""SQLite history for Aliasx — the record that makes Undo possible.

Every rename is written down as a batch plus one row per file, so a run
can be reversed hours or days later. Set ALIASX_HOME to point the
store somewhere else (the self-test uses a temporary folder).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional


APP_NAME = "Aliasx"


def app_dir() -> Path:
    override = os.environ.get("ALIASX_HOME")
    if override:
        return Path(override)
    return Path.home() / "Library" / "Application Support" / APP_NAME


def db_path() -> Path:
    return app_dir() / "aliasx.sqlite3"


SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,               -- ISO8601, local time
    mode       TEXT NOT NULL,               -- random | numbered | keep
    ext_mode   TEXT DEFAULT 'keep',
    extension  TEXT DEFAULT '',
    folder     TEXT DEFAULT '',             -- common parent, for display
    total      INTEGER DEFAULT 0,
    renamed    INTEGER DEFAULT 0,
    failed     INTEGER DEFAULT 0,
    undone     INTEGER DEFAULT 0            -- 0 no, 1 fully, 2 partly
);

CREATE TABLE IF NOT EXISTS moves (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id  INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    old_path  TEXT NOT NULL,
    new_path  TEXT NOT NULL,
    undone    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_moves_batch ON moves(batch_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect() -> sqlite3.Connection:
    directory = app_dir()
    directory.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path()))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db() -> None:
    with cursor() as con:
        con.executescript(SCHEMA)


@contextmanager
def cursor():
    con = _connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def common_folder(paths) -> str:
    """Folder to show for a batch: the shared parent, else 'several folders'."""
    folders = {str(Path(p).parent) for p in paths}
    if len(folders) == 1:
        return folders.pop()
    if not folders:
        return ""
    return "%d folders" % len(folders)


# ------------------------------------------------------------- writing

def record_batch(mode: str, ext_mode: str, extension: str,
                 moves, failed: int = 0) -> int:
    """Store a finished rename. `moves` is a sequence of (old, new) paths."""
    pairs = [(str(old), str(new)) for old, new in moves]
    ts = datetime.now().isoformat(timespec="seconds")
    with cursor() as con:
        cur = con.execute(
            "INSERT INTO batches (ts, mode, ext_mode, extension, folder, "
            "total, renamed, failed, undone) VALUES (?,?,?,?,?,?,?,?,0)",
            (ts, mode, ext_mode, extension,
             common_folder([old for old, _ in pairs]),
             len(pairs) + failed, len(pairs), failed))
        batch_id = cur.lastrowid
        con.executemany(
            "INSERT INTO moves (batch_id, old_path, new_path, undone) "
            "VALUES (?,?,?,0)",
            [(batch_id, old, new) for old, new in pairs])
        return batch_id


def mark_undone(batch_id: int, restored) -> None:
    """Flag the given (old, new) pairs as reversed and update the batch."""
    keys = {(str(old), str(new)) for old, new in restored}
    with cursor() as con:
        for old, new in keys:
            con.execute(
                "UPDATE moves SET undone = 1 WHERE batch_id = ? AND "
                "old_path = ? AND new_path = ?", (batch_id, old, new))
        row = con.execute(
            "SELECT COUNT(*) AS n, SUM(undone) AS u FROM moves "
            "WHERE batch_id = ?", (batch_id,)).fetchone()
        total, undone = int(row["n"] or 0), int(row["u"] or 0)
        state = 0 if not undone else (1 if undone >= total else 2)
        con.execute("UPDATE batches SET undone = ? WHERE id = ?",
                    (state, batch_id))


# ------------------------------------------------------------- reading

def list_batches(limit: int = 500) -> List[sqlite3.Row]:
    with cursor() as con:
        return list(con.execute(
            "SELECT * FROM batches ORDER BY id DESC LIMIT ?", (limit,)))


def get_batch(batch_id: int) -> Optional[sqlite3.Row]:
    with cursor() as con:
        return con.execute("SELECT * FROM batches WHERE id = ?",
                           (batch_id,)).fetchone()


def list_moves(batch_id: int, pending_only: bool = False) -> List[sqlite3.Row]:
    query = "SELECT * FROM moves WHERE batch_id = ?"
    if pending_only:
        query += " AND undone = 0"
    query += " ORDER BY id"
    with cursor() as con:
        return list(con.execute(query, (batch_id,)))


def latest_undoable() -> Optional[sqlite3.Row]:
    """Most recent batch that still has files left to put back."""
    with cursor() as con:
        return con.execute(
            "SELECT b.* FROM batches b WHERE EXISTS ("
            "  SELECT 1 FROM moves m WHERE m.batch_id = b.id AND m.undone = 0"
            ") ORDER BY b.id DESC LIMIT 1").fetchone()


# ------------------------------------------------------------ housekeeping

def delete_batch(batch_id: int) -> None:
    with cursor() as con:
        con.execute("DELETE FROM moves WHERE batch_id = ?", (batch_id,))
        con.execute("DELETE FROM batches WHERE id = ?", (batch_id,))


def clear_history() -> None:
    with cursor() as con:
        con.execute("DELETE FROM moves")
        con.execute("DELETE FROM batches")
    with cursor() as con:
        con.execute("VACUUM")


def history_counts() -> tuple:
    with cursor() as con:
        batches = con.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        moves = con.execute("SELECT COUNT(*) FROM moves").fetchone()[0]
    return int(batches), int(moves)


def history_size_bytes() -> int:
    try:
        return db_path().stat().st_size
    except OSError:
        return 0


def get_meta(key: str, default: Optional[str] = None) -> Optional[str]:
    with cursor() as con:
        row = con.execute("SELECT value FROM meta WHERE key = ?",
                          (key,)).fetchone()
        return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    with cursor() as con:
        con.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value))
