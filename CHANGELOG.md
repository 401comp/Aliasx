# Changelog

## 1.0.0 — 2026-07-30

First packaged release. Rebuilt from the original single-file
`File_Renamer.py` script (kept in `versions/`).

### Added
- **Rename history and undo.** Every batch is written to SQLite in
  `~/Library/Application Support/File Renamer/`, so a rename can be
  reversed after quitting the app. History tab lists every batch with
  its files; undo works per batch or on the most recent one (⌘Z).
- **Live preview.** Each file shows its current name beside the name it
  will get. Nothing is renamed until you press the button.
- **Two more naming styles** alongside random names: numbered names
  (prefix, start number, digit width) and keep-the-name/change-only-the-
  extension.
- **Keep original extension** — the original script forced you to type
  one.
- Add whole folders, optionally including subfolders and hidden files.
- Drag files onto the list when `tkinterdnd2` is installed.
- Progress bar and per-file status for large batches; renaming runs off
  the UI thread so the window never beachballs.
- Menu bar with ⌘O / ⌘⇧O / ⌘R / ⌘Z, an About box, and a "Where things
  are stored" item.
- `prefs.json` remembering window size, position, and every setting.
- Custom app icon, `--selftest` (51 checks), `--version`, DMG installer
  with an `/Applications` shortcut.

### Fixed (from the original script)
- **Files could be overwritten.** `os.rename` replaces the destination
  silently on macOS, and the `os.path.exists` check in front of it left
  a race open. New names are now claimed with an exclusive create before
  the rename, and a blocked file is reported rather than clobbered.
- **Name swaps destroyed a file.** Renaming `a`→`b` while `b`→`a` now
  routes both through temporary names.
- **One bad file killed the whole run.** A `PermissionError` partway
  through left some files renamed, some not, and threw a traceback at
  the terminal. Failures are now per-file, reported in plain English,
  and the rest of the batch continues.
- **Renames were irreversible** — random names erased the only record of
  the originals.
- Illegal characters, over-long names, and malformed extensions such as
  `tar.gz` or `jp/g` are rejected or trimmed instead of producing a
  broken filename.
- Symlinks and aliases are skipped rather than renamed in place of what
  they point at.
- Window opens centered instead of at Tk's default position.
- Follows the system Light/Dark appearance instead of hardcoded button
  colours.

### Compatibility
- Sources are Python 3.9-clean and gated by `compat_check.py` on every
  build, so the same tree builds on Catalina (10.15) with python.org
  3.9.13 and `requirements-catalina.txt`.
