import shutil

import pytest

from src.auto_m4b import app
from src.lib.audiobook import Audiobook
from src.lib.inbox_state import InboxState
from src.lib.strings import en
from src.tests.helpers.pytest_dumps import FIXTURES_ROOT, TEST_DIRS
from src.tests.helpers.pytest_utils import testutils


class test_series:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, reset_all):
        yield

    def test_multi_series_container_single_m4a_and_flat_mp3s(
        self,
        nathan_lowell__nested_series_m4a,
        capfd: pytest.CaptureFixture[str],
    ):
        testutils.set_match_filter("^(Nathan Lowell)")
        books = InboxState().get_like("^(Nathan Lowell)")
        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            *[b.path for b in books if not b.tree.has_structure("series_parent")],
            loops=[testutils.check_output(converted_eq=22, already_converted_eq=0)],
        )

    @pytest.mark.parametrize("backups_enabled", [False, True])
    def test_convert_series_backups_on_off(
        self,
        backups_enabled,
        Chanur_Series: list[Audiobook],
        capfd: pytest.CaptureFixture[str],
    ):
        with testutils.set_backups(backups_enabled):
            qualities = [
                f"{b.bitrate_friendly} @ {b.samplerate_friendly}".replace("kb/s", "kbps") for b in Chanur_Series
            ]
            app(max_loops=1)
            out = testutils.get_stdout(capfd)
            series_parent = Chanur_Series[0]
            child_books = Chanur_Series[1:]
            assert len(child_books) == 5
            for book, quality in zip(child_books, qualities):
                testutils.assert_converted_book_and_collateral_exist(book, quality)
            assert testutils.assert_processed_output(
                out,
                *child_books,
                loops=[testutils.check_output(found_books_eq=5, converted_eq=5)],
            )
            assert out.count("Book Series •••••")
            assert series_parent.converted_dir.exists()
            for book in child_books:
                assert book.converted_dir.exists()

    def test_book_series_output_and_collateral(
        self,
        Chanur_Series: list[Audiobook],
        enable_archiving,
    ):

        app(max_loops=1)
        series_parent = Chanur_Series[0]
        assert series_parent.converted_dir.exists()
        # Ensure series is output to series directory
        for book in Chanur_Series[1:]:
            assert book.converted_dir.is_relative_to(series_parent.converted_dir)
            assert book.converted_dir.exists()
            assert testutils.assert_converted_book_and_collateral_exist(book, "128 kbps @ 22 kHz")

        # Ensure collateral in series dir is copied to converted dir
        assert not series_parent.inbox_dir.exists()
        assert series_parent.archive_dir.exists()
        for pic in [
            "414fL6J.png",
            "i367gyc.png",
            "KiaprKx.png",
            "mhHDEdX.png",
            "xEZNYAN.png",
        ]:
            assert (series_parent.converted_dir / pic).exists()

    def test_flattens_nested_books_and_series_in_container(
        self,
        secret_project_series__nested_flat_mixed: Audiobook,
        capfd: pytest.CaptureFixture[str],
    ):

        app(max_loops=1)
        stdout = testutils.get_stdout(capfd)
        assert stdout.count(en.BOOK_NEEDS_FLATTENING) == 2

    def test_series_standalone_m4b_moves_to_series_converted_dir(
        self,
        Chanur_Series: list[Audiobook],
        capfd: pytest.CaptureFixture[str],
    ):
        """A standalone m4b placed directly under a series parent folder (alongside
        other mp3 books) should be moved to converted/<series>/<book_stem>/<book>.m4b —
        not to the flat converted/<book_stem>/ path.  Regression for the crash where
        process_already_m4b used cfg.converted_dir / item.path.stem (dropping the
        series prefix)."""
        from src.lib.config import cfg

        series_parent = Chanur_Series[0]
        book_stem = "06 - Chanur's Endgame"
        book_filename = f"{book_stem}.m4b"

        src_fixture = FIXTURES_ROOT / "basic_with_cover__standalone_m4b.m4b"
        dst = series_parent.inbox_dir / book_filename

        shutil.copy(src_fixture, dst)
        dst.touch()  # refresh mtime

        standalone_book = Audiobook(dst)
        _ = standalone_book.orig_file_type  # pre-compute before app moves the file

        app(max_loops=1)

        assert not cfg.FATAL_FILE.exists(), "App crashed fatally"

        expected_converted_dir = TEST_DIRS.converted / series_parent.path.name / book_stem
        expected_converted_file = expected_converted_dir / book_filename
        assert expected_converted_dir.exists(), f"Series converted dir missing: {expected_converted_dir}"
        assert expected_converted_file.is_file(), f"Converted file missing: {expected_converted_file}"
