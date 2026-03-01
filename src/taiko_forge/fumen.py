"""TJA-to-fumen chart conversion.

Uses the ``tja2fumen`` library to convert community TJA chart files into
the binary fumen format used by Taiko no Tatsujin on PSP / 3DS / arcade.

Output files follow the naming convention ``{stem}_{suffix}.bin`` where
*suffix* is one of ``e`` (Easy), ``n`` (Normal), ``h`` (Hard),
``m`` (Oni), ``x`` (Ura).  Only single-player charts (no ``_1`` / ``_2``
suffix) are used for PSP DLC.
"""

import shutil
from pathlib import Path

from taiko_forge.tja import DIFF_SUFFIXES


def convert_tja_to_fumen(tja_path: str, work_dir: str) -> dict[str, str]:
    """Convert a TJA file to fumen binaries.

    Parameters
    ----------
    tja_path : str
        Path to the source ``.tja`` file.
    work_dir : str
        Temporary directory where intermediate files are written.

    Returns
    -------
    dict[str, str]
        Mapping of difficulty suffix (``e``, ``n``, ``h``, ``m``, ``x``)
        to the absolute path of the generated ``.bin`` file.  Only
        difficulties present in the TJA are included.
    """
    from tja2fumen import main as tja2fumen_main

    dst = Path(work_dir) / Path(tja_path).name
    shutil.copy2(tja_path, dst)
    tja2fumen_main([str(dst)])

    stem = dst.stem
    results: dict[str, str] = {}
    for suffix in DIFF_SUFFIXES:
        fpath = Path(work_dir) / f"{stem}_{suffix}.bin"
        if fpath.exists():
            results[suffix] = str(fpath)
    return results
