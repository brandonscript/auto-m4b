import threading
from types import SimpleNamespace

from src.fix_metadata import build_arg_parser
from src.lib import id3_utils
from src.lib.config import cfg
from src.lib.metadata.settings import Fixm4bSettings, set_settings
from src.lib.metadata import providers


def test_metadata_candidate_normalizes_smart_quotes():
    candidate = providers.MetadataCandidate(
        provider="openlibrary",
        title="Midnight’s Children",
        author="O’Reilly",
        narrator='“Reader”',
    )

    assert candidate.title == "Midnight's Children"
    assert candidate.author == "O'Reilly"
    assert candidate.narrator == '"Reader"'


def test_lookup_metadata_reuses_scoped_provider_results(monkeypatch):
    calls = 0

    def fake_open_library(_title, _author, _narrator):
        nonlocal calls
        calls += 1
        return providers.MetadataCandidate(
            provider="openlibrary",
            title="The Hobbit",
            author="J. R. R. Tolkien",
            status="match",
        )

    monkeypatch.setattr(providers, "_open_library_lookup", fake_open_library)
    providers.clear_provider_cache()

    first = providers.lookup_metadata("The Hobbit", lookup_goodreads=False)
    second = providers.lookup_metadata("The Hobbit", lookup_goodreads=False)

    assert calls == 1
    assert first == second
    assert first is not second


class _FakeGoodscraps:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def canonical_book_id(self, book_id):
        return book_id

    def search(self, _query, *, limit, resolve_canonical=False):
        assert limit == 10
        return [
            SimpleNamespace(
                book_id=42,
                canonical_book_id=42,
                title="The Hobbit",
                author=SimpleNamespace(name="J. R. R. Tolkien"),
                url="https://www.goodreads.com/book/show/42",
            )
        ]

    def book(self, book_id):
        assert str(book_id) == "42"
        return SimpleNamespace(
            book_id=42,
            title="The Hobbit",
            author=SimpleNamespace(name="J. R. R. Tolkien"),
            additional_authors=[],
            first_published_year=1937,
            url="https://www.goodreads.com/book/show/42",
        )


class _AuthorAwareGoodscraps(_FakeGoodscraps):
    def search(self, _query, *, limit, resolve_canonical=False):
        assert limit == 10
        return [
            SimpleNamespace(
                book_id=99,
                canonical_book_id=99,
                title="The Sword of Summer",
                author=SimpleNamespace(name="Rick Riordan"),
                url="https://www.goodreads.com/book/show/99",
            ),
            SimpleNamespace(
                book_id=100,
                canonical_book_id=100,
                title="By the Sword",
                author=SimpleNamespace(name="Mercedes Lackey"),
                url="https://www.goodreads.com/book/show/100",
            ),
        ]

    def book(self, book_id):
        if str(book_id) == "100":
            return SimpleNamespace(
                book_id=100,
                title="By the Sword",
                author=SimpleNamespace(name="Mercedes Lackey"),
                additional_authors=[],
                first_published_year=1991,
                url="https://www.goodreads.com/book/show/100",
            )
        return SimpleNamespace(
            book_id=99,
            title="The Sword of Summer",
            author=SimpleNamespace(name="Rick Riordan"),
            additional_authors=[],
            first_published_year=2015,
            url="https://www.goodreads.com/book/show/99",
        )


class _TitleCollisionGoodscraps(_FakeGoodscraps):
    def search(self, _query, *, limit, resolve_canonical=False):
        assert limit == 10
        return [
            SimpleNamespace(
                book_id=33580643,
                canonical_book_id=33580643,
                title=(
                    "Lovers, Lore & Loss Songs From The Arrows of the Queen, "
                    "Arrow's Flight and Arrow's Fall by Mercedes Lackey & D. F. Sanders"
                ),
                author=SimpleNamespace(name="Mercedes Lackey"),
                url="https://www.goodreads.com/book/show/33580643",
            ),
            SimpleNamespace(
                book_id=777,
                canonical_book_id=777,
                title="Arrow's Fall: Lovers, Lore & Loss",
                author=SimpleNamespace(name="Mercedes Lackey"),
                url="https://www.goodreads.com/book/show/777",
            ),
            SimpleNamespace(
                book_id=14014,
                canonical_book_id=14014,
                title="Arrow's Fall (Heralds of Valdemar, #3)",
                author=SimpleNamespace(name="Mercedes Lackey"),
                url="https://www.goodreads.com/book/show/14014.Arrow_s_Fall",
            ),
            SimpleNamespace(
                book_id=49475188,
                canonical_book_id=49475188,
                title="Queen's Own Volume Two: Arrow's Fall",
                author=SimpleNamespace(name="Mercedes Lackey"),
                url="https://www.goodreads.com/book/show/49475188",
            ),
        ]

    def book(self, book_id):
        assert str(book_id) == "14014"
        return SimpleNamespace(
            book_id=14014,
            title="Arrow's Fall",
            author=SimpleNamespace(name="Mercedes Lackey"),
            additional_authors=[],
            first_published_year=1988,
            url="https://www.goodreads.com/book/show/14014.Arrow_s_Fall",
        )


