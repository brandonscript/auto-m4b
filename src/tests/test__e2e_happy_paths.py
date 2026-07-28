import re
import shutil
import time

import pytest
from pytest import CaptureFixture

from src.auto_m4b import app
from src.lib import term
from src.lib.audiobook import Audiobook
from src.lib.id3_utils import extract_cover_art
from src.lib.inbox_state import InboxState
from src.lib.misc import re_group
from src.lib.typing import OnComplete
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

    def test_basic_book_m4b(self, blackmail_bibingka__flat_m4b: Audiobook, capfd: CaptureFixture[str]):
        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            blackmail_bibingka__flat_m4b,
            loops=[testutils.check_output(found_books_eq=1, converted_eq=1)],
        )
        assert blackmail_bibingka__flat_m4b.converted_dir.exists()

    def test_multipart_m4b_merges_even_if_structure_claims_single(
        self,
        blackmail_bibingka__flat_m4b: Audiobook,
        capfd: CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Multi-part m4b must merge when the tree is wrongly scored as single.

        Regression: Angel of Darkness (3 part .m4bs) was moved to converted via
        process_already_m4b because structure said single/standalone with no
        filesystem audio-count gate.
        """
        from src.lib.books_tree.books_tree import BooksTree

        original = BooksTree.has_any_structure

        def claim_single(self, *structs):
            if set(structs) & {"single", "standalone_file"}:
                return True
            return original(self, *structs)

        monkeypatch.setattr(BooksTree, "has_any_structure", claim_single)

        app(max_loops=1)
        out = testutils.get_stdout(capfd)
        assert "already been converted" not in out, (
            "Multi-part m4b must not take process_already_m4b when disk has >1 audio file"
        )
        assert testutils.assert_processed_output(
            out,
            blackmail_bibingka__flat_m4b,
            loops=[testutils.check_output(found_books_eq=1, converted_eq=1)],
        )
        assert blackmail_bibingka__flat_m4b.converted_dir.exists()
        m4bs = list(blackmail_bibingka__flat_m4b.converted_dir.glob("*.m4b"))
        assert len(m4bs) == 1, f"Expected one merged m4b, got {m4bs}"

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

    def test_backup_dir_not_created_when_disabled(self, tiny__flat_mp3: Audiobook, capfd: CaptureFixture[str]):
        """When BACKUP=False, check_dirs() must NOT create the backup directory.

        Regression: backup_dir was always included in check_dirs() regardless
        of the BACKUP setting, causing an empty folder to appear even when the
        user had backups turned off.
        """
        from src.lib.config import cfg

        with testutils.set_backups(False):
            backup_dir = cfg.backup_dir
            # Remove the dir if it already exists from a prior run so we get a
            # clean slate for this assertion.
            import shutil as _shutil
            _shutil.rmtree(backup_dir, ignore_errors=True)

            cfg.check_dirs()

            assert not backup_dir.exists(), (
                f"Backup dir should NOT be created when BACKUP=False, but found: {backup_dir}"
            )

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

    @pytest.mark.parametrize(
        "starting_loop, max_loops, match_filter, watching_count, banner_count",
        [
            # Banner and "Watching for" only ever appear on loop 1 (loop_counter == 1).
            # Subsequent loops process silently — no "Checking for" header any more.
            (0, 1, "--none--", 1, 1),
            (0, 1, "tiny", 1, 1),
            (2, 1, "--none--", 0, 0),  # starting at loop 2 → banner never prints
            (2, 1, "tiny", 0, 0),
            (0, 3, "tiny", 1, 1),  # only loop 1 prints the banner even across 3 loops
            (2, 3, "tiny", 0, 0),
        ],
    )
    @pytest.mark.order()
    def test_friendly_message_when_inbox_is_empty(
        self,
        starting_loop,
        max_loops,
        match_filter,
        watching_count,
        banner_count,
        requires_empty_inbox,
        tiny__flat_mp3: Audiobook,
        capfd: CaptureFixture[str],
    ):

        InboxState().destroy()  # type: ignore
        inbox = InboxState()
        inbox.loop_counter = starting_loop
        inbox.banner_printed = bool(inbox.loop_counter > 0)
        for i in range(max_loops):
            is_last_loop = i == max_loops - 1
            # Set match_filter to none until the last loop
            testutils.set_match_filter("--none--" if not is_last_loop else match_filter)
            testutils.force_inbox_hash_change()
            # Each call to app() should advance exactly one lc step.  Using
            # `starting_loop + i + 1` as max_loops ensures the app stops as
            # soon as it completes lc = starting_loop + i + 1, so the next
            # outer iteration gets a clean starting point.
            app(max_loops=starting_loop + i + 1)
        expected_lc = starting_loop + max_loops
        lc = InboxState().loop_counter
        assert lc == expected_lc, f"loop_counter={lc}, expected={expected_lc}"
        out = testutils.get_stdout(capfd)
        converted = [tiny__flat_mp3] if match_filter == "tiny" else []
        empty = lambda: testutils.check_output(empty=True)
        check = (
            [*[f() for f in [empty] * (max_loops - 1)], testutils.check_output(found_books_eq=1)]
            if match_filter == "tiny"
            else [empty()]
        )
        assert testutils.assert_processed_output(out, *converted, loops=check, starting_loop=starting_loop)

        assert out.count("Starting auto-m4b...") == (1 if starting_loop == 0 else 0)
        assert watching_count == out.count("Watching for books in")
        assert out.count("Checking for books in") == 0, "Checking header should never appear"
        assert banner_count == out.count("⌐◒-◒")

    def test_match_filter_multiple_mp3s(
        self,
        tower_treasure__flat_mp3: Audiobook,
        house_on_the_cliff__flat_mp3: Audiobook,
        capfd: CaptureFixture[str],
        enable_archiving,
    ):

        testutils.backdate_inbox_files()
        testutils.set_match_filter("^(tower|house)")
        inbox = InboxState()
        # inbox.destroy()  # type: ignore
        inbox.scan()
        assert tower_treasure__flat_mp3.inbox_dir.exists()
        assert house_on_the_cliff__flat_mp3.inbox_dir.exists()
        tower = inbox.get("tower_treasure__flat_mp3")
        house = inbox.get("house_on_the_cliff__flat_mp3")
        assert tower
        assert house
        total_books = inbox.num_ok
        matched_books = inbox.num_matched
        assert matched_books == 2
        filtered_books = inbox.num_ignored_books
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
        found = int(re_group(re.search(r"Found (\d+) book", out), 1, default=0))
        ignoring = int(re_group(re.search(r"\(ignoring (\d+)\)", out), 1, default=0))
        converted = len(testutils.get_all_processed_books(out))
        assert found == matched_books
        assert ignoring == filtered_books
        inbox.scan()
        assert found + ignoring == total_books == inbox.num_ok + converted
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
    def test_multidisc_backups_work_when_flattened(
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

        # Only assert cover art exists for fixtures that have embedded cover art.
        # No-cover books rely on internet scraping which is unreliable in tests.
        if book.has_id3_cover:
            img = extract_cover_art(
                book.converted_file,
                save_to_file=True,
                filename="test_cover.jpg",
            )
            assert img.exists()
            assert img.stat().st_size > 10000
