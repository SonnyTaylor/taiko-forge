"""Audio conversion pipeline.

Handles the full chain: source audio -> 44100 Hz 16-bit WAV -> ATRAC3 (.at3).

ATRAC3 notes (PSP format)
-------------------------
- PSP games use Sony's ATRAC3 / ATRAC3plus codec stored in RIFF-WAV
  containers with the .at3 extension.
- Source WAV *must* be 44100 Hz, 16-bit, stereo PCM before encoding.
- The ``at3tool`` encoder (from Sony's PSP SDK) produces the correct
  format: ``at3tool -e input.wav output.at3``
- For looping audio (e.g. song previews) add ``-wholeloop``.
- Encoded files begin with a standard RIFF header
  (``b'RIFF....WAVEfmt '``) which the game uses as the injection point
  inside EDAT containers.
"""

import os
import subprocess

SAMPLE_RATE = 44100
PREVIEW_DURATION = 15  # seconds


def convert_to_wav(
    input_path: str, output_path: str, ffmpeg: str = "ffmpeg"
) -> str:
    """Convert any audio format to 44100 Hz, 16-bit stereo WAV."""
    cmd = [
        ffmpeg, "-y", "-i", input_path,
        "-ar", str(SAMPLE_RATE),
        "-ac", "2",
        "-sample_fmt", "s16",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{r.stderr[-800:]}")
    return output_path


def extract_preview(
    input_path: str,
    output_path: str,
    start: float,
    duration: float = PREVIEW_DURATION,
    ffmpeg: str = "ffmpeg",
) -> str:
    """Extract a short clip and convert to 44100 Hz WAV for the song preview."""
    cmd = [
        ffmpeg, "-y",
        "-ss", str(max(0, start)),
        "-i", input_path,
        "-t", str(duration),
        "-ar", str(SAMPLE_RATE),
        "-ac", "2",
        "-sample_fmt", "s16",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg preview extraction failed:\n{r.stderr[-800:]}")
    return output_path


def wav_to_at3(
    wav_path: str, at3_path: str, at3tool: str, *, loop: bool = False
) -> str:
    """Encode a WAV file to ATRAC3 using Sony's at3tool.

    Parameters
    ----------
    loop : bool
        Pass ``-wholeloop`` so the PSP loops the entire file (used for
        the short song preview ``SONG_S.EDAT``).
    """
    cmd = [os.path.abspath(at3tool)]
    if loop:
        cmd.append("-wholeloop")
    cmd += ["-e", wav_path, at3_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"at3tool failed:\n{r.stderr[-400:]}{r.stdout[-400:]}"
        )
    return at3_path