class _ItalianGirlGoodscraps(_FakeGoodscraps):
    def search(self, _query, *, limit, resolve_canonical=False):
        assert limit == 10
        return [
            SimpleNamespace(
                book_id=40253222,
                canonical_book_id=40253222,
                title="Lucinda Riley Collection 6 Books Bundles",
                author=SimpleNamespace(name="Lucinda Riley"),
                url="https://www.goodreads.com/book/show/40253222",
            ),
            SimpleNamespace(
                book_id=22057035,
                canonical_book_id=22057035,
                title="The Italian Girl",
                author=SimpleNamespace(name="Lucinda Edmonds"),
                url="https://www.goodreads.com/book/show/22057035",
            ),
        ]

    def book(self, book_id):
        assert str(book_id) == "22057035"
        return SimpleNamespace(
            book_id=22057035,
            title="The Italian Girl",
            author=SimpleNamespace(name="Lucinda Edmonds"),
            additional_authors=[],
            first_published_year=1996,
            url="https://www.goodreads.com/book/show/22057035",
        )


class _SeriesPrefixedGoodscraps(_FakeGoodscraps):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.queries = []

    def search(self, query, *, limit, resolve_canonical=False):
        assert limit == 10
        self.queries.append(query)
        if query not in ("Cockroaches Jo Nesbø", "Cockroaches"):
            return []
        return [
            SimpleNamespace(
                book_id=18373214,
                canonical_book_id=18373214,
                title="Cockroaches (Harry Hole, #2)",
                author=SimpleNamespace(name="Jo Nesbø"),
                url="https://www.goodreads.com/book/show/18373214-cockroaches",
            )
        ]

    def book(self, book_id):
        assert str(book_id) == "18373214"
        return SimpleNamespace(
            book_id=18373214,
            title="Cockroaches",
            author=SimpleNamespace(name="Jo Nesbø"),
            additional_authors=[],
            first_published_year=1998,
            url="https://www.goodreads.com/book/show/18373214-cockroaches",
        )


class _CanonicalPhantomGoodscraps(_FakeGoodscraps):
    def search(self, _query, *, limit, resolve_canonical=False):
        assert limit == 10
        return [
            SimpleNamespace(
                book_id=123790521,
                canonical_book_id=13256064,
                title="Phantom by Jo Nesbo",
                author=SimpleNamespace(name="Jo Nesbø"),
                url="https://www.goodreads.com/book/show/123790521-phantom-by-jo-nesbo",
            )
        ]

    def canonical_book_id(self, book_id):
        assert str(book_id) == "123790521"
        return 13256064

    def book(self, book_id):
        assert str(book_id) == "13256064"
        return SimpleNamespace(
            book_id=13256064,
            title="Phantom",
            author=SimpleNamespace(name="Jo Nesbø"),
            additional_additional_authors=[],
            first_published_year=2011,
            url="https://www.goodreads.com/book/show/13256064-phantom",
        )

def test_goodreads_lookup_normalizes_and_scores(monkeypatch):
    monkeypatch.setattr(providers, "Goodscraps", _FakeGoodscraps)
    monkeypatch.setattr(providers, "get_settings", lambda: Fixm4bSettings(goodscraps_user_agent="auto-m4b/1.0 (test@example.com)"))

    result = providers._goodreads_lookup("The Hobbit", "J. R. R. Tolkien", "")

    assert result.provider == "goodreads"
    assert result.status == "match"
    assert result.title == "The Hobbit"
    assert result.author == "J. R. R. Tolkien"
    assert result.year == "1937"
    assert result.ref == "42"
    assert result.score == 1.0


def test_goodreads_prefers_a_similar_author_over_top_title(monkeypatch):
    monkeypatch.setattr(providers, "Goodscraps", _AuthorAwareGoodscraps)
    monkeypatch.setattr(providers, "get_settings", lambda: Fixm4bSettings(goodscraps_user_agent="auto-m4b/1.0 (test@example.com)"))

    result = providers._goodreads_lookup("By the Sword", "Mercedes Lackey", "")

    assert result.title == "By the Sword"
    assert result.author == "Mercedes Lackey"
    assert result.year == "1991"


