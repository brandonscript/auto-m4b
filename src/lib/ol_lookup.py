import re
import sys
import urllib.parse
from datetime import timedelta
from math import log10
from typing import Any, Literal, NotRequired, overload, TypedDict

import requests
import requests_cache
from rapidfuzz import fuzz

from src.lib.misc import max_if, re_group
from src.lib.term import print_debug
from src.lib.config import cfg

requests_cache.install_cache(
    str(cfg.META_DIR / "ol_cache"), backend="sqlite", expire_after=timedelta(days=1), ignored_parameters=["User-Agent"]
)

OpenLibraryAuthorResult = TypedDict(
    "OpenLibraryAuthorResult",
    {
        "key": str,
        "name": str,
        "type": str,
        "work_count": int,
        "alternate_names": NotRequired[list[str]],
        "birth_date": NotRequired[str],
        "death_date": NotRequired[str],
        "top_subjects": NotRequired[list[str]],
        "top_work": NotRequired[str],
        "ratings_average": NotRequired[float],
        "ratings_sortable": NotRequired[float],
        "ratings_count": NotRequired[int],
        "ratings_count_1": NotRequired[int],
        "ratings_count_2": NotRequired[int],
        "ratings_count_3": NotRequired[int],
        "ratings_count_4": NotRequired[int],
        "ratings_count_5": NotRequired[int],
        "want_to_read_count": NotRequired[int],
        "already_read_count": NotRequired[int],
        "currently_reading_count": NotRequired[int],
        "readinglog_count": NotRequired[int],
        "_version_": NotRequired[int],
    },
)

OpenLibrarySearchResult = TypedDict(
    "OpenLibrarySearchResult",
    {
        "key": str,
        "author_key": list[str],
        "author_name": list[str],
        "type": NotRequired[str],
        "name": str,
        "alternate_names": NotRequired[list[str]],
        "work_count": int,
        "ratings_count": NotRequired[int],
        "currently_reading_count": NotRequired[int],
        "read_count": NotRequired[int],
        "want_to_read_count": NotRequired[int],
        "cover_edition_key": NotRequired[str],
        "cover_i": NotRequired[int],
        "ebook_access": NotRequired[str],
        "edition_count": int,
        "first_publish_year": NotRequired[int],
        "has_fulltext": NotRequired[bool],
        "ia": NotRequired[list[str]],
        "ia_collections": NotRequired[list[str]],
        "language": NotRequired[list[str]],
        "lending_edition_s": NotRequired[str],
        "lending_identifier_s": NotRequired[str],
        "public_scan_b": NotRequired[bool],
        "title": NotRequired[str],
    },
)


def _generate_unique_app_name() -> str:
    """Uses nltk corpus to generate a unique app name"""
    from random import choice

    from nltk.corpus import words

    # Keep pulling random words until we have 3 that are <= 6 chars
    result = []
    while len(result) < 3:
        word = re.sub(r"[^a-zA-Z]", "", str(choice(words.words())))
        if len(word) > 3 and len(word) <= 8:
            result.append(word)
    return "-".join(result).lower()


def _get_open_library_user_agent() -> str | None:
    """Get the user agent for the Open Library API from the env var and
    validates that it matches the following format, and includes/generates
    a unique name.

    MyAppName/1.0 (myemail@example.com)
    """
    from src.lib.config import cfg
    from src.lib.patterns import open_library_user_agent_pattern

    if not (agent_string := cfg.OPEN_LIBRARY_USER_AGENT):
        return None

    match = open_library_user_agent_pattern.search(agent_string)

    err_msg = f"Invalid Open Library user agent: {agent_string}, must match: MyAppName/1.0 (myemail@example.com)"

    if not match:
        raise ValueError(err_msg)

    app_name = re_group(match, "app", default="")
    email = re_group(match, "email", default="")
    version = re_group(match, "version", default="0.0.1")

    if not app_name or not email:
        raise ValueError(err_msg)

    if email.lower() in ("myemail@example.com", "example@example.com"):
        raise ValueError("Please use your own email address for the Open Library API user agent")

    if app_name.lower() == "auto-m4b":
        # Check cfg.META_DIR for a file called "app_name"
        app_name_file = cfg.META_DIR / "app_name"
        if app_name_file.exists():
            with open(app_name_file, "r") as f:
                app_name = f.read().strip()
            if app_name and not app_name == "auto-m4b":
                return f"{app_name}/{version} ({email})"
        else:
            app_name = f"auto-m4b-{_generate_unique_app_name()}"
            with open(app_name_file, "w") as f:
                f.write(app_name)

    return f"{app_name}/{version} ({email})"


def _in_alternate_names(name: str, doc: dict[str, Any]) -> bool:
    """Check if name is in the alternate_names list of the doc"""
    if not (alternate_names := doc.get("alternate_names", None)):
        return False
    name = name.lower().strip()
    name_no_periods = name.replace(".", "")
    name_period_spaces = re.sub(r"\s+", " ", name.replace(".", ". "))
    return (
        name in map(str.lower, alternate_names)
        or name_no_periods in map(str.lower, alternate_names)
        or name_period_spaces in map(str.lower, alternate_names)
    )


