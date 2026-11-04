from pathlib import Path

import pytest

from src.lib.audiobook import Audiobook
from src.lib.ffmpeg_utils import get_bitrate_py, is_variable_bitrate
from src.lib.formatters import human_bitrate
from src.lib.parsers import (
    extract_path_info,
    get_name_from_str,
    parse_author,
    romans,
)
from src.tests.helpers.pytest_statics import PART_ROMANS, ROTK_ROMANS
from src.tests.helpers.pytest_utils import testutils
from src.tests.test_cleaners import strip_partno_tests


@pytest.mark.parametrize(
    "input_str, expected",
    [
        # fmt: off
        # Author names with middle initials — 'A.' must not be treated as the article 'a'
        ("James S.A. Corey", "James S.A. Corey"),
        ("James S. A. Corey", "James S. A. Corey"),
        # Folder-style strings: author before the dash
        ("James S.A. Corey - The Expanse Series", "James S.A. Corey"),
        ("James S. A. Corey - Leviathan Wakes (2011)", "James S. A. Corey"),
        # Other authors with 'a'-initial patterns should still work
        ("T.A. Barron - The Lost Years of Merlin", "T.A. Barron"),
        ("R.A. Salvatore - The Legend of Drizzt", "R.A. Salvatore"),
        # fmt: on
    ],
)
def test_parse_author_with_a_initials(input_str, expected):
    """parse_author must not truncate names at uppercase 'A.' initials.

    'get_name_from_str' split on the article 'a', which incorrectly treated
    'A.' (a name initial) as a separator, producing e.g. 'James S.' instead of
    'James S.A. Corey'.
    """
    result = parse_author(input_str, "fs" if " - " in input_str else "generic", fallback="")
    assert result == expected, f"parse_author({input_str!r}) returned {result!r}, expected {expected!r}"


@pytest.mark.parametrize(
    "input_str, expected",
    [
        # fmt: off
        ("James S.A. Corey", "James S.A. Corey"),
        ("James S. A. Corey", "James S. A. Corey"),
        ("Alexandre Dumas", "Alexandre Dumas"),
        # Still splits on title-casing articles in book titles
        ("Alexandre Dumas The Count of Monte Cristo", "Alexandre Dumas"),
        # fmt: on
    ],
)
def test_get_name_from_str_preserves_a_initials(input_str, expected):
    """get_name_from_str must not split 'James S.A.' at the 'A.' initial."""
    result = get_name_from_str(input_str)
    assert result == expected, f"get_name_from_str({input_str!r}) returned {result!r}, expected {expected!r}"


def test_parse_author_does_not_treat_possessive_title_as_author():
    """A possessive title before a dash is not an author delimiter."""
    value = "Wizard's Butler - [Wizard's Butler 01.0] The Wizard's Butler"

    assert parse_author(value, "fs", fallback="") == ""


@pytest.mark.parametrize(
    "book_dir, expected_title",
    [
        ("01 South Coast Shaman's Tales from the Golden Age of the Solar Clipper, Book 1", "South Coast"),
        ("02 Cape Grace Shaman's Tales from the Golden Age of the Solar Clipper, Book 2", "Cape Grace"),
        ("03 Finwell Bay Shaman's Tales from the Golden Age of the Solar Clipper, Book 3", "Finwell Bay"),
    ],
)
def test_extract_path_info_uses_series_book_prefix_as_title(book_dir, expected_title):
    """Do not promote an incidental NLP phrase from a numbered series path."""
    from src.lib.books_tree.books_tree import BooksTree

    child = (
        Path(__file__).parent
        / "fixtures"
        / "nathan_lowell__nested_series_m4a"
        / "Shaman's Tales from the Golden Age of the Solar Clipper"
        / book_dir
    )
    book = Audiobook(BooksTree(child))

    extract_path_info(book)

    assert book.fs_title == expected_title


