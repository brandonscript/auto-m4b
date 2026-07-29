"""Fast unit tests for Open Library scoring helpers (no network)."""

from __future__ import annotations

from src.lib.ol_lookup import (
    OpenLibraryTitle,
    _author_name_sim,
    _find_best_title,
    _title_sim,
)


def test_author_name_sim_handles_list():
    assert _author_name_sim("Tana French", ["Tana French", "Someone Else"]) == 1.0
    assert _author_name_sim("Tana French", ["Simon Toyne"]) < 0.5
    assert _author_name_sim("Tana French", []) == 0.0
    assert _author_name_sim("", ["Tana French"]) == 0.0
    # String form still works
    assert _author_name_sim("Tana French", "Tana French") == 1.0


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