def _find_best_author(
    author: str, matches: list[OpenLibraryAuthorResult], *, method: Literal["score", "similarity"] = "score"
) -> tuple[OpenLibraryAuthorResult | None, float]:
    if not matches:
        return (None, 0.0)

    score_ordered = sorted(
        matches,
        key=lambda x: (
            x.get("work_count", 0),
            x.get("ratings_count", 0),
            x.get("currently_reading_count", 0),
            x.get("read_count", 0),
            x.get("want_to_read_count", 0),
        ),
        reverse=True,
    )
    sim_ordered = sorted(matches, key=lambda x: fuzz.ratio(author, x["name"]), reverse=True)

    top_scored = score_ordered[0]
    top_sim = sim_ordered[0]

    # closest_match: OpenLibraryAuthorResult | None = None
    # closest_score = 0.0
    # for m in matches:
    #     score = fuzz.ratio(author, m["name"]) / 100
    #     if score > closest_score:
    #         closest_score = score
    #         closest_match = m

    # If closest_match is the same as ordered[0], we found an easy match
    if top_sim and top_sim["key"] == top_scored["key"]:
        return (top_scored, fuzz.ratio(author, top_scored["name"]) / 100)

    # Otherwise, find the highest scored/most similar match
    if method == "score":
        return (top_scored, fuzz.ratio(author, top_scored["name"]) / 100)

    return (top_sim, fuzz.ratio(author, top_sim["name"]) / 100)


def _author_name_sim(candidate: str, author_names: list[str] | str | None) -> float:
    """Best fuzz.ratio of *candidate* against an OL ``author_name`` list (0..1)."""
    if not candidate:
        return 0.0
    if isinstance(author_names, str):
        names = [author_names] if author_names else []
    else:
        names = [n for n in (author_names or []) if n]
    if not names:
        return 0.0
    return max(fuzz.ratio(candidate, n) for n in names) / 100


def _title_sim(a: str, b: str) -> tuple[float, float]:
    """Return ``(fuzz.ratio, token_set_ratio)`` both in 0..1."""
    left = (a or "").strip()
    right = (b or "").strip()
    if not left or not right:
        return 0.0, 0.0
    return fuzz.ratio(left, right) / 100, fuzz.token_set_ratio(left, right) / 100


# Align with id3_utils auto-apply floor (score >= 0.5).
OL_MATCH_MIN = 0.5
# Drop pure noise from free-text q= fallback; keep edition-subtitle hits (~0.2).
OL_LOW_CONFIDENCE_MIN = 0.15


def _edition_title_strings(edition: dict) -> list[str]:
    """Work/edition title variants for similarity scoring."""
    title = (edition.get("title") or "").strip()
    subtitle = (edition.get("subtitle") or "").strip()
    out: list[str] = []
    if title:
        out.append(title)
    if title and subtitle:
        out.append(f"{title}: {subtitle}")
        out.append(f"{title} - {subtitle}")
    if subtitle and subtitle not in out:
        out.append(subtitle)
    return out


def _fetch_work_editions(work_key: str, *, agent: str) -> list[dict]:
    """Return edition entry dicts for a work key (``/works/OL…W``)."""
    if not work_key:
        return []
    key = work_key if work_key.startswith("/") else f"/works/{work_key}"
    try:
        url = f"https://openlibrary.org{key}/editions.json"
        response = requests.get(url, headers={"User-Agent": agent}, timeout=30)
        response.raise_for_status()
        entries = response.json().get("entries") or []
    except Exception as e:
        print_debug(f"Error fetching editions for {key}: {e}")
        return []
    return [ed for ed in entries if isinstance(ed, dict)]


def _edition_subtitle_candidates(edition: dict) -> list[str]:
    """Subtitle strings from an edition (field or parsed from title)."""
    title = (edition.get("title") or "").strip()
    subtitle = (edition.get("subtitle") or "").strip()
    out: list[str] = []
    if subtitle:
        out.append(subtitle)
    # "Eona: the last Dragoneye" / "Eona - The Last Dragoneye" with no subtitle field
    for sep in (": ", " - ", ":", " -"):
        if sep in title:
            left, right = title.split(sep, 1)
            right = right.strip()
            if left.strip() and right and right not in out:
                out.append(right)
            break
    return out


def _title_contains_subtitle(title: str, subtitle: str) -> bool:
    """True if *subtitle* tokens are already present in *title*."""
    t = (title or "").strip()
    s = (subtitle or "").strip()
    if not t or not s:
        return False
    if s.lower() in t.lower():
        return True
    return fuzz.token_set_ratio(t, s) / 100 >= 0.85 and len(s) <= len(t) + 5


def ol_title_uses_dash_separator(ol_title: str, base: str, subtitle: str) -> bool:
    """True when the OL title itself is ``base - subtitle`` (not colon).

    Folder / filesystem dashes are ignored — only Open Library's form counts.
    """
    ol = (ol_title or "").strip().lower()
    b = (base or "").strip().lower()
    s = (subtitle or "").strip().lower()
    if not ol or not b or not s:
        return False
    if f"{b}: {s}" in ol or f"{b}:{s}" in ol:
        return False
    if f"{b} - {s}" in ol or f"{b} -{s}" in ol:
        return True
    if re.search(re.escape(b) + r"\s+-\s+" + re.escape(s), ol):
        return True
    return False


# Back-compat alias (tests / older call sites) — dash signal is OL-only now.
def _local_prefers_dash_separator(corpus: str, base: str, subtitle: str) -> bool:
    """Deprecated: use ``ol_title_uses_dash_separator``. Treats *corpus* as an OL title."""
    return ol_title_uses_dash_separator(corpus, base, subtitle)


