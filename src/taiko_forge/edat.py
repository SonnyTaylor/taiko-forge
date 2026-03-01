"""EDAT file patchers for PSP Taiko DLC.

DLC songs for Taiko no Tatsujin Portable DX live in folders containing
several ``.EDAT`` files.  Despite the extension these are *not*
encrypted; each is a thin container around raw payload data.

Files handled
-------------
- ``MUSIC_INFO.EDAT`` -- first two bytes encode the unique song ID.
                         Difficulty star ratings are stored near the end.
- ``SONG.EDAT``       -- audio container.  Everything from the ``RIFF``
  marker onward is the ATRAC3 stream.  A 3-byte little-endian size field
  in the header (before RIFF) records the AT3 payload length and must be
  updated whenever the audio is replaced with a different-sized file.
- ``SONG_S.EDAT``     -- same layout as SONG.EDAT but holds a short
  looping preview clip.  The size field is especially important here:
  if it is stale the PSP will cut off playback after a few seconds.
- ``*FUMEN*.EDAT``    -- raw fumen binary chart data (full replacement).
"""

import struct
from pathlib import Path


# Difficulty type byte values used by MUSIC_INFO.EDAT
DIFF_BYTE = {
    "e": 0x01,  # Easy
    "n": 0x02,  # Normal
    "h": 0x03,  # Hard
    "m": 0x04,  # Oni
    "x": 0x05,  # Ura/Oni+
}


def patch_music_info(edat_path: str, song_id: int, courses: dict | None = None) -> None:
    """Write song ID and optionally difficulty bytes into MUSIC_INFO.EDAT.

    - Bytes 0–1: song ID (big-endian).
    - Near the end of the file: difficulty type bytes (01=Easy, 02=Normal,
      03=Hard, 04=Oni, 05=Ura).  These control the icons shown on the song
      select screen.  Each difficulty that is present in *courses* (a dict
      mapping suffix like 'e'/'n'/'h'/'m'/'x' to star level) has its byte
      updated.
    """
    data = bytearray(Path(edat_path).read_bytes())
    # Song ID
    data[0] = (song_id >> 8) & 0xFF
    data[1] = song_id & 0xFF

    # Patch difficulty type bytes if course info is supplied.
    # The bytes live somewhere inside the last 64 bytes of MUSIC_INFO.EDAT.
    # Their layout: consecutive bytes whose values indicate which difficulty
    # slots are active (01-05).  We scan backward from EOF looking for any
    # existing difficulty type byte (01-04) and replace the sequence.
    if courses:
        present = sorted(
            [DIFF_BYTE[s] for s in courses if s in DIFF_BYTE],
        )
        if present:
            _patch_difficulty_display(data, present)

    Path(edat_path).write_bytes(bytes(data))


def _patch_difficulty_display(data: bytearray, difficulty_bytes: list[int]) -> None:
    """Attempt to update difficulty-display bytes near the end of the file.

    Searches the last 64 bytes for an existing difficulty sequence (all
    values in 0x01-0x05 range) and overwrites with the new values, zero-
    padding the remainder of the original slot region so unused slots are
    cleared.
    """
    tail_start = max(0, len(data) - 64)
    tail = data[tail_start:]

    # Find a run of 1-5 consecutive bytes all in range 0x01..0x05
    best_pos: int | None = None
    best_len = 0
    i = 0
    while i < len(tail):
        if 0x01 <= tail[i] <= 0x05:
            j = i
            while j < len(tail) and 0x01 <= tail[j] <= 0x05:
                j += 1
            run_len = j - i
            if run_len >= best_len:
                best_len = run_len
                best_pos = i
            i = j
        else:
            i += 1

    if best_pos is not None and best_len >= 1:
        abs_pos = tail_start + best_pos
        # Overwrite the run with new difficulty bytes (pad with 0 if shorter)
        for k in range(best_len):
            data[abs_pos + k] = (
                difficulty_bytes[k] if k < len(difficulty_bytes) else 0x00
            )


def _patch_at3_size_in_header(
    header: bytearray, old_size: int, new_size: int
) -> bytearray:
    """Replace 3-byte little-endian size encodings in an EDAT header.

    PSP Taiko EDATs store a 3-byte little-endian field immediately before
    the RIFF payload that tells the console how many bytes of audio data
    follow.  This must be updated when the replacement AT3 is a different
    size from the template audio, otherwise the preview clip will cut off
    after a few seconds (or crash on real hardware).

    The function replaces *all* occurrences of the old 3-byte encoding so
    it works regardless of exact offset.
    """
    if old_size == new_size or len(header) < 3:
        return header

    old_le = struct.pack("<I", old_size)[:3]
    new_le = struct.pack("<I", new_size)[:3]

    result = bytearray()
    i = 0
    while i < len(header):
        if header[i : i + 3] == old_le:
            result.extend(new_le)
            i += 3
        else:
            result.append(header[i])
            i += 1
    return result


def inject_at3_into_edat(edat_path: str, at3_path: str) -> int:
    """Replace the audio payload inside SONG.EDAT / SONG_S.EDAT.

    Locates the ``RIFF`` header (which marks the start of the ATRAC3
    data) and replaces everything from that offset onward with the
    contents of *at3_path*.  Also updates the 3-byte little-endian size
    field in the header so the PSP reads the full audio and the preview
    loops correctly.

    Returns the byte offset where the injection was made.
    """
    edat = bytearray(Path(edat_path).read_bytes())
    at3 = Path(at3_path).read_bytes()

    idx = edat.find(b"RIFF")
    if idx == -1:
        raise RuntimeError(
            f"RIFF marker not found in {Path(edat_path).name}. "
            "The template may not contain audio data."
        )

    old_at3_size = len(edat) - idx
    new_at3_size = len(at3)

    # Patch the size field in the header bytes that precede the RIFF marker.
    header = _patch_at3_size_in_header(
        bytearray(edat[:idx]), old_at3_size, new_at3_size
    )

    Path(edat_path).write_bytes(bytes(header) + at3)
    return idx


def replace_fumen_edat(edat_path: str, fumen_path: str) -> None:
    """Replace a FUMEN EDAT with new chart data (full file replacement)."""
    Path(edat_path).write_bytes(Path(fumen_path).read_bytes())
