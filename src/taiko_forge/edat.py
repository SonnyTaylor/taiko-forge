"""EDAT file patchers for PSP Taiko DLC.

DLC songs for Taiko no Tatsujin Portable DX live in folders containing
several ``.EDAT`` files.  Despite the extension these are *not*
encrypted; each is a thin container around raw payload data.

Files handled
-------------
- ``MUSIC_INFO.EDAT`` -- first two bytes encode the unique song ID.
- ``SONG.EDAT``       -- audio container.  Everything from the ``RIFF``
  marker onward is the ATRAC3 stream.
- ``SONG_S.EDAT``     -- same layout as SONG.EDAT but holds a short
  looping preview clip.
- ``*FUMEN*.EDAT``    -- raw fumen binary chart data (full replacement).
"""

from pathlib import Path


def patch_music_info(edat_path: str, song_id: int) -> None:
    """Write a 2-byte song ID into the first two bytes of MUSIC_INFO.EDAT."""
    data = bytearray(Path(edat_path).read_bytes())
    data[0] = (song_id >> 8) & 0xFF
    data[1] = song_id & 0xFF
    Path(edat_path).write_bytes(bytes(data))


def inject_at3_into_edat(edat_path: str, at3_path: str) -> int:
    """Replace the audio payload inside SONG.EDAT / SONG_S.EDAT.

    Locates the ``RIFF`` header (which marks the start of the ATRAC3
    data) and replaces everything from that offset onward with the
    contents of *at3_path*.

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

    Path(edat_path).write_bytes(bytes(edat[:idx]) + at3)
    return idx


def replace_fumen_edat(edat_path: str, fumen_path: str) -> None:
    """Replace a FUMEN EDAT with new chart data (full file replacement)."""
    Path(edat_path).write_bytes(Path(fumen_path).read_bytes())