def id3_prefer_colon_separator(title: str, *, ol_title_hint: str | None = None) -> str:
    """Normalize ``Title - Subtitle`` → ``Title: Subtitle`` for id3 tags.

    Keeps a dash only when *ol_title_hint* is already a dash-form title/subtitle.
    """
    t = (title or "").strip()
    if not t or ": " in t:
        return t
    m = re.match(r"^(.+?)\s+-\s+(.+)$", t)
    if not m:
        return t
    left, right = m.group(1).strip(), m.group(2).strip()
    if not left or not right:
        return t
    if ol_title_hint and ol_title_uses_dash_separator(ol_title_hint, left, right):
        return t
    return f"{left}: {right}"


def _subtitle_sep_normalized(title: str) -> str:
    """Compare titles treating ``: `` and `` - `` as the same separator."""
    t = (title or "").strip().casefold()
    return re.sub(r"\s*:\s*", " - ", t)


def join_title_subtitle(base: str, subtitle: str, *, prefer_dash: bool = False) -> str:
    """Join base + subtitle for id3. Default separator is ``: ``; use `` - `` when preferred.

    Does not add a separator if *base* already contains *subtitle*.
    """
    base = (base or "").strip()
    subtitle = (subtitle or "").strip()
    if not subtitle:
        return base
    if not base:
        return subtitle
    if _title_contains_subtitle(base, subtitle):
        return base
    # Strip a leading separator from subtitle if present
    subtitle = re.sub(r"^[\s:\-]+", "", subtitle).strip()
    if not subtitle or _title_contains_subtitle(base, subtitle):
        return base
    sep = " - " if prefer_dash else ": "
    return f"{base}{sep}{subtitle}"


_SUBTITLE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)


def _subtitle_content_tokens(text: str) -> list[str]:
    """Alphanumeric tokens length > 2, minus stopwords."""
    return [
        t
        for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(t) > 2 and t not in _SUBTITLE_STOPWORDS
    ]


def _subtitle_attested_locally(subtitle: str, naming_corpus: str, *, min_fraction: float = 0.75) -> bool:
    """True when ≥ *min_fraction* of subtitle content tokens appear in *naming_corpus*."""
    tokens = _subtitle_content_tokens(subtitle)
    if not tokens:
        return False
    corpus = (naming_corpus or "").lower()
    if not corpus.strip():
        return False
    # Prefer whole-token hits so short fragments do not over-match.
    corpus_tokens = set(re.findall(r"[a-z0-9]+", corpus))
    hits = sum(1 for t in tokens if t in corpus_tokens)
    return (hits / len(tokens)) >= min_fraction


def _split_title_subtitle_parts(title: str) -> tuple[str, str] | None:
    """Split ``Left: Right`` / ``Left - Right`` into base + subtitle, or None."""
    t = (title or "").strip()
    if not t:
        return None
    for sep in (": ", " - ", ":", " -"):
        if sep in t:
            left, right = t.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return None


def _edition_base_title_candidates(edition: dict) -> list[str]:
    """Base (left) titles from an edition — never a standalone subtitle."""
    title = (edition.get("title") or "").strip()
    out: list[str] = []
    if not title:
        return out
    parts = _split_title_subtitle_parts(title)
    if parts:
        out.append(parts[0])
    else:
        out.append(title)
    return out


def _desired_matches_edition_title(
    work_key: str,
    desired: str,
    *,
    agent: str,
) -> bool:
    """True when *desired* already matches a full edition title form for the work.

    Full form means ``title: subtitle`` (or dash) when the edition has a subtitle;
    bare ``title`` only when there is no subtitle field / embedded subtitle.
    Never treats a bare subtitle (e.g. ``Dragoneye Reborn``) as a full match, so
    incomplete locals still enrich.
    """
    d = (desired or "").strip()
    if not work_key or not d:
        return False
    d_norm = _subtitle_sep_normalized(d)
    for ed in _fetch_work_editions(work_key, agent=agent):
        title = (ed.get("title") or "").strip()
        subtitle = (ed.get("subtitle") or "").strip()
        if not title:
            continue
        forms: list[str] = []
        embedded = _split_title_subtitle_parts(title)
        if subtitle:
            # Edition has an explicit subtitle — only joined forms count as complete.
            forms.append(f"{title}: {subtitle}")
            forms.append(f"{title} - {subtitle}")
        elif embedded:
            # Title already carries base + subtitle (e.g. "Eon: Dragoneye Reborn").
            forms.append(title)
            forms.append(f"{embedded[0]}: {embedded[1]}")
            forms.append(f"{embedded[0]} - {embedded[1]}")
        else:
            forms.append(title)
        for t in forms:
            if not t:
                continue
            if _subtitle_sep_normalized(t) == d_norm:
                return True
            # Fuzz only when desired covers nearly all content tokens of the full
            # form — otherwise bare subtitles match via token_set_ratio == 100.
            t_toks = set(_subtitle_content_tokens(t))
            d_toks = set(_subtitle_content_tokens(d))
            if t_toks and (len(t_toks & d_toks) / len(t_toks)) < 0.9:
                continue
            if fuzz.token_set_ratio(t, d) / 100 >= 0.95 and fuzz.ratio(t, d) / 100 >= 0.85:
                return True
    return False


