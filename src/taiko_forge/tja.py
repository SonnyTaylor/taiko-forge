"""TJA chart file parser.

Extracts metadata (title, BPM, audio reference, difficulties) from .tja
files used by the Taiko no Tatsujin community.
"""

from pathlib import Path

DIFF_MAP = {
    "e": "Easy",
    "n": "Normal",
    "h": "Hard",
    "m": "Oni",
    "x": "Ura",
}

DIFF_SUFFIXES = list(DIFF_MAP.keys())


def parse_tja(filepath: str) -> dict:
    """Parse a TJA file and return song metadata.

    Returns a dict with keys: title, subtitle, bpm, wave, offset,
    demostart, courses (mapping difficulty name -> level).
    """
    info: dict = {
        "title": "",
        "subtitle": "",
        "bpm": 0.0,
        "wave": "",
        "offset": 0.0,
        "demostart": 0.0,
        "courses": {},
    }

    # Detect encoding
    enc = "utf-8-sig"
    try:
        raw = Path(filepath).read_bytes()
        if raw[:2] == b"\xff\xfe":
            enc = "utf-16-le"
        elif raw[:3] == b"\xef\xbb\xbf":
            enc = "utf-8-sig"
    except Exception:
        pass

    current_course = None
    with open(filepath, encoding=enc, errors="replace") as f:
        for line in f:
            line = line.strip()
            if (
                ":" in line
                and not line.startswith("//")
                and not line.startswith("#")
            ):
                key, _, val = line.partition(":")
                key = key.strip().upper()
                val = val.strip()

                if key == "TITLE":
                    info["title"] = val
                elif key == "SUBTITLE":
                    info["subtitle"] = val.lstrip("-").strip()
                elif key == "BPM":
                    try:
                        info["bpm"] = float(val)
                    except ValueError:
                        pass
                elif key == "WAVE":
                    info["wave"] = val
                elif key == "OFFSET":
                    try:
                        info["offset"] = float(val)
                    except ValueError:
                        pass
                elif key == "DEMOSTART":
                    try:
                        info["demostart"] = float(val)
                    except ValueError:
                        pass
                elif key == "COURSE":
                    current_course = val.strip()
                elif key == "LEVEL" and current_course:
                    try:
                        info["courses"][current_course] = int(val)
                    except ValueError:
                        info["courses"][current_course] = val

    return info
