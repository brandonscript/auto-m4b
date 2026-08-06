"""Provider-neutral metadata lookup and comparison."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import re
from threading import RLock
from dataclasses import dataclass, field

from cachetools import TTLCache
from goodscraps import Goodscraps
from rapidfuzz import fuzz

from src.lib.cleaners import fix_smart_quotes, minimalist_title
from src.lib.config import cfg
from src.lib.term import print_debug
from src.lib.typing import MEMO_TTL

_PROVIDER_CACHE: TTLCache[tuple[object, ...], MetadataComparison] = TTLCache(maxsize=256, ttl=MEMO_TTL)
_PROVIDER_CACHE_LOCK = RLock()


_SERIES_NUMBER_PREFIX = re.compile(
    r"^\s*.+?\s+\d{1,3}\s*[:\-–—]\s*(?P<title>\S.*)$"
)


@dataclass(frozen=True)
class MetadataCandidate:
    """Normalized metadata returned by one provider."""

    provider: str
    title: str = ""
    author: str = ""
    narrator: str = ""
    year: str = ""
    ref: str = ""
    url: str = ""
    score: float = 0.0
    status: str = "none"
    error: str = ""

    def __post_init__(self) -> None:
        """Keep provider-returned text safe for display, comparison, and tags."""
        for field_name in ("title", "author", "narrator", "error"):
            object.__setattr__(self, field_name, fix_smart_quotes(getattr(self, field_name)))

    @property
    def confident(self) -> bool:
        return self.status == "match"


@dataclass
class MetadataComparison:
    """Results from all enabled providers and the selected candidate."""

    candidates: dict[str, MetadataCandidate] = field(default_factory=dict)
    selected: MetadataCandidate | None = None
    conflicts: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.selected is None:
            return "none"
        return self.selected.status


def _status(score: float) -> str:
    if score >= 0.5:
        return "match"
    if score >= 0.35:
        return "low_confidence"
    return "none"


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return max(fuzz.ratio(left, right), fuzz.token_set_ratio(left, right)) / 100


def _strict_title_similarity(left: str, right: str, author: str = "") -> float:
    """Score the complete title while still allowing minor punctuation changes.

    ``token_set_ratio`` is intentionally permissive, but it gives a perfect score
    when a short title is merely contained in a much longer title. Use the full
    string ratio as the tie-breaker so an exact book title beats an anthology,
    companion work, or reference title containing the same words.
    """
    left = minimalist_title(left, author=author).casefold()
    right = minimalist_title(right, author=author).casefold()
    if not left or not right:
        return 0.0
    if right == left:
        return 1.0
    if right.startswith(f"{left} (") and right.endswith(")"):
        return 1.0
    if right.startswith(f"{left} ") or right.startswith(f"{left}:"):
        return 0.95
    return fuzz.ratio(left, right) / 100


def _series_number_core_title(title: str) -> str:
    """Remove a leading ``Series NN:``/``Series NN -`` prefix when present."""
    match = _SERIES_NUMBER_PREFIX.match(title or "")
    return match.group("title").strip() if match else (title or "").strip()


def _goodreads_lookup(
    title: str,
    author: str,
    narrator: str,
    *,
    ref: str | None = None,
) -> MetadataCandidate:
    if not cfg.GOODSCRAPS_USER_AGENT:
        return MetadataCandidate(provider="goodreads", status="skipped")

    try:
        normalized_ref = ref
        if ref:
            match = re.search(r"/book/(?:show/)?(\d+)", ref)
            normalized_ref = match.group(1) if match else ref
        with Goodscraps(
            timeout=cfg.GOODSCRAPS_TIMEOUT,
            user_agent=cfg.GOODSCRAPS_USER_AGENT,
        ) as client:
            if ref:
                score = 1.0
                best = None
                book = client.book(normalized_ref)
            else:
                search_bases = [title]
                core_title = minimalist_title(title, author=author)
                if core_title != title:
                    search_bases.append(core_title)
                series_core_title = _series_number_core_title(title)
                if series_core_title not in search_bases:
                    search_bases.append(series_core_title)
                search_queries = [
                    query
                    for base in search_bases
                    for query in ((f"{base} {author}", base) if author else (base,))
                ]
                matches = []
                seen_ids: set[int] = set()
                for query in search_queries:
                    try:
                        query_matches = client.search(
                            query,
                            limit=10,
                        )
                    except Exception as exc:
                        print_debug(f"Goodreads search failed for {query!r}: {exc}")
                        continue
                    for item in query_matches:
                        if item.book_id not in seen_ids:
                            seen_ids.add(item.book_id)
                            matches.append(item)
                if not matches:
                    return MetadataCandidate(provider="goodreads", status="none")

                def scored_match(item) -> tuple[float, float, float, float]:
                    title_score = _similarity(title, item.title)
                    author_score = (
                        _similarity(author, item.author.name if item.author else "")
                        if author
                        else title_score
                    )
                    strict_title_score = _strict_title_similarity(
                        title, item.title, author=author
                    )
                    return (
                        title_score * 0.7 + author_score * 0.3,
                        author_score,
                        title_score,
                        strict_title_score,
                    )

                scored = [(item, *scored_match(item)) for item in matches]
                exact_title_matches = [row for row in scored if row[4] >= 0.95]
                author_matches = [row for row in scored if row[2] >= 0.5] if author else []
                if exact_title_matches:
                    best, score, _author_score, _title_score, _strict_title_score = max(
                        exact_title_matches,
                        key=lambda row: (row[4], row[2], row[3], row[1]),
                    )
                elif author_matches:
                    best, score, _author_score, _title_score, _strict_title_score = max(
                        author_matches,
                        key=lambda row: (row[2], row[4], row[3], row[1]),
                    )
                else:
                    best, score, _author_score, _title_score, _strict_title_score = max(
                        scored,
                        key=lambda row: (row[4], row[3], row[1]),
                    )
                book_id = client.canonical_book_id(best.book_id)
                book = client.book(book_id)
            canonical_author = book.author.name if book.author else (best.author.name if best and best.author else "")
            return MetadataCandidate(
                provider="goodreads",
                title=book.title or (best.title if best else ""),
                author=canonical_author,
                year=str(book.first_published_year or ""),
                ref=str(book.book_id),
                url=book.url or (best.url if best else "") or "",
                score=score,
                status="forced" if ref else _status(score),
            )
    except Exception as exc:
        print_debug(f"Error looking up {title!r} from Goodreads: {exc}")
        return MetadataCandidate(provider="goodreads", status="error", error=str(exc))


def _open_library_lookup(title: str, author: str, narrator: str) -> MetadataCandidate:
    try:
        from src.lib.ol_lookup import ol_match_band, open_library_lookup_title

        result = open_library_lookup_title(
            title,
            author=author or None,
            narrator=narrator or None,
            method="similarity",
        )
        band = ol_match_band(result)
        if result is None:
            return MetadataCandidate(provider="openlibrary", status=band)
        return MetadataCandidate(
            provider="openlibrary",
            title=result.title,
            author=result.author,
            narrator=result.narrator,
            year=result.date,
            ref=result.key,
            url=result.url,
            score=result.score(fallback=0.0),
            status=band,
        )
    except Exception as exc:
        print_debug(f"Error looking up {title!r} from Open Library: {exc}")
        return MetadataCandidate(provider="openlibrary", status="error", error=str(exc))


def _add_conflicts(comparison: MetadataComparison) -> None:
    goodreads = comparison.candidates.get("goodreads")
    open_library = comparison.candidates.get("openlibrary")
    if not goodreads or not open_library or not goodreads.confident or not open_library.confident:
        return

    fields = (
        ("title", goodreads.title, open_library.title),
        ("author", goodreads.author, open_library.author),
        ("year", goodreads.year, open_library.year),
    )
    for name, left, right in fields:
        if left and right and (name == "year" and left != right or name != "year" and _similarity(left, right) < 0.85):
            comparison.conflicts.append(f"{name}: Goodreads={left!r}, Open Library={right!r}")


def lookup_metadata(
    title: str,
    *,
    author: str = "",
    narrator: str = "",
    lookup_goodreads: bool = True,
    lookup_open_library: bool = True,
    goodreads_ref: str | None = None,
) -> MetadataComparison:
    """Query enabled providers and select Goodreads before Open Library."""
    cache_key = (
        title,
        author,
        narrator,
        lookup_goodreads,
        lookup_open_library,
        goodreads_ref,
        cfg.GOODSCRAPS_USER_AGENT,
        cfg.GOODSCRAPS_TIMEOUT,
        cfg.OPEN_LIBRARY_TIMEOUT,
    )
    with _PROVIDER_CACHE_LOCK:
        if cached := _PROVIDER_CACHE.get(cache_key):
            return deepcopy(cached)

    comparison = MetadataComparison()
    lookups = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        if lookup_goodreads:
            lookups["goodreads"] = executor.submit(
                _goodreads_lookup,
                title,
                author,
                narrator,
                ref=goodreads_ref,
            )
        if lookup_open_library:
            lookups["openlibrary"] = executor.submit(
                _open_library_lookup,
                title,
                author,
                narrator,
            )
        for provider, future in lookups.items():
            comparison.candidates[provider] = future.result()

    _add_conflicts(comparison)
    goodreads = comparison.candidates.get("goodreads")
    open_library = comparison.candidates.get("openlibrary")
    if goodreads and goodreads.status in ("match", "forced"):
        comparison.selected = goodreads
    elif open_library and open_library.status == "match":
        comparison.selected = open_library
    elif goodreads and goodreads.status == "low_confidence":
        comparison.selected = goodreads
    elif open_library and open_library.status == "low_confidence":
        comparison.selected = open_library
    with _PROVIDER_CACHE_LOCK:
        _PROVIDER_CACHE[cache_key] = deepcopy(comparison)
    return comparison


def clear_provider_cache() -> None:
    """Clear in-process provider results after configuration or test changes."""
    with _PROVIDER_CACHE_LOCK:
        _PROVIDER_CACHE.clear()
