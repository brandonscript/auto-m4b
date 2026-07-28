# auto-m4b

A Python-native audiobook converter that watches a folder for new audiobooks and automatically converts multi-file MP3/M4A collections into a single, chapterized `.m4b`.

## Features

- **Folder watcher** — continuously monitors your inbox and converts new books as they arrive
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
- [Poetry](https://python-poetry.org/) (for running from source)

## Installation

### Docker (recommended)

```bash
docker pull brandonscript/auto-m4b
```

Then copy `docker-compose.template.yml` to `docker-compose.yml`, update the volume paths, and run:

```bash
docker compose up -d
```

See the [Docker](#docker) section below for the full compose example and `docker run` usage.

### From source

```bash
git clone https://github.com/brandonscript/auto-m4b.git
cd auto-m4b
poetry install
```

## Docker

### Docker Compose

Copy `docker-compose.template.yml` to `docker-compose.yml` and edit the volume paths:

```yaml
services:
  auto-m4b:
    image: brandonscript/auto-m4b
    container_name: auto-m4b
    restart: unless-stopped
    volumes:
      - /path/to/inbox:/data/inbox
      - /path/to/converted:/data/converted
      - /path/to/archive:/data/archive
      - /path/to/backup:/data/backup
    environment:
      - INBOX_FOLDER=/data/inbox
      - CONVERTED_FOLDER=/data/converted
      - ARCHIVE_FOLDER=/data/archive
      - BACKUP_FOLDER=/data/backup
      - TZ=America/Vancouver  # your timezone
```

```bash
docker compose up -d
```

### docker run

```bash
docker run -d \
  --name auto-m4b \
  --restart unless-stopped \
  -v /path/to/inbox:/data/inbox \
  -v /path/to/converted:/data/converted \
  -v /path/to/archive:/data/archive \
  -v /path/to/backup:/data/backup \
  -e INBOX_FOLDER=/data/inbox \
  -e CONVERTED_FOLDER=/data/converted \
  -e ARCHIVE_FOLDER=/data/archive \
  -e BACKUP_FOLDER=/data/backup \
  -e TZ=America/Vancouver \
  brandonscript/auto-m4b
```

All configuration is done via environment variables — see the [Configuration reference](#configuration-reference) below for the full list.

## Configuration

### From source

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
| `MAX_BITRATE` | `0` | Max output bitrate in kbps; `0`/unset keeps the source rate. Sources above the cap are re-encoded (m4b passthrough/stream-copy is skipped) |
| `MAX_CHAPTER_LENGTH` | `15,30` | Min/max chapter length in minutes |
| `AUDIO_EXTS` | mp3,m4a,m4b,… | Comma-separated list of audio extensions to process |
| `MATCH_FILTER` | *(none)* | Regex — only process books whose name matches |
| `ON_COMPLETE` | `archive` | What to do with source files after conversion: `archive`, `delete`, or `nothing` |
| `OVERWRITE_EXISTING` | `N` | Set to `Y` to re-convert books that already exist in `CONVERTED_FOLDER` |
| `BACKUP` | `Y` | Set to `N` to skip backing up source files |
| `CRASH_PROTECTION` | `Y` | Set to `N` to disable skipping books that previously failed |
| `USE_FILENAMES_AS_CHAPTERS` | `N` | Set to `Y` to derive chapter titles from filenames instead of ID3 tags |
| `NO_CATS` | `N` | Set to `Y` to suppress the ASCII cat art between loops |
| `OPEN_LIBRARY_USER_AGENT` | *(none)* | User-agent string for Open Library API lookups — enables author/narrator swap detection (see [Open Library setup](#open-library-setup)) |
| `POST_CONVERT_SCRIPT` | *(none)* | Path to a Python (`.py`) or bash (`.sh`) script to run after each successful conversion (see [Post-conversion scripts](#post-conversion-scripts)) |
| `POST_CONVERT_SCRIPT_TIMEOUT` | `60` | Seconds before the post-convert script is killed |

## Open Library setup

auto-m4b can query the [Open Library API](https://openlibrary.org/developers/api) to detect and correct
swapped author/narrator tags. This is most useful for audiobook MP3 rips that use the "music
convention" — where the narrator (performer) is stored in the `artist` field and the author
(creator) is in `composer`, without an `albumartist` tag. Without this correction, auto-m4b may
tag the output `.m4b` with the narrator as the author and vice versa.

### Why this happens

Many torrent-sourced audiobook rips follow music tagging conventions:

| ID3 field | Music meaning | Audiobook meaning | auto-m4b output |
|---|---|---|---|
| `artist` | performer | **narrator** | should become `composer` |
| `composer` | creator | **author** | should become `artist` / `albumartist` |

auto-m4b's local scoring heuristics handle the majority of cases, but when the tags are ambiguous
(e.g. only `artist` and `composer` are set, no `albumartist`) OL is the only reliable way to
determine which name is the actual book author.

### How to enable it

Set `OPEN_LIBRARY_USER_AGENT` in your compose file or `.env`:

```
OPEN_LIBRARY_USER_AGENT=MyApp/1.0 (you@example.com)
```

Per [OL's API policy](https://openlibrary.org/developers/api), the string must include:
- A short name and version for your application (`MyApp/1.0`)
- A contact email in parentheses (`you@example.com`)

Replace both placeholders with real values — do **not** leave the example text as-is.

When the variable is unset or left as the placeholder, OL lookups are silently skipped and
author/narrator are determined from ID3 tags alone.

## Post-conversion scripts

auto-m4b can run a custom script after each successful conversion. Set
`POST_CONVERT_SCRIPT` to the path of a `.py` or `.sh` file (or any executable).
The script runs **after** the converted `.m4b` has been moved to `CONVERTED_FOLDER`
and the inbox source has been archived/deleted per `ON_COMPLETE`.

A failing or timed-out script only logs a warning — it never aborts the
conversion cycle or prevents the next book from being processed. Script
stdout/stderr (and failure details) are written to a dedicated
`auto-m4b.<title>.post-convert.log` next to the converted `.m4b` (not the
`[quality].txt` description file), and non-zero exits also print those details
to the console warning so they aren't swallowed when `DEBUG` is off.

### Environment variables passed to the script

| Variable | Description |
|---|---|
| `AUTO_M4B_INBOX_PATH` | Original inbox path for the book (may no longer exist on disk if archived/deleted) |
| `AUTO_M4B_CONVERTED_PATH` | Full path to the finished `.m4b` file |
| `AUTO_M4B_CONVERTED_DIR` | Directory containing the converted output |
| `AUTO_M4B_TITLE` | Book title (from ID3 / Open Library / filename heuristics) |
| `AUTO_M4B_AUTHOR` | Book author |
| `AUTO_M4B_KEY` | Inbox-relative key (folder name / nested path) |
| `AUTO_M4B_WATCH_SOURCE` | Reconstructed path under `WATCH_FOLDER` (`WATCH_FOLDER`/`AUTO_M4B_KEY`), or empty if `WATCH_FOLDER` is unset |

### Python example

```python
#!/usr/bin/env python3
import os

title = os.environ["AUTO_M4B_TITLE"]
author = os.environ["AUTO_M4B_AUTHOR"]
converted = os.environ["AUTO_M4B_CONVERTED_PATH"]
print(f"Converted '{title}' by {author} → {converted}")
```

### Bash example

```bash
#!/usr/bin/env bash
echo "Converted '${AUTO_M4B_TITLE}' by ${AUTO_M4B_AUTHOR} → ${AUTO_M4B_CONVERTED_PATH}"
```

### Docker setup

Mount a scripts directory into the container and point `POST_CONVERT_SCRIPT` at it:

```yaml
volumes:
  - /path/to/scripts:/scripts:ro
environment:
  - POST_CONVERT_SCRIPT=/scripts/my-hook.py
  - POST_CONVERT_SCRIPT_TIMEOUT=30
```

### Site-specific hooks (e.g. Deluge)

Deluge finalize (relabel + `move_storage` after converting a book copied from
`WATCH_FOLDER`) is intentionally **not** shipped in this repo — mount your own
script via `POST_CONVERT_SCRIPT`. A site-specific example for phantom-docker
lives at `/etc/docker/scripts/auto-m4b/post-convert-deluge.py`.

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
