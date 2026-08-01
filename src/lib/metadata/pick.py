"""Desired-tag picking (title/author/date/narrator) for metadata planning."""

from __future__ import annotations

import os
import re
from pathlib import Path

from rapidfuzz import fuzz

from src.lib.cleaners import (
    is_author_only_name,
    minimalist_title,
    strip_leading_author_dash,
)
from src.lib.metadata.models import CliPaths, TagSnapshot
from src.lib.metadata.priors import (
    _loose_m4b_in_author_folder,
    folder_narrator_hint,
    folder_title_hint,
    parent_author_hint,
)
from src.lib.metadata.stem import _looks_like_title
from src.lib.misc import parse_bool
from src.lib.parsers import get_year_from_date, swap_firstname_lastname


def _title_usable(title: str) -> bool:
    t = (title or "").strip()
    if not t or len(t) < 2:
        return False
    if t.isdigit():
        return False
    return True


def _env_truthy(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    if v == "on":
        return True
    return parse_bool(v) if v else False


def resolve_minimalist(*, flag_on: bool = False, flag_off: bool = False) -> bool:
    """Resolve minimalist mode: explicit flags beat ``CLI_MINIMALIST`` env."""
    if flag_off:
        return False
    if flag_on:
        return True
    return _env_truthy("CLI_MINIMALIST")


def _filesystem_year(book_dir: Path, source: TagSnapshot | None, current: TagSnapshot) -> str:
    """Return the oldest year present in the book folder or audio filenames."""
    candidates: list[int] = []
    for name in (
        book_dir.name,
        source.path.name if source and source.path else "",
        current.path.name if current.path else "",
    ):
        if match := re.search(r"\((\d{4})\)", name or ""):
            candidates.append(int(match.group(1)))
    return str(min(candidates)) if candidates else ""


def resolve_local_date(fs_year: str, id3_year: str) -> str:
    """Apply the locked no-OL rule: choose the older available local year."""
    years = [int(y) for y in (fs_year, id3_year) if y and y.isdigit()]
    return str(min(years)) if years else (fs_year or id3_year or "")


def _pick_desired(
    book_dir: Path,
    source: TagSnapshot | None,
    current: TagSnapshot,
    *,
    minimalist: bool = False,
    cli: CliPaths | None = None,
) -> tuple[str, str, str, str, str, list[str]]:
    """Return (title, author, album, date, narrator, reasons)."""
    reasons: list[str] = []
    loose_author = _loose_m4b_in_author_folder(book_dir, cli)
    if loose_author:
        # {converted}/Author/*.m4b — this folder is the author, not the book title.
        folder_title = ""
        folder_narr = ""
        parent_author = swap_firstname_lastname(book_dir.name.strip())
        reasons.append(f"author from author folder ({book_dir.name!r})")
    else:
        folder_title = folder_title_hint(book_dir.name)
        folder_narr = folder_narrator_hint(book_dir.name)
        parent_author = parent_author_hint(book_dir, cli)

    src_title = (source.title if source else "") or ""
    src_album = (source.album if source else "") or ""
    title = ""
    if _title_usable(src_title):
        if folder_title and fuzz.token_set_ratio(src_title, folder_title) / 100 < 0.5:
            title = folder_title
            reasons.append(f"prefer folder title over source {src_title!r}")
        else:
            title = src_title
            if src_album and fuzz.token_set_ratio(src_title, src_album) / 100 < 0.85:
                reasons.append(f"keep source title over album ({src_album!r})")
    elif _title_usable(folder_title):
        title = folder_title
        reasons.append("title from folder name")
    elif _title_usable(current.title) and (
        not folder_title
        or fuzz.token_set_ratio(current.title, folder_title) / 100 >= 0.55
    ):
        title = current.title
        if loose_author:
            reasons.append("title from id3 (loose m4b in author folder)")
    else:
        # Last resort: m4b stem often equals the book title for loose files.
        stem_title = (current.path.stem if current.path else "") or ""
        if loose_author and _title_usable(stem_title) and not is_author_only_name(
            stem_title, parent_author
        ):
            title = stem_title
            reasons.append("title from m4b filename (loose m4b in author folder)")
        else:
            title = folder_title or current.title or book_dir.name

    # Provisional author early so title cleanup can strip leading "Author - ".
    src_author = ""
    if source:
        src_author = source.albumartist or source.artist or ""
    provisional_author = ""
    if src_author and not _looks_like_title(src_author, title or folder_title):
        provisional_author = src_author
    elif parent_author:
        provisional_author = parent_author
    elif (current.artist or "").strip() and not _looks_like_title(
        current.artist, title or folder_title
    ):
        provisional_author = current.artist.strip()

    if provisional_author and title:
        deauthored = strip_leading_author_dash(title, provisional_author)
        if deauthored != title and _title_usable(deauthored):
            reasons.append(f"strip author prefix from title {title!r}")
            title = deauthored

    if minimalist and title:
        from src.lib.ol_lookup import _subtitle_sep_normalized, id3_prefer_colon_separator

        stripped = minimalist_title(title, author=provisional_author)
        candidates: list[str] = []
        for cand in (current.title or "", folder_title, stripped):
            if not _title_usable(cand):
                continue
            deauthored_cand = strip_leading_author_dash(cand, provisional_author)
            cand_core = minimalist_title(cand, author=provisional_author)
            if is_author_only_name(cand_core, provisional_author):
                continue
            # still has marketing junk relative to cleaned core
            if cand_core.casefold() != deauthored_cand.strip().casefold():
                continue
            if fuzz.token_set_ratio(cand, stripped) / 100 >= 0.85:
                c = deauthored_cand.strip() or cand.strip()
                if c not in candidates and not is_author_only_name(c, provisional_author):
                    candidates.append(c)
        if not candidates:
            candidates = (
                [stripped]
                if not is_author_only_name(stripped, provisional_author)
                else [title]
            )
        # Prefer colon form when candidates only differ by ": " vs " - "
        chosen = candidates[0]
        for cand in candidates:
            if _subtitle_sep_normalized(cand) != _subtitle_sep_normalized(chosen):
                continue
            if ": " in cand and ": " not in chosen:
                chosen = cand
        chosen = id3_prefer_colon_separator(chosen)
        if chosen != title:
            reasons.append(f"minimalist title {title!r} → {chosen!r}")
            title = chosen
    elif title:
        from src.lib.ol_lookup import id3_prefer_colon_separator

        normalized = id3_prefer_colon_separator(title)
        if normalized != title:
            reasons.append(f"id3 colon subtitle {title!r} → {normalized!r}")
            title = normalized
    author = ""
    if src_author and not _looks_like_title(src_author, title):
        author = src_author
    elif parent_author:
        author = parent_author
        reasons.append(f"author from parent folder ({book_dir.parent.name!r})")
    elif current.albumartist or current.artist:
        cand = current.albumartist or current.artist
        if parent_author and fuzz.token_set_ratio(cand, parent_author) / 100 >= 0.5:
            author = cand
        elif src_author and fuzz.token_set_ratio(cand, src_author) / 100 >= 0.5:
            author = cand
        else:
            author = parent_author or src_author or cand
            if parent_author or src_author:
                reasons.append(f"replace wrong author {cand!r}")
    else:
        author = parent_author or "Unknown Author"

    cur_author = current.albumartist or current.artist or ""
    if cur_author and fuzz.token_set_ratio(cur_author, author) / 100 < 0.5:
        reasons.append(f"author {cur_author!r} → {author!r}")

    if current.title and fuzz.token_set_ratio(current.title, title) / 100 < 0.55:
        reasons.append(f"title {current.title!r} → {title!r}")

    album = title

    fs_year = _filesystem_year(book_dir, source, current)
    cur_y = get_year_from_date(current.date)
    src_y = get_year_from_date(source.date) if source and source.date else ""
    date = resolve_local_date(fs_year, cur_y or src_y)
    if date and cur_y and date != cur_y:
        reasons.append(f"date {cur_y} → {date}")
    elif date and src_y and date != src_y:
        reasons.append(f"date {src_y} → {date}")

    narrator = ""
    if folder_narr and fuzz.token_set_ratio(folder_narr, author) / 100 < 0.5:
        narrator = folder_narr
    if current.composer and fuzz.token_set_ratio(current.composer, author) / 100 >= 0.7:
        reasons.append(f"clear narrator/composer {current.composer!r} (was author)")
        narrator = narrator
    elif current.composer and not narrator:
        if fuzz.token_set_ratio(current.composer, author) / 100 < 0.5:
            pass

    return title, author, album, date, narrator, reasons

