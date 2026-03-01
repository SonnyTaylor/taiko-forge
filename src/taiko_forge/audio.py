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


def convert_to_wav(input_path: str, output_path: str, ffmpeg: str = "ffmpeg") -> str:
    """Convert any audio format to 44100 Hz, 16-bit stereo WAV."""
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        input_path,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        "2",
        "-sample_fmt",
        "s16",
        output_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{r.stderr[-800:]}")
    return output_path


# Minimum samples required by at3tool -wholeloop (0 <= S < S+6143 <= E)
_MIN_PREVIEW_SAMPLES = 6144
_MIN_PREVIEW_BYTES = _MIN_PREVIEW_SAMPLES * 2 * 2 + 44  # stereo 16-bit + WAV header


def get_audio_duration(input_path: str, ffmpeg: str = "ffmpeg") -> float:
    """Return the duration of an audio file in seconds via ffprobe."""
    ffprobe = (
        os.path.join(os.path.dirname(ffmpeg), "ffprobe")
        if os.path.dirname(ffmpeg)
        else "ffprobe"
    )
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        input_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        try:
            return float(r.stdout.strip())
        except ValueError:
            pass
    return 0.0


def extract_preview(
    input_path: str,
    output_path: str,
    start: float,
    duration: float = PREVIEW_DURATION,
    ffmpeg: str = "ffmpeg",
) -> str:
    """Extract a short clip and convert to 44100 Hz WAV for the song preview.

    If *start* is beyond the audio's end (or the extracted clip is shorter
    than the at3tool minimum of 6144 samples), the extraction is retried
    from position 0 so the preview always gets valid audio.
    """

    def _run(seek_start: float) -> bool:
        cmd = [
            ffmpeg,
            "-y",
            "-ss",
            str(max(0.0, seek_start)),
            "-i",
            input_path,
            "-t",
            str(duration),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "2",
            "-sample_fmt",
            "s16",
            output_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg preview extraction failed:\n{r.stderr[-800:]}")
        return os.path.getsize(output_path) >= _MIN_PREVIEW_BYTES

    ok = _run(start)
    if not ok and start > 0:
        # Retry from the beginning if the requested start yielded nothing useful
        _run(0.0)
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
    at3tool_abs = os.path.abspath(at3tool)
    # Run at3tool from its own directory so that msvcr71.dll (which must
    # sit alongside the executable) is found on all Windows configurations.
    at3tool_dir = os.path.dirname(at3tool_abs)

    cmd = [at3tool_abs]
    if loop:
        cmd.append("-wholeloop")
    # Use absolute paths for in/out so they resolve correctly from at3tool_dir
    cmd += ["-e", os.path.abspath(wav_path), os.path.abspath(at3_path)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=at3tool_dir)
    if r.returncode != 0:
        raise RuntimeError(f"at3tool failed:\n{r.stderr[-400:]}{r.stdout[-400:]}")
    return at3_path