@pytest.mark.parametrize(
    "fixture, relative_path, expected_title",
    [
        (
            "nathan_lowell__nested_series_m4a",
            "A Seeker's Tale from the Golden Age of the Solar Clipper/01 In Ashes Born",
            "In Ashes Born",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "A Seeker's Tale from the Golden Age of the Solar Clipper/02 To Fire Called A Seekers Tale from the Golden Age of the Solar Clipper, Book 2 (Unabridged)",
            "To Fire Called",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "A Seeker's Tale from the Golden Age of the Solar Clipper/03 By Darkness Forged A Seeker's Tale from the Golden Age of the Solar Clipper, Book 3",
            "By Darkness Forged",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "A Trader's Tale from the Golden Age of the Solar Clipper/01 Quarter Share",
            "Quarter Share",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "A Trader's Tale from the Golden Age of the Solar Clipper/02 Half Share",
            "Half Share",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "A Trader's Tale from the Golden Age of the Solar Clipper/03 Full Share A Trader's Tale from the Golden Age of the Solar Clipper, Book 3",
            "Full Share",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "A Trader's Tale from the Golden Age of the Solar Clipper/04 Double Share",
            "Double Share",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "A Trader's Tale from the Golden Age of the Solar Clipper/05 Captain's Share",
            "Captain's Share",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "A Trader's Tale from the Golden Age of the Solar Clipper/06 Owner's Share",
            "Owner's Share",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "Smuggler's Tales from the Golden Age of the Solar Clipper/01 Milk Run Smuggler's Tales, Book 1",
            "Milk Run",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "Smuggler's Tales from the Golden Age of the Solar Clipper/02 Suicide Run Smuggler's Tales, Book 2",
            "Suicide Run",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "Smuggler's Tales from the Golden Age of the Solar Clipper/03 Home Run",
            "Home Run",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "Tanyth Fairport Adventures/ 01 Ravenwood",
            "Ravenwood",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "Tanyth Fairport Adventures/03 The Hermit of Lammas Wood",
            "The Hermit of Lammas Wood",
        ),
        (
            "nathan_lowell__nested_series_m4a",
            "Tanyth Fairport Adventures/Wizard's Butler - [Wizard's Butler 01.0] The Wizard's Butler",
            "The Wizard's Butler",
        ),
        ("chanur_series__series_mp3", "02 - Chanur's Venture", "Chanur's Venture"),
        ("chanur_series__series_mp3", "01 - Pride Of Chanur", "Pride Of Chanur"),
        ("chanur_series__series_mp3", "03 - Kif Strikes Back", "Kif Strikes Back"),
        ("chanur_series__series_mp3", "04 - Chanur's Homecoming", "Chanur's Homecoming"),
        ("chanur_series__series_mp3", "05 - Chanur's Legacy", "Chanur's Legacy"),
        ("the_hobbit__multidisc_mp3", "J.R.R. Tolkien - The Hobbit - Disc 1", "The Hobbit"),
        ("secret_project_series__nested_flat_mixed", "Brandon Sanderson - 2023 - Yumi and the Nightmare Painter", "Yumi and the Nightmare Painter"),
    ],
)
def test_extract_path_info_fixture_title_corpus(fixture, relative_path, expected_title):
    """Keep representative real-world fixture names from regressing to NLP fragments."""
    from src.lib.books_tree.books_tree import BooksTree

    path = Path(__file__).parent / "fixtures" / fixture / relative_path
    book = Audiobook(BooksTree(path))

    extract_path_info(book)

    assert book.fs_title == expected_title


@pytest.mark.parametrize(
    "expected, prop, indirect_fixture",
    [
        ("Trenton Lee Stewart", "fs_author", "benedict_society__mp3"),
        ("The Mysterious Benedict Society", "fs_title", "benedict_society__mp3"),
    ],
    indirect=["indirect_fixture"],
)
def test_extract_path_info(expected, prop, indirect_fixture):

    assert getattr(extract_path_info(indirect_fixture), prop) == expected


def test_book_title_pattern_ignores_numeric_ranges():
    """Hyphens in 'Books1-3' must not be treated as 'Series - Title' separators.

    Regression: Crescent City Fae Complete Boxed Set Books1-3 → fs_title '3' → 3.m4b.
    """
    from src.lib.misc import re_group
    from src.lib.patterns import book_title_pattern

    assert re_group(book_title_pattern.search("Crescent City Fae Complete Boxed Set Books1-3"), "book_title") in (
        None,
        "",
    )
    assert (
        re_group(
            book_title_pattern.search("Premonition Pointe 02 - Witching for Hope (2020)"),
            "book_title",
        )
        == "Witching for Hope"
    )


