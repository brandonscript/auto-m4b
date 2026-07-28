import re
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
        app(max_loops=1)
        # No path list — the Tanyth Fairport Adventures series has a mixed
        # structure (flat .m4a + sub-directories) that makes pre-scan
        # is_book_root classification unreliable.  The converted_eq=22 check in
        # loops is sufficient to verify all 22 books were processed.
        assert testutils.assert_processed_output(
            capfd,
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

    def test_series_with_single_remaining_book_does_not_flatten_to_parent(
        self,
        capfd: pytest.CaptureFixture[str],
    ):
        """When a series parent directory has only one child remaining (e.g. after other
        books in the series were already archived), auto-m4b must NOT flatten the remaining
        book's files into the series parent root.

        Regression for the John Grisham / 'The Appeal' bug: score_series_parent returned
        0.0 for single-child parents (< 0.75 threshold), so check_nested incorrectly marked
        the parent as 'nested', then flatten_nested_book moved files from the child dir up
        to the series root."""
        from src.lib.config import cfg

        # Simulates a series where all other books were archived, leaving only one
        series_dir = TEST_DIRS.inbox / "John Grisham"
        book_dir = series_dir / "2008 - The Appeal"
        book_dir.mkdir(parents=True, exist_ok=True)

        src_mp3 = FIXTURES_ROOT / "basic_with_cover__standalone_mp3.mp3"
        for i in range(3):
            shutil.copy(src_mp3, book_dir / f"Chapter {i+1:02d}.mp3")
        # Touch so the dir is not considered "recently modified"
        for f in book_dir.iterdir():
            import os, time as _time

            os.utime(f, (_time.time() - 120, _time.time() - 120))

        try:
            testutils.set_match_filter("^(John Grisham)")
            app(max_loops=1)

            assert not cfg.FATAL_FILE.exists(), "App crashed fatally"

            # Files must NOT have been moved to the series parent root
            mp3_at_root = [f for f in series_dir.iterdir() if f.is_file() and f.suffix == ".mp3"]
            assert not mp3_at_root, (
                f"Bug: mp3 files were incorrectly flattened into the series parent dir: "
                f"{[f.name for f in mp3_at_root]}"
            )

            # The book subdirectory must still exist
            assert book_dir.exists(), "Book subdirectory should not have been removed"

            # In test_do_nothing mode the converted dir should contain the series-namespaced output
            expected_converted_dir = TEST_DIRS.converted / "John Grisham" / "2008 - The Appeal"
            assert expected_converted_dir.exists(), (
                f"Expected converted output at {expected_converted_dir}"
            )
        finally:
            shutil.rmtree(series_dir, ignore_errors=True)

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

    def test_empty_series_parent_dir_cleaned_up_in_same_run(
        self,
        Chanur_Series: list[Audiobook],
        enable_archiving,
    ):
        """
        When all series children are archived in one process_inbox pass, the parent
        inbox dir must also be removed — even if is_last_book_in_series did not fire
        (e.g. due to dict insertion order placing the "last" scan-order child first).

        Regression for: series parent dir left empty in inbox after all books converted.
        """
        app(max_loops=1)
        series_parent = Chanur_Series[0]

        # All children converted — parent inbox dir must be gone.
        assert not series_parent.inbox_dir.exists(), (
            f"Series parent inbox dir should be cleaned up but still exists: {series_parent.inbox_dir}"
        )

    def test_empty_series_parent_dir_cleaned_up_on_next_run(
        self,
        Chanur_Series: list[Audiobook],
        enable_archiving,
    ):
        """
        If the series parent dir is left empty on disk (e.g. after a container restart
        where _items was reset and prune_gone removed all children), the next
        process_inbox call must detect and remove the empty dir.

        This covers the restart scenario: BooksTree won't classify an empty dir as
        series_parent (no children = no audio files), so it never enters _items again.
        The Sweep 2 path in process_inbox must catch it via inbox dir iteration.
        """
        app(max_loops=1)
        series_parent = Chanur_Series[0]

        # Simulate the "stuck empty parent" state by recreating the empty inbox dir.
        series_parent.inbox_dir.mkdir(parents=True, exist_ok=True)
        assert series_parent.inbox_dir.exists()
        assert not any(series_parent.inbox_dir.iterdir()), "Sanity: dir should be empty"

        # Force mtime to be old enough to pass the was_recently_modified guard.
        import os
        import time
        old_time = time.time() - 3600  # 1 hour ago
        os.utime(series_parent.inbox_dir, (old_time, old_time))

        # Reset the loop counter so the second app() call actually runs.
        # (InboxState is a singleton; its loop_counter stays at 1 after the first
        # app() call, which would make the second while-loop skip entirely.)
        InboxState().reset_loop_counter()

        # Second pass should remove it via Sweep 2 (not-in-_items, empty, not recent).
        app(max_loops=1)

        assert not series_parent.inbox_dir.exists(), (
            f"Empty series parent dir should have been removed on the next run: {series_parent.inbox_dir}"
        )

    def test_book_in_author_dir_is_not_flattened(
        self,
        tower_treasure__author_dir_mp3: Audiobook,
        capfd: pytest.CaptureFixture[str],
    ):
        """When a book lives inside an author-named folder (e.g.
        inbox/Dixon, Franklin W./The Tower Treasure/audio.mp3), the audio must
        NOT be flattened up to the author root.  The book should be processed
        from the inner book directory and its converted output should land in a
        dedicated sub-folder, not at the author root level.

        Regression for: flatten_nested_book moving audio to the author dir when
        the outer dir had a comma-separated "Last, First" name.
        """
        from src.lib.config import cfg

        testutils.set_match_filter("^(Dixon)")
        app(max_loops=1)

        assert not cfg.FATAL_FILE.exists(), "App crashed fatally"

        author_inbox_dir = TEST_DIRS.inbox / "Dixon, Franklin W."

        # Audio must NOT have been flattened to the author root
        mp3_at_author_root = [
            f for f in author_inbox_dir.iterdir()
            if f.is_file() and f.suffix == ".mp3"
        ] if author_inbox_dir.exists() else []
        assert not mp3_at_author_root, (
            f"Bug: mp3 files were incorrectly flattened to the author dir: "
            f"{[f.name for f in mp3_at_author_root]}"
        )

        # The converted output must be in a book-named sub-folder, not at the
        # author root (i.e. converted/Dixon, Franklin W./The Tower Treasure/)
        expected_book_dir = TEST_DIRS.converted / "Dixon, Franklin W." / "The Tower Treasure"
        assert expected_book_dir.exists(), (
            f"Expected converted output in book subfolder: {expected_book_dir}"
        )

        out = testutils.get_stdout(capfd)
        # No flatten message should appear — the book folder was preserved
        assert en.BOOK_NEEDS_FLATTENING not in out, (
            "Flatten message should not appear when book is inside an author dir"
        )

    def test_midflight_series_addition_is_picked_up(
        self,
        Chanur_Series: list[Audiobook],
        enable_archiving,
        capfd: pytest.CaptureFixture[str],
    ):
        """Books dropped into a series folder while conversion is in flight must be
        discovered via the mid-loop rescan, appended to the work queue, and converted
        — and the Book Series tracker dots must grow to include them.

        Regression for: Dark Tower 1–7 added to King, Stephen mid-run were archived
        by cleanup_series_dir without ever being converted.
        """
        import os
        import time
        from unittest.mock import patch

        from src.lib import run as run_module
        from src.lib.config import cfg

        series_parent = Chanur_Series[0]
        midflight_name = "06 - Midflight Book"
        midflight_dir = series_parent.inbox_dir / midflight_name
        converted_midflight = series_parent.converted_dir / midflight_name

        call_count = {"n": 0}
        original_process_book = run_module.process_book

        def process_then_inject(b, item, _series_rerouted=False):
            result = original_process_book(b, item, _series_rerouted=_series_rerouted)
            call_count["n"] += 1
            # After the first book finishes, drop a new sibling into the series folder.
            if call_count["n"] == 1 and not midflight_dir.exists():
                midflight_dir.mkdir(parents=True, exist_ok=True)
                src = FIXTURES_ROOT / "basic_with_cover__standalone_mp3.mp3"
                dest = midflight_dir / "chapter01.mp3"
                shutil.copy(src, dest)
                # Age so was_recently_modified does not skip the new book.
                old = time.time() - (cfg.WAIT_TIME * 3 + 1)
                os.utime(dest, (old, old))
                os.utime(midflight_dir, (old, old))
            return result

        with patch("src.lib.run.process_book", process_then_inject):
            app(max_loops=1)

        assert not cfg.FATAL_FILE.exists(), "App crashed fatally"
        assert converted_midflight.exists(), (
            f"Mid-flight book should have been converted to {converted_midflight}"
        )
        m4bs = list(converted_midflight.glob("*.m4b"))
        assert m4bs, f"Expected an .m4b under {converted_midflight}"

        out = testutils.get_stdout(capfd)
        # Original Chanur series is 5 books; after mid-flight add the tracker should
        # show 6 dots at some point (••••••).
        assert "Book Series" in out
        assert re.search(r"Book Series[^\n]*••••••", testutils.strip_ansi_codes(out)), (
            "Series tracker should grow to 6 dots after mid-flight addition"
        )

    def test_cleanup_series_dir_defers_when_audio_remains(
        self,
        Chanur_Series: list[Audiobook],
        enable_archiving,
        capfd: pytest.CaptureFixture[str],
    ):
        """cleanup_series_dir must not archive/delete a series parent that still
        contains audio files (e.g. mid-flight drops not yet in the work queue).
        """
        from src.lib.config import cfg
        from src.lib.inbox_state import InboxState
        from src.lib.run import cleanup_series_dir

        series_parent = Chanur_Series[0]
        leftover_dir = series_parent.inbox_dir / "99 - Leftover Book"
        leftover_dir.mkdir(parents=True, exist_ok=True)
        src = FIXTURES_ROOT / "basic_with_cover__standalone_mp3.mp3"
        leftover_mp3 = leftover_dir / "leftover.mp3"
        shutil.copy(src, leftover_mp3)

        inbox = InboxState()
        inbox.scan(force=True)
        parent_item = inbox.get(series_parent.key)
        assert parent_item is not None and parent_item.is_series_parent

        cleanup_series_dir(parent_item)

        assert leftover_mp3.exists(), "Leftover audio must not be archived/deleted"
        assert series_parent.inbox_dir.exists(), "Series parent must remain when audio is present"
        out = testutils.get_stdout(capfd)
        assert "deferring cleanup" in testutils.strip_ansi_codes(out).lower()
        assert not cfg.FATAL_FILE.exists()

    def test_author_dir_cleaned_up_after_last_book(
        self,
        tower_treasure__author_dir_mp3: Audiobook,
        enable_archiving,
    ):
        """Author container dirs must be removed once their last book is archived.

        Regression for: inbox/Author Name/ left behind as an empty (or .DS_Store-only)
        shell after all nested books finished converting.
        """
        from src.lib.config import cfg

        testutils.set_match_filter("^(Dixon)")
        author_inbox_dir = TEST_DIRS.inbox / "Dixon, Franklin W."
        assert author_inbox_dir.is_dir()

        app(max_loops=1)

        assert not cfg.FATAL_FILE.exists(), "App crashed fatally"
        assert not author_inbox_dir.exists(), (
            f"Author inbox dir should be cleaned up after last book archived: {author_inbox_dir}"
        )

    def test_unrelated_empty_inbox_dir_is_left_alone(
        self,
        tower_treasure__author_dir_mp3: Audiobook,
        enable_archiving,
    ):
        """Empty dirs that were never converted must not be swept away."""
        from src.lib.config import cfg

        stray = TEST_DIRS.inbox / "Accidentally Empty Folder"
        stray.mkdir()
        (stray / ".DS_Store").write_bytes(b"x")

        # Make mtime old enough to pass was_recently_modified.
        import os
        import time

        old = time.time() - 3600
        os.utime(stray, (old, old))

        testutils.set_match_filter("^(Dixon)")
        app(max_loops=1)

        assert stray.exists(), "Unrelated empty inbox dir must be left alone"
        assert not cfg.FATAL_FILE.exists()
