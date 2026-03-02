"""Taiko Forge GUI application — customtkinter edition."""

import os
import re
import subprocess
import sys
import threading
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from taiko_forge.builder import DLCBuilder
from taiko_forge.config import CONFIG_DIR, find_tool, load_config, save_config
from taiko_forge.tja import parse_tja

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

if getattr(sys, "frozen", False):
    _TOOLS_DIR = CONFIG_DIR / "tools"
else:
    _TOOLS_DIR = _PROJECT_ROOT / "tools"

_BUNDLED_TEMPLATE_ZIP = "SONG_DLC_123.zip"


def _find_bundled_template_zip() -> str:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / _BUNDLED_TEMPLATE_ZIP)
        candidates.append(Path(sys.executable).resolve().parent / _BUNDLED_TEMPLATE_ZIP)
    candidates.append(_PROJECT_ROOT / _BUNDLED_TEMPLATE_ZIP)

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


# ── Catppuccin Mocha ────────────────────────────────────────────────
class C:
    CRUST = "#11111b"
    MANTLE = "#181825"
    BASE = "#1e1e2e"
    SURFACE0 = "#313244"
    SURFACE1 = "#45475a"
    SURFACE2 = "#585b70"
    OVERLAY0 = "#6c7086"
    OVERLAY1 = "#7f849c"
    SUBTEXT0 = "#a6adc8"
    SUBTEXT1 = "#bac2de"
    TEXT = "#cdd6f4"
    LAVENDER = "#b4befe"
    BLUE = "#89b4fa"
    SAPPHIRE = "#74c7ec"
    SKY = "#89dceb"
    TEAL = "#94e2d5"
    GREEN = "#a6e3a1"
    YELLOW = "#f9e2af"
    PEACH = "#fab387"
    MAROON = "#eba0ac"
    RED = "#f38ba8"
    MAUVE = "#cba6f7"
    PINK = "#f5c2e7"
    FLAMINGO = "#f2cdcd"
    ROSEWATER = "#f5e0dc"


