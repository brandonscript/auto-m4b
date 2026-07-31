"""Rename-stem helpers for metadata planning."""

from __future__ import annotations

from rapidfuzz import fuzz

from src.lib.cleaners import is_author_only_name
from src.lib.fs_utils import safe_filename


def _usable_rename_stem(s: str, author: str = "") -> bool:
    return bool(s) and not is_author_only_name(s, author)


def _stem_matches_book_title(stem: str, title: str, author: str = "") -> bool:
    """True when *stem* already names the book (title or Author - Title).

    Treats ``: `` and `` - `` as the same separator so ``The Searcher - A Novel``
    matches title ``The Searcher: A Novel``.
    """
    from src.lib.ol_lookup import _subtitle_sep_normalized

    s_norm = _subtitle_sep_normalized(stem)
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
        if c and s_norm == _subtitle_sep_normalized(c):
            return True
    return False


def _looks_like_title(name: str, title: str) -> bool:
    if not name or not title:
        return False
    return fuzz.token_set_ratio(name, title) / 100 >= 0.85