def _best_matching_edition_base_title(
    work_key: str,
    naming_corpus: str,
    *,
    work_title: str,
    prefer_local: str | None,
    agent: str,
) -> str:
    """Pick the edition/work base closest to local naming for subtitle joins.

    Regional alternate work titles (e.g. ``The Two Pearls of Wisdom``) lose to
    edition titles like ``Eon`` when the local corpus / desired title prefers them.
    Never uses a marketing subtitle alone (e.g. ``Dragoneye Reborn``) as the join base.
    """
    work = (work_title or "").strip()
    local = (prefer_local or "").strip()
    corpus = (naming_corpus or "").strip()
    candidates: list[str] = []
    seen: set[str] = set()
    edition_bases: set[str] = set()
    edition_subs: set[str] = set()

    def _add(s: str) -> None:
        s = (s or "").strip()
        if not s:
            return
        key = s.casefold()
        if key in seen:
            return
        seen.add(key)
        candidates.append(s)

    _add(work)
    if local:
        parts = _split_title_subtitle_parts(local)
        if parts:
            _add(parts[0])
        # Unsplit local is added only if it is an edition/work base (below), not a
        # bare marketing subtitle used as the sole local title.
    if work_key:
        for ed in _fetch_work_editions(work_key, agent=agent):
            for base in _edition_base_title_candidates(ed):
                _add(base)
                edition_bases.add(base.casefold())
            for sub in _edition_subtitle_candidates(ed):
                edition_subs.add(sub.casefold())

    if local and not _split_title_subtitle_parts(local):
        # Allow unsplit local only when it matches a known edition/work base.
        if local.casefold() in edition_bases or local.casefold() == work.casefold():
            _add(local)

    # Drop candidates that are edition subtitles but not bases (e.g. Dragoneye Reborn).
    if edition_subs:
        candidates = [
            c
            for c in candidates
            if c.casefold() not in edition_subs or c.casefold() in edition_bases
        ]

    if not candidates:
        return work

    def _score(base: str) -> tuple[float, float, float, int]:
        # Prefer bases attested in local corpus / closer to prefer_local.
        corpus_hit = 1.0 if corpus and _subtitle_attested_locally(base, corpus, min_fraction=1.0) else 0.0
        # Short bases like "Eon" need token presence, not full subtitle attestation.
        if corpus and not corpus_hit:
            corpus_tokens = set(re.findall(r"[a-z0-9]+", corpus.lower()))
            btoks = _subtitle_content_tokens(base) or [
                t for t in re.findall(r"[a-z0-9]+", base.lower()) if t
            ]
            if btoks and all(t in corpus_tokens for t in btoks):
                corpus_hit = 1.0
        local_token = fuzz.token_set_ratio(base, local) / 100 if local else 0.0
        local_ratio = fuzz.ratio(base, local) / 100 if local else 0.0
        # Prefer shorter bases when scores tie (Eon over The Two Pearls of Wisdom).
        return (corpus_hit, local_token, local_ratio, -len(base))

    return max(candidates, key=_score)


def _best_matching_edition_subtitle(
    work_key: str,
    naming_corpus: str,
    *,
    base_title: str,
    agent: str,
    prefer_local: str | None = None,
) -> str | None:
    """Best edition subtitle attested in *naming_corpus* that adds to *base_title*.

    When several candidates pass attestation, prefer the one closest to *prefer_local*
    (e.g. source/desired title ``Dragoneye Reborn`` over an unattested alternate).
    """
    if not work_key or not (naming_corpus or "").strip():
        return None
    candidates: list[str] = []
    seen: set[str] = set()
    for ed in _fetch_work_editions(work_key, agent=agent):
        for sub in _edition_subtitle_candidates(ed):
            key = sub.lower()
            if key in seen:
                continue
            seen.add(key)
            if _title_contains_subtitle(base_title, sub):
                continue
            if not _subtitle_attested_locally(sub, naming_corpus):
                continue
            candidates.append(sub)
    if not candidates:
        return None
    if prefer_local and prefer_local.strip():
        return max(
            candidates,
            key=lambda s: (
                fuzz.token_set_ratio(s, prefer_local) / 100,
                fuzz.ratio(s, prefer_local) / 100,
                len(s),
            ),
        )
    return max(candidates, key=lambda s: (len(s), s.lower()))


def _best_edition_title_score(work_key: str, query: str, *, agent: str) -> float:
    """Best fuzz.ratio of *query* vs work editions' titles/subtitles (0..1)."""
    if not work_key or not (query or "").strip():
        return 0.0
    best = 0.0
    for ed in _fetch_work_editions(work_key, agent=agent):
        for t in _edition_title_strings(ed):
            ratio, token = _title_sim(query, t)
            best = max(best, ratio, token)
    return best


def _boost_title_score_via_editions(
    title: str,
    matches: list[OpenLibrarySearchResult],
    title_res: OpenLibrarySearchResult | None,
    title_score: float,
    author_score: float | None,
    *,
    agent: str,
    max_works: int = 3,
) -> float:
    """If author is solid but work-title score is low, rescore via edition titles.

    Returns the best score (original or edition-boosted). Does not change *title_res*.
    """
    if title_res is None or not title_res.get("key"):
        return title_score
    if title_score >= OL_MATCH_MIN:
        return title_score
    if author_score is None or author_score < OL_MATCH_MIN:
        return title_score

    # Prefer works already close by title similarity; always include the chosen match.
    ranked = sorted(
        matches,
        key=lambda x: fuzz.ratio(title, x.get("title", "")),
        reverse=True,
    )
    keys: list[str] = []
    chosen = title_res.get("key") or ""
    if chosen:
        keys.append(chosen)
    for m in ranked:
        k = m.get("key") or ""
        if k and k not in keys:
            keys.append(k)
        if len(keys) >= max_works:
            break

    best = title_score
    for k in keys:
        work_title = next((m.get("title", "") for m in matches if m.get("key") == k), "")
        work_ratio, work_token = _title_sim(title, work_title)
        ed_score = _best_edition_title_score(k, title, agent=agent)
        best = max(best, work_ratio, work_token, ed_score)
        if best >= OL_MATCH_MIN:
            break
    return best


