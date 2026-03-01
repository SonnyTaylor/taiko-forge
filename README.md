# Taiko Forge

Custom DLC builder for **Taiko no Tatsujin Portable DX** (PSP).

Takes a TJA chart file + audio and produces a ready-to-copy DLC folder
for your PSP. One click from `.tja` to playable song.

## What it does

1. Parses your TJA chart and extracts all difficulties
2. Converts audio (OGG/MP3/FLAC/WAV) to 44100 Hz 16-bit WAV, then to Sony ATRAC3
3. Generates a looping preview clip from the `DEMOSTART` position
4. Converts TJA charts to fumen binary format (all difficulties)
5. Patches the DLC template: injects audio into `SONG.EDAT`, preview into `SONG_S.EDAT`, charts into `FUMEN` EDATs, and sets a unique song ID in `MUSIC_INFO.EDAT`

## Prerequisites

| Tool | Purpose | How to get it |
|------|---------|---------------|
| **Python 3.11+** | Runtime | [python.org](https://www.python.org/) |
| **uv** | Package manager | `pip install uv` or [docs.astral.sh/uv](https://docs.astral.sh/uv/) |
| **ffmpeg** | Audio decoding/resampling | `winget install ffmpeg` or [ffmpeg.org](https://ffmpeg.org/) |
| **at3tool.exe** | ATRAC3 encoder | See [below](#at3tool) |

### at3tool

`at3tool.exe` is Sony's ATRAC3 encoder. It is not freely distributable but can
be found online. Place it (along with `msvcr71.dll` if needed) in the
`tools/at3tool/` directory:

```
tools/
  at3tool/
    at3tool.exe
    msvcr71.dll
```

The app auto-detects it from this location.

#### ATRAC3 format notes

PSP games use Sony's ATRAC3 codec stored in RIFF-WAV containers (`.at3` files).
Key constraints:

- Source audio **must** be 44100 Hz, 16-bit PCM, stereo WAV before encoding
- `at3tool -e input.wav output.at3` encodes a song
- `at3tool -wholeloop -e input.wav output.at3` makes the file loop (for previews)
- Encoded files start with a standard `RIFF....WAVEfmt` header

Taiko Forge handles all of this automatically.

## Install

```bash
git clone <this-repo>
cd taiko-forge

uv sync
```

## Usage

```bash
uv run taiko-forge
```

Or run directly:

```bash
uv run python -m taiko_forge
```

### Quick start

1. **Get a template DLC folder** -- Copy any existing `SONG_DLC_XXX` folder from
   your PSP's `PSP/GAME/NPJH50426/` directory. This is used as the base structure.

2. **Get a TJA chart** -- Either create your own or grab one from the
   [ESE (Every Song Ever)](https://git.vanillaaaa.org/ESE/ESE) community database,
   which has TJA charts for thousands of official Taiko songs organized by genre:
   - `01 Pop`, `02 Anime`, `03 Vocaloid`, `04 Children and Folk`
   - `05 Variety`, `06 Classical`, `07 Game Music`
   - `09 Namco Original`, and more

3. **Get the audio** -- The matching audio file for your chart (OGG, MP3, WAV, etc.)

4. **Launch Taiko Forge**, fill in the paths, and hit **BUILD DLC**

5. **Copy the output folder** to `PSP/GAME/NPJH50426/` on your memory stick

### How PSP Taiko DLC works

Each DLC song lives in a folder (e.g. `SONG_DLC_001`) containing EDAT files:

| File | Contents |
|------|----------|
| `MUSIC_INFO.EDAT` | Song metadata. First 2 bytes = unique song ID |
| `SONG.EDAT` | Full song audio (ATRAC3 data after `RIFF` header) |
| `SONG_S.EDAT` | Short looping preview clip (same format) |
| `*FUMEN*.EDAT` | Chart data for each difficulty (binary fumen format) |
| `*TEXPACK*.EDAT` | Song title textures (not currently modifiable) |

Taiko Forge copies a template folder, replaces the payloads inside each EDAT
with your custom content, and assigns a unique song ID.

## Project structure

```
taiko-forge/
  src/taiko_forge/
    __init__.py     # Package version
    __main__.py     # Entry point
    app.py          # GUI (tkinter)
    audio.py        # ffmpeg + at3tool pipeline
    builder.py      # Build orchestration
    config.py       # Settings persistence
    edat.py         # EDAT binary patching
    fumen.py        # TJA -> fumen conversion
    tja.py          # TJA chart parser
  tools/
    at3tool/        # Place at3tool.exe here
  examples/         # Example TJA files
  pyproject.toml
  README.md
```

## Known limitations

- **Song name textures** (`*TEXPACK*.EDAT`) cannot be modified yet -- the song
  title on the selection screen will show the name from your template DLC.
- **Pause/resume** may cause the song audio to reset. This is a PSP limitation
  with injected audio.
- Chart conversion uses the **single-player** charts from the TJA. Double-play
  (P1/P2) charts are generated but not used by the PSP version.

## Credits

- [tja2fumen](https://github.com/vivaria/tja2fumen) -- TJA to fumen conversion
- [ESE (Every Song Ever)](https://git.vanillaaaa.org/ESE/ESE) -- Community TJA database
- [PSPunk ATRAC3 guide](https://www.pspunk.com/psp-atrac3/) -- ATRAC3 format reference
- Original modding method documented by the PSP Taiko community

## License

MIT
