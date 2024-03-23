from pathlib import Path

import pytest

from src.lib.audiobook import Audiobook
from src.lib.ffmpeg_utils import get_bitrate_py, is_variable_bitrate
from src.lib.formatters import human_bitrate
from src.lib.id3_utils import extract_id3_tag_py, write_id3_tags_eyed3
from src.lib.parsers import extract_path_info
from src.lib.typing import BadFileError
from src.tests.helpers.pytest_utils import testutils


def test_extract_path_info(benedict_society__mp3):

    assert (
        extract_path_info(benedict_society__mp3).fs_title
        == "The Mysterious Benedict Society"
    )


def test_eyed3_load_fails_for_non_audio_file(not_an_audio_file: Audiobook):

    with pytest.raises(BadFileError):
        write_id3_tags_eyed3(not_an_audio_file.sample_audio1, {})


def test_id3_extract_fails_for_corrupt_file(corrupt_audiobook: Audiobook):

    with pytest.raises(BadFileError):
        extract_id3_tag_py(corrupt_audiobook.sample_audio1, "title", throw=True)


def test_parse_id3_narrator(blank_audiobook: Audiobook):

    test_str = "Mysterious Benedict Society#1    Read by Del Roy                           Unabridged  13 hrs 17 min           Listening Library/Random House Audio"

    write_id3_tags_eyed3(blank_audiobook.sample_audio1, {"comment": test_str})
    assert extract_id3_tag_py(blank_audiobook.sample_audio1, "comment") == test_str

    book = Audiobook(blank_audiobook.sample_audio1).extract_metadata()
    assert book.id3_comment == test_str
    assert book.narrator == "Del Roy"


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

    from src.lib.parsers import get_roman_numerals_dict

    assert get_roman_numerals_dict(input) == expected


rotk_romans = [
    "1_ Book V - Chapter 01 - Minas Tirith.mp3",
    "1_ Book V - Chapter 02 - The Passing of the Grey Company.mp3",
    "1_ Book V - Chapter 03 - The Muster of Rohan.mp3",
    "1_ Book V - Chapter 04 - The Siege of Gondor.mp3",
    "1_ Book V - Chapter 05 - The Ride of the Rohirrim.mp3",
    "1_ Book V - Chapter 06 - The Battle of Pelennor Fields.mp3",
    "1_ Book V - Chapter 07 - The Pyre of Denethor.mp3",
    "1_ Book V - Chapter 08 - The Houses of Healing.mp3",
    "1_ Book V - Chapter 09 - The Last Debate.mp3",
    "1_ Book V - Chapter 10 - The Black Gate Opens.mp3",
    "2_ Book VI - Chapter 01 - The Tower of Cirith Ungol.mp3",
    "2_ Book VI - Chapter 02 - The Land of Shadow.mp3",
    "2_ Book VI - Chapter 03 - Mount Doom.mp3",
    "2_ Book VI - Chapter 04 - The Field of Cormallen.mp3",
    "2_ Book VI - Chapter 05 - The Steward & The King.mp3",
    "2_ Book VI - Chapter 06 - Many Partings.mp3",
    "2_ Book VI - Chapter 07 - Homeward Bound.mp3",
    "2_ Book VI - Chapter 08 - The Scouring of the Shire.mp3",
    "2_ Book VI - Chapter 09 - The Grey Havens.mp3",
    "3_ Appendix A - Annals of the Kings and Rulers.mp3",
    "3_ Appendix B - The House of Eorl.mp3",
    "3_ Appendix C - Durin's Folk.mp3",
]

rotk_no_romans = [
    "1_ Book  - Chapter 01 - Minas Tirith.mp3",
    "1_ Book  - Chapter 02 - The Passing of the Grey Company.mp3",
    "1_ Book  - Chapter 03 - The Muster of Rohan.mp3",
    "1_ Book  - Chapter 04 - The Siege of Gondor.mp3",
    "1_ Book  - Chapter 05 - The Ride of the Rohirrim.mp3",
    "1_ Book  - Chapter 06 - The Battle of Pelennor Fields.mp3",
    "1_ Book  - Chapter 07 - The Pyre of Denethor.mp3",
    "1_ Book  - Chapter 08 - The Houses of Healing.mp3",
    "1_ Book  - Chapter 09 - The Last Debate.mp3",
    "1_ Book  - Chapter 10 - The Black Gate Opens.mp3",
    "2_ Book  - Chapter 01 - The Tower of Cirith Ungol.mp3",
    "2_ Book  - Chapter 02 - The Land of Shadow.mp3",
    "2_ Book  - Chapter 03 - Mount Doom.mp3",
    "2_ Book  - Chapter 04 - The Field of Cormallen.mp3",
    "2_ Book  - Chapter 05 - The Steward & The King.mp3",
    "2_ Book  - Chapter 06 - Many Partings.mp3",
    "2_ Book  - Chapter 07 - Homeward Bound.mp3",
    "2_ Book  - Chapter 08 - The Scouring of the Shire.mp3",
    "2_ Book  - Chapter 09 - The Grey Havens.mp3",
    "3_ Appendix A - Annals of the Kings and Rulers.mp3",
    "3_ Appendix B - The House of Eorl.mp3",
    "3_ Appendix C - Durin's Folk.mp3",
]

part_romans = [
    "Part I - Prologue.mp3",
    "Part II - A Long-expected Party.mp3",
    "Part III - Shadow of the Past.mp3",
    "Part IV - Riddles in the Dark.mp3",
    "Part V - The Army of Storms.mp3",
    "Part VI - Epilogue.mp3",
]

part_no_romans = [
    "Part  - Prologue.mp3",
    "Part  - A Long-expected Party.mp3",
    "Part  - Shadow of the Past.mp3",
    "Part  - Riddles in the Dark.mp3",
    "Part  - The Army of Storms.mp3",
    "Part  - Epilogue.mp3",
]


@pytest.mark.parametrize(
    "test_files, expected",
    [
        (
            rotk_romans,
            rotk_no_romans,
        ),
        (
            part_romans,
            part_no_romans,
        ),
    ],
)
def test_strip_roman_numerals(
    test_files: list[str], expected: list[str], tmp_path: Path
):

    from src.lib.parsers import strip_roman_numerals

    d = testutils.make_tmp_files(tmp_path, test_files)

    assert [f.name for f in strip_roman_numerals(d)] == expected


@pytest.mark.parametrize(
    "test_files, expected",
    [
        (
            rotk_romans,
            False,
        ),
        (
            part_romans,
            True,
        ),
    ],
)
def test_roman_numerals_affect_file_order(
    test_files: list[str], expected, tmp_path: Path
):

    from src.lib.parsers import roman_numerals_affect_file_order

    d = testutils.make_tmp_files(tmp_path, test_files)

    assert roman_numerals_affect_file_order(d) == expected
