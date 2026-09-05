#!/usr/bin/env python3
"""Aliasx self-test — headless, no window, no user files touched.

Everything runs inside a temporary folder, with the app's storage
redirected there too (ALIASX_HOME), so running this never disturbs
the real history or preferences.

    python3 selftest.py
    python3 aliasx.py --selftest
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


class Checker:
    """Collects pass/fail lines so one failure does not hide the rest."""

    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, name: str, condition, detail: str = "") -> bool:
        if condition:
            self.passed += 1
            print("  ok   %s" % name)
            return True
        self.failed += 1
        print("  FAIL %s%s" % (name, ("  — " + detail) if detail else ""))
        return False

    def raises(self, name: str, exc, fn, *args, **kwargs) -> bool:
        try:
            fn(*args, **kwargs)
        except exc:
            return self.check(name, True)
        except Exception as err:
            return self.check(name, False, "raised %r instead" % err)
        return self.check(name, False, "did not raise")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------- name rules

def test_names(c, renamer):
    print("naming rules")
    name = renamer.random_name(12)
    c.check("random_name honours the length", len(name) == 12)
    c.check("random_name stays alphanumeric",
            all(ch in renamer.ALPHABET for ch in name))
    c.check("random_name varies between calls",
            len({renamer.random_name(8) for _ in range(50)}) > 45)
    c.check("name length is clamped to a sane range",
            renamer.clamp_length(1) == renamer.RANDOM_LEN_MIN
            and renamer.clamp_length(999) == renamer.RANDOM_LEN_MAX
            and renamer.clamp_length("nope") == 8)

    c.check("extensions normalise to a leading dot, lower case",
            renamer.normalise_extension("JPG") == ".jpg"
            and renamer.normalise_extension("  .Txt ") == ".txt"
            and renamer.normalise_extension("..png") == ".png"
            and renamer.normalise_extension("") == "")
    c.raises("a slash in the extension is rejected",
             renamer.PlanError, renamer.normalise_extension, "jp/g")
    c.raises("a dotted extension is rejected",
             renamer.PlanError, renamer.normalise_extension, "tar.gz")

    c.check("illegal characters are stripped from a stem",
            renamer.sanitize_stem("a/b:c\nd") == "a-b-c-d"
            and renamer.sanitize_stem("   ") == "file")
    long_stem = "x" * 400
    fitted = renamer._fit_name(long_stem, ".jpg")
    c.check("over-long names are trimmed to fit the filesystem",
            len(fitted.encode("utf-8")) <= renamer.NAME_MAX
            and fitted.endswith(".jpg"))


# ---------------------------------------------------------------- plans

def test_plans(c, renamer, tmp):
    print("planning")
    folder = tmp / "plan"
    files = [write(folder / n, n) for n in
             ("one.jpg", "two.jpg", "three.png")]

    plan = renamer.build_plan(files, renamer.MODE_RANDOM, random_length=8)
    c.check("random plan covers every file", len(plan) == 3)
    c.check("random plan keeps the original extension",
            [m.dst.suffix for m in plan] == [".jpg", ".jpg", ".png"])
    c.check("random plan gives every file a different name",
            len({m.dst.name for m in plan}) == 3)
    c.check("random plan stays in the same folder",
            all(m.dst.parent == m.src.parent for m in plan))

    plan = renamer.build_plan(files, renamer.MODE_RANDOM,
                              ext_mode=renamer.EXT_SET, extension="TXT")
    c.check("a new extension is applied to every file",
            all(m.dst.suffix == ".txt" for m in plan))

    plan = renamer.build_plan(files, renamer.MODE_NUMBERED, prefix="Photo-")
    c.check("numbered plan pads to the width of the batch",
            [m.dst.stem for m in plan] == ["Photo-1", "Photo-2", "Photo-3"])

    many = [write(folder / ("f%02d.jpg" % n), "x") for n in range(12)]
    plan = renamer.build_plan(many, renamer.MODE_NUMBERED, prefix="Shot")
    c.check("numbered plan widens the padding for bigger batches",
            plan[0].dst.stem == "Shot01" and plan[-1].dst.stem == "Shot12")

    plan = renamer.build_plan(files, renamer.MODE_NUMBERED, prefix="Img",
                             start_number=100, pad=5)
    c.check("numbered plan honours start number and digit count",
            plan[0].dst.stem == "Img00100" and plan[2].dst.stem == "Img00102")

    plan = renamer.build_plan(files, renamer.MODE_KEEP,
                              ext_mode=renamer.EXT_SET, extension="bak")
    c.check("keep-name mode changes only the extension",
            [m.dst.name for m in plan] == ["one.bak", "two.bak", "three.bak"])

    plan = renamer.build_plan(files, renamer.MODE_KEEP)
    c.check("a file that would keep its own name is marked unchanged",
            renamer.changed_moves(plan) == [])

    write(folder / "Photo-1.jpg", "already here")
    plan = renamer.build_plan(files, renamer.MODE_NUMBERED, prefix="Photo-")
    c.check("a name already on disk is stepped over",
            plan[0].dst.name == "Photo-1-2.jpg")

    c.raises("EXT_SET with a blank extension is refused",
             renamer.PlanError, renamer.build_plan, files,
             renamer.MODE_RANDOM, ext_mode=renamer.EXT_SET, extension="  ")
    c.raises("an unknown naming mode is refused",
             renamer.PlanError, renamer.build_plan, files, "sideways")


# ------------------------------------------------------------ execution

def test_execution(c, renamer, tmp):
    print("renaming")
    folder = tmp / "run"
    files = [write(folder / n, "body of " + n)
             for n in ("a.txt", "b.txt", "c.txt")]

    plan = renamer.build_plan(files, renamer.MODE_NUMBERED, prefix="n")
    outcome = renamer.execute_plan(plan)
    c.check("a clean batch reports no failures", outcome.ok, str(outcome.failures))
    c.check("every file got its new name",
            all(m.dst.exists() and not m.src.exists() for m in outcome.done))
    c.check("file contents survive the rename",
            (folder / "n1.txt").read_text() == "body of a.txt")

    seen = []
    renamer.execute_plan(
        renamer.build_plan(sorted(folder.glob("*.txt")),
                           renamer.MODE_RANDOM),
        progress=lambda step, total, path: seen.append((step, total)))
    c.check("progress is reported once per file",
            len(seen) == 3 and seen[-1] == (3, 3), str(seen))

    # A destination that already exists must never be overwritten.
    guard = tmp / "guard"
    src = write(guard / "src.txt", "keep me")
    victim = write(guard / "victim.txt", "do not lose me")
    outcome = renamer.execute_plan([renamer.Move(src, victim)])
    c.check("an existing file is never overwritten",
            victim.read_text() == "do not lose me" and src.exists())
    c.check("the blocked file is reported in plain English",
            len(outcome.failures) == 1
            and "Errno" not in outcome.failures[0][1])

    # A -> B while B -> A has to route through temporary names.
    swap = tmp / "swap"
    first = write(swap / "a.txt", "AAA")
    second = write(swap / "b.txt", "BBB")
    outcome = renamer.execute_plan([renamer.Move(first, second),
                                    renamer.Move(second, first)])
    c.check("files can swap names without losing either",
            outcome.ok and first.read_text() == "BBB"
            and second.read_text() == "AAA", str(outcome.failures))
    c.check("no temporary files are left behind",
            not list(swap.glob(".aliasx-*")))

    # A file that disappeared between preview and rename.
    ghost = tmp / "ghost"
    ghost.mkdir()
    missing = ghost / "gone.txt"
    outcome = renamer.execute_plan([renamer.Move(missing, ghost / "new.txt")])
    c.check("a vanished file fails cleanly instead of crashing",
            not outcome.done and len(outcome.failures) == 1)
    c.check("no placeholder is left where a rename failed",
            not (ghost / "new.txt").exists())
    c.check("the vanished-file message says what to do",
            "no longer" in outcome.failures[0][1])


# ------------------------------------------------------------- gathering

def test_gather(c, renamer, tmp):
    print("adding files")
    root = tmp / "tree"
    write(root / "top.jpg", "1")
    write(root / ".hidden.jpg", "2")
    write(root / "sub" / "deep.jpg", "3")

    names = [p.name for p in renamer.gather([root])]
    c.check("a folder contributes its files", names == ["top.jpg"])
    c.check("hidden files are skipped by default",
            ".hidden.jpg" not in names)
    c.check("hidden files can be opted in",
            ".hidden.jpg" in [p.name for p in
                              renamer.gather([root], include_hidden=True)])
    c.check("subfolders are included only when asked",
            "deep.jpg" in [p.name for p in
                           renamer.gather([root], recurse=True)])
    c.check("the same file added twice appears once",
            len(renamer.gather([root / "top.jpg", root / "top.jpg"])) == 1)


# -------------------------------------------------------- history + undo

def test_history(c, renamer, database, tmp):
    print("history and undo")
    database.init_db()
    folder = tmp / "hist"
    files = [write(folder / n, n) for n in ("p.txt", "q.txt")]

    plan = renamer.build_plan(files, renamer.MODE_RANDOM)
    outcome = renamer.execute_plan(plan)
    batch_id = database.record_batch(
        renamer.MODE_RANDOM, renamer.EXT_KEEP, "",
        [(m.src, m.dst) for m in outcome.done])

    batches = database.list_batches()
    c.check("the batch is recorded", len(batches) == 1
            and int(batches[0]["renamed"]) == 2)
    c.check("the batch remembers the folder it worked in",
            batches[0]["folder"] == str(folder))
    c.check("every rename is recorded individually",
            len(database.list_moves(batch_id)) == 2)
    c.check("a fresh batch is offered for undo",
            database.latest_undoable() is not None)

    rows = database.list_moves(batch_id, pending_only=True)
    pairs = [(r["old_path"], r["new_path"]) for r in rows]
    undone = renamer.undo_moves(pairs)
    c.check("undo puts the original names back",
            undone.ok and all(Path(old).exists() for old, _ in pairs),
            str(undone.failures))

    database.mark_undone(batch_id, [(old, new) for old, new in pairs])
    c.check("a fully reversed batch is flagged undone",
            int(database.get_batch(batch_id)["undone"]) == 1)
    c.check("a reversed batch is no longer offered for undo",
            database.latest_undoable() is None)

    database.clear_history()
    c.check("clearing the history empties both tables",
            database.history_counts() == (0, 0))


# ------------------------------------------------------------------ prefs

def test_prefs(c, prefs) -> None:
    print("preferences")
    loaded = prefs.load()
    c.check("defaults are present on a first run",
            loaded["mode"] == "random" and loaded["window"]["w"] == 900)

    loaded["mode"] = "numbered"
    loaded["prefix"] = "Trip"
    loaded["window"] = {"x": 40, "y": 60, "w": 1000, "h": 700}
    prefs.save(loaded)
    again = prefs.load()
    c.check("settings survive a save and reload",
            again["mode"] == "numbered" and again["prefix"] == "Trip")
    c.check("the window rect becomes a Tk geometry string",
            prefs.geometry_string(again) == "1000x700+40+60")

    again["remember_geometry"] = False
    c.check("position is dropped when the user opts out",
            prefs.geometry_string(again) == "1000x700")

    prefs.prefs_path().write_text("{ this is not json", encoding="utf-8")
    c.check("a corrupt prefs file falls back to defaults",
            prefs.load()["mode"] == "random")


# ------------------------------------------------------------------- run

def run() -> bool:
    c = Checker()
    with tempfile.TemporaryDirectory(prefix="aliasx-selftest-") as raw:
        tmp = Path(raw)
        os.environ["ALIASX_HOME"] = str(tmp / "support")

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import database
        import prefs
        import renamer

        print("Aliasx self-test — %s\n" % tmp)
        test_names(c, renamer)
        test_plans(c, renamer, tmp)
        test_execution(c, renamer, tmp)
        test_gather(c, renamer, tmp)
        test_history(c, renamer, database, tmp)
        test_prefs(c, prefs)

    total = c.passed + c.failed
    print("\n%d of %d checks passed." % (c.passed, total))
    if c.failed:
        print("SELF-TEST FAILED")
    else:
        print("Self-test OK")
    return c.failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
