"""Plan orchestration: build a FixPlan for one book directory."""

from __future__ import annotations

import re
from pathlib import Path

from rapidfuzz import fuzz

from src.lib.cleaners import clean_string, minimalist_title, title_case_ol_title
from src.lib.fs_utils import ensure_audio_ext, safe_filename
from src.lib.metadata.models import CliPaths, FixPlan, SourceResolutionError, TagSnapshot
from src.lib.metadata.ol_attach import _attach_open_library
from src.lib.metadata.pick import _filesystem_year, _pick_desired
from src.lib.metadata.providers import MetadataComparison, lookup_metadata
from src.lib.metadata.sources import (
    _QUALITY_TXT,
    _find_desc_txt,
    _find_source_and_m4b,
    filename_gcs_context,
    _source_audio_file,
    resolve_source_dir,
    source_common_filename,
    source_common_title,
    source_files_display,
)
from src.lib.metadata.stem import (
    _stem_matches_book_title,
    _usable_rename_stem,
    is_trailing_article_variant,
    near_match_ol_filename_stem,
    preserve_original_year_in_stem,
)
from src.lib.metadata.apply import _desc_needs_rewrite


def _apply_cleanup_filename(plan: FixPlan, local_title: str) -> None:
    """Prefer a near-identical Open Library title for cleaned filenames."""
    from src.lib.config import cfg

    if not cfg.CLEANUP_FILENAMES:
        return

    article_variant = is_trailing_article_variant(local_title, plan.ol_title)
    numeric_local_title = None
    if plan.ol_title:
        from src.lib.ol_lookup import _strip_boundary_number, _title_sim

        numeric_local_title = _strip_boundary_number(local_title)
        numeric_fallback = bool(
            numeric_local_title
            and _title_sim(numeric_local_title, plan.ol_title)[0] >= 0.9
        )
    else:
        numeric_fallback = False
    if article_variant:
        canonical_title = title_case_ol_title(plan.ol_title)
        if plan.desired_title != canonical_title:
            plan.desired_title = canonical_title
            plan.desired_album = canonical_title
            plan.reasons.append(
                f"use Open Library article ordering for tags "
                f"{local_title!r} → {canonical_title!r}"
            )
        cleanup_stem = preserve_original_year_in_stem(
            safe_filename(title_case_ol_title(local_title)),
            plan.desired_stem,
            plan.m4b.stem,
        )
    elif numeric_fallback:
        def _filename_has_boundary_number(value: str) -> bool:
            stem = Path(value).stem
            return bool(
                re.match(r"^\s*#?\d+\b", stem)
                or re.search(r"(?:^|[\s._-])#?\d+\s*[\])]?$", stem)
            )

        original_filename_has_number = any(
            _filename_has_boundary_number(value)
            for value in (plan.m4b.stem, plan.fs_files)
            if value
        )
        if original_filename_has_number:
            cleanup_stem = safe_filename(title_case_ol_title(local_title))
        else:
            cleanup_stem = near_match_ol_filename_stem(
                plan.m4b.stem,
                plan.ol_title,
                plan.m4b.stem,
            )
    else:
        cleanup_stem = near_match_ol_filename_stem(
            local_title,
            plan.ol_title,
            plan.desired_stem,
            plan.m4b.stem,
        )
    if not cleanup_stem or cleanup_stem == plan.desired_stem:
        return

    plan.reasons.append(
        f"cleanup filename from near-match Open Library title "
        f"{plan.desired_stem!r} → {cleanup_stem!r}"
    )
    plan.desired_stem = cleanup_stem
    plan.rename_m4b_to = (
        plan.m4b.with_name(ensure_audio_ext(cleanup_stem, ".m4b"))
        if plan.m4b.stem != cleanup_stem
        else None
    )
    if plan.desc_txt and plan.rename_m4b_to:
        quality_match = _QUALITY_TXT.match(plan.desc_txt.name)
        suffix = (
            plan.desc_txt.name[len(quality_match.group(1)) :]
            if quality_match
            else ".txt"
        )
        plan.rename_desc_to = plan.desc_txt.with_name(f"{cleanup_stem}{suffix}")


