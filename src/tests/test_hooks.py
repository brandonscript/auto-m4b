"""Tests for the post-convert hook runner."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.lib.hooks import _append_post_convert_log, run_post_convert_script


def test_append_post_convert_log_writes_dedicated_file(tmp_path: Path):
    log = tmp_path / "auto-m4b.Book.post-convert.log"
    book = SimpleNamespace(post_convert_log_file=log)

    _append_post_convert_log(
        book,
        script_name="post-convert-deluge.py",
        status="failed",
        exit_code=1,
        stdout="[deluge] finalizing…\n",
        stderr="Deluge login failed\n",
    )

    text = log.read_text(encoding="utf-8")
    assert "Post-convert script: post-convert-deluge.py" in text
    assert "Status: failed" in text
    assert "Exit code: 1" in text
    assert "Deluge login failed" in text


def test_run_post_convert_script_writes_failure_log(tmp_path: Path):
    script = tmp_path / "fail.sh"
    script.write_text("#!/bin/bash\necho out-msg\necho err-msg >&2\nexit 7\n", encoding="utf-8")
    script.chmod(0o755)

    converted_dir = tmp_path / "converted"
    converted_dir.mkdir()
    log = converted_dir / "auto-m4b.Book.post-convert.log"
    book = SimpleNamespace(
        post_convert_log_file=log,
        inbox_dir=tmp_path / "inbox" / "Book",
        converted_file=converted_dir / "Book.m4b",
        converted_dir=converted_dir,
        title="Book",
        author="Author",
        key="Book",
    )

    with patch("src.lib.config.cfg") as cfg:
        cfg.POST_CONVERT_SCRIPT = str(script)
        cfg.POST_CONVERT_SCRIPT_TIMEOUT = 10
        cfg.watch_dir = None
        run_post_convert_script(book)

    text = log.read_text(encoding="utf-8")
    assert "Status: failed" in text
    assert "Exit code: 7" in text
    assert "out-msg" in text
    assert "err-msg" in text
