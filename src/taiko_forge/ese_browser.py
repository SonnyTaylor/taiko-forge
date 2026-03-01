"""ESE Gitea repository browser for Taiko Forge.

Provides helpers to list genres, search songs, and download TJA + OGG
files directly from https://git.vanillaaaa.org/ESE/ESE.
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path

_API = "https://git.vanillaaaa.org/api/v1/repos/ESE/ESE/contents"
_RAW = "https://git.vanillaaaa.org/ESE/ESE/raw/branch/master"

# In-memory genre cache so switching genres doesn't re-fetch from the API
_genre_cache: dict[str, list[dict]] = {}

GENRES = [
    "01 Pop",
    "02 Anime",
    "03 Vocaloid",
    "04 Children and Folk",
    "05 Variety",
    "06 Classical",
    "07 Game Music",
    "08 Live Festival Mode",
    "09 Namco Original",
]


def _api_get(path: str) -> list:
    url = f"{_API}/{urllib.parse.quote(path)}"
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "taiko-forge/1.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def list_songs(genre: str, *, use_cache: bool = True) -> list[dict]:
    """Return song dicts for *genre*.

    Each dict has: ``name``, ``path``, ``tja_url``, ``ogg_url``.
    Results are cached in memory so switching genres is instant.
    """
    if use_cache and genre in _genre_cache:
        return _genre_cache[genre]
    items = _api_get(genre)
    songs = []
    for item in items:
        if item.get("type") != "dir":
            continue
        name = item["name"]
        enc_genre = urllib.parse.quote(genre)
        enc_name = urllib.parse.quote(name)
        base = f"{_RAW}/{enc_genre}/{enc_name}"
        songs.append(
            {
                "name": name,
                "path": item["path"],
                "tja_url": f"{base}/{enc_name}.tja",
                "ogg_url": f"{base}/{enc_name}.ogg",
            }
        )
    songs = sorted(songs, key=lambda s: s["name"].lower())
    _genre_cache[genre] = songs
    return songs


def download_tja(song: dict, dest_dir: Path) -> Path:
    """Download TJA chart for *song* into *dest_dir*. Returns local path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{song['name']}.tja"
    req = urllib.request.Request(
        song["tja_url"], headers={"User-Agent": "taiko-forge/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        dest.write_bytes(resp.read())
    return dest


def download_audio(song: dict, dest_dir: Path, progress_fn=None) -> Path:
    """Download OGG audio for *song* into *dest_dir*. Returns local path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{song['name']}.ogg"
    req = urllib.request.Request(
        song["ogg_url"], headers={"User-Agent": "taiko-forge/1.0"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(dest, "wb") as fh:
            while chunk := resp.read(1 << 15):
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_fn and total:
                    progress_fn(downloaded / total)
    return dest