def _attach_provider_comparison(
    plan: FixPlan,
    comparison: MetadataComparison,
    *,
    apply_goodreads: bool = False,
    minimalist: bool = False,
) -> None:
    """Attach both provider results while preserving OL's existing enrichments."""
    goodreads = comparison.candidates.get("goodreads")
    open_library = comparison.candidates.get("openlibrary")
    if goodreads:
        plan.goodreads_title = goodreads.title
        plan.goodreads_author = goodreads.author
        plan.goodreads_year = goodreads.year
        plan.goodreads_key = goodreads.ref
        plan.goodreads_url = goodreads.url
        plan.goodreads_score = goodreads.score
        plan.goodreads_status = goodreads.status
    if open_library:
        plan.ol_title = open_library.title
        plan.ol_author = open_library.author
        plan.ol_year = open_library.year
        plan.ol_key = open_library.ref
        plan.ol_url = open_library.url
        plan.ol_score = open_library.score
        plan.ol_status = open_library.status
    plan.provider_conflicts.extend(comparison.conflicts)
    for conflict in comparison.conflicts:
        plan.reasons.append(f"provider disagreement ({conflict})")

    if goodreads and open_library and goodreads.status in ("match", "forced") and open_library.status == "match":
        local_titles = [plan.fs_title.strip(), plan.current.title.strip()]
        provider_titles = [goodreads.title.strip(), open_library.title.strip()]
        if all(local_titles) and all(provider_titles):
            local_similarity = fuzz.token_set_ratio(*local_titles) / 100
            provider_similarity = fuzz.token_set_ratio(*provider_titles) / 100
            local_provider_similarity = max(
                fuzz.token_set_ratio(local_titles[0], provider_titles[0]),
                fuzz.token_set_ratio(local_titles[0], provider_titles[1]),
                fuzz.partial_ratio(local_titles[0], provider_titles[0]),
                fuzz.partial_ratio(local_titles[0], provider_titles[1]),
            ) / 100
            if (
                local_similarity >= 0.95
                and provider_similarity >= 0.85
                and local_provider_similarity >= 0.65
                and local_titles[0].casefold() != provider_titles[0].casefold()
            ):
                plan.desired_title = goodreads.title
                plan.desired_album = goodreads.title
                plan.reasons.append("resolve 2–2 title tie with Goodreads")

        provider_title_similarity = max(
            fuzz.ratio(goodreads.title, open_library.title),
            fuzz.token_set_ratio(goodreads.title, open_library.title),
        ) / 100
        if (
            provider_title_similarity >= 0.85
            and goodreads.title
            and (plan.desired_title or "").strip().casefold()
            != goodreads.title.strip().casefold()
        ):
            plan.desired_title = goodreads.title
            plan.desired_album = goodreads.title
            plan.reasons.append("use agreed Goodreads/Open Library title")

    selected = comparison.selected
    if not selected:
        return
    plan.selected_provider = selected.provider
    if selected.provider == "openlibrary":
        _attach_open_library(plan, apply_ol_tags=False, minimalist=minimalist)
        return
    if selected.provider != "goodreads" or not apply_goodreads:
        if selected.provider == "goodreads" and selected.status in ("match", "forced") and selected.year:
            plan.desired_date = selected.year
            plan.reasons.append("prefer Goodreads publication year")
        return

    if selected.year:
        plan.desired_date = selected.year
    if selected.title:
        plan.desired_title = selected.title
        plan.desired_album = selected.title
        plan.reasons.append("use Goodreads title (forced)")
    if selected.author:
        plan.desired_author = selected.author
        plan.reasons.append("use Goodreads author (forced)")


