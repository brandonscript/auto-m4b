from pathlib import Path

import pytest

from src.lib.misc import isorted
from src.lib.parsers import romans
from src.tests.helpers.pytest_statics import (
    PART_NO_ROMANS,
    PART_ROMANS,
    ROTK_NO_ROMANS,
    ROTK_ROMANS,
)
from src.tests.helpers.pytest_utils import testutils


@pytest.mark.parametrize(
    "test_str, expected",
    [
        ("disc 1", ""),
        ("Disc 1", ""),
        ("CD 1", ""),
        ("cd1", ""),
        ("CD 2", ""),
        ("cd.3", ""),
        ("(Disc 4)", ""),
        (" - disc 5", ""),
        (
            "The Last Guardian (Disc 01) - Track07.mp3",
            "The Last Guardian - Track07.mp3",
        ),
        (
            "The Last Guardian - Disc 01 - Track07.mp3",
            "The Last Guardian - Track07.mp3",
        ),
        (
            "The Last Guardian (Disc 01)",
            "The Last Guardian",
        ),
        (
            "The Last Guardian - Disc 01",
            "The Last Guardian",
        ),
        (
            "The Last Guardian, CD01",
            "The Last Guardian",
        ),
    ],
)
def test_strip_disc_number(test_str: str, expected: str):
    from src.lib.cleaners import strip_disc_number

    assert strip_disc_number(test_str) == expected


strip_partno_tests = [
    ("part 1", ""),
    ("pt 08", ""),
    ("pt. 42", ""),
    ("Part 1", ""),
    ("Part 06", ""),
    ("Part 009", ""),
    ("pt1", ""),
    ("PT 2", ""),
    ("(Part 4)", ""),
    (" - part 5", ""),
    (
        "The Last Guardian (Part 01) - Track07.mp3",
        "The Last Guardian - Track07.mp3",
    ),
    (
        "The Last Guardian - Part 01 - Track07.mp3",
        "The Last Guardian - Track07.mp3",
    ),
    ("The Last Guardian (Part 01)", "The Last Guardian"),
    ("The Last Guardian - Part 01", "The Last Guardian"),
    ("The Last Guardian, PT.01", "The Last Guardian"),
    ("The Last Guardian, pt 1", "The Last Guardian"),
    ("TouchofFrostPart1MythosAcademy", "TouchofFrostMythosAcademy"),
    ("TouchofFrostPart 01.mp3", "TouchofFrost.mp3"),
    ("Midnight Frost: Part 1", "Midnight Frost"),
]


@pytest.mark.parametrize(
    "test_str, expected", [*strip_partno_tests, ("TouchofFrostPart", "TouchofFrost")]
)
def test_strip_part_number(test_str: str, expected: str):
    from src.lib.cleaners import strip_part_number

    assert strip_part_number(test_str) == expected


@pytest.mark.parametrize(
    "test_str, expected",
    [
        ("That's to runnin' scared", "That's to runnin' scared"),
        ("That‘s to runnin’ scared", "That's to runnin' scared"),
        ("That’s to runnin’ scared", "That's to runnin' scared"),
        ('"Hello," she said.', '"Hello," she said.'),
        ("‘Hello,’ she said.", "'Hello,' she said."),
        ("’Hello,’ she said.", "'Hello,' she said."),
        ("‚Hello,‘ she said.", "'Hello,' she said."),
        ("‛Hello,‛ she said.", "'Hello,' she said."),
        ("′Hello,′ she said.", "'Hello,' she said."),
        ("‘Hello,’ she said.", "'Hello,' she said."),
        ("“Hello,” she said.", '"Hello," she said.'),
        ("”Hello,” she said.", '"Hello," she said.'),
        ("„Hello,“ she said.", '"Hello," she said.'),
        ("‟Hello,‟ she said.", '"Hello," she said.'),
        ("″Hello,″ she said.", '"Hello," she said.'),
        ("″Hello,″ she said.", '"Hello," she said.'),
    ],
)
def test_fix_smart_quotes(test_str: str, expected: str):
    from src.lib.cleaners import fix_smart_quotes

    assert fix_smart_quotes(test_str) == expected


