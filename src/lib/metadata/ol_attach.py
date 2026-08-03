"""Open Library attach / date consensus for metadata plans."""

from __future__ import annotations

from src.lib.cleaners import looks_like_marketing_subtitle, minimalist_title, title_case_ol_title
from src.lib.metadata.models import FixPlan
from src.lib.metadata.priors import folder_title_hint
from src.lib.parsers import get_year_from_date


def _attach_open_library(
    plan: FixPlan,
    *,
    ol_ref: str | None = None,
    apply_ol_tags: bool = False,
    minimalist: bool = False,
) -> FixPlan:
    """Lookup or fetch Open Library metadata onto *plan* (mutates and returns it)."""
    from src.lib.ol_lookup import (
        _best_matching_edition_base_title,
        _best_matching_edition_subtitle,
        _desired_matches_edition_title,
        _get_open_library_user_agent,
        id3_prefer_colon_separator,
        join_title_subtitle,
        ol_match_band,
        ol_title_uses_dash_separator,
        open_library_fetch_by_ref,
        open_library_lookup_title,
        _strip_boundary_number,
        _title_sim,
    )

    try:
        if ol_ref:
            ol = open_library_fetch_by_ref(
                ol_ref,
                original_author=plan.desired_author,
                original_narrator=plan.desired_narrator or None,
            )
            if ol is None:
                plan.ol_status = "none"
                plan.reasons.append(f"Open Library fetch failed for {ol_ref!r} (is OPEN_LIBRARY_USER_AGENT set?)")
                return plan
            plan.ol_status = "forced"
        else:
            # Always try full + stripped core so marketing junk does not block matches.
            queries: list[str] = []
            for q in (
                plan.desired_title,
                minimalist_title(plan.desired_title or "", author=plan.desired_author),
                folder_title_hint(plan.book_dir.name),
            ):
                q = (q or "").strip()
                if q and q.casefold() not in {x.casefold() for x in queries}:
                    queries.append(q)

            best_ol = None
            best_band = "skipped"
            best_score = -1.0
            band_rank = {"match": 3, "low_confidence": 2, "none": 1, "skipped": 0}
            for q in queries:
                cand = open_library_lookup_title(
                    q,
                    author=plan.desired_author,
                    narrator=plan.desired_narrator or None,
                    method="similarity",
                )
                band = ol_match_band(cand)
                score = float(cand.score(fallback=0.0)) if cand is not None else 0.0
                if band_rank.get(band, 0) > band_rank.get(best_band, 0) or (
                    band == best_band and score > best_score
                ):
                    best_ol, best_band, best_score = cand, band, score

            ol = best_ol
            if best_band == "skipped":
                plan.ol_status = "skipped"
                return plan
            if best_band == "none":
                plan.ol_status = "none"
                return plan
            plan.ol_status = best_band  # match | low_confidence
    except ValueError as e:
        plan.ol_status = "none"
        plan.reasons.append(str(e))
        return plan
    except Exception:
        plan.ol_status = "none"
        return plan

    plan.ol_title = title_case_ol_title(ol.title) if ol and ol.title else ""
    plan.ol_author = ol.author if ol else ""
    plan.ol_narrator = ol.narrator if ol else ""
    plan.ol_year = ol.date if ol else ""
    plan.ol_key = ol.key if ol else ""
    plan.ol_url = ol.url if ol else ""
    plan.ol_score = float(ol.score(fallback=0.0)) if ol else 0.0

    # Enrich title with edition subtitle when local naming already attests those tokens.
    # Prefer an edition base closest to local naming (e.g. Eon) over a regional
    # alternate work title (e.g. The Two Pearls of Wisdom). Never use a marketing
    # source-only title (e.g. Dragoneye Reborn alone) as the join base.
    agent = _get_open_library_user_agent()
    if agent and plan.ol_key and plan.ol_status in ("match", "low_confidence", "forced"):
        work_title = (plan.ol_title or "").strip()
        corpus = " ".join(
            p
            for p in (
                plan.book_dir.name,
                folder_title_hint(plan.book_dir.name),
                plan.fs_files or "",
                plan.fs_title or "",
                plan.desired_title or "",
            )
            if p
        )
        prefer_local = (plan.desired_title or plan.fs_title or "").strip() or None
        # Keep a local title that already matches an edition form (US Eon vs AU work title).
        already_good = bool(
            prefer_local
            and _desired_matches_edition_title(plan.ol_key, prefer_local, agent=agent)
        )
        base_title = _best_matching_edition_base_title(
            plan.ol_key,
            corpus,
            work_title=work_title,
            prefer_local=prefer_local,
            agent=agent,
        )
        sub = None
        if not already_good:
            sub = _best_matching_edition_subtitle(
                plan.ol_key,
                corpus,
                base_title=base_title,
                agent=agent,
                prefer_local=prefer_local,
            )
        # Never re-attach trilogy/Book N/unabridged noise (esp. in minimalist mode).
        if sub and looks_like_marketing_subtitle(sub):
            sub = None
        if sub and base_title:
            # id3 defaults to colon; dash only if OL title is already dash-form.
            prefer_dash = ol_title_uses_dash_separator(
                plan.ol_title or "", base_title, sub
            )
            enriched = title_case_ol_title(
                join_title_subtitle(base_title, sub, prefer_dash=prefer_dash)
            )
            enriched = id3_prefer_colon_separator(
                enriched, ol_title_hint=plan.ol_title if prefer_dash else None
            )
            if enriched and enriched != plan.desired_title:
                # Minimalist: do not grow a clean desired title with OL subtitle noise
                if (
                    minimalist
                    and minimalist_title(enriched, author=plan.desired_author)
                    != enriched.strip()
                ):
                    pass
                else:
                    plan.desired_title = enriched
                    plan.desired_album = enriched
                    plan.ol_title = enriched
                    plan.reasons.append(f"title + OL subtitle ({sub!r})")

    # A case typo should not make an otherwise unanimous title lose to the
    # local spelling. When filesystem, ID3, and OL agree case-insensitively,
    # use OL's canonical casing for the tags.
    if plan.ol_status in ("match", "forced") and plan.ol_title:
        local_titles = (plan.fs_title, plan.current.title, plan.desired_title)
        ol_title_key = plan.ol_title.strip().casefold()
        all_local_titles_present = all(value.strip() for value in local_titles)
        all_local_titles_match = all(
            value.strip().casefold() == ol_title_key for value in local_titles
        )
        if all_local_titles_present and all_local_titles_match:
            canonical_title = title_case_ol_title(plan.ol_title)
            if plan.desired_title != canonical_title:
                local_title = plan.desired_title
                plan.desired_title = canonical_title
                plan.desired_album = canonical_title
                plan.reasons.append(
                    f"use Open Library title casing for unanimous local title "
                    f"{local_title!r} → {canonical_title!r}"
                )

    if plan.ol_status == "match" and plan.ol_author:
        id3_author_support = max(
            (
                _title_sim(plan.ol_author, value)[0]
                for value in (
                    plan.current.artist,
                    plan.current.albumartist,
                    plan.current.composer,
                )
                if value
            ),
            default=0.0,
        )
        if id3_author_support >= 0.9 and plan.desired_author != plan.ol_author:
            local_author = plan.desired_author
            plan.desired_author = plan.ol_author
            plan.reasons.append(
                f"use Open Library author for ID3-supported local author "
                f"{local_author!r} → {plan.ol_author!r}"
            )
        if plan.ol_narrator:
            id3_narrator_support = max(
                (
                    _title_sim(plan.ol_narrator, value)[0]
                    for value in (
                        plan.current.artist,
                        plan.current.albumartist,
                        plan.current.composer,
                    )
                    if value
                ),
                default=0.0,
            )
            if id3_narrator_support >= 0.9 and plan.desired_narrator != plan.ol_narrator:
                local_narrator = plan.desired_narrator or "(unknown)"
                plan.desired_narrator = plan.ol_narrator
                plan.reasons.append(
                    f"use Open Library narrator for ID3-supported local narrator "
                    f"{local_narrator!r} → {plan.ol_narrator!r}"
                )

    if (
        not apply_ol_tags
        and plan.ol_status == "match"
        and plan.ol_title
        and (numeric_title := _strip_boundary_number(plan.desired_title))
        and _title_sim(numeric_title, plan.ol_title)[0] >= 0.9
    ):
        local_numeric_title = plan.desired_title
        id3_values = (
            plan.current.title,
            plan.current.album,
            plan.current.artist,
            plan.current.albumartist,
            plan.current.composer,
        )
        id3_support = max(
            (_title_sim(plan.ol_title, value)[0] for value in id3_values if value),
            default=0.0,
        )
        if id3_support >= 0.9:
            plan.desired_title = plan.ol_title
            plan.desired_album = plan.ol_title
            plan.reasons.append(
                f"use Open Library title for numeric local variant "
                f"{local_numeric_title!r} → {plan.ol_title!r}"
            )

    if apply_ol_tags and plan.ol_status == "forced":
        _apply_ol_fields_to_desired(plan)
    else:
        # Auto OL is display-only for tags, but date can adopt a 2-of-3 consensus.
        _apply_date_consensus(plan)
    return plan