def _find_best_title(
    title: str,
    matches: list[OpenLibrarySearchResult],
    *,
    author: str | None = None,
    narrator: str | None = None,
    method: Literal["score", "similarity"] = "score",
) -> tuple[OpenLibrarySearchResult | None, float, float | None, Literal["author", "narrator"] | None]:
    """
    Returns:
        tuple[OpenLibrarySearchResult | None, float, float]
        - The best match
        - The score of the best match
        - The score of the author candidate
        - Which of author or narrator is the likely author
    """
    if not matches:
        return (None, 0.0, 0.0, None)

    score_ordered = sorted(
        matches,
        key=lambda x: (
            x.get("work_count", 0),
            x.get("ratings_count", 0),
            x.get("currently_reading_count", 0),
            x.get("read_count", 0),
            x.get("want_to_read_count", 0),
        ),
        reverse=True,
    )
    sim_ordered = sorted(matches, key=lambda x: fuzz.ratio(title, x.get("title", "")), reverse=True)

    author_sim_ordered = sorted(
        matches,
        key=lambda x: _author_name_sim(author or "", x.get("author_name")) if author else 0,
        reverse=True,
    )
    narrator_sim_ordered = sorted(
        matches,
        key=lambda x: _author_name_sim(narrator or "", x.get("author_name")) if narrator else 0,
        reverse=True,
    )

    top_scored = score_ordered[0]
    top_sim = sim_ordered[0]
    top_author_sim = author_sim_ordered[0] if author else None
    top_narrator_sim = narrator_sim_ordered[0] if narrator else None

    # If both author and narrator, figure out which one is most similar to the top_scored and top_sim books by doing fuzz.ratio on the author_name and narrator_name for both top_scored and top_sim
    # Even though we pass author and narrator in, there are no narrators in the OL search results - this is only used to determine which of the two names is more likely to be the author (in the case the id3 tags were swapped)
    author_candidate = None
    if author or narrator:
        author_candidates = list(filter(lambda a: a is not None, [top_author_sim, top_narrator_sim]))
        scores = list(
            map(
                lambda c: (
                    c,
                    max(
                        (
                            fuzz.ratio(ta, a)
                            for t in [top_scored, top_sim]
                            for ta in t.get("author_name", [])
                            for a in (c or {}).get("author_name", [])
                        ),
                        default=0,
                    ),
                ),
                author_candidates,
            )
        )
        author_candidate = max(scores, key=lambda c: c[1])[0] if scores else None

    def _get_author_sim(
        title_res: OpenLibrarySearchResult,
    ) -> tuple[float | None, Literal["author", "narrator"] | None]:
        names = title_res.get("author_name") or []
        # Use `is not None` — a real 0.0 score must not fall through as falsy.
        _author_sim: float | None = (
            None if not author else (0.0 if not author_candidate else _author_name_sim(author, names))
        )
        _narrator_sim: float | None = (
            None if not narrator else (0.0 if not author_candidate else _author_name_sim(narrator, names))
        )
        if _author_sim is not None and _narrator_sim is not None:
            if _author_sim >= _narrator_sim:
                return _author_sim, "author"
            return _narrator_sim, "narrator"
        if _author_sim is not None:
            return _author_sim, "author"
        if _narrator_sim is not None:
            return _narrator_sim, "narrator"
        return None, None

    # If top_scored and top_sim are the same, we found an easy match
    if top_scored["key"] == top_sim["key"]:
        title_sim = fuzz.ratio(title, top_scored.get("title", "")) / 100
        author_sim = _get_author_sim(top_scored)
        return (top_scored, title_sim, *author_sim)

    # Otherwise, find the title with the best score / highest similarity
    if method == "score":
        return (top_scored, fuzz.ratio(title, top_scored.get("title", "")) / 100, *_get_author_sim(top_scored))

    return (top_sim, fuzz.ratio(title, top_sim.get("title", "")) / 100, *_get_author_sim(top_sim))


class OpenLibraryAuthor:
    def __init__(self, author_res: OpenLibraryAuthorResult | None, score: float | None):
        if not author_res is None:
            self.author_res = author_res
        else:
            self.author_res = OpenLibraryAuthorResult(
                key="",
                name="",
                type="",
                work_count=0,
                alternate_names=[],
            )

        self._score = score

    def __repr__(self) -> str:
        return f"OpenLibraryAuthor(name={self.name}, score={self.score()})"

    @property
    def has_match(self) -> bool:
        return bool(self.author_res.get("key", ""))

    @property
    def name(self) -> str:
        return self.author_res.get("name", "")

    @property
    def work_count(self) -> int:
        return int(self.author_res.get("work_count", 0) or 0)

    @overload
    def score(self, *, fallback: float) -> float: ...

    @overload
    def score(self, *, fallback: float | None = None) -> float | None: ...

    def score(self, *, fallback: float | None = None) -> float | None:
        return float(self._score) if self.has_match and isinstance(self._score, (float, int)) else fallback


