import pytest

from src.lib.audiobook import Audiobook
from src.lib.id3_utils import extract_id3_tag_py, write_id3_tags_eyed3
from src.lib.parsers import extract_path_info
from src.lib.typing import BadFileError


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