def test_extract_path_info_books_range_not_title_three():
    """extract_path_info must not set fs_title to '3' for Books1-3 PartN filenames."""
    import shutil

    from src.lib.books_tree.books_tree import BooksTree
    from src.tests.helpers.pytest_dumps import TEST_DIRS

    folder = TEST_DIRS.inbox / "Crescent City Fae [Boxed Set]"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for i in (1, 2, 3):
            (folder / f"Crescent City Fae Complete Boxed Set Books1-3 Part{i}.mp3").write_bytes(b"x")

        book = Audiobook(BooksTree(folder))
        extract_path_info(book)
        assert book.fs_title != "3"
        # Prefer folder name or a substantial title extracted from the common filename
        assert len(book.fs_title) >= 3 or book.fs_title == ""
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_bitrate_vbr(bitrate_vbr__mp3: Audiobook):

    vbr_file = bitrate_vbr__mp3.sample_audio1

    std_bitrate, actual = get_bitrate_py(vbr_file)
    assert std_bitrate == 48000
    assert actual == 45567

    assert is_variable_bitrate(vbr_file)

    assert human_bitrate(vbr_file) == "~46 kb/s"


def test_bitrate_cbr(bitrate_cbr__mp3: Audiobook):

    cbr_file = bitrate_cbr__mp3.sample_audio1

    std_bitrate, actual = get_bitrate_py(cbr_file)
    assert std_bitrate == 128000
    assert actual == 128000

    assert not is_variable_bitrate(cbr_file)

    assert human_bitrate(cbr_file) == "128 kb/s"


@pytest.mark.parametrize(
    "input, expected",
    [
        ("A", {}),
        ("B", {}),
        ("8", {}),
        ("I", {"I": 1}),
        ("II", {"II": 1}),
        ("III", {"III": 1}),
        ("IV", {"IV": 1}),
        ("V", {"V": 1}),
        ("VI", {"VI": 1}),
        ("VII", {"VII": 1}),
        ("VIII", {"VIII": 1}),
        ("IX", {"IX": 1}),
        ("X", {"X": 1}),
        (["Star Wars", "Episode", "IV", "A New Hope"], {"IV": 1}),
        (["Star Wars", "Episode", "V", "The Empire Strikes Back"], {"V": 1}),
        (["Star Wars", "Episode", "VI", "Return of the Jedi"], {"VI": 1}),
        (["Star Wars", "Episode", "VII", "The Force Awakens"], {"VII": 1}),
        (["Star Wars", "Episode", "VIII", "The Last Jedi"], {"VIII": 1}),
        (["Star Wars", "Episode", "IX", "The Rise of Skywalker"], {"IX": 1}),
        (["Star Trek III: The Search for Spock"], {"III": 1}),
        (
            ["Chapter I", "Chapter II", "Chapter III", "Chapter IV"],
            {"I": 1, "II": 1, "III": 1, "IV": 1},
        ),
    ],
)
def test_get_roman_numerals_dict(input, expected):

    from src.lib.parsers import get_romans_dict

    assert get_romans_dict(input) == expected


@pytest.mark.parametrize(
    "test_files, expected",
    [
        (
            ROTK_ROMANS,
            False,
        ),
        (
            PART_ROMANS,
            True,
        ),
    ],
)
def test_roman_numerals_affect_file_order(test_files: list[str], expected, tmp_path: Path):

    from src.lib.parsers import roman_numerals_affect_file_order

    d = testutils.make_tmp_files(tmp_path, test_files)

    assert roman_numerals_affect_file_order(d) == expected


