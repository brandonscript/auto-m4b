"""CLI/UX unit tests for fix_metadata (argparse, prompts, banners, path discovery)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.fix_metadata import (
    CliPaths,
    FixPlan,
    TagSnapshot,
    edit_plan,
    iter_book_dirs,
    main,
    parse_apply_prompt,
    prompt_apply,
    prompt_goodreads_ref,
    prompt_ol_ref,
    resolve_cli_paths,
    resolve_target_paths,
    _set_plan_filename,
    _banner_fixing_clause,
    _banner_missing_clause,
    _can_reassign_author_to_narrator,
    _format_mode_banner,
    _format_planning_progress,
    _id3_already_correct_style,
    _prompt_edit_value,
    _save_interactive_tags_only,
    _truth_props,
)
from src.lib.metadata.apply import apply_fix


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


def test_cli_accepts_short_g_for_goodreads():
    """-g is an alias for --goodreads."""
    from src.fix_metadata import build_arg_parser

    args = build_arg_parser().parse_args(["-g", "176803", "-i", "Author/Book"])
    assert args.goodreads_ref == "176803"
    assert args.interactive is True


def test_forced_goodreads_does_not_require_source(tmp_path: Path, monkeypatch):
    import src.fix_metadata as module

    plan = _main_manual_ol_plan(tmp_path)
    captured: dict[str, object] = {}

    monkeypatch.setattr(module, "resolve_cli_paths", lambda: CliPaths())
    monkeypatch.setattr(module, "resolve_target_paths", lambda _paths, _cli: [tmp_path])
    monkeypatch.setattr(module, "iter_book_dirs", lambda _paths, recursive: [tmp_path])
    monkeypatch.setattr(
        module,
        "plan_fix",
        lambda *args, **kwargs: captured.update(kwargs) or plan,
    )
    monkeypatch.setattr(module, "print_ol_session_notice", lambda **kwargs: None)
    monkeypatch.setattr(module, "_print_planning_progress", lambda *args: None)
    monkeypatch.setattr(module, "_clear_planning_progress", lambda: None)
    monkeypatch.setattr(module, "apply_fix", lambda *args, **kwargs: None)

    assert main(["--apply", "--goodreads", "176803", str(tmp_path)]) == 0
    assert captured["require_source"] is False


def test_cli_accepts_tags_only_option():
    from src.fix_metadata import build_arg_parser

    args = build_arg_parser().parse_args(["-t", "Author/Book"])

    assert args.tags_only is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("e", "e"), ("edit", "e"), ("c", "c"), ("cancel", "c")],
)
def test_parse_apply_prompt_edit_and_cancel(raw: str, expected: str):
    assert parse_apply_prompt(raw) == expected


def test_parse_apply_prompt_reassigns_author_to_narrator():
    assert parse_apply_prompt("r") == "r"
    assert parse_apply_prompt("reassign") == "s"


def test_parse_apply_prompt_accepts_goodreads():
    assert parse_apply_prompt("g") == "g"
    assert parse_apply_prompt("goodreads") == "g"


def test_parse_apply_prompt_tags_only():
    assert parse_apply_prompt("t") == "t"
    assert parse_apply_prompt("tags only") == "s"


def test_edit_plan_uses_proposed_values_and_updates_filename(tmp_path: Path, monkeypatch):
    m4b = _touch(tmp_path / "Current.m4b")
    plan = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title="Proposed title",
        desired_author="Proposed author",
        desired_album="Proposed title",
        desired_date="2020",
        desired_narrator="",
        desired_stem="Current",
        current=TagSnapshot(path=m4b),
    )
    answers = iter(["Edited title", "Edited author", "2021", "Narrator", "Edited"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    edit_plan(plan)

    assert plan.desired_title == "Edited title"
    assert plan.desired_album == "Edited title"
    assert plan.desired_author == "Edited author"
    assert plan.desired_date == "2021"
    assert plan.desired_narrator == "Narrator"
    assert plan.desired_stem == "Edited"
    assert plan.rename_m4b_to == tmp_path / "Edited.m4b"


def test_edit_filename_rejects_extension(tmp_path: Path):
    m4b = _touch(tmp_path / "Current.m4b")
    plan = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title="Book",
        desired_author="Author",
        desired_album="Book",
        desired_date="",
        desired_narrator="",
        desired_stem="Current",
        current=TagSnapshot(path=m4b),
    )

    assert _set_plan_filename(plan, "Edited.m4b") is False


def test_prompt_apply_exposes_cancel_for_manual_ol(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "c")
    plan = FixPlan(
        book_dir=Path("."),
        m4b=Path("book.m4b"),
        source=None,
        desired_title="Book",
        desired_author="Author",
        desired_album="Book",
        desired_date="",
        desired_narrator="",
        desired_stem="book",
        current=TagSnapshot(),
    )

    assert prompt_apply(plan, manual_ol_pending=True) == "c"


def test_prompt_apply_exposes_author_to_narrator_reassignment(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "r")
    plan = FixPlan(
        book_dir=Path("."),
        m4b=Path("book.m4b"),
        source=None,
        desired_title="Book",
        desired_author="Philippa Gregory",
        desired_album="Book",
        desired_date="",
        desired_narrator="",
        desired_stem="book",
        current=TagSnapshot(artist="Bianca Amato"),
    )

    assert prompt_apply(plan) == "r"
    assert _can_reassign_author_to_narrator(plan)


def test_prompt_apply_does_not_offer_reassignment_with_existing_narrator(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "r")
    plan = FixPlan(
        book_dir=Path("."),
        m4b=Path("book.m4b"),
        source=None,
        desired_title="Book",
        desired_author="Philippa Gregory",
        desired_album="Book",
        desired_date="",
        desired_narrator="",
        desired_stem="book",
        current=TagSnapshot(artist="Bianca Amato", composer="Existing narrator"),
    )

    assert not _can_reassign_author_to_narrator(plan)


def test_save_interactive_tags_only_suppresses_renames(tmp_path: Path, monkeypatch):
    import src.fix_metadata as module

    m4b = _touch(tmp_path / "Current.m4b")
    desc = _touch(tmp_path / "Current [128].txt")
    plan = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title="Book",
        desired_author="Author",
        desired_album="Book",
        desired_date="2020",
        desired_narrator="Narrator",
        desired_stem="Book",
        current=TagSnapshot(path=m4b),
        desc_txt=desc,
        rename_m4b_to=tmp_path / "Book.m4b",
        rename_desc_to=tmp_path / "Book [128].txt",
    )
    applied: list[FixPlan] = []
    monkeypatch.setattr(module, "apply_fix", lambda current_plan, **kwargs: applied.append(current_plan))
    monkeypatch.setattr(module, "_finish_status_line", lambda _final: None)
    monkeypatch.setattr(module, "divider", lambda: None)

    _save_interactive_tags_only(plan, cli=CliPaths(), index=0, total=1)

    assert len(applied) == 1
    assert applied[0].rename_m4b_to is None
    assert applied[0].rename_desc_to is None
    assert plan.rename_m4b_to == tmp_path / "Book.m4b"


def test_tags_only_cli_suppresses_renames(tmp_path: Path, monkeypatch):
    import src.fix_metadata as module

    plan = _main_manual_ol_plan(tmp_path)
    plan.rename_m4b_to = tmp_path / "Renamed.m4b"
    plan.rename_desc_to = tmp_path / "Renamed.txt"
    _stub_main_for_manual_ol(monkeypatch, tmp_path, plan)
    applied: list[FixPlan] = []
    monkeypatch.setattr(module, "apply_fix", lambda current_plan, **kwargs: applied.append(current_plan))

    assert main(["--tags-only", "--no-ol", str(tmp_path)]) == 0
    assert len(applied) == 1
    assert applied[0].rename_m4b_to is None
    assert applied[0].rename_desc_to is None
    assert plan.rename_m4b_to == tmp_path / "Renamed.m4b"


def test_interactive_tags_only_skips_rename_only_plans(tmp_path: Path, monkeypatch):
    import src.fix_metadata as module

    plan = _main_manual_ol_plan(tmp_path)
    plan.current = TagSnapshot(
        title="Book",
        artist="Author",
        album="Book",
        albumartist="Author",
        date="2020",
    )
    plan.rename_m4b_to = tmp_path / "Renamed.m4b"
    _stub_main_for_manual_ol(monkeypatch, tmp_path, plan)
    monkeypatch.setattr(
        module,
        "prompt_apply",
        lambda *args, **kwargs: pytest.fail("rename-only plan should be skipped"),
    )

    assert main(["-it", "--no-ol", str(tmp_path)]) == 0


def test_interactive_reassignment_updates_proposal_and_is_one_shot(
    tmp_path: Path, monkeypatch
):
    import src.fix_metadata as module

    plan = FixPlan(
        book_dir=tmp_path,
        m4b=_touch(tmp_path / "Book.m4b"),
        source=None,
        desired_title="Book",
        desired_author="Philippa Gregory",
        desired_album="Book",
        desired_date="2020",
        desired_narrator="",
        desired_stem="Book",
        current=TagSnapshot(title="Book", artist="Bianca Amato", date="2020"),
    )
    _stub_main_for_manual_ol(monkeypatch, tmp_path, plan)
    monkeypatch.setattr(module, "_attach_open_library", lambda *args, **kwargs: None)
    prompt_kwargs: list[bool] = []
    choices = iter(["r", "s"])

    def fake_prompt(_plan, **kwargs):
        prompt_kwargs.append(kwargs["allow_author_to_narrator"])
        return next(choices)

    monkeypatch.setattr(module, "prompt_apply", fake_prompt)

    assert main(["-i", "--no-ol", str(tmp_path)]) == 0
    assert plan.desired_narrator == "Bianca Amato"
    assert prompt_kwargs == [True, False]


def _main_manual_ol_plan(tmp_path: Path) -> FixPlan:
    m4b = _touch(tmp_path / "Book.m4b")
    return FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title="Book",
        desired_author="Author",
        desired_album="Book",
        desired_date="2020",
        desired_narrator="",
        desired_stem="Book",
        current=TagSnapshot(title="Book", date="2020", path=m4b),
    )


def _stub_main_for_manual_ol(monkeypatch, tmp_path: Path, plan: FixPlan):
    import src.fix_metadata as module

    monkeypatch.setattr(module, "resolve_cli_paths", lambda: CliPaths())
    monkeypatch.setattr(
        module, "resolve_target_paths", lambda _paths, _cli: [tmp_path]
    )
    monkeypatch.setattr(
        module, "iter_book_dirs", lambda _paths, recursive: [tmp_path]
    )
    monkeypatch.setattr(module, "plan_fix", lambda *args, **kwargs: plan)
    monkeypatch.setattr(module, "_apply_cleanup_filename", lambda *args: None)
    monkeypatch.setattr(module, "_print_planning_progress", lambda *args: None)
    monkeypatch.setattr(module, "_clear_planning_progress", lambda: None)
    monkeypatch.setattr(module, "print_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "print_ol_session_notice", lambda **kwargs: None)


def test_manual_ol_can_be_edited_before_confirmation(tmp_path: Path, monkeypatch):
    import src.fix_metadata as module

    plan = _main_manual_ol_plan(tmp_path)
    _stub_main_for_manual_ol(monkeypatch, tmp_path, plan)
    applied: list[FixPlan] = []

    def fake_attach(current_plan, **kwargs):
        if kwargs.get("ol_ref"):
            current_plan.ol_status = "forced"
            current_plan.ol_title = "Open Library title"
            current_plan.desired_title = "Open Library title"
            current_plan.desired_album = "Open Library title"

    monkeypatch.setattr(module, "_attach_open_library", fake_attach)
    monkeypatch.setattr(module, "prompt_ol_ref", lambda: "OL123W")
    monkeypatch.setattr(
        module, "edit_plan", lambda current_plan: setattr(current_plan, "desired_title", "Edited title")
    )
    monkeypatch.setattr(module, "apply_fix", lambda current_plan, **kwargs: applied.append(current_plan))
    choices = iter(["o", "e"])
    monkeypatch.setattr(module, "prompt_apply", lambda *args, **kwargs: next(choices))

    assert main(["-i", str(tmp_path)]) == 0
    assert len(applied) == 1
    assert applied[0].desired_title == "Edited title"


def test_manual_ol_cancel_restores_original_proposal(tmp_path: Path, monkeypatch):
    import src.fix_metadata as module

    plan = _main_manual_ol_plan(tmp_path)
    _stub_main_for_manual_ol(monkeypatch, tmp_path, plan)
    shown_titles: list[str] = []
    applied: list[FixPlan] = []

    def fake_attach(current_plan, **kwargs):
        if kwargs.get("ol_ref"):
            current_plan.ol_status = "forced"
            current_plan.ol_title = "Open Library title"
            current_plan.desired_title = "Open Library title"
            current_plan.desired_album = "Open Library title"

    monkeypatch.setattr(module, "_attach_open_library", fake_attach)
    monkeypatch.setattr(module, "prompt_ol_ref", lambda: "OL123W")
    monkeypatch.setattr(
        module,
        "print_plan",
        lambda current_plan, **kwargs: shown_titles.append(current_plan.desired_title),
    )
    choices = iter(["o", "c", "s"])
    monkeypatch.setattr(module, "prompt_apply", lambda *args, **kwargs: next(choices))
    monkeypatch.setattr(module, "apply_fix", lambda current_plan, **kwargs: applied.append(current_plan))

    assert main(["-i", str(tmp_path)]) == 0
    assert shown_titles == ["Book", "Open Library title", "Book"]
    assert applied == []


def test_edit_prompt_ctrl_c_propagates(monkeypatch):
    def raise_interrupt(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", raise_interrupt)

    with pytest.raises(KeyboardInterrupt):
        _prompt_edit_value("Title", "Proposed title")


def test_open_library_ref_prompt_ctrl_c_propagates(monkeypatch):
    def raise_interrupt(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", raise_interrupt)

    with pytest.raises(KeyboardInterrupt):
        prompt_ol_ref()


def test_goodreads_ref_prompt_ctrl_c_propagates(monkeypatch):
    def raise_interrupt(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", raise_interrupt)

    with pytest.raises(KeyboardInterrupt):
        prompt_goodreads_ref()


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


def test_apply_fix_does_not_create_missing_description(tmp_path: Path):
    m4b = _touch(tmp_path / "Children of Memory.m4b")
    plan = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title="Children of Memory",
        desired_author="Adrian Tchaikovsky",
        desired_album="Children of Memory",
        desired_date="2023",
        desired_narrator="",
        desired_stem="Children of Memory",
        current=TagSnapshot(
            title="Children of Memory",
            artist="Adrian Tchaikovsky",
            album="Children of Memory",
            albumartist="Adrian Tchaikovsky",
            date="2023",
            path=m4b,
        ),
    )

    apply_fix(plan, dry_run=False, quiet=True)

    assert list(tmp_path.glob("*.txt")) == []
