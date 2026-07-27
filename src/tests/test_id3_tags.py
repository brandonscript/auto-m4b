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
                # Source album tag includes the LibriVox edition suffix ", Version 3".
                # extract_metadata preserves this faithfully; verify_and_update_id3_tags
                # strips it when writing the final output (see test_verify_tags_after_convert).
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
            # Source files have garbled camelCase tags (no artist/album, title =
            # "TouchofFrostPart1...").  Without OL configured the heuristic cannot
            # find an author, so author stays empty.  With OL, it would resolve to
            # the real author ("Jennifer Estep").  Title is the common filename
            # prefix "TouchofFrost".
            {"title": "TouchofFrost", "author": "", "narrator": ""},
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


def test_title_strips_author_prefix_from_filename_style_tag(
    book_with_filename_as_title_tag: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """When a title tag is set to the full filesystem name (author + dash + title),
    the scorer must strip the author prefix so the displayed title is clean.

    Regression: rippers like mp3tag embed the folder name verbatim as the title
    tag (e.g. "Jeffery Deaver - Pellham Series 02 Bloody River Blues 1993 001-033").
    Two files in the same folder differ only in the trailing track range, so GCS
    produces a truncated common prefix ending with a bare digit ("...1993 0").
    The fix in TagScorer recovers title1 from the truncated GCS, and the
    post-processing step in extract_metadata strips the author prefix.
    """
    book = book_with_filename_as_title_tag
    author = "Jeffery Deaver"

    # Set title tags to the full filename — mimics what many rippers do.
    file1_title = f"{author} - Pellham Series 02 Bloody River Blues 1993 001-033"
    file2_title = f"{author} - Pellham Series 02 Bloody River Blues 1993 034-066"

    mock_id3_tags(
        (book.sample_audio1, {"title": file1_title, "album": "", "artist": author, "albumartist": author}),
        (book.sample_audio2, {"title": file2_title, "album": "", "artist": author, "albumartist": author}),
    )

    book.extract_path_info()
    book.extract_metadata()

    # The GCS-truncated version ends with a bare "0" (from "1993 001" vs "1993 034").
    # After the fix, title_c is replaced with title1 so the full track suffix is present.
    assert book.title and not book.title.rstrip().endswith("0"), (
        f"Title must not end with truncated digit '0'; got '{book.title}'"
    )
    # The author prefix should have been stripped.
    assert not book.title.startswith(author), (
        f"Title must not start with the author name '{author}'; got '{book.title}'"
    )
    # The real book title should be present.
    assert "Bloody River Blues" in (book.title or ""), (
        f"Expected 'Bloody River Blues' in title, got '{book.title}'"
    )
    # Author should still be correct.
    assert book.author == author, f"Expected author '{author}', got '{book.author}'"


def test_title_strips_author_prefix_single_file(
    book_with_partno_track_titles: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """Single-file book where the title tag equals 'Author - Book Title (Year)'.

    The author prefix and year suffix should be stripped so the final title is
    just the book title.  This covers the Lincoln Rhyme / Cold Moon scenario.
    """
    book = book_with_partno_track_titles
    author = "Jeffery Deaver"
    full_title = "Jeffery Deaver - Lincoln Rhyme Series 07 The Cold Moon 2006"

    mock_id3_tags(
        (book.sample_audio1, {"title": full_title, "album": "", "artist": author, "albumartist": author}),
        (book.sample_audio2, {"title": full_title, "album": "", "artist": author, "albumartist": author}),
    )

    book.extract_path_info()
    book.extract_metadata()

    assert not book.title.startswith(author), (
        f"Author prefix must be stripped from title; got '{book.title}'"
    )
    assert "The Cold Moon" in (book.title or ""), (
        f"Expected 'The Cold Moon' in title, got '{book.title}'"
    )
    assert book.author == author, f"Expected author '{author}', got '{book.author}'"


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


def test_ol_sentence_case_does_not_downgrade_title(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """When OL returns the title in sentence case but the existing tag is already
    properly title-cased, _check_title must keep the existing casing.

    Regression: 'The Assassin King' (correct) was being replaced by
    'The assassin king' (sentence case from the OL database).
    """
    import shutil
    from unittest.mock import MagicMock, PropertyMock, patch

    from src.lib.id3_utils import verify_and_update_id3_tags

    book = book_in_author_named_folder
    title = "The Assassin King"
    author = "Elizabeth Haydon"

    mock_id3_tags(
        (book.sample_audio1, {"title": title, "album": title, "artist": author, "albumartist": author}),
        (book.sample_audio2, {"title": title, "album": title, "artist": author, "albumartist": author}),
    )

    book.extract_path_info()
    book.extract_metadata()

    # Place a tagged copy in the build dir as an mp3 and patch build_file to
    # return it — verify_and_update_id3_tags only needs a readable audio file,
    # and mutagen can write ID3 tags to mp3 but not to a fake .m4b stub.
    book.build_dir.mkdir(parents=True, exist_ok=True)
    build_mp3 = book.build_dir / f"{title}.mp3"
    shutil.copy(book.sample_audio1, build_mp3)
    write_id3_tags_mutagen(build_mp3, {"title": title, "album": title, "artist": author, "albumartist": author})

    # Simulate OL returning the title in sentence case (common in OL database)
    ol_sentence_case = title.lower().capitalize()  # "The assassin king"
    mock_ol_result = MagicMock()
    mock_ol_result.__bool__ = lambda self: True
    mock_ol_result.has_match = True
    mock_ol_result.score = MagicMock(return_value=0.8)  # >= 0.5 → triggers update
    mock_ol_result.title = ol_sentence_case
    mock_ol_result.author_and_narrator_swapped = False
    mock_ol_result.author_score = MagicMock(return_value=0.95)
    mock_ol_result.author = author
    mock_ol_result.narrator = ""
    mock_ol_result.date = ""

    with patch("src.lib.id3_utils.open_library_lookup_title", return_value=mock_ol_result):
        with patch("src.lib.id3_utils.open_library_lookup_author", return_value=MagicMock(__bool__=lambda self: False)):
            with patch.object(type(book), "build_file", new_callable=PropertyMock, return_value=build_mp3):
                verify_and_update_id3_tags(book, in_dir="build")

    result_tags = extract_id3_tags(build_mp3)
    assert result_tags.get("title") == title, (
        f"OL sentence-case title '{ol_sentence_case}' must not overwrite properly-cased '{title}'; "
        f"got '{result_tags.get('title')}'"
    )


def test_build_file_uses_title_not_folder_name(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """When the inbox folder is named after the author (e.g. 'Haydon, Elizabeth'),
    build_file and final_desc_file must use the book title as the stem, not the
    folder name.

    Regression: the output m4b was named 'Haydon, Elizabeth.m4b' and the
    description file 'Haydon, Elizabeth [~61 kbps @ 44.1 kHz].txt'.
    """
    book = book_in_author_named_folder
    title = "The Assassin King"
    author = "Elizabeth Haydon"

    mock_id3_tags(
        (book.sample_audio1, {"title": title, "album": title, "artist": author, "albumartist": author}),
        (book.sample_audio2, {"title": title, "album": title, "artist": author, "albumartist": author}),
    )

    book.extract_path_info()
    book.extract_metadata()
    book.set_active_dir("build")

    # build_file stem must be the title, not the folder name
    assert book.build_file.stem == title, (
        f"build_file stem must be '{title}' (title), not '{book.build_file.stem}' (folder name)"
    )
    assert "Haydon" not in book.build_file.stem, (
        f"build_file must not use the author folder name; got '{book.build_file}'"
    )

    # final_desc_file stem must also use the title
    book.set_active_dir("converted")
    assert title in book.final_desc_file.name, (
        f"final_desc_file must contain the book title '{title}'; got '{book.final_desc_file.name}'"
    )
    assert "Haydon, Elizabeth" not in book.final_desc_file.stem, (
        f"final_desc_file must not use the author folder name; got '{book.final_desc_file.name}'"
    )


def test_ol_first_extraction_album_is_author(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """When a ripper stores author-name in the album field and the real book
    title in the title field, OL-first extraction must identify the correct
    title and author without relying on heuristic scoring.

    Regression scenario (Laurie R. King – 'The God of the Hive'):
        title  = "The God of the Hive"   ← correct book title
        artist = "read by Jenny Sterlin" ← narrator, not author
        album  = "Laurie R. King"        ← author stored as album

    Without OL-first, the heuristic scorer sees album="Laurie R. King" and
    may select it as the title because artist/album scoring is ambiguous.
    With OL-first, OL looks up "The God of the Hive" (title field) and
    returns author="Laurie R. King", resolving the confusion immediately.
    """
    from unittest.mock import MagicMock, patch

    book = book_in_author_named_folder
    book_title = "The Assassin King"
    author = "Elizabeth Haydon"
    narrator = "Jenny Sterlin"

    mock_id3_tags(
        (book.sample_audio1, {
            "title": book_title,
            "artist": f"read by {narrator}",
            "album": author,          # ← author stored as album (the bug pattern)
            "albumartist": "",
        }),
        (book.sample_audio2, {
            "title": book_title,
            "artist": f"read by {narrator}",
            "album": author,
            "albumartist": "",
        }),
    )

    book.extract_path_info()

    # Mock OL: when queried with the book title it returns the correct author
    ol_result = MagicMock()
    ol_result.__bool__ = lambda self: True
    ol_result.has_match = True
    ol_result.score = MagicMock(return_value=0.95)  # very confident (high similarity)
    ol_result.title = book_title
    ol_result.author = author
    ol_result.narrator = ""
    ol_result.date = "2006"
    ol_result.author_and_narrator_swapped = False
    ol_result.author_score = MagicMock(return_value=0.95)

    # Simulate OL-first returning a confident match: title and author resolved.
    # The function now returns the OpenLibraryTitle object (or None on failure).
    def _fake_ol(b, t1, t2):
        b.title = book_title
        b.album = book_title
        b.sortalbum = book_title
        b.artist = author
        b.albumartist = author
        return ol_result  # truthy → ol_resolved = True

    with patch("src.lib.id3_utils._ol_early_extraction", side_effect=_fake_ol):
        book.extract_metadata()

    assert book.title == book_title, (
        f"OL-first: title should be '{book_title}', got '{book.title}'"
    )
    assert book.artist == author, (
        f"OL-first: author (artist) should be '{author}', got '{book.artist}'"
    )
    assert book.narrator == narrator, (
        f"OL-first: narrator should be '{narrator}', got '{book.narrator}'"
    )


def _make_ol_result(score: float, title: str, author: str, date: str = "") -> "MagicMock":
    """Helper to build a mock OpenLibraryTitle for _ol_early_extraction tests."""
    from unittest.mock import MagicMock

    r = MagicMock()
    r.__bool__ = lambda self: True
    r.has_match = True
    r.score = MagicMock(return_value=score)
    r.title = title
    r.author = author
    r.narrator = ""
    r.date = date
    return r


def test_ol_early_extraction_accepts_high_similarity_score(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """_ol_early_extraction must accept a high-similarity OL result (score >= 0.5).

    Regression: the scoring convention was inverted — a perfect fuzz.ratio match
    returns score=1.0, but the old code checked `score < best_score` starting from
    1.0 so 1.0 < 1.0 is False and best_ol was never set, causing all good matches
    (including exact ones like 'Map of Bones') to be silently rejected.
    """
    from unittest.mock import PropertyMock, patch

    from src.lib.id3_utils import _ol_early_extraction

    book = book_in_author_named_folder
    title = "Map of Bones"
    author = "James Rollins"

    mock_id3_tags(
        (book.sample_audio1, {"title": title, "artist": author, "album": title, "albumartist": author}),
        (book.sample_audio2, {"title": title, "artist": author, "album": title, "albumartist": author}),
    )
    book.extract_path_info()

    ol_result = _make_ol_result(score=1.0, title=title, author=author, date="2005")

    from src.lib.config import cfg as real_cfg
    from src.lib.id3_tags import Id3Tags

    tag1 = Id3Tags.from_file(book.sample_audio1, throw=False)
    with patch("src.lib.id3_utils.open_library_lookup_title", return_value=ol_result):
        with patch.object(type(real_cfg), "OPEN_LIBRARY_USER_AGENT", new_callable=PropertyMock, return_value="test-agent/1.0"):
            result = _ol_early_extraction(book, tag1, tag1)

    assert result is not None, "High-similarity OL match (score=1.0) must be accepted"
    assert book.title == title, f"Expected title '{title}', got '{book.title}'"
    assert book.artist == author, f"Expected author '{author}', got '{book.artist}'"


def test_ol_early_extraction_rejects_low_similarity_score(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """_ol_early_extraction must reject a low-similarity OL result (score < 0.5).

    A poor fuzzy match should not override heuristic extraction.
    """
    from unittest.mock import PropertyMock, patch

    from src.lib.id3_utils import _ol_early_extraction

    book = book_in_author_named_folder
    mock_id3_tags(
        (book.sample_audio1, {"title": "Some Book", "artist": "Some Author", "album": "", "albumartist": ""}),
        (book.sample_audio2, {"title": "Some Book", "artist": "Some Author", "album": "", "albumartist": ""}),
    )
    book.extract_path_info()

    ol_result = _make_ol_result(score=0.3, title="Completely Different Book", author="Wrong Author")

    from src.lib.config import cfg as real_cfg
    from src.lib.id3_tags import Id3Tags

    tag1 = Id3Tags.from_file(book.sample_audio1, throw=False)
    with patch("src.lib.id3_utils.open_library_lookup_title", return_value=ol_result):
        with patch.object(type(real_cfg), "OPEN_LIBRARY_USER_AGENT", new_callable=PropertyMock, return_value="test-agent/1.0"):
            result = _ol_early_extraction(book, tag1, tag1)

    assert result is None, "Low-similarity OL match (score=0.3) must be rejected"


def test_verify_tags_applies_ol_with_perfect_similarity_score(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """verify_and_update_id3_tags must apply OL data even when score=1.0 (perfect match).

    Regression: the old threshold was `score < 0.9` (treating score as distance),
    so a perfect similarity score of 1.0 was never < 0.9 and OL corrections were
    silently skipped. The fixed threshold is `score >= 0.5`.
    """
    import shutil
    from unittest.mock import MagicMock, PropertyMock, patch

    from src.lib.id3_utils import verify_and_update_id3_tags

    book = book_in_author_named_folder
    title = "Map of Bones"
    corrected_author = "James Rollins"
    wrong_author = "James Rolins"  # typo in source tag

    mock_id3_tags(
        (book.sample_audio1, {"title": title, "album": title, "artist": wrong_author, "albumartist": wrong_author}),
        (book.sample_audio2, {"title": title, "album": title, "artist": wrong_author, "albumartist": wrong_author}),
    )
    book.extract_path_info()
    book.artist = wrong_author
    book.albumartist = wrong_author
    book.title = title

    book.build_dir.mkdir(parents=True, exist_ok=True)
    build_mp3 = book.build_dir / f"{title}.mp3"
    shutil.copy(book.sample_audio1, build_mp3)
    write_id3_tags_mutagen(build_mp3, {"title": title, "album": title, "artist": wrong_author, "albumartist": wrong_author})

    ol_result = MagicMock()
    ol_result.__bool__ = lambda self: True
    ol_result.has_match = True
    ol_result.score = MagicMock(return_value=1.0)  # perfect match — previously skipped
    ol_result.title = title
    ol_result.author = corrected_author
    ol_result.narrator = ""
    ol_result.date = "2005"
    ol_result.author_score = MagicMock(return_value=0.9)
    ol_result.author_and_narrator_swapped = False

    with patch("src.lib.id3_utils.open_library_lookup_title", return_value=ol_result):
        with patch("src.lib.id3_utils.open_library_lookup_author", return_value=MagicMock(__bool__=lambda self: False)):
            with patch.object(type(book), "build_file", new_callable=PropertyMock, return_value=build_mp3):
                verify_and_update_id3_tags(book, in_dir="build")

    result_tags = extract_id3_tags(build_mp3)
    assert result_tags.get("artist") == corrected_author, (
        f"OL perfect-score correction must apply: expected '{corrected_author}', got '{result_tags.get('artist')}'"
    )


def test_album_tag_used_as_title_when_title_has_part_number(
    book_with_partno_track_titles: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """When individual track title tags carry part numbers (e.g. 'War and Peace,
    Part 1' / 'War and Peace, Part 5') but the album tag carries the clean book
    title ('War and Peace'), the metadata extraction must prefer the album tag
    for book.title.

    Regression: _ol_early_extraction tried the raw part-titled track first and
    OL matched it ('War and Peace Part 1'), locking in the wrong title.  The
    determine_title() scorer also failed to penalise the individual titles
    because the *common* prefix between title1 and title2 ('War and Peace')
    doesn't contain a part number — only the individual titles do.
    """
    book = book_with_partno_track_titles

    mock_id3_tags(
        (
            book.sample_audio1,
            {
                "title": "War and Peace, Part 1",
                "album": "War and Peace",
                "artist": "Leo Tolstoy",
                "albumartist": "Leo Tolstoy",
                "tracknumber": "1/5",
            },
        ),
        (
            book.sample_audio2,
            {
                "title": "War and Peace, Part 5",
                "album": "War and Peace",
                "artist": "Leo Tolstoy",
                "albumartist": "Leo Tolstoy",
                "tracknumber": "5/5",
            },
        ),
    )

    book.extract_path_info()
    book.extract_metadata()

    # The whole-book title must come from the album tag, not the part-tagged track title
    assert book.title == "War and Peace", (
        f"Expected title 'War and Peace' (from album tag), got '{book.title}'"
    )
    assert "Part" not in (book.title or ""), (
        f"Title must not contain 'Part'; got '{book.title}'"
    )
    assert book.author == "Leo Tolstoy", (
        f"Expected author 'Leo Tolstoy', got '{book.author}'"
    )


def test_ol_early_extraction_title_cases_sentence_case_ol_title(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """OL sentence-case titles must be Title-Cased when assigned to book.title.

    Regression: 'The sunne in splendour' from OL produced sentence-case output
    filenames (build_file / final_desc_file) and ID3 title tags.
    """
    from unittest.mock import PropertyMock, patch

    from src.lib.config import cfg as real_cfg
    from src.lib.id3_tags import Id3Tags
    from src.lib.id3_utils import _ol_early_extraction

    book = book_in_author_named_folder
    # Seed ID3 with sentence case so OL is the authority for the match.
    mock_id3_tags(
        (
            book.sample_audio1,
            {
                "title": "The sunne in splendour",
                "album": "The sunne in splendour",
                "artist": "Sharon Kay Penman",
                "albumartist": "Sharon Kay Penman",
            },
        ),
        (
            book.sample_audio2,
            {
                "title": "The sunne in splendour",
                "album": "The sunne in splendour",
                "artist": "Sharon Kay Penman",
                "albumartist": "Sharon Kay Penman",
            },
        ),
    )
    book.extract_path_info()

    ol_result = _make_ol_result(
        score=0.95,
        title="The sunne in splendour",
        author="Sharon Kay Penman",
        date="1982",
    )
    tag1 = Id3Tags.from_file(book.sample_audio1, throw=False)
    with patch("src.lib.id3_utils.open_library_lookup_title", return_value=ol_result):
        with patch.object(
            type(real_cfg),
            "OPEN_LIBRARY_USER_AGENT",
            new_callable=PropertyMock,
            return_value="test-agent/1.0",
        ):
            result = _ol_early_extraction(book, tag1, tag1)

    assert result is not None
    assert book.title == "The Sunne in Splendour", (
        f"Expected Title-Cased OL title, got '{book.title}'"
    )
    # build_file / desc file stems are driven by book.title
    assert book.build_file.stem == "The Sunne in Splendour"
    assert "The Sunne in Splendour" in book.final_desc_file.name


def test_ol_verify_title_cases_sentence_case_into_id3_tags(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """verify_and_update_id3_tags must write Title-Cased OL titles into ID3 tags.

    When book.title is still sentence-cased (e.g. early extraction did not run)
    and OL returns sentence case, the written tag must still be Title Case.
    """
    import shutil
    from unittest.mock import MagicMock, PropertyMock, patch

    from src.lib.id3_utils import verify_and_update_id3_tags

    book = book_in_author_named_folder
    author = "Sharon Kay Penman"
    sentence = "The reckoning"
    expected = "The Reckoning"

    mock_id3_tags(
        (book.sample_audio1, {"title": sentence, "album": sentence, "artist": author, "albumartist": author}),
        (book.sample_audio2, {"title": sentence, "album": sentence, "artist": author, "albumartist": author}),
    )
    book.extract_path_info()
    book.extract_metadata()
    # Force sentence-case book.title so verify's OL path is the fixer.
    book.title = sentence
    book.album = sentence

    book.build_dir.mkdir(parents=True, exist_ok=True)
    build_mp3 = book.build_dir / f"{sentence}.mp3"
    shutil.copy(book.sample_audio1, build_mp3)
    write_id3_tags_mutagen(
        build_mp3, {"title": sentence, "album": sentence, "artist": author, "albumartist": author}
    )

    mock_ol_result = MagicMock()
    mock_ol_result.__bool__ = lambda self: True
    mock_ol_result.has_match = True
    mock_ol_result.score = MagicMock(return_value=0.9)
    mock_ol_result.title = sentence
    mock_ol_result.author_and_narrator_swapped = False
    mock_ol_result.author_score = MagicMock(return_value=0.95)
    mock_ol_result.author = author
    mock_ol_result.narrator = ""
    mock_ol_result.date = ""

    with patch("src.lib.id3_utils.open_library_lookup_title", return_value=mock_ol_result):
        with patch(
            "src.lib.id3_utils.open_library_lookup_author",
            return_value=MagicMock(__bool__=lambda self: False),
        ):
            with patch.object(type(book), "build_file", new_callable=PropertyMock, return_value=build_mp3):
                verify_and_update_id3_tags(book, in_dir="build")

    result_tags = extract_id3_tags(build_mp3)
    assert result_tags.get("title") == expected, (
        f"Expected ID3 title '{expected}', got '{result_tags.get('title')}'"
    )
    assert result_tags.get("album") == expected, (
        f"Expected ID3 album '{expected}', got '{result_tags.get('album')}'"
    )
