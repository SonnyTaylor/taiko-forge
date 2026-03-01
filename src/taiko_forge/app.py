"""Taiko Forge GUI application."""

import os
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from taiko_forge.builder import DLCBuilder
from taiko_forge.config import CONFIG_DIR, find_tool, load_config, save_config
from taiko_forge.tja import parse_tja

# -- Resolve project root (for bundled at3tool in tools/) --
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Taiko Forge")
        self.root.geometry("780x920")
        self.root.minsize(680, 780)
        self.root.configure(bg=C.BG)
        self.root.option_add("*Font", ("Segoe UI", 10))

        self.cfg = load_config()
        self.building = False

        self._setup_styles()
        self._build_ui()
        self._restore_state()
        self._check_deps()

    # ---- styling -------------------------------------------------------
    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")

        s.configure(
            ".", background=C.BG, foreground=C.TEXT,
            fieldbackground=C.SURFACE, borderwidth=0,
        )
        s.configure("TFrame", background=C.BG)
        s.configure("Card.TFrame", background=C.SURFACE)
        s.configure("TLabel", background=C.BG, foreground=C.TEXT,
                     font=("Segoe UI", 10))
        s.configure("Card.TLabel", background=C.SURFACE, foreground=C.TEXT)
        s.configure("Header.TLabel", background=C.BG, foreground=C.PEACH,
                     font=("Segoe UI", 11, "bold"))
        s.configure("Title.TLabel", background=C.BG, foreground=C.TEXT,
                     font=("Segoe UI", 18, "bold"))
        s.configure("Sub.TLabel", background=C.BG, foreground=C.SUBTEXT,
                     font=("Segoe UI", 9))
        s.configure("Info.TLabel", background=C.SURFACE, foreground=C.BLUE,
                     font=("Segoe UI Semibold", 10))
        s.configure("TEntry", fieldbackground=C.SURFACE2,
                     foreground=C.TEXT, insertcolor=C.TEXT)
        s.configure("TButton", background=C.SURFACE2, foreground=C.TEXT,
                     font=("Segoe UI Semibold", 10), padding=(12, 6))
        s.map("TButton",
              background=[("active", C.BLUE), ("disabled", C.SURFACE)],
              foreground=[("active", C.BG), ("disabled", C.SUBTEXT)])
        s.configure("Build.TButton", background=C.BLUE, foreground=C.BG,
                     font=("Segoe UI", 13, "bold"), padding=(20, 10))
        s.map("Build.TButton",
              background=[("active", C.GREEN), ("disabled", C.SURFACE)],
              foreground=[("active", C.BG), ("disabled", C.SUBTEXT)])
        s.configure("Browse.TButton", padding=(8, 4), font=("Segoe UI", 9))
        s.configure("Horizontal.TProgressbar", troughcolor=C.SURFACE2,
                     background=C.GREEN, thickness=8)
        s.configure("TLabelframe", background=C.SURFACE, foreground=C.PEACH,
                     font=("Segoe UI", 10, "bold"))
        s.configure("TLabelframe.Label", background=C.SURFACE,
                     foreground=C.PEACH, font=("Segoe UI", 10, "bold"))

    # ---- UI build ------------------------------------------------------
    def _build_ui(self):
        # Scrollable canvas
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

        def _resize(event):
            canvas.itemconfig(canvas.find_all()[0], width=event.width)
        canvas.bind("<Configure>", _resize)

        pad = {"padx": 16, "pady": (4, 4)}
        main = self.scroll_frame

        # -- Title --
        ttk.Label(main, text="Taiko Forge", style="Title.TLabel").pack(
            pady=(16, 0), padx=16, anchor="w",
        )
        ttk.Label(
            main,
            text="Custom DLC builder for Taiko no Tatsujin Portable DX (PSP)",
            style="Sub.TLabel",
        ).pack(padx=16, anchor="w")

        # -- Dependencies --
        dep_frame = ttk.LabelFrame(
            main, text="  Dependencies  ", style="TLabelframe",
        )
        dep_frame.pack(fill="x", **pad, pady=(12, 4))
        self.dep_labels: dict[str, ttk.Label] = {}
        dep_inner = ttk.Frame(dep_frame, style="Card.TFrame")
        dep_inner.pack(fill="x", padx=12, pady=8)
        for i, tool in enumerate(["ffmpeg", "tja2fumen", "at3tool"]):
            ttk.Label(dep_inner, text=f"{tool}:", style="Card.TLabel").grid(
                row=i, column=0, sticky="w", padx=(0, 8), pady=2,
            )
            lbl = ttk.Label(dep_inner, text="checking...", style="Card.TLabel")
            lbl.grid(row=i, column=1, sticky="w", pady=2)
            self.dep_labels[tool] = lbl

        # -- Tool Paths --
        tools_frame = ttk.LabelFrame(
            main, text="  Tool Paths  ", style="TLabelframe",
        )
        tools_frame.pack(fill="x", **pad)
        tools_inner = ttk.Frame(tools_frame, style="Card.TFrame")
        tools_inner.pack(fill="x", padx=12, pady=8)
        tools_inner.columnconfigure(1, weight=1)

        self.var_at3tool = tk.StringVar()
        self.var_ffmpeg = tk.StringVar()
        self._path_row(tools_inner, 0, "at3tool.exe:", self.var_at3tool,
                       [("Executables", "*.exe"), ("All", "*.*")])
        self._path_row(tools_inner, 1, "ffmpeg:", self.var_ffmpeg,
                       [("Executables", "*.exe"), ("All", "*.*")])

        # -- Song Source --
        song_frame = ttk.LabelFrame(
            main, text="  Song Source  ", style="TLabelframe",
        )
        song_frame.pack(fill="x", **pad)
        song_inner = ttk.Frame(song_frame, style="Card.TFrame")
        song_inner.pack(fill="x", padx=12, pady=8)
        song_inner.columnconfigure(1, weight=1)

        self.var_tja = tk.StringVar()
        self.var_audio = tk.StringVar()
        self.var_ese = tk.StringVar()

        self._path_row(
            song_inner, 0, "TJA Chart:", self.var_tja,
            [("TJA files", "*.tja"), ("All", "*.*")],
            callback=self._on_tja_selected,
        )
        self._path_row(
            song_inner, 1, "Audio File:", self.var_audio,
            [("Audio", "*.ogg *.mp3 *.wav *.flac"), ("All", "*.*")],
        )
        self._path_row(song_inner, 2, "ESE Repo (opt):", self.var_ese,
                       directory=True)

        btn_frame = ttk.Frame(song_inner, style="Card.TFrame")
        btn_frame.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(btn_frame, text="Browse ESE...", style="Browse.TButton",
                   command=self._browse_ese).pack(side="left", padx=(0, 8))

        self.song_info_frame = ttk.Frame(song_frame, style="Card.TFrame")
        self.song_info_frame.pack(fill="x", padx=12, pady=(0, 8))
        self.lbl_song_info = ttk.Label(
            self.song_info_frame,
            text="Select a TJA file to see song info",
            style="Info.TLabel", wraplength=650,
        )
        self.lbl_song_info.pack(anchor="w", padx=4, pady=4)

        # -- DLC Settings --
        dlc_frame = ttk.LabelFrame(
            main, text="  DLC Settings  ", style="TLabelframe",
        )
        dlc_frame.pack(fill="x", **pad)
        dlc_inner = ttk.Frame(dlc_frame, style="Card.TFrame")
        dlc_inner.pack(fill="x", padx=12, pady=8)
        dlc_inner.columnconfigure(1, weight=1)

        self.var_template = tk.StringVar()
        self.var_output = tk.StringVar()
        self.var_song_id = tk.StringVar(value="00FF")
        self.var_folder_name = tk.StringVar(value="SONG_DLC_CUSTOM")

        self._path_row(dlc_inner, 0, "Template DLC Folder:", self.var_template,
                       directory=True)
        self._path_row(dlc_inner, 1, "PSP Game Folder:", self.var_output,
                       directory=True)

        ttk.Label(dlc_inner, text="Song ID (hex):", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=4,
        )
        ttk.Entry(dlc_inner, textvariable=self.var_song_id, width=8).grid(
            row=2, column=1, sticky="w", pady=4,
        )

        ttk.Label(dlc_inner, text="Output Folder Name:",
                  style="Card.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=4,
        )
        ttk.Entry(dlc_inner, textvariable=self.var_folder_name).grid(
            row=3, column=1, sticky="ew", pady=4,
        )

        self.lbl_template_info = ttk.Label(dlc_frame, text="",
                                           style="Info.TLabel")
        self.lbl_template_info.pack(anchor="w", padx=16, pady=(0, 8))
        self.var_template.trace_add(
            "write", lambda *_: self._on_template_changed(),
        )

        # -- Build --
        build_pad = ttk.Frame(main, style="TFrame")
        build_pad.pack(fill="x", padx=16, pady=(12, 4))
        self.btn_build = ttk.Button(
            build_pad, text="BUILD DLC",
            style="Build.TButton", command=self._do_build,
        )
        self.btn_build.pack(fill="x")

        # -- Progress --
        self.progress_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(
            main, variable=self.progress_var, maximum=1.0,
            mode="determinate", style="Horizontal.TProgressbar",
        ).pack(fill="x", padx=16, pady=(4, 4))

        # -- Log --
        ttk.Label(main, text="Build Log", style="Header.TLabel").pack(
            anchor="w", padx=16, pady=(8, 2),
        )
        log_frame = tk.Frame(main, bg=C.SURFACE, bd=0)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.log_text = tk.Text(
            log_frame, bg=C.SURFACE, fg=C.TEXT,
            insertbackground=C.TEXT, font=("Cascadia Code", 9),
            relief="flat", padx=8, pady=8, height=14, wrap="word",
            state="disabled",
        )
        log_scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        self.log_text.tag_configure("ok", foreground=C.GREEN)
        self.log_text.tag_configure("warn", foreground=C.YELLOW)
        self.log_text.tag_configure("err", foreground=C.RED)
        self.log_text.tag_configure("info", foreground=C.BLUE)

        self._log(
            "Ready. Select a TJA file and template DLC folder to begin.",
            "info",
        )

    # ---- helpers -------------------------------------------------------
    def _path_row(self, parent, row, label, var, filetypes=None,
                  directory=False, callback=None):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=4,
        )
        ttk.Entry(parent, textvariable=var).grid(
            row=row, column=1, sticky="ew", pady=4, padx=(0, 4),
        )

        def browse():
            if directory:
                path = filedialog.askdirectory(title=label)
            else:
                path = filedialog.askopenfilename(
                    title=label, filetypes=filetypes,
                )
            if path:
                var.set(path)
                if callback:
                    callback()

        ttk.Button(parent, text="Browse", style="Browse.TButton",
                   command=browse).grid(row=row, column=2, pady=4)

        if callback:
            var.trace_add("write", lambda *_: callback())

    # ---- state ---------------------------------------------------------
    def _restore_state(self):
        c = self.cfg
        self.var_at3tool.set(c.get("at3tool", ""))
        self.var_ffmpeg.set(c.get("ffmpeg", ""))
        self.var_ese.set(c.get("ese_repo", ""))
        self.var_template.set(c.get("template", ""))
        self.var_output.set(c.get("output", ""))
        self.var_song_id.set(c.get("song_id", "00FF"))
        self.var_folder_name.set(c.get("folder_name", "SONG_DLC_CUSTOM"))

        # Auto-detect at3tool in tools/ directory
        if not self.var_at3tool.get():
            local = _PROJECT_ROOT / "tools" / "at3tool" / "at3tool.exe"
            if local.exists():
                self.var_at3tool.set(str(local))

    def _save_state(self):
        self.cfg.update({
            "at3tool": self.var_at3tool.get(),
            "ffmpeg": self.var_ffmpeg.get(),
            "ese_repo": self.var_ese.get(),
            "template": self.var_template.get(),
            "output": self.var_output.get(),
            "song_id": self.var_song_id.get(),
            "folder_name": self.var_folder_name.get(),
        })
        save_config(self.cfg)

    # ---- deps ----------------------------------------------------------
    def _check_deps(self):
        at3 = self.var_at3tool.get()
        if not at3 or not os.path.isfile(at3):
            local = _PROJECT_ROOT / "tools" / "at3tool" / "at3tool.exe"
            if local.exists():
                self.var_at3tool.set(str(local))
                at3 = str(local)

        deps = {
            "ffmpeg": find_tool("ffmpeg") or self.var_ffmpeg.get() or None,
            "tja2fumen": None,
            "at3tool": at3 if (at3 and os.path.isfile(at3)) else None,
        }

        try:
            from tja2fumen import main as _  # noqa: F401
            deps["tja2fumen"] = "installed"
        except ImportError:
            pass

        if deps["ffmpeg"] and not self.var_ffmpeg.get():
            self.var_ffmpeg.set(deps["ffmpeg"])

        for tool, path in deps.items():
            lbl = self.dep_labels[tool]
            if path:
                display = "(Python package)" if tool == "tja2fumen" else f"({path})"
                lbl.configure(text=f"OK  {display}", foreground=C.GREEN)
            else:
                hint = {
                    "ffmpeg": "  -  winget install ffmpeg",
                    "tja2fumen": "  -  uv add tja2fumen",
                    "at3tool": "  -  place in tools/at3tool/",
                }.get(tool, "")
                lbl.configure(text=f"NOT FOUND{hint}", foreground=C.RED)

    # ---- callbacks -----------------------------------------------------
    def _on_tja_selected(self):
        path = self.var_tja.get()
        if not path or not os.path.isfile(path):
            return
        try:
            info = parse_tja(path)
            courses = ", ".join(
                f"{k}({v})" for k, v in info["courses"].items()
            ) or "None found"
            text = (
                f"Title: {info['title']}   |   Artist: {info['subtitle']}\n"
                f"BPM: {info['bpm']}   |   Demo Start: {info['demostart']}s\n"
                f"Difficulties: {courses}"
            )
            self.lbl_song_info.configure(text=text)

            if info["wave"]:
                wave_path = Path(path).parent / info["wave"]
                if wave_path.exists() and not self.var_audio.get():
                    self.var_audio.set(str(wave_path))

            if info["title"]:
                safe = re.sub(r"[^\w\s-]", "", info["title"])
                safe = safe.strip().replace(" ", "_")
                self.var_folder_name.set(f"SONG_DLC_{safe.upper()[:20]}")
        except Exception as e:
            self.lbl_song_info.configure(text=f"Error parsing TJA: {e}")

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
            preview += "..."
        self.lbl_template_info.configure(
            text=f"{len(edats)} EDAT files ({fumen_count} fumen): {preview}"
        )

    def _browse_ese(self):
        ese_dir = self.var_ese.get()
        if not ese_dir or not os.path.isdir(ese_dir):
            ese_dir = filedialog.askdirectory(title="Select ESE Repository Root")
            if not ese_dir:
                return
            self.var_ese.set(ese_dir)
        path = filedialog.askopenfilename(
            title="Select TJA from ESE", initialdir=ese_dir,
            filetypes=[("TJA files", "*.tja"), ("All", "*.*")],
        )
        if path:
            self.var_tja.set(path)
            self._on_tja_selected()

    # ---- log -----------------------------------------------------------
    def _log(self, msg, tag=None):
        self.log_text.configure(state="normal")
        if tag:
            self.log_text.insert("end", msg + "\n", tag)
        else:
            self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log_ts(self, msg, tag=None):
        self.root.after(0, self._log, msg, tag)

    def _progress_ts(self, val):
        self.root.after(0, lambda: self.progress_var.set(val))

    # ---- build ---------------------------------------------------------
    def _validate(self) -> bool:
        errors = []

        if not self.var_tja.get() or not os.path.isfile(self.var_tja.get()):
            errors.append("TJA chart file not found")
        if not self.var_audio.get() or not os.path.isfile(self.var_audio.get()):
            errors.append("Audio file not found")
        if not self.var_template.get() or not os.path.isdir(
            self.var_template.get()
        ):
            errors.append("Template DLC folder not found")
        if not self.var_output.get() or not os.path.isdir(
            self.var_output.get()
        ):
            errors.append("PSP game folder (output target) not found")

        at3 = self.var_at3tool.get()
        if not at3 or not os.path.isfile(at3):
            errors.append("at3tool.exe not found")

        ffmpeg = self.var_ffmpeg.get() or "ffmpeg"
        try:
            subprocess.run([ffmpeg, "-version"], capture_output=True, timeout=5)
        except Exception:
            errors.append("ffmpeg not found")

        try:
            from tja2fumen import main as _  # noqa: F401
        except ImportError:
            errors.append("tja2fumen not installed (uv add tja2fumen)")

        try:
            sid = int(self.var_song_id.get(), 16)
            if not 0 <= sid <= 0xFFFF:
                raise ValueError
        except ValueError:
            errors.append("Song ID must be a hex value 0000-FFFF")

        if errors:
            messagebox.showerror("Validation Failed", "\n".join(errors))
            return False
        return True

    def _do_build(self):
        if self.building:
            return
        if not self._validate():
            return

        self._save_state()
        self.building = True
        self.btn_build.configure(state="disabled")
        self.progress_var.set(0)

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        output_dir = Path(self.var_output.get()) / self.var_folder_name.get()
        song_id = int(self.var_song_id.get(), 16)

        builder = DLCBuilder(
            template_dir=self.var_template.get(),
            output_dir=str(output_dir),
            tja_path=self.var_tja.get(),
            audio_path=self.var_audio.get(),
            song_id=song_id,
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
            except Exception as e:
                self._log_ts(f"\nERROR: {e}", "err")
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
