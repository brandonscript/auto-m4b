"""bookpeek adapter for auto-m4b metadata (ASR + Audnexus + optional GR/OL corroboration)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

from cachetools import TTLCache
from rapidfuzz import fuzz

from src.lib.config import cfg
from src.lib.term import print_debug, print_warning
from src.lib.typing import MEMO_TTL

if TYPE_CHECKING:
    from bookpeek.models import BookPeekResult

    from src.lib.metadata.providers import MetadataCandidate, MetadataComparison

_BOOKPEEK_SCAN_CACHE: TTLCache[tuple[object, ...], object] = TTLCache(maxsize=64, ttl=MEMO_TTL)
_BOOKPEEK_SCAN_LOCK = RLock()


@dataclass(frozen=True)
class BookPeekCorroboration:
    """Which direct providers bookpeek's nested online hits agreed with."""

    goodreads: bool = False
    openlibrary: bool = False


def bookpeek_enabled() -> bool:
    return bool(getattr(cfg, "BOOKPEEK", False))


def bookpeek_should_run_online() -> bool:
    """Online by default when auto-m4b already has GR and/or OL user agents."""
    return bool(cfg.GOODSCRAPS_USER_AGENT or cfg.OPEN_LIBRARY_USER_AGENT)


def clear_bookpeek_scan_cache() -> None:
    with _BOOKPEEK_SCAN_LOCK:
        _BOOKPEEK_SCAN_CACHE.clear()


def _bookpeek_scan_cache_key(audio_path: Path, online: bool) -> tuple[object, ...]:
    path = Path(audio_path)
    st = path.stat()
    return (str(path.resolve()), st.st_size, st.st_mtime_ns, online)


def build_bookpeek_config():
    """Build BookPeekConfig from auto-m4b settings (reuses GR/OL UAs; no duplicate env)."""
    from bookpeek import BookPeekConfig, EnrichConfig

    gr_ua = (cfg.GOODSCRAPS_USER_AGENT or "").strip() or None
    ol_ua = (cfg.OPEN_LIBRARY_USER_AGENT or "").strip() or None
    online = bookpeek_should_run_online()
    return BookPeekConfig(
        enrich=EnrichConfig(
            enabled=online,
            goodreads=bool(gr_ua),
            openlibrary=bool(ol_ua),
            audnexus=True,
            goodreads_user_agent=gr_ua,
            openlibrary_user_agent=ol_ua,
            goodreads_timeout=float(cfg.GOODSCRAPS_TIMEOUT or 30),
            openlibrary_timeout=float(cfg.OPEN_LIBRARY_TIMEOUT or 15),
        )
    )


def scan_bookpeek(audio_path: Path, *, online: bool | None = None) -> BookPeekResult | None:
    """Run bookpeek on a sample audio file. Soft-fails if deps/ASR unavailable."""
    if not bookpeek_enabled():
        return None
    if not audio_path or not Path(audio_path).is_file():
        print_debug(f"bookpeek: skip, missing audio {audio_path}")
        return None
    try:
        from bookpeek import BookPeek
    except ImportError as exc:
        print_warning(f"BOOKPEEK is enabled but bookpeek is not importable: {exc}")
        return None

    run_online = bookpeek_should_run_online() if online is None else online
    try:
        cache_key = _bookpeek_scan_cache_key(Path(audio_path), run_online)
    except OSError:
        cache_key = None
    if cache_key is not None:
        with _BOOKPEEK_SCAN_LOCK:
            cached = _BOOKPEEK_SCAN_CACHE.get(cache_key)
        if cached is not None:
            print_debug(f"bookpeek: cache hit for {Path(audio_path).name}")
            return cached  # type: ignore[return-value]

    try:
        client = BookPeek(build_bookpeek_config())
        result = client.scan(Path(audio_path), online=run_online)
    except Exception as exc:
        print_warning(f"bookpeek scan failed for {Path(audio_path).name}: {exc}")
        print_debug(f"bookpeek error detail: {exc!r}")
        return None

    if result is not None and cache_key is not None:
        with _BOOKPEEK_SCAN_LOCK:
            _BOOKPEEK_SCAN_CACHE[cache_key] = result
    return result


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return max(fuzz.ratio(left, right), fuzz.token_set_ratio(left, right)) / 100


def _best_work(result: BookPeekResult, provider: str):
    matches = (result.online_matches or {}).get(provider)
    works = getattr(matches, "works", None) or []
    if not works:
        return None
    return max(works, key=lambda w: getattr(w, "score", 0) or 0)


def _best_audnexus(result: BookPeekResult):
    return _best_work(result, "audnexus")


