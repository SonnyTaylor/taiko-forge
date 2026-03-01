"""DLC build orchestration.

Ties together audio conversion, chart conversion and EDAT patching into
a single linear pipeline that produces a ready-to-copy DLC folder.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from taiko_forge.audio import convert_to_wav, extract_preview, wav_to_at3
from taiko_forge.edat import (
    inject_at3_into_edat,
    patch_music_info,
    replace_fumen_edat,
)
from taiko_forge.fumen import convert_tja_to_fumen
from taiko_forge.tja import DIFF_MAP, DIFF_SUFFIXES, parse_tja


class DLCBuilder:
    """Builds a complete PSP DLC folder from a TJA chart + audio file."""

    def __init__(
        self,
        *,
        template_dir: str,
        output_dir: str,
        tja_path: str,
        audio_path: str,
        song_id: int,
        at3tool_path: str,
        ffmpeg_path: str,
        log_fn: Callable[[str], None],
        progress_fn: Callable[[float], None],
    ):
        self.template_dir = Path(template_dir)
        self.output_dir = Path(output_dir)
        self.tja_path = tja_path
        self.audio_path = audio_path
        self.song_id = song_id
        self.at3tool = at3tool_path
        self.ffmpeg = ffmpeg_path
        self.log = log_fn
        self.progress = progress_fn
        self.tja_info = parse_tja(tja_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> None:
        steps = 7
        step = 0

        # 1 -- Copy template
        self.log(f"[1/{steps}] Copying template DLC folder...")
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        shutil.copytree(self.template_dir, self.output_dir)
        step += 1
        self.progress(step / steps)

        with tempfile.TemporaryDirectory() as tmpdir:
            # 2 -- Source audio -> 44100 Hz 16-bit WAV
            self.log(f"[2/{steps}] Converting audio to 44100 Hz WAV...")
            wav_full = os.path.join(tmpdir, "song.wav")
            convert_to_wav(self.audio_path, wav_full, self.ffmpeg)
            step += 1
            self.progress(step / steps)

            # 3 -- WAV -> ATRAC3
            self.log(f"[3/{steps}] Encoding to ATRAC3...")
            at3_full = os.path.join(tmpdir, "song.at3")
            wav_to_at3(wav_full, at3_full, self.at3tool)
            step += 1
            self.progress(step / steps)

            # 4 -- Preview clip -> looping ATRAC3
            self.log(f"[4/{steps}] Creating looping preview clip...")
            wav_preview = os.path.join(tmpdir, "preview.wav")
            at3_preview = os.path.join(tmpdir, "preview.at3")
            demo_start = self.tja_info.get("demostart", 0)
            extract_preview(
                self.audio_path, wav_preview, demo_start, ffmpeg=self.ffmpeg
            )
            wav_to_at3(wav_preview, at3_preview, self.at3tool, loop=True)
            step += 1
            self.progress(step / steps)

            # 5 -- TJA -> fumen binaries
            self.log(f"[5/{steps}] Converting TJA charts to fumen...")
            fumen_dir = os.path.join(tmpdir, "fumen")
            os.makedirs(fumen_dir)
            fumens = convert_tja_to_fumen(self.tja_path, fumen_dir)
            names = ", ".join(DIFF_MAP.get(s, s) for s in fumens)
            self.log(f"         Generated: {names}")
            step += 1
            self.progress(step / steps)

            # 6 -- Patch EDAT files
            self.log(f"[6/{steps}] Patching EDAT files...")
            self._patch_edats(at3_full, at3_preview, fumens)
            step += 1
            self.progress(step / steps)

        # 7 -- Song ID + difficulty bytes
        self.log(
            f"[7/{steps}] Setting song ID to 0x{self.song_id:04X} and difficulty bytes..."
        )
        mi = self._find_file("MUSIC_INFO")
        if mi:
            # Map TJA course names (e.g. "Oni", "Easy") to single-letter suffixes
            # so patch_music_info can write the correct difficulty type bytes.
            name_to_suffix = {v.lower(): k for k, v in DIFF_MAP.items()}
            courses_by_suffix = {
                name_to_suffix[name.lower()]: level
                for name, level in self.tja_info.get("courses", {}).items()
                if name.lower() in name_to_suffix
            }
            patch_music_info(mi, self.song_id, courses=courses_by_suffix)
        else:
            self.log("  WARNING: MUSIC_INFO.EDAT not found in template!")
        self.progress(1.0)

        self.log("")
        self.log("== BUILD COMPLETE ==")
        self.log(f"Output: {self.output_dir}")
        self.log("Copy this folder to PSP/GAME/NPJH50426/ on your memory stick.")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find_file(self, pattern: str) -> str | None:
        pat = pattern.upper()
        for f in self.output_dir.iterdir():
            if pat in f.name.upper():
                return str(f)
        return None

    def _find_files(self, pattern: str) -> list[str]:
        pat = pattern.upper()
        return [str(f) for f in self.output_dir.iterdir() if pat in f.name.upper()]

    def _patch_edats(
        self, at3_song: str, at3_preview: str, fumens: dict[str, str]
    ) -> None:
        # -- Song audio --
        song_edat = self._find_file("SONG.EDAT")
        if not song_edat:
            candidates = [
                f
                for f in self._find_files("SONG")
                if "SONG_S" not in Path(f).name.upper()
                and "TEXPACK" not in Path(f).name.upper()
            ]
            song_edat = candidates[0] if candidates else None

        if song_edat:
            offset = inject_at3_into_edat(song_edat, at3_song)
            self.log(f"  Injected audio at 0x{offset:X} in {Path(song_edat).name}")
        else:
            self.log("  WARNING: No SONG EDAT found for audio injection!")

        # -- Preview audio --
        preview_edat = self._find_file("SONG_S")
        if preview_edat:
            offset = inject_at3_into_edat(preview_edat, at3_preview)
            self.log(f"  Injected preview at 0x{offset:X} in {Path(preview_edat).name}")
        else:
            self.log("  WARNING: No SONG_S EDAT found for preview!")

        # -- Fumen charts --
        for suffix, fumen_path in fumens.items():
            diff_name = DIFF_MAP.get(suffix, suffix).upper()
            fumen_edat = self._match_fumen_edat(suffix, diff_name)
            if fumen_edat:
                replace_fumen_edat(fumen_edat, fumen_path)
                self.log(f"  Replaced {Path(fumen_edat).name} with {diff_name} chart")
            else:
                self.log(f"  WARNING: No FUMEN EDAT found for {diff_name}!")

    def _match_fumen_edat(self, suffix: str, diff_name: str) -> str | None:
        # 3-letter abbreviations sometimes used in PSP DLC filenames
        _ABBREV = {
            "e": "EZY",
            "n": "NRM",
            "h": "HRD",
            "m": "ONI",
            "x": "URA",
        }
        abbrev = _ABBREV.get(suffix, suffix.upper())
        for pat in [
            f"FUMEN_{diff_name}",  # FUMEN_ONI
            f"FUMEN{diff_name}",  # FUMENONI
            f"FUMEN_{abbrev}",  # FUMEN_ONI (via abbrev, same for ONI but different for others)
            f"FUMEN{abbrev}",  # FUMENONI
            f"FUMEN_{suffix.upper()}",  # FUMEN_M
            f"FUMEN{suffix.upper()}",  # FUMENM
        ]:
            hit = self._find_file(pat)
            if hit:
                return hit
        # Fallback: match by numeric index (e=1, n=2, h=3, m=4, x=5)
        idx = DIFF_SUFFIXES.index(suffix) + 1
        return self._find_file(f"FUMEN_{idx}") or self._find_file(f"FUMEN{idx}")