@pytest.mark.parametrize(
    "test_str, expected",
    [
        ("hello%20world", "hello world"),
        ("hello%2Cworld", "hello,world"),
        ("hello%2Fworld", "hello/world"),
        ("hello%3Aworld", "hello:world"),
        ("hello%40world", "hello@world"),
        ("hello%3Dworld", "hello=world"),
        ("hello%26world", "hello&world"),
        ("hello%3Fworld", "hello?world"),
        ("hello&amp;world", "hello&world"),
        ("hello&quot;world", 'hello"world'),
        ("h&quot;&quot;w&quot;", 'h""w"'),
        ("hello&apos;world", "hello'world"),
        ("hello&lt;world", "hello<world"),
        ("hello&gt;world", "hello>world"),
        ("hello&nbsp;world", "hello world"),
        ("hello&mdash;world", "hello—world"),
        ("hello&ndash;world", "hello–world"),
        ("hello&copy;world", "hello©world"),
    ],
)
def test_un_urlencode(test_str: str, expected: str):
    from src.lib.cleaners import un_urlencode

    assert un_urlencode(test_str) == expected


@pytest.mark.parametrize(
    "test_str, expected",
    [
        ("<p>hello world</p>", "hello world"),
        ("<p>hello world", "hello world"),
        ("hello world</p>", "hello world"),
        ("<p>hello world", "hello world"),
        (
            "hello, <br />what a <b>wonderful</b> <span>world</span>",
            "hello, what a wonderful world",
        ),
    ],
)
def test_strip_html_tags(test_str: str, expected: str):
    from src.lib.cleaners import strip_html_tags

    assert strip_html_tags(test_str) == expected


@pytest.mark.parametrize(
    "test_files, expected",
    [
        (
            ROTK_ROMANS,
            ROTK_NO_ROMANS,
        ),
        (
            PART_ROMANS,
            PART_NO_ROMANS,
        ),
    ],
)
def test_strip_roman_numerals_from_list(
    test_files: list[str], expected: list[str], tmp_path: Path
):

    from src.lib.parsers import romans

    d = testutils.make_tmp_files(tmp_path, test_files)

    assert romans.strip_from_list([f.name for f in isorted(d.rglob("*"))]) == expected


@pytest.mark.parametrize(
    "test_case, expected",
    [
        ("A", "A"),
        ("B", "B"),
        ("8", "8"),
        ("I", ""),
        ("II", ""),
        ("III", ""),
        ("IV", ""),
        ("V", ""),
        ("VI", ""),
        ("VII", ""),
        ("VIII", ""),
        ("IX", ""),
        ("X", ""),
        ("XI", ""),
        ("XII", ""),
        ("XIII", ""),
        ("Roman_Numeral_Book_I - Part_0", "Roman_Numeral_Book_ - Part_0"),
        ("Roman_Numeral_Book_II - Part_1", "Roman_Numeral_Book_ - Part_1"),
        ("Roman_Numeral_Book_III - Part_2", "Roman_Numeral_Book_ - Part_2"),
        ("Roman_Numeral_Book_IV - Part_3", "Roman_Numeral_Book_ - Part_3"),
        ("Star Wars Episode IV: A New Hope", "Star Wars Episode : A New Hope"),
        (
            "Star Wars Episode V: The Empire Strikes Back",
            "Star Wars Episode : The Empire Strikes Back",
        ),
        (
            "Star Wars Episode VI: Return of the Jedi",
            "Star Wars Episode : Return of the Jedi",
        ),
        (
            "Star Wars EpisodeVII: The Force Awakens",
            "Star Wars Episode: The Force Awakens",
        ),
        (
            "Star Wars EpisodeVIII: The Last Jedi",
            "Star Wars Episode: The Last Jedi",
        ),
        (
            "Star Wars Episodeix: The Rise of Skywalker",
            "Star Wars Episodeix: The Rise of Skywalker",
        ),
        ("Star.Trek.III.The.Search.for.Spock", "Star.Trek..The.Search.for.Spock"),
    ],
)
def test_romans_strip(test_case, expected):

    assert romans.strip(test_case) == expected
