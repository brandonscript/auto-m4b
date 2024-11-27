import pytest

from src.lib.audiobook import Audiobook


class test_audiobook_class:

    def test_orig_file_type(self, house_on_the_cliff__flat_mp3: Audiobook):
        assert house_on_the_cliff__flat_mp3.orig_file_type == "mp3"

    @pytest.mark.parametrize(
        "indirect_fixture, expected_num_files",
        [
            ("house_on_the_cliff__flat_mp3", 2),
            ("corrupt_audiobook", 1),
            ("nathan_lowell__nested_series_m4a", 28),
        ],
        indirect=["indirect_fixture"],
    )
    def test_num_files(self, indirect_fixture: Audiobook, expected_num_files: int):
        assert indirect_fixture.num_files("inbox") == expected_num_files
