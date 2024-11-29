import re
import shutil

import pytest
from pytest import CaptureFixture

from src.auto_m4b import app
from src.lib.audiobook import Audiobook
from src.lib.config import OnComplete
from src.lib.id3_utils import extract_cover_art
from src.lib.inbox_state import InboxState
from src.lib.misc import re_group
from src.tests.helpers.pytest_utils import testutils


@pytest.mark.slow
class test_happy_paths:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, reset_all):
        yield

    @pytest.mark.parametrize(
        "indirect_fixture, capfd",
        [
            ("tower_treasure__flat_mp3", "capfd"),
            ("house_on_the_cliff__flat_mp3", "capfd"),
        ],
        indirect=["indirect_fixture", "capfd"],
    )
    def test_basic_book_mp3(self, indirect_fixture: Audiobook, capfd: CaptureFixture[str]):
        book = indirect_fixture
        quality = f"{book.bitrate_friendly} @ {book.samplerate_friendly}".replace("kb/s", "kbps")
        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            book,
            loops=[testutils.check_output(found_books_eq=1, converted_eq=1)],
        )
        assert testutils.assert_converted_book_and_collateral_exist(book, quality)

    def test_convert_multiple_books_mp3(
        self,
        all_hardy_boys: list[Audiobook],
        capfd: CaptureFixture[str],
    ):
        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            *all_hardy_boys[0:4],
            loops=[testutils.check_output(found_books_eq=4, converted_eq=4)],
        )

    def test_backup_book_mp3(self, tiny__flat_mp3: Audiobook, capfd: CaptureFixture[str], enable_backups):
        app(max_loops=1)
        out = testutils.get_stdout(capfd)
        assert "Making a backup copy" in out
        assert testutils.assert_processed_output(
            out,
            tiny__flat_mp3,
            loops=[testutils.check_output(found_books_eq=1, converted_eq=1)],
        )
        assert tiny__flat_mp3.converted_dir.exists()

    @pytest.mark.parametrize(
        "starting_loop, match_filter",
        [(0, "tiny"), (0, "--none--"), (2, "tiny"), (2, "--none--")],
    )
    @pytest.mark.order()
    def test_friendly_message_when_inbox_is_empty(
        self,
        requires_empty_inbox,
        tiny__flat_mp3: Audiobook,
        starting_loop,
        match_filter,
        capfd: CaptureFixture[str],
    ):

        InboxState().loop_counter = starting_loop
        testutils.set_match_filter(match_filter)
        testutils.force_inbox_hash_change(age=-2)
        app(max_loops=starting_loop + 1)
        out = testutils.get_stdout(capfd)
        converted = [tiny__flat_mp3] if match_filter == "tiny" else []
        check = (
            [testutils.check_output(found_books_eq=1)]
            if match_filter == "tiny"
            else [testutils.check_output(empty=True)]
        )
        assert testutils.assert_processed_output(out, *converted, loops=check)

        watching_count = out.count("Watching for books in")
        checking_count = out.count("Checking for books in")

        if starting_loop <= 1:
            assert watching_count == 1
        elif match_filter == "tiny":
            assert checking_count == 1
        else:
            assert watching_count == 1
            assert checking_count == 0

    def test_match_filter_multiple_mp3s(
        self,
        tower_treasure__flat_mp3: Audiobook,
        house_on_the_cliff__flat_mp3: Audiobook,
        capfd: CaptureFixture[str],
        enable_archiving,
    ):

        testutils.set_match_filter("^(tower|house)")
        inbox = InboxState()
        inbox_dirs = inbox.book_dirs
        inbox.scan()
        matched_books = len(inbox.matched_books)
        filtered_books = len(inbox.filtered_books)
        inbox.destroy()  # type: ignore
        app(max_loops=1)
        assert tower_treasure__flat_mp3.converted_dir.exists()
        assert house_on_the_cliff__flat_mp3.converted_dir.exists()
        out = testutils.get_stdout(capfd)
        assert testutils.assert_processed_output(
            out,
            tower_treasure__flat_mp3,
            house_on_the_cliff__flat_mp3,
            loops=[testutils.check_output(found_books_eq=2, converted_eq=2)],
        )
        found = int(re_group(re.search(r"Found (\d+) book", out), default=1))
        ignoring = int(re_group(re.search(r"\(ignoring (\d+)\)", out), default=1))
        converted = len(testutils.get_all_processed_books(out))
        assert found == matched_books
        assert ignoring == filtered_books
        assert found + ignoring == len(inbox_dirs) == len(find_book_dirs_in_inbox()) + converted
        # With archiving enabled, the inbox should have 2 fewer books.
        # If archiving is disabled, the inbox should have the same number of books.

    def test_flatten_multidisc_mp3(
        self,
        old_mill__multidisc_mp3: Audiobook,
        capfd: CaptureFixture[str],
    ):

        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            old_mill__multidisc_mp3,
            loops=[testutils.check_output(found_books_eq=1, converted_eq=1)],
        )
        assert old_mill__multidisc_mp3.converted_dir.exists()

    @pytest.mark.parametrize("backups_enabled", [False, True])
    def test_convert_series_mp3(
        self,
        backups_enabled,
        Chanur_Series: list[Audiobook],
        capfd: CaptureFixture[str],
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

    def test_book_series_output_to_series_dir(
        self,
        Chanur_Series: list[Audiobook],
        enable_archiving,
    ):

        app(max_loops=1)
        series_parent = Chanur_Series[0]
        assert series_parent.converted_dir.exists()
        for book in Chanur_Series[1:]:
            assert book.converted_dir.is_relative_to(series_parent.converted_dir)
            assert book.converted_dir.exists()
        assert not series_parent.inbox_dir.exists()
        assert series_parent.archive_dir.exists()

    def test_book_series_handles_series_collateral(
        self,
        Chanur_Series: list[Audiobook],
        enable_archiving,
    ):

        app(max_loops=1)
        series_parent = Chanur_Series[0]
        assert series_parent.converted_dir.exists()
        for pic in [
            "414fL6J.png",
            "i367gyc.png",
            "KiaprKx.png",
            "mhHDEdX.png",
            "xEZNYAN.png",
        ]:
            assert (series_parent.converted_dir / pic).exists()
        assert not series_parent.inbox_dir.exists()
        assert series_parent.archive_dir.exists()

    @pytest.mark.parametrize(
        "partial_flatten_backup_dirs",
        [
            ([]),
            (["J.R.R. Tolkien - The Hobbit - Disc 1"]),
            (
                [
                    "J.R.R. Tolkien - The Hobbit - Disc 1",
                    "J.R.R. Tolkien - The Hobbit - Disc 2",
                ]
            ),
            (
                [
                    "J.R.R. Tolkien - The Hobbit - Disc 1",
                    "J.R.R. Tolkien - The Hobbit - Disc 2",
                    "J.R.R. Tolkien - The Hobbit - Disc 3",
                    "J.R.R. Tolkien - The Hobbit - Disc 4",
                    "J.R.R. Tolkien - The Hobbit - Disc 5",
                ]
            ),
        ],
    )
    def test_backups_are_ok_when_flattening_multidisc_books(
        self,
        partial_flatten_backup_dirs: list[str],
        the_hobbit__multidisc_mp3: Audiobook,
        enable_backups,
        capfd: CaptureFixture[str],
    ):

        # make a backup of the_hobbit__multidisc_mp3 before running the app
        shutil.rmtree(the_hobbit__multidisc_mp3.backup_dir, ignore_errors=True)
        the_hobbit__multidisc_mp3.backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            the_hobbit__multidisc_mp3.inbox_dir,
            the_hobbit__multidisc_mp3.backup_dir,
            dirs_exist_ok=True,
        )

        if partial_flatten_backup_dirs:
            for d in partial_flatten_backup_dirs:
                for f in (the_hobbit__multidisc_mp3.backup_dir / d).iterdir():
                    f.rename(the_hobbit__multidisc_mp3.backup_dir / f.name)
                shutil.rmtree(the_hobbit__multidisc_mp3.backup_dir / d)

        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            the_hobbit__multidisc_mp3,
            loops=[testutils.check_output(found_books_eq=1, converted_eq=1)],
        )
        assert the_hobbit__multidisc_mp3.converted_dir.exists()

    @pytest.mark.parametrize(
        "on_complete, backup",
        [
            ("test_do_nothing", False),
            ("archive", False),
            ("delete", False),
            ("delete", True),
        ],
    )
    def test_original_handled_on_complete(
        self, on_complete: OnComplete, backup: bool, tower_treasure__flat_mp3: Audiobook
    ):
        shutil.rmtree(tower_treasure__flat_mp3.archive_dir, ignore_errors=True)
        with testutils.set_on_complete(on_complete):
            with testutils.set_backups(backup):
                app(max_loops=1)

                assert tower_treasure__flat_mp3.converted_dir.exists()
                match on_complete:
                    case "test_do_nothing":
                        assert tower_treasure__flat_mp3.inbox_dir.exists()
                        assert not tower_treasure__flat_mp3.archive_dir.exists()
                    case "archive":
                        assert not tower_treasure__flat_mp3.inbox_dir.exists()
                        assert tower_treasure__flat_mp3.archive_dir.exists()
                    case "delete":
                        if backup:
                            assert not tower_treasure__flat_mp3.inbox_dir.exists()
                        else:
                            assert tower_treasure__flat_mp3.inbox_dir.exists()
                        assert not tower_treasure__flat_mp3.archive_dir.exists()

    @pytest.mark.parametrize(
        "indirect_fixture, capfd",
        [
            ("basic_with_cover__single_mp3", "capfd"),
            ("basic_with_cover__single_m4b", "capfd"),
            ("basic_no_cover__single_mp3", "capfd"),
            ("basic_no_cover__single_m4b", "capfd"),
        ],
        indirect=["indirect_fixture", "capfd"],
    )
    def test_cover_art_is_tagged(self, indirect_fixture: Audiobook, capfd: CaptureFixture[str]):
        book = indirect_fixture
        # testutils.set_match_filter(r"^basic_\w+_cover")
        app(max_loops=1)
        if book.orig_file_type == "m4b":
            checks = {
                "found_books_eq": 1,
                "already_converted_eq": 1,
            }
        else:
            checks = {
                "found_books_eq": 1,
                "converted_eq": 1,
            }
        assert testutils.assert_processed_output(
            capfd,
            book,
            loops=[testutils.check_output(**checks)],  # type: ignore
        )

        # extract cover art and check that it is > 10kb
        img = extract_cover_art(
            book.converted_file,
            save_to_file=True,
            filename="test_cover.jpg",
        )
        assert img.exists()
        assert img.stat().st_size > 10000
