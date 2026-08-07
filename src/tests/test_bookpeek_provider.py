"""Tests for bookpeek adapter, UA passthrough, and GR/OL corroboration consolidation."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.fix_metadata import build_arg_parser, print_plan
from src.lib.config import cfg
from fixm4b.metadata import providers
from src.lib.metadata.bookpeek_provider import (
    bookpeek_to_candidate,
    build_bookpeek_config,
    corroborate_providers,
    scan_bookpeek,
)
from src.lib.metadata.models import FixPlan, TagSnapshot
from src.lib.metadata.plan import _attach_provider_comparison


def _fake_result(
    *,
    title="The Blighted Stars",
    author="Megan E. O'Keefe",
    narrators=None,
    gr_title=None,
    gr_author=None,
    gr_score=0.9,
    ol_title=None,
    ol_author=None,
    ol_score=0.9,
    asin="B0TEST",
):
    narrators = narrators or ["Ciaran Saward"]
    gr_works = []
    if gr_title:
        gr_works.append(SimpleNamespace(title=gr_title, title_complete=gr_title, author=gr_author, score=gr_score))
    ol_works = []
    if ol_title:
        ol_works.append(SimpleNamespace(title=ol_title, author=ol_author, score=ol_score))
    aud_works = [
        SimpleNamespace(title=title, authors=[author], narrators=narrators, asin=asin, score=0.93, region="us")
    ]
    return SimpleNamespace(
        title=title,
        author=author,
        narrators=narrators,
        transcript=SimpleNamespace(engine="whisper", model="tiny.en", seconds=60.0),
        online_matches={
            "goodreads": SimpleNamespace(works=gr_works, authors=[]),
            "openlibrary": SimpleNamespace(works=ol_works, authors=[]),
            "audnexus": SimpleNamespace(works=aud_works, authors=[], narrators=narrators),
        },
    )


def test_build_bookpeek_config_reuses_autom4b_user_agents(monkeypatch):
    monkeypatch.setattr(cfg, "GOODSCRAPS_USER_AGENT", "auto-m4b/1.0 (gr@example.com)")
    monkeypatch.setattr(cfg, "OPEN_LIBRARY_USER_AGENT", "MyApp/1.0 (ol@example.com)")
    monkeypatch.setattr(cfg, "GOODSCRAPS_TIMEOUT", 22.0)
    monkeypatch.setattr(cfg, "OPEN_LIBRARY_TIMEOUT", 18.0)
    monkeypatch.setattr(cfg, "BOOKPEEK", True)

    enrich = build_bookpeek_config().enrich
    assert enrich.enabled is True
    assert enrich.goodreads is True
    assert enrich.openlibrary is True
    assert enrich.goodreads_user_agent == "auto-m4b/1.0 (gr@example.com)"
    assert enrich.openlibrary_user_agent == "MyApp/1.0 (ol@example.com)"
    assert enrich.goodreads_timeout == 22.0
    assert enrich.openlibrary_timeout == 18.0


def test_build_bookpeek_config_disables_gr_ol_without_agents(monkeypatch):
    monkeypatch.setattr(cfg, "GOODSCRAPS_USER_AGENT", "")
    monkeypatch.setattr(cfg, "OPEN_LIBRARY_USER_AGENT", "")
    monkeypatch.setattr(cfg, "BOOKPEEK", True)

    enrich = build_bookpeek_config().enrich
    assert enrich.enabled is False
    assert enrich.goodreads is False
    assert enrich.openlibrary is False
    assert enrich.audnexus is True
    assert enrich.goodreads_user_agent is None
    assert enrich.openlibrary_user_agent is None


def test_scan_bookpeek_skipped_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "BOOKPEEK", False)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    assert scan_bookpeek(audio) is None


def test_scan_bookpeek_injects_online_and_ua(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "BOOKPEEK", True)
    monkeypatch.setattr(cfg, "GOODSCRAPS_USER_AGENT", "auto-m4b/1.0 (gr@example.com)")
    monkeypatch.setattr(cfg, "OPEN_LIBRARY_USER_AGENT", "")
    monkeypatch.setattr(cfg, "GOODSCRAPS_TIMEOUT", 30.0)
    monkeypatch.setattr(cfg, "OPEN_LIBRARY_TIMEOUT", 15.0)

    audio = tmp_path / "book.mp3"
    audio.write_bytes(b"fake")

    captured: dict = {}

    class _FakeBookPeek:
        def __init__(self, config):
            captured["config"] = config

        def scan(self, path, *, online=None, progress=None):
            captured["path"] = Path(path)
            captured["online"] = online
            return _fake_result()

    import fixm4b.metadata.bookpeek_provider as bp

    monkeypatch.setattr(bp, "BookPeek", _FakeBookPeek, raising=False)
    # Patch the import site inside scan_bookpeek
    import bookpeek as bookpeek_mod

    monkeypatch.setattr(bookpeek_mod, "BookPeek", _FakeBookPeek)

    result = scan_bookpeek(audio)
    assert result is not None
    assert captured["online"] is True
    assert captured["config"].enrich.goodreads_user_agent == "auto-m4b/1.0 (gr@example.com)"
    assert captured["config"].enrich.goodreads is True
    assert captured["config"].enrich.openlibrary is False


def test_corroborate_does_not_duplicate_goodreads_candidate():
    comparison = providers.MetadataComparison(
        candidates={
            "goodreads": providers.MetadataCandidate(
                provider="goodreads",
                title="The Blighted Stars",
                author="Megan E. O'Keefe",
                status="match",
                score=0.8,
            )
        }
    )
    result = _fake_result(gr_title="The Blighted Stars", gr_author="Megan E. O'Keefe")
    corr = corroborate_providers(comparison, result)
    assert corr.goodreads is True
    assert "bookpeek" not in comparison.candidates or comparison.candidates.get("bookpeek") is None
    assert comparison.candidates["goodreads"].score >= 0.8
    # Still a single goodreads candidate — no nested bookpeek>goodreads key
    assert list(comparison.candidates) == ["goodreads"]


def test_lookup_metadata_folds_bookpeek_without_duplicate_sections(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "BOOKPEEK", True)
    monkeypatch.setattr(cfg, "GOODSCRAPS_USER_AGENT", "ua")
    providers.clear_provider_cache()

    def fake_gr(title, author, narrator, ref=None):
        return providers.MetadataCandidate(
            provider="goodreads",
            title="The Blighted Stars",
            author="Megan E. O'Keefe",
            status="match",
            score=0.88,
            ref="123",
        )

    monkeypatch.setattr(providers, "_goodreads_lookup", fake_gr)
    monkeypatch.setattr(providers, "_open_library_lookup", lambda *a, **k: providers.MetadataCandidate(provider="openlibrary", status="skipped"))

    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"x")

    import fixm4b.metadata.bookpeek_provider as bp

    monkeypatch.setattr(
        bp,
        "scan_bookpeek",
        lambda *_a, **_k: _fake_result(gr_title="The Blighted Stars", gr_author="Megan E. O'Keefe"),
    )

    comparison = providers.lookup_metadata(
        "The Blighted Stars",
        author="Megan E. O'Keefe",
        lookup_goodreads=True,
        lookup_open_library=False,
        lookup_bookpeek=True,
        audio_path=audio,
    )
    assert "goodreads" in comparison.candidates
    assert "bookpeek" in comparison.candidates
    assert comparison.bookpeek_corroborated_goodreads is True
    assert comparison.candidates["bookpeek"].narrator == "Ciaran Saward"
    # No fabricated nested provider keys
    assert set(comparison.candidates) <= {"goodreads", "openlibrary", "bookpeek"}


def test_attach_and_print_plan_shows_single_goodreads_and_bookpeek_narrator(tmp_path):
    m4b = tmp_path / "book.m4b"
    m4b.write_bytes(b"x")
    plan = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title="The Blighted Stars",
        desired_author="Megan E. O'Keefe",
        desired_album="The Blighted Stars",
        desired_date="2023",
        desired_narrator="",
        desired_stem="book",
        current=TagSnapshot(title="Old", artist="Old", album="Old"),
    )
    comparison = providers.MetadataComparison(
        candidates={
            "goodreads": providers.MetadataCandidate(
                provider="goodreads",
                title="The Blighted Stars",
                author="Megan E. O'Keefe",
                year="2023",
                status="match",
                score=0.9,
            ),
            "bookpeek": bookpeek_to_candidate(_fake_result()),
        },
        selected=providers.MetadataCandidate(
            provider="goodreads",
            title="The Blighted Stars",
            author="Megan E. O'Keefe",
            narrator="Ciaran Saward",
            status="match",
            score=0.9,
        ),
        bookpeek_engine="whisper",
        bookpeek_seconds=60.0,
        bookpeek_corroborated_goodreads=True,
    )
    _attach_provider_comparison(plan, comparison)
    assert plan.goodreads_status == "match"
    assert plan.bookpeek_corroborated_goodreads is True
    assert plan.desired_narrator == "Ciaran Saward"
    assert plan.bookpeek_asin == "B0TEST"
    assert plan.bookpeek_status == "match"

    # Rendering uses Tinta (may bypass capsys); assert the plan fields that drive
    # a single goodreads header + separate bookpeek ASR/Audnexus section.
    assert plan.bookpeek_corroborated_goodreads
    assert "bookpeek > goodreads" not in (plan.goodreads_title + plan.bookpeek_title)
    print_plan(plan, show_rename=False)


def test_cli_bookpeek_flags_exist():
    parser = build_arg_parser()
    args = parser.parse_args(["--no-bookpeek"])
    assert args.no_bookpeek is True
    args = parser.parse_args(["--bookpeek"])
    assert args.bookpeek is True