@pytest.mark.parametrize(
    "test_case, expected",
    [
        ("A", False),
        ("B", False),
        ("8", False),
        ("I", True),
        ("II", True),
        ("III", True),
        ("IV", True),
        ("V", True),
        ("VI", True),
        ("VII", True),
        ("VIII", True),
        ("IX", True),
        ("X", True),
        ("XI", True),
        ("XII", True),
        ("XIII", True),
        ("XIV", True),
        ("XV", True),
        ("XVI", True),
        ("XVII", True),
        ("XVIII", True),
        ("XIX", True),
        ("XX", True),
        ("XXI", True),
        ("XXII", True),
        ("XXIII", True),
        ("XXIV", True),
        ("XXV", True),
        ("XXVI", True),
        ("XXVII", True),
        ("XXVIII", True),
        ("XXIX", True),
        ("XXX", True),
        ("XXXI", True),
        ("XXXII", True),
        ("XXXIII", True),
        ("XXXIV", True),
        ("XXXV", True),
        ("XXXVI", True),
        ("XXXVII", True),
        ("XXXVIII", True),
        ("XXXIX", True),
        ("XL", True),
        ("XLI", True),
        ("XLII", True),
        ("XLIII", True),
        ("XLIV", True),
        ("XLV", True),
        ("XLVI", True),
        ("XLVII", True),
        ("XLVIII", True),
        ("XLIX", True),
        ("L", True),
        ("LI", True),
        ("LII", True),
        ("LIII", True),
        ("LIV", True),
        ("LV", True),
        ("LVI", True),
        ("LVII", True),
        ("LVIII", True),
        ("LIX", True),
        ("LX", True),
        ("LXI", True),
        ("LXII", True),
        ("LXIII", True),
        ("LXIV", True),
        ("LXV", True),
        ("LXVI", True),
        ("LXVII", True),
        ("LXVIII", True),
        ("LXIX", True),
        ("LXX", True),
    ],
)
def test_romans_is_roman_numeral(test_case, expected):

    assert romans.is_roman_numeral(test_case) == expected


@pytest.mark.parametrize(
    "test_case, expected",
    [
        ("A", []),
        ("B", []),
        ("8", []),
        ("I", ["I"]),
        ("II", ["II"]),
        ("Chapter III", ["III"]),
        ("Chapter IV", ["IV"]),
        ("Chapter V", ["V"]),
        ("Chapter VI", ["VI"]),
        ("Chapter VII", ["VII"]),
        ("Chapter VIII", ["VIII"]),
        ("Chapter IX", ["IX"]),
        ("Chapter X", ["X"]),
        ("Chapter XI", ["XI"]),
        ("Chapter XII", ["XII"]),
        ("Chapter XIII", ["XIII"]),
        ("Star Wars Episode IV: A New Hope", ["IV"]),
        ("Star Wars Episode V: The Empire Strikes Back", ["V"]),
        ("Star Wars Episode VI: Return of the Jedi", ["VI"]),
        ("Star Wars Episode VII: The Force Awakens", ["VII"]),
        ("Star Wars Episode VIII: The Last Jedi", ["VIII"]),
        ("Star Wars Episode IX: The Rise of Skywalker", ["IX"]),
        ("Star Trek III: The Search for Spock", ["III"]),
        ("Dune: Parts II & III - Muad'Dib & The Prophet", ["II", "III"]),
    ],
)
def test_romans_find_all(test_case, expected):

    assert romans.find_all(test_case) == expected


@pytest.mark.parametrize(
    "int_or_roman, expected",
    [
        (1, 1),
        (2, 2),
        (3, 3),
        (9, 9),
        (10, 10),
        (149, 149),
        (310, 310),
        ("001", 1),
        ("01", 1),
        ("1", 1),
        ("55", 55),
        ("0901", 901),
        ("I", 1),
        ("II", 2),
        ("III", 3),
        ("IV", 4),
        ("V", 5),
        ("VI", 6),
        ("VII", 7),
        ("VIII", 8),
        ("IX", 9),
        ("X", 10),
        ("XI", 11),
        ("XII", 12),
        ("XIII", 13),
        ("XIV", 14),
        ("XV", 15),
        ("XVI", 16),
        ("XVII", 17),
        ("XVIII", 18),
        ("XIX", 19),
        ("XX", 20),
        ("XXI", 21),
        ("XXII", 22),
        ("XXIII", 23),
        ("XXIV", 24),
        ("XXV", 25),
        ("XXVI", 26),
        ("XXVII", 27),
        ("XXVIII", 28),
        ("XXIX", 29),
        ("XXX", 30),
        ("i", 1),
        ("iI", 2),
        ("IiI", 3),
        ("Iv", 4),
        ("V", 5),
        ("v", 5),
        ("vi", 6),
        ("VIi", 7),
        ("vIIi", 8),
        ("ix", 9),
        ("x", 10),
        ("X", 10),
        ("  I ", 1),
        (" VI   ", 6),
        # not roman numerals, but contain roman numeral chars
        ("nothin'", -1),
        ("investigator", -1),
        ("codex", -1),
    ],
)
def test_romans_to_int(int_or_roman, expected):

    from src.lib.parsers import romans

    assert romans.to_int(int_or_roman) == expected


