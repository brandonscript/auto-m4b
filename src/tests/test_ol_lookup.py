"""Fast unit tests for Open Library scoring helpers (no network)."""

from __future__ import annotations

from urllib.parse import unquote_plus
from unittest.mock import MagicMock, patch

from src.lib.ol_lookup import (
    OL_MATCH_MIN,
    OpenLibraryTitle,
    _author_name_sim,
    _best_edition_title_score,
    _best_matching_edition_base_title,
    _best_matching_edition_subtitle,
    _boost_title_score_via_editions,
    _desired_matches_edition_title,
    _edition_title_strings,
    _find_best_title,
    _strip_boundary_number,
    _subtitle_attested_locally,
    _title_sim,
    id3_prefer_colon_separator,
    join_title_subtitle,
    ol_title_uses_dash_separator,
    open_library_lookup_title,
)


def test_author_name_sim_handles_list():
    assert _author_name_sim("Tana French", ["Tana French", "Someone Else"]) == 1.0
    assert _author_name_sim("Tana French", ["Simon Toyne"]) < 0.5
    assert _author_name_sim("Tana French", []) == 0.0
    assert _author_name_sim("", ["Tana French"]) == 0.0
    # String form still works
    assert _author_name_sim("Tana French", "Tana French") == 1.0


def _ol_doc(key: str, title: str) -> dict:
    return {
        "key": key,
        "title": title,
        "name": title,
        "author_name": ["Brandon Sanderson"],
        "author_key": ["OL1A"],
        "work_count": 10,
        "edition_count": 1,
    }


def _mock_title_search(titles: dict[str, list[dict]]):
    def get(url: str, **_kwargs):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        query = (
            url.split("title=", 1)[-1].split("&", 1)[0]
            if "title=" in url
            else url.split("q=", 1)[-1].split("&", 1)[0]
        )

        docs = titles.get(unquote_plus(query), [])
        response.json.return_value = {"numFound": len(docs), "docs": docs}
        return response

    return get


def test_strip_boundary_number_keeps_meaningful_title_only():
    assert _strip_boundary_number("Elantris 01") == "Elantris"
    assert _strip_boundary_number("01 Elantris") == "Elantris"
    assert _strip_boundary_number("1984") is None


def test_numeric_title_lookup_uses_stripped_fallback():
    with (
        patch("src.lib.ol_lookup._get_open_library_user_agent", return_value="test/1.0 (t@e.com)"),
        patch(
            "src.lib.ol_lookup.requests.get",
            side_effect=_mock_title_search({"elantris": [_ol_doc("/works/OL5738147W", "Elantris")]}),
        ),
    ):
        result = open_library_lookup_title("Elantris 01")

    assert result is not None
    assert result.title == "Elantris"
    assert result.key == "/works/OL5738147W"


def test_leading_numeric_title_lookup_uses_stripped_fallback():
    with (
        patch("src.lib.ol_lookup._get_open_library_user_agent", return_value="test/1.0 (t@e.com)"),
        patch(
            "src.lib.ol_lookup.requests.get",
            side_effect=_mock_title_search({"elantris": [_ol_doc("/works/OL5738147W", "Elantris")]}),
        ),
    ):
        result = open_library_lookup_title("01 Elantris")

    assert result is not None
    assert result.title == "Elantris"


def test_numeric_title_lookup_prefers_original_numbered_title():
    with (
        patch("src.lib.ol_lookup._get_open_library_user_agent", return_value="test/1.0 (t@e.com)"),
        patch(
            "src.lib.ol_lookup.requests.get",
            side_effect=_mock_title_search(
                {
                    "the 100": [_ol_doc("/works/OL100W", "The 100")],
                    "the": [_ol_doc("/works/OL101W", "The")],
                }
            ),
        ),
    ):
        result = open_library_lookup_title("The 100")

    assert result is not None
    assert result.title == "The 100"
    assert result.key == "/works/OL100W"


def test_numeric_title_lookup_rejects_ambiguous_numbered_fallbacks():
    with (
        patch("src.lib.ol_lookup._get_open_library_user_agent", return_value="test/1.0 (t@e.com)"),
        patch(
            "src.lib.ol_lookup.requests.get",
            side_effect=_mock_title_search(
                {
                    "elantris": [
                        _ol_doc("/works/OL1W", "Elantris #1"),
                        _ol_doc("/works/OL2W", "Elantris #2"),
                    ]
                }
            ),
        ),
    ):
        result = open_library_lookup_title("Elantris 01")

    assert result is not None
    assert not result.has_match


