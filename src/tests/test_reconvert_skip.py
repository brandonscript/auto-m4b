"""Tests for reconvert skip policy and idle inbox pickup."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.lib.audiobook import Audiobook
from src.lib.fs_utils import audio_fingerprints_match, hash_path_audio_files
from src.lib.inbox_state import InboxState
from src.lib.run import ok_to_overwrite


@pytest.fixture(autouse=True)
def _reset_inbox():
    InboxState._instance = None  # type: ignore
    yield
    InboxState._instance = None  # type: ignore


def _copy_audio_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)


class TestAudioFingerprintsMatch:
    def test_identical_trees_match(self, tiny__flat_mp3: Audiobook, tmp_path: Path):
        other = tmp_path / "copy"
        _copy_audio_tree(tiny__flat_mp3.inbox_dir, other)
        assert audio_fingerprints_match(tiny__flat_mp3.inbox_dir, other)

    def test_different_size_does_not_match(self, tiny__flat_mp3: Audiobook, tmp_path: Path):
        other = tmp_path / "copy"
        _copy_audio_tree(tiny__flat_mp3.inbox_dir, other)
        # Grow one audio file so the fingerprint changes
        audio = next(other.rglob("*.mp3"))
        audio.write_bytes(audio.read_bytes() + b"\x00" * 64)
        assert not audio_fingerprints_match(tiny__flat_mp3.inbox_dir, other)

    def test_missing_path_does_not_match(self, tiny__flat_mp3: Audiobook, tmp_path: Path):
        assert not audio_fingerprints_match(tiny__flat_mp3.inbox_dir, tmp_path / "nope")


class TestOkToOverwrite:
    def test_allows_when_converted_and_archive_gone(self, tiny__flat_mp3: Audiobook):
        shutil.rmtree(tiny__flat_mp3.converted_dir, ignore_errors=True)
        shutil.rmtree(tiny__flat_mp3.archive_dir, ignore_errors=True)
        from src.lib.config import cfg

        cfg.OVERWRITE_MODE = "skip"
        assert ok_to_overwrite(tiny__flat_mp3) is True

    def test_skips_when_converted_exists(self, tiny__flat_mp3: Audiobook):
        InboxState().scan(force=True)
        tiny__flat_mp3.converted_dir.mkdir(parents=True, exist_ok=True)
        tiny__flat_mp3.converted_file.write_bytes(b"\x00" * 2048)
        try:
            from src.lib.config import cfg

            cfg.OVERWRITE_MODE = "skip"
            assert ok_to_overwrite(tiny__flat_mp3) is False
            assert InboxState().get(tiny__flat_mp3).status == "processed"  # type: ignore
        finally:
            shutil.rmtree(tiny__flat_mp3.converted_dir, ignore_errors=True)

    def test_skips_when_archive_fingerprint_matches(self, tiny__flat_mp3: Audiobook):
        shutil.rmtree(tiny__flat_mp3.converted_dir, ignore_errors=True)
        shutil.rmtree(tiny__flat_mp3.archive_dir, ignore_errors=True)
        _copy_audio_tree(tiny__flat_mp3.inbox_dir, tiny__flat_mp3.archive_dir)
        try:
            from src.lib.config import cfg

            cfg.OVERWRITE_MODE = "skip"
            InboxState().scan(force=True)
            assert ok_to_overwrite(tiny__flat_mp3) is False
            assert InboxState().get(tiny__flat_mp3).status == "processed"  # type: ignore
        finally:
            shutil.rmtree(tiny__flat_mp3.archive_dir, ignore_errors=True)

    def test_allows_when_archive_fingerprint_differs(self, tiny__flat_mp3: Audiobook):
        shutil.rmtree(tiny__flat_mp3.converted_dir, ignore_errors=True)
        shutil.rmtree(tiny__flat_mp3.archive_dir, ignore_errors=True)
        _copy_audio_tree(tiny__flat_mp3.inbox_dir, tiny__flat_mp3.archive_dir)
        audio = next(tiny__flat_mp3.archive_dir.rglob("*.mp3"))
        audio.write_bytes(audio.read_bytes() + b"\x00" * 128)
        try:
            from src.lib.config import cfg

            cfg.OVERWRITE_MODE = "skip"
            assert ok_to_overwrite(tiny__flat_mp3) is True
        finally:
            shutil.rmtree(tiny__flat_mp3.archive_dir, ignore_errors=True)


class TestProcessedReset:
    def test_processed_resets_when_converted_gone_and_no_archive(self, tiny__flat_mp3: Audiobook):
        inbox = InboxState()
        inbox.scan(force=True)
        item = inbox.get(tiny__flat_mp3)
        assert item
        item.set_processed()
        shutil.rmtree(tiny__flat_mp3.converted_dir, ignore_errors=True)
        shutil.rmtree(tiny__flat_mp3.archive_dir, ignore_errors=True)

        inbox.scan(force=True)
        assert inbox.get(tiny__flat_mp3).status == "new"  # type: ignore

    def test_processed_kept_when_archive_matches(self, tiny__flat_mp3: Audiobook):
        inbox = InboxState()
        inbox.scan(force=True)
        item = inbox.get(tiny__flat_mp3)
        assert item
        item.set_processed()
        shutil.rmtree(tiny__flat_mp3.converted_dir, ignore_errors=True)
        shutil.rmtree(tiny__flat_mp3.archive_dir, ignore_errors=True)
        _copy_audio_tree(tiny__flat_mp3.inbox_dir, tiny__flat_mp3.archive_dir)

        try:
            inbox.scan(force=True)
            assert inbox.get(tiny__flat_mp3).status == "processed"  # type: ignore
        finally:
            shutil.rmtree(tiny__flat_mp3.archive_dir, ignore_errors=True)


class TestIdlePickup:
    def test_live_hash_triggers_processing_after_stale_empty_scan(
        self, tiny__flat_mp3: Audiobook, tmp_path: Path
    ):
        """Empty startup hash + book already on disk → next_hash forces needs_scan."""
        inbox = InboxState()
        # Simulate post-startup: empty hash recorded as last run end, but book is present.
        inbox.scan(force=True, set_ready=True)
        inbox.start()
        inbox.done()

        # Stale the cached hash back to "empty" while leaving the book on disk.
        empty_hash = hash_path_audio_files(tmp_path)  # no audio → empty fingerprint
        inbox._hashes = [(empty_hash, inbox._hashes[0][1])]  # type: ignore[index]
        inbox._last_run_end = (empty_hash, inbox._last_run_end[1] if inbox._last_run_end else 0)
        inbox._items.clear()

        assert not inbox.matched_ok_books
        assert inbox.inbox_needs_processing() is True
        assert tiny__flat_mp3.key in inbox.matched_ok_books or inbox.num_matched_ok >= 1
