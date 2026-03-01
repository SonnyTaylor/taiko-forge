"""Taiko Forge GUI application."""

import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from taiko_forge.builder import DLCBuilder
from taiko_forge.config import CONFIG_DIR, find_tool, load_config, save_config
from taiko_forge.tja import parse_tja

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# When frozen by PyInstaller __file__ lives in a temp dir — use the persistent
# config dir for tool downloads so they survive between launches.
if getattr(sys, "frozen", False):
    _TOOLS_DIR = CONFIG_DIR / "tools"
else:
    _TOOLS_DIR = _PROJECT_ROOT / "tools"


# ======================================================================
# Catppuccin Mocha palette
# ======================================================================
class C:
    BG = "#1e1e2e"
    SURFACE = "#313244"
    SURFACE2 = "#45475a"
    TEXT = "#cdd6f4"
    SUBTEXT = "#a6adc8"
    RED = "#f38ba8"
    GREEN = "#a6e3a1"
    BLUE = "#89b4fa"
    PEACH = "#fab387"
    YELLOW = "#f9e2af"
    TEAL = "#94e2d5"


# ======================================================================
# Small reusable modal: download progress
# ======================================================================
class _ProgressDialog:
    """Small modal window showing a download progress bar."""

    def __init__(self, parent, title: str):
        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.geometry("400x130")
        self.win.resizable(False, False)
        self.win.configure(bg=C.BG)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)  # block close

        self._status = tk.StringVar(value="Connecting…")
        self._prog = tk.DoubleVar(value=0.0)

        ttk.Label(self.win, textvariable=self._status, style="TLabel").pack(
            padx=16, pady=(18, 6)
        )
        ttk.Progressbar(
            self.win,
            variable=self._prog,
            maximum=1.0,
            mode="determinate",
            style="Horizontal.TProgressbar",
        ).pack(fill="x", padx=16, pady=(0, 8))
        self._btn = ttk.Button(
            self.win,
            text="Close",
            state="disabled",
            command=self.win.destroy,
            style="Browse.TButton",
        )
        self._btn.pack(pady=(0, 12))

    # thread-safe updates
    def status(self, text: str):
        self.win.after(0, self._status.set, text)

    def progress(self, frac: float):
        self.win.after(0, self._prog.set, frac)

    def done(self, msg: str = "Done!"):
        self.win.after(0, self._finish, msg, True)

    def error(self, msg: str):
        self.win.after(0, self._finish, f"Error: {msg}", True)

    def _finish(self, msg: str, enable_close: bool):
        self._status.set(msg)
        self._prog.set(1.0)
        if enable_close:
            self.win.protocol("WM_DELETE_WINDOW", self.win.destroy)
            self._btn.configure(state="normal")


