"""
Tests for src.lib.watch_folder.WatchFolder.

Each test gets its own isolated watch directory via the ``watch_dir`` fixture,
which also sets/unsets WATCH_FOLDER and invalidates cfg.watch_dir so that the
cached value is re-computed from the current environment.
"""

import os
import shutil
import time
from pathlib import Path

import pytest

from src.lib.config import cfg
from src.lib.watch_folder import WatchFolder
from src.tests.helpers.pytest_utils import testutils


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def watch_dir(tmp_path: Path):
    """
    Create a fresh, isolated watch directory for a single test.
    Sets WATCH_FOLDER and clears cfg.watch_dir so the new value is picked up.
    Restores the previous state on teardown.
    """
    watch = tmp_path / "watch"
    watch.mkdir()

    prev = os.environ.get("WATCH_FOLDER")
    os.environ["WATCH_FOLDER"] = str(watch)
    try:
        del cfg.watch_dir
    except AttributeError:
        pass

    yield watch

    if prev is None:
        os.environ.pop("WATCH_FOLDER", None)
    else:
        os.environ["WATCH_FOLDER"] = prev
    try:
        del cfg.watch_dir
    except AttributeError:
        pass
    shutil.rmtree(watch, ignore_errors=True)


def _make_audio_files(directory: Path, *names: str) -> list[Path]:
    """Create stub audio files (empty files with audio extensions) in *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        p = directory / name
        testutils.make_mock_file(p)
        paths.append(p)
    return paths


def _backdate(path: Path, seconds: float = 30.0):
    """Set mtime/atime of all files under *path* to the past."""
    old = time.time() - seconds
    for f in path.rglob("*"):
        if f.is_file():
            os.utime(f, (old, old))


# ---------------------------------------------------------------------------
# WatchFolder._audio_file_count
# ---------------------------------------------------------------------------


class TestAudioFileCount:
    def test_counts_mp3_files(self, watch_dir: Path):
        book = watch_dir / "MyBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3", "ch3.mp3")
        assert WatchFolder._audio_file_count(book) == 3

    def test_counts_mixed_audio_extensions(self, watch_dir: Path):
        book = watch_dir / "MyBook"
        _make_audio_files(book, "part1.mp3", "part2.m4a")
        assert WatchFolder._audio_file_count(book) == 2

    def test_does_not_count_video_files(self, watch_dir: Path):
        book = watch_dir / "MovieWithCommentary"
        _make_audio_files(book, "commentary.mp3")
        # Add video files alongside the audio file
        (book / "movie.mkv").touch()
        (book / "movie.mp4").touch()
        (book / "bonus.mov").touch()
        assert WatchFolder._audio_file_count(book) == 1

    def test_counts_audio_files_recursively(self, watch_dir: Path):
        book = watch_dir / "MultiDisc"
        _make_audio_files(book / "Disc1", "track1.mp3", "track2.mp3")
        _make_audio_files(book / "Disc2", "track3.mp3")
        assert WatchFolder._audio_file_count(book) == 3

    def test_empty_dir_returns_zero(self, watch_dir: Path):
        book = watch_dir / "Empty"
        book.mkdir()
        assert WatchFolder._audio_file_count(book) == 0


# ---------------------------------------------------------------------------
# WatchFolder.is_stable
# ---------------------------------------------------------------------------


class TestIsStable:
    def test_stable_after_backdating(self, watch_dir: Path):
        book = watch_dir / "StableBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book, seconds=cfg.WAIT_TIME * 3 + 1)
        assert WatchFolder.is_stable(book) is True

    def test_not_stable_when_recently_modified(self, watch_dir: Path):
        book = watch_dir / "NewBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        # Files were just created — mtime is within WAIT_TIME
        assert WatchFolder.is_stable(book) is False

    def test_not_stable_when_part_file_present(self, watch_dir: Path):
        book = watch_dir / "InProgress"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book, seconds=cfg.WAIT_TIME * 3 + 1)
        # Deluge writes .part files for incomplete downloads
        (book / "ch3.mp3.part").touch()
        assert WatchFolder.is_stable(book) is False

    def test_empty_dir_is_stable(self, watch_dir: Path):
        book = watch_dir / "Empty"
        book.mkdir()
        assert WatchFolder.is_stable(book) is True


# ---------------------------------------------------------------------------
# WatchFolder._should_ignore
# ---------------------------------------------------------------------------


class TestShouldIgnore:
    def test_ignores_dot_dirs(self, watch_dir: Path):
        assert WatchFolder._should_ignore(watch_dir / ".hidden") is True

    def test_ignores_hash_dirs(self, watch_dir: Path):
        assert WatchFolder._should_ignore(watch_dir / "#auto-m4b") is True
        assert WatchFolder._should_ignore(watch_dir / "#done") is True

    def test_ignores_synology_metadata_dirs(self, watch_dir: Path):
        assert WatchFolder._should_ignore(watch_dir / "@eaDir") is True

    def test_ignores_tmp_dirs(self, watch_dir: Path):
        assert WatchFolder._should_ignore(watch_dir / "@tmp") is True

    def test_does_not_ignore_regular_dirs(self, watch_dir: Path):
        assert WatchFolder._should_ignore(watch_dir / "My Audiobook") is False
        assert WatchFolder._should_ignore(watch_dir / "Author - Title") is False


# ---------------------------------------------------------------------------
# WatchFolder.find_convertible_books
# ---------------------------------------------------------------------------


class TestFindConvertibleBooks:
    def test_finds_multi_audio_folder(self, watch_dir: Path):
        book = watch_dir / "MyBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book)
        found = WatchFolder.find_convertible_books()
        assert book in found

    def test_ignores_single_audio_file_folder(self, watch_dir: Path):
        book = watch_dir / "SingleTrack"
        _make_audio_files(book, "track.mp3")
        _backdate(book)
        found = WatchFolder.find_convertible_books()
        assert book not in found

    def test_ignores_single_m4b_folder(self, watch_dir: Path):
        book = watch_dir / "AlreadyDone"
        _make_audio_files(book, "book.m4b")
        _backdate(book)
        found = WatchFolder.find_convertible_books()
        assert book not in found

    def test_ignores_mixed_audio_video_folder(self, watch_dir: Path):
        """A folder with 1 audio file + video files must NOT be copied."""
        book = watch_dir / "VideoWithCommentary"
        _make_audio_files(book, "commentary.mp3")
        (book / "movie.mkv").touch()
        (book / "movie.mp4").touch()
        _backdate(book)
        found = WatchFolder.find_convertible_books()
        assert book not in found

    def test_ignores_folder_already_in_inbox(self, watch_dir: Path):
        book = watch_dir / "MyBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book)
        # Simulate the book already being in the inbox
        inbox_copy = cfg.inbox_dir / "MyBook"
        inbox_copy.mkdir(parents=True, exist_ok=True)
        try:
            found = WatchFolder.find_convertible_books()
            assert book not in found
        finally:
            shutil.rmtree(inbox_copy, ignore_errors=True)

    def test_ignores_folder_already_in_converted(self, watch_dir: Path):
        book = watch_dir / "MyBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book)
        converted_copy = cfg.converted_dir / "MyBook"
        converted_copy.mkdir(parents=True, exist_ok=True)
        try:
            found = WatchFolder.find_convertible_books()
            assert book not in found
        finally:
            shutil.rmtree(converted_copy, ignore_errors=True)

    def test_ignores_folder_already_in_archive(self, watch_dir: Path):
        book = watch_dir / "MyBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book)
        archive_copy = cfg.archive_dir / "MyBook"
        archive_copy.mkdir(parents=True, exist_ok=True)
        try:
            found = WatchFolder.find_convertible_books()
            assert book not in found
        finally:
            shutil.rmtree(archive_copy, ignore_errors=True)

    def test_ignores_hash_dirs(self, watch_dir: Path):
        bad = watch_dir / "#auto-m4b"
        _make_audio_files(bad, "ch1.mp3", "ch2.mp3")
        _backdate(bad)
        found = WatchFolder.find_convertible_books()
        assert bad not in found

    def test_returns_empty_when_watch_dir_not_set(self):
        prev = os.environ.pop("WATCH_FOLDER", None)
        try:
            del cfg.watch_dir
        except AttributeError:
            pass
        try:
            assert WatchFolder.find_convertible_books() == []
        finally:
            if prev:
                os.environ["WATCH_FOLDER"] = prev
            try:
                del cfg.watch_dir
            except AttributeError:
                pass


# ---------------------------------------------------------------------------
# WatchFolder.scan_and_copy
# ---------------------------------------------------------------------------


class TestScanAndCopy:
    def test_copies_stable_book_to_inbox(self, watch_dir: Path):
        book = watch_dir / "MyBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book)

        copied = WatchFolder.scan_and_copy()

        assert len(copied) == 1
        dest = cfg.inbox_dir / "MyBook"
        assert dest.exists()
        assert dest in copied
        # Source must still exist (copy, not move)
        assert book.exists()

    def test_does_not_copy_unstable_book(self, watch_dir: Path):
        book = watch_dir / "Downloading"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        # Files are fresh — not stable yet

        copied = WatchFolder.scan_and_copy()

        assert copied == []
        assert not (cfg.inbox_dir / "Downloading").exists()

    def test_does_not_copy_single_audio_file(self, watch_dir: Path):
        book = watch_dir / "SingleTrack"
        _make_audio_files(book, "track.mp3")
        _backdate(book)

        copied = WatchFolder.scan_and_copy()

        assert copied == []
        assert not (cfg.inbox_dir / "SingleTrack").exists()

    def test_copies_multiple_books(self, watch_dir: Path):
        for name in ("Book A", "Book B", "Book C"):
            book = watch_dir / name
            _make_audio_files(book, "ch1.mp3", "ch2.mp3")
            _backdate(book)

        copied = WatchFolder.scan_and_copy()

        assert len(copied) == 3
        for name in ("Book A", "Book B", "Book C"):
            assert (cfg.inbox_dir / name).exists()

    def test_skips_already_copied_on_second_call(self, watch_dir: Path):
        book = watch_dir / "MyBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book)

        first = WatchFolder.scan_and_copy()
        assert len(first) == 1

        # Second call: book is now in inbox, should be skipped
        second = WatchFolder.scan_and_copy()
        assert second == []

    def test_marker_file_written_to_source_after_copy(self, watch_dir: Path):
        book = watch_dir / "MarkedBook"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book)

        copied = WatchFolder.scan_and_copy()
        assert len(copied) == 1

        # Marker file must appear in the SOURCE directory
        assert (book / ".auto-m4b").exists()
        # Marker should NOT be in the inbox copy (we write it after copytree)
        assert not (cfg.inbox_dir / "MarkedBook" / ".auto-m4b").exists()

    def test_marker_prevents_recopy_after_inbox_removed(self, watch_dir: Path):
        """Even if inbox/converted/archive entries disappear (e.g. user moves the
        m4b to their library), the marker file in the source dir stops re-copying."""
        book = watch_dir / "GoneFromInbox"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book)

        first = WatchFolder.scan_and_copy()
        assert len(first) == 1

        # Simulate: user moved the converted m4b, inbox/archive both gone
        import shutil

        shutil.rmtree(cfg.inbox_dir / "GoneFromInbox", ignore_errors=True)

        # Second call: marker file alone should prevent re-copy
        second = WatchFolder.scan_and_copy()
        assert second == []
        assert not (cfg.inbox_dir / "GoneFromInbox").exists()

    def test_copies_new_nested_book_after_parent_was_marked(self, watch_dir: Path):
        """A later download under a marked container is copied independently."""
        container = watch_dir / "Brandon Sanderson"
        first_book = container / "3-The Hero of Ages"
        _make_audio_files(first_book, "ch1.mp3", "ch2.mp3")
        _backdate(container)

        first = WatchFolder.scan_and_copy()
        assert first == [cfg.inbox_dir / container.name]
        assert (container / ".auto-m4b").read_text(encoding="utf-8") == "3-The Hero of Ages"

        second_book = container / "4-The Alloy of Law"
        _make_audio_files(second_book, "ch1.mp3", "ch2.mp3")
        _backdate(container)

        second = WatchFolder.scan_and_copy()

        assert second == [cfg.inbox_dir / container.name / second_book.name]
        assert (cfg.inbox_dir / container.name / first_book.name).exists()
        assert (cfg.inbox_dir / container.name / second_book.name).exists()
        assert "4-The Alloy of Law" in (container / ".auto-m4b").read_text(encoding="utf-8")

    def test_retries_nested_book_when_converted_output_is_empty(self, watch_dir: Path):
        """An empty converted shell must not make a marked child permanently handled."""
        container = watch_dir / "Retry Container"
        child = container / "Book One"
        _make_audio_files(child, "ch1.mp3", "ch2.mp3")
        (container / ".auto-m4b").write_text(child.name, encoding="utf-8")
        _backdate(container)

        # Reproduce the bad state: an archive record exists, but the converted
        # child directory exists without an .m4b output while the source remains
        # available for retry.
        (cfg.archive_dir / container.name / child.name).mkdir(parents=True)
        (cfg.converted_dir / container.name / child.name).mkdir(parents=True)

        copied = WatchFolder.scan_and_copy()

        assert copied == [cfg.inbox_dir / container.name / child.name]
        assert (cfg.inbox_dir / container.name / child.name / "ch1.mp3").exists()

    def test_no_op_without_watch_dir(self):
        prev = os.environ.pop("WATCH_FOLDER", None)
        try:
            del cfg.watch_dir
        except AttributeError:
            pass
        try:
            assert WatchFolder.scan_and_copy() == []
        finally:
            if prev:
                os.environ["WATCH_FOLDER"] = prev
            try:
                del cfg.watch_dir
            except AttributeError:
                pass

    def test_ignores_part_files_in_stable_otherwise_dir(self, watch_dir: Path):
        book = watch_dir / "InProgress"
        _make_audio_files(book, "ch1.mp3", "ch2.mp3")
        _backdate(book)
        (book / "ch3.mp3.part").touch()  # still downloading

        copied = WatchFolder.scan_and_copy()

        assert copied == []
        assert not (cfg.inbox_dir / "InProgress").exists()
