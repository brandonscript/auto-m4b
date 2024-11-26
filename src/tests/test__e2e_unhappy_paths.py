import asyncio
import concurrent
import concurrent.futures
import shutil
import time
from copy import deepcopy
from unittest.mock import patch

import pytest
from pytest import CaptureFixture

from src.auto_m4b import app
from src.lib.audiobook import Audiobook
from src.lib.fs_utils import rename_dir
from src.lib.inbox_state import InboxState
from src.lib.strings import en
from src.tests.conftest import TEST_DIRS
from src.tests.helpers.pytest_fixtures import load_test_fixtures
from src.tests.helpers.pytest_utils import testutils

ORDER = 1


@pytest.mark.slow
class test_unhappy_paths:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, reset_all: None):
        yield

    @pytest.mark.order(ORDER)
    def test_nonstandard_bitrate_mp3s(
        self,
        bitrate_nonstandard__mp3: Audiobook,
        the_crusades_through_arab_eyes__flat_mp3: Audiobook,
        capfd: CaptureFixture[str],
    ):

        testutils.set_match_filter("^(bitrate_nonstandard|the_crusades)")
        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            bitrate_nonstandard__mp3,
            the_crusades_through_arab_eyes__flat_mp3,
            loops=[testutils.check_output(found_books_eq=2, converted_eq=2)],
        )
        assert bitrate_nonstandard__mp3.converted_dir.exists()
        assert the_crusades_through_arab_eyes__flat_mp3.converted_dir.exists()

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_failed_books_only_print_once(self, roman_numeral__mp3: Audiobook, capfd: CaptureFixture[str]):
        app(max_loops=3)
        # assert the message only appears once
        out = testutils.get_stdout(capfd)
        assert out.count(en.ROMAN_ERR) == 1
        assert testutils.assert_processed_output(out, loops=[testutils.check_output(found_books_eq=1, converted_eq=0)])

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_no_matches_found(
        self,
        tower_treasure__flat_mp3: Audiobook,
        capfd: CaptureFixture[str],
    ):

        testutils.set_match_filter("test-do-not-match")
        app(max_loops=4)
        assert testutils.assert_processed_output(
            capfd, loops=[testutils.check_output(found_books_eq=0, converted_eq=0)]
        )

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_skip_known_failed_books(
        self,
        roman_numeral__mp3: Audiobook,
        tower_treasure__flat_mp3: Audiobook,
        capfd: CaptureFixture[str],
    ):
        inbox = InboxState()

        match_filter = "^(Roman|tower)"

        testutils.set_match_filter(match_filter)
        app(max_loops=2)
        out = testutils.get_stdout(capfd)

        assert testutils.assert_processed_output(
            out,
            tower_treasure__flat_mp3,
            loops=[
                testutils.check_output(found_books_eq=2, converted_eq=1),
            ],
        )
        assert out.count(en.ROMAN_ERR) == 1

        testutils.fail_book(roman_numeral__mp3, from_now=30)
        inbox.reset_inbox(match_filter)
        time.sleep(1)
        testutils.force_inbox_hash_change(age=-2)
        app(max_loops=4)
        out = testutils.get_stdout(capfd)

        assert testutils.assert_processed_output(
            out,
            tower_treasure__flat_mp3,
            loops=[testutils.check_output(found_books_eq=2, converted_eq=1, skipped_failed_eq=1)],
        )
        assert out.count(en.ROMAN_ERR) == 0

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_ignore_failed_if_unchanged(
        self,
        roman_numeral__mp3: Audiobook,
        tower_treasure__flat_mp3: Audiobook,
        house_on_the_cliff__flat_mp3: Audiobook,
        capfd: CaptureFixture[str],
        caplog,
    ):

        inbox = InboxState()
        with testutils.set_wait_time(0.5):

            testutils.set_match_filter("^(Roman|tower)")
            app(max_loops=1)
            out = testutils.get_stdout(capfd)
            assert testutils.assert_processed_output(
                out,
                tower_treasure__flat_mp3,
                loops=[testutils.check_output(found_books_eq=2, converted_eq=1)],
            )
            assert out.count(en.ROMAN_ERR) == 1
            testutils.fail_book("Roman Numeral Book", from_now=30)
            inbox.reset_inbox("^(Roman|tower|house)")
            time.sleep(1)
            testutils.force_inbox_hash_change(age=-2)
            app(max_loops=3)
            out = testutils.get_stdout(capfd)
            assert testutils.assert_processed_output(
                out,
                tower_treasure__flat_mp3,
                house_on_the_cliff__flat_mp3,
                loops=[testutils.check_output(found_books_eq=3, converted_eq=2, skipped_failed_eq=1)],
            )

    ORDER += 1

    @pytest.mark.parametrize(
        "archive",
        [True, False],
    )
    @pytest.mark.order(ORDER)
    @pytest.mark.asyncio
    async def test_skips_failed_when_new_books_added(
        self,
        missing_chums__mixed_mp3: Audiobook,
        tower_treasure__flat_mp3: Audiobook,
        disable_multidisc,
        enable_debug,
        archive,
        capfd: CaptureFixture[str],
    ):

        from src.lib.config import cfg

        txr_name = "txr_treasure__flat_mp3"
        shutil.rmtree(cfg.inbox_dir / txr_name, ignore_errors=True)

        rename_dir(tower_treasure__flat_mp3.inbox_dir, txr_name)

        async def async_app():
            with testutils.set_wait_time(1):
                with testutils.set_sleep_time(0.5):
                    time.sleep(0)
                    testutils.print("Starting app...")
                    testutils.set_match_filter("^(missing|tower)")
                    app(max_loops=8, test=False)
                    testutils.print("Finished app")

        def renamer():
            time.sleep(2)
            testutils.rename_files(
                tower_treasure__flat_mp3,
                append="-new1",
                rstrip=r"-new\d",
                wait_time=0.25,
            )
            time.sleep(2)
            rename_dir(cfg.inbox_dir / txr_name, tower_treasure__flat_mp3.basename)
            testutils.rename_files(
                tower_treasure__flat_mp3,
                append="-new2",
                rstrip=r"-new\d",
                wait_time=0.25,
            )

        with testutils.set_on_complete("archive" if archive else "test_do_nothing"):
            app_task = asyncio.create_task(async_app())

            with concurrent.futures.ThreadPoolExecutor() as executor:
                await asyncio.get_running_loop().run_in_executor(executor, renamer)

            await app_task

            out = testutils.get_stdout(capfd)

            assert out.count(en.MULTI_ERR) == 1
            assert out.count(en.INBOX_RECENTLY_MODIFIED) == 1
            assert out.count(en.BOOK_RECENTLY_MODIFIED) == 0
            assert out.count(en.DEBUG_WAITING_FOR_INBOX) > 0

            assert testutils.assert_processed_output(
                out,
                tower_treasure__flat_mp3,
                loops=[
                    testutils.check_output(found_books_eq=1, converted_eq=0),
                    testutils.check_output(found_books_eq=2, converted_eq=1, skipped_failed_eq=1),
                ],
            )

        shutil.rmtree(cfg.inbox_dir / txr_name, ignore_errors=True)

    ORDER += 1

    @pytest.mark.order(ORDER)
    @pytest.mark.asyncio
    async def test_retries_failed_books_when_changed(
        self,
        old_mill__multidisc_mp3: Audiobook,
        capfd: CaptureFixture[str],
        disable_multidisc,
    ):
        inbox_dir = old_mill__multidisc_mp3.inbox_dir
        converted_dir = old_mill__multidisc_mp3.converted_dir
        shutil.rmtree(converted_dir, ignore_errors=True)

        async def async_app():
            with testutils.set_sleep_time(1):
                with testutils.set_wait_time(1, delay=0):
                    testutils.print("Starting app...")
                    app(max_loops=6)
                    testutils.print("Finished app")

        app_task = asyncio.create_task(async_app())

        with concurrent.futures.ThreadPoolExecutor() as executor:
            await asyncio.get_running_loop().run_in_executor(
                executor, testutils.flatten_book, old_mill__multidisc_mp3, 4
            )

        out = testutils.get_stdout(capfd)

        await app_task
        assert out.count(en.MULTI_ERR) == 1
        assert out.count(en.INBOX_RECENTLY_MODIFIED) == 1
        assert testutils.assert_processed_output(
            out,
            old_mill__multidisc_mp3,
            loops=[
                testutils.check_output(found_books_eq=1, converted_eq=0),
                testutils.check_output(
                    found_books_eq=1,
                    converted_eq=1,
                    skipped_failed_eq=0,
                    retried_books_eq=1,
                ),
            ],
        )
        shutil.rmtree(inbox_dir, ignore_errors=True)

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_header_only_prints_when_there_are_books_to_process(
        self, tiny__flat_mp3: Audiobook, capfd: CaptureFixture[str]
    ):
        testutils.set_match_filter("test-do-not-match")
        app(max_loops=10)

        out = testutils.get_stdout(capfd)
        assert testutils.assert_header_count(out, expected_eq=1)
        assert testutils.assert_no_duplicate_banners(out.splitlines())
        assert testutils.assert_processed_output(
            out,
            loops=[testutils.check_output(found_books_eq=0, converted_eq=0)],
        )

    ORDER += 1

    @pytest.mark.asyncio
    @pytest.mark.order(ORDER)
    async def test_waits_for_recent_inbox_changes(
        self,
        tower_treasure__flat_mp3: Audiobook,
        mock_inbox_being_copied_to,
        capfd: CaptureFixture[str],
    ):

        async def async_app():
            testutils.print("Starting app...")
            testutils.set_match_filter("tower")
            app(max_loops=1)
            testutils.print("Finished app")

        with testutils.set_wait_time(1.25):

            app_task = asyncio.create_task(async_app())

            with concurrent.futures.ThreadPoolExecutor() as executor:
                await asyncio.get_running_loop().run_in_executor(executor, mock_inbox_being_copied_to, 5, 1)

            await app_task

            out = testutils.get_stdout(capfd)

            assert testutils.assert_processed_output(
                out,
                tower_treasure__flat_mp3,
                loops=[testutils.check_output(found_books_eq=1, converted_eq=1)],
            )

            assert out.count(en.INBOX_RECENTLY_MODIFIED) == 1
            assert out.count(en.BOOK_RECENTLY_MODIFIED) == 0

    ORDER += 1

    @pytest.mark.asyncio
    @pytest.mark.order(ORDER)
    async def test_detects_books_added_while_converting(
        self,
        tower_treasure__flat_mp3: Audiobook,
        house_on_the_cliff__flat_mp3: Audiobook,
        enable_archiving,
        capfd: CaptureFixture[str],
    ):
        the_sunlit_man__flat_mp3 = Audiobook(TEST_DIRS.inbox / "the_sunlit_man__flat_mp3")
        tiny__flat_mp3 = Audiobook(TEST_DIRS.inbox / "tiny__flat_mp3")
        shutil.rmtree(the_sunlit_man__flat_mp3.inbox_dir, ignore_errors=True)
        shutil.rmtree(tiny__flat_mp3.inbox_dir, ignore_errors=True)

        match_filter = "^(tower|house|the_sunlit|tiny)"
        testutils.set_match_filter(match_filter)

        def add_book_to_inbox():
            time.sleep(5)
            testutils.print("Loading additional test fixtures...")
            load_test_fixtures("the_sunlit_man__flat_mp3", "tiny__flat_mp3", match_filter=match_filter)

        async def async_app():
            with testutils.set_wait_time(1):
                testutils.print("Starting app...")
                app(max_loops=2)
                testutils.print("Finished app")

        app_task = asyncio.create_task(async_app())

        with concurrent.futures.ThreadPoolExecutor() as executor:
            await asyncio.get_running_loop().run_in_executor(executor, add_book_to_inbox)

        await app_task

        out = testutils.get_stdout(capfd)
        assert testutils.assert_processed_output(
            out,
            tower_treasure__flat_mp3,
            house_on_the_cliff__flat_mp3,
            the_sunlit_man__flat_mp3,
            tiny__flat_mp3,
            loops=[
                testutils.check_output(found_books_eq=2, converted_eq=2),
                testutils.check_output(found_books_eq=2, converted_eq=2),
            ],
        )
        assert testutils.assert_header_count(out, expected_eq=2)

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_secret_project_series__nested_flat_mixed(
        self,
        secret_project_series__nested_flat_mixed: Audiobook,
        capfd: CaptureFixture[str],
    ):

        app(max_loops=1)
        stdout, _ = capfd.readouterr()
        assert en.MULTI_ERR in stdout

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_long_filename__mp3(self, conspiracy_theories__flat_mp3: Audiobook):
        inbox = InboxState()

        conspiracy_theories__flat_mp3_copy = deepcopy(conspiracy_theories__flat_mp3)
        (TEST_DIRS.converted / "auto-m4b.log").unlink(missing_ok=True)  # remove the log file to force a conversion
        testutils.set_match_filter("Conspiracies")
        app(max_loops=1)
        assert conspiracy_theories__flat_mp3.converted_dir.exists()
        # do the conversion again to test the log file
        inbox.destroy()  # type: ignore
        shutil.rmtree(conspiracy_theories__flat_mp3.converted_dir, ignore_errors=True)
        TEST_DIRS.inbox.touch()
        time.sleep(1)

        app(max_loops=2)
        assert conspiracy_theories__flat_mp3_copy.converted_dir.exists()

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_multi_disc_fails(
        self,
        old_mill__multidisc_mp3: Audiobook,
        disable_multidisc,
        capfd: CaptureFixture[str],
    ):

        shutil.rmtree(old_mill__multidisc_mp3.converted_dir, ignore_errors=True)
        time.sleep(2)
        app(max_loops=2)
        out = testutils.get_stdout(capfd)
        assert out.count(en.MULTI_ERR) == 1
        assert testutils.assert_processed_output(
            out,
            loops=[testutils.check_output(found_books_eq=1, converted_eq=0)],
        )

    ORDER += 1

    @pytest.mark.parametrize("add_extra_books", [False, True])
    @pytest.mark.order(ORDER)
    def test_failed_notify_doesnt_repeat_after_convert(
        self,
        requires_empty_inbox,
        tower_treasure__flat_mp3: Audiobook,
        missing_chums__mixed_mp3: Audiobook,
        old_mill__multidisc_mp3: Audiobook,
        tiny__flat_mp3: Audiobook,
        the_sunlit_man__flat_mp3: Audiobook,
        disable_multidisc,
        enable_archiving,
        add_extra_books,
        capfd: CaptureFixture[str],
    ):

        if not add_extra_books:
            shutil.rmtree(tiny__flat_mp3.inbox_dir, ignore_errors=True)
            shutil.rmtree(the_sunlit_man__flat_mp3.inbox_dir, ignore_errors=True)

        testutils.set_match_filter("^(tower|missing|old)")
        for d in [
            _
            for b in (
                tower_treasure__flat_mp3,
                missing_chums__mixed_mp3,
                old_mill__multidisc_mp3,
            )
            for _ in (b.backup_dir, b.converted_dir)
        ]:
            shutil.rmtree(d, ignore_errors=True)

        time.sleep(2)
        app(max_loops=2)
        out = testutils.get_stdout(capfd)
        assert out.count(en.MULTI_ERR) == 2
        assert testutils.assert_processed_output(
            out,
            tower_treasure__flat_mp3,
            loops=[
                testutils.check_output(found_books_eq=3, converted_eq=1),
            ],
        )

    ORDER += 1

    @pytest.mark.order(ORDER)
    @pytest.mark.parametrize("loop_count", [0, 2])
    def test_waits_for_fixed_if_all_failed(
        self,
        requires_empty_inbox,
        missing_chums__mixed_mp3: Audiobook,
        roman_numeral__mp3: Audiobook,
        disable_multidisc,
        loop_count,
        capfd: CaptureFixture[str],
    ):

        testutils.set_match_filter(None)
        testutils.fail_book(missing_chums__mixed_mp3)
        testutils.fail_book(roman_numeral__mp3)

        # Note: probably an impossible state to get into now, but just in case
        testutils.force_inbox_up_to_date()
        InboxState().loop_counter = loop_count

        app(max_loops=1)
        out = testutils.get_stdout(capfd)

        if loop_count == 0:
            assert testutils.assert_header_count(out, expected_eq=1)
        else:
            assert testutils.assert_header_count(out, expected_eq=0)

        assert out.count(en.ROMAN_ERR) == 0
        assert out.count(en.MULTI_ERR) == 0

        check = (
            [testutils.check_output(found_books_eq=2, converted_eq=0)]
            if loop_count == 0
            else [testutils.check_output(empty=True)]
        )
        assert testutils.assert_processed_output(
            out,
            loops=check,
        )
        assert out.count("waiting for them to be fixed") == (1 if loop_count == 0 else 0)

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_inbox_hash_doesnt_change_when_book_fails(
        self,
        tiny__flat_mp3: Audiobook,
        old_mill__multidisc_mp3: Audiobook,
        disable_multidisc,
        enable_debug,
        capfd: CaptureFixture[str],
    ):
        testutils.set_match_filter("^(tiny|old)")
        time.sleep(1)
        app(max_loops=1)
        out = testutils.get_stdout(capfd)
        assert out.count(en.DEBUG_INBOX_HASH_UNCHANGED) == 0
        assert out.count(en.DONE_CONVERTING) == 1
        assert out.count(en.MULTI_ERR) == 1
        assert out.count(en.INBOX_RECENTLY_MODIFIED) == 0

        assert testutils.assert_processed_output(
            out,
            tiny__flat_mp3,
            loops=[testutils.check_output(found_books_eq=2, converted_eq=1)],
        )

        InboxState().reset_loop_counter()
        app(max_loops=2)
        out = testutils.get_stdout(capfd)
        assert testutils.assert_count_inbox_hash_changed(out.splitlines(), 1)
        assert out.count(en.DONE_CONVERTING) == 1
        assert out.count(en.MULTI_ERR) == 0
        assert out.count(en.INBOX_RECENTLY_MODIFIED) == 0

        assert testutils.assert_processed_output(
            out,
            tiny__flat_mp3,
            loops=[
                testutils.check_output(found_books_eq=2, converted_eq=1, skipped_failed_eq=1),
            ],
        )

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_prints_dont_repeat_when_inbox_is_empty(
        self,
        enable_debug,
        capfd: CaptureFixture[str],
    ):
        inbox_hidden = TEST_DIRS.inbox.parent / "inbox-hidden"

        # hide inbox
        if not inbox_hidden.exists():
            TEST_DIRS.inbox.rename(inbox_hidden)
        elif list(TEST_DIRS.inbox.glob("*")):
            pytest.fail(
                "Inbox is not empty and inbox-hidden exists, cannot run this test. Please empty the inbox or delete inbox-hidden"
            )

        try:
            app(max_loops=5)
            out = testutils.get_stdout(capfd)
            # assert out.count("Watching for books in") == 1
            assert testutils.assert_count_no_audio_files_found(out.splitlines(), 1)
            assert testutils.assert_processed_output(
                out,
                loops=[testutils.check_output(empty=True)],
            )
        finally:
            # unhide inbox
            inbox_hidden.rename(TEST_DIRS.inbox)

    ORDER += 1

    @pytest.mark.order(ORDER)
    def test_fatal_err_creates_err_file(self, tiny__flat_mp3: Audiobook, enable_backups, tmp_path):
        from src.lib.config import cfg

        def bad__mv_or_cp_dir_contents(*args, **kwargs):
            raise FileNotFoundError(f"No such file or directory {args[1]}")

        with patch("src.lib.fs_utils._mv_or_cp_dir_contents", bad__mv_or_cp_dir_contents):

            try:

                from src.lib.config import cfg

                with pytest.raises(FileNotFoundError):
                    app(max_loops=1)

                assert cfg.FATAL_FILE.exists()
            finally:
                cfg.FATAL_FILE.unlink(missing_ok=True)
