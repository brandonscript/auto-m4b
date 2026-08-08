# Metadata conflicts — convert vs shared planner

Inventory of behavioral divergences between **convert**
(`id3_utils.extract_metadata` / `verify_and_update_id3_tags`,
`audiobook.output_filename_stem`, `parsers.extract_path_info`) and the
**shared planner** (`src/lib/metadata/`).

Statuses:

- `adopt_shared` — both sides use shared behavior (or convert post-transform)
- `keep_convert_adapter` — intentional convert-only difference until product says otherwise
- `mode_flag` — CLI flag / convert fixed mode
- `pending_review` — needs an explicit product decision (do not auto-pick)

Contract tests: [`src/tests/test_metadata_divergence.py`](../src/tests/test_metadata_divergence.py).
Domain tests: [`src/tests/test_metadata_plan.py`](../src/tests/test_metadata_plan.py).

| Concern | Convert behavior | Shared / fix_metadata behavior | Status |
| --- | --- | --- | --- |
| **Colon (id3 subtitle)** | `_finalize_convert_title` → `id3_prefer_colon_separator`. Filenames: `safe_filename` still maps `: ` → ` - `. | Same colon preference in `_pick_desired`. | `adopt_shared` |
| **Minimalist (id3 titles)** | Convert **always** `minimalist_title` on resolved titles via `_finalize_convert_title`. | CLI: `minimalist` / `CLI_MINIMALIST` / `--no-minimalist`. | `adopt_shared` (convert) + `mode_flag` (CLI) |
| **Minimalist (passthrough stems)** | Single-file m4b/m4a/aac **passthrough** stems skip minimalist strip (keeps Book N in filename). | CLI rename stems are minimalist-cleaned when mode on. | `keep_convert_adapter` |
| **Stem refuse author-only** | `_usable_rename_stem` / `is_author_only_name`. | Same helpers. | `adopt_shared` |
| **Dates (±1 / consensus)** | Shared resolver uses FS folder/filename + ID3; OL exact-majority, near-pair, and confidence rules. | Same resolver. | `adopt_shared` |
| **Stem (GCS vs title)** | `CLEANUP_FILENAMES=0` keeps trusted GCS; opt-in cleanup rejects generic tracks and uses title/dir context. | Shared GCS with the same generic-track safeguards. | `adopt_shared` |
| **OL edition enrich** | Shared edition base+subtitle enrichment when `OPEN_LIBRARY_USER_AGENT` is set. | Edition base+subtitle when locally attested. | `adopt_shared` |
| **Folder priors** | Pipeline roots are clamped using configured paths. | `#plex` / parent-author / loose author-dir / cli-root clamp. | `adopt_shared` |
| **OL auto-write** | Auto-applies shared OL title/author/date when the user agent is configured. | Display-only unless forced. | `keep_convert_adapter` |
| **Goodreads selection** | When enabled, queries both providers and prefers a confident Goodreads result; Open Library remains fallback. | Queries both providers and displays comparison; forced `--goodreads` applies the selected book. | `adopt_shared` |
| **Provider disagreements** | Reports Goodreads/Open Library field conflicts and continues with Goodreads selected. | Reports field conflicts without blocking a dry-run or automatic plan. | `adopt_shared` |

## Non-minimalist tests (`@pytest.mark.non_minimalist`)

Tagged in `test_metadata_plan.py` for Phase 4 triage:

- `test_plan_fix_non_minimalist_keeps_full_source_stem`
- `test_plan_fix_never_renames_to_author_even_if_gcs_is_author`
- `test_plan_fix_keeps_searcher_dash_stem_not_glued_archive[False]`

**Interim decision:** keep as **CLI-only** coverage of `--no-minimalist` / `minimalist=False`. Convert does not run these paths. No mass rewrite.

## Locked implementation notes

- `CLEANUP_FILENAMES=0` is the safe default: tags are updated without metadata-driven renames.
- `CLEANUP_FILENAMES=1` handles useful flat stems such as `BookName-cd1`, rejects generic stems such as
  `Track01`, and combines a sensible book directory with a useful file fragment when both are needed.
- Single-file passthrough keeps its original filename while tags may still be updated.

## Phase 3 notes

- Colon + always-minimalist are **post-selection** transforms; convert selection is still OCR / MetadataScore / OL-early (not full `plan_fix`).
- `minimalist_title` drops unbalanced `(Series, Book N)` paren tails.
- `test_parse_combo_id3_tags[…expected3]` can fail when `OPEN_LIBRARY_USER_AGENT` is set (OL early overwrites Album Artist narrator) — tracked under **OL auto-write**.

## Phase 6 notes (verify planner)

- Post-build `verify_and_update_id3_tags` calls shared `plan_fix` only when early
  GR/OL results are missing or no longer match `book.*`. When early providers still
  match, verify reuses the stash and skips `plan_fix` / re-lookups (no edition enrich
  in that short-circuit path).
- Pre-convert `extract_metadata` selection is unchanged (OCR / MetadataScore / OL-early).
- Convert still auto-applies desired fields after the plan (shared auto OL remains
  display-only unless `ol_ref` forces attach). Passthrough / basename stem adapters
  stay convert-side.
- If `plan_fix` raises, verify falls back to attach-only (`FixPlan` + `_attach_open_library`).

