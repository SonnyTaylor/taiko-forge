"""Auto-download tools (at3tool, ffmpeg) for Taiko Forge."""

import urllib.request
import zipfile
from pathlib import Path

AT3TOOL_URL = "https://www.pspunk.com/files/psp/at3tool.zip"
# gyan.dev release essentials: ffmpeg.exe + ffprobe.exe, ~14 MB compressed
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _download(url: str, dest: Path, progress_fn=None) -> None:
    """Download *url* to *dest*, calling progress_fn(0–1) if supplied."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "taiko-forge/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(dest, "wb") as fh:
            while chunk := resp.read(1 << 15):
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_fn and total:
                    progress_fn(downloaded / total)


def download_at3tool(tools_dir: Path, progress_fn=None) -> Path:
    """Download and extract at3tool.zip into *tools_dir/at3tool/*.

    Returns the path to at3tool.exe.
    """
    out_dir = tools_dir / "at3tool"
    zip_path = tools_dir / "_at3tool_dl.zip"

    if progress_fn:
        progress_fn(0.0)

    _download(
        AT3TOOL_URL,
        zip_path,
        lambda f: progress_fn(f * 0.85) if progress_fn else None,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)
    zip_path.unlink(missing_ok=True)

    if progress_fn:
        progress_fn(1.0)

    exe = out_dir / "at3tool.exe"
    if not exe.exists():
        # Zip might nest files in a sub-folder
        for candidate in out_dir.rglob("at3tool.exe"):
            candidate.rename(exe)
            break

    if not exe.exists():
        raise RuntimeError("at3tool.exe not found after extracting zip")

    return exe


def download_ffmpeg(tools_dir: Path, progress_fn=None) -> Path:
    """Download gyan.dev ffmpeg essentials and extract ffmpeg.exe.

    Places ffmpeg.exe in *tools_dir/ffmpeg/*.  Returns its path.
    """
    out_dir = tools_dir / "ffmpeg"
    zip_path = tools_dir / "_ffmpeg_dl.zip"

    if progress_fn:
        progress_fn(0.0)

    _download(
        FFMPEG_URL,
        zip_path,
        lambda f: progress_fn(f * 0.90) if progress_fn else None,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        # Essentials layout: ffmpeg-X.X-essentials_build/bin/ffmpeg.exe
        extracted = False
        for member in zf.namelist():
            if member.endswith("/bin/ffmpeg.exe") or member == "ffmpeg.exe":
                data = zf.read(member)
                (out_dir / "ffmpeg.exe").write_bytes(data)
                extracted = True
                break
        if not extracted:
            raise RuntimeError("ffmpeg.exe not found inside downloaded zip")

    zip_path.unlink(missing_ok=True)

    if progress_fn:
        progress_fn(1.0)

    return out_dir / "ffmpeg.exe"
