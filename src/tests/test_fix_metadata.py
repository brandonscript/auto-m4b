"""CLI/UX unit tests for fix_metadata (argparse, prompts, banners, path discovery)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.fix_metadata import (
    FixPlan,
    TagSnapshot,
    iter_book_dirs,
    parse_apply_prompt,
    resolve_cli_paths,
    resolve_target_paths,
    _banner_fixing_clause,
    _banner_missing_clause,
    _format_mode_banner,
    _format_planning_progress,
    _id3_already_correct_style,
    _truth_props,
)
def _touch(path: Path, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_cli_accepts_short_o_for_ol():
    """-o is an alias for --ol."""
    from src.fix_metadata import build_arg_parser

    args = build_arg_parser().parse_args(["-o", "OL19765246W", "-i", "Author/Book"])
    assert args.ol_ref == "OL19765246W"
    assert args.interactive is True


def test_cli_error_is_readable(capfd):
    """Bad args print a short colored error plus compact Usage (not stock argparse)."""
    from src.fix_metadata import build_arg_parser
    from src.tests.helpers.pytest_utils import testutils

    parser = build_arg_parser()
    with pytest.raises(SystemExit) as ei:
        parser.parse_args(["--not-a-real-flag"])
    assert ei.value.code == 2
    # Tinta/smart_print write via a cached stdout handle, so use PRINT_LOG fallback.
    out = testutils.get_stdout(capfd)
    assert "Unrecognized argument" in out or "unrecognized" in out.lower()
    assert "--not-a-real-flag" in out
    assert "python -m src.fix_metadata: error:" not in out
    assert "Usage:" in out
    assert ("-o" in out or "--ol" in out) and "-i" in out


def test_parse_apply_prompt():
    assert parse_apply_prompt("") == "s"
    assert parse_apply_prompt("y") == "y"
    assert parse_apply_prompt("Yes") == "y"
    assert parse_apply_prompt("s") == "s"
    assert parse_apply_prompt("skip") == "s"
    assert parse_apply_prompt("n") == "s"
    assert parse_apply_prompt("o") == "o"
    assert parse_apply_prompt("ol") == "o"
    assert parse_apply_prompt("m") == "m"
    assert parse_apply_prompt("match") == "m"
    assert parse_apply_prompt("q") == "q"
    assert parse_apply_prompt("quit") == "q"
    assert parse_apply_prompt("a") == "s"  # "all" removed; unknown → skip
    assert parse_apply_prompt("maybe") == "s"


def test_iter_book_dirs_auto_recursive_author(tmp_path: Path):
    author = tmp_path / "Author, A"
    b1 = author / "Book One"
    b2 = author / "Book Two"
    _touch(b1 / "one.m4b")
    _touch(b2 / "two.m4b")

    dirs = iter_book_dirs([author], recursive=False)
    assert {d.name for d in dirs} == {"Book One", "Book Two"}


def test_iter_book_dirs_double_nesting_converted_root(tmp_path: Path):
    converted = tmp_path / "converted"
    a1 = converted / "Author One" / "Book A"
    a2 = converted / "Author Two" / "Book B"
    _touch(a1 / "a.m4b")
    _touch(a2 / "b.m4b")

    dirs = iter_book_dirs([converted], recursive=False)
    assert {d.name for d in dirs} == {"Book A", "Book B"}


def test_iter_book_dirs_mixed_warns_without_r(tmp_path: Path):
    root = tmp_path / "mixed"
    _touch(root / "root.m4b")
    child = root / "Child Book"
    _touch(child / "child.m4b")

    # Without -r: only the parent book dir (children skipped with a warn).
    dirs = iter_book_dirs([root], recursive=False)
    assert [d.name for d in dirs] == ["mixed"]

    dirs_r = iter_book_dirs([root], recursive=True)
    assert {d.name for d in dirs_r} == {"mixed", "Child Book"}


def test_resolve_target_paths_relative_under_converted(tmp_path: Path, monkeypatch):
    converted = tmp_path / "converted"
    author = converted / "George, Margaret"
    author.mkdir(parents=True)
    monkeypatch.setenv("CLI_CONVERTED_FOLDER", str(converted))
    monkeypatch.setenv("CLI_ARCHIVE_FOLDER", str(tmp_path / "archive"))
    monkeypatch.setenv("CLI_INBOX_FOLDER", str(tmp_path / "inbox"))
    (tmp_path / "archive").mkdir()
    (tmp_path / "inbox").mkdir()

    cli = resolve_cli_paths()
    assert cli.converted == converted.resolve()

    resolved = resolve_target_paths([Path("George, Margaret")], cli)
    assert resolved == [author.resolve()]

    defaulted = resolve_target_paths([], cli)
    assert defaulted == [converted.resolve()]


def test_format_planning_progress():
    assert _format_planning_progress(12, 133, "The Left Hand of Darkness (1969)") == (
        "Planning 12/133 · The Left Hand of Darkness (1969)"
    )


def test_low_confidence_ol_count_in_banner_phrasing():
    """Mode banner: needs-fixing + missing sources (no OL-on-review junk)."""
    assert _banner_fixing_clause(0, 7) == "No books need fixing"
    assert _banner_fixing_clause(1, 1) == "1 needs fixing"
    assert _banner_fixing_clause(1, 7) == "1 of 7 needs fixing"
    assert _banner_fixing_clause(2, 7) == "2 of 7 need fixing"
    assert _banner_fixing_clause(5, 5) == "5 need fixing"

    assert _banner_missing_clause(0) == "No missing source files"
    assert _banner_missing_clause(1) == "1 missing source file"
    assert _banner_missing_clause(2) == "2 missing source files"

    assert (
        _format_mode_banner("Interactive", 1, 7, 0)
        == "Interactive // 1 of 7 needs fixing · No missing source files"
    )
    assert (
        _format_mode_banner("Interactive", 2, 7, 2)
        == "Interactive // 2 of 7 need fixing · 2 missing source files"
    )
    assert _format_mode_banner("Interactive", 0, 7, 0) == "Interactive // No books need fixing"
    assert (
        _format_mode_banner("Interactive", 0, 7, 2)
        == "Interactive // No books need fixing · 2 missing source files"
    )


def test_truth_props_date_uses_desired_not_ol(tmp_path: Path):
    """FS/id3 coloring truth is desired_date even when OL year differs."""
    m4b = tmp_path / "book.m4b"
    m4b.touch()
    plan = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title="The Dark Days Club",
        desired_author="Alison Goodman",
        desired_album="The Dark Days Club",
        desired_date="2016",
        desired_narrator="",
        desired_stem="The Dark Days Club",
        current=TagSnapshot(
            title="The Dark Days Club", artist="Alison Goodman", date="2016", path=m4b
        ),
        fs_date="2015",
        ol_status="match",
        ol_title="The Dark Days Club",
        ol_author="Alison Goodman",
        ol_year="2016",
    )
    truth = _truth_props(plan)
    assert truth["date"] == "2016"
    # FS wrong vs desired → id3 match should be mint (not grey+amber)
    assert _id3_already_correct_style("2015", "2016", is_date=True) == "mint"
    # Both agree → muted already-correct on id3 is fine
    assert _id3_already_correct_style("2016", "2016", is_date=True) == "light_grey"


def test_truth_props_prefers_desired_when_ol_year_differs(tmp_path: Path):
    """Even if OL says 2015, coloring follows desired (near-tie / local prior)."""
    m4b = tmp_path / "book.m4b"
    m4b.touch()
    plan = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title="Eon",
        desired_author="Alison Goodman",
        desired_album="Eon",
        desired_date="2008",
        desired_narrator="",
        desired_stem="Eon",
        current=TagSnapshot(title="Eon", artist="Alison Goodman", date="2017", path=m4b),
        fs_date="2008",
        ol_status="match",
        ol_year="2010",
    )
    assert _truth_props(plan)["date"] == "2008"
    assert _id3_already_correct_style("2008", "2008", is_date=True) == "light_grey"