def test_title_sim_returns_ratio_and_token_set():
    ratio, token = _title_sim("The Searcher", "The Searcher: A Novel")
    assert ratio > 0.7
    assert token > 0.7
    ratio2, token2 = _title_sim("About A Poem", "The Best American Spiritual Writing 2008")
    assert ratio2 < 0.5
    assert token2 < 0.55


def test_get_author_sim_via_find_best_title_list_author_name():
    """author_score must work when OL returns author_name as a list (not a string)."""
    matches = [
        {
            "key": "/works/OL1W",
            "title": "Solitude",
            "author_name": ["Ursula K. Le Guin"],
            "author_key": ["OL1A"],
            "work_count": 10,
            "edition_count": 1,
            "name": "Solitude",
        }
    ]
    best, title_score, author_score, author_prop = _find_best_title(
        "Solitude",
        matches,  # type: ignore[arg-type]
        author="Ursula K. Le Guin",
        method="similarity",
    )
    assert best is not None
    assert title_score == 1.0
    assert author_score == 1.0
    assert author_prop == "author"


def test_author_score_zero_is_preserved_not_falsy():
    """A real 0.0 author_score must not collapse to None via falsy checks."""
    matches = [
        {
            "key": "/works/OL2W",
            "title": "Solitude",
            "author_name": ["Anthony Storr"],
            "author_key": ["OL2A"],
            "work_count": 5,
            "edition_count": 1,
            "name": "Solitude",
        }
    ]
    best, _title_score, author_score, author_prop = _find_best_title(
        "Solitude",
        matches,  # type: ignore[arg-type]
        author="Ursula K. Le Guin",
        method="similarity",
    )
    assert best is not None
    assert author_prop == "author"
    assert author_score is not None
    assert author_score < 0.5


def test_swapped_author_narrator_properties():
    title_res = {
        "key": "/works/OL3W",
        "title": "Harry Potter",
        "author_name": ["J. K. Rowling"],
        "author_key": ["OL3A"],
        "work_count": 1,
        "edition_count": 1,
        "name": "Harry Potter",
    }
    # Tags swapped: artist=Stephen Fry (narrator), composer missing; we passed
    # author=Fry, narrator=Rowling and OL decided narrator is the real author.
    ol = OpenLibraryTitle(
        title_res,  # type: ignore[arg-type]
        1.0,
        0.95,
        "narrator",
        original_author="Stephen Fry",
        original_narrator="J. K. Rowling",
    )
    assert ol.author_and_narrator_swapped is True
    assert ol.author == "J. K. Rowling"
    assert ol.narrator == "Stephen Fry"


def test_edition_title_strings_includes_subtitle_variants():
    assert _edition_title_strings({"title": "Eon", "subtitle": "Dragoneye Reborn"}) == [
        "Eon",
        "Eon: Dragoneye Reborn",
        "Eon - Dragoneye Reborn",
        "Dragoneye Reborn",
    ]
    assert _edition_title_strings({"title": "Solo"}) == ["Solo"]
    assert _edition_title_strings({}) == []


