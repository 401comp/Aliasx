"""Rename planning and execution — the whole engine, with no Tk in it.

Kept GUI-free on purpose so the self-test can exercise every rule
headlessly. Two ideas carry the design:

* **Plan first, rename second.** `build_plan()` works out every new name
  up front (checking the disk and the rest of the batch for clashes), so
  the preview the user sees is literally what will happen.
* **Never clobber.** A destination is reserved with O_CREAT|O_EXCL
  before the rename, which closes the race `os.path.exists()` leaves
  open — `os.rename` on macOS silently overwrites, and this app's whole
  job is throwing away the old names.

Python 3.9 syntax throughout so the same sources build on Catalina.
"""

from __future__ import annotations

import errno
import os
import random
import re
import string
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Sequence

ALPHABET = string.ascii_letters + string.digits
RANDOM_LEN_MIN = 4
RANDOM_LEN_MAX = 32
NAME_MAX = 255                       # bytes, HFS+/APFS per-component limit

MODE_RANDOM = "random"
MODE_NUMBERED = "numbered"
MODE_KEEP = "keep"
MODES = (MODE_RANDOM, MODE_NUMBERED, MODE_KEEP)

EXT_KEEP = "keep"
EXT_SET = "set"
EXT_MODES = (EXT_KEEP, EXT_SET)

# Characters macOS will not accept in a filename component, plus the
# control range. ":" is the classic one — Finder shows it as "/".
_ILLEGAL = re.compile(r"[/:\x00-\x1f\x7f]")

_rng = random.SystemRandom()


class PlanError(Exception):
    """Bad settings, phrased for a dialog rather than a traceback."""


class Move(NamedTuple):
    """One planned rename. `src` and `dst` always share a parent folder."""
    src: Path
    dst: Path

    @property
    def changed(self) -> bool:
        return str(self.src) != str(self.dst)


class Outcome(NamedTuple):
    """What actually happened when a plan ran."""
    done: List[Move]
    failures: List[tuple]            # (Path, plain-English message)

    @property
    def ok(self) -> bool:
        return not self.failures


# --------------------------------------------------------------- names

def random_name(length: int = 8) -> str:
    """Random alphanumeric stem, the original app's naming scheme."""
    length = clamp_length(length)
    return "".join(_rng.choice(ALPHABET) for _ in range(length))


def clamp_length(length) -> int:
    try:
        length = int(length)
    except (TypeError, ValueError):
        return 8
    return max(RANDOM_LEN_MIN, min(RANDOM_LEN_MAX, length))


def normalise_extension(ext: str) -> str:
    """'txt', '.TXT', '  .txt ' -> '.txt'. Empty string means 'none'."""
    ext = (ext or "").strip()
    if not ext:
        return ""
    while ext.startswith("."):
        ext = ext[1:]
    ext = ext.strip()
    if not ext:
        return ""
    if _ILLEGAL.search(ext) or ext.startswith(" ") or "." in ext:
        raise PlanError(
            "“%s” is not a usable extension. Use letters and "
            "numbers only, such as jpg or txt." % ext)
    return "." + ext.lower()


def sanitize_stem(stem: str) -> str:
    """Strip anything macOS will not put in a filename."""
    cleaned = _ILLEGAL.sub("-", stem or "").strip().strip(".")
    return cleaned or "file"


def _fit_name(stem: str, ext: str) -> str:
    """Trim the stem so stem+ext fits in one path component."""
    name = stem + ext
    if len(name.encode("utf-8")) <= NAME_MAX:
        return name
    room = NAME_MAX - len(ext.encode("utf-8"))
    trimmed = stem.encode("utf-8")[:max(1, room)].decode("utf-8", "ignore")
    return (trimmed or "file") + ext


# ---------------------------------------------------------------- plan

def _key(path: Path) -> str:
    """Comparison key for a path on a case-insensitive volume."""
    return os.path.normcase(str(path))


