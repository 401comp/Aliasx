# Aliasx

Batch file renaming for macOS, with an undo that actually survives
quitting the app.

Renaming a folder of files to random names throws away the only copy of
the old names. This version writes every batch down before it touches
anything, so **Undo Last Rename** can put all of them back — an hour
later or a week later.

Runs on **macOS 10.15 Catalina and up**. Everything stays on your Mac:
no network access, no telemetry, nothing uploaded.

---

## What it does

1. **Add files** — the Add Files / Add Folder buttons, or drag them
   straight onto the list.
2. **Pick a naming style**
   | Style | Result |
   |---|---|
   | Random names | `a7Kd93Xb.jpg` — 4 to 32 characters, letters and digits |
   | Numbered names | `Photo-0001.jpg` — your prefix, start number, digit count |
   | Keep each name | `holiday.jpg` → `holiday.png` — extension only |
3. **Check the preview** — every file shows its current name next to the
   name it is about to get. Nothing happens until you press Rename.
4. **Rename** — and if it was not what you wanted, undo it.

Extensions can be kept as they are or changed to anything you type. Files
that would end up with the name they already have are marked
*(no change)* and left alone.

## Safety

The original version of this script had three ways to lose a file. All
three are closed:

- **Nothing is ever overwritten.** `os.rename` silently replaces the
  destination on macOS, so the new name is claimed first with an
  exclusive create. If a file with that name turns up in the split
  second before the rename, the file is skipped and reported instead.
- **Name swaps work.** Renaming `a.txt` to `b.txt` while `b.txt` becomes
  `a.txt` routes both through temporary names, so neither is lost.
- **A failure never takes the batch down.** A file that has been moved,
  locked, or put on a read-only disk is reported in plain English and
  left exactly as it was; the rest of the batch still goes through.

Source files are only ever renamed in place — never copied, moved to
another folder, or modified.

## Options

| Option | What it does |
|---|---|
| Name length | Characters in a random name (4–32) |
| Prefix / Start at / Digits | Numbered naming; `Digits: 0` picks a width from the file count |
| Keep original extension | Leave `.jpg`, `.png` etc. alone |
| Change to | Replace every extension with the one you type |
| Include subfolders | Adding a folder also picks up everything inside it |
| Include hidden files | Files beginning with a dot are added too |
| Ask before renaming | Confirmation dialog before a batch runs |

Settings, the window size, and the window position are remembered
between launches.

## History and undo

The **History** tab lists every batch: when it ran, how many files, and
whether it can still be undone. Select one to see each original name and
what it became, then **Undo Selected Batch** to put them back. Files that
have since been moved or deleted are reported and the rest still go
back.

**Undo Last Rename** (⌘Z) does the most recent batch that still has
files left to restore.

## Storage

Two files, both in `~/Library/Application Support/Aliasx/`:

- `aliasx.sqlite3` — the rename history that Undo reads
- `prefs.json` — window size/position and your last settings

Delete that folder to reset the app completely; your files are not
affected. **Help → Where things are stored** says the same thing inside
the app.

## Plugins

Aliasx supports drop-in plugins without touching core functionality.
A plugin is a single `.py` file placed in
`~/Library/Application Support/Aliasx/plugins/` that exports a
`register(app)` function; it loads automatically the next time you launch.

**Plugins → Manage Plugins…** lists every installed plugin with a
description and an enable/disable toggle. Disabling a plugin persists
immediately and takes effect on the next launch — its code is never even
imported while disabled. Official plugins ship through pull requests to
this repo rather than being written ad-hoc.

## Run it

```bash
./run.sh
```

or from the repo:

```bash
python3 aliasx.py
```

Keyboard: ⌘O add files, ⌘⇧O add folder, ⌘R rename, ⌘Z undo.

## Build

```bash
chmod +x build.sh && ./build.sh
```

Produces `dist/Aliasx.app` and `release/Aliasx-1.0.0.dmg`
(drag-install, with an `/Applications` shortcut). The build runs the
compatibility check, the self-test, and a portability check before it
packages anything, and it never launches the app.

On modern macOS the script uses Homebrew's `python@3.14` plus
`python-tk@3.14` — not the miniconda `python3` that sits on `PATH`.

### Building for Catalina (10.15)

A PyInstaller bundle runs on the macOS generation it was built on and
newer, and nothing older. To ship something a Catalina Mac can open, run
`./build.sh` **on the Catalina machine**:

1. Install Python 3.9.13 from python.org (Catalina's last practical
   Python).
2. `./build.sh` — it detects `10.x`, switches to
   `requirements-catalina.txt`, and refuses to continue on the wrong
   Python version.

The sources are kept Python 3.9-clean so this never becomes a rewrite.
`compat_check.py` parses every file with `feature_version=(3, 9)` and
verifies `from __future__ import annotations` is present, and it runs on
every build.

Drag-and-drop needs `tkinterdnd2`; without it the app runs exactly the
same, minus the drop target.

## Self-test

```bash
python3 selftest.py          # or: python3 aliasx.py --selftest
```

51 checks covering name generation, collision avoidance, the overwrite
guard, name swaps, missing-file handling, history, undo, and
preferences. Runs headless in a temporary folder — no window, and your
real history and settings are untouched. `build.sh` will not package
anything if it fails.

## Files

| File | Purpose |
|---|---|
| `aliasx.py` | Tk UI, menus, preview, history tab, job runner |
| `renamer.py` | The engine — planning, collision rules, safe execution |
| `database.py` | SQLite history that makes undo possible |
| `prefs.py` | `prefs.json` for window state and last-used settings |
| `selftest.py` | Headless checks |
| `compat_check.py` | Python 3.9 / Catalina source gate |
| `assets/make_icon.py` | Draws `icon.icns` with Pillow + `iconutil` |
| `build.sh` / `run.sh` | Build the DMG / run from source |
| `versions/` | Source snapshots, including the original script |

## Licence

MIT — see `LICENSE.txt`.