def _normalize_year(value: str | None) -> str:
    """Extract a 4-digit year string, or empty if none."""
    return get_year_from_date(value or "") or ""


def _year_consensus(*years: str | None) -> str | None:
    """Return a year shared by at least two non-empty inputs, else None."""
    counts: dict[str, int] = {}
    for raw in years:
        y = _normalize_year(raw)
        if not y:
            continue
        counts[y] = counts.get(y, 0) + 1
    winners = [y for y, n in counts.items() if n >= 2]
    if len(winners) == 1:
        return winners[0]
    return None


def resolve_date_consensus(
    fs_year: str | None,
    id3_year: str | None,
    ol_year: str | None,
    *,
    ol_status: str = "",
) -> str:
    """Resolve filesystem, ID3, and OL years using the locked product policy."""
    values = [_normalize_year(y) for y in (fs_year, id3_year, ol_year)]
    fs_y, id3_y, ol_y = values
    local = [int(y) for y in (fs_y, id3_y) if y]
    if not ol_y or ol_status not in ("match", "low_confidence", "forced"):
        return str(min(local)) if local else (fs_y or id3_y or "")
    present = [int(y) for y in values if y]
    counts: dict[int, int] = {}
    for year in present:
        counts[year] = counts.get(year, 0) + 1
    majority = [year for year, count in counts.items() if count >= 2]
    if majority:
        return str(majority[0])
    if len(present) == 3:
        pairs = [(present[i], present[j]) for i in range(3) for j in range(i + 1, 3)]
        near_pairs = [pair for pair in pairs if abs(pair[0] - pair[1]) <= 1]
        if near_pairs:
            pair = min(near_pairs, key=lambda p: abs(p[0] - p[1]))
            outlier = next(year for year in present if year not in pair)
            if abs(outlier - pair[0]) >= 2:
                return str(min(pair))
        if ol_status == "match":
            return ol_y
        return str(min(local)) if local else ol_y
    return ol_y if ol_status == "match" and not local else (str(min(local)) if local else ol_y)