def bookpeek_to_candidate(result: BookPeekResult) -> MetadataCandidate:
    from src.lib.metadata.providers import MetadataCandidate, _status

    aud = _best_audnexus(result)
    narrators = list(result.narrators or [])
    if aud and getattr(aud, "narrators", None):
        # Prefer Audnexus-verified names when present
        narrators = list(aud.narrators) or narrators
    narrator = narrators[0] if narrators else ""
    asin = getattr(aud, "asin", "") or ""
    score = float(getattr(aud, "score", 0) or 0)
    if not score and (result.title or result.author):
        score = 0.55 if result.title and result.author else 0.4
    status = _status(score) if (result.title or result.author or narrator) else "none"
    return MetadataCandidate(
        provider="bookpeek",
        title=result.title or "",
        author=result.author or "",
        narrator=narrator,
        year="",
        ref=asin,
        url="",
        score=score,
        status=status,
    )


def corroborate_providers(
    comparison: MetadataComparison,
    result: BookPeekResult,
) -> BookPeekCorroboration:
    """Mark direct GR/OL candidates as corroborated when bookpeek nested hits agree.

    Does not add nested GR/OL as separate candidates.
    """
    from src.lib.metadata.providers import MetadataCandidate, _status

    gr_flag = False
    ol_flag = False
    direct_gr = comparison.candidates.get("goodreads")
    direct_ol = comparison.candidates.get("openlibrary")
    bp_gr = _best_work(result, "goodreads")
    bp_ol = _best_work(result, "openlibrary")

    def _agrees(direct: MetadataCandidate | None, work) -> bool:
        if not direct or not work or direct.status in ("skipped", "error", "none"):
            return False
        title = getattr(work, "title_complete", None) or getattr(work, "title", "") or ""
        author = getattr(work, "author", "") or ""
        title_ok = not direct.title or not title or _similarity(direct.title, title) >= 0.85
        author_ok = not direct.author or not author or _similarity(direct.author, author) >= 0.85
        return bool(title_ok and author_ok and (direct.title or direct.author))

    def _bump(direct: MetadataCandidate) -> MetadataCandidate:
        new_score = min(1.0, (direct.score or 0) + 0.05)
        status = direct.status
        if status == "none":
            status = _status(new_score)
        return MetadataCandidate(
            provider=direct.provider,
            title=direct.title,
            author=direct.author,
            narrator=direct.narrator,
            year=direct.year,
            ref=direct.ref,
            url=direct.url,
            score=new_score,
            status=status,
            error=direct.error,
        )

    if _agrees(direct_gr, bp_gr) and direct_gr:
        gr_flag = True
        comparison.candidates["goodreads"] = _bump(direct_gr)
    if _agrees(direct_ol, bp_ol) and direct_ol:
        ol_flag = True
        comparison.candidates["openlibrary"] = _bump(direct_ol)

    # Fill empty GR/OL display from bookpeek nested hits when direct lookup was skipped
    if (not direct_gr or direct_gr.status == "skipped") and bp_gr:
        title = getattr(bp_gr, "title_complete", None) or getattr(bp_gr, "title", "") or ""
        author = getattr(bp_gr, "author", "") or ""
        score = float(getattr(bp_gr, "score", 0) or 0)
        comparison.candidates["goodreads"] = MetadataCandidate(
            provider="goodreads",
            title=title,
            author=author,
            score=score,
            status=_status(score),
        )
        gr_flag = True
    if (not direct_ol or direct_ol.status == "skipped") and bp_ol:
        title = getattr(bp_ol, "title", "") or ""
        author = getattr(bp_ol, "author", "") or ""
        score = float(getattr(bp_ol, "score", 0) or 0)
        comparison.candidates["openlibrary"] = MetadataCandidate(
            provider="openlibrary",
            title=title,
            author=author,
            score=score,
            status=_status(score),
        )
        ol_flag = True

    return BookPeekCorroboration(goodreads=gr_flag, openlibrary=ol_flag)


def maybe_apply_bookpeek_fallback(
    comparison: MetadataComparison,
    bp_candidate: MetadataCandidate,
) -> None:
    """If GR/OL are weak/missing, allow confident bookpeek title/author as selected."""
    selected = comparison.selected
    if bp_candidate.status not in ("match", "low_confidence"):
        return
    if selected and selected.status in ("match", "forced"):
        return
    if not selected or selected.status in ("none", "skipped", "error", "low_confidence"):
        if bp_candidate.status == "match" or (
            bp_candidate.status == "low_confidence"
            and (not selected or selected.status != "low_confidence")
        ):
            comparison.selected = bp_candidate


def bookpeek_conflicts_against_selected(
    comparison: MetadataComparison,
    bp_candidate: MetadataCandidate,
) -> list[str]:
    """Conflicts only when bookpeek meaningfully disagrees with the selected GR/OL hit."""
    selected = comparison.selected
    if not selected or selected.provider == "bookpeek":
        return []
    if not bp_candidate.confident or not selected.confident:
        return []
    conflicts: list[str] = []
    if bp_candidate.title and selected.title and _similarity(bp_candidate.title, selected.title) < 0.85:
        conflicts.append(f"title: {selected.provider}={selected.title!r}, bookpeek={bp_candidate.title!r}")
    if bp_candidate.author and selected.author and _similarity(bp_candidate.author, selected.author) < 0.85:
        conflicts.append(f"author: {selected.provider}={selected.author!r}, bookpeek={bp_candidate.author!r}")
    return conflicts