def build_plan(paths: Sequence, mode: str = MODE_RANDOM, *,
               random_length: int = 8,
               prefix: str = "File",
               start_number: int = 1,
               pad: int = 0,
               ext_mode: str = EXT_KEEP,
               extension: str = "") -> List[Move]:
    """Work out the new name for every file, avoiding every clash.

    Clashes are checked against three things: names already on the disk,
    names already claimed earlier in this same batch, and (for numbered
    and keep-name modes) each other. Nothing here touches the disk apart
    from `exists()` probes.
    """
    if mode not in MODES:
        raise PlanError("Unknown naming mode: %s" % mode)
    if ext_mode not in EXT_MODES:
        raise PlanError("Unknown extension mode: %s" % ext_mode)

    new_ext = ""
    if ext_mode == EXT_SET:
        new_ext = normalise_extension(extension)
        if not new_ext:
            raise PlanError(
                "Enter a file extension (such as jpg), or switch to "
                "“Keep original extension”.")

    prefix = sanitize_stem(prefix) if mode == MODE_NUMBERED else prefix
    try:
        start_number = max(0, int(start_number))
    except (TypeError, ValueError):
        start_number = 1

    files = [Path(p) for p in paths]
    if mode == MODE_NUMBERED and not int(pad or 0):
        widest = start_number + max(0, len(files) - 1)
        pad = max(1, len(str(widest)))
    pad = max(0, int(pad or 0))

    sources = {_key(f) for f in files}
    claimed = set()
    plan: List[Move] = []
    counter = start_number

    for src in files:
        ext = new_ext if ext_mode == EXT_SET else src.suffix
        folder = src.parent

        if mode == MODE_RANDOM:
            dst = _unique_random(folder, ext, sources, claimed, random_length)
        else:
            if mode == MODE_NUMBERED:
                stem = "%s%0*d" % (prefix, pad, counter) if pad \
                    else "%s%d" % (prefix, counter)
                counter += 1
            else:
                stem = sanitize_stem(src.stem)
            dst = _unique_numbered(folder, stem, ext, src, sources, claimed)

        claimed.add(_key(dst))
        plan.append(Move(src, dst))
    return plan


def _taken(dst: Path, own: Optional[Path], sources: set, claimed: set) -> bool:
    key = _key(dst)
    if own is not None and key == _key(own):
        return False                      # a file may keep its own name
    if key in claimed or key in sources:
        return True
    try:
        return dst.exists()
    except OSError:
        return True                       # unreadable -> treat as taken


def _unique_random(folder: Path, ext: str, sources: set, claimed: set,
                   length: int) -> Path:
    for _ in range(10000):
        dst = folder / _fit_name(random_name(length), ext)
        if not _taken(dst, None, sources, claimed):
            return dst
    raise PlanError(
        "Could not find an unused random name in “%s”. Try a "
        "longer name length." % folder.name)


def _unique_numbered(folder: Path, stem: str, ext: str, own: Path,
                     sources: set, claimed: set) -> Path:
    dst = folder / _fit_name(stem, ext)
    if not _taken(dst, own, sources, claimed):
        return dst
    for n in range(2, 10000):
        dst = folder / _fit_name("%s-%d" % (stem, n), ext)
        if not _taken(dst, own, sources, claimed):
            return dst
    raise PlanError(
        "Too many files in “%s” already use the name "
        "“%s”." % (folder.name, stem))


def changed_moves(plan: Sequence) -> List[Move]:
    """Drop the entries whose name would not actually change."""
    return [m for m in plan if m.changed]


# ----------------------------------------------------------- execution

def friendly_error(err: BaseException, path: Path) -> str:
    """Turn an OSError into something a non-technical user can act on."""
    name = path.name or str(path)
    if isinstance(err, FileNotFoundError):
        return ("%s is no longer in that folder — it may have been moved, "
                "renamed, or deleted since you added it." % name)
    if isinstance(err, FileExistsError):
        return ("%s was left alone: another file with the new name turned "
                "up in the folder just now." % name)
    if isinstance(err, PermissionError):
        return ("%s could not be renamed because macOS denied permission. "
                "The file may be locked, or File Renamer may need access "
                "to that folder in System Settings › Privacy & "
                "Security › Files and Folders." % name)
    if isinstance(err, OSError):
        if err.errno == errno.EROFS:
            return ("%s is on a read-only disk, so it cannot be renamed."
                    % name)
        if err.errno == errno.ENOSPC:
            return "The disk holding %s is full." % name
        if err.errno == errno.ENAMETOOLONG:
            return "The new name for %s is too long for this disk." % name
        if err.errno in (errno.EBUSY, errno.ETXTBSY):
            return ("%s is in use by another program. Close it and try "
                    "again." % name)
        if err.errno == errno.EXDEV:
            return ("%s cannot be renamed across two different disks."
                    % name)
        return "%s could not be renamed (%s)." % (
            name, err.strerror or "unknown disk error")
    return "%s could not be renamed (%s)." % (name, err)


