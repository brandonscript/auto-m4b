"""Upgrade contracts: state survives a rename without duplicate processing."""

import os
from pathlib import Path

import pytest

from src.lib.name_migration import (
    LEGACY_MARKER,
    MARKER,
    marker_path,
    migrate_home,
    migrate_logs,
    migrate_path,
    migrate_temp,
)


def test_fresh_and_legacy_home(tmp_path):
    assert migrate_home(tmp_path) == tmp_path / MARKER
    old = tmp_path / LEGACY_MARKER
    old.mkdir()
    (old / "cache.db").write_bytes(b"cached data")
    assert (migrate_home(tmp_path) / "cache.db").read_bytes() == b"cached data"
    assert migrate_home(tmp_path).is_dir()
    assert not old.exists()


def test_conflicts_keep_both_and_retry_safely(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "cache").write_text("old")
    (new / "cache").write_text("new")
    with pytest.warns(UserWarning, match="Preserved"):
        migrate_path(old, new)
    assert (new / "cache").read_text() == "new"
    assert (new / "cache.legacy-backup").read_text() == "old"
    migrate_path(old, new)
    assert len(list(new.iterdir())) == 2


def test_markers_preserve_contents_and_stop_on_conflict(tmp_path):
    old = tmp_path / LEGACY_MARKER
    old.write_text("Book 1\nBook 2")
    assert marker_path(tmp_path).read_text() == "Book 1\nBook 2"
    old.write_text("Book 3")
    with pytest.raises(RuntimeError, match="Conflicting processing state"):
        marker_path(tmp_path)
    assert old.read_text() == "Book 3"


def test_readonly_marker_still_recognized(tmp_path, monkeypatch):
    old = tmp_path / LEGACY_MARKER
    old.touch()

    def denied(*args):
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "rename", denied)
    with pytest.warns(UserWarning, match="continuing to recognize"):
        assert marker_path(tmp_path) == old


def test_live_legacy_process_blocks_migration(tmp_path):
    old = tmp_path / "auto-m4b"
    old.mkdir()
    (old / "running.pid").write_text(f"pid={os.getpid()}")
    with pytest.raises(RuntimeError, match="still be running"):
        migrate_temp(tmp_path)
    assert old.exists()


def test_fatal_state_survives(tmp_path):
    old = tmp_path / "auto-m4b"
    old.mkdir()
    (old / "fatal.log").write_text("fatal evidence")
    assert (migrate_temp(tmp_path) / "fatal.log").read_text() == "fatal evidence"
    assert migrate_temp(tmp_path).is_dir()


def test_partial_work_is_not_deleted_or_resumed(tmp_path):
    old = tmp_path / "auto-m4b"
    old.mkdir()
    (old / "build").mkdir()
    (old / "build" / "partial.m4b").write_bytes(b"partial audio")
    with pytest.raises(RuntimeError, match="temporary work remains"):
        migrate_temp(tmp_path)
    assert (old / "build").is_dir()


def test_nested_logs_and_conflicts_preserved(tmp_path):
    folder = tmp_path / "Author" / "Book"
    folder.mkdir(parents=True)
    (folder / "auto-m4b.Book.log").write_text("history")
    (tmp_path / "auto-m4b.log").write_text("global history")
    migrate_logs(tmp_path)
    migrate_logs(tmp_path)
    assert (folder / "otto-m4b.Book.log").read_text() == "history"
    assert (tmp_path / "otto-m4b.log").read_text() == "global history"
    assert not list(tmp_path.rglob("auto-m4b*.log"))


def test_symlink_state_rejected(tmp_path):
    old = tmp_path / "old"
    old.symlink_to(tmp_path / "elsewhere")
    (tmp_path / "elsewhere").touch()
    with pytest.raises(RuntimeError, match="symlink"):
        migrate_path(old, tmp_path / "new")


def test_interrupted_directory_merge_can_resume(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "a").write_text("first")
    (old / "b").write_text("second")
    rename = Path.rename

    def interrupt(path, target):
        if path.name == "b":
            raise OSError("interrupted")
        return rename(path, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", interrupt)
        with pytest.raises(OSError, match="interrupted"):
            migrate_path(old, new)
    migrate_path(old, new)
    assert (new / "a").read_text() == "first"
    assert (new / "b").read_text() == "second"
    assert not old.exists()


def test_conflicting_fatal_state_stops_without_overwrite(tmp_path):
    old, new = tmp_path / "auto-m4b", tmp_path / "otto-m4b"
    old.mkdir()
    new.mkdir()
    (old / "fatal.log").write_text("legacy failure")
    (new / "fatal.log").write_text("current failure")
    with pytest.raises(RuntimeError, match="Conflicting processing state"):
        migrate_temp(tmp_path)
    assert (old / "fatal.log").read_text() == "legacy failure"
    assert (new / "fatal.log").read_text() == "current failure"


def test_empty_work_dirs_can_migrate(tmp_path):
    old = tmp_path / "auto-m4b"
    (old / "build").mkdir(parents=True)
    assert (migrate_temp(tmp_path) / "build").is_dir()
    assert not old.exists()


def test_explicit_legacy_working_directory_is_preserved(tmp_path):
    old = tmp_path / "auto-m4b"
    (old / "merge").mkdir(parents=True)
    (old / "fatal.log").write_text("failure")
    new = migrate_temp(tmp_path, working=old)
    assert (old / "merge").is_dir()
    assert (new / "fatal.log").read_text() == "failure"
    assert migrate_temp(tmp_path, working=old) == new
