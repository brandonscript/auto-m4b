# fix_metadata — retag converted audiobooks (no re-encode)

Standalone CLI for correcting ID3 tags, `.m4b` filenames, and companion quality `.txt` files **after** conversion. It does not re-encode audio.

- CLI / UX: [`src/fix_metadata.py`](../src/fix_metadata.py)
- Shared planner (also used by convert): [`src/lib/metadata/`](../src/lib/metadata/)
- Convert ↔ shared divergences (manual review): [`metadata-conflicts.md`](metadata-conflicts.md)

Convert always runs **minimalist** title cleanup. The CLI still honors `--minimalist` / `--no-minimalist` / `CLI_MINIMALIST`.

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
export CLI_MINIMALIST=1   # optional; prefer core titles (see Minimalist titles)
export OPEN_LIBRARY_USER_AGENT='auto-m4b/1.0 (you@example.com)'
```

Log file is always `{converted}/auto-m4b.log` (no separate env var).

`OPEN_LIBRARY_USER_AGENT` uses the same format as the converter (see README Open Library setup).

## Recursion

- No audio in a dir, but nested book dirs → **auto-recursive** (author / converted root).
- Audio here **and** child book dirs → process this dir only; warn unless `-r` / `--recursive`.

Author hints never climb above `CLI_CONVERTED_FOLDER` (or archive/inbox): if the book dir is a **direct child** of converted (`converted/Author/*.m4b` with no nested book folder), the folder name is treated as the author and the title comes from id3 / filename — not from the converted root’s basename.

Rename stems: strip series/`NN - ` prefixes as usual, but if the original source or current `.m4b` stem already ended with `(YYYY)`, keep that year on the filename (years are optional, but never drop one that was already there).

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
| Auto | (default) | Lookup by desired title/author; show link; may enrich proposed title with edition subtitle when local naming attests it |
| Skip auto | `--no-ol` | No automatic lookup |
| Force (CLI) | `--ol URL_OR_ID` | Single-book only; applies OL title/author/year |
| Force (interactive) | `o` at the prompt | Paste URL or `OL…W` / `OL…M`, re-show proposal |
| Accept low-confidence | `m` at the prompt | Only when OL shows a low-confidence candidate |
| Edit proposed values | `e` at the prompt | Edit Title, Author, Date, Narrator, and filename one at a time |

Auto lookup uses structured `title=` first, then free-text `q=` if that misses (edition subtitles / alt titles). **Dual title query:** every auto lookup always tries the full desired title **and** the minimalist-stripped core (even when minimalist mode is off), so marketing junk like *The Lady Helen Trilogy, Book 1 (Unabridged)* does not block a match on *The Dark Days Club*. When the work title scores below 0.5 but author confidence is solid (≥ 0.5, or the author was resolved onto the query), editions are fetched and titles/subtitles are scored so marketing titles (e.g. *Eon: Dragoneye Reborn*) can promote the match. Score ≥ 0.5 → confident match (display only for author/date); 0.15–0.5 → low-confidence (amber; use `m` to adopt). Below that → no match.

When an edition subtitle is strongly attested in local naming (folder / source content tokens), the **proposed id3 title** becomes `Base: Subtitle` using the edition/work base closest to local naming (e.g. *Eon: Dragoneye Reborn*, *Eona: The Last Dragoneye*) — never stacking two marketing subtitles, and never replacing a local/US form with a regional alternate work title (e.g. *The Two Pearls of Wisdom*). Id3 `Title: Subtitle` prefers colon; filenames map `:` → ` - ` via `safe_filename`; folder dashes are not an id3 signal (dash only when Open Library’s title itself uses that form).

Dry-run / non-interactive `--apply` report the count of low-confidence OL matches in the mode banner but never auto-adopt low-confidence OL author/date — only interactive `m` or forced `--ol` / `o` applies those. Session end prints light grey `Done` and mint `✓` (matching per-book Done); exit code is still non-zero when any source lookups failed.

Accepted refs: full `openlibrary.org/works/…` or `/books/…` URLs, or bare `OL123W` / `OL123M`.

Interactive prompt:

- `y` — yes  
- `s` — skip (default)  
- `m` — use this openlibrary match (only when low-confidence)  
- `o` — provide an Open Library id or url  
- `e` — edit the proposed Title, Author, Date, Narrator, and filename
- `c` — cancel a pending manual Open Library lookup
- `q` — quit  

Edit mode uses the proposed values as defaults. Press Enter to keep a value,
enter `_` to clear a metadata field, or enter a replacement filename. A
filename cannot be cleared. When readline is available, values are pre-filled
and editable; otherwise the prompts start blank and Enter keeps the proposal.
After `o`, the lookup is provisional until `y` confirms it; `e` can revise it
and `c` restores the proposal from before the lookup.

Review layout: nested Reviewing book box, then Filesystem / id3 tags / optional Open Library blocks (mint = correct, amber = wrong/low-confidence OL, grey = missing, light grey = already correct), then a yellow Proposed fixes rail. Session-level Open Library skip/disable notice prints once under auto-recursive.

Ctrl+C quits cleanly (no traceback).

## Dates / years

Filesystem year comes from the trailing `(YYYY)` in the book folder and/or source/current filename. Without Open Library, the older available filesystem/ID3 year wins, including one-year near ties. With Open Library, an exact two-of-three match wins; a near pair wins with the older year when the third is at least two years away; otherwise a high-confidence all-divergent match uses OL and low-confidence all-divergent results fall back to filesystem versus ID3. Forced OL (`--ol` / `o` / `m`) still applies OL tags directly.

Filesystem / id3 / OL date colors are judged against **desired** date (what would be written): match = mint, mismatch = amber. When FS is wrong and id3 is right, id3 is mint (not grey) so the pair never reads as grey+amber.

## Minimalist titles

Set `CLI_MINIMALIST=1` (or pass `--minimalist`) to prefer core book titles and strip series / Book N / `(Unabridged)` marketing suffixes from proposed id3 titles and rename stems. `--no-minimalist` disables the mode even when the env var is set. Minimalist (and title cleanup generally) is author-aware: a leading `Author - ` prefix is stripped before series cleanup so author dashes cannot collapse a stem to the author alone. Rename stems never become author-only — if cleanup fails, the source filename or current `.m4b` name is kept.

Example: source title *The Dark Days Club: The Lady Helen Trilogy, Book 1 (Unabridged)* → desired title *The Dark Days Club*. Substantive subtitles such as *Eona: The Last Dragoneye* are left alone.

Open Library auto lookup always runs the dual full + stripped query described above, regardless of this flag.

## Useful flags

```text
-i, --interactive   Prompt per book before writing (implies apply)
--apply             Write without prompting
-r, --recursive     Include child book dirs when the path itself is also a book
-s, --source PATH   Unconverted originals root
-o, --ol URL_OR_ID  Force Open Library work/edition (one book)
--no-ol             Skip automatic OL lookup
--minimalist        Prefer core titles; strip series/Book N/(Unabridged) (or CLI_MINIMALIST=1)
--no-minimalist     Disable minimalist even if CLI_MINIMALIST is set
--ignore GLOB       Skip matching filenames (repeatable)
--debug             Verbose debug
```

Interactive mode and `-o`/`--ol` can retag from the converted folder/m4b alone when archive source files are missing (still pass `-s` when you have them). Dry-run / non-interactive `--apply` without `-o` still require a resolvable source.

Large author folders: planning shows an updating `Planning i/N · folder` line first. Interactive keeps that pass local, then runs Open Library on those local candidates (so date consensus can clear no-ops) and only then prints the mode banner — e.g. `Interactive // 1 of 7 needs fixing · No missing source files` or `Interactive // No books need fixing`.

## Tests

```bash
poetry run python -m pytest src/tests/test_fix_metadata.py src/tests/test_cleaners_minimalist.py -q
```