def open_library_lookup_author(
    author: str, *, method: Literal["score", "similarity"] = "score"
) -> OpenLibraryAuthor | None:
    """Queries the Open Library API to get the author's score.

    Make sure you follow their rules for identifying your application:
    https://openlibrary.org/developers/api

    Make sure you use your own email address, and a unique
    name other than `auto-m4b`.

    This env var should be in the following format:

    OPEN_LIBRARY_USER_AGENT=MyAppName/1.0 (myemail@example.com)
    """

    agent_string = _get_open_library_user_agent()
    if not agent_string:
        return None

    try:
        author_lower = author.lower().strip()
        author_no_periods = author_lower.replace(".", "")
        author_period_spaces = re.sub(r"\s+", " ", author_lower.replace(".", ". "))
        matches = []
        exact_matches = []
        found = 0
        for name in list(set([author_lower, author_no_periods, author_period_spaces])):
            url = f"https://openlibrary.org/search/authors.json?q={urllib.parse.quote_plus(name)}"
            response = requests.get(url, headers={"User-Agent": agent_string})
            response.raise_for_status()
            data = response.json()
            matches.extend(
                [OpenLibraryAuthorResult(**d) for d in data.get("docs", []) if d.get("type", "") == "author"]
            )
            found += data["numFound"]
            exact_matches.extend(
                [
                    OpenLibraryAuthorResult(**d)
                    for d in matches
                    if d["name"].lower() == name or _in_alternate_names(name, d)
                ]
            )

        # dedupe matches by key - which are lists of dicts, so we can't use a set()
        matches = list({d["key"]: d for d in matches}.values())
        exact_matches = list({d["key"]: d for d in exact_matches}.values())

        exact_with_works = [d for d in exact_matches if d.get("work_count", 0) > 0]
        exact_with_ratings = [d for d in exact_matches if d.get("ratings_count", 0) > 0]
        max_works = max_if((d.get("work_count", 0) for d in exact_matches), 0)
        max_to_read = max_if((d.get("want_to_read_count", 0) for d in exact_matches), 0)
        max_reading = max_if((d.get("currently_reading_count", 0) for d in exact_matches), 0)
        max_read = max_if((d.get("read_count", 0) for d in exact_matches), 0)

        exact_len = len(exact_matches)
        w_works_len = len(exact_with_works)
        w_ratings_len = len(exact_with_ratings)

        base_score = 0.0
        if found:
            base_score += min(0.25, found / 10)
        if max_works:
            base_score += max(0.5, log10(max_works))

        for m in [max_to_read, max_reading, max_read]:
            if m:
                base_score += min(0.25, m / 10)
            else:
                base_score -= 0.2

        best_author = None

        if exact_len:
            base_score += max(1.0, log10(exact_len * 10))
            best_author, _best_score = _find_best_author(author, exact_matches, method=method)

            for m in [w_works_len, w_ratings_len]:
                if m < exact_len:
                    base_score -= (1 - (m / exact_len)) / 2
                else:
                    base_score += min(0.25, m / 10)
        else:
            best_author, best_score = _find_best_author(author, matches, method="similarity")
            base_score -= 1 - best_score

        # If best_author has a negative score, return an empty author
        if base_score < 0:
            return OpenLibraryAuthor(None, None)

        return OpenLibraryAuthor(best_author, round(base_score, 3))
    except Exception as e:
        print_debug(f"Error looking up author {author} from Open Library: {e}")
        if "pytest" in sys.modules:
            raise e
        return None


class OpenLibraryTitle:
    def __init__(
        self,
        title_res: OpenLibrarySearchResult | None,
        score: float | None,
        author_score: float | None,
        author_prop: Literal["author", "narrator"] | None,
        *,
        original_author: str | None,
        original_narrator: str | None,
    ):
        if not title_res is None:
            self.title_res = title_res
        else:
            self.title_res = OpenLibrarySearchResult(
                key="",
                author_key=[],
                author_name=[],
                type="",
                name="",
                alternate_names=[],
                work_count=0,
                ratings_count=0,
                currently_reading_count=0,
                read_count=0,
                want_to_read_count=0,
                cover_edition_key="",
                cover_i=0,
                ebook_access="",
                edition_count=0,
                first_publish_year=0,
                has_fulltext=False,
            )
        self._score = score

        self._author_score = author_score
        self.author_prop = author_prop
        self.original_author = original_author
        self.original_narrator = original_narrator

    def __repr__(self) -> str:
        return f"OpenLibraryTitle(title={self.title}, score={self.score()}, author_score={self.author_score()}, author_prop={self.author_prop})"

    @property
    def has_match(self) -> bool:
        return bool(self.title_res.get("key", ""))

    @property
    def title(self) -> str:
        return self.title_res.get("title", "") if self.has_match else ""

    @overload
    def score(self, *, fallback: float) -> float: ...

    @overload
    def score(self, *, fallback: float | None = None) -> float | None: ...

    def score(self, *, fallback: float | None = None) -> float | None:
        return float(self._score) if self.has_match and isinstance(self._score, (float, int)) else fallback

    @overload
    def author_score(self, *, fallback: float) -> float: ...

    @overload
    def author_score(self, *, fallback: float | None = None) -> float | None: ...

    def author_score(self, *, fallback: float | None = None) -> float | None:
        return (
            float(self._author_score) if self.has_match and isinstance(self._author_score, (float, int)) else fallback
        )

    def _get_author_or_narrator(self, prop: Literal["author", "narrator"]) -> str:
        original = self.original_author if prop == "author" else self.original_narrator
        if authors := self.title_res.get("author_name", [""]):
            # return the first if there is no original author, otherwise the one with the highest fuzz.ratio
            if not original:
                return authors[0]
            else:
                return max(authors, key=lambda x: fuzz.ratio(original or "", x))
        return ""

    @property
    def author(self) -> str:
        # When tags were swapped, original_narrator is the real author — pick the
        # OL author_name closest to that input. Never recurse through .narrator.
        if self.author_and_narrator_swapped:
            return self._get_author_or_narrator("narrator")
        return self._get_author_or_narrator("author")

    @property
    def author_and_narrator_swapped(self) -> bool:
        return self.author_prop == "narrator"

    @property
    def narrator(self) -> str:
        if not self.has_match:
            return ""
        if self.author_and_narrator_swapped and self.original_author:
            # Mislabeled "author" input was actually the performer/narrator.
            return self.original_author
        return self.original_narrator or ""

    @property
    def date(self) -> str:
        return str(self.title_res.get("first_publish_year", "")) if self.has_match else ""

    @property
    def key(self) -> str:
        return self.title_res.get("key", "") if self.has_match else ""

    @property
    def url(self) -> str:
        return f"https://openlibrary.org{self.key}" if self.key else ""


