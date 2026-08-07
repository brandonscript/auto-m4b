"""Rename-stem helpers for metadata planning."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from src.lib.cleaners import (
    is_author_only_name,
    title_case_ol_title,
)
from src.lib.fs_utils import safe_filename

_YEAR_SUFFIX = re.compile(r"\s*\((\d{4})\)\s*$")
_TRAILING_ARTICLE = re.compile(r"^(?P<body>.+?),\s*(?P<article>the|a|an)$", re.I)
_LEADING_ARTICLE = re.compile(r"^(?P<article>the|a|an)\s+(?P<body>.+)$", re.I)


def _usable_rename_stem(s: str, author: str = "") -> bool:
    return bool(s) and not is_author_only_name(s, author)


def year_suffix_from_stem(stem: str) -> str:
    """Return `` (YYYY)`` if *stem* ends with a paren year, else ``""``."""
    m = _YEAR_SUFFIX.search(stem or "")
    return f" ({m.group(1)})" if m else ""


def preserve_original_year_in_stem(stem: str, *originals: str) -> str:
    """Keep ``(YYYY)`` on the rename stem when an original filename already had it.

    Years are not required on filenames, but if the source/current stem carried
    one, do not drop it when the stem is rebuilt from a yearless title.
    """
    s = (stem or "").strip()
    if not s or _YEAR_SUFFIX.search(s):
        return s
    for orig in originals:
        suffix = year_suffix_from_stem(orig or "")
        if suffix:
            return f"{s}{suffix}"
    return s


def near_match_ol_filename_stem(
    local_title: str, ol_title: str, *originals: str, threshold: float = 90
) -> str:
    """Return a cleaned OL filename stem when titles are nearly identical."""
    local = (local_title or "").strip()
    ol = (ol_title or "").strip()
    if not local or not ol or fuzz.ratio(local.casefold(), ol.casefold()) < threshold:
        return ""
    stem = safe_filename(title_case_ol_title(ol))
    return preserve_original_year_in_stem(stem, *originals)


def is_trailing_article_variant(local_title: str, ol_title: str) -> bool:
    """True for ``Title, The`` versus Open Library's ``The Title`` form."""
    local_match = _TRAILING_ARTICLE.match((local_title or "").strip())
    ol_match = _LEADING_ARTICLE.match((ol_title or "").strip())
    return bool(
        local_match
        and ol_match
        and local_match.group("article").casefold() == ol_match.group("article").casefold()
        and local_match.group("body").strip().casefold() == ol_match.group("body").strip().casefold()
    )


def _stem_matches_book_title(stem: str, title: str, author: str = "") -> bool:
    """True when *stem* already names the book (title or Author - Title).

    Treats ``: `` and `` - `` as the same separator so ``The Searcher - A Novel``
    matches title ``The Searcher: A Novel``. Trailing ``(YYYY)`` on the stem is
    ignored for the comparison so a yearful filename still matches a yearless title.
    """
    from src.lib.ol_lookup import subtitle_sep_normalized

    s_bare = _YEAR_SUFFIX.sub("", stem or "").strip()
    s_norm = subtitle_sep_normalized(s_bare)
    if not s_norm:
        return False
    candidates: list[str] = []
    t = (title or "").strip()
    if t:
        candidates.append(safe_filename(t))
        candidates.append(t)
    a = (author or "").strip()
    if a and t:
        title_fs = safe_filename(t)
        candidates.append(f"{a} - {title_fs}")
        candidates.append(safe_filename(f"{a} - {t}"))
    for c in candidates:
        if c and s_norm == subtitle_sep_normalized(c):
            return True
    return False


def _looks_like_title(name: str, title: str) -> bool:
    if not name or not title:
        return False
    return fuzz.token_set_ratio(name, title) / 100 >= 0.85

