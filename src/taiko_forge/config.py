"""Persistent configuration and tool discovery."""

import glob
import json
import os
import shutil
from pathlib import Path

CONFIG_DIR = Path.home() / ".taiko-forge"
CONFIG_PATH = CONFIG_DIR / "config.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def find_tool(name: str, extra_paths: list[str] | None = None) -> str | None:
    """Locate an executable by name.

    Checks *extra_paths* first, then the system PATH, then common
    platform-specific install locations.
    """
    if extra_paths:
        for p in extra_paths:
            if os.path.isfile(p):
                return p

    result = shutil.which(name)
    if result:
        return result

    # Windows: search WinGet / Chocolatey / manual installs
    if os.name == "nt" and name == "ffmpeg":
        for pattern in [
            os.path.expanduser(
                "~/AppData/Local/Microsoft/WinGet/Packages/**/ffmpeg.exe"
            ),
            "C:/ffmpeg/bin/ffmpeg.exe",
            "C:/tools/ffmpeg/bin/ffmpeg.exe",
            "C:/ProgramData/chocolatey/bin/ffmpeg.exe",
        ]:
            hits = glob.glob(pattern, recursive=True)
            if hits:
                return hits[0]

    return None
