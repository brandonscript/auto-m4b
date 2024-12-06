import pytest

from src.auto_m4b import app
from src.tests.helpers.pytest_dumps import TEST_DIRS
from src.tests.helpers.pytest_utils import testutils


class test_standalone_and_single:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, reset_all):
        yield

    def test_standalone_m4b_is_directly_moved(
        self,
        basic_with_cover__standalone_m4b,
        capfd: pytest.CaptureFixture[str],
    ):
        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            basic_with_cover__standalone_m4b,
            loops=[testutils.check_output(found_books_eq=1, already_converted_eq=1)],
        )

    def test_single_m4b_is_directly_moved(
        self,
        basic_with_cover__single_m4b,
        capfd: pytest.CaptureFixture[str],
    ):
        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            basic_with_cover__single_m4b,
            loops=[testutils.check_output(found_books_eq=1, already_converted_eq=1)],
        )

    def test_standalone_mp3_is_converted_and_put_in_folder(
        self,
        basic_with_cover__standalone_mp3,
        capfd: pytest.CaptureFixture[str],
    ):
        app(max_loops=1)
        out = testutils.get_stdout(capfd)
        inbox_dir = TEST_DIRS.inbox / basic_with_cover__standalone_mp3.path.stem
        assert testutils.assert_processed_output(
            out,
            inbox_dir,
            loops=[testutils.check_output(found_books_eq=1, converted_eq=1)],
        )

    def test_standalone_mp3_finds_adjacent_files(
        self,
        basic_no_cover__standalone_mp3,
        capfd: pytest.CaptureFixture[str],
    ):
        app(max_loops=1)
        out = testutils.get_stdout(capfd)
        inbox_dir = TEST_DIRS.inbox / basic_no_cover__standalone_mp3.path.stem
        converted_dir = TEST_DIRS.converted / basic_no_cover__standalone_mp3.path.stem
        assert testutils.assert_processed_output(
            out,
            inbox_dir,
            loops=[testutils.check_output(found_books_eq=1, converted_eq=1)],
        )
        assert (converted_dir / basic_no_cover__standalone_mp3.path.stem).with_suffix(".jpg").exists()
        assert not (converted_dir / "LeviathanWakes.jpg").exists()