def test_best_edition_title_score_from_mocked_editions():
    """Edition title containing the query should score ≥ match floor."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "entries": [
            {"title": "Eon", "subtitle": "Dragoneye Reborn"},
            {"title": "Eon"},
        ]
    }
    with patch("src.lib.ol_lookup.requests.get", return_value=resp) as get:
        score = _best_edition_title_score(
            "/works/OL123W", "Dragoneye Reborn", agent="test/1.0 (t@e.com)"
        )
    assert score >= OL_MATCH_MIN
    get.assert_called_once()
    assert "editions.json" in get.call_args.args[0]


def test_boost_via_editions_when_author_solid():
    matches = [
        {
            "key": "/works/OL123W",
            "title": "Eon",
            "author_name": ["Alison Goodman"],
            "author_key": ["OLA"],
            "work_count": 5,
            "edition_count": 2,
            "name": "Eon",
        }
    ]
    with patch(
        "src.lib.ol_lookup._best_edition_title_score", return_value=0.87
    ) as ed_score:
        boosted = _boost_title_score_via_editions(
            "Dragoneye Reborn",
            matches,  # type: ignore[arg-type]
            matches[0],  # type: ignore[arg-type]
            0.21,
            0.95,
            agent="test/1.0 (t@e.com)",
        )
    assert boosted >= OL_MATCH_MIN
    assert boosted == 0.87
    ed_score.assert_called()


def test_boost_skipped_when_author_weak_or_missing():
    matches = [
        {
            "key": "/works/OL123W",
            "title": "Eon",
            "author_name": ["Someone Else"],
            "author_key": ["OLA"],
            "work_count": 5,
            "edition_count": 2,
            "name": "Eon",
        }
    ]
    with patch("src.lib.ol_lookup._best_edition_title_score", return_value=0.99) as ed_score:
        assert (
            _boost_title_score_via_editions(
                "Dragoneye Reborn",
                matches,  # type: ignore[arg-type]
                matches[0],  # type: ignore[arg-type]
                0.21,
                0.2,
                agent="test/1.0 (t@e.com)",
            )
            == 0.21
        )
        assert (
            _boost_title_score_via_editions(
                "Dragoneye Reborn",
                matches,  # type: ignore[arg-type]
                matches[0],  # type: ignore[arg-type]
                0.21,
                None,
                agent="test/1.0 (t@e.com)",
            )
            == 0.21
        )
    ed_score.assert_not_called()


def test_boost_skipped_when_title_already_confident():
    matches = [
        {
            "key": "/works/OL1W",
            "title": "The Searcher",
            "author_name": ["Tana French"],
            "author_key": ["OLA"],
            "work_count": 1,
            "edition_count": 1,
            "name": "The Searcher",
        }
    ]
    with patch("src.lib.ol_lookup._best_edition_title_score", return_value=1.0) as ed_score:
        assert (
            _boost_title_score_via_editions(
                "The Searcher",
                matches,  # type: ignore[arg-type]
                matches[0],  # type: ignore[arg-type]
                0.95,
                1.0,
                agent="test/1.0 (t@e.com)",
            )
            == 0.95
        )
    ed_score.assert_not_called()


def test_join_title_subtitle_defaults_to_colon():
    assert join_title_subtitle("Eona", "The Last Dragoneye") == "Eona: The Last Dragoneye"
    assert join_title_subtitle("Eona", "The Last Dragoneye", prefer_dash=True) == (
        "Eona - The Last Dragoneye"
    )
    # Do not double-add when subtitle already present
    assert join_title_subtitle("Eona: The Last Dragoneye", "The Last Dragoneye") == (
        "Eona: The Last Dragoneye"
    )
    assert join_title_subtitle("Eona", "") == "Eona"


def test_ol_title_uses_dash_separator_ol_only():
    """Dash preference is OL-title-only; folder-style corpus alone is not enough."""
    assert ol_title_uses_dash_separator("Eon - Dragoneye Reborn", "Eon", "Dragoneye Reborn")
    assert not ol_title_uses_dash_separator("Eon: Dragoneye Reborn", "Eon", "Dragoneye Reborn")
    assert not ol_title_uses_dash_separator("Eona", "Eona", "The Last Dragoneye")


def test_id3_prefer_colon_separator():
    assert id3_prefer_colon_separator("Eon - Dragoneye Reborn") == "Eon: Dragoneye Reborn"
    # OL hint already dash-form for the same left/right → keep dash
    assert (
        id3_prefer_colon_separator(
            "Something - The Something Else",
            ol_title_hint="Something - The Something Else",
        )
        == "Something - The Something Else"
    )
    # Already colon → unchanged
    assert id3_prefer_colon_separator("Eon: Dragoneye Reborn") == "Eon: Dragoneye Reborn"


def test_best_matching_edition_subtitle_requires_local_tokens():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "entries": [
            {"title": "Eona", "subtitle": "the last Dragoneye"},
            {"title": "Eona"},
        ]
    }
    with patch("src.lib.ol_lookup.requests.get", return_value=resp):
        hit = _best_matching_edition_subtitle(
            "/works/OL16116601W",
            "Eon 02 - Eona - The Last Dragoneye (2011)",
            base_title="Eona",
            agent="test/1.0 (t@e.com)",
        )
        miss = _best_matching_edition_subtitle(
            "/works/OL16116601W",
            "Some Unrelated Book Folder (2011)",
            base_title="Eona",
            agent="test/1.0 (t@e.com)",
        )
    assert hit is not None
    assert "dragoneye" in hit.lower()
    assert miss is None


def test_subtitle_attestation_rejects_partial_dragoneye_overlap():
    """Rise of the Dragoneye must not pass on Dragoneye alone."""
    corpus = "Eon 01 - Eon - Dragoneye Reborn (2008) Dragoneye Reborn.m4b"
    assert _subtitle_attested_locally("Dragoneye Reborn", corpus)
    assert not _subtitle_attested_locally("Rise of the Dragoneye", corpus)


def test_eon_prefers_dragoneye_reborn_not_rise_subtitle():
    """Goodreads form: Eon: Dragoneye Reborn — never Dragoneye Reborn: Rise…"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "entries": [
            {"title": "Eon", "subtitle": "Dragoneye Reborn"},
            {"title": "Eon", "subtitle": "Rise of the Dragoneye"},
            {"title": "Eon: Rise of the Dragoneye"},
        ]
    }
    corpus = "Eon 01 - Eon - Dragoneye Reborn (2008) Dragoneye Reborn.m4b"
    with patch("src.lib.ol_lookup.requests.get", return_value=resp):
        sub = _best_matching_edition_subtitle(
            "/works/OL29358192W",
            corpus,
            base_title="Eon",
            agent="test/1.0 (t@e.com)",
            prefer_local="Dragoneye Reborn",
        )
    assert sub is not None
    assert sub.lower() == "dragoneye reborn"
    enriched = join_title_subtitle("Eon", sub)
    assert enriched == "Eon: Dragoneye Reborn"
    assert "Rise" not in enriched