# ======================================================================
# ESE Online Song Browser dialog
# ======================================================================
class _ESEDialog:
    """Browse and download songs from the ESE TJA database (online)."""

    def __init__(self, parent, on_select):
        """on_select(tja_path: str, ogg_path: str) called on success."""
        from taiko_forge.ese_browser import GENRES

        self.on_select = on_select
        self.songs: list[dict] = []
        self.filtered: list[dict] = []
        self._genres = GENRES

        self.win = tk.Toplevel(parent)
        self.win.title("ESE Song Browser")
        self.win.geometry("580x500")
        self.win.minsize(460, 400)
        self.win.configure(bg=C.BG)
        self.win.transient(parent)
        self.win.grab_set()

        self._build_ui()
        # Kick off first genre load
        self._load_genre(self._genres[0])

    # ------------------------------------------------------------------
    def _build_ui(self):
        s = self.win

        # ── top bar ──────────────────────────────────────────────────
        top = ttk.Frame(s)
        top.pack(fill="x", padx=12, pady=(12, 6))

        ttk.Label(top, text="Genre:").pack(side="left")
        self._genre_var = tk.StringVar(value=self._genres[0])
        cb = ttk.Combobox(
            top,
            textvariable=self._genre_var,
            values=self._genres,
            state="readonly",
            width=24,
        )
        cb.pack(side="left", padx=(4, 16))
        cb.bind("<<ComboboxSelected>>", lambda _: self._load_genre(self._genre_var.get()))

        ttk.Label(top, text="Search:").pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        ttk.Entry(top, textvariable=self._search_var).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        # ── count + listbox ──────────────────────────────────────────
        mid = ttk.Frame(s)
        mid.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self._count_var = tk.StringVar(value="Loading…")
        ttk.Label(mid, textvariable=self._count_var, style="Sub.TLabel").pack(
            anchor="w", pady=(0, 4)
        )

        lf = tk.Frame(mid, bg=C.SURFACE2, bd=0)
        lf.pack(fill="both", expand=True)
        self._lb = tk.Listbox(
            lf,
            bg=C.SURFACE2,
            fg=C.TEXT,
            selectbackground=C.BLUE,
            selectforeground=C.BG,
            font=("Segoe UI", 10),
            activestyle="none",
            relief="flat",
            bd=0,
        )
        sb = ttk.Scrollbar(lf, command=self._lb.yview)
        self._lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._lb.pack(fill="both", expand=True, padx=2, pady=2)
        self._lb.bind("<<ListboxSelect>>", self._on_lb_select)
        # Double-click to download immediately
        self._lb.bind("<Double-Button-1>", lambda _: self._download_and_use())

        # ── selected song info ───────────────────────────────────────
        self._info_var = tk.StringVar(value="Select a song, then click Download & Use.")
        ttk.Label(
            s,
            textvariable=self._info_var,
            style="Info.TLabel",
            wraplength=540,
        ).pack(padx=12, anchor="w", pady=(0, 4))

        # ── download progress ────────────────────────────────────────
        self._dl_prog = tk.DoubleVar(value=0.0)
        ttk.Progressbar(
            s,
            variable=self._dl_prog,
            maximum=1.0,
            mode="determinate",
            style="Horizontal.TProgressbar",
        ).pack(fill="x", padx=12, pady=(0, 2))
        self._dl_status = tk.StringVar(value="")
        ttk.Label(s, textvariable=self._dl_status, style="Sub.TLabel").pack(
            padx=12, anchor="w", pady=(0, 6)
        )

        # ── buttons ──────────────────────────────────────────────────
        bf = ttk.Frame(s)
        bf.pack(fill="x", padx=12, pady=(0, 14))
        self._btn_dl = ttk.Button(
            bf,
            text="Download & Use Song",
            style="Build.TButton",
            command=self._download_and_use,
            state="disabled",
        )
        self._btn_dl.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(
            bf, text="Cancel", style="Browse.TButton", command=self.win.destroy
        ).pack(side="right")

    # ------------------------------------------------------------------
    def _load_genre(self, genre: str):
        self.songs = []
        self.filtered = []
        self._lb.delete(0, "end")
        self._count_var.set("Loading…")
        self._btn_dl.configure(state="disabled")
        self._search_var.set("")

        def fetch():
            from taiko_forge.ese_browser import list_songs

            try:
                songs = list_songs(genre)
                self.win.after(0, self._set_songs, songs)
            except Exception as exc:
                self.win.after(0, self._count_var.set, f"Error loading: {exc}")

        threading.Thread(target=fetch, daemon=True).start()

    def _set_songs(self, songs: list):
        self.songs = songs
        self._filter()

    def _filter(self):
        q = self._search_var.get().lower()
        self.filtered = [s for s in self.songs if q in s["name"].lower()]
        self._lb.delete(0, "end")
        for s in self.filtered:
            self._lb.insert("end", "  " + s["name"])
        self._count_var.set(f"{len(self.filtered)} songs")

    def _on_lb_select(self, _evt=None):
        sel = self._lb.curselection()
        if not sel:
            self._btn_dl.configure(state="disabled")
            return
        song = self.filtered[sel[0]]
        self._info_var.set(f"Selected: {song['name']}")
        self._btn_dl.configure(state="normal")

    def _download_and_use(self):
        sel = self._lb.curselection()
        if not sel:
            return
        song = self.filtered[sel[0]]
        dest_dir = CONFIG_DIR / "songs" / song["name"]
        tja_path = dest_dir / f"{song['name']}.tja"
        ogg_path = dest_dir / f"{song['name']}.ogg"

        # Already cached
        if tja_path.exists() and ogg_path.exists():
            self.on_select(str(tja_path), str(ogg_path))
            self.win.destroy()
            return

        self._btn_dl.configure(state="disabled")
        self._dl_status.set("Downloading chart…")
        self._dl_prog.set(0.05)

        def run():
            from taiko_forge.ese_browser import download_audio, download_tja

            try:
                download_tja(song, dest_dir)
                self.win.after(0, self._dl_status.set, "Downloading audio…")
                self.win.after(0, self._dl_prog.set, 0.25)

                def _audio_prog(f):
                    self.win.after(0, self._dl_prog.set, 0.25 + f * 0.75)

                download_audio(song, dest_dir, _audio_prog)
                self.win.after(0, self._on_dl_done, str(tja_path), str(ogg_path))
            except Exception as exc:
                self.win.after(0, self._on_dl_error, str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _on_dl_done(self, tja: str, ogg: str):
        self._dl_status.set("Done!")
        self._dl_prog.set(1.0)
        self.on_select(tja, ogg)
        self.win.destroy()

    def _on_dl_error(self, msg: str):
        self._dl_status.set(f"Error: {msg}")
        self._btn_dl.configure(state="normal")


# ======================================================================
# Main application
# ======================================================================
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Taiko Forge")
        self.root.geometry("800x960")
        self.root.minsize(680, 800)
        self.root.configure(bg=C.BG)
        self.root.option_add("*Font", ("Segoe UI", 10))

        self.cfg = load_config()
        self.building = False

        self._setup_styles()
        self._build_ui()
        self._restore_state()
        self._check_deps()

    # ── styling ─────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(
            ".",
            background=C.BG,
            foreground=C.TEXT,
            fieldbackground=C.SURFACE,
            borderwidth=0,
        )
        s.configure("TFrame", background=C.BG)
        s.configure("Card.TFrame", background=C.SURFACE)
        s.configure("TLabel", background=C.BG, foreground=C.TEXT, font=("Segoe UI", 10))
        s.configure("Card.TLabel", background=C.SURFACE, foreground=C.TEXT)
        s.configure(
            "Header.TLabel",
            background=C.BG,
            foreground=C.PEACH,
            font=("Segoe UI", 11, "bold"),
        )
        s.configure(
            "Title.TLabel",
            background=C.BG,
            foreground=C.TEXT,
            font=("Segoe UI", 18, "bold"),
        )
        s.configure(
            "Sub.TLabel", background=C.BG, foreground=C.SUBTEXT, font=("Segoe UI", 9)
        )
        s.configure(
            "Info.TLabel",
            background=C.SURFACE,
            foreground=C.BLUE,
            font=("Segoe UI Semibold", 10),
        )
        s.configure(
            "TEntry",
            fieldbackground=C.SURFACE2,
            foreground=C.TEXT,
            insertcolor=C.TEXT,
        )
        s.configure(
            "TButton",
            background=C.SURFACE2,
            foreground=C.TEXT,
            font=("Segoe UI Semibold", 10),
            padding=(12, 6),
        )
        s.map(
            "TButton",
            background=[("active", C.BLUE), ("disabled", C.SURFACE)],
            foreground=[("active", C.BG), ("disabled", C.SUBTEXT)],
        )
        s.configure(
            "Build.TButton",
            background=C.BLUE,
            foreground=C.BG,
            font=("Segoe UI", 13, "bold"),
            padding=(20, 10),
        )
        s.map(
            "Build.TButton",
            background=[("active", C.GREEN), ("disabled", C.SURFACE)],
            foreground=[("active", C.BG), ("disabled", C.SUBTEXT)],
        )
        s.configure("Browse.TButton", padding=(8, 4), font=("Segoe UI", 9))
        s.configure("Download.TButton", padding=(8, 4), font=("Segoe UI", 9))
        s.map(
            "Download.TButton",
            background=[("active", C.TEAL), ("disabled", C.SURFACE)],
            foreground=[("active", C.BG)],
        )
        s.configure(
            "Horizontal.TProgressbar",
            troughcolor=C.SURFACE2,
            background=C.GREEN,
            thickness=8,
        )
        s.configure(
            "TLabelframe",
            background=C.SURFACE,
            foreground=C.PEACH,
            font=("Segoe UI", 10, "bold"),
        )
        s.configure(
            "TLabelframe.Label",
            background=C.SURFACE,
            foreground=C.PEACH,
            font=("Segoe UI", 10, "bold"),
        )
        s.configure("TCombobox", fieldbackground=C.SURFACE2, foreground=C.TEXT)

    # ── UI build ─────────────────────────────────────────────────────
    def _build_ui(self):
        outer = tk.Frame(self.root, bg=C.BG)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=C.BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.scroll_frame = ttk.Frame(canvas, style="TFrame")
        self.scroll_frame.bind(
            "<Configure>",
            lambda _: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(canvas.find_all()[0], width=e.width),
        )

        pad = {"padx": 16, "pady": (4, 4)}
        m = self.scroll_frame  # shorthand

        # ── Title ──────────────────────────────────────────────────
        ttk.Label(m, text="Taiko Forge", style="Title.TLabel").pack(
            pady=(16, 0), padx=16, anchor="w"
        )
        ttk.Label(
            m,
            text="Custom DLC builder for Taiko no Tatsujin Portable DX (PSP)",
            style="Sub.TLabel",
        ).pack(padx=16, anchor="w", pady=(0, 8))

        # ── Setup ──────────────────────────────────────────────────
        setup_frame = ttk.LabelFrame(m, text="  Setup  ", style="TLabelframe")
        setup_frame.pack(fill="x", padx=16, pady=(8, 4))
        si = ttk.Frame(setup_frame, style="Card.TFrame")
        si.pack(fill="x", padx=12, pady=8)
        si.columnconfigure(1, weight=1)

        # Status row (dep check labels)
        self.dep_labels: dict[str, ttk.Label] = {}
        for col, tool in enumerate(["ffmpeg", "tja2fumen", "at3tool"]):
            ttk.Label(si, text=f"{tool}:", style="Card.TLabel").grid(
                row=0, column=col * 2, sticky="w", padx=(0 if col == 0 else 12, 4), pady=(0, 6)
            )
            lbl = ttk.Label(si, text="checking…", style="Card.TLabel")
            lbl.grid(row=0, column=col * 2 + 1, sticky="w", pady=(0, 6))
            self.dep_labels[tool] = lbl

        ttk.Separator(si, orient="horizontal").grid(
            row=1, column=0, columnspan=6, sticky="ew", pady=(0, 6)
        )

        # at3tool path row
        self.var_at3tool = tk.StringVar()
        ttk.Label(si, text="at3tool.exe:", style="Card.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=4, padx=(0, 8)
        )
        ttk.Entry(si, textvariable=self.var_at3tool).grid(
            row=2, column=2, columnspan=2, sticky="ew", pady=4, padx=(0, 4)
        )
        ttk.Button(
            si,
            text="Browse",
            style="Browse.TButton",
            command=lambda: self._pick_file(
                self.var_at3tool,
                [("Executables", "*.exe"), ("All", "*.*")],
                after=self._check_deps,
            ),
        ).grid(row=2, column=4, pady=4, padx=(0, 4))
        ttk.Button(
            si,
            text="Download",
            style="Download.TButton",
            command=self._download_at3tool,
        ).grid(row=2, column=5, pady=4)

        # ffmpeg path row
        self.var_ffmpeg = tk.StringVar()
        ttk.Label(si, text="ffmpeg:", style="Card.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=4, padx=(0, 8)
        )
        ttk.Entry(si, textvariable=self.var_ffmpeg).grid(
            row=3, column=2, columnspan=2, sticky="ew", pady=4, padx=(0, 4)
        )
        ttk.Button(
            si,
            text="Browse",
            style="Browse.TButton",
            command=lambda: self._pick_file(
                self.var_ffmpeg,
                [("Executables", "*.exe"), ("All", "*.*")],
                after=self._check_deps,
            ),
        ).grid(row=3, column=4, pady=4, padx=(0, 4))
        ttk.Button(
            si,
            text="Download",
            style="Download.TButton",
            command=self._download_ffmpeg,
        ).grid(row=3, column=5, pady=4)

        # ── Step 1 — Song Source ───────────────────────────────────
        s1 = ttk.LabelFrame(m, text="  Step 1 — Song Source  ", style="TLabelframe")
        s1.pack(fill="x", **pad)
        s1i = ttk.Frame(s1, style="Card.TFrame")
        s1i.pack(fill="x", padx=12, pady=8)
        s1i.columnconfigure(1, weight=1)

        self.var_tja = tk.StringVar()
        self.var_audio = tk.StringVar()

        # TJA row with ESE browser button
        ttk.Label(s1i, text="TJA Chart:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Entry(s1i, textvariable=self.var_tja).grid(
            row=0, column=1, sticky="ew", pady=4, padx=(0, 4)
        )
        ttk.Button(
            s1i,
            text="Browse",
            style="Browse.TButton",
            command=lambda: self._pick_file(
                self.var_tja,
                [("TJA files", "*.tja"), ("All", "*.*")],
                after=self._on_tja_selected,
            ),
        ).grid(row=0, column=2, pady=4, padx=(0, 4))
        ttk.Button(
            s1i,
            text="Browse ESE…",
            style="Download.TButton",
            command=self._open_ese_browser,
        ).grid(row=0, column=3, pady=4)

        # Audio row
        ttk.Label(s1i, text="Audio File:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Entry(s1i, textvariable=self.var_audio).grid(
            row=1, column=1, sticky="ew", pady=4, padx=(0, 4)
        )
        ttk.Button(
            s1i,
            text="Browse",
            style="Browse.TButton",
            command=lambda: self._pick_file(
                self.var_audio,
                [("Audio", "*.ogg *.mp3 *.wav *.flac"), ("All", "*.*")],
            ),
        ).grid(row=1, column=2, pady=4, padx=(0, 4))
        ttk.Label(
            s1i,
            text="(auto-filled from ESE or TJA WAVE field)",
            style="Sub.TLabel",
        ).grid(row=1, column=3, sticky="w", pady=4)

        # Song info display
        info_wrap = ttk.Frame(s1, style="Card.TFrame")
        info_wrap.pack(fill="x", padx=12, pady=(0, 8))
        self.lbl_song_info = ttk.Label(
            info_wrap,
            text="Select a TJA file or browse ESE to see song info here.",
            style="Info.TLabel",
            wraplength=700,
        )
        self.lbl_song_info.pack(anchor="w", padx=8, pady=6)

        self.var_tja.trace_add("write", lambda *_: self._on_tja_selected())

        # ── Step 2 — DLC Settings ──────────────────────────────────
        s2 = ttk.LabelFrame(m, text="  Step 2 — DLC Settings  ", style="TLabelframe")
        s2.pack(fill="x", **pad)
        s2i = ttk.Frame(s2, style="Card.TFrame")
        s2i.pack(fill="x", padx=12, pady=8)
        s2i.columnconfigure(1, weight=1)

        self.var_template = tk.StringVar()
        self.var_output = tk.StringVar()
        self.var_song_id = tk.StringVar(value="00FF")
        self.var_folder_name = tk.StringVar(value="SONG_DLC_CUSTOM")

        self._path_row(
            s2i, 0, "Template DLC Folder:", self.var_template, directory=True
        )
        self._path_row(s2i, 1, "PSP Game Folder:", self.var_output, directory=True)

        ttk.Label(s2i, text="Song ID (hex):", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=4
        )
        id_frame = ttk.Frame(s2i, style="Card.TFrame")
        id_frame.grid(row=2, column=1, sticky="w", pady=4)
        ttk.Entry(id_frame, textvariable=self.var_song_id, width=8).pack(side="left")
        ttk.Label(
            id_frame,
            text="  hex 0000–FFFF  (use a unique value per song)",
            style="Sub.TLabel",
        ).pack(side="left", padx=(6, 0))

        ttk.Label(s2i, text="Output Folder Name:", style="Card.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Entry(s2i, textvariable=self.var_folder_name).grid(
            row=3, column=1, sticky="ew", pady=4
        )

        self.lbl_template_info = ttk.Label(s2, text="", style="Info.TLabel")
        self.lbl_template_info.pack(anchor="w", padx=16, pady=(0, 8))
        self.var_template.trace_add("write", lambda *_: self._on_template_changed())

        # ── Step 3 — Build ─────────────────────────────────────────
        s3 = ttk.LabelFrame(m, text="  Step 3 — Build  ", style="TLabelframe")
        s3.pack(fill="x", padx=16, pady=(4, 4))
        s3i = ttk.Frame(s3, style="Card.TFrame")
        s3i.pack(fill="x", padx=12, pady=12)

        self.btn_build = ttk.Button(
            s3i, text="BUILD DLC", style="Build.TButton", command=self._do_build
        )
        self.btn_build.pack(fill="x", pady=(0, 8))

        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(
            s3i,
            variable=self.progress_var,
            maximum=1.0,
            mode="determinate",
            style="Horizontal.TProgressbar",
        ).pack(fill="x")

        # ── Build Log ──────────────────────────────────────────────
        ttk.Label(m, text="Build Log", style="Header.TLabel").pack(
            anchor="w", padx=16, pady=(8, 2)
        )
        log_wrap = tk.Frame(m, bg=C.SURFACE, bd=0)
        log_wrap.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.log_text = tk.Text(
            log_wrap,
            bg=C.SURFACE,
            fg=C.TEXT,
            insertbackground=C.TEXT,
            font=("Cascadia Code", 9),
            relief="flat",
            padx=8,
            pady=8,
            height=14,
            wrap="word",
            state="disabled",
        )
        log_scroll = ttk.Scrollbar(log_wrap, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        for tag, color in [("ok", C.GREEN), ("warn", C.YELLOW), ("err", C.RED), ("info", C.BLUE)]:
            self.log_text.tag_configure(tag, foreground=color)

        self._log("Ready. Use Step 1 to pick a song, Step 2 to set DLC options, then Build.", "info")

    # ── path helpers ────────────────────────────────────────────────
    def _path_row(self, parent, row, label, var, filetypes=None, directory=False):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Entry(parent, textvariable=var).grid(
            row=row, column=1, sticky="ew", pady=4, padx=(0, 4)
        )

        def browse():
            path = (
                filedialog.askdirectory(title=label)
                if directory
                else filedialog.askopenfilename(title=label, filetypes=filetypes)
            )
            if path:
                var.set(path)

        ttk.Button(parent, text="Browse", style="Browse.TButton", command=browse).grid(
            row=row, column=2, pady=4
        )

    def _pick_file(self, var, filetypes=None, directory=False, after=None):
        path = (
            filedialog.askdirectory()
            if directory
            else filedialog.askopenfilename(filetypes=filetypes)
        )
        if path:
            var.set(path)
            if after:
                after()

    # ── state ────────────────────────────────────────────────────────
    def _restore_state(self):
        c = self.cfg
        self.var_at3tool.set(c.get("at3tool", ""))
        self.var_ffmpeg.set(c.get("ffmpeg", ""))
        self.var_template.set(c.get("template", ""))
        self.var_output.set(c.get("output", ""))
        self.var_song_id.set(c.get("song_id", "00FF"))
        self.var_folder_name.set(c.get("folder_name", "SONG_DLC_CUSTOM"))

        if not self.var_at3tool.get():
            for candidate in [
                CONFIG_DIR / "tools" / "at3tool" / "at3tool.exe",  # downloaded
                _PROJECT_ROOT / "tools" / "at3tool" / "at3tool.exe",  # dev / manual
            ]:
                if candidate.exists():
                    self.var_at3tool.set(str(candidate))
                    break

    def _save_state(self):
        self.cfg.update(
            {
                "at3tool": self.var_at3tool.get(),
                "ffmpeg": self.var_ffmpeg.get(),
                "template": self.var_template.get(),
                "output": self.var_output.get(),
                "song_id": self.var_song_id.get(),
                "folder_name": self.var_folder_name.get(),
            }
        )
        save_config(self.cfg)

    # ── dep check ───────────────────────────────────────────────────
    def _check_deps(self):
        at3 = self.var_at3tool.get()
        if not at3 or not os.path.isfile(at3):
            for candidate in [
                CONFIG_DIR / "tools" / "at3tool" / "at3tool.exe",
                _PROJECT_ROOT / "tools" / "at3tool" / "at3tool.exe",
            ]:
                if candidate.exists():
                    self.var_at3tool.set(str(candidate))
                    at3 = str(candidate)
                    break

        ffmpeg_path = find_tool("ffmpeg") or self.var_ffmpeg.get() or None
        if ffmpeg_path and not self.var_ffmpeg.get():
            self.var_ffmpeg.set(ffmpeg_path)

        deps = {
            "ffmpeg": ffmpeg_path,
            "tja2fumen": None,
            "at3tool": at3 if (at3 and os.path.isfile(at3)) else None,
        }
        try:
            from tja2fumen import main as _  # noqa: F401

            deps["tja2fumen"] = "installed"
        except ImportError:
            pass

        hints = {
            "ffmpeg": "  NOT FOUND — click Download",
            "tja2fumen": "  NOT FOUND — run: uv add tja2fumen",
            "at3tool": "  NOT FOUND — click Download",
        }
        for tool, path in deps.items():
            lbl = self.dep_labels[tool]
            if path:
                display = "(Python package)" if tool == "tja2fumen" else f"({Path(path).name})"
                lbl.configure(text=f"✓ OK  {display}", foreground=C.GREEN)
            else:
                lbl.configure(text=hints[tool], foreground=C.RED)

    # ── download helpers ────────────────────────────────────────────
    def _download_at3tool(self):
        dlg = _ProgressDialog(self.root, "Downloading at3tool")

        def run():
            from taiko_forge.downloader import download_at3tool

            try:
                dlg.status("Downloading at3tool.zip from PSPunk…")
                exe = download_at3tool(_TOOLS_DIR, dlg.progress)
                self.var_at3tool.set(str(exe))
                self.root.after(0, self._check_deps)
                dlg.done("at3tool ready!")
            except Exception as exc:
                dlg.error(str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _download_ffmpeg(self):
        dlg = _ProgressDialog(self.root, "Downloading ffmpeg")

        def run():
            from taiko_forge.downloader import download_ffmpeg

            try:
                dlg.status("Downloading ffmpeg essentials (~14 MB)…")
                exe = download_ffmpeg(_TOOLS_DIR, dlg.progress)
                self.var_ffmpeg.set(str(exe))
                self.root.after(0, self._check_deps)
                dlg.done("ffmpeg ready!")
            except Exception as exc:
                dlg.error(str(exc))

        threading.Thread(target=run, daemon=True).start()

    # ── ESE browser ─────────────────────────────────────────────────
    def _open_ese_browser(self):
        def on_select(tja_path: str, ogg_path: str):
            self.var_tja.set(tja_path)
            self.var_audio.set(ogg_path)
            self._on_tja_selected()

        _ESEDialog(self.root, on_select)

    # ── TJA callbacks ───────────────────────────────────────────────
    def _on_tja_selected(self):
        path = self.var_tja.get()
        if not path or not os.path.isfile(path):
            return
        try:
            info = parse_tja(path)
            courses = (
                ", ".join(f"{k}({v})" for k, v in info["courses"].items()) or "None"
            )
            self.lbl_song_info.configure(
                text=(
                    f"Title: {info['title']}   |   Artist: {info['subtitle']}\n"
                    f"BPM: {info['bpm']}   |   Demo Start: {info['demostart']}s\n"
                    f"Difficulties: {courses}"
                )
            )
            if info["wave"] and not self.var_audio.get():
                wave_path = Path(path).parent / info["wave"]
                if wave_path.exists():
                    self.var_audio.set(str(wave_path))
            if info["title"]:
                safe = re.sub(r"[^\w\s-]", "", info["title"]).strip().replace(" ", "_")
                self.var_folder_name.set(f"SONG_DLC_{safe.upper()[:20]}")
        except Exception as exc:
            self.lbl_song_info.configure(text=f"Error parsing TJA: {exc}")

    def _on_template_changed(self):
        path = self.var_template.get()
        if not path or not os.path.isdir(path):
            self.lbl_template_info.configure(text="")
            return
        files = os.listdir(path)
        edats = [f for f in files if f.upper().endswith(".EDAT")]
        fumen_count = sum(1 for f in edats if "FUMEN" in f.upper())
        preview = ", ".join(sorted(edats)[:8])
        if len(edats) > 8:
            preview += "…"
        self.lbl_template_info.configure(
            text=f"{len(edats)} EDAT files ({fumen_count} fumen): {preview}"
        )

    # ── log ──────────────────────────────────────────────────────────
    def _log(self, msg, tag=None):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n", tag or "")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log_ts(self, msg, tag=None):
        self.root.after(0, self._log, msg, tag)

    def _progress_ts(self, val):
        self.root.after(0, lambda: self.progress_var.set(val))

    # ── build ────────────────────────────────────────────────────────
    def _validate(self) -> bool:
        errors = []
        if not self.var_tja.get() or not os.path.isfile(self.var_tja.get()):
            errors.append("TJA chart file not found")
        if not self.var_audio.get() or not os.path.isfile(self.var_audio.get()):
            errors.append("Audio file not found")
        if not self.var_template.get() or not os.path.isdir(self.var_template.get()):
            errors.append("Template DLC folder not found")
        if not self.var_output.get() or not os.path.isdir(self.var_output.get()):
            errors.append("PSP game folder not found")
        at3 = self.var_at3tool.get()
        if not at3 or not os.path.isfile(at3):
            errors.append("at3tool.exe not found — use Download button in Setup")
        ffmpeg = self.var_ffmpeg.get() or "ffmpeg"
        try:
            subprocess.run([ffmpeg, "-version"], capture_output=True, timeout=5)
        except Exception:
            errors.append("ffmpeg not found — use Download button in Setup")
        try:
            from tja2fumen import main as _  # noqa: F401
        except ImportError:
            errors.append("tja2fumen not installed (run: uv add tja2fumen)")
        try:
            sid = int(self.var_song_id.get(), 16)
            if not 0 <= sid <= 0xFFFF:
                raise ValueError
        except ValueError:
            errors.append("Song ID must be hex 0000–FFFF")

        if errors:
            messagebox.showerror("Cannot Build", "\n".join(f"• {e}" for e in errors))
            return False
        return True

    def _do_build(self):
        if self.building or not self._validate():
            return
        self._save_state()
        self.building = True
        self.btn_build.configure(state="disabled")
        self.progress_var.set(0)
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        output_dir = Path(self.var_output.get()) / self.var_folder_name.get()
        builder = DLCBuilder(
            template_dir=self.var_template.get(),
            output_dir=str(output_dir),
            tja_path=self.var_tja.get(),
            audio_path=self.var_audio.get(),
            song_id=int(self.var_song_id.get(), 16),
            at3tool_path=self.var_at3tool.get(),
            ffmpeg_path=self.var_ffmpeg.get() or "ffmpeg",
            log_fn=self._log_ts,
            progress_fn=self._progress_ts,
        )

        def run():
            try:
                builder.build()
                self._log_ts("")
                self._log_ts("Done! Your custom DLC is ready.", "ok")
            except Exception as exc:
                self._log_ts(f"\nERROR: {exc}", "err")
                self._log_ts("Build failed. Check the log above.", "err")
            finally:
                self.root.after(0, self._build_done)

        threading.Thread(target=run, daemon=True).start()

    def _build_done(self):
        self.building = False
        self.btn_build.configure(state="normal")


def main():
    root = tk.Tk()
    try:
        root.iconbitmap(default="")
    except Exception:
        pass
    App(root)
    root.mainloop()
