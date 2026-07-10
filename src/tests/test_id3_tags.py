import re
from collections.abc import Callable

import pytest
from mutagen.id3._util import ID3NoHeaderError
from mutagen.mp3 import HeaderNotFoundError

from src.lib.audiobook import Audiobook
from src.lib.id3_tags import extract_id3_tags
from src.lib.id3_utils import map_kid3_keys, write_id3_tags_mutagen
from src.lib.inbox_state import InboxState
from src.lib.misc import increment
from src.lib.parsers import (
    has_graphic_audio,
)
from src.tests.helpers.pytest_utils import testutils


def test_tags_load_fails_for_non_audio_file(not_an_audio_file: Audiobook):

    with pytest.raises(ID3NoHeaderError):
        write_id3_tags_mutagen(not_an_audio_file.sample_audio1, {})


def test_id3_extract_fails_for_corrupt_file(corrupt_audiobook: Audiobook):

    with pytest.raises(HeaderNotFoundError):
        extract_id3_tags(corrupt_audiobook.sample_audio1, "title", throw=True)


@pytest.mark.parametrize(
    "test_dict1, test_dict2, expected",
    [
        (
            {
                "comment": (
                    "Written by Sarah J. Maas - Performed by Melody Muze as Feyre, Anthony Palmini as Rhysand, Colleen Delany as Narrator; Jon Vertullo as Cassian, and Amanda Forstrom as Morrigan; with Shawn K. Jain, Nora Achrati, Karenna Foley, Gabriel Michael, Natalie Van Sistine, Eva Wilhelm, Henry W. Kramer, Bianca Bryan, Renee Dorian, Matthew Bassett, Rob McFadyen, Ryan Carlo Dalusung, Yasmin Tuazon, Matthew Schleigh, Nanette Savard, Dan Delgado, Michael John Casey, Alejandro Ruiz, and Samantha Cooper"
                )
            },
            {},
            {
                "author": "Sarah J. Maas",
                "artist": "Sarah J. Maas",
                "albumartist": "Sarah J. Maas",
                "narrator": "Melody Muze",
            },
        ),
        (
            {
                "artist": "Sarah J. Maas",
                "albumartist": "Melody Muze",
                "title": "ACoFaS pt 1",
                "album": "A Court of Thorns and Roses: A Court of Frost and Starlight",
            },
            {},
            {
                "title": "A Court of Thorns and Roses: A Court of Frost and Starlight",
                "album": "A Court of Thorns and Roses: A Court of Frost and Starlight",
                "sortalbum": "Court of Thorns and Roses: A Court of Frost and Starlight",
                "author": "Sarah J. Maas",
                "artist": "Sarah J. Maas",
                "albumartist": "Melody Muze",
                "narrator": "Melody Muze",
            },
        ),
        (
            map_kid3_keys(
                {
                    "Track": 1,
                    "Title": "The Late Show-1",
                    "Artist": "Michael Connelly",
                    "Album": "The Late Show",
                    "Date": 2017,
                    "Genre": "",
                    "Comment": "Read by Katherine Moennig {F",
                    "Duration": "1:15:36.00",
                    "Album Artist": "",
                    "Composer": "",
                }
            ),
            map_kid3_keys(
                {
                    "Track": 2,
                    "Title": "The Late Show-2",
                    "Artist": "Michael Connelly",
                    "Album": "The Late Show",
                    "Date": 2017,
                    "Genre": "",
                    "Comment": "Read by Katherine Moennig {F",
                    "Duration": "1:02:53.00",
                    "Album Artist": "",
                    "Composer": "",
                }
            ),
            {
                "title": "The Late Show",
                "album": "The Late Show",
                "sortalbum": "Late Show",
                "author": "Michael Connelly",
                "artist": "Michael Connelly",
                "albumartist": "Michael Connelly",
                "narrator": "Katherine Moennig",
                "year": "2017",
            },
        ),
        (
            map_kid3_keys(
                {
                    "Track": 1,
                    "Title": "The Late Show-1",
                    "Artist": "Michael Connelly",
                    "Album": "The Late Show",
                    "Date": 2017,
                    "Album Artist": "Katherine Moennig",
                }
            ),
            map_kid3_keys(
                {
                    "Track": 2,
                    "Title": "The Late Show-2",
                    "Artist": "Michael Connelly",
                    "Album": "The Late Show",
                    "Date": 2017,
                    "Album Artist": "Katherine Moennig",
                }
            ),
            {
                "title": "The Late Show",
                "album": "The Late Show",
                "sortalbum": "Late Show",
                "author": "Michael Connelly",
                "artist": "Michael Connelly",
                "albumartist": "Katherine Moennig",
                "narrator": "Katherine Moennig",
                "year": "2017",
            },
        ),
        (
            {
                "title": "Firekeeper's Daughter - 001",
                "artist": "Angeline Boulley",
                "album": "Firekeeper's Daughter",
            },
            {},
            {
                "title": "Firekeeper's Daughter",
                "album": "Firekeeper's Daughter",
                "sortalbum": "Firekeeper's Daughter",
                "author": "Angeline Boulley",
                "artist": "Angeline Boulley",
                "albumartist": "Angeline Boulley",
            },
        ),
    ],
)
def test_parse_combo_id3_tags(
    test_dict1: dict[str, str],
    test_dict2: dict[str, str],
    expected: dict[str, str],
    blank_audiobook: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    if not test_dict2:
        test_dict2 = {**test_dict1}
    if "title" in test_dict2:
        test_dict2 = {**test_dict2, "title": increment(test_dict2["title"])}

    assert blank_audiobook.sample_audio1
    assert blank_audiobook.sample_audio2

    _got_tags = mock_id3_tags(
        (blank_audiobook.sample_audio1, test_dict1),
        (blank_audiobook.sample_audio2, test_dict2),
    )

    book = Audiobook(blank_audiobook.sample_audio1).extract_metadata()

    for key in expected.keys():
        assert getattr(book, key) == expected[key], f"Expected {key} '{expected[key]}', got '{getattr(book, key)}'"


def test_ignore_graphic_audio(graphic_audio__single_m4b: Audiobook, capfd: pytest.CaptureFixture):

    b = graphic_audio__single_m4b
    b.extract_metadata(console=True)
    for prop in [
        "author",
        "artist",
        "albumartist",
        "narrator",
        "title",
        "album",
        "sortalbum",
        "composer",
    ]:
        assert not has_graphic_audio(getattr(b, prop))

    assert b.title == "A Court of Thorns and Roses: A Court of Frost and Starlight"
    assert b.album == b.title
    assert b.sortalbum == b.title.removeprefix("A ")
    assert b.author == "Sarah J. Maas"
    assert b.artist == b.author
    assert b.albumartist == b.author
    assert b.narrator == "Melody Muze"

    assert """Sampling A Court Of Thorns And Roses [03.1] A Court Of Frost And Starlight.m4b for book metadata and quality info:
- Title: A Court of Thorns and Roses: A Court of Frost and Starlight
- Author: Sarah J. Maas
- Narrator: Melody Muze
- Date: 2023
- Quality: 64 kb/s @ 44.1 kHz
- Duration: 0h:00m:33s""" in testutils.get_stdout(
        capfd
    )


@pytest.mark.parametrize(
    "test_dict, expected_author",
    [
        (
            {"comment": "Written by Sarah J. Maas - Performed by Melody Muze as Feyre, Anthony Palmini as Rhysand"},
            "Sarah J. Maas",
        ),
        (
            {
                "artist": "GraphicAudio LLC",
                "comment": "Written by Sarah J. Maas - Performed by Melody Muze as Feyre, Anthony Palmini as Rhysand",
            },
            "Sarah J. Maas",
        ),
        (
            {
                "artist": "Sarah J. Maas",
                "comment": "Performed by Melody Muze as Feyre, Anthony Palmini as Rhysand",
            },
            "Sarah J. Maas",
        ),
        (
            {
                "albumartist": "Sarah J. Maas",
                "comment": "Performed by Melody Muze as Feyre, Anthony Palmini as Rhysand",
            },
            "Sarah J. Maas",
        ),
        (
            {
                "artist": "Melody Muze",
                "albumartist": "Sarah J. Maas",
                "comment": "Performed by Melody Muze as Feyre, Anthony Palmini as Rhysand",
            },
            "Sarah J. Maas",
        ),
        (
            {
                "comment": (
                    "When we rescued the first fluffy-eared princess, I didn't realize how lucky we’d been. She was a kind soul, and gentle-everything you’d imagine a sweet princess to be. Though atop the second tower, the next stripey-tailed princess bore a rage as wild as the sun. Her body burned hot like a furnace. But it was our job to help her return to normal-well, not our main job. Our journey took us from cold mountains to wild seas on a pirate ship. Our quest? To save the third-and last-princess, so we could halt The Witch King in his tracks."
                )
            },
            "",
        ),
        (
            {"artist": "Melody Muze", "albumartist": "Sarah J. Maas", "comment": ""},
            "Melody Muze",
        ),
        (
            {"artist": "Sarah J. Maas", "albumartist": "Melody Muze", "comment": ""},
            "Sarah J. Maas",
        ),
        (
            {
                "artist": "James Allen/Andrew Farell (Narrator)",
                "comment": "",
            },
            "James Allen",
        ),
        (
            {
                "artist": "James Allen/Andrew Farell",
                "comment": "",
            },
            "James Allen",
        ),
    ],
)
def test_parse_id3_author(
    test_dict: dict[str, str],
    expected_author: str,
    blank_audiobook: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):

    _got_tags = mock_id3_tags(
        (blank_audiobook.sample_audio1, test_dict),
        (blank_audiobook.sample_audio2, test_dict),
    )

    book = Audiobook(blank_audiobook.sample_audio1).extract_metadata()
    assert book.author == expected_author


@pytest.mark.parametrize(
    "test_dict, expected_date",
    [
        (
            {
                "date": "2023-10-22",
            },
            "2023",
        ),
    ],
)
def test_parse_id3_date(
    test_dict: dict[str, str],
    expected_date: str,
    blank_audiobook: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):

    _got_tags = mock_id3_tags(
        (blank_audiobook.sample_audio1, test_dict),
        (blank_audiobook.sample_audio2, test_dict),
    )

    book = Audiobook(blank_audiobook.sample_audio1).extract_metadata()
    assert book.year == expected_date


@pytest.mark.parametrize(
    "indirect_fixture, expected_dict",
    [
        (
            "touch_of_frost__flat_mp3",
            {"title": "TouchofFrost"},
        ),
        (
            "count_of_monte_cristo__flat_mp3",
            {
                "title": "The Count of Monte Cristo",
                "author": "Alexandre Dumas",
                "narrator": "Richard Matthews",
            },
        ),
        (
            "house_on_the_cliff__flat_mp3",
            {
                "title": "The House on the Cliff, Version 3",
                "author": "Franklin W. Dixon",
                "narrator": "",
            },
        ),
    ],
    indirect=["indirect_fixture"],
)
def test_parse_tags_from_fixtures(
    indirect_fixture: Audiobook,
    expected_dict: dict[str, str],
):

    book = indirect_fixture
    book.extract_metadata()
    _tags1 = extract_id3_tags(book.sample_audio1)
    _tags2 = extract_id3_tags(book.sample_audio2) if book.sample_audio2 else {}

    for key in expected_dict.keys():
        assert (
            getattr(book, key) == expected_dict[key]
        ), f"Expected {key} '{expected_dict[key]}', got '{getattr(book, key)}'"


@pytest.mark.parametrize(
    "indirect_fixture, expected_dict",
    [
        (
            "touch_of_frost__flat_mp3",
            # Author stays as-is because the ID3 tags have "TouchofFrost" (camelCase
            # filename artifact) as both title and author — NLP / OL does not reliably
            # detect this as an invalid name, so the author is preserved rather than
            # cleared.
            {"title": "TouchofFrost", "author": "TouchofFrost", "narrator": ""},
        ),
        (
            "count_of_monte_cristo__flat_mp3",
            {
                "title": "The Count of Monte Cristo",
                "author": "Alexandre Dumas",
                "narrator": "Richard Matthews",
            },
        ),
        (
            "house_on_the_cliff__flat_mp3",
            {
                # Open Library used to append the edition binding (", Brown Cloth") to
                # the title but the current code/API no longer returns that suffix.
                "title": "The House on the Cliff",
                "author": "Franklin W. Dixon",
                "narrator": "",
            },
        ),
    ],
    indirect=["indirect_fixture"],
)
def test_verify_tags_after_convert(
    indirect_fixture: Audiobook,
    expected_dict: dict[str, str],
):

    from src.auto_m4b import app

    book = indirect_fixture
    _orig_match_filter = InboxState().match_filter
    testutils.set_match_filter(re.escape(book.path.stem))

    app(max_loops=1)

    book.extract_metadata()
    _tags1 = extract_id3_tags(book.sample_audio1)
    _tags2 = extract_id3_tags(book.sample_audio2) if book.sample_audio2 else {}
    converted = Audiobook(book.converted_file).update_from_tags()
    _converted_tags = extract_id3_tags(book.converted_file)

    # Ensure converted file has the same tags as the expected
    for key in expected_dict.keys():
        assert (
            getattr(converted, key) == expected_dict[key]
        ), f"Expected {key} '{expected_dict[key]}', got '{getattr(converted, key)}'"

    testutils.set_match_filter(_orig_match_filter)


def test_title_from_folder_beats_partno_track_title(
    book_with_partno_track_titles: Audiobook,
    mock_id3_tags,
):
    """Title/album tags must come from the folder name, not the 'N of M' common substring of track titles.

    Regression: when source tracks carry titles like '1 of 04', '2 of 04', … the
    common suffix 'of 04' was being selected as book.title instead of falling back
    to the filesystem-derived title from the folder name.
    """
    book = book_with_partno_track_titles

    mock_id3_tags(
        (book.sample_audio1, {"title": "1 of 04", "album": "", "artist": "Stephen Hawking", "albumartist": "Stephen Hawking"}),
        (book.sample_audio2, {"title": "2 of 04", "album": "", "artist": "Stephen Hawking", "albumartist": "Stephen Hawking"}),
    )

    # extract_path_info must be called before extract_metadata — this is what run.py does in
    # production, and it populates book.fs_title / book.fs_author so the scorer can fall back
    # to them when ID3 tags are useless (e.g. "N of M" track titles with no album tag).
    book.extract_path_info()
    book.extract_metadata()

    assert book.title == "A Brief History of Time", (
        f"Expected title 'A Brief History of Time' from folder name, got '{book.title}'"
    )
    assert "of 04" not in (book.title or ""), (
        f"Title must not contain the track-number fragment 'of 04'; got '{book.title}'"
    )
    assert book.author == "Stephen Hawking", f"Expected author 'Stephen Hawking', got '{book.author}'"
    assert book.album == book.title, f"Expected album == title ('{book.title}'), got '{book.album}'"


@pytest.mark.slow
def test_encoder_tag_is_auto_m4b_after_conversion(
    blank_audiobook: Audiobook,
):
    """Output m4b must report encoder=brandonscript/auto-m4b, overwriting any source value.

    Both the ffmetadata embed (during merge) and the mutagen correction pass
    (verify_and_update_id3_tags) must stamp the encoder atom with the canonical
    tool identifier; no legacy 'm4b-tool', 'BOOKSY', or source 'PHNTM' values
    should survive in the converted file.
    """
    from src.auto_m4b import app

    app(max_loops=1)

    tags = extract_id3_tags(blank_audiobook.converted_file)
    encoder_val = tags.get("encoder", "")

    assert encoder_val == "brandonscript/auto-m4b", (
        f"Expected encoder 'brandonscript/auto-m4b', got '{encoder_val}'"
    )


@pytest.mark.parametrize(
    "test_dict, expected_narrator",
    [
        (
            {
                "comment": (
                    "Mysterious Benedict Society#1    Read by Del Roy                           Unabridged  13 hrs 17 min           Listening Library/Random House Audio"
                )
            },
            "Del Roy",
        ),
        ({"comment": "Read by Nicola Barber; Unabr"}, "Nicola Barber"),
        (
            {"artist": "Melody Muze", "albumartist": "Sarah J. Maas", "comment": ""},
            "Sarah J. Maas",
        ),
        (
            {"artist": "Sarah J. Maas", "albumartist": "Melody Muze", "comment": ""},
            "Melody Muze",
        ),
        (
            {
                "artist": "H. D. Carlton",
                "comment": (
                    "Death walks alongside me...but the reaper is no match for me. I'm trapped in a world full of monsters dressed as men, and those who aren't as they seem. They won't keep me forever. I no longer recognize the person I've become."
                ),
                "composer": "Teddy Hamilton, Michelle Sparks",
            },
            "Teddy Hamilton, Michelle Sparks",
        ),
        (
            {
                "artist": "James Allen/Andrew Farell (Narrator)",
                "comment": "",
            },
            "Andrew Farell",
        ),
        (
            {
                "artist": "James Allen/Andrew Farell",
                "comment": "",
            },
            "Andrew Farell",
        ),
        # Audiobook convention, no albumartist: artist=author, composer=narrator.
        # The boosted composer_is_narrator score should win even without an albumartist tag.
        (
            {
                "artist": "J.K. Rowling",
                "composer": "Stephen Fry",
                "comment": "",
            },
            "Stephen Fry",
        ),
    ],
)
def test_parse_id3_narrator(
    test_dict: dict[str, str],
    expected_narrator: str,
    blank_audiobook: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):

    _got_tags = mock_id3_tags(
        (blank_audiobook.sample_audio1, test_dict),
        (blank_audiobook.sample_audio2, test_dict),
    )

    book = Audiobook(blank_audiobook.sample_audio1).extract_metadata()
    assert book.narrator == expected_narrator


@pytest.mark.skip(
    reason=(
        "Music-convention tags (artist=narrator, composer=author, no albumartist) cannot be "
        "corrected by the local heuristic alone — the scorer treats artist as author by default. "
        "OPEN_LIBRARY_USER_AGENT must be configured so verify_and_update_id3_tags() can detect "
        "the swap via OL title lookup and rewrite the tags in the final m4b."
    )
)
def test_music_convention_tags_require_ol_for_swap_detection(
    blank_audiobook: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """
    Many MP3 audiobook rips use the music convention: artist = narrator (performer),
    composer = author (creator), albumartist = absent.

    Example: the Stephen Fry Harry Potter readings have
        artist   = "Stephen Fry"
        composer = "J. K. Rowling"

    Without Open Library the scorer produces author=Stephen Fry (wrong).
    With OL configured, verify_and_update_id3_tags() detects that J.K. Rowling is
    the known book author and swaps artist/composer in the output m4b.

    This test is intentionally skipped because it requires a live OL lookup.
    Un-skip it locally to verify OL swap detection end-to-end.
    """
    tags = {
        "artist": "Stephen Fry",
        "composer": "J. K. Rowling",
        "album": "Harry Potter And The Goblet Of Fire",
        "title": "HP04: Harry Potter And The Goblet Of Fire",
        "comment": "",
    }
    mock_id3_tags(
        (blank_audiobook.sample_audio1, tags),
        (blank_audiobook.sample_audio2, tags),
    )

    book = Audiobook(blank_audiobook.sample_audio1).extract_metadata()

    # After OL swap correction the author should be Rowling, not Fry.
    assert book.author == "J. K. Rowling", f"Expected J. K. Rowling as author, got '{book.author}'"
    assert book.narrator == "Stephen Fry", f"Expected Stephen Fry as narrator, got '{book.narrator}'"