def _reserve_and_rename(src: Path, dst: Path) -> None:
    """Rename, refusing to overwrite anything.

    `os.rename` replaces the destination without a word on POSIX, so the
    name is claimed first with an exclusive create. If the rename then
    fails, the placeholder is cleaned up so the folder is left as found.
    """
    fd = os.open(str(dst), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        os.rename(str(src), str(dst))
    except OSError:
        try:
            os.unlink(str(dst))
        except OSError:
            pass
        raise


def _needs_two_phase(plan: Sequence) -> bool:
    """True when some file's new name is another file's current name."""
    sources = {_key(m.src) for m in plan}
    return any(_key(m.dst) in sources and _key(m.dst) != _key(m.src)
               for m in plan)


def _temp_path(folder: Path) -> Path:
    for _ in range(10000):
        cand = folder / (".filerenamer-%s.tmp" % random_name(12))
        if not cand.exists():
            return cand
    raise OSError(errno.EEXIST, "no free temporary name")


def execute_plan(plan: Sequence,
                 progress: Optional[Callable] = None,
                 cancelled: Optional[Callable] = None) -> Outcome:
    """Carry out a plan. Never raises for a per-file problem.

    Files that fail are reported and left exactly as they were; the rest
    of the batch still goes through. When any new name collides with a
    name still in use inside the batch (A→B while B→A), everything moves
    through a temporary name first so no file is ever overwritten.
    """
    moves = changed_moves(plan)
    done: List[Move] = []
    failures: List[tuple] = []
    if not moves:
        return Outcome(done, failures)

    total = len(moves)
    step = 0

    def tick(path: Path) -> None:
        if progress is not None:
            progress(step, total, path)

    if not _needs_two_phase(moves):
        for move in moves:
            if cancelled is not None and cancelled():
                break
            step += 1
            tick(move.src)
            try:
                _reserve_and_rename(move.src, move.dst)
                done.append(move)
            except OSError as err:
                failures.append((move.src, friendly_error(err, move.src)))
        return Outcome(done, failures)

    # Two-phase: park every file under a temporary name, then place them.
    parked = []
    for move in moves:
        if cancelled is not None and cancelled():
            break
        step += 1
        tick(move.src)
        try:
            tmp = _temp_path(move.src.parent)
            os.rename(str(move.src), str(tmp))
            parked.append((move, tmp))
        except OSError as err:
            failures.append((move.src, friendly_error(err, move.src)))

    for move, tmp in parked:
        try:
            _reserve_and_rename(tmp, move.dst)
            done.append(move)
        except OSError as err:
            try:
                os.rename(str(tmp), str(move.src))
                failures.append((move.src, friendly_error(err, move.src)))
            except OSError:
                failures.append((move.src, (
                    "%s could not be given its new name and could not be "
                    "put back. It is in the same folder, temporarily named "
                    "%s." % (move.src.name, tmp.name))))
    return Outcome(done, failures)


def undo_moves(pairs: Sequence) -> Outcome:
    """Put files back. `pairs` is a sequence of (old_path, new_path)."""
    plan = [Move(Path(new), Path(old)) for old, new in pairs]
    return execute_plan(plan)


# ------------------------------------------------------------ gathering

def gather(paths: Sequence, recurse: bool = False,
           include_hidden: bool = False) -> List[Path]:
    """Expand a mix of files and folders into a sorted, unique file list.

    Folders contribute their files; `recurse` walks subfolders too.
    Aliases and symlinks are skipped — renaming the link rather than the
    file it points at is never what someone means here.
    """
    out = []
    seen = set()

    def add(path: Path) -> None:
        key = _key(path)
        if key in seen:
            return
        if not include_hidden and path.name.startswith("."):
            return
        seen.add(key)
        out.append(path)

    for raw in paths:
        path = Path(raw)
        try:
            if path.is_symlink():
                continue
            if path.is_file():
                add(path)
            elif path.is_dir():
                entries = path.rglob("*") if recurse else path.glob("*")
                for child in sorted(entries):
                    try:
                        if child.is_file() and not child.is_symlink():
                            add(child)
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(out, key=lambda p: (str(p.parent).lower(), p.name.lower()))