def plan_fix(
    book_dir: Path,
    ignore_globs: list[str] | None = None,
    *,
    cli: CliPaths | None = None,
    scope_root: Path | None = None,
    source_root: Path | None = None,
    debug: bool = False,
    require_source: bool = True,
    ol_ref: str | None = None,
    lookup_ol: bool = True,
    goodreads_ref: str | None = None,
    lookup_goodreads: bool | None = None,
    minimalist: bool = False,
) -> FixPlan | None:
    """Build a fix plan for one book dir.

    Raises SourceResolutionError when ``require_source`` and no source can be resolved.
    Returns None when the book needs no changes (unless ``ol_ref`` forces a rewrite).
    """
    ignore_globs = ignore_globs or []
    cli = cli or CliPaths()
    book_dir = book_dir.resolve()
    scope_root = (scope_root or book_dir).resolve()

    if not book_dir.is_dir():
        return None
    beside_source, m4b = _find_source_and_m4b(book_dir, ignore_globs)
    if not m4b:
        return None

    source_path: Path | None = None
    source_snap: TagSnapshot | None = None
    reasons_prefix: str | None = None
    common_title_reason: str = ""
    filename_stem: str = ""
    fs_files: str = ""

    if require_source:
        src_dir = resolve_source_dir(
            book_dir,
            beside_source=beside_source,
            cli=cli,
            scope_root=scope_root,
            source_root=source_root,
            debug=debug,
        )
        filename_stem = source_common_filename(src_dir, ignore_globs)
        fs_files = source_files_display(src_dir, ignore_globs)
        if beside_source and src_dir == book_dir:
            source_path = beside_source
            source_snap = TagSnapshot.from_file(beside_source)
            # Still strip Part N from a lone beside-m4b source title
            cleaned = clean_string(source_snap.title or "").strip(" -_,.")
            if cleaned and cleaned != source_snap.title:
                source_snap.title = cleaned
                common_title_reason = "title stripped part/disc markers"
            if not filename_stem:
                filename_stem = clean_string(beside_source.stem).strip(" -_,.")
            if not fs_files:
                fs_files = beside_source.name
        else:
            source_path = _source_audio_file(src_dir, ignore_globs)
            if source_path is None:
                raise SourceResolutionError(book_dir, f"no audio files in source dir {src_dir}")
            if src_dir != book_dir:
                reasons_prefix = f"source from {src_dir}"
            source_snap = TagSnapshot.from_file(source_path)
            common_title, common_title_reason = source_common_title(src_dir, ignore_globs)
            if common_title:
                source_snap.title = common_title
                # Prefer common album too when titles were part-split
                if not source_snap.album or fuzz.token_set_ratio(source_snap.album, common_title) / 100 < 0.5:
                    source_snap.album = common_title
    elif beside_source:
        source_path = beside_source
        source_snap = TagSnapshot.from_file(beside_source)
        filename_stem = clean_string(beside_source.stem).strip(" -_,.")
        fs_files = beside_source.name

    current = TagSnapshot.from_file(m4b)
    title, author, album, date, narrator, reasons = _pick_desired(
        book_dir, source_snap, current, minimalist=minimalist, cli=cli
    )
    # Local determinations (folder + source) before any Open Library override.
    # fs_date includes folder and source/current filename years, not the picked date.
    folder_date = _filesystem_year(book_dir, source_snap, current)
    fs_title, fs_author, fs_date, fs_narrator = (
        title,
        author,
        folder_date,
        narrator,
    )
    if reasons_prefix:
        reasons.insert(0, reasons_prefix)
    if common_title_reason:
        reasons.insert(0 if not reasons_prefix else 1, common_title_reason)

    # Rename stem = part-stripped GCS of source filenames (not the ID3 title).
    # Never emit an author-only stem — prefer the original source filename, then
    # title, then the current m4b name (minimalist or not).
    raw_stem = filename_gcs_context(filename_stem, book_dir, title) or title or m4b.stem
    stem = safe_filename(raw_stem) if raw_stem else ""
    title_stem = safe_filename(title) if title else ""
    original_stem = safe_filename(filename_stem) if filename_stem else ""

    if minimalist and raw_stem:
        cleaned = minimalist_title(raw_stem, author=author)
        cleaned = safe_filename(cleaned) if cleaned else ""
        if _usable_rename_stem(cleaned, author):
            if cleaned != stem:
                reasons.append(f"minimalist rename stem {stem!r} → {cleaned!r}")
            stem = cleaned
        elif _usable_rename_stem(title_stem, author):
            if title_stem != stem:
                reasons.append(
                    f"minimalist rename stem rejected {cleaned or stem!r}; "
                    f"using title {title_stem!r}"
                )
            stem = title_stem
        elif _usable_rename_stem(original_stem, author):
            if original_stem != stem:
                reasons.append(
                    f"minimalist rename stem rejected {cleaned or stem!r}; "
                    f"keeping source {original_stem!r}"
                )
            stem = original_stem
        else:
            if m4b.stem != stem:
                reasons.append(
                    f"minimalist rename stem rejected {cleaned or stem!r}; "
                    f"keeping {m4b.stem!r}"
                )
            stem = m4b.stem
    elif not _usable_rename_stem(stem, author):
        # Non-minimalist: still never rename to author-only.
        if _usable_rename_stem(original_stem, author):
            reasons.append(
                f"rename stem rejected author-only {stem!r}; "
                f"keeping source {original_stem!r}"
            )
            stem = original_stem
        elif _usable_rename_stem(title_stem, author):
            reasons.append(
                f"rename stem rejected author-only {stem!r}; "
                f"using title {title_stem!r}"
            )
            stem = title_stem
        else:
            reasons.append(
                f"rename stem rejected author-only {stem!r}; "
                f"keeping {m4b.stem!r}"
            )
            stem = m4b.stem

    # If the current .m4b already matches the title (or Author - Title), keep it —
    # don't rename to a glued source stem like TheSearcherANovel_ep7.
    if _stem_matches_book_title(m4b.stem, title, author):
        if stem != m4b.stem:
            reasons.append(f"keep current filename {m4b.stem!r} (matches title)")
        stem = m4b.stem

    # Keep (YYYY) on the filename when the original stem already had it.
    yearful = preserve_original_year_in_stem(stem, filename_stem, m4b.stem, original_stem)
    if yearful != stem:
        reasons.append(f"keep year in filename {stem!r} → {yearful!r}")
        stem = yearful

    # fix-metadata must not rename files unless explicit cleanup was enabled.
    from src.lib.config import cfg

    if not cfg.CLEANUP_FILENAMES:
        stem = m4b.stem

    rename_to = m4b.with_name(ensure_audio_ext(stem, ".m4b")) if stem and m4b.stem != stem else None
    if rename_to == m4b:
        rename_to = None

    desc = _find_desc_txt(book_dir, m4b)
    rename_desc = None
    if desc and rename_to:
        m = _QUALITY_TXT.match(desc.name)
        if m:
            quality_part = desc.name[len(m.group(1)) :]
            rename_desc = desc.with_name(f"{stem}{quality_part}")
        else:
            rename_desc = desc.with_name(f"{stem}.txt")

    plan = FixPlan(
        book_dir=book_dir,
        m4b=m4b,
        source=source_path,
        desired_title=title,
        desired_author=author,
        desired_album=album,
        desired_date=date,
        desired_narrator=narrator,
        desired_stem=stem,
        current=current,
        reasons=reasons,
        rename_m4b_to=rename_to,
        desc_txt=desc,
        rename_desc_to=rename_desc if rename_desc and rename_desc != desc else None,
        fs_title=fs_title,
        fs_author=fs_author,
        fs_date=fs_date,
        fs_narrator=fs_narrator,
        fs_files=fs_files,
    )
    if desc and _desc_needs_rewrite(desc, plan):
        if "update description txt contents" not in plan.reasons:
            plan.reasons.append("update description txt contents")

    from src.lib.config import cfg

    if lookup_goodreads is None:
        lookup_goodreads = bool(cfg.GOODSCRAPS_USER_AGENT)
    if goodreads_ref and not lookup_goodreads:
        lookup_goodreads = True

    if ol_ref:
        _attach_open_library(
            plan, ol_ref=ol_ref, apply_ol_tags=True, minimalist=minimalist
        )
    elif goodreads_ref or (lookup_goodreads and cfg.GOODSCRAPS_USER_AGENT):
        comparison = lookup_metadata(
            title,
            author=author,
            narrator=narrator,
            lookup_goodreads=lookup_goodreads,
            lookup_open_library=lookup_ol,
            goodreads_ref=goodreads_ref,
        )
        _attach_provider_comparison(
            plan,
            comparison,
            apply_goodreads=bool(goodreads_ref),
            minimalist=minimalist,
        )
    elif lookup_ol:
        _attach_open_library(
            plan, apply_ol_tags=False, minimalist=minimalist
        )

    if plan.ol_title:
        _apply_cleanup_filename(plan, title)

    if not plan.needs_work:
        return None
    return plan

