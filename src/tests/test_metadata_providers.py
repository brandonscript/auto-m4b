from types import SimpleNamespace

from src.fix_metadata import build_arg_parser
from src.lib import id3_utils
from src.lib.config import cfg
from src.lib.metadata import providers


class _FakeGoodscraps:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def search(self, _query, *, limit):
        assert limit == 10
        return [
            SimpleNamespace(
                book_id=42,
                title="The Hobbit",
                author_name="J. R. R. Tolkien",
                url="https://www.goodreads.com/book/show/42",
            )
        ]

    def book(self, book_id):
        assert str(book_id) == "42"
        return SimpleNamespace(
            book_id=42,
            title="The Hobbit",
            author_primary=SimpleNamespace(name="J. R. R. Tolkien"),
            authors=[],
            first_published_year=1937,
            url="https://www.goodreads.com/book/show/42",
        )


def test_goodreads_lookup_normalizes_and_scores(monkeypatch):
    monkeypatch.setattr(providers, "Goodscraps", _FakeGoodscraps)
    monkeypatch.setattr(providers.cfg, "GOODSCRAPS_USER_AGENT", "auto-m4b/1.0 (test@example.com)")

    result = providers._goodreads_lookup("The Hobbit", "J. R. R. Tolkien", "")

    assert result.provider == "goodreads"
    assert result.status == "match"
    assert result.title == "The Hobbit"
    assert result.author == "J. R. R. Tolkien"
    assert result.year == "1937"
    assert result.ref == "42"
    assert result.score == 1.0


def test_goodreads_forced_lookup_skips_search(monkeypatch):
    monkeypatch.setattr(providers, "Goodscraps", _FakeGoodscraps)
    monkeypatch.setattr(providers.cfg, "GOODSCRAPS_USER_AGENT", "auto-m4b/1.0 (test@example.com)")

    result = providers._goodreads_lookup("ignored", "", "", ref="42")

    assert result.status == "forced"
    assert result.ref == "42"


def test_lookup_prefers_goodreads_and_reports_conflicts(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_goodreads_lookup",
        lambda *_args, **_kwargs: providers.MetadataCandidate(
            provider="goodreads",
            title="The Hobbit",
            author="J. R. R. Tolkien",
            year="1937",
            status="match",
            score=0.95,
        ),
    )
    monkeypatch.setattr(
        providers,
        "_open_library_lookup",
        lambda *_args, **_kwargs: providers.MetadataCandidate(
            provider="openlibrary",
            title="The Hobbit: An Unexpected Journey",
            author="J. R. R. Tolkien",
            year="1937",
            status="match",
            score=0.9,
        ),
    )

    comparison = providers.lookup_metadata("The Hobbit", author="J. R. R. Tolkien")

    assert comparison.selected is not None
    assert comparison.selected.provider == "goodreads"
    assert any(conflict.startswith("title:") for conflict in comparison.conflicts)


def test_lookup_falls_back_to_open_library(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_goodreads_lookup",
        lambda *_args, **_kwargs: providers.MetadataCandidate(
            provider="goodreads",
            status="error",
            error="timeout",
        ),
    )
    monkeypatch.setattr(
        providers,
        "_open_library_lookup",
        lambda *_args, **_kwargs: providers.MetadataCandidate(
            provider="openlibrary",
            title="The Hobbit",
            author="J. R. R. Tolkien",
            status="match",
            score=0.8,
        ),
    )

    comparison = providers.lookup_metadata("The Hobbit", author="J. R. R. Tolkien")

    assert comparison.selected is not None
    assert comparison.selected.provider == "openlibrary"


def test_cli_exposes_goodreads_controls():
    args = build_arg_parser().parse_args(["--goodreads", "42", "--no-goodreads"])

    assert args.goodreads_ref == "42"
    assert args.no_goodreads is True


def test_main_extraction_accepts_confident_goodreads_candidate(monkeypatch):
    monkeypatch.setattr(cfg, "GOODSCRAPS_USER_AGENT", "auto-m4b/1.0 (test@example.com)")
    monkeypatch.setattr(
        id3_utils,
        "lookup_metadata",
        lambda *_args, **_kwargs: providers.MetadataComparison(
            selected=providers.MetadataCandidate(
                provider="goodreads",
                title="The Hobbit",
                author="J. R. R. Tolkien",
                status="match",
                score=0.95,
            )
        ),
    )
    book = SimpleNamespace(
        fs_title="The Hobbit",
        fs_author="J. R. R. Tolkien",
        fs_narrator="",
        basename="The Hobbit",
    )
    tags = SimpleNamespace(title="The Hobbit", album="", albumartist="", artist="", composer="")

    result = id3_utils._goodreads_early_extraction(book, tags, tags)

    assert result is not None
    assert result.provider == "goodreads"


def test_provider_titles_break_a_two_two_local_tie():
    plan = SimpleNamespace(
        fs_title="Lord of Emperors: Sarantine Mosaic 02",
        current=SimpleNamespace(title="Lord of Emperors - Sarantine Mosaic 02"),
        desired_title="Lord of Emperors: Sarantine Mosaic 02",
        desired_album="Lord of Emperors: Sarantine Mosaic 02",
        reasons=[],
        provider_conflicts=[],
    )
    comparison = providers.MetadataComparison(
        candidates={
            "goodreads": providers.MetadataCandidate(
                provider="goodreads",
                title="Lord of Emperors",
                status="match",
            ),
            "openlibrary": providers.MetadataCandidate(
                provider="openlibrary",
                title="Lord of Emperors",
                status="match",
            ),
        },
        selected=providers.MetadataCandidate(
            provider="goodreads",
            title="Lord of Emperors",
            status="match",
        ),
    )

    from src.lib.metadata.plan import _attach_provider_comparison

    _attach_provider_comparison(plan, comparison)

    assert plan.desired_title == "Lord of Emperors"
    assert "resolve 2–2 title tie with Goodreads" in plan.reasons