def _apply_date_consensus(plan: FixPlan) -> None:
    """Apply the locked FS / ID3 / OL date policy."""
    if plan.ol_status not in ("match", "low_confidence"):
        return
    ol_y = _normalize_year(plan.ol_year)
    if not ol_y:
        return
    fs_y = _normalize_year(plan.fs_date)
    id3_y = _normalize_year(plan.current.date)
    winner = resolve_date_consensus(fs_y, id3_y, ol_y, ol_status=plan.ol_status)
    cur = _normalize_year(plan.desired_date)
    if winner == cur:
        return
    plan.reasons.append(f"date consensus {cur or '(none)'} → {winner} (2 of FS/id3/OL)")
    plan.desired_date = winner


def _apply_ol_fields_to_desired(plan: FixPlan) -> None:
    """Copy stored OL fields into desired_* tags (does not change rename stem)."""
    if plan.ol_title:
        plan.desired_title = plan.ol_title
        plan.desired_album = plan.desired_title
        plan.reasons.append(f"title from Open Library ({plan.ol_key})")
    if plan.ol_author:
        plan.desired_author = plan.ol_author
        plan.reasons.append(f"author from Open Library ({plan.ol_author!r})")
    if plan.ol_narrator:
        plan.desired_narrator = plan.ol_narrator
        plan.reasons.append(f"narrator from Open Library ({plan.ol_narrator!r})")
    if plan.ol_year:
        if get_year_from_date(plan.desired_date) != get_year_from_date(str(plan.ol_year)):
            plan.reasons.append(f"date from Open Library ({plan.ol_year})")
        plan.desired_date = str(plan.ol_year)