def test_goodreads_prefers_exact_title_over_longer_containing_title(monkeypatch):
    """A companion title containing the query must not beat the actual book."""
    monkeypatch.setattr(providers, "Goodscraps", _TitleCollisionGoodscraps)
    monkeypatch.setattr(providers, "get_settings", lambda: Fixm4bSettings(goodscraps_user_agent="auto-m4b/1.0 (test@example.com)"))

    result = providers._goodreads_lookup("Arrow's Fall", "Mercedes Lackey", "")

    assert result.ref == "14014"
    assert result.title == "Arrow's Fall"
    assert result.year == "1988"


def test_goodreads_prefers_exact_title_over_exact_author_collection(monkeypatch):
    monkeypatch.setattr(providers, "Goodscraps", _ItalianGirlGoodscraps)
    monkeypatch.setattr(providers, "get_settings", lambda: Fixm4bSettings(goodscraps_user_agent="auto-m4b/1.0 (test@example.com)"))

    result = providers._goodreads_lookup("The Italian Girl", "Lucinda Riley", "")

    assert result.ref == "22057035"
    assert result.title == "The Italian Girl"
    assert result.year == "1996"


def test_goodreads_falls_back_to_series_core_title(monkeypatch):
    client = _SeriesPrefixedGoodscraps()
    monkeypatch.setattr(providers, "Goodscraps", lambda **_kwargs: client)
    monkeypatch.setattr(providers, "get_settings", lambda: Fixm4bSettings(goodscraps_user_agent="auto-m4b/1.0 (test@example.com)"))

    result = providers._goodreads_lookup("Harry Hole 02: Cockroaches", "Jo Nesbø", "")

    assert result.ref == "18373214"
    assert result.title == "Cockroaches"
    assert result.year == "1998"
    assert "Cockroaches Jo Nesbø" in client.queries


def test_goodreads_resolves_search_result_to_canonical_book(monkeypatch):
    monkeypatch.setattr(providers, "Goodscraps", _CanonicalPhantomGoodscraps)
    monkeypatch.setattr(providers, "get_settings", lambda: Fixm4bSettings(goodscraps_user_agent="auto-m4b/1.0 (test@example.com)"))

    result = providers._goodreads_lookup("Phantom", "Jo Nesbø", "")

    assert result.ref == "13256064"
    assert result.title == "Phantom"
    assert result.author == "Jo Nesbø"
    assert result.year == "2011"

def test_goodreads_forced_lookup_skips_search(monkeypatch):
    monkeypatch.setattr(providers, "Goodscraps", _FakeGoodscraps)
    monkeypatch.setattr(providers, "get_settings", lambda: Fixm4bSettings(goodscraps_user_agent="auto-m4b/1.0 (test@example.com)"))

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


def test_lookup_queries_enabled_providers_in_parallel(monkeypatch):
    barrier = threading.Barrier(2)

    def goodreads_lookup(*_args, **_kwargs):
        barrier.wait(timeout=1)
        return providers.MetadataCandidate(provider="goodreads", status="match", title="Book")

    def open_library_lookup(*_args, **_kwargs):
        barrier.wait(timeout=1)
        return providers.MetadataCandidate(provider="openlibrary", status="match", title="Book")

    monkeypatch.setattr(providers, "_goodreads_lookup", goodreads_lookup)
    monkeypatch.setattr(providers, "_open_library_lookup", open_library_lookup)

    comparison = providers.lookup_metadata("Book")

    assert comparison.selected is not None
    assert set(comparison.candidates) == {"goodreads", "openlibrary"}


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


def test_agreeing_provider_titles_replace_series_prefixed_local_title():
    plan = SimpleNamespace(
        fs_title="Harry Hole 02: Cockroaches",
        current=SimpleNamespace(title="Harry Hole 02 - Cockroaches"),
        desired_title="Harry Hole 02: Cockroaches",
        desired_album="Harry Hole 02: Cockroaches",
        reasons=[],
        provider_conflicts=[],
    )
    comparison = providers.MetadataComparison(
        candidates={
            "goodreads": providers.MetadataCandidate(
                provider="goodreads",
                title="Cockroaches",
                status="match",
            ),
            "openlibrary": providers.MetadataCandidate(
                provider="openlibrary",
                title="Cockroaches",
                status="match",
            ),
        },
        selected=providers.MetadataCandidate(
            provider="goodreads",
            title="Cockroaches",
            status="match",
        ),
    )

    from src.lib.metadata.plan import _attach_provider_comparison

    _attach_provider_comparison(plan, comparison)

    assert plan.desired_title == "Cockroaches"
    assert plan.desired_album == "Cockroaches"
    assert "use agreed Goodreads/Open Library title" in plan.reasons