def ol_match_band(ol: "OpenLibraryTitle | None") -> Literal["match", "low_confidence", "none", "skipped"]:
    """Classify an OL title result for fix_metadata display / apply gating."""
    if ol is None:
        return "skipped"
    if not ol.has_match:
        return "none"
    score = ol.score(fallback=0.0)
    if score >= OL_MATCH_MIN:
        return "match"
    if score >= OL_LOW_CONFIDENCE_MIN:
        return "low_confidence"
    return "none"


def open_library_lookup_title(
    title: str,
    *,
    author: str | None = None,
    narrator: str | None = None,
    method: Literal["score", "similarity"] = "score",
) -> OpenLibraryTitle | None:
    """Queries the Open Library API to get the title's score.

    Make sure you follow their rules for identifying your application:
    https://openlibrary.org/developers/api

    Make sure you use your own email address, and a unique
    name other than `auto-m4b`.

    This env var should be in the following format:

    OPEN_LIBRARY_USER_AGENT=MyAppName/1.0 (myemail@example.com)
    """

    from src.lib.patterns import junk_chars_title_pattern, title_chunk_pattern

    agent_string = _get_open_library_user_agent()
    if not agent_string:
        return None

    author_result = (None, 0.0)
    narrator_result = (None, 0.0)
    authors = []

    if author and (author_result := open_library_lookup_author(author, method="similarity")):
        if (a_name := author_result.name) and a_name:
            authors.append(a_name)
    if narrator and (narrator_result := open_library_lookup_author(narrator, method="similarity")):
        if (n_name := narrator_result.name) and n_name:
            authors.append(n_name)

    try:
        title_lower = title.lower().strip()
        title_no_periods = title_lower.replace(".", "")
        title_no_punctuation = junk_chars_title_pattern.sub("", title_lower)
        title_unchunked = title_chunk_pattern.sub("", title_lower)

        matches = []
        found = 0
        for t in list(set([title_lower, title_no_periods, title_no_punctuation, title_unchunked])):
            urls = (
                [
                    f"https://openlibrary.org/search.json?title={urllib.parse.quote_plus(t)}&author={urllib.parse.quote_plus(a)}"
                    for a in authors
                ]
                if authors
                else [f"https://openlibrary.org/search.json?title={urllib.parse.quote_plus(t)}"]
            )
            for url in urls:
                response = requests.get(url, headers={"User-Agent": agent_string})
                response.raise_for_status()
                data = response.json()
                matches.extend([OpenLibrarySearchResult(**d) for d in data.get("docs", [])])
                found += data["numFound"]

        # Structured title= often misses edition subtitles / alt marketing titles
        # (e.g. "Dragoneye Reborn" → work titled "Eon"). Fall back to free-text q=.
        if not matches:
            for t in list(set([title_lower, title_no_periods, title_no_punctuation, title_unchunked])):
                urls = (
                    [
                        f"https://openlibrary.org/search.json?q={urllib.parse.quote_plus(t)}&author={urllib.parse.quote_plus(a)}"
                        for a in authors
                    ]
                    if authors
                    else [f"https://openlibrary.org/search.json?q={urllib.parse.quote_plus(t)}"]
                )
                for url in urls:
                    response = requests.get(url, headers={"User-Agent": agent_string}, timeout=30)
                    response.raise_for_status()
                    data = response.json()
                    matches.extend([OpenLibrarySearchResult(**d) for d in data.get("docs", [])])
                    found += data.get("numFound") or 0

        title_res, title_score, author_score, author_kind = _find_best_title(
            title, matches, author=author, narrator=narrator, method=method
        )
        # Author resolved onto the query counts as enough confidence to try editions,
        # even when per-doc author_score is missing/weak.
        author_gate = author_score
        if author_gate is None or author_gate < OL_MATCH_MIN:
            if authors:
                author_gate = OL_MATCH_MIN
        title_score = _boost_title_score_via_editions(
            title,
            matches,
            title_res,
            title_score,
            author_gate,
            agent=agent_string,
        )
        return OpenLibraryTitle(
            title_res,
            title_score,
            author_score,
            author_kind,
            original_author=author,
            original_narrator=narrator,
        )
    except requests.exceptions.HTTPError as e:
        print_debug(f"Error looking up title  from Open Library: {e}")
        return None
    except Exception as e:
        print_debug(f"Error looking up title {title} from Open Library: {e}")
        if "pytest" in sys.modules:
            raise e
        return None