@pytest.mark.parametrize(
    "test_case, expected",
    [
        ("Bk1", False),
        ("Bk-1", False),
        ("Book1", False),
        ("Book-1", False),
        ("Book.1", False),
        ("Book_1", False),
        ("Book 1", False),
        ("Book 1 - The Fellowship of the Ring", False),
        ("CD1", True),
        ("CD-1", True),
        ("cd1", True),
        ("Disc-1", True),
        ("Disk.1", True),
        ("Disc_1", True),
        ("CD 1", True),
        ("Disc 1 - The Fellowship of the Ring", True),
        ("The Fellowship of the Ring - CD 1", True),
        ("Disk", False),
        ("Disc", False),
        ("CD", False),
        ("The Fellowship of the Ring", False),
        ("The Fellowship of the Ring - CD", False),
        ("The Fellowship of the Ring - Disc", False),
        ("The Fellowship of the Ring - Disc #3", True),
        ("The Fellowship of the Ring - Disc # 3", True),
        ("The Fellowship of the Ring - Disc.3", True),
        ("The Fellowship of the Ring - Disc.#3", True),
        ("#", False),
        ("#1", False),
        ("#-1", False),
        ("#1", False),
        ("#-1", False),
        ("#1", False),
        ("#1", False),
        ("# 1", False),
        ("Aleron Kong - The Land Alliances (Chaos Seeds #3)", False),
        ("# 3 (Chaos Seeds) - Aleron Kong - The Land Alliances", False),
        ("The Land Alliances (Chaos Seeds #3) - Aleron Kong", False),
        ("#The Land Alliances (Chaos Seeds)", False),
        ("The Land Alliances (Chaos Seeds) - #", False),
        ("The Land Alliances (Disc #1)", True),
    ],
)
def test_is_maybe_multi_disc(test_case, expected):

    from src.lib.parsers import is_maybe_multi_disc

    assert is_maybe_multi_disc(test_case) == expected
    assert is_maybe_multi_disc(test_case.lower()) == expected
    assert is_maybe_multi_disc(test_case.title()) == expected
    assert is_maybe_multi_disc(test_case.capitalize()) == expected
    assert is_maybe_multi_disc(test_case.upper()) == expected


@pytest.mark.parametrize(
    "test_case, expected",
    [
        ("Pt1", True),
        ("part1", True),
        ("part_1", True),
        ("Pt8", True),
        ("Pt-8", True),
        ("Part8", True),
        ("Part-8", True),
        ("Part.8", True),
        ("Part_8", True),
        ("Part 8", True),
        ("Part 8 - Quest for the Spark", True),
        ("Quest for the Spark - Pt 8", True),
        ("Part", False),
        ("Quest for the Spark", False),
        ("Quest for the Spark - Pt", False),
    ],
)
def test_is_maybe_multi_part(test_case, expected):

    from src.lib.parsers import is_maybe_multi_part

    assert is_maybe_multi_part(test_case) == expected
    assert is_maybe_multi_part(test_case.lower()) == expected
    assert is_maybe_multi_part(test_case.title()) == expected
    assert is_maybe_multi_part(test_case.capitalize()) == expected
    assert is_maybe_multi_part(test_case.upper()) == expected


series_true_tests = [
    "Bk1",
    "Bk-1",
    "Book1",
    "Book-1",
    "Book.1",
    "Book_1",
    "Book 1",
    "Book 1 - The Fellowship of the Ring",
    "The Fellowship of the Ring - Bk 1",
    "#1",
    "#-1",
    "#1",
    "#-1",
    "#1",
    "#1",
    "# 1",
    "Old Man's War Series/Old Man's War - John Scalzi",
    "Aleron Kong - The Land Alliances (Chaos Seeds #3)",
    "# 3 (Chaos Seeds) - Aleron Kong - The Land Alliances",
    "The Land Alliances (Chaos Seeds #3) - Aleron Kong",
]


