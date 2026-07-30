# Agent notes for auto-m4b

Quick reference for AI agents working in this repo.

## Environment

- **Python:** 3.12 (see `pyproject.toml`)
- **Dependency manager:** [Poetry](https://python-poetry.org/)
- **Virtualenv:** project-local at `.venv/` (`poetry.toml` sets `virtualenvs.in-project = true`)

Do **not** use the system `python` or `pytest` directly — imports like `tinta` live in the Poetry venv and will fail otherwise.

### First-time / fresh clone setup

```bash
cd /path/to/auto-m4b
poetry install
poetry run python -m spacy download en_core_web_sm
```

System requirement: `ffmpeg` and `ffprobe` on `PATH`.

### Running commands

Prefer either form:

```bash
# Option A: poetry run (works without activating the venv)
poetry run python -m pytest src/tests/test_books_tree.py -q

# Option B: activate the venv first
source .venv/bin/activate
python -m pytest src/tests/test_books_tree.py -q
```

Verify you're on the right interpreter:

```bash
poetry run python -c "import sys; print(sys.executable)"
# → .../auto-m4b/.venv/bin/python
```

## Project layout

| Path                  | Purpose                                                            |
| --------------------- | ------------------------------------------------------------------ |
| `src/`                | Application code (`src/lib/`, `src/auto_m4b.py`)                   |
| `src/fix_metadata.py`| Standalone CLI to retag/rename converted books (no re-encode)      |
| `docs/fix-metadata.md` | Operator/agent reference for that CLI                            |
| `src/tests/`          | Pytest suite                                                       |
| `src/tests/helpers/`  | Fixtures, mocks (`pytest_dumps.py`, `pytest_fixtures.py`)          |
| `src/tests/tmp/`      | Ephemeral test dirs (inbox, converted, etc.) — created by fixtures |
| `src/tests/fixtures/` | Static test audio/fixture files                                    |

Tests append `src/` to `sys.path` via `src/tests/conftest.py`.

## Common commands

```bash
# Run the app
poetry run python -m src

# Run all tests (default pytest addopts: verbose, color, --slow)
poetry run python -m pytest src/tests/

# Run one test file or node
poetry run python -m pytest src/tests/test_books_tree.py -q
poetry run python -m pytest "src/tests/test_books_tree.py::test_tree_finding::test_find_books_in_inbox[path7-2-2-expected7]" -v

# Type check
poetry run mypy src/

# Lint/format (dev deps)
poetry run ruff check src/
poetry run black src/
```

CI runs a subset of tests (see `.github/workflows/ci.yml`) and skips some slow/e2e suites.

## Test gotchas

- Many tests need the **`mock_inbox`** fixture, which populates `src/tests/tmp/inbox/` with synthetic audiobook dirs. Don't debug tree-finding tests against an empty inbox.
- Pytest is configured with `--slow` in `pyproject.toml` addopts; slow tests are included by default.
- Some tests require NLTK data and the spaCy `en_core_web_sm` model (CI downloads these).
- If you need to create new test fixtures, ideally try to use the fake-generated mocked books for tests, because they are very small files. If a real file with real id3 tags is required, pause and ask the user to create small fragments of the real files.

## Development workflow

### Rules (enforced for every change)

**A. All tests must pass before committing.**

Run the full suite locally before committing anything — even small changes:

```bash
poetry run python -m pytest src/tests/ -p no:randomly -q
```

The three known-flaky tests (see [Known flaky tests](#known-flaky-tests) below) may be ignored when all other tests pass. Everything else must be green.

**B. Once tests pass, push to `dev`.**

After a passing run, commit and push to `origin/dev`:

```bash
git add -A
git commit -m "your message"
git push origin dev
```

Do not leave passing changes uncommitted on the local branch. The container runs off whatever is checked out at `/etc/docker/auto-m4b/`, but the canonical source of truth is `origin/dev`.

**C. Auto-rebuild the live container when the real inbox is empty.**

After finishing auto-m4b code changes (tests green, committed/pushed as appropriate), check the **real** production inbox. If it has no books waiting **and** the `auto-m4b` container is currently running, rebuild it automatically so Phantom picks up the new code:

```bash
INBOX="/mnt/ragnarok/media/Books/Audiobooks/#auto-m4b/inbox"
# Count non-junk entries (ignore .DS_Store / hidden files)
ls -A "$INBOX" 2>/dev/null | grep -v '^\.' | grep -v '^\.DS_Store$' || true

# If empty and container is up:
docker ps --format '{{.Names}}' | grep -qx auto-m4b && dr rebuild auto-m4b:nvidia
```

- **Do rebuild** when the inbox has no convertible book folders/files (empty or only junk like `.DS_Store`).
- **Do not rebuild** if books are still in the inbox — that would interrupt an in-flight conversion. Tell the user the changes are ready and they should rebuild once the inbox drains (or ask them to confirm).
- Prefer `dr rebuild auto-m4b:nvidia` (Phantom’s GPU variant). Both variants share `container_name: auto-m4b`.

### Branching strategy

The author uses a `dev` branch for small, ongoing feature work and incremental fixes. Most day-to-day development lands in `dev` first and is released to `main` from there.

Larger, independent features or fixes that need isolation still get their own branches off `main`. But as a rule: if it's a small improvement that doesn't need a separate review context, it goes in `dev`.

Agents should not create new branches for small changes unless the author asks. When in doubt, ask.

### Releasing to `main`

When `dev` is ready to release:

1. Squash-merge `dev` into `main` (preserves `dev` history):
   ```bash
   git checkout main
   git merge --squash dev
   ```
2. Bump `version` in `pyproject.toml` (semver — patch for fixes, minor for features).
3. Commit with a release message summarising the changes.
4. Push both branches:
   ```bash
   git push origin main
   git push origin dev
   ```

## Open Library author/narrator swap detection

auto-m4b can query the [Open Library API](https://openlibrary.org/developers/api) to detect when
author and narrator tags are swapped in source files (common with MP3 rips that use the music
convention: `artist = narrator`, `composer = author`, no `albumartist`).

To enable it, set `OPEN_LIBRARY_USER_AGENT` in the compose file to a valid identification string:

```
OPEN_LIBRARY_USER_AGENT=MyAppName/1.0 (myemail@example.com)
```

Per OL's API policy, the string must identify your application and include a contact email so they
can reach you if your bot misbehaves. Do **not** use the literal placeholder above — replace both
the app name and email with real values.

When the env var is absent or the placeholder text is left unchanged, the swap-detection step in
`verify_and_update_id3_tags()` is silently skipped and author/narrator are taken from the raw ID3
scores only (which can be wrong for music-convention-tagged files).

## Docker build workflow

**Site-specific compose files are not in this repo.** On Phantom they live in
`/etc/docker/auto-m4b-host/` and are symlinked as `docker-compose.auto-m4b.yml` /
`docker-compose.auto-m4b-nvidia.yml` inside the clone. Public consumers should copy
`docker-compose.template.yml`. Do not commit personal compose files here.

The Dockerfile is split into two layers to keep dev rebuilds fast:

- **`Dockerfile.base`** — all heavy dependencies: ffmpeg, Poetry packages, spaCy model, NLTK corpora. Produces `auto-m4b-base:latest`. Only needs rebuilding when `pyproject.toml`, `poetry.lock`, or system deps change.
- **`Dockerfile`** — just `COPY src/` on top of `auto-m4b-base:latest`. Rebuilds in seconds.

```bash
# Build (or rebuild) the base — only needed when deps change:
dr build auto-m4b-base       # or: docker compose -f docker-compose.auto-m4b.yml --profile base build auto-m4b-base

# Normal dev rebuild (fast — only re-copies src/):
# Phantom runs the NVIDIA variant, so always build and start auto-m4b:nvidia
dr build auto-m4b:nvidia     # or: docker compose -f docker-compose.auto-m4b-nvidia.yml build auto-m4b
```

## Container variants

Two mutually exclusive variants are available. Starting one automatically stops and removes the other:

```bash
dr start auto-m4b          # standard (CPU-only ffmpeg)
dr start auto-m4b:nvidia   # NVIDIA GPU-accelerated ffmpeg  ← used on Phantom
```

Both use `container_name: auto-m4b`, so `docker logs -f auto-m4b` works regardless of which variant is running.

## Host-mounted paths (Phantom → Ragnarok SMB share)

The container works on a Ragnarok SMB share that is mounted on Phantom at `/mnt/ragnarok`. Inside the container the share appears under `/media`.

| Purpose                 | Host path (Phantom)                                        | Container path                                |
| ----------------------- | ---------------------------------------------------------- | --------------------------------------------- |
| Inbox (drop books here) | `/mnt/ragnarok/media/Books/Audiobooks/#auto-m4b/inbox`     | `/media/Books/Audiobooks/#auto-m4b/inbox`     |
| Converted output        | `/mnt/ragnarok/media/Books/Audiobooks/#auto-m4b/converted` | `/media/Books/Audiobooks/#auto-m4b/converted` |
| Archive                 | `/mnt/ragnarok/media/Books/Audiobooks/#auto-m4b/archive`   | `/media/Books/Audiobooks/#auto-m4b/archive`   |
| Backup                  | `/mnt/ragnarok/media/Books/Audiobooks/#auto-m4b/backup`    | `/media/Books/Audiobooks/#auto-m4b/backup`    |
| Working/temp            | `/tmp/auto-m4b` (container-local)                          | `/tmp/auto-m4b`                               |

When testing against live books, drop or inspect files in the host-side inbox path above.

## fix_metadata CLI (retag without re-encode)

Use this when converted (or `#plex`) books have wrong tags/filenames and you do **not** want to reconvert. Full flag/env reference: **[docs/fix-metadata.md](docs/fix-metadata.md)**.

```bash
# Host (Phantom) — am4b exports CLI_* paths + OPEN_LIBRARY_USER_AGENT
am4b fix -i "George, Margaret"
am4b fix --apply --ol OL45804W "George, Margaret/Elizabeth I (2011)"

# Or via Poetry
poetry run python -m src.fix_metadata -h
```

Notes for agents:

- Default is dry-run; `-i` prompts per book; `--apply` writes.
- Relative paths resolve under `CLI_CONVERTED_FOLDER`; no args → entire converted tree (auto-recursive).
- Source tags come from archive mirror (or `-s`). Multi-part archives use GCS + part strippers — titles should not keep `Part 1`.
- OL match/link is shown when `OPEN_LIBRARY_USER_AGENT` is set; `--ol` / interactive `o` force a work/edition onto a **single** book.
- Do not rebuild the live container solely for CLI-only changes; the host Poetry tree is enough for `am4b fix`.

## Key architecture notes for development

### Watchdog (`src/auto_m4b.py`)

- Uses `watchdog` `PollingObserver` on the inbox directory.
- The `_InboxHandler` filters out files whose names start with `"auto-m4b."` or end with `".log"` — this prevents auto-m4b's own per-book log files from creating a re-trigger loop.
- The observer sets a `threading.Event` (`dirty`) which the main loop waits on; it does not loop on a timer.

### InboxState (`src/lib/inbox_state.py`)

- `matched_ok_books` — books that are ready to process (not already processed or failed).
- `set_processed(book)` — marks a book as done without counting it as a failure. Call this whenever a book is intentionally skipped (e.g. already converted), otherwise it will be re-queued every loop.
- `inbox_hash_changed` — detects whether the inbox contents have changed since the last run. If books are present but the hash hasn't changed (e.g. due to a scanner race), this is overridden to `True` so the processing banner still fires.

### BooksTree (`src/lib/books_tree/books_tree.py`)

- `determine_structure` runs in multiple passes. Pass #3 adds `flat`/`nested`/`single` structures.
- **Guard**: Pass #3 skips a dir if it already has a "strong" structure (`series_parent`, `series_book`, `multi_book`, `unknown`). This prevents those classifications from being overwritten by weaker ones, while still allowing `flat`, `nested`, and `single` to coexist on the same dir.
- `score_series_parent` in `scorers.py` returns `0.85` for single-child series parents where the child's name starts with a digit — required to correctly classify e.g. "John Grisham / 1 - The Firm" directory layouts without mangling files.

### ok_to_overwrite (`src/lib/run.py`)

- When a book is skipped because an already-converted copy exists in the archive or converted dir, `InboxState().set_processed(book)` is called immediately. Without this, the book would be re-evaluated (and spew "Skipping..." notices) on every watchdog trigger.

## Known flaky tests

Three metadata-related tests fail intermittently when the full suite runs but pass in isolation. They are **not** caused by recent changes and should be treated as pre-existing flakiness:

- `test_verify_tags_after_convert[touch_of_frost__flat_mp3-expected_dict0]`
- `test_verify_tags_after_convert[house_on_the_cliff__flat_mp3-expected_dict2]`
- `test_extract_path_info[Trenton Lee Stewart-fs_author-benedict_society__mp3]`

When all other tests pass and only these three fail, it is safe to proceed.

## Conventions

- Match existing style: Black (120 cols), Ruff, isort profile black.
- Keep changes focused; tests live beside the code they exercise under `src/tests/`.
- Only commit when explicitly asked.
