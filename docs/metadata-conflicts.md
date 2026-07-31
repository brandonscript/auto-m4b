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
| **Dates (±1 / consensus)** | Scorer earlier-of(id3, fs); OL may overwrite; **no** `_apply_date_consensus` in verify yet. | Folder ±1 near-tie; 2-of-3 consensus after OL. | `pending_review` |
| **Stem (GCS vs title)** | Prefers resolved **title** (or passthrough). | Prefers source **GCS**, keep if matches title. | `pending_review` |
| **OL edition enrich** | Work title only (no edition subtitle join). | Edition base+subtitle when locally attested. | `pending_review` |
| **Folder priors** | spaCy inbox basename. | `#plex` / parent-author / loose author-dir / cli-root clamp. | `pending_review` |
| **OL auto-write** | Auto-applies OL on extract + verify. | Display-only unless forced. | `pending_review` (intentional product fork for now) |

## Non-minimalist tests (`@pytest.mark.non_minimalist`)

Tagged in `test_metadata_plan.py` for Phase 4 triage:

- `test_plan_fix_non_minimalist_keeps_full_source_stem`
- `test_plan_fix_never_renames_to_author_even_if_gcs_is_author`
- `test_plan_fix_keeps_searcher_dash_stem_not_glued_archive[False]`

**Interim decision:** keep as **CLI-only** coverage of `--no-minimalist` / `minimalist=False`. Convert does not run these paths. No mass rewrite.

## Still needs operator decision

1. Wire `_apply_date_consensus` into convert verify?
2. Unify rename stem on GCS vs title (or keep `stem_source` modes)?
3. Bring edition-subtitle enrichment into convert OL path?
4. Use shared folder priors when inbox/converted layout is `#plex`-shaped?
5. Keep OL auto-write on convert forever, or move toward display-only + explicit accept?

## Phase 3 notes

- Colon + always-minimalist are **post-selection** transforms; convert selection is still OCR / MetadataScore / OL-early (not full `plan_fix`).
- `minimalist_title` drops unbalanced `(Series, Book N)` paren tails.
- `test_parse_combo_id3_tags[…expected3]` can fail when `OPEN_LIBRARY_USER_AGENT` is set (OL early overwrites Album Artist narrator) — tracked under **OL auto-write**.
