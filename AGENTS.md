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

| Path | Purpose |
|------|---------|
| `src/` | Application code (`src/lib/`, `src/auto_m4b.py`) |
| `src/tests/` | Pytest suite |
| `src/tests/helpers/` | Fixtures, mocks (`pytest_dumps.py`, `pytest_fixtures.py`) |
| `src/tests/tmp/` | Ephemeral test dirs (inbox, converted, etc.) — created by fixtures |
| `src/tests/fixtures/` | Static test audio/fixture files |

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

## Branching strategy

The author uses a `dev` branch for small, ongoing feature work and incremental fixes. Most day-to-day development lands in `dev` first and is merged to `main` from there, avoiding the overhead of long-lived feature branches for minor changes.

Larger, independent features or fixes that need isolation (e.g. the style of PRs #3–5) still get their own branches off `main`. But as a rule: if it's a small improvement that doesn't need a separate review context, it goes in `dev`.

Agents should not create new branches for small changes unless the author asks. When in doubt, ask.

## Conventions

- Match existing style: Black (120 cols), Ruff, isort profile black.
- Keep changes focused; tests live beside the code they exercise under `src/tests/`.
- Only commit when explicitly asked.
