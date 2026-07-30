# fix_metadata — retag converted audiobooks (no re-encode)

Standalone CLI for correcting ID3 tags, `.m4b` filenames, and companion quality `.txt` files **after** conversion. It does not re-encode audio.

Primary module: [`src/fix_metadata.py`](../src/fix_metadata.py).

## When to use it

- Converted books picked up the wrong author/title (e.g. bad Open Library early match).
- Multi-part archive sources left `Part 1` in the title/filename.
- You want an interactive review pass over `converted/` (or a `#plex` tree) without running the watchdog converter.

Prefer this over re-dropping books into the inbox when only metadata/filenames are wrong.

## Quick start

```bash
# From the repo (Poetry venv)
poetry run python -m src.fix_metadata -h
poetry run python -m src.fix_metadata -i "George, Margaret"
poetry run python -m src.fix_metadata --apply "George, Margaret/Elizabeth I (2011)"
```

Default is **dry-run**. Write with `--apply`, or confirm each book with `-i` / `--interactive`.

## Path resolution

| Input | Behavior |
| ----- | -------- |
| No paths | Scan `CLI_CONVERTED_FOLDER` / `CONVERTED_FOLDER` (auto-recursive) |
| Relative (`Author` or `Author/Book`) | Resolve under converted |
| Absolute under converted | Same; source from mirrored archive path |
| Absolute elsewhere (e.g. `#plex`) | Source audio must sit beside the `.m4b`, or pass `-s` |

### Host vs container env

Compose uses `INBOX_FOLDER` / `CONVERTED_FOLDER` / `ARCHIVE_FOLDER` (container `/media/...`). On the host CLI, set the mirrors:

```bash
export CLI_CONVERTED_FOLDER=/mnt/ragnarok/media/Books/Audiobooks/#auto-m4b/converted
export CLI_ARCHIVE_FOLDER=/mnt/ragnarok/media/Books/Audiobooks/#auto-m4b/archive
export CLI_INBOX_FOLDER=/mnt/ragnarok/media/Books/Audiobooks/#auto-m4b/inbox
export OPEN_LIBRARY_USER_AGENT='auto-m4b/1.0 (you@example.com)'
```

Log file is always `{converted}/auto-m4b.log` (no separate env var).

`OPEN_LIBRARY_USER_AGENT` uses the same format as the converter (see README Open Library setup).

## Recursion

- No audio in a dir, but nested book dirs → **auto-recursive** (author / converted root).
- Audio here **and** child book dirs → process this dir only; warn unless `-r` / `--recursive`.

## Source reconstruction

Order of preference:

1. `-s` / `--source` — originals root; relative nesting must match the converted scope.
2. Source audio beside the `.m4b`.
3. Under known converted → mirror into `archive/` (`archive / relative_to(converted)`).
4. Otherwise → fail that book with a clear “no source” message.

Multi-file archives use **greatest common string** across titles/filenames, then the same part/disc strippers as conversion (`clean_string`), so `Elizabeth I, Part 1/2/3` becomes `Elizabeth I`.

## Open Library

When `OPEN_LIBRARY_USER_AGENT` is set, proposals show an OL match + link (**display only** by default — does not overwrite tags).

| Mode | Flag / key | Behavior |
| ---- | ---------- | -------- |
| Auto | (default) | Lookup by desired title/author; show link |
| Skip auto | `--no-ol` | No automatic lookup |
| Force (CLI) | `--ol URL_OR_ID` | Single-book only; applies OL title/author/year |
| Force (interactive) | `o` at the prompt | Paste URL or `OL…W` / `OL…M`, re-show proposal |

Accepted refs: full `openlibrary.org/works/…` or `/books/…` URLs, or bare `OL123W` / `OL123M`.

Interactive prompt (multi-line menu):

- `y` — apply this book  
- `s` — skip (default)  
- `o` — then paste an Open Library URL or id (e.g. `OL45804W`); proposal is rebuilt  
- `q` — quit  

Ctrl+C quits cleanly (no traceback).

## Useful flags

```text
-i, --interactive   Prompt per book before writing (implies apply)
--apply             Write without prompting
-r, --recursive     Include child book dirs when the path itself is also a book
-s, --source PATH   Unconverted originals root
--ol URL_OR_ID      Force Open Library work/edition (one book)
--no-ol             Skip automatic OL lookup
--ignore GLOB       Skip matching filenames (repeatable)
--debug             Verbose debug
```

## Tests

```bash
poetry run python -m pytest src/tests/test_fix_metadata.py -q
```
