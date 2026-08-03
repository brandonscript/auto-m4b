"""Provider-neutral metadata lookup and comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from goodscraps import Goodscraps
from rapidfuzz import fuzz

from src.lib.cleaners import minimalist_title
from src.lib.config import cfg
from src.lib.term import print_debug


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
                matches = client.search(title, limit=10)
                if not matches and minimalist_title(title, author=author) != title:
                    matches = client.search(minimalist_title(title, author=author), limit=10)
                if not matches:
                    return MetadataCandidate(provider="goodreads", status="none")

                def scored_match(item) -> tuple[float, float, float]:
                    title_score = _similarity(title, item.title)
                    author_score = _similarity(author, item.author_name or "") if author else title_score
                    return title_score * 0.7 + author_score * 0.3, author_score, title_score

                scored = [(item, *scored_match(item)) for item in matches]
                author_matches = [row for row in scored if row[2] >= 0.5] if author else []
                if author_matches:
                    best, score, _author_score, _title_score = max(
                        author_matches,
                        key=lambda row: (row[2], row[3], row[1]),
                    )
                else:
                    best, score, _author_score, _title_score = max(
                        scored,
                        key=lambda row: row[1],
                    )
                book = client.book(best.book_id)
            primary = book.author_primary or (book.authors[0] if book.authors else None)
            canonical_author = primary.name if primary else (best.author_name if best else "")
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
    comparison = MetadataComparison()
    if lookup_goodreads:
        comparison.candidates["goodreads"] = _goodreads_lookup(
            title,
            author,
            narrator,
            ref=goodreads_ref,
        )
    if lookup_open_library:
        comparison.candidates["openlibrary"] = _open_library_lookup(title, author, narrator)

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
    return comparison