# ── Apply Catppuccin theme on customtkinter ─────────────────────────
def _apply_catppuccin():
    """Configure customtkinter to use Catppuccin Mocha colors."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


# ── Progress Dialog ─────────────────────────────────────────────────
class ProgressDialog(ctk.CTkToplevel):
    """Modal dialog showing download progress."""

    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title(title)
        self.geometry("440x160")
        self.resizable(False, False)
        self.configure(fg_color=C.BASE)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        self.after(10, self.focus_force)

        self._status_var = ctk.StringVar(value="Connecting…")
        self._prog_var = ctk.DoubleVar(value=0.0)

        ctk.CTkLabel(
            self,
            textvariable=self._status_var,
            font=ctk.CTkFont(size=13),
            text_color=C.TEXT,
        ).pack(padx=20, pady=(24, 8))

        self._bar = ctk.CTkProgressBar(
            self,
            variable=self._prog_var,
            width=400,
            height=14,
            progress_color=C.GREEN,
            fg_color=C.SURFACE0,
            corner_radius=7,
        )
        self._bar.pack(padx=20, pady=(0, 12))

        self._btn = ctk.CTkButton(
            self,
            text="Close",
            state="disabled",
            command=self.destroy,
            fg_color=C.SURFACE1,
            hover_color=C.SURFACE2,
            text_color=C.TEXT,
            corner_radius=8,
            width=100,
            height=32,
        )
        self._btn.pack(pady=(0, 16))

    def status(self, text: str):
        self.after(0, self._status_var.set, text)

    def progress(self, frac: float):
        self.after(0, self._prog_var.set, frac)

    def done(self, msg: str = "Done!"):
        self.after(0, self._finish, msg)

    def error(self, msg: str):
        self.after(0, self._finish, f"Error: {msg}")

    def _finish(self, msg: str):
        self._status_var.set(msg)
        self._prog_var.set(1.0)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._btn.configure(state="normal")


# ── ESE Browser Dialog ──────────────────────────────────────────────
class ESEDialog(ctk.CTkToplevel):
    """Browse and download songs from the ESE database."""

    def __init__(self, parent, on_select):
        super().__init__(parent)
        from taiko_forge.ese_browser import GENRES

        self.on_select = on_select
        self.songs: list[dict] = []
        self.filtered: list[dict] = []
        self._genres = GENRES
        self._genre_cache: dict[str, list[dict]] = {}

        self.title("ESE Song Browser")
        self.geometry("820x660")
        self.minsize(640, 520)
        self.configure(fg_color=C.BASE)
        self.transient(parent)
        self.grab_set()
        self.after(10, self.focus_force)

        self._build_ui()
        self._load_genre(self._genres[0])

    def _build_ui(self):
        # ── Top bar ──
        top = ctk.CTkFrame(self, fg_color=C.MANTLE, corner_radius=12)
        top.pack(fill="x", padx=16, pady=(16, 8))

        row1 = ctk.CTkFrame(top, fg_color="transparent")
        row1.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            row1,
            text="Genre",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C.SUBTEXT0,
        ).pack(side="left", padx=(0, 8))
        self._genre_var = ctk.StringVar(value=self._genres[0])
        genre_menu = ctk.CTkOptionMenu(
            row1,
            variable=self._genre_var,
            values=self._genres,
            command=self._load_genre,
            fg_color=C.SURFACE0,
            button_color=C.SURFACE1,
            button_hover_color=C.SURFACE2,
            text_color=C.TEXT,
            dropdown_fg_color=C.SURFACE0,
            dropdown_hover_color=C.SURFACE1,
            dropdown_text_color=C.TEXT,
            width=220,
            height=32,
            corner_radius=8,
        )
        genre_menu.pack(side="left")

        ctk.CTkLabel(
            row1,
            text="Search",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C.SUBTEXT0,
        ).pack(side="left", padx=(20, 8))
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        ctk.CTkEntry(
            row1,
            textvariable=self._search_var,
            fg_color=C.SURFACE0,
            border_color=C.SURFACE1,
            text_color=C.TEXT,
            placeholder_text="Filter songs…",
            placeholder_text_color=C.OVERLAY0,
            height=32,
            corner_radius=8,
        ).pack(side="left", fill="x", expand=True, padx=(0, 0))

        # ── Count label ──
        self._count_var = ctk.StringVar(value="Loading…")
        ctk.CTkLabel(
            top,
            textvariable=self._count_var,
            font=ctk.CTkFont(size=11),
            text_color=C.SUBTEXT0,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        # ── Song list ──
        self._list_frame_outer = ctk.CTkFrame(self, fg_color=C.MANTLE, corner_radius=12)
        self._list_frame_outer.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        self._listbox = tk.Listbox(
            self._list_frame_outer,
            bg=C.MANTLE,
            fg=C.TEXT,
            selectbackground=C.BLUE,
            selectforeground=C.CRUST,
            font=("Segoe UI", 13),
            activestyle="none",
            relief="flat",
            bd=0,
            highlightthickness=0,
            selectmode="extended",
        )
        sb = ctk.CTkScrollbar(
            self._list_frame_outer,
            command=self._listbox.yview,
            fg_color=C.MANTLE,
            button_color=C.SURFACE1,
            button_hover_color=C.SURFACE2,
        )
        self._listbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=6)
        self._listbox.pack(fill="both", expand=True, padx=6, pady=6)
        self._listbox.bind("<<ListboxSelect>>", self._on_lb_select)
        self._listbox.bind("<Double-Button-1>", lambda _: self._download_and_use())

        # ── Info + progress ──
        info_frame = ctk.CTkFrame(self, fg_color=C.MANTLE, corner_radius=12)
        info_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._info_var = ctk.StringVar(
            value="Select one or more songs, then click Download & Use."
        )
        ctk.CTkLabel(
            info_frame,
            textvariable=self._info_var,
            font=ctk.CTkFont(size=12),
            text_color=C.BLUE,
            wraplength=580,
            justify="left",
        ).pack(padx=14, pady=(10, 4), anchor="w")

        self._dl_prog = ctk.DoubleVar(value=0.0)
        self._dl_bar = ctk.CTkProgressBar(
            info_frame,
            variable=self._dl_prog,
            width=580,
            height=8,
            progress_color=C.GREEN,
            fg_color=C.SURFACE0,
            corner_radius=4,
        )
        self._dl_bar.pack(padx=14, pady=(0, 2))
        self._dl_status = ctk.StringVar(value="")
        ctk.CTkLabel(
            info_frame,
            textvariable=self._dl_status,
            font=ctk.CTkFont(size=11),
            text_color=C.SUBTEXT0,
        ).pack(padx=14, anchor="w", pady=(0, 10))

        # ── Buttons ──
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(0, 16))

        self._btn_dl = ctk.CTkButton(
            btn_frame,
            text="⬇  Download & Use",
            command=self._download_and_use,
            state="disabled",
            fg_color=C.BLUE,
            hover_color=C.LAVENDER,
            text_color=C.CRUST,
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=10,
            height=38,
        )
        self._btn_dl.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self._btn_bulk = ctk.CTkButton(
            btn_frame,
            text="⬇  Bulk Download All",
            command=self._bulk_download,
            state="disabled",
            fg_color=C.TEAL,
            hover_color=C.GREEN,
            text_color=C.CRUST,
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=10,
            height=38,
        )
        self._btn_bulk.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="Select All",
            command=self._select_all,
            fg_color=C.SURFACE1,
            hover_color=C.SURFACE2,
            text_color=C.TEXT,
            corner_radius=10,
            height=38,
            width=90,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            command=self.destroy,
            fg_color=C.SURFACE1,
            hover_color=C.SURFACE2,
            text_color=C.TEXT,
            corner_radius=10,
            height=38,
            width=80,
        ).pack(side="right")

    def _load_genre(self, genre: str):
        self.songs = []
        self.filtered = []
        self._listbox.delete(0, "end")
        self._btn_dl.configure(state="disabled")
        self._btn_bulk.configure(state="disabled")
        self._search_var.set("")

        # Use cached data if available
        if genre in self._genre_cache:
            self._count_var.set("Loading (cached)…")
            self.after(10, self._set_songs, self._genre_cache[genre])
            return

        self._count_var.set("Loading…")

        def fetch():
            from taiko_forge.ese_browser import list_songs

            try:
                songs = list_songs(genre)
                self._genre_cache[genre] = songs
                self.after(0, self._set_songs, songs)
            except Exception as exc:
                self.after(0, self._count_var.set, f"Error: {exc}")

        threading.Thread(target=fetch, daemon=True).start()

    def _set_songs(self, songs: list):
        self.songs = songs
        self._filter()

    def _filter(self):
        q = self._search_var.get().lower()
        self.filtered = [s for s in self.songs if q in s["name"].lower()]
        self._listbox.delete(0, "end")
        for s in self.filtered:
            self._listbox.insert("end", "  " + s["name"])
        self._count_var.set(f"{len(self.filtered)} songs")
        if self.filtered:
            self._btn_bulk.configure(state="normal")
        else:
            self._btn_bulk.configure(state="disabled")

    def _select_all(self):
        self._listbox.select_set(0, "end")
        self._on_lb_select()

    def _on_lb_select(self, _evt=None):
        sel = self._listbox.curselection()
        if not sel:
            self._btn_dl.configure(state="disabled")
            return
        count = len(sel)
        if count == 1:
            song = self.filtered[sel[0]]
            self._info_var.set(f"Selected: {song['name']}")
        else:
            self._info_var.set(f"{count} songs selected")
        self._btn_dl.configure(state="normal")

    def _download_and_use(self):
        sel = self._listbox.curselection()
        if not sel:
            return
        songs = [self.filtered[i] for i in sel]
        if len(songs) == 1:
            self._download_single(songs[0])
        else:
            self._download_multiple(songs, use_after=True)

    def _download_single(self, song: dict):
        dest_dir = CONFIG_DIR / "songs" / song["name"]
        tja_path = dest_dir / f"{song['name']}.tja"
        ogg_path = dest_dir / f"{song['name']}.ogg"

        if tja_path.exists() and ogg_path.exists():
            self.on_select(str(tja_path), str(ogg_path))
            self.destroy()
            return

        self._btn_dl.configure(state="disabled")
        self._btn_bulk.configure(state="disabled")
        self._dl_status.set("Downloading chart…")
        self._dl_prog.set(0.05)

        def run():
            from taiko_forge.ese_browser import download_audio, download_tja

            try:
                download_tja(song, dest_dir)
                self.after(0, self._dl_status.set, "Downloading audio…")
                self.after(0, self._dl_prog.set, 0.25)

                def _audio_prog(f):
                    self.after(0, self._dl_prog.set, 0.25 + f * 0.75)

                download_audio(song, dest_dir, _audio_prog)
                self.after(0, self._on_dl_done, str(tja_path), str(ogg_path))
            except Exception as exc:
                self.after(0, self._on_dl_error, str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _download_multiple(self, songs: list[dict], *, use_after: bool = False):
        """Download multiple songs sequentially with progress."""
        self._btn_dl.configure(state="disabled")
        self._btn_bulk.configure(state="disabled")
        total = len(songs)

        def run():
            from taiko_forge.ese_browser import download_audio, download_tja

            last_tja = None
            last_ogg = None
            for i, song in enumerate(songs):
                dest_dir = CONFIG_DIR / "songs" / song["name"]
                tja_path = dest_dir / f"{song['name']}.tja"
                ogg_path = dest_dir / f"{song['name']}.ogg"

                base_frac = i / total
                self.after(
                    0,
                    self._dl_status.set,
                    f"[{i + 1}/{total}] Downloading {song['name']}…",
                )
                self.after(0, self._dl_prog.set, base_frac)

                if tja_path.exists() and ogg_path.exists():
                    last_tja, last_ogg = str(tja_path), str(ogg_path)
                    continue

                try:
                    download_tja(song, dest_dir)
                    self.after(0, self._dl_prog.set, base_frac + 0.3 / total)

                    def _audio_prog(f, _base=base_frac):
                        self.after(
                            0, self._dl_prog.set, _base + (0.3 + f * 0.7) / total
                        )

                    download_audio(song, dest_dir, _audio_prog)
                    last_tja, last_ogg = str(tja_path), str(ogg_path)
                except Exception as exc:
                    self.after(
                        0,
                        self._dl_status.set,
                        f"Error on {song['name']}: {exc}",
                    )

            if use_after and last_tja and last_ogg:
                self.after(0, self._on_dl_done, last_tja, last_ogg)
            else:
                self.after(0, self._on_bulk_done, total)

        threading.Thread(target=run, daemon=True).start()

    def _bulk_download(self):
        """Download all currently filtered songs."""
        if not self.filtered:
            return
        self._download_multiple(self.filtered)

    def _on_dl_done(self, tja: str, ogg: str):
        self._dl_status.set("Done!")
        self._dl_prog.set(1.0)
        self.on_select(tja, ogg)
        self.destroy()

    def _on_bulk_done(self, count: int):
        self._dl_status.set(f"Downloaded {count} songs to cache!")
        self._dl_prog.set(1.0)
        self._btn_dl.configure(state="normal")
        self._btn_bulk.configure(state="normal")

    def _on_dl_error(self, msg: str):
        self._dl_status.set(f"Error: {msg}")
        self._btn_dl.configure(state="normal")
        self._btn_bulk.configure(state="normal")


# ── Helper: create a labeled row ────────────────────────────────────
def _labeled_entry(parent, label, var, row, *, browse_cmd=None, extra_btn=None):
    """Add a row: label + entry + optional browse + optional extra button."""
    ctk.CTkLabel(
        parent,
        text=label,
        font=ctk.CTkFont(size=12),
        text_color=C.SUBTEXT1,
    ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6)

    entry = ctk.CTkEntry(
        parent,
        textvariable=var,
        fg_color=C.SURFACE0,
        border_color=C.SURFACE1,
        text_color=C.TEXT,
        corner_radius=8,
        height=34,
    )
    entry.grid(row=row, column=1, sticky="ew", pady=6, padx=(0, 6))

    col = 2
    if browse_cmd:
        ctk.CTkButton(
            parent,
            text="Browse",
            command=browse_cmd,
            fg_color=C.SURFACE1,
            hover_color=C.SURFACE2,
            text_color=C.TEXT,
            corner_radius=8,
            width=80,
            height=32,
            font=ctk.CTkFont(size=12),
        ).grid(row=row, column=col, pady=6, padx=(0, 4))
        col += 1
    if extra_btn:
        lbl, cmd, color = extra_btn
        ctk.CTkButton(
            parent,
            text=lbl,
            command=cmd,
            fg_color=color,
            hover_color=C.SURFACE2,
            text_color=C.CRUST if color != C.SURFACE1 else C.TEXT,
            corner_radius=8,
            width=110,
            height=32,
            font=ctk.CTkFont(size=12),
        ).grid(row=row, column=col, pady=6)
    return entry


# ── Card frame helper ───────────────────────────────────────────────
def _card(parent, title: str, icon: str = "") -> ctk.CTkFrame:
    """Create a Catppuccin 'card' frame with a section header."""
    wrapper = ctk.CTkFrame(parent, fg_color="transparent")
    wrapper.pack(fill="x", padx=0, pady=(0, 4))

    header = ctk.CTkFrame(wrapper, fg_color="transparent")
    header.pack(fill="x", padx=4, pady=(0, 4))
    ctk.CTkLabel(
        header,
        text=f"{icon}  {title}" if icon else title,
        font=ctk.CTkFont(size=14, weight="bold"),
        text_color=C.PEACH,
    ).pack(side="left")

    card = ctk.CTkFrame(wrapper, fg_color=C.MANTLE, corner_radius=14)
    card.pack(fill="x")
    inner = ctk.CTkFrame(card, fg_color="transparent")
    inner.pack(fill="x", padx=16, pady=14)
    inner.columnconfigure(1, weight=1)
    return inner


# ======================================================================
# Main application
# ======================================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        _apply_catppuccin()

        self.title("Taiko Forge")
        self.geometry("860x1080")
        self.minsize(700, 900)
        self.configure(fg_color=C.BASE)

        self.cfg = load_config()
        self.building = False

        self._build_ui()
        self._restore_state()
        self._check_deps()
        # Scan for installed DLC after loading state
        self.after(500, self._scan_installed_dlc)

    # ── UI Construction ─────────────────────────────────────────────
    def _build_ui(self):
        # ── Main scrollable area ──
        container = ctk.CTkScrollableFrame(
            self,
            fg_color=C.BASE,
            scrollbar_button_color=C.SURFACE1,
            scrollbar_button_hover_color=C.SURFACE2,
        )
        container.pack(fill="both", expand=True, padx=0, pady=0)

        content = ctk.CTkFrame(container, fg_color="transparent")
        content.pack(fill="x", padx=24, pady=16)

        # ── Header ──
        hdr = ctk.CTkFrame(content, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 4))

        title_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        title_frame.pack(side="left")
        ctk.CTkLabel(
            title_frame,
            text="\U0001f941  Taiko Forge",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=C.TEXT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_frame,
            text="Custom DLC builder for Taiko no Tatsujin Portable DX (PSP)",
            font=ctk.CTkFont(size=13),
            text_color=C.SUBTEXT0,
        ).pack(anchor="w", pady=(2, 0))

        # Version pill
        pill = ctk.CTkFrame(hdr, fg_color=C.SURFACE0, corner_radius=12)
        pill.pack(side="right", anchor="ne", pady=6)
        ctk.CTkLabel(
            pill,
            text=" v2.0.1 ",
            font=ctk.CTkFont(size=11),
            text_color=C.OVERLAY1,
        ).pack(padx=8, pady=2)

        # ── Separator ──
        ctk.CTkFrame(content, fg_color=C.SURFACE1, height=1, corner_radius=0).pack(
            fill="x", pady=(12, 16)
        )

        # ── Dependency Status Bar ──
        dep_card = ctk.CTkFrame(content, fg_color=C.MANTLE, corner_radius=14)
        dep_card.pack(fill="x", pady=(0, 16))
        dep_inner = ctk.CTkFrame(dep_card, fg_color="transparent")
        dep_inner.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(
            dep_inner,
            text="Dependencies",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=C.PEACH,
        ).pack(anchor="w", pady=(0, 8))

        dep_row = ctk.CTkFrame(dep_inner, fg_color="transparent")
        dep_row.pack(fill="x")

        self.dep_pills: dict[str, ctk.CTkLabel] = {}
        for tool in ["ffmpeg", "tja2fumen", "at3tool"]:
            pill_frame = ctk.CTkFrame(dep_row, fg_color=C.SURFACE0, corner_radius=10)
            pill_frame.pack(side="left", padx=(0, 8))
            name_lbl = ctk.CTkLabel(
                pill_frame,
                text=f"  {tool}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=C.TEXT,
            )
            name_lbl.pack(side="left", padx=(8, 2), pady=5)
            status_lbl = ctk.CTkLabel(
                pill_frame,
                text="checking\u2026  ",
                font=ctk.CTkFont(size=11),
                text_color=C.OVERLAY0,
            )
            status_lbl.pack(side="left", padx=(0, 8), pady=5)
            self.dep_pills[tool] = status_lbl

        # ── Setup Section ──
        setup = _card(content, "Setup", "\u2699")

        self.var_at3tool = ctk.StringVar()
        self.var_ffmpeg = ctk.StringVar()

        _labeled_entry(
            setup,
            "at3tool.exe",
            self.var_at3tool,
            0,
            browse_cmd=lambda: self._pick_file(
                self.var_at3tool,
                [("Executables", "*.exe"), ("All", "*.*")],
                after=self._check_deps,
            ),
            extra_btn=("\u2b07 Download", self._download_at3tool, C.TEAL),
        )
        _labeled_entry(
            setup,
            "ffmpeg",
            self.var_ffmpeg,
            1,
            browse_cmd=lambda: self._pick_file(
                self.var_ffmpeg,
                [("Executables", "*.exe"), ("All", "*.*")],
                after=self._check_deps,
            ),
            extra_btn=("\u2b07 Download", self._download_ffmpeg, C.TEAL),
        )

        # ── Step 1 — Song Source ──
        s1 = _card(content, "Step 1 \u2014 Song Source", "\U0001f3b5")

        self.var_tja = ctk.StringVar()
        self.var_audio = ctk.StringVar()

        # TJA row
        ctk.CTkLabel(
            s1,
            text="TJA Chart",
            font=ctk.CTkFont(size=12),
            text_color=C.SUBTEXT1,
        ).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
        ctk.CTkEntry(
            s1,
            textvariable=self.var_tja,
            fg_color=C.SURFACE0,
            border_color=C.SURFACE1,
            text_color=C.TEXT,
            corner_radius=8,
            height=34,
        ).grid(row=0, column=1, sticky="ew", pady=6, padx=(0, 6))
        ctk.CTkButton(
            s1,
            text="Browse",
            command=lambda: self._pick_file(
                self.var_tja,
                [("TJA files", "*.tja"), ("All", "*.*")],
                after=self._on_tja_selected,
            ),
            fg_color=C.SURFACE1,
            hover_color=C.SURFACE2,
            text_color=C.TEXT,
            corner_radius=8,
            width=80,
            height=32,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=2, pady=6, padx=(0, 4))
        ctk.CTkButton(
            s1,
            text="Browse ESE\u2026",
            command=self._open_ese_browser,
            fg_color=C.MAUVE,
            hover_color=C.LAVENDER,
            text_color=C.CRUST,
            corner_radius=8,
            width=110,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=3, pady=6)

        # Audio row
        _labeled_entry(
            s1,
            "Audio File",
            self.var_audio,
            1,
            browse_cmd=lambda: self._pick_file(
                self.var_audio,
                [("Audio", "*.ogg *.mp3 *.wav *.flac"), ("All", "*.*")],
            ),
        )
        ctk.CTkLabel(
            s1,
            text="Auto-filled from ESE or TJA WAVE field",
            font=ctk.CTkFont(size=11),
            text_color=C.OVERLAY0,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 2))

        # Song info display
        self.song_info_frame = ctk.CTkFrame(
            s1.master,
            fg_color=C.SURFACE0,
            corner_radius=10,
        )
        self.song_info_frame.pack(fill="x", padx=16, pady=(0, 14))
        self.lbl_song_info = ctk.CTkLabel(
            self.song_info_frame,
            text="Select a TJA file or browse ESE to see song info here.",
            font=ctk.CTkFont(size=12),
            text_color=C.BLUE,
            wraplength=700,
            justify="left",
        )
        self.lbl_song_info.pack(padx=14, pady=10, anchor="w")

        self.var_tja.trace_add("write", lambda *_: self._on_tja_selected())

        # ── Step 2 — DLC Settings ──
        s2 = _card(content, "Step 2 \u2014 DLC Settings", "\U0001f4e6")

        self.var_template = ctk.StringVar()
        self.var_output = ctk.StringVar()
        self.var_song_id = ctk.StringVar(value="00FF")
        self.var_folder_name = ctk.StringVar(value="SONG_DLC_CUSTOM")

        _labeled_entry(
            s2,
            "Template DLC (Folder or ZIP)",
            self.var_template,
            0,
            browse_cmd=lambda: self._pick_file(self.var_template, directory=True),
        )
        _labeled_entry(
            s2,
            "PSP Game Folder",
            self.var_output,
            1,
            browse_cmd=lambda: self._pick_file(
                self.var_output, directory=True, after=self._scan_installed_dlc
            ),
        )

        # Song ID
        ctk.CTkLabel(
            s2,
            text="Song ID (hex)",
            font=ctk.CTkFont(size=12),
            text_color=C.SUBTEXT1,
        ).grid(row=2, column=0, sticky="w", padx=(0, 10), pady=6)
        id_frame = ctk.CTkFrame(s2, fg_color="transparent")
        id_frame.grid(row=2, column=1, columnspan=3, sticky="w", pady=6)
        ctk.CTkEntry(
            id_frame,
            textvariable=self.var_song_id,
            fg_color=C.SURFACE0,
            border_color=C.SURFACE1,
            text_color=C.TEXT,
            corner_radius=8,
            width=90,
            height=34,
        ).pack(side="left")
        ctk.CTkLabel(
            id_frame,
            text="hex 0000\u2013FFFF \u00b7 use a unique value per song",
            font=ctk.CTkFont(size=11),
            text_color=C.OVERLAY0,
        ).pack(side="left", padx=(10, 0))

        # Folder name
        _labeled_entry(s2, "Output Folder Name", self.var_folder_name, 3)

        # Template info
        self.lbl_template_info = ctk.CTkLabel(
            s2.master,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=C.BLUE,
            wraplength=700,
            justify="left",
        )
        self.lbl_template_info.pack(padx=16, anchor="w", pady=(0, 14))
        self.var_template.trace_add("write", lambda *_: self._on_template_changed())

        # ── Installed DLC Section ──
        installed_wrapper = ctk.CTkFrame(content, fg_color="transparent")
        installed_wrapper.pack(fill="x", pady=(0, 4))

        hdr_frame = ctk.CTkFrame(installed_wrapper, fg_color="transparent")
        hdr_frame.pack(fill="x", padx=4, pady=(0, 4))
        ctk.CTkLabel(
            hdr_frame,
            text="\U0001f4c2  Installed DLC",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=C.PEACH,
        ).pack(side="left")
        ctk.CTkButton(
            hdr_frame,
            text="\u21bb Scan",
            command=self._scan_installed_dlc,
            fg_color=C.SURFACE1,
            hover_color=C.SURFACE2,
            text_color=C.TEXT,
            corner_radius=8,
            width=70,
            height=28,
            font=ctk.CTkFont(size=11),
        ).pack(side="right")

        installed_card = ctk.CTkFrame(
            installed_wrapper, fg_color=C.MANTLE, corner_radius=14
        )
        installed_card.pack(fill="x")

        self.installed_list = tk.Listbox(
            installed_card,
            bg=C.MANTLE,
            fg=C.TEXT,
            font=("Segoe UI", 12),
            activestyle="none",
            relief="flat",
            bd=0,
            highlightthickness=0,
            selectmode="single",
            height=5,
        )
        inst_sb = ctk.CTkScrollbar(
            installed_card,
            command=self.installed_list.yview,
            fg_color=C.MANTLE,
            button_color=C.SURFACE1,
            button_hover_color=C.SURFACE2,
        )
        self.installed_list.configure(yscrollcommand=inst_sb.set)
        inst_sb.pack(side="right", fill="y", padx=(0, 4), pady=6)
        self.installed_list.pack(fill="both", expand=True, padx=6, pady=6)

        self.installed_info = ctk.CTkLabel(
            installed_card,
            text="Set a PSP Game Folder to scan for installed DLC.",
            font=ctk.CTkFont(size=11),
            text_color=C.OVERLAY0,
        )
        self.installed_info.pack(padx=14, pady=(0, 10), anchor="w")

        # ── Batch Build Section ──
        batch_wrapper = ctk.CTkFrame(content, fg_color="transparent")
        batch_wrapper.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            batch_wrapper,
            text="\U0001f4e5  Batch Build from Cache",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=C.PEACH,
        ).pack(anchor="w", padx=4, pady=(0, 4))

        batch_card = ctk.CTkFrame(
            batch_wrapper, fg_color=C.MANTLE, corner_radius=14
        )
        batch_card.pack(fill="x")
        batch_inner = ctk.CTkFrame(batch_card, fg_color="transparent")
        batch_inner.pack(fill="x", padx=16, pady=14)

        batch_desc = ctk.CTkLabel(
            batch_inner,
            text="Build DLC for all downloaded songs in cache. Each song gets an auto-assigned Song ID.",
            font=ctk.CTkFont(size=12),
            text_color=C.SUBTEXT0,
            wraplength=700,
            justify="left",
        )
        batch_desc.pack(anchor="w", pady=(0, 8))

        batch_btn_frame = ctk.CTkFrame(batch_inner, fg_color="transparent")
        batch_btn_frame.pack(fill="x")

        self.btn_batch_build = ctk.CTkButton(
            batch_btn_frame,
            text="\u26a1 Batch Build All Cached Songs",
            command=self._do_batch_build,
            fg_color=C.MAUVE,
            hover_color=C.LAVENDER,
            text_color=C.CRUST,
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=10,
            height=38,
        )
        self.btn_batch_build.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.batch_status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            batch_inner,
            textvariable=self.batch_status_var,
            font=ctk.CTkFont(size=11),
            text_color=C.SUBTEXT0,
        ).pack(anchor="w", pady=(6, 0))

        self.batch_prog_var = ctk.DoubleVar(value=0.0)
        self.batch_prog_bar = ctk.CTkProgressBar(
            batch_inner,
            variable=self.batch_prog_var,
            height=8,
            progress_color=C.TEAL,
            fg_color=C.SURFACE0,
            corner_radius=4,
        )
        self.batch_prog_bar.pack(fill="x", pady=(4, 0))

        # ── Step 3 — Build ──
        build_wrapper = ctk.CTkFrame(content, fg_color="transparent")
        build_wrapper.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            build_wrapper,
            text="\U0001f528  Step 3 \u2014 Build",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=C.PEACH,
        ).pack(anchor="w", padx=4, pady=(0, 4))

        build_card = ctk.CTkFrame(build_wrapper, fg_color=C.MANTLE, corner_radius=14)
        build_card.pack(fill="x")
        build_inner = ctk.CTkFrame(build_card, fg_color="transparent")
        build_inner.pack(fill="x", padx=16, pady=16)

        self.btn_build = ctk.CTkButton(
            build_inner,
            text="BUILD  DLC",
            command=self._do_build,
            fg_color=C.BLUE,
            hover_color=C.LAVENDER,
            text_color=C.CRUST,
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            corner_radius=12,
            height=50,
        )
        self.btn_build.pack(fill="x", pady=(0, 12))

        self.progress_var = ctk.DoubleVar(value=0.0)
        self.progress_bar = ctk.CTkProgressBar(
            build_inner,
            variable=self.progress_var,
            height=10,
            progress_color=C.GREEN,
            fg_color=C.SURFACE0,
            corner_radius=5,
        )
        self.progress_bar.pack(fill="x")

        # ── Build Log ──
        log_wrapper = ctk.CTkFrame(content, fg_color="transparent")
        log_wrapper.pack(fill="x", pady=(12, 4))
        ctk.CTkLabel(
            log_wrapper,
            text="\U0001f4cb  Build Log",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=C.PEACH,
        ).pack(anchor="w", padx=4, pady=(0, 4))

        log_card = ctk.CTkFrame(log_wrapper, fg_color=C.MANTLE, corner_radius=14)
        log_card.pack(fill="x")

        self.log_text = tk.Text(
            log_card,
            bg=C.MANTLE,
            fg=C.TEXT,
            insertbackground=C.TEXT,
            font=("Cascadia Code", 10),
            relief="flat",
            padx=14,
            pady=12,
            height=14,
            wrap="word",
            state="disabled",
            highlightthickness=0,
            bd=0,
        )
        log_sb = ctk.CTkScrollbar(
            log_card,
            command=self.log_text.yview,
            fg_color=C.MANTLE,
            button_color=C.SURFACE1,
            button_hover_color=C.SURFACE2,
        )
        self.log_text.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y", padx=(0, 6), pady=8)
        self.log_text.pack(fill="both", expand=True, padx=(6, 0), pady=6)

        for tag, color in [
            ("ok", C.GREEN),
            ("warn", C.YELLOW),
            ("err", C.RED),
            ("info", C.BLUE),
        ]:
            self.log_text.tag_configure(tag, foreground=color)

        self._log("Ready. Pick a song \u2192 set DLC options \u2192 Build.", "info")

        # ── Footer ──
        ctk.CTkFrame(content, fg_color=C.SURFACE1, height=1, corner_radius=0).pack(
            fill="x", pady=(16, 8)
        )
        ctk.CTkLabel(
            content,
            text="Taiko Forge \u00b7 github.com/SonnyTaylor/taiko-forge",
            font=ctk.CTkFont(size=11),
            text_color=C.OVERLAY0,
        ).pack(pady=(0, 8))

    # ── File picking ────────────────────────────────────────────────
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

    # ── State persistence ───────────────────────────────────────────
    def _restore_state(self):
        c = self.cfg
        self.var_at3tool.set(c.get("at3tool", ""))
        self.var_ffmpeg.set(c.get("ffmpeg", ""))
        saved_template = c.get("template", "")
        if self._is_template_source(saved_template):
            self.var_template.set(saved_template)
        else:
            self.var_template.set(_find_bundled_template_zip())
        self.var_output.set(c.get("output", ""))
        self.var_song_id.set(c.get("song_id", "00FF"))
        self.var_folder_name.set(c.get("folder_name", "SONG_DLC_CUSTOM"))

        if not self.var_at3tool.get():
            for candidate in [
                CONFIG_DIR / "tools" / "at3tool" / "at3tool.exe",
                _PROJECT_ROOT / "tools" / "at3tool" / "at3tool.exe",
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

    # ── Dependency checking ─────────────────────────────────────────
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

        for tool, path in deps.items():
            pill = self.dep_pills[tool]
            if path:
                pill.configure(text="\u2713 OK  ", text_color=C.GREEN)
            else:
                pill.configure(text="\u2717 Missing  ", text_color=C.RED)

    # ── Download helpers ────────────────────────────────────────────
    def _download_at3tool(self):
        dlg = ProgressDialog(self, "Downloading at3tool")

        def run():
            from taiko_forge.downloader import download_at3tool

            try:
                dlg.status("Downloading at3tool.zip\u2026")
                exe = download_at3tool(_TOOLS_DIR, dlg.progress)
                self.var_at3tool.set(str(exe))
                self.after(0, self._check_deps)
                dlg.done("at3tool ready!")
            except Exception as exc:
                dlg.error(str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _download_ffmpeg(self):
        dlg = ProgressDialog(self, "Downloading ffmpeg")

        def run():
            from taiko_forge.downloader import download_ffmpeg

            try:
                dlg.status("Downloading ffmpeg essentials (~14 MB)\u2026")
                exe = download_ffmpeg(_TOOLS_DIR, dlg.progress)
                self.var_ffmpeg.set(str(exe))
                self.after(0, self._check_deps)
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

        ESEDialog(self, on_select)

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
                    f"Title: {info['title']}   \u00b7   Artist: {info['subtitle']}\n"
                    f"BPM: {info['bpm']}   \u00b7   Demo Start: {info['demostart']}s\n"
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
        if not self._is_template_source(path):
            self.lbl_template_info.configure(text="")
            return

        try:
            if os.path.isdir(path):
                files = os.listdir(path)
                edats = [f for f in files if f.upper().endswith(".EDAT")]
                fumen_count = sum(1 for f in edats if "FUMEN" in f.upper())
                preview = ", ".join(sorted(edats)[:8])
                if len(edats) > 8:
                    preview += "\u2026"
                self.lbl_template_info.configure(
                    text=f"{len(edats)} EDAT files ({fumen_count} fumen): {preview}"
                )
                return

            with zipfile.ZipFile(path, "r") as zf:
                entries = [Path(i.filename).name for i in zf.infolist() if not i.is_dir()]

            edats = sorted({name for name in entries if name.upper().endswith(".EDAT")})
            fumen_count = sum(1 for f in edats if "FUMEN" in f.upper())
            preview = ", ".join(edats[:8])
            if len(edats) > 8:
                preview += "\u2026"
            self.lbl_template_info.configure(
                text=f"ZIP template: {len(edats)} EDAT files ({fumen_count} fumen): {preview}"
            )
        except Exception as exc:
            self.lbl_template_info.configure(text=f"Template read error: {exc}")

    def _is_template_source(self, path: str) -> bool:
        if not path:
            return False
        if os.path.isdir(path):
            return True
        return os.path.isfile(path) and path.lower().endswith(".zip")

    # ── Logging ─────────────────────────────────────────────────────
    def _log(self, msg, tag=None):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n", tag or "")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log_ts(self, msg, tag=None):
        self.after(0, self._log, msg, tag)

    def _progress_ts(self, val):
        self.after(0, lambda: self.progress_var.set(val))

    # ── Installed DLC Scanner ───────────────────────────────────────
    def _scan_installed_dlc(self):
        """Scan the PSP game folder for existing DLC and display them."""
        output_dir = self.var_output.get()
        self.installed_list.delete(0, "end")

        if not output_dir or not os.path.isdir(output_dir):
            self.installed_info.configure(
                text="Set a PSP Game Folder to scan for installed DLC."
            )
            return

        self.installed_info.configure(text="Scanning\u2026")
        used_ids: set[int] = set()
        dlc_entries: list[str] = []

        for entry in sorted(Path(output_dir).iterdir()):
            if not entry.is_dir():
                continue
            edats = [f for f in entry.iterdir() if f.suffix.upper() == ".EDAT"]
            if not edats:
                continue

            song_id_str = "????"
            mi = next(
                (f for f in edats if "MUSIC_INFO" in f.name.upper()), None
            )
            if mi:
                try:
                    data = mi.read_bytes()
                    if len(data) >= 2:
                        sid = (data[0] << 8) | data[1]
                        song_id_str = f"{sid:04X}"
                        used_ids.add(sid)
                except Exception:
                    pass

            fumen_count = sum(1 for f in edats if "FUMEN" in f.name.upper())
            dlc_entries.append(
                f"  [{song_id_str}] {entry.name}  ({len(edats)} EDAT, {fumen_count} charts)"
            )

        for line in dlc_entries:
            self.installed_list.insert("end", line)

        self.installed_info.configure(
            text=f"{len(dlc_entries)} DLC folder(s) found. "
            f"Song IDs in use: {', '.join(f'0x{i:04X}' for i in sorted(used_ids)) or 'none'}"
        )

        # Auto-suggest next available song ID
        if used_ids:
            next_id = max(used_ids) + 1
            if next_id <= 0xFFFF:
                self.var_song_id.set(f"{next_id:04X}")
                self._log(
                    f"Auto-set Song ID to 0x{next_id:04X} (next available)", "info"
                )

    # ── Batch Build ─────────────────────────────────────────────────
    def _do_batch_build(self):
        """Build DLC for all songs in the download cache."""
        cache_dir = CONFIG_DIR / "songs"
        if not cache_dir.exists():
            self.batch_status_var.set("No cached songs found. Download songs from ESE first.")
            return

        # Validate basic requirements
        template = self.var_template.get()
        output = self.var_output.get()
        at3 = self.var_at3tool.get()
        ffmpeg = self.var_ffmpeg.get() or "ffmpeg"

        errors = []
        if not self._is_template_source(template):
            errors.append("Template DLC folder/zip not set")
        if not output or not os.path.isdir(output):
            errors.append("PSP game folder not set")
        if not at3 or not os.path.isfile(at3):
            errors.append("at3tool.exe not found")
        try:
            subprocess.run([ffmpeg, "-version"], capture_output=True, timeout=5)
        except Exception:
            errors.append("ffmpeg not found")
        try:
            from tja2fumen import main as _  # noqa: F401
        except ImportError:
            errors.append("tja2fumen not installed")

        if errors:
            messagebox.showerror(
                "Cannot Batch Build",
                "\n".join(f"\u2022 {e}" for e in errors),
            )
            return

        # Gather all cached songs with TJA + audio
        songs_to_build: list[tuple[str, str, str]] = []  # (name, tja, audio)
        for song_dir in sorted(cache_dir.iterdir()):
            if not song_dir.is_dir():
                continue
            tja_files = list(song_dir.glob("*.tja"))
            audio_files = list(song_dir.glob("*.ogg")) + list(song_dir.glob("*.mp3")) + list(song_dir.glob("*.wav"))
            if tja_files and audio_files:
                songs_to_build.append(
                    (song_dir.name, str(tja_files[0]), str(audio_files[0]))
                )

        if not songs_to_build:
            self.batch_status_var.set("No complete songs in cache (need TJA + audio).")
            return

        count = len(songs_to_build)
        if not messagebox.askyesno(
            "Batch Build",
            f"Build DLC for {count} cached song(s)?\n\n"
            f"Song IDs will be assigned starting from 0x{self.var_song_id.get()}.\n"
            "Each song gets a separate DLC folder.",
        ):
            return

        self.building = True
        self.btn_batch_build.configure(state="disabled")
        self.btn_build.configure(state="disabled")
        self.batch_prog_var.set(0.0)

        base_id = int(self.var_song_id.get(), 16)

        def run():
            built = 0
            for i, (name, tja, audio) in enumerate(songs_to_build):
                song_id = base_id + i
                if song_id > 0xFFFF:
                    self.after(
                        0,
                        self.batch_status_var.set,
                        f"Stopped: Song ID overflow at 0x{song_id:X}",
                    )
                    break

                safe_name = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")
                folder_name = f"SONG_DLC_{safe_name.upper()[:20]}"
                output_dir = Path(output) / folder_name

                self.after(
                    0,
                    self.batch_status_var.set,
                    f"[{i + 1}/{count}] Building: {name} (ID 0x{song_id:04X})",
                )
                self.after(0, self.batch_prog_var.set, i / count)

                try:
                    builder = DLCBuilder(
                        template_dir=template,
                        output_dir=str(output_dir),
                        tja_path=tja,
                        audio_path=audio,
                        song_id=song_id,
                        at3tool_path=at3,
                        ffmpeg_path=ffmpeg,
                        log_fn=self._log_ts,
                        progress_fn=lambda _: None,  # Use batch progress instead
                    )
                    builder.build()
                    built += 1
                except Exception as exc:
                    self._log_ts(f"Error building {name}: {exc}", "err")

            self.after(0, self.batch_prog_var.set, 1.0)
            self.after(
                0,
                self.batch_status_var.set,
                f"Batch complete! {built}/{count} songs built successfully.",
            )
            self._log_ts(
                f"\nBatch build done: {built}/{count} songs built. \U0001f389", "ok"
            )
            self.after(0, self._batch_build_done, base_id + len(songs_to_build))

        threading.Thread(target=run, daemon=True).start()

    def _batch_build_done(self, next_id: int):
        self.building = False
        self.btn_batch_build.configure(state="normal")
        self.btn_build.configure(state="normal")
        # Update song ID to next available
        if next_id <= 0xFFFF:
            self.var_song_id.set(f"{next_id:04X}")
        self._scan_installed_dlc()

    # ── Build ───────────────────────────────────────────────────────
    def _validate(self) -> bool:
        errors = []
        if not self.var_tja.get() or not os.path.isfile(self.var_tja.get()):
            errors.append("TJA chart file not found")
        if not self.var_audio.get() or not os.path.isfile(self.var_audio.get()):
            errors.append("Audio file not found")
        if not self._is_template_source(self.var_template.get()):
            errors.append("Template DLC folder/zip not found")
        if not self.var_output.get() or not os.path.isdir(self.var_output.get()):
            errors.append("PSP game folder not found")
        at3 = self.var_at3tool.get()
        if not at3 or not os.path.isfile(at3):
            errors.append("at3tool.exe not found \u2014 use Download in Setup")
        ffmpeg = self.var_ffmpeg.get() or "ffmpeg"
        try:
            subprocess.run([ffmpeg, "-version"], capture_output=True, timeout=5)
        except Exception:
            errors.append("ffmpeg not found \u2014 use Download in Setup")
        try:
            from tja2fumen import main as _  # noqa: F401
        except ImportError:
            errors.append("tja2fumen not installed (run: uv add tja2fumen)")
        try:
            sid = int(self.var_song_id.get(), 16)
            if not 0 <= sid <= 0xFFFF:
                raise ValueError
        except ValueError:
            errors.append("Song ID must be hex 0000\u2013FFFF")

        if errors:
            messagebox.showerror(
                "Cannot Build", "\n".join(f"\u2022 {e}" for e in errors)
            )
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
                self._log_ts("Done! Your custom DLC is ready. \U0001f389", "ok")
            except Exception as exc:
                self._log_ts(f"\nERROR: {exc}", "err")
                self._log_ts("Build failed. Check the log above.", "err")
            finally:
                self.after(0, self._build_done)

        threading.Thread(target=run, daemon=True).start()

    def _build_done(self):
        self.building = False
        self.btn_build.configure(state="normal")


def main():
    app = App()
    app.mainloop()
