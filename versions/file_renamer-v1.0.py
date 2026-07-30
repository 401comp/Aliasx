#!/usr/bin/env python3
"""File Renamer — batch renaming for macOS, with a real undo.

What it does:
  1. Add files (or whole folders, or drag them in).
  2. Pick a naming style — random names, numbered names, or keep the
     name and only change the extension.
  3. Check the preview: every file shows its current name beside the
     name it is about to get. Nothing happens until you say so.
  4. Rename. The batch is written to a history file, so “Undo Last
     Rename” puts every file back under its original name — today, or
     next week.

Renaming to random names throws away the only copy of the old name,
which is why this version records every batch before it touches
anything. Files are never overwritten: a new name is claimed
exclusively before the rename, and a batch that renames A to B while
renaming B to A moves everything through temporary names first.

Nothing leaves this Mac — no network access, no telemetry.

  python3 file_renamer.py              # normal launch
  python3 file_renamer.py --selftest   # headless checks, no window
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import database
import prefs as prefs_module
import renamer

APP_NAME = "File Renamer"
VERSION = "1.0.0"
try:
    from _build import BUILD          # written by build.sh on every build
except Exception:
    BUILD = "source"

# Drag-and-drop is a bonus, not a requirement — the app runs fine without
# tkinterdnd2 installed (and it is absent from a plain `python3` run).
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    HAS_DND = False

MODE_LABELS = (
    (renamer.MODE_RANDOM, "Random names  (a7Kd93Xb)"),
    (renamer.MODE_NUMBERED, "Numbered names  (Photo-0001)"),
    (renamer.MODE_KEEP, "Keep each name, change extension only"),
)


# --------------------------------------------------------------- helpers

def center_window(win, width=None, height=None):
    """Open a window centered on screen — every window in this app does.

    Setting the position on a window that has not been mapped yet is racy
    on macOS, so the window is withdrawn, measured, placed, and only then
    shown.
    """
    try:
        win.withdraw()
        win.update_idletasks()
        w = int(width or win.winfo_reqwidth())
        h = int(height or win.winfo_reqheight())
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(24, (sh - h) // 2 - 24)
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        win.deiconify()
    except tk.TclError:
        pass


def center_on_parent(win, parent):
    """Center a dialog over the window that opened it."""
    try:
        win.withdraw()
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        win.geometry("+%d+%d" % (max(0, px + (pw - w) // 2),
                                 max(24, py + (ph - h) // 3)))
        win.deiconify()
    except tk.TclError:
        pass


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%.0f %s" % (size, unit) if unit == "bytes" \
                else "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%d bytes" % num_bytes


def pretty_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %-I:%M %p")
    except (ValueError, TypeError):
        return iso or ""


def plural(count: int, one: str, many=None) -> str:
    return "%d %s" % (count, one if count == 1 else (many or one + "s"))


# ------------------------------------------------------------- the app

class RenamerApp:

    def __init__(self, root):
        self.root = root
        self.prefs = prefs_module.load()
        self.files = []            # list[Path], the queue
        self.plan = []             # list[renamer.Move], parallel to files
        self.plan_error = ""
        self.busy = False
        self.cancel_flag = False
        self.jobs = queue.Queue()
        self._preview_job = None

        root.title(APP_NAME)
        root.minsize(760, 520)
        self._build_style()
        self._build_vars()
        self._build_menu()
        self._build_layout()
        self._restore_geometry()
        self._enable_dnd()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.refresh_history()
        self.refresh_preview()

    # ----------------------------------------------------------- chrome

    def _build_style(self):
        style = ttk.Style()
        # aqua inherits the system Light/Dark appearance; only role styles
        # are defined, never a background or foreground on the base widgets.
        if "aqua" in style.theme_names():
            style.theme_use("aqua")
        style.configure("Header.TLabel", font=("Helvetica", 15, "bold"))
        style.configure("Sub.TLabel", font=("Helvetica", 11))
        style.configure("Muted.TLabel", font=("Helvetica", 11),
                        foreground="#8a8a8e")
        style.configure("Warn.TLabel", font=("Helvetica", 11),
                        foreground="#e5533d")
        style.configure("Ok.TLabel", font=("Helvetica", 11),
                        foreground="#2e9e5b")

    def _build_vars(self):
        p = self.prefs
        self.mode_var = tk.StringVar(value=p["mode"])
        self.length_var = tk.StringVar(value=str(p["random_length"]))
        self.prefix_var = tk.StringVar(value=p["prefix"])
        self.start_var = tk.StringVar(value=str(p["start_number"]))
        self.pad_var = tk.StringVar(value=str(p["pad"]))
        self.ext_mode_var = tk.StringVar(value=p["ext_mode"])
        self.ext_var = tk.StringVar(value=p["extension"])
        self.recurse_var = tk.BooleanVar(value=bool(p["recurse_folders"]))
        self.hidden_var = tk.BooleanVar(value=bool(p["include_hidden"]))
        self.confirm_var = tk.BooleanVar(value=bool(p["confirm_rename"]))
        self.remember_var = tk.BooleanVar(value=bool(p["remember_geometry"]))
        self.status_var = tk.StringVar(value="Add files to get started.")

        for var in (self.mode_var, self.length_var, self.prefix_var,
                    self.start_var, self.pad_var, self.ext_mode_var,
                    self.ext_var):
            var.trace_add("write", self._on_setting_changed)
        for var in (self.recurse_var, self.hidden_var, self.confirm_var,
                    self.remember_var):
            var.trace_add("write", lambda *_a: self.save_prefs())

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Add Files…", accelerator="Cmd+O",
                              command=self.add_files)
        file_menu.add_command(label="Add Folder…", accelerator="Cmd+Shift+O",
                              command=self.add_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Rename Files", accelerator="Cmd+R",
                              command=self.do_rename)
        file_menu.add_command(label="Undo Last Rename", accelerator="Cmd+Z",
                              command=self.undo_last)
        file_menu.add_separator()
        file_menu.add_command(label="Clear List", command=self.clear_list)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About %s" % APP_NAME,
                              command=self.show_about)
        help_menu.add_command(label="Where things are stored",
                              command=self.show_storage)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)
        self.root.bind_all("<Command-o>", lambda _e: self.add_files())
        self.root.bind_all("<Command-O>", lambda _e: self.add_folder())
        self.root.bind_all("<Command-r>", lambda _e: self.do_rename())
        self.root.bind_all("<Command-z>", lambda _e: self.undo_last())

    def _build_layout(self):
        outer = ttk.Frame(self.root, padding=(14, 12))
        outer.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        self.rename_tab = ttk.Frame(self.notebook, padding=12)
        self.history_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.rename_tab, text="  Rename  ")
        self.notebook.add(self.history_tab, text="  History  ")
        try:
            self.notebook.select(int(self.prefs.get("last_tab_index", 0)))
        except (tk.TclError, ValueError):
            pass
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_rename_tab()
        self._build_history_tab()

    # ------------------------------------------------------ rename tab

    def _build_rename_tab(self):
        tab = self.rename_tab

        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Button(bar, text="Add Files…",
                   command=self.add_files).pack(side="left")
        ttk.Button(bar, text="Add Folder…",
                   command=self.add_folder).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Remove Selected",
                   command=self.remove_selected).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Clear List",
                   command=self.clear_list).pack(side="left", padx=(6, 0))
        hint = ("Drag files here, or use Add Files."
                if HAS_DND else "Use Add Files or Add Folder.")
        ttk.Label(bar, text=hint, style="Muted.TLabel").pack(side="right")

        table = ttk.Frame(tab)
        table.pack(fill="both", expand=True, pady=(10, 0))
        columns = ("current", "new", "folder")
        self.tree = ttk.Treeview(table, columns=columns, show="headings",
                                 selectmode="extended", height=12)
        self.tree.heading("current", text="Current name")
        self.tree.heading("new", text="New name")
        self.tree.heading("folder", text="Folder")
        self.tree.column("current", width=230, anchor="w")
        self.tree.column("new", width=230, anchor="w")
        self.tree.column("folder", width=260, anchor="w")
        self.tree.tag_configure("unchanged", foreground="#8a8a8e")
        vsb = ttk.Scrollbar(table, orient="vertical",
                            command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<BackSpace>", lambda _e: self.remove_selected())
        self.tree.bind("<Delete>", lambda _e: self.remove_selected())

        self._build_options(tab)

        action = ttk.Frame(tab)
        action.pack(fill="x", pady=(12, 0))
        self.progress = ttk.Progressbar(action, mode="determinate",
                                        length=200)
        self.rename_btn = ttk.Button(action, text="Rename Files",
                                     command=self.do_rename)
        self.rename_btn.pack(side="right")
        self.undo_btn = ttk.Button(action, text="Undo Last Rename",
                                   command=self.undo_last)
        self.undo_btn.pack(side="right", padx=(0, 8))
        self.status_label = ttk.Label(action, textvariable=self.status_var,
                                      style="Sub.TLabel")
        self.status_label.pack(side="left")

    def _build_options(self, parent):
        box = ttk.LabelFrame(parent, text=" Naming ", padding=10)
        box.pack(fill="x", pady=(12, 0))

        for value, label in MODE_LABELS:
            ttk.Radiobutton(box, text=label, value=value,
                            variable=self.mode_var).pack(anchor="w")

        detail = ttk.Frame(box)
        detail.pack(fill="x", pady=(8, 0))

        self.random_row = ttk.Frame(detail)
        ttk.Label(self.random_row, text="Name length:").pack(side="left")
        ttk.Spinbox(self.random_row, from_=renamer.RANDOM_LEN_MIN,
                    to=renamer.RANDOM_LEN_MAX, width=5,
                    textvariable=self.length_var).pack(side="left", padx=(6, 0))
        ttk.Label(self.random_row, text="characters",
                  style="Muted.TLabel").pack(side="left", padx=(6, 0))

        self.numbered_row = ttk.Frame(detail)
        ttk.Label(self.numbered_row, text="Prefix:").pack(side="left")
        ttk.Entry(self.numbered_row, width=16,
                  textvariable=self.prefix_var).pack(side="left", padx=(6, 12))
        ttk.Label(self.numbered_row, text="Start at:").pack(side="left")
        ttk.Spinbox(self.numbered_row, from_=0, to=999999, width=6,
                    textvariable=self.start_var).pack(side="left", padx=(6, 12))
        ttk.Label(self.numbered_row, text="Digits:").pack(side="left")
        ttk.Spinbox(self.numbered_row, from_=0, to=9, width=4,
                    textvariable=self.pad_var).pack(side="left", padx=(6, 0))
        ttk.Label(self.numbered_row, text="(0 = automatic)",
                  style="Muted.TLabel").pack(side="left", padx=(6, 0))

        ext_box = ttk.Frame(box)
        ext_box.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(ext_box, text="Keep original extension",
                        value=renamer.EXT_KEEP,
                        variable=self.ext_mode_var).pack(side="left")
        ttk.Radiobutton(ext_box, text="Change to:", value=renamer.EXT_SET,
                        variable=self.ext_mode_var).pack(side="left",
                                                         padx=(14, 4))
        ttk.Entry(ext_box, width=10,
                  textvariable=self.ext_var).pack(side="left")

        opts = ttk.Frame(box)
        opts.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(opts, text="Include subfolders when adding a folder",
                        variable=self.recurse_var).pack(side="left")
        ttk.Checkbutton(opts, text="Include hidden files",
                        variable=self.hidden_var).pack(side="left", padx=(14, 0))
        ttk.Checkbutton(opts, text="Ask before renaming",
                        variable=self.confirm_var).pack(side="left", padx=(14, 0))

        self._sync_detail_rows()

    def _sync_detail_rows(self):
        mode = self.mode_var.get()
        for row in (self.random_row, self.numbered_row):
            row.pack_forget()
        if mode == renamer.MODE_RANDOM:
            self.random_row.pack(fill="x")
        elif mode == renamer.MODE_NUMBERED:
            self.numbered_row.pack(fill="x")

    # ----------------------------------------------------- history tab

    def _build_history_tab(self):
        tab = self.history_tab
        ttk.Label(tab, text="Every rename is recorded here so it can be "
                            "undone later.", style="Sub.TLabel").pack(anchor="w")

        top = ttk.Frame(tab)
        top.pack(fill="both", expand=True, pady=(10, 0))
        columns = ("when", "what", "files", "state", "folder")
        self.hist_tree = ttk.Treeview(top, columns=columns, show="headings",
                                      selectmode="browse", height=9)
        for name, text, width in (("when", "When", 175),
                                  ("what", "Naming", 120),
                                  ("files", "Files", 60),
                                  ("state", "Status", 110),
                                  ("folder", "Folder", 280)):
            self.hist_tree.heading(name, text=text)
            self.hist_tree.column(name, width=width, anchor="w")
        self.hist_tree.column("files", anchor="e")
        self.hist_tree.tag_configure("undone", foreground="#8a8a8e")
        hsb = ttk.Scrollbar(top, orient="vertical",
                            command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=hsb.set)
        self.hist_tree.pack(side="left", fill="both", expand=True)
        hsb.pack(side="left", fill="y")
        self.hist_tree.bind("<<TreeviewSelect>>", self._on_history_select)

        ttk.Label(tab, text="Files in the selected batch",
                  style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        bottom = ttk.Frame(tab)
        bottom.pack(fill="both", expand=True)
        self.detail_tree = ttk.Treeview(bottom, columns=("old", "new"),
                                        show="headings", height=6)
        self.detail_tree.heading("old", text="Original name")
        self.detail_tree.heading("new", text="Renamed to")
        self.detail_tree.column("old", width=320, anchor="w")
        self.detail_tree.column("new", width=320, anchor="w")
        self.detail_tree.tag_configure("undone", foreground="#8a8a8e")
        dsb = ttk.Scrollbar(bottom, orient="vertical",
                            command=self.detail_tree.yview)
        self.detail_tree.configure(yscrollcommand=dsb.set)
        self.detail_tree.pack(side="left", fill="both", expand=True)
        dsb.pack(side="left", fill="y")

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(12, 0))
        ttk.Button(row, text="Undo Selected Batch",
                   command=self.undo_selected).pack(side="left")
        ttk.Button(row, text="Forget Selected",
                   command=self.forget_selected).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Clear History…",
                   command=self.clear_history).pack(side="left", padx=(8, 0))
        self.hist_status = ttk.Label(row, text="", style="Muted.TLabel")
        self.hist_status.pack(side="right")

    # --------------------------------------------------------- queueing

    def add_files(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(
            title="Select files to rename",
            initialdir=self.prefs.get("last_dir") or str(Path.home()))
        if paths:
            self._remember_dir(paths[0])
            self.add_paths(paths)

    def add_folder(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(
            title="Select a folder of files to rename",
            initialdir=self.prefs.get("last_dir") or str(Path.home()))
        if folder:
            self._remember_dir(folder)
            self.add_paths([folder])

    def _remember_dir(self, path):
        try:
            path = Path(path)
            self.prefs["last_dir"] = str(path if path.is_dir()
                                         else path.parent)
            self.save_prefs()
        except OSError:
            pass

    def add_paths(self, paths):
        """Add files/folders, keeping the list unique and sorted."""
        try:
            found = renamer.gather(paths,
                                   recurse=self.recurse_var.get(),
                                   include_hidden=self.hidden_var.get())
        except OSError as err:
            self.warn("Could not read those items",
                      renamer.friendly_error(err, Path(str(paths[0]))))
            return
        known = {os.path.normcase(str(p)) for p in self.files}
        added = [p for p in found
                 if os.path.normcase(str(p)) not in known]
        if not added:
            if found:
                self.status_var.set("Those files are already in the list.")
            else:
                self.status_var.set(
                    "Nothing to rename there — no files were found.")
            return
        self.files.extend(added)
        self.files.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))
        self.refresh_preview()

    def remove_selected(self):
        if self.busy:
            return
        indexes = {int(i) for i in self.tree.selection()}
        if not indexes:
            return
        self.files = [f for n, f in enumerate(self.files) if n not in indexes]
        self.refresh_preview()

    def clear_list(self):
        if self.busy:
            return
        self.files = []
        self.refresh_preview()

    def _enable_dnd(self):
        if not HAS_DND:
            return
        try:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self._on_drop)
        except (tk.TclError, AttributeError):
            pass

    def _on_drop(self, event):
        try:
            paths = self.root.tk.splitlist(event.data)
        except tk.TclError:
            paths = [event.data]
        self.add_paths(paths)

    # ---------------------------------------------------------- preview

    def _on_setting_changed(self, *_args):
        self._sync_detail_rows()
        self.save_prefs()
        if self._preview_job is not None:
            try:
                self.root.after_cancel(self._preview_job)
            except tk.TclError:
                pass
        self._preview_job = self.root.after(180, self.refresh_preview)

    def refresh_preview(self):
        """Rebuild the plan and repaint the table. Cheap enough to
        re-run on every keystroke, debounced by _on_setting_changed."""
        self._preview_job = None
        self.plan_error = ""
        self.plan = []
        if self.files:
            try:
                self.plan = renamer.build_plan(
                    self.files, self.mode_var.get(),
                    random_length=self._int(self.length_var, 8),
                    prefix=self.prefix_var.get() or "File",
                    start_number=self._int(self.start_var, 1),
                    pad=self._int(self.pad_var, 0),
                    ext_mode=self.ext_mode_var.get(),
                    extension=self.ext_var.get())
            except renamer.PlanError as err:
                self.plan_error = str(err)

        self.tree.delete(*self.tree.get_children())
        for index, path in enumerate(self.files):
            move = self.plan[index] if index < len(self.plan) else None
            if move is None:
                new_name, tags = "—", ("unchanged",)
            elif move.changed:
                new_name, tags = move.dst.name, ()
            else:
                new_name, tags = "(no change)", ("unchanged",)
            self.tree.insert("", "end", iid=str(index), tags=tags,
                             values=(path.name, new_name, str(path.parent)))
        self._update_status()
        self._update_buttons()

    def _update_status(self):
        if self.plan_error:
            self.status_label.configure(style="Warn.TLabel")
            self.status_var.set(self.plan_error)
            return
        self.status_label.configure(style="Sub.TLabel")
        if not self.files:
            self.status_var.set("Add files to get started.")
            return
        changing = len(renamer.changed_moves(self.plan))
        if changing == len(self.files):
            self.status_var.set("%s ready to rename."
                                % plural(len(self.files), "file"))
        else:
            self.status_var.set(
                "%s in the list — %s will be renamed."
                % (plural(len(self.files), "file"), plural(changing, "file")))

    def _update_buttons(self):
        can_rename = bool(self.plan) and not self.plan_error \
            and bool(renamer.changed_moves(self.plan)) and not self.busy
        self.rename_btn.configure(
            state=("normal" if can_rename else "disabled"))
        try:
            undoable = database.latest_undoable() is not None
        except Exception:
            undoable = False
        self.undo_btn.configure(
            state=("normal" if undoable and not self.busy else "disabled"))

    @staticmethod
    def _int(var, fallback):
        try:
            return int(str(var.get()).strip())
        except (ValueError, tk.TclError):
            return fallback

    # ---------------------------------------------------------- renaming

    def do_rename(self):
        if self.busy:
            return
        if self.plan_error:
            self.warn("Check the settings", self.plan_error)
            return
        moves = renamer.changed_moves(self.plan)
        if not moves:
            self.warn("Nothing to do",
                      "None of these files would get a different name. "
                      "Change the naming style or the extension first.")
            return
        if self.confirm_var.get():
            question = ("Rename %s?\n\nThe current names will be replaced. "
                        "You can put them back with Undo Last Rename."
                        % plural(len(moves), "file"))
            if not messagebox.askyesno(APP_NAME, question, parent=self.root):
                return

        mode = self.mode_var.get()
        ext_mode = self.ext_mode_var.get()
        extension = self.ext_var.get()

        def work(progress, cancelled):
            outcome = renamer.execute_plan(moves, progress, cancelled)
            batch_id = None
            if outcome.done:
                batch_id = database.record_batch(
                    mode, ext_mode, extension,
                    [(m.src, m.dst) for m in outcome.done],
                    failed=len(outcome.failures))
            return ("rename", outcome, batch_id)

        self._start_job(work, len(moves), "Renaming…")

    def undo_last(self):
        if self.busy:
            return
        try:
            batch = database.latest_undoable()
        except Exception as err:
            self.warn("Could not read the history", self._store_error(err))
            return
        if batch is None:
            self.warn("Nothing to undo",
                      "There is no rename left to put back.")
            return
        self._undo_batch(int(batch["id"]))

    def undo_selected(self):
        selection = self.hist_tree.selection()
        if not selection:
            self.warn("Pick a batch",
                      "Select a rename in the list above first.")
            return
        self._undo_batch(int(selection[0]))

    def _undo_batch(self, batch_id):
        if self.busy:
            return
        try:
            rows = database.list_moves(batch_id, pending_only=True)
        except Exception as err:
            self.warn("Could not read the history", self._store_error(err))
            return
        if not rows:
            self.warn("Already undone",
                      "Every file in that rename is already back under its "
                      "original name.")
            return
        pairs = [(row["old_path"], row["new_path"]) for row in rows]
        question = ("Put %s back under the original name%s?"
                    % (plural(len(pairs), "file"),
                       "" if len(pairs) == 1 else "s"))
        if not messagebox.askyesno(APP_NAME, question, parent=self.root):
            return

        def work(progress, cancelled):
            plan = [renamer.Move(Path(new), Path(old)) for old, new in pairs]
            outcome = renamer.execute_plan(plan, progress, cancelled)
            restored = [(str(m.dst), str(m.src)) for m in outcome.done]
            if restored:
                database.mark_undone(batch_id, restored)
            return ("undo", outcome, batch_id)

        self._start_job(work, len(pairs), "Putting names back…")

    # -------------------------------------------------------- job runner

    def _start_job(self, work, total, label):
        """Run `work` off the main thread; Tk is only touched by the poll."""
        self.busy = True
        self.cancel_flag = False
        self.jobs = queue.Queue()
        self.progress.configure(maximum=max(1, total), value=0)
        self.progress.pack(side="left", padx=(0, 12))
        self.status_label.configure(style="Sub.TLabel")
        self.status_var.set(label)
        self._set_controls_enabled(False)

        def progress(step, count, path):
            self.jobs.put(("progress", step, count, path))

        def cancelled():
            return self.cancel_flag

        def runner():
            try:
                self.jobs.put(work(progress, cancelled))
            except Exception:
                self.jobs.put(("crash", traceback.format_exc(), None))

        threading.Thread(target=runner, daemon=True).start()
        self.root.after(60, self._poll_job)

    def _poll_job(self):
        finished = None
        try:
            while True:
                message = self.jobs.get_nowait()
                if message[0] == "progress":
                    _kind, step, count, path = message
                    self.progress.configure(maximum=max(1, count), value=step)
                    self.status_var.set("Renaming %s (%d of %d)…"
                                        % (Path(path).name, step, count))
                else:
                    finished = message
        except queue.Empty:
            pass
        if finished is None:
            self.root.after(60, self._poll_job)
            return
        self._finish_job(finished)

    def _finish_job(self, message):
        self.busy = False
        self.progress.pack_forget()
        self._set_controls_enabled(True)
        kind = message[0]

        if kind == "crash":
            self.warn("Something went wrong",
                      "File Renamer hit an unexpected problem and stopped "
                      "before finishing. No further files were changed.\n\n"
                      "Details:\n%s" % message[1].strip().splitlines()[-1])
            self.refresh_preview()
            self.refresh_history()
            return

        _kind, outcome, _batch_id = message
        if kind == "rename":
            done = {os.path.normcase(str(m.src)) for m in outcome.done}
            self.files = [f for f in self.files
                          if os.path.normcase(str(f)) not in done]
        self.refresh_preview()
        self.refresh_history()
        self._report(kind, outcome)

    def _report(self, kind, outcome):
        verb = "renamed" if kind == "rename" else "put back"
        count = len(outcome.done)
        if not outcome.failures:
            self.status_label.configure(style="Ok.TLabel")
            self.status_var.set("%s %s." % (plural(count, "file"), verb))
            return
        self.status_label.configure(style="Warn.TLabel")
        self.status_var.set("%s %s, %s skipped."
                            % (plural(count, "file"), verb,
                               plural(len(outcome.failures), "file")))
        lines = [msg for _path, msg in outcome.failures[:12]]
        if len(outcome.failures) > 12:
            lines.append("…and %s more."
                         % plural(len(outcome.failures) - 12, "file"))
        messagebox.showwarning(
            APP_NAME,
            "%s %s. These were left alone:\n\n%s"
            % (plural(count, "file"), verb, "\n\n".join(lines)),
            parent=self.root)

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for widget in (self.rename_btn, self.undo_btn):
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        if enabled:
            self._update_buttons()

    # ----------------------------------------------------------- history

    def refresh_history(self):
        try:
            batches = database.list_batches()
        except Exception as err:
            self.hist_status.configure(text=self._store_error(err))
            return
        self.hist_tree.delete(*self.hist_tree.get_children())
        self.detail_tree.delete(*self.detail_tree.get_children())
        labels = {renamer.MODE_RANDOM: "Random",
                  renamer.MODE_NUMBERED: "Numbered",
                  renamer.MODE_KEEP: "Extension only"}
        states = {0: "Can undo", 1: "Undone", 2: "Partly undone"}
        for row in batches:
            state = int(row["undone"] or 0)
            naming = labels.get(row["mode"], row["mode"])
            if row["ext_mode"] == renamer.EXT_SET and row["extension"]:
                try:
                    naming += " " + renamer.normalise_extension(
                        row["extension"])
                except renamer.PlanError:
                    pass
            self.hist_tree.insert(
                "", "end", iid=str(row["id"]),
                tags=("undone",) if state == 1 else (),
                values=(pretty_time(row["ts"]), naming, row["renamed"],
                        states.get(state, ""), row["folder"] or ""))
        count_batches, count_moves = database.history_counts()
        self.hist_status.configure(
            text="%s, %s recorded · %s"
                 % (plural(count_batches, "rename"), plural(count_moves, "file"),
                    human_size(database.history_size_bytes())))
        self._update_buttons()

    def _on_history_select(self, _event=None):
        self.detail_tree.delete(*self.detail_tree.get_children())
        selection = self.hist_tree.selection()
        if not selection:
            return
        try:
            rows = database.list_moves(int(selection[0]))
        except Exception:
            return
        for row in rows:
            self.detail_tree.insert(
                "", "end",
                tags=("undone",) if int(row["undone"] or 0) else (),
                values=(Path(row["old_path"]).name,
                        Path(row["new_path"]).name))

    def forget_selected(self):
        selection = self.hist_tree.selection()
        if not selection:
            self.warn("Pick a batch", "Select a rename in the list first.")
            return
        if not messagebox.askyesno(
                APP_NAME,
                "Remove this rename from the history?\n\nThe files stay "
                "exactly as they are — but they can no longer be undone.",
                parent=self.root):
            return
        try:
            database.delete_batch(int(selection[0]))
        except Exception as err:
            self.warn("Could not update the history", self._store_error(err))
            return
        self.refresh_history()

    def clear_history(self):
        if not messagebox.askyesno(
                APP_NAME,
                "Erase the whole rename history?\n\nNo files are touched, "
                "but nothing can be undone afterwards.",
                parent=self.root):
            return
        try:
            database.clear_history()
        except Exception as err:
            self.warn("Could not clear the history", self._store_error(err))
            return
        self.refresh_history()

    def _on_tab_changed(self, _event=None):
        try:
            self.prefs["last_tab_index"] = self.notebook.index("current")
            self.save_prefs()
        except tk.TclError:
            pass

    # ----------------------------------------------------------- dialogs

    def warn(self, title, detail):
        messagebox.showwarning(APP_NAME, "%s\n\n%s" % (title, detail),
                               parent=self.root)

    @staticmethod
    def _store_error(err):
        return ("The rename history could not be read or written. It lives "
                "in %s — check that folder is available and not full.\n\n"
                "(%s)" % (database.app_dir(), err))

    def show_about(self):
        messagebox.showinfo(
            APP_NAME,
            "%s %s (build %s)\n\n"
            "Batch renaming with an undo that survives quitting the app.\n\n"
            "Everything stays on this Mac — no network access, no "
            "telemetry, and source files are never copied anywhere.\n\n"
            "Python %s · Tk %s"
            % (APP_NAME, VERSION, BUILD,
               "%d.%d.%d" % sys.version_info[:3],
               self.root.tk.call("info", "patchlevel")),
            parent=self.root)

    def show_storage(self):
        messagebox.showinfo(
            APP_NAME,
            "File Renamer keeps two files, both in:\n\n%s\n\n"
            "• file_renamer.sqlite3 — the rename history that Undo uses\n"
            "• prefs.json — window size and your last settings\n\n"
            "Delete that folder to reset the app completely. Your renamed "
            "files are not affected."
            % database.app_dir(), parent=self.root)

    # -------------------------------------------------------- lifecycle

    def _restore_geometry(self):
        window = self.prefs.get("window") or prefs_module.DEFAULTS["window"]
        width = int(window.get("w") or 900)
        height = int(window.get("h") or 640)
        x, y = window.get("x"), window.get("y")
        if self.remember_var.get() and x is not None and y is not None:
            self.root.withdraw()
            self.root.update_idletasks()
            self.root.geometry("%dx%d+%d+%d" % (width, height, int(x), int(y)))
            self.root.deiconify()
        else:
            center_window(self.root, width, height)

    def save_prefs(self):
        self.prefs.update({
            "mode": self.mode_var.get(),
            "random_length": self._int(self.length_var, 8),
            "prefix": self.prefix_var.get(),
            "start_number": self._int(self.start_var, 1),
            "pad": self._int(self.pad_var, 0),
            "ext_mode": self.ext_mode_var.get(),
            "extension": self.ext_var.get(),
            "recurse_folders": bool(self.recurse_var.get()),
            "include_hidden": bool(self.hidden_var.get()),
            "confirm_rename": bool(self.confirm_var.get()),
            "remember_geometry": bool(self.remember_var.get()),
        })
        prefs_module.save(self.prefs)

    def on_close(self):
        if self.busy:
            if not messagebox.askyesno(
                    APP_NAME, "A rename is still running. Quit anyway?",
                    parent=self.root):
                return
            self.cancel_flag = True
        try:
            if self.remember_var.get():
                self.prefs["window"] = prefs_module.capture_geometry(self.root)
            self.save_prefs()
        except tk.TclError:
            pass
        self.root.destroy()


# ----------------------------------------------------------------- entry

def make_root():
    """Tk root, with drag-and-drop support when tkinterdnd2 is present."""
    if HAS_DND:
        try:
            return TkinterDnD.Tk()
        except Exception:
            pass
    return tk.Tk()


def run_gui() -> int:
    try:
        database.init_db()
    except Exception as err:
        # No history means no undo — say so plainly rather than dying.
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            APP_NAME,
            "File Renamer could not open its history file in\n%s\n\n"
            "The app will still rename files, but Undo will not be "
            "available until that folder can be written to.\n\n(%s)"
            % (database.app_dir(), err))
        root.destroy()

    root = make_root()
    RenamerApp(root)
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="file-renamer",
                                     description="Batch file renamer for macOS.")
    parser.add_argument("--selftest", action="store_true",
                        help="run the built-in checks and exit (no window)")
    parser.add_argument("--version", action="store_true",
                        help="print the version and exit")
    args, _unknown = parser.parse_known_args()

    if args.version:
        print("%s %s (build %s)" % (APP_NAME, VERSION, BUILD))
        return 0
    if args.selftest:
        import selftest
        return 0 if selftest.run() else 1
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