def test_eona_joins_last_dragoneye_onto_work_title():
    """Goodreads form: Eona: The Last Dragoneye."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "entries": [
            {"title": "Eona", "subtitle": "the last Dragoneye"},
        ]
    }
    corpus = "Eon 02 - Eona - The Last Dragoneye (2011) Eona.m4b"
    with patch("src.lib.ol_lookup.requests.get", return_value=resp):
        sub = _best_matching_edition_subtitle(
            "/works/OL16116601W",
            corpus,
            base_title="Eona",
            agent="test/1.0 (t@e.com)",
            prefer_local="Eona",
        )
    assert sub is not None
    from src.lib.cleaners import title_case_ol_title

    assert title_case_ol_title(join_title_subtitle("Eona", sub)) == "Eona: The Last Dragoneye"


def test_safe_filename_translates_colon_subtitle():
    from src.lib.fs_utils import safe_filename

    assert safe_filename("Eona: The Last Dragoneye") == "Eona - The Last Dragoneye"
    assert safe_filename("Eon: Dragoneye Reborn") == "Eon - Dragoneye Reborn"


def test_desired_matches_edition_title_full_form_only():
    editions = [
        {"title": "The Two Pearls of Wisdom"},
        {"title": "Eon", "subtitle": "Dragoneye Reborn"},
        {"title": "Eon: Dragoneye Reborn"},
    ]
    with patch("src.lib.ol_lookup._fetch_work_editions", return_value=editions):
        assert _desired_matches_edition_title(
            "/works/OL5954753W",
            "Eon: Dragoneye Reborn",
            agent="test/1.0 (t@e.com)",
        )
        assert _desired_matches_edition_title(
            "/works/OL5954753W",
            "Eon - Dragoneye Reborn",
            agent="test/1.0 (t@e.com)",
        )
        # Incomplete marketing-only local must still enrich
        assert not _desired_matches_edition_title(
            "/works/OL5954753W",
            "Dragoneye Reborn",
            agent="test/1.0 (t@e.com)",
        )


def test_best_matching_edition_base_prefers_local_eon_over_au_work():
    editions = [
        {"title": "The Two Pearls of Wisdom"},
        {"title": "Eon", "subtitle": "Dragoneye Reborn"},
    ]
    corpus = "Eon 01 - Eon - Dragoneye Reborn (2008) Dragoneye Reborn.m4b"
    with patch("src.lib.ol_lookup._fetch_work_editions", return_value=editions):
        base = _best_matching_edition_base_title(
            "/works/OL5954753W",
            corpus,
            work_title="The Two Pearls of Wisdom",
            prefer_local="Eon: Dragoneye Reborn",
            agent="test/1.0 (t@e.com)",
        )
    assert base == "Eon"
