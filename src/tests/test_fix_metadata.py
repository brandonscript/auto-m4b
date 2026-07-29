"""Fast unit tests for fix_metadata helpers (no audio fixtures)."""

from src.fix_metadata import (
    folder_narrator_hint,
    folder_title_hint,
    parse_apply_prompt,
    _last_first_to_first_last,
)


def test_folder_title_hint_strips_series_narrator_year():
    assert folder_title_hint("Earthsea Cycle 05.3 - The Bones of the Earth [Wauters] (2001)") == (
        "The Bones of the Earth"
    )
    assert folder_title_hint("About A Poem [Downer] (2007)") == "About A Poem"
    assert folder_title_hint("The Searcher (2020)") == "The Searcher"
    assert folder_title_hint("[Collections] The Island of the Immortals [De Cuir] (1998)") == (
        "The Island of the Immortals"
    )


def test_folder_narrator_hint():
    assert folder_narrator_hint("Solitude [Pardee] (1994)") == "Pardee"
    assert folder_narrator_hint("The Diary of the Rose [AB] [Lefkow] (1976)") == "Lefkow"
    assert folder_narrator_hint("The Searcher (2020)") == ""


def test_last_first_conversion():
    assert _last_first_to_first_last("Le Guin, Ursula K.") == "Ursula K. Le Guin"
    assert _last_first_to_first_last("French, Tana") == "Tana French"
    assert _last_first_to_first_last("Ursula K. Le Guin") == "Ursula K. Le Guin"


def test_parse_apply_prompt():
    assert parse_apply_prompt("") == "n"
    assert parse_apply_prompt("y") == "y"
    assert parse_apply_prompt("Yes") == "y"
    assert parse_apply_prompt("n") == "n"
    assert parse_apply_prompt("skip") == "n"
    assert parse_apply_prompt("a") == "a"
    assert parse_apply_prompt("all") == "a"
    assert parse_apply_prompt("q") == "q"
    assert parse_apply_prompt("quit") == "q"
    assert parse_apply_prompt("maybe") == "n"