@pytest.mark.parametrize(
    "test_case, expected",
    [
        *[(test_case, True) for test_case in series_true_tests],
        *[
            ("01 - Pride Of Chanur", False),
            ("Book", False),
            ("The Fellowship of the Ring", False),
            ("The Fellowship of the Ring - Bk", False),
            ("#", False),
            ("#The Land Alliances (Chaos Seeds)", False),
            ("The Land Alliances (Chaos Seeds) - #", False),
            ("The Land Alliances (Disc #1)", False),
        ],
    ],
)
def test_is_maybe_multiple_books_or_series(test_case, expected):

    from src.lib.parsers import is_maybe_series_book

    assert is_maybe_series_book(test_case) == expected
    assert is_maybe_series_book(test_case.lower()) == expected
    assert is_maybe_series_book(test_case.title()) == expected
    assert is_maybe_series_book(test_case.capitalize()) == expected
    assert is_maybe_series_book(test_case.upper()) == expected


@pytest.mark.parametrize(
    "s1, s2, expected",
    [
        *[(s1, None, False) for s1 in series_true_tests],
        *[(t, None, True) for (t, _) in strip_partno_tests],
        *[
            (
                "0100 _ Books on Tape _ The Count of Monte Cristo _ Alexandre Dumas",
                "0101 _ Ch 01 _ The Arrival at Marseilles",
                True,
            ),
        ],
    ],
)
def test_contains_partno_or_ch(s1, s2, expected):

    from src.lib.parsers import contains_partno_or_ch

    assert contains_partno_or_ch(s1, s2) == expected


@pytest.mark.parametrize(
    "test_case, expected",
    [
        # fmt: off
        ("Alexandre Dumas", [("Alexandre Dumas", 4.6)]),
        ("Matthew Nicol", [("Matthew Nicol", 0.91)]),
        ("Andrea Camilleri", [("Andrea Camilleri", 3.5)]),
        ("Camilleri, Andrea", [("Andrea Camilleri", 3.5)]),
        ("John S. Marr", [("John S. Marr", 2.35)]),
        ("Marr, John S.", [("John S. Marr", 2.35)]),
        ("Read by Leonard Porter", [("Leonard Porter", 1.2)]),
        ("Read by J. Scott", [("J. Scott", 3.1)]),
        ("Franklin W Dixon", [("Franklin W. Dixon", 3.6)]),
        ("Franklin W. Dixon", [("Franklin W. Dixon", 3.8)]),
        ("Colette Cœtre-Conté", [("Colette Cœtre-Conté", 1.8)]),
        ("Alexandre Dumas The Count of Monte Cristo", [("Alexandre Dumas", 4.6), ("Monte Cristo", -0.125)]),
        ("0100 _ Books on Tape _ The Count of Monte Cristo _ Alexandre Dumas", [("Alexandre Dumas", 4.6), ("Monte Cristo", -0.125)]),
        ("The Lord of the Rings - J.R.R. Tolkien", [("J.R.R. Tolkien", 3.6)]),
        ("The Lord of the Rings - Tolkien, J.R.R.", [("J.R.R. Tolkien", 3.6)]),
        ("Old Man's War Series/Old Man's War - John Scalzi", [("John Scalzi", 3.8), ("Old Man", 0.751)]),
        ("Aleron Kong - The Land Alliances (Chaos Seeds #3)", [("Aleron Kong", 2.3), ("Chaos Seeds", -0.175)]),
        ("Melody Muze as Feyre", [('Melody Muze', 0.99), ('Feyre',  0.84)]),
        # fmt: on
    ],
)
def test_get_nlp_names(test_case, expected):

    from src.lib.parsers import get_nlp_names

    results = get_nlp_names(test_case, no_cache=True)
    for (name, label, score), (exp_name, _exp_score) in zip(results, expected):
        assert name == exp_name
        assert label.startswith("PER"), f"{name} does not start with PER____"
