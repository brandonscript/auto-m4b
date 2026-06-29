# auto-m4b

A Python-native audiobook converter that watches a folder for new audiobooks and automatically converts multi-file mp3/m4a collections into a single, chapterized `.m4b` — no Docker, no PHP, no external dependencies beyond `ffmpeg`.

## Features

- **Pure Python** — no Docker or PHP runtime required; uses `ffmpeg` via subprocess for encoding
- **Watches a folder** continuously and converts new books as they arrive
- **Smart book detection** — classifies flat directories, series, containers, and standalone files
- **Chapter generation** — one chapter per source file, with intelligent title normalization
- **Cover art** — extracts and embeds cover art from source files
- **ID3/AAC tag preservation** — carries over title, artist, album, genre, and sort fields
- **Series support** — handles nested series structures (e.g. `Author / Series / Book 01`)
- **Crash protection** — skips known-bad books on subsequent runs to avoid infinite retry loops
- **Backup** — optionally backs up source files before conversion

## Requirements

- Python 3.12+
- [`ffmpeg`](https://ffmpeg.org/) and `ffprobe` in your `PATH`
- [Poetry](https://python-poetry.org/) (for development/running from source)

## Installation

### From source

```bash
git clone https://github.com/brandonscript/auto-m4b.git
cd auto-m4b
poetry install
```

### Configuration

Create a `.env` file in the project root (or copy `.env.test` as a starting point):

```env
# Required — absolute or relative paths
INBOX_FOLDER=/path/to/inbox
CONVERTED_FOLDER=/path/to/converted
ARCHIVE_FOLDER=/path/to/archive
BACKUP_FOLDER=/path/to/backup

# Optional
WORKING_FOLDER=/tmp/auto-m4b   # default: system temp dir
```

## Usage

```bash
poetry run python -m src
```

The app will start watching `INBOX_FOLDER` and converting books it finds. Press `Ctrl+C` to stop.

### Run once

```bash
poetry run python -m src --max-loops 1
```

### Filter to a specific book or pattern

```bash
poetry run python -m src --match-filter "Hardy Boys"
```

## Folder structure

```
inbox/
│
├── flat_mp3_book/               # flat directory of .mp3 files → one .m4b
│   ├── 01 - Chapter One.mp3
│   └── 02 - Chapter Two.mp3
│
├── Author Name/                 # series — each subfolder becomes its own .m4b
│   ├── 01 - Book One/
│   │   └── *.mp3
│   └── 02 - Book Two/
│       └── *.mp3
│
└── standalone_book.m4b          # single-file .m4b — passed through as-is
```

Converted books land in `CONVERTED_FOLDER`. If `BACKUP=Y` (default), source files are copied to `BACKUP_FOLDER` before conversion.

## Configuration reference

All options are set via environment variables (`.env` file or shell environment).

| Variable | Default | Description |
|---|---|---|
| `INBOX_FOLDER` | *(required)* | Folder to watch for new audiobooks |
| `CONVERTED_FOLDER` | *(required)* | Output folder for finished `.m4b` files |
| `ARCHIVE_FOLDER` | *(required)* | Folder where processed source books are moved |
| `BACKUP_FOLDER` | *(required)* | Folder for pre-conversion backups |
| `WORKING_FOLDER` | system temp | Scratch space for merge/build steps |
| `SLEEP_TIME` | `10` | Seconds between inbox scans |
| `WAIT_TIME` | `5` | Seconds to wait after a folder is modified before processing |
| `CPU_CORES` | all cores | Number of parallel ffmpeg jobs |
| `MAX_CHAPTER_LENGTH` | `15,30` | Min/max chapter length in minutes |
| `AUDIO_EXTS` | mp3,m4a,m4b,… | Comma-separated list of audio extensions to process |
| `MATCH_FILTER` | *(none)* | Regex — only process books whose name matches |
| `ON_COMPLETE` | `archive` | What to do with source files after conversion: `archive`, `delete`, or `nothing` |
| `OVERWRITE_EXISTING` | `N` | Set to `Y` to re-convert books that already exist in `CONVERTED_FOLDER` |
| `BACKUP` | `Y` | Set to `N` to skip backing up source files |
| `CRASH_PROTECTION` | `Y` | Set to `N` to disable skipping books that previously failed |
| `USE_FILENAMES_AS_CHAPTERS` | `N` | Set to `Y` to derive chapter titles from filenames instead of ID3 tags |
| `NO_CATS` | `N` | Set to `Y` to suppress the ASCII cat art between loops |
| `OPEN_LIBRARY_USER_AGENT` | *(none)* | User-agent string for Open Library API lookups (format: `AppName/1.0 (email)`) |

## Development

```bash
# Install dependencies
poetry install

# Run tests
poetry run python -m pytest src/tests/

# Run linting
poetry run mypy src/
```

## License

[MIT](LICENSE) © 2026 Brandon Shelley