_OL_PATH_REF = re.compile(
    r"(?:https?://(?:www\.)?openlibrary\.org)?/?(?P<kind>works|books)/(?P<id>OL\d+[WMwm])\b",
    re.I,
)
_OL_BARE_REF = re.compile(r"^(?P<id>OL\d+)(?P<suffix>[WMwm])$", re.I)


def parse_ol_ref(raw: str) -> tuple[Literal["works", "books"], str] | None:
    """Parse an Open Library URL or id into ``(works|books, OLxxxxW|M)``.

    Accepts:
    - ``https://openlibrary.org/works/OL123W``
    - ``/works/OL123W`` / ``works/OL123W``
    - ``https://openlibrary.org/books/OL123M``
    - bare ``OL123W`` / ``OL123M``
    """
    s = (raw or "").strip()
    if not s:
        return None
    m = _OL_PATH_REF.search(s)
    if m:
        kind = m.group("kind").lower()
        olid = m.group("id").upper()
        # Normalize suffix letter
        olid = olid[:-1] + olid[-1].upper()
        return kind, olid  # type: ignore[return-value]
    m = _OL_BARE_REF.match(s)
    if m:
        suffix = m.group("suffix").upper()
        olid = f"{m.group('id').upper()}{suffix}"
        kind: Literal["works", "books"] = "works" if suffix == "W" else "books"
        return kind, olid
    return None


def open_library_fetch_by_ref(
    ref: str,
    *,
    original_author: str | None = None,
    original_narrator: str | None = None,
) -> OpenLibraryTitle | None:
    """Fetch a work/edition by Open Library URL or id and wrap as ``OpenLibraryTitle``.

    Raises ``ValueError`` if *ref* cannot be parsed. Returns ``None`` if the user
    agent is unset or the API returns no usable doc.
    """
    parsed = parse_ol_ref(ref)
    if not parsed:
        raise ValueError(
            f"Unrecognized Open Library ref: {ref!r} "
            "(expected works/OL…W, books/OL…M, or a full openlibrary.org URL)"
        )
    kind, olid = parsed

    agent_string = _get_open_library_user_agent()
    if not agent_string:
        return None

    key = f"/{kind}/{olid}"
    try:
        # Search by key — returns author_name / title in one round-trip.
        url = f"https://openlibrary.org/search.json?q={urllib.parse.quote(f'key:{key}')}"
        response = requests.get(url, headers={"User-Agent": agent_string}, timeout=30)
        response.raise_for_status()
        docs = response.json().get("docs") or []
        match = next((d for d in docs if d.get("key") == key), None)
        if match is None and docs:
            match = docs[0]
        if match is None:
            # Fallback: direct works/books JSON (title only; authors may be keys)
            direct = f"https://openlibrary.org{key}.json"
            response = requests.get(direct, headers={"User-Agent": agent_string}, timeout=30)
            response.raise_for_status()
            data = response.json()
            title = data.get("title") or ""
            author_names: list[str] = []
            for a in data.get("authors") or []:
                # works: {"author": {"key": "/authors/OL…A"}}; editions vary
                akey = None
                if isinstance(a, dict):
                    akey = (a.get("author") or {}).get("key") if "author" in a else a.get("key")
                if akey:
                    ar = requests.get(
                        f"https://openlibrary.org{akey}.json",
                        headers={"User-Agent": agent_string},
                        timeout=30,
                    )
                    if ar.ok:
                        author_names.append(ar.json().get("name") or "")
            match = {
                "key": key,
                "title": title,
                "author_name": [n for n in author_names if n],
                "author_key": [],
                "work_count": 1,
                "edition_count": 1,
                "name": title,
                "first_publish_year": data.get("first_publish_date") or data.get("publish_date") or 0,
            }
        year_raw = match.get("first_publish_year") or 0
        year = int(year_raw) if str(year_raw).isdigit() else 0
        safe = OpenLibrarySearchResult(
            key=str(match.get("key") or key),
            author_key=list(match.get("author_key") or []),
            author_name=list(match.get("author_name") or []),
            type=str(match.get("type") or ""),
            name=str(match.get("name") or match.get("title") or ""),
            work_count=int(match.get("work_count") or 1),
            edition_count=int(match.get("edition_count") or 1),
            title=str(match.get("title") or match.get("name") or ""),
            first_publish_year=year,
        )
        return OpenLibraryTitle(
            safe,
            1.0,
            1.0,
            "author",
            original_author=original_author,
            original_narrator=original_narrator,
        )
    except requests.exceptions.RequestException as e:
        print_debug(f"Error fetching Open Library ref {ref}: {e}")
        return None
    except Exception as e:
        print_debug(f"Error fetching Open Library ref {ref}: {e}")
        if "pytest" in sys.modules:
            raise e
        return None
