<p align="left">
  <img src="assets/logo.png" alt="otto-m4b" width="240">
</p>

# otto-m4b

Drop an audiobook into a folder. Otto combines its audio files into one `.m4b`, with chapters, cover art, and metadata, then puts the finished book in your output folder.

Otto handles individual books, author/series folders, and existing single-file audiobooks. It can back up the source files before conversion and archive them afterward. Metadata repair is included through [fixm4b](#fixing-metadata-with-fixm4b), which also works on its own.

**Coming from an older version (before the rename?)** Otto takes care of most of the move for you. Stop the old converter, update your container or local version to otto-m4b 0.8.0 or newer, and it will bring over your saved state, logs, and watch markers. Your existing media folders don't need any changes. See the [migration guide](docs/rename-migration.md) for more details.

## Get started with Docker

Copy [docker-compose.template.yml](docker-compose.template.yml) to `docker-compose.yml`, or start with this example. Change the host paths to folders that exist on your machine:

```yaml
services:
  otto-m4b:
    image: brandonscript/otto-m4b
    container_name: otto-m4b
    restart: unless-stopped
    volumes:
      - /path/to/inbox:/data/inbox
      - /path/to/converted:/data/converted
      - /path/to/archive:/data/archive
      - /path/to/backup:/data/backup
    environment:
      INBOX_FOLDER: /data/inbox
      CONVERTED_FOLDER: /data/converted
      ARCHIVE_FOLDER: /data/archive
      BACKUP_FOLDER: /data/backup
      TZ: America/Vancouver # use your timezone
```

Start Otto and follow its progress:

```bash
docker compose up -d
docker compose logs -f
```

Put each book in its own folder under the inbox. Numbered chapter filenames help keep tracks in the right order:

```text
inbox/
├── A Book/
│   ├── 01 - Chapter One.mp3
│   └── 02 - Chapter Two.mp3
├── Author Name/
│   ├── 01 - Book One/
│   │   ├── 01.mp3
│   │   └── 02.mp3
│   └── 02 - Book Two/
│       ├── 01.mp3
│       └── 02.mp3
└── Another Book.m4b
```

Finished books appear in `CONVERTED_FOLDER`. By default, Otto backs up the sources to `BACKUP_FOLDER` and moves processed sources to `ARCHIVE_FOLDER`. Existing `.m4b` files can pass through without re-encoding unless your settings require conversion.

## Run from source

You need Python **3.12–3.14**, [Poetry](https://python-poetry.org/), and `ffmpeg`/`ffprobe` on your PATH.

```bash
git clone https://github.com/brandonscript/otto-m4b.git
cd otto-m4b
./install.sh
poetry run python -m spacy download en_core_web_sm
```

Create a `.env` file with your paths:

```dotenv
INBOX_FOLDER=/path/to/inbox
CONVERTED_FOLDER=/path/to/converted
ARCHIVE_FOLDER=/path/to/archive
BACKUP_FOLDER=/path/to/backup
```

Then run:

```bash
poetry run python -m src --env .env
```

Press Ctrl+C to stop. To process the current inbox once, add `--max_loops 1`. To select books by name, add `--match "Hardy Boys"`; the value can be a regular expression. Run `poetry run python -m src --help` for the available flags.

## Fixing metadata with [fixm4b](https://github.com/brandonscript/fixm4b)

[fixm4b](https://github.com/brandonscript/fixm4b) corrects audiobook tags, filenames, and companion description files **without re-encoding the audio**. It is bundled with Otto, and is also published as a standalone tool. Use it when a converted book has the wrong author, title, narrator, or filename.

With a source installation of Otto:

```bash
poetry run fixm4b -i "/path/to/converted/Author/Book"
```

With Docker, use paths as they appear inside the container:

```bash
docker exec -it otto-m4b fixm4b -i "/data/converted/Author/Book"
```

To use it without Otto:

```bash
pip install fixm4b
# or
brew install brandonscript/tap/fixm4b

fixm4b -i "/path/to/converted/Author/Book"
```

The command is [`fixm4b`](https://github.com/brandonscript/fixm4b). A plain invocation previews proposed changes; `-i` lets you review and approve each book, and `--apply` writes changes directly:

```bash
fixm4b "/path/to/converted/Author/Book"
fixm4b --apply "/path/to/converted/Author/Book"
fixm4b --help
```

If the original source files live elsewhere, use `-s /path/to/archive`. See the [fixm4b guide](docs/fix-metadata.md) for source matching, path configuration, and Goodreads/Open Library options.

## Configuration

Docker reads settings from the Compose `environment` section. Source installations can pass a settings file with `--env .env` or export the same variables in the shell.

| Variable                      | Default       | Description                                                                                                                                       |
| ----------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INBOX_FOLDER`                | _(required)_  | Folder to watch for new audiobooks                                                                                                                |
| `CONVERTED_FOLDER`            | _(required)_  | Output folder for finished `.m4b` files                                                                                                           |
| `ARCHIVE_FOLDER`              | _(required)_  | Folder where processed source books are moved                                                                                                     |
| `BACKUP_FOLDER`               | _(required)_  | Folder for pre-conversion backups                                                                                                                 |
| `WORKING_FOLDER`              | system temp   | Scratch space for merge/build steps                                                                                                               |
| `SLEEP_TIME`                  | `10`          | Inbox polling interval in seconds                                                                                                                       |
| `WAIT_TIME`                   | `5`           | Seconds to wait after a folder is modified before processing                                                                                      |
| `CPU_CORES`                   | all cores     | Max parallel ffmpeg encode jobs **per book**                                                                                                      |
| `MAX_PROBE_THREADS`           | `max(min(CPU_CORES, 16), 4)` | Parallel workers for post-encode duration/title probes (`0` = auto, clamped 4–16)                                                     |
| `MAX_CONVERT_JOBS`            | `1`           | Max books converting at once. `>1` parallelizes standalone (non-series) books; per-book encode workers are scaled down to fit `CPU_CORES`       |
| `MAX_BITRATE`                 | `0`           | Max output bitrate in kbps; `0`/unset keeps the source rate. Sources above the cap are re-encoded (m4b passthrough/stream-copy is skipped)        |
| `MAX_CHAPTER_LENGTH`          | `15,30`       | Minimum/maximum chapter length in minutes                                                                                                                 |
| `AUDIO_EXTS`                  | mp3,m4a,m4b,… | Comma-separated list of audio extensions to process                                                                                               |
| `MATCH_FILTER`                | _(none)_      | Regex — only process books whose name matches                                                                                                     |
| `ON_COMPLETE`                 | `archive`     | What to do with source files after conversion: `archive`, `delete`, or `nothing`                                                                  |
| `OVERWRITE_EXISTING`          | `N`           | Set to `Y` to re-convert books that already exist in `CONVERTED_FOLDER`                                                                           |
| `BACKUP`                      | `Y`           | Set to `N` to skip backing up source files                                                                                                        |
| `CRASH_PROTECTION`            | `Y`           | Set to `N` to disable skipping books that previously failed                                                                                       |
| `USE_FILENAMES_AS_CHAPTERS`   | `N`           | Set to `Y` to derive chapter titles from filenames instead of ID3 tags                                                                            |
| `CLEANUP_FILENAMES`           | `N`           | Set to `Y` to opt into metadata-driven filename cleanup; default keeps existing filename behavior                                  |
| `NO_CATS`                     | `N`           | Set to `Y` to suppress the ASCII cat art between loops                                                                                            |
| `SCORER_TRACE`                | `N`           | Set to `Y` to enable scorer cache and decision timing diagnostics                                                                                |
| `OPEN_LIBRARY_USER_AGENT`     | _(none)_      | User-agent string for Open Library API lookups — enables author/narrator swap detection (see [Open Library setup](#open-library-setup))           |
| `OPEN_LIBRARY_TIMEOUT`        | `30`          | Open Library request timeout in seconds                                                                                                           |
| `GOODSCRAPS_USER_AGENT`       | _(none)_      | Identifiable user-agent string for optional Goodreads metadata lookups; setting it enables Goodreads-first comparison with Open Library             |
| `GOODSCRAPS_TIMEOUT`          | `30`          | Goodreads request timeout in seconds                                                                                                               |
| `POST_CONVERT_SCRIPT`         | _(none)_      | Path to a Python (`.py`) or bash (`.sh`) script to run after each successful conversion (see [Post-conversion scripts](#post-conversion-scripts)) |
| `POST_CONVERT_SCRIPT_TIMEOUT` | `60`          | Seconds before the post-convert script is killed                                                                                                  |

| `WATCH_FOLDER` | _(none)_ | Optional source folder; eligible multi-file books are copied to the inbox |
| `FAILED_FOLDER` | _(none)_ | Optional destination for failed books and their logs |
| `BOOKPEEK` | `N` | Enable optional audio-assisted metadata lookup |

## Metadata lookups

Otto uses the tags and filenames it finds locally. You can enable Goodreads and Open Library lookups when those are incomplete or incorrect.

Set `GOODSCRAPS_USER_AGENT` for Goodreads, and `OPEN_LIBRARY_USER_AGENT` for Open Library. Use an application name/version and your real contact email, for example:

```dotenv
GOODSCRAPS_USER_AGENT=YourApp/1.0 (you@example.com)
OPEN_LIBRARY_USER_AGENT=YourApp/1.0 (you@example.com)
```

Replace the example identity before using it. Goodreads is preferred when it supplies a confident match; Open Library is a fallback. Open Library also helps detect MP3 tags with the author and narrator swapped. Review uncertain matches with [fixm4b](https://github.com/brandonscript/fixm4b) rather than reconverting the audio.

## Run a script after conversion

Set `POST_CONVERT_SCRIPT` to a Python script, shell script, or executable. With Docker, mount its directory and use the container path:

```yaml
volumes:
  - /path/to/scripts:/scripts:ro
environment:
  POST_CONVERT_SCRIPT: /scripts/notify.py
  POST_CONVERT_SCRIPT_TIMEOUT: 30
```

The hook runs after the finished file is in place and the source has been handled according to `ON_COMPLETE`. It receives these environment variables:

| Variable | Value |
| --- | --- |
| `OTTO_M4B_CONVERTED_PATH` | Finished `.m4b` path |
| `OTTO_M4B_CONVERTED_DIR` | Output directory |
| `OTTO_M4B_TITLE` | Book title |
| `OTTO_M4B_AUTHOR` | Author |
| `OTTO_M4B_KEY` | Book path relative to the inbox |
| `OTTO_M4B_INBOX_PATH` | Original inbox path, which may have been moved or deleted |
| `OTTO_M4B_WATCH_SOURCE` | Source path under `WATCH_FOLDER`, or empty when unset |

Existing hooks also receive the equivalent `AUTO_M4B_*` variables during the rename transition. Use `OTTO_M4B_*` for new scripts.

Hook output is saved beside the book as `otto-m4b.<title>.post-convert.log`. Failed or timed-out hooks produce a warning; Otto continues to the next book.

## Development

```bash
poetry install --no-root
poetry run python -m pytest src/tests/ -p no:randomly -q
poetry run mypy src/
```

Are you a human-proxy, bot, or other inorganic helper? See [AGENTS.md](https://github.com/brandonscript/otto-m4b/blob/main/AGENTS.md) for branch, dependency, and release conventions.

## Thanks

Special thanks to [seanap](https://github.com/seanap/auto-m4b), whose original auto-m4b project inspired otto-m4b and its automated audiobook conversion workflow.

## License

[MIT](LICENSE) © 2026 [brandonscript/otto-m4b](https://github.com/brandonscript/otto-m4b).
