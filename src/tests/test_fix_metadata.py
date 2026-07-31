"""Fast unit tests for fix_metadata helpers (no real media fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from unittest.mock import MagicMock

from src.fix_metadata import (
    CliPaths,
    FixPlan,
    SourceResolutionError,
    TagSnapshot,
    filesystem_extracted,
    folder_narrator_hint,
    folder_title_hint,
    iter_book_dirs,
    map_source_dir,
    minimalist_title,
    parse_apply_prompt,
    plan_fix,
    resolve_cli_paths,
    resolve_minimalist,
    resolve_source_dir,
    resolve_target_paths,
    source_common_filename,
    source_common_title,
    source_files_display,
    _apply_date_consensus,
    _apply_ol_fields_to_desired,
    _attach_open_library,
    _banner_fixing_clause,
    _banner_missing_clause,
    _format_mode_banner,
    _format_planning_progress,
    _id3_already_correct_style,
    _prop_equal,
    _stem_matches_book_title,
    _truth_props,
    _year_consensus,
)
from src.lib.parsers import swap_firstname_lastname
from src.lib.ol_lookup import (
    OL_LOW_CONFIDENCE_MIN,
    OL_MATCH_MIN,
    ol_match_band,
    parse_ol_ref,
)


def test_folder_title_hint_strips_series_narrator_year():
    assert folder_title_hint("Earthsea Cycle 05.3 - The Bones of the Earth [Wauters] (2001)") == (
        "The Bones of the Earth"
    )
    assert folder_title_hint("About A Poem [Downer] (2007)") == "About A Poem"
    assert folder_title_hint("The Searcher (2020)") == "The Searcher"
    assert folder_title_hint("[Collections] The Island of the Immortals [De Cuir] (1998)") == (
        "The Island of the Immortals"
    )


def test_folder_narrator_hint():
    assert folder_narrator_hint("Solitude [Pardee] (1994)") == "Pardee"
    assert folder_narrator_hint("The Diary of the Rose [AB] [Lefkow] (1976)") == "Lefkow"
    assert folder_narrator_hint("The Searcher (2020)") == ""


def test_stem_matches_book_title_colon_vs_dash():
    assert _stem_matches_book_title("The Searcher - A Novel", "The Searcher: A Novel") is True


def test_stem_matches_book_title_author_prefixed():
    assert (
        _stem_matches_book_title(
            "Tana French - The Searcher - A Novel",
            "The Searcher: A Novel",
            "Tana French",
        )
        is True
    )


def test_stem_matches_book_title_rejects_glued_source():
    assert _stem_matches_book_title("TheSearcherANovel_ep7", "The Searcher: A Novel") is False


def test_filesystem_extracted(tmp_path: Path):
    book = tmp_path / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    book.mkdir(parents=True)
    title, author, date, narrator = filesystem_extracted(book)
    # folder_title_hint keeps "Eon - …" after stripping the numbered series prefix
    assert title == "Eon - Dragoneye Reborn"
    assert author == "Alison Goodman"
    assert date == "2008"
    assert narrator == ""


def test_plan_fix_stores_fs_priors(tmp_path: Path, monkeypatch):
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    book = converted / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    arch = archive / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    _touch(book / "Eon Series.m4b", size=50)
    _touch(arch / "part1.mp3", size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.suffix == ".m4b":
            return TagSnapshot(title="Eon Series", artist="Greg Bear", date="2017", path=path)
        return TagSnapshot(title="Dragoneye Reborn", artist="Alison Goodman", date="2008", path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
    )
    assert plan is not None
    assert plan.fs_title == "Dragoneye Reborn"
    assert plan.fs_author == "Alison Goodman"
    assert plan.fs_date == "2008"
    assert plan.desired_title == plan.fs_title
    assert plan.current.title == "Eon Series"


def test_plan_fix_prefers_folder_year_over_id3_date(tmp_path: Path, monkeypatch):
    """Folder (YYYY) beats polluted converted id3 when source has no date."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    book = converted / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    arch = archive / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    _touch(book / "Eon Series.m4b", size=50)
    _touch(arch / "part1.mp3", size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.suffix == ".m4b":
            return TagSnapshot(title="Eon Series", artist="Greg Bear", date="2017", path=path)
        return TagSnapshot(title="Dragoneye Reborn", artist="Alison Goodman", date="", path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
    )
    assert plan is not None
    assert plan.fs_date == "2008"
    assert plan.desired_date == "2008"
    assert any("2017" in r and "2008" in r for r in plan.reasons)


def test_plan_fix_without_archive_when_source_not_required(tmp_path: Path, monkeypatch):
    """Interactive / -o path: plan from m4b + folder when archive source is missing."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    folder = "Lady Helen 03 - The Dark Days Deceit (2007)"
    book = converted / "Goodman, Alison" / folder
    # No archive counterpart
    archive.mkdir(parents=True, exist_ok=True)
    _touch(book / "The Dark Days Deceit.m4b", size=50)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        return TagSnapshot(
            title="The Dark Days Deceit",
            artist="Alison Goodman",
            date="2007",
            path=path,
        )

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")

    with pytest.raises(SourceResolutionError):
        plan_fix(
            book,
            cli=cli,
            scope_root=converted / "Goodman, Alison",
            require_source=True,
            lookup_ol=False,
        )

    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=False,
        lookup_ol=False,
    )
    assert plan is not None
    assert plan.source is None
    assert plan.desired_title == "The Dark Days Deceit"
    assert plan.desired_author == "Alison Goodman"


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


def test_last_first_conversion():
    assert swap_firstname_lastname("Le Guin, Ursula K.") == "Ursula K. Le Guin"
    assert swap_firstname_lastname("French, Tana") == "Tana French"
    assert swap_firstname_lastname("Ursula K. Le Guin") == "Ursula K. Le Guin"


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


def test_parse_ol_ref():
    assert parse_ol_ref("https://openlibrary.org/works/OL45804W") == ("works", "OL45804W")
    assert parse_ol_ref("/works/OL45804W") == ("works", "OL45804W")
    assert parse_ol_ref("OL45804W") == ("works", "OL45804W")
    assert parse_ol_ref("https://openlibrary.org/books/OL123M") == ("books", "OL123M")
    assert parse_ol_ref("OL123M") == ("books", "OL123M")
    assert parse_ol_ref("not-a-ref") is None
    assert parse_ol_ref("") is None


def test_resolve_minimalist_env_and_flags(monkeypatch):
    monkeypatch.setenv("CLI_MINIMALIST", "1")
    assert resolve_minimalist() is True
    assert resolve_minimalist(flag_off=True) is False

    monkeypatch.delenv("CLI_MINIMALIST", raising=False)
    assert resolve_minimalist() is False
    assert resolve_minimalist(flag_on=True) is True


def test_plan_fix_minimalist_dark_days_club(tmp_path: Path, monkeypatch):
    """Minimalist strips trilogy junk; ±1yr folder/id3 near-tie leaves id3 date alone."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    folder = "Lady Helen 01 - The Dark Days Club (2015)"
    book = converted / "Goodman, Alison" / folder
    arch = archive / "Goodman, Alison" / folder
    junk = "The Dark Days Club: The Lady Helen Trilogy, Book 1 (Unabridged)"
    _touch(book / "The Dark Days Club.m4b", size=50)
    _touch(arch / "part1.mp3", size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.suffix == ".m4b":
            return TagSnapshot(
                title="The Dark Days Club",
                artist="Alison Goodman",
                date="2016",
                path=path,
            )
        return TagSnapshot(title=junk, artist="Alison Goodman", date="2015", path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
        minimalist=True,
    )
    assert plan is not None
    assert plan.desired_title == "The Dark Days Club"
    assert plan.fs_date == "2015"
    assert plan.desired_date == "2016"  # near-tie: do not churn id3
    assert not any("2016" in r and "2015" in r for r in plan.reasons)
    stem_l = plan.desired_stem.casefold()
    assert "trilogy" not in stem_l
    assert "unabridged" not in stem_l
    assert "book" not in stem_l


def test_plan_fix_minimalist_never_renames_to_author(tmp_path: Path, monkeypatch):
    """Author-prefixed marketing archive stem must not become Alison Goodman.m4b."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    folder = "Lady Helen 01 - The Dark Days Club (2015)"
    book = converted / "Goodman, Alison" / folder
    arch = archive / "Goodman, Alison" / folder
    src_name = (
        "Alison Goodman - The Dark Days Club The Lady Helen Trilogy, "
        "Book 1 (Unabridged).mp3"
    )
    _touch(book / "The Dark Days Club.m4b", size=50)
    _touch(arch / src_name, size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.suffix == ".m4b":
            return TagSnapshot(
                title="The Dark Days Club",
                artist="Alison Goodman",
                date="2016",
                path=path,
            )
        return TagSnapshot(
            title="The Dark Days Club The Lady Helen Trilogy, Book 1 (Unabridged)",
            artist="Alison Goodman",
            date="2015",
            path=path,
        )

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
        minimalist=True,
    )
    assert plan is not None
    assert plan.desired_stem.casefold() != "alison goodman"
    assert plan.desired_stem == "The Dark Days Club"
    assert plan.rename_m4b_to is None
    stem_l = plan.desired_stem.casefold()
    assert "trilogy" not in stem_l
    assert "unabridged" not in stem_l
    assert "book" not in stem_l


def test_plan_fix_non_minimalist_keeps_full_source_stem(tmp_path: Path, monkeypatch):
    """Without minimalist, keep the full source filename (never author-only)."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    folder = "Lady Helen 01 - The Dark Days Club (2015)"
    book = converted / "Goodman, Alison" / folder
    arch = archive / "Goodman, Alison" / folder
    src_stem = (
        "Alison Goodman - The Dark Days Club The Lady Helen Trilogy, "
        "Book 1 (Unabridged)"
    )
    _touch(book / "The Dark Days Club.m4b", size=50)
    _touch(arch / f"{src_stem}.mp3", size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.suffix == ".m4b":
            return TagSnapshot(
                title="The Dark Days Club",
                artist="Alison Goodman",
                date="2016",
                path=path,
            )
        return TagSnapshot(
            title=src_stem,
            artist="Alison Goodman",
            date="2015",
            path=path,
        )

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
        minimalist=False,
    )
    assert plan is not None
    assert plan.desired_stem.casefold() != "alison goodman"
    assert "Dark Days Club" in plan.desired_stem
    assert "Alison Goodman" in plan.desired_stem
    assert "Trilogy" in plan.desired_stem or "trilogy" in plan.desired_stem.casefold()


def test_plan_fix_never_renames_to_author_even_if_gcs_is_author(
    tmp_path: Path, monkeypatch
):
    """If GCS/stem collapses to the author, keep the current m4b filename."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    folder = "Lady Helen 01 - The Dark Days Club (2015)"
    book = converted / "Goodman, Alison" / folder
    arch = archive / "Goodman, Alison" / folder
    _touch(book / "The Dark Days Club.m4b", size=50)
    _touch(arch / "part1.mp3", size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        return TagSnapshot(
            title="Alison Goodman",
            artist="Alison Goodman",
            date="2015",
            path=path,
        )

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    monkeypatch.setattr(
        "src.fix_metadata.source_common_filename",
        lambda *a, **k: "Alison Goodman",
    )
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
        minimalist=False,
    )
    assert plan is not None
    assert plan.desired_stem.casefold() != "alison goodman"
    assert plan.desired_stem == "The Dark Days Club"
    assert plan.rename_m4b_to is None


def test_plan_fix_minimalist_keeps_colon_not_folder_dash(tmp_path: Path, monkeypatch):
    """Folder dashes are not an id3 signal; keep Title: Subtitle colon form."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    folder = "Eon 01 - Eon - Dragoneye Reborn (2008)"
    book = converted / "Goodman, Alison" / folder
    arch = archive / "Goodman, Alison" / folder
    _touch(book / "Eon - Dragoneye Reborn.m4b", size=50)
    _touch(arch / "part1.mp3", size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.suffix == ".m4b":
            return TagSnapshot(
                title="Eon: Dragoneye Reborn",
                artist="Alison Goodman",
                date="2008",
                path=path,
            )
        return TagSnapshot(
            title="Dragoneye Reborn",
            artist="Alison Goodman",
            date="2008",
            path=path,
        )

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
        minimalist=True,
    )
    assert plan is not None
    assert plan.desired_title == "Eon: Dragoneye Reborn"
    assert " - " not in plan.desired_title


def test_attach_ol_dual_ol_lookup_stripped_fallback(tmp_path: Path, monkeypatch):
    """Full junk title misses; minimalist-stripped core matches."""
    junk = "The Dark Days Club: The Lady Helen Trilogy, Book 1 (Unabridged)"
    book = tmp_path / "Goodman, Alison" / "Lady Helen 01 - Other Book (2015)"
    book.mkdir(parents=True)
    m4b = book / "junk.m4b"
    m4b.touch()

    queries: list[str] = []
    match = MagicMock()
    match.title = "The Dark Days Club"
    match.author = "Alison Goodman"
    match.date = "2015"
    match.key = "/works/OL123W"
    match.url = "https://openlibrary.org/works/OL123W"
    match.score = MagicMock(return_value=0.95)
    match.has_match = True

    def fake_lookup(title, *a, **k):
        queries.append(title)
        if minimalist_title(title) == title.strip() and "Trilogy" not in title:
            return match
        return None

    monkeypatch.setenv("OPEN_LIBRARY_USER_AGENT", "test/1.0 (t@e.com)")
    monkeypatch.setattr("src.lib.ol_lookup.open_library_lookup_title", fake_lookup)
    monkeypatch.setattr(
        "src.lib.ol_lookup.ol_match_band",
        lambda cand, *a, **k: "match" if cand is match else "none",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._best_matching_edition_subtitle",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._get_open_library_user_agent",
        lambda: "test/1.0 (t@e.com)",
    )

    plan = FixPlan(
        book_dir=book,
        m4b=m4b,
        source=None,
        desired_title=junk,
        desired_author="Alison Goodman",
        desired_album=junk,
        desired_date="2015",
        desired_narrator="",
        desired_stem="junk",
        current=TagSnapshot(title=junk, artist="Alison Goodman", date="2015", path=m4b),
    )
    _attach_open_library(plan, apply_ol_tags=False)
    assert junk in queries
    assert "The Dark Days Club" in queries
    assert plan.ol_status == "match"
    assert plan.ol_title == "The Dark Days Club"


def _touch(path: Path, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


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


def test_archive_mirror_source(tmp_path: Path):
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    book = converted / "Author" / "My Book"
    arch_book = archive / "Author" / "My Book"
    _touch(book / "out.m4b", size=100)
    _touch(arch_book / "orig.mp3", size=200)

    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    src = resolve_source_dir(
        book,
        beside_source=None,
        cli=cli,
        scope_root=converted / "Author",
        source_root=None,
    )
    assert src == arch_book.resolve()


def test_missing_archive_raises(tmp_path: Path):
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    archive.mkdir()
    book = converted / "Author" / "My Book"
    _touch(book / "out.m4b")

    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    with pytest.raises(SourceResolutionError, match="no archive source"):
        resolve_source_dir(
            book,
            beside_source=None,
            cli=cli,
            scope_root=converted / "Author",
            source_root=None,
        )


def test_dash_s_match_and_missing(tmp_path: Path):
    converted = tmp_path / "converted"
    author = converted / "Author"
    book = author / "My Book"
    _touch(book / "out.m4b")

    originals = tmp_path / "originals"
    matched = originals / "My Book"
    _touch(matched / "orig.mp3")

    mapped = map_source_dir(book, originals, author)
    assert mapped == matched.resolve()

    empty = tmp_path / "empty_src"
    empty.mkdir()
    assert map_source_dir(book, empty, author) is None

    with pytest.raises(SourceResolutionError, match="no matching folder under -s"):
        resolve_source_dir(
            book,
            beside_source=None,
            cli=CliPaths(),
            scope_root=author,
            source_root=empty,
        )


def test_external_abs_without_beside_source_fails(tmp_path: Path):
    plex = tmp_path / "plex" / "Author" / "Book"
    _touch(plex / "book.m4b")
    cli = CliPaths(
        converted=(tmp_path / "converted").resolve(),
        archive=(tmp_path / "archive").resolve(),
        inbox=(tmp_path / "inbox").resolve(),
    )
    (tmp_path / "converted").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "inbox").mkdir()

    with pytest.raises(SourceResolutionError, match="outside converted"):
        resolve_source_dir(
            plex,
            beside_source=None,
            cli=cli,
            scope_root=plex,
            source_root=None,
        )


def test_plan_fix_uses_archive_source(tmp_path: Path):
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    book = converted / "French, Tana" / "The Searcher (2020)"
    arch = archive / "French, Tana" / "The Searcher (2020)"
    _touch(book / "The Searcher.m4b", size=50)
    # Minimal valid-ish empty file — mutagen may return empty tags; folder priors still apply.
    _touch(arch / "orig.mp3", size=80)

    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "French, Tana",
        require_source=True,
        lookup_ol=False,
    )
    assert plan is not None
    assert plan.desired_author == "Tana French"
    assert plan.source is not None
    assert "source from" in plan.reasons[0]


@pytest.mark.parametrize("minimalist", [True, False])
def test_plan_fix_keeps_searcher_dash_stem_not_glued_archive(
    tmp_path: Path, monkeypatch, minimalist: bool
):
    """Keep Title - Subtitle m4b; do not rename to glued archive stem."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    folder = "The Searcher (2020)"
    book = converted / "French, Tana" / folder
    arch = archive / "French, Tana" / folder
    _touch(book / "The Searcher - A Novel.m4b", size=50)
    _touch(arch / "TheSearcherANovel_ep7.m4a", size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        return TagSnapshot(
            title="The Searcher: A Novel",
            artist="Tana French",
            albumartist="Tana French",
            date="2020",
            path=path,
        )

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "French, Tana",
        require_source=True,
        lookup_ol=False,
        minimalist=minimalist,
    )
    assert plan is not None
    assert plan.rename_m4b_to is None
    assert plan.desired_stem == "The Searcher - A Novel"


def test_source_common_title_strips_parts(tmp_path: Path, monkeypatch):
    titles = {
        "Elizabeth I, Part 1.m4b": "Elizabeth I, Part 1",
        "Elizabeth I, Part 2.m4b": "Elizabeth I, Part 2",
        "Elizabeth I, Part 3.m4b": "Elizabeth I, Part 3",
    }
    for name in titles:
        _touch(tmp_path / name)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        return TagSnapshot(title=titles[path.name], path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    title, reason = source_common_title(tmp_path)
    assert title == "Elizabeth I"
    assert "stripped" in reason


def test_source_common_title_from_numbered_filenames(tmp_path: Path, monkeypatch):
    for name in ("01 - Book Name.mp3", "02 - Book Name.mp3"):
        _touch(tmp_path / name)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        return TagSnapshot(path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    title, reason = source_common_title(tmp_path)
    assert "Book Name" in title
    assert reason


def test_source_common_title_single_part_still_strips(tmp_path: Path, monkeypatch):
    _touch(tmp_path / "only.m4b")

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        return TagSnapshot(title="War and Peace, Part 1", path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    title, _reason = source_common_title(tmp_path)
    assert title == "War and Peace"


def test_source_common_filename_strips_parts(tmp_path: Path):
    for name in (
        "Alison Goodman - Dragoneye Reborn, Part 1.mp3",
        "Alison Goodman - Dragoneye Reborn, Part 2.mp3",
        "Alison Goodman - Dragoneye Reborn, Part 3.mp3",
    ):
        _touch(tmp_path / name)

    stem = source_common_filename(tmp_path)
    assert stem == "Alison Goodman - Dragoneye Reborn"


def test_source_files_display_strips_parts(tmp_path: Path):
    for name in (
        "Alison Goodman - Dragoneye Reborn, Part 1.mp3",
        "Alison Goodman - Dragoneye Reborn, Part 2.mp3",
        "Alison Goodman - Dragoneye Reborn, Part 3.mp3",
    ):
        _touch(tmp_path / name)

    assert source_files_display(tmp_path) == "Alison Goodman - Dragoneye Reborn.mp3"


def test_plan_fix_rename_stem_from_filename_gcs(tmp_path: Path, monkeypatch):
    """Keep title-matching m4b stem; do not rename to author-prefixed filename GCS."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    book = converted / "Goodman, Alison" / "Dragoneye Reborn (2008)"
    arch = archive / "Goodman, Alison" / "Dragoneye Reborn (2008)"
    _touch(book / "Dragoneye Reborn.m4b", size=50)
    part_files = {
        "Alison Goodman - Dragoneye Reborn, Part 1.mp3": "Dragoneye Reborn",
        "Alison Goodman - Dragoneye Reborn, Part 2.mp3": "Dragoneye Reborn",
        "Alison Goodman - Dragoneye Reborn, Part 3.mp3": "Dragoneye Reborn",
    }
    for name in part_files:
        _touch(arch / name, size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.name in part_files:
            return TagSnapshot(title=part_files[path.name], artist="Alison Goodman", path=path)
        if path.suffix == ".m4b":
            return TagSnapshot(title="Dragoneye Reborn", artist="", path=path)
        return TagSnapshot(path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
    )
    assert plan is not None
    assert plan.desired_title == "Dragoneye Reborn"
    assert plan.desired_stem == "Dragoneye Reborn"
    assert plan.rename_m4b_to is None


def test_plan_fix_rename_stem_from_filename_gcs_when_junk(tmp_path: Path, monkeypatch):
    """Junk m4b stem still renames to author-prefixed filename GCS."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    book = converted / "Goodman, Alison" / "Dragoneye Reborn (2008)"
    arch = archive / "Goodman, Alison" / "Dragoneye Reborn (2008)"
    _touch(book / "Book.m4b", size=50)
    part_files = {
        "Alison Goodman - Dragoneye Reborn, Part 1.mp3": "Dragoneye Reborn",
        "Alison Goodman - Dragoneye Reborn, Part 2.mp3": "Dragoneye Reborn",
        "Alison Goodman - Dragoneye Reborn, Part 3.mp3": "Dragoneye Reborn",
    }
    for name in part_files:
        _touch(arch / name, size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.name in part_files:
            return TagSnapshot(title=part_files[path.name], artist="Alison Goodman", path=path)
        if path.suffix == ".m4b":
            return TagSnapshot(title="Dragoneye Reborn", artist="", path=path)
        return TagSnapshot(path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
    )
    assert plan is not None
    assert plan.desired_title == "Dragoneye Reborn"
    assert plan.desired_stem == "Alison Goodman - Dragoneye Reborn"
    assert plan.rename_m4b_to is not None
    assert plan.rename_m4b_to.name == "Alison Goodman - Dragoneye Reborn.m4b"


def test_plan_fix_prefers_common_title_over_part(tmp_path: Path, monkeypatch):
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    book = converted / "George, Margaret" / "Elizabeth I (2011)"
    arch = archive / "George, Margaret" / "Elizabeth I (2011)"
    _touch(book / "Elizabeth I.m4b", size=50)
    part_files = {
        "Elizabeth I, Part 1.m4b": "Elizabeth I, Part 1",
        "Elizabeth I, Part 2.m4b": "Elizabeth I, Part 2",
        "Elizabeth I, Part 3.m4b": "Elizabeth I, Part 3",
    }
    for name in part_files:
        _touch(arch / name, size=80)

    real_from_file = TagSnapshot.from_file

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.name in part_files:
            return TagSnapshot(title=part_files[path.name], album="Elizabeth I", path=path)
        if path.name.endswith(".m4b") and "Part" not in path.name:
            # Converted m4b currently has wrong part title — should be fixed to Elizabeth I
            return TagSnapshot(title="Elizabeth I, Part 1", artist="Wrong", path=path)
        return real_from_file(path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "George, Margaret",
        require_source=True,
        lookup_ol=False,
    )
    assert plan is not None
    assert plan.desired_title == "Elizabeth I"
    assert plan.desired_author == "Margaret George"


def test_ol_match_band():
    assert OL_MATCH_MIN == 0.5
    assert OL_LOW_CONFIDENCE_MIN == 0.15
    assert ol_match_band(None) == "skipped"

    m = MagicMock()
    m.has_match = False
    assert ol_match_band(m) == "none"

    m.has_match = True
    m.score = MagicMock(return_value=0.9)
    assert ol_match_band(m) == "match"

    m.score = MagicMock(return_value=0.21)
    assert ol_match_band(m) == "low_confidence"

    m.score = MagicMock(return_value=0.05)
    assert ol_match_band(m) == "none"


def test_apply_ol_fields_to_desired(tmp_path: Path):
    m4b = tmp_path / "book.m4b"
    m4b.touch()
    plan = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title="Old Title",
        desired_author="Old Author",
        desired_album="Old Title",
        desired_date="1999",
        desired_narrator="",
        desired_stem="Old Title",
        current=TagSnapshot(title="Old Title", artist="Old Author", date="1999", path=m4b),
        ol_title="Dragoneye Reborn",
        ol_author="Alison Goodman",
        ol_year="2008",
        ol_key="/works/OL123W",
    )
    _apply_ol_fields_to_desired(plan)
    assert plan.desired_title == "Dragoneye Reborn"
    assert plan.desired_album == "Dragoneye Reborn"
    assert plan.desired_author == "Alison Goodman"
    assert plan.desired_date == "2008"
    assert plan.desired_stem == "Old Title"  # rename stem unchanged
    assert any("Open Library" in r for r in plan.reasons)


def test_attach_ol_enriches_title_with_edition_subtitle(tmp_path: Path, monkeypatch):
    """Edition subtitle attested in folder → id3 proposal uses work title + colon."""
    book = tmp_path / "Goodman, Alison" / "Eon 02 - Eona - The Last Dragoneye (2011)"
    book.mkdir(parents=True)
    m4b = book / "Eona.m4b"
    m4b.touch()

    ol = MagicMock()
    ol.title = "Eona"
    ol.author = "Alison Goodman"
    ol.date = "2011"
    ol.key = "/works/OL16116601W"
    ol.url = "https://openlibrary.org/works/OL16116601W"
    ol.score = MagicMock(return_value=0.95)
    ol.has_match = True

    monkeypatch.setenv("OPEN_LIBRARY_USER_AGENT", "test/1.0 (t@e.com)")
    # Patch ol_lookup symbols: _attach_open_library imports them locally at call time.
    monkeypatch.setattr(
        "src.lib.ol_lookup.open_library_lookup_title",
        lambda *a, **k: ol,
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.ol_match_band",
        lambda *a, **k: "match",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._fetch_work_editions",
        lambda *a, **k: [{"title": "Eona", "subtitle": "the last Dragoneye"}],
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._best_matching_edition_subtitle",
        lambda *a, **k: "the last Dragoneye",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._get_open_library_user_agent",
        lambda: "test/1.0 (t@e.com)",
    )

    plan = FixPlan(
        book_dir=book,
        m4b=m4b,
        source=None,
        desired_title="Eona",
        desired_author="Alison Goodman",
        desired_album="Eona",
        desired_date="2011",
        desired_narrator="",
        desired_stem="Eona",
        current=TagSnapshot(title="Eon Series", artist="Greg Bear", date="2017", path=m4b),
        fs_title="Eona",
        fs_files="Eona.m4b",
    )
    _attach_open_library(plan, apply_ol_tags=False)
    assert plan.desired_title == "Eona: The Last Dragoneye"
    assert plan.ol_title == "Eona: The Last Dragoneye"
    assert plan.desired_stem == "Eona"  # rename stem unchanged


def test_attach_ol_eon_uses_work_title_not_marketing_base(tmp_path: Path, monkeypatch):
    """Do not stack Dragoneye Reborn + Rise…; join work title Eon + attested subtitle."""
    book = tmp_path / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    book.mkdir(parents=True)
    m4b = book / "Dragoneye Reborn.m4b"
    m4b.touch()

    ol = MagicMock()
    ol.title = "Eon"
    ol.author = "Alison Goodman"
    ol.date = "1998"
    ol.key = "/works/OL29358192W"
    ol.url = "https://openlibrary.org/works/OL29358192W"
    ol.score = MagicMock(return_value=0.9)
    ol.has_match = True

    monkeypatch.setenv("OPEN_LIBRARY_USER_AGENT", "test/1.0 (t@e.com)")
    monkeypatch.setattr("src.lib.ol_lookup.open_library_lookup_title", lambda *a, **k: ol)
    monkeypatch.setattr("src.lib.ol_lookup.ol_match_band", lambda *a, **k: "match")
    monkeypatch.setattr(
        "src.lib.ol_lookup._fetch_work_editions",
        lambda *a, **k: [
            {"title": "Eon", "subtitle": "Dragoneye Reborn"},
            {"title": "Eon", "subtitle": "Rise of the Dragoneye"},
        ],
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._best_matching_edition_subtitle",
        lambda *a, **k: "Dragoneye Reborn",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._get_open_library_user_agent",
        lambda: "test/1.0 (t@e.com)",
    )

    plan = FixPlan(
        book_dir=book,
        m4b=m4b,
        source=None,
        desired_title="Dragoneye Reborn",
        desired_author="Alison Goodman",
        desired_album="Dragoneye Reborn",
        desired_date="2008",
        desired_narrator="",
        desired_stem="Dragoneye Reborn",
        current=TagSnapshot(
            title="Dragoneye Reborn", artist="Alison Goodman", date="2008", path=m4b
        ),
        fs_title="Dragoneye Reborn",
        fs_files="Dragoneye Reborn.m4b",
    )
    _attach_open_library(plan, apply_ol_tags=False)
    assert plan.desired_title == "Eon: Dragoneye Reborn"
    assert plan.ol_title == "Eon: Dragoneye Reborn"
    assert "Rise" not in plan.desired_title
    assert plan.desired_stem == "Dragoneye Reborn"


def test_attach_ol_keeps_eon_over_au_work_title(tmp_path: Path, monkeypatch):
    """OL work title may be AU alternate; keep local/US edition form Eon: Dragoneye Reborn."""
    book = tmp_path / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    book.mkdir(parents=True)
    m4b = book / "Dragoneye Reborn.m4b"
    m4b.touch()

    ol = MagicMock()
    ol.title = "The Two Pearls of Wisdom"
    ol.author = "Alison Goodman"
    ol.date = "2008"
    ol.key = "/works/OL5954753W"
    ol.url = "https://openlibrary.org/works/OL5954753W"
    ol.score = MagicMock(return_value=1.0)
    ol.has_match = True

    editions = [
        {"title": "The Two Pearls of Wisdom"},
        {"title": "Eon", "subtitle": "Dragoneye Reborn"},
        {"title": "Eon: Dragoneye Reborn"},
    ]

    monkeypatch.setenv("OPEN_LIBRARY_USER_AGENT", "test/1.0 (t@e.com)")
    monkeypatch.setattr("src.lib.ol_lookup.open_library_lookup_title", lambda *a, **k: ol)
    monkeypatch.setattr("src.lib.ol_lookup.ol_match_band", lambda *a, **k: "match")
    monkeypatch.setattr(
        "src.lib.ol_lookup._fetch_work_editions",
        lambda *a, **k: editions,
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._best_matching_edition_subtitle",
        lambda *a, **k: "Dragoneye Reborn",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._get_open_library_user_agent",
        lambda: "test/1.0 (t@e.com)",
    )

    plan = FixPlan(
        book_dir=book,
        m4b=m4b,
        source=None,
        desired_title="Eon: Dragoneye Reborn",
        desired_author="Alison Goodman",
        desired_album="Eon: Dragoneye Reborn",
        desired_date="2008",
        desired_narrator="",
        desired_stem="Eon - Dragoneye Reborn",
        current=TagSnapshot(
            title="Eon: Dragoneye Reborn",
            artist="Alison Goodman",
            date="2008",
            path=m4b,
        ),
        fs_title="Eon: Dragoneye Reborn",
        fs_files="Dragoneye Reborn.m4b",
    )
    _attach_open_library(plan, apply_ol_tags=False)
    assert plan.desired_title == "Eon: Dragoneye Reborn"
    assert "Two Pearls" not in plan.desired_title
    assert plan.desired_stem == "Eon - Dragoneye Reborn"


def test_attach_ol_enriches_with_local_edition_base_not_au_work(
    tmp_path: Path, monkeypatch
):
    """Incomplete local title still enriches using Eon base, not AU work title."""
    book = tmp_path / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    book.mkdir(parents=True)
    m4b = book / "Dragoneye Reborn.m4b"
    m4b.touch()

    ol = MagicMock()
    ol.title = "The Two Pearls of Wisdom"
    ol.author = "Alison Goodman"
    ol.date = "2008"
    ol.key = "/works/OL5954753W"
    ol.url = "https://openlibrary.org/works/OL5954753W"
    ol.score = MagicMock(return_value=1.0)
    ol.has_match = True

    editions = [
        {"title": "The Two Pearls of Wisdom"},
        {"title": "Eon", "subtitle": "Dragoneye Reborn"},
    ]

    monkeypatch.setenv("OPEN_LIBRARY_USER_AGENT", "test/1.0 (t@e.com)")
    monkeypatch.setattr("src.lib.ol_lookup.open_library_lookup_title", lambda *a, **k: ol)
    monkeypatch.setattr("src.lib.ol_lookup.ol_match_band", lambda *a, **k: "match")
    monkeypatch.setattr(
        "src.lib.ol_lookup._fetch_work_editions",
        lambda *a, **k: editions,
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._get_open_library_user_agent",
        lambda: "test/1.0 (t@e.com)",
    )

    plan = FixPlan(
        book_dir=book,
        m4b=m4b,
        source=None,
        desired_title="Dragoneye Reborn",
        desired_author="Alison Goodman",
        desired_album="Dragoneye Reborn",
        desired_date="2008",
        desired_narrator="",
        desired_stem="Dragoneye Reborn",
        current=TagSnapshot(
            title="Dragoneye Reborn", artist="Alison Goodman", date="2008", path=m4b
        ),
        fs_title="Dragoneye Reborn",
        fs_files="Dragoneye Reborn.m4b",
    )
    _attach_open_library(plan, apply_ol_tags=False)
    assert plan.desired_title == "Eon: Dragoneye Reborn"
    assert "Two Pearls" not in plan.desired_title


def test_format_planning_progress():
    assert _format_planning_progress(12, 133, "The Left Hand of Darkness (1969)") == (
        "Planning 12/133 · The Left Hand of Darkness (1969)"
    )


def test_plan_fix_defers_ol_then_attach(tmp_path: Path, monkeypatch):
    """Interactive defer: plan_fix(lookup_ol=False), then _attach_open_library later."""
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    book = converted / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    arch = archive / "Goodman, Alison" / "Eon 01 - Eon - Dragoneye Reborn (2008)"
    _touch(book / "Eon Series.m4b", size=50)
    _touch(arch / "part1.mp3", size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.suffix == ".m4b":
            return TagSnapshot(title="Eon Series", artist="Greg Bear", date="2017", path=path)
        return TagSnapshot(title="Dragoneye Reborn", artist="Alison Goodman", date="2008", path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    cli = CliPaths(converted=converted.resolve(), archive=archive.resolve(), inbox=tmp_path / "inbox")
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
    )
    assert plan is not None
    assert plan.needs_work
    assert not plan.ol_status
    assert not plan.ol_title

    ol = MagicMock()
    ol.title = "Eon"
    ol.author = "Alison Goodman"
    ol.date = "2008"
    ol.key = "/works/OL29358192W"
    ol.url = "https://openlibrary.org/works/OL29358192W"
    ol.score = MagicMock(return_value=0.9)
    ol.has_match = True

    monkeypatch.setenv("OPEN_LIBRARY_USER_AGENT", "test/1.0 (t@e.com)")
    monkeypatch.setattr("src.lib.ol_lookup.open_library_lookup_title", lambda *a, **k: ol)
    monkeypatch.setattr("src.lib.ol_lookup.ol_match_band", lambda *a, **k: "match")
    monkeypatch.setattr(
        "src.lib.ol_lookup._fetch_work_editions",
        lambda *a, **k: [{"title": "Eon", "subtitle": "Dragoneye Reborn"}],
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._best_matching_edition_subtitle",
        lambda *a, **k: "Dragoneye Reborn",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup._get_open_library_user_agent",
        lambda: "test/1.0 (t@e.com)",
    )

    _attach_open_library(plan, apply_ol_tags=False)
    assert plan.ol_status == "match"
    assert plan.desired_title == "Eon: Dragoneye Reborn"
    assert plan.needs_work


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


def test_needs_work_respects_matching_desc_and_date_consensus(tmp_path: Path):
    """needs_work stays False when tags+desc already match; dirty desc or pre-consensus date churn."""
    m4b = tmp_path / "The Memoirs of Cleopatra.m4b"
    m4b.touch()
    title = "The Memoirs of Cleopatra"
    author = "Margaret George"

    # Case 1: tags match desired, no rename, desc already has correct Book title / Author.
    desc_ok = tmp_path / "ok.txt"
    desc_ok.write_text(f"Book title: {title}\nAuthor: {author}\n", encoding="utf-8")
    plan_ok = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title=title,
        desired_author=author,
        desired_album=title,
        desired_date="1997",
        desired_narrator="",
        desired_stem=title,
        current=TagSnapshot(
            title=title,
            artist=author,
            album=title,
            albumartist=author,
            date="1997",
            path=m4b,
        ),
        desc_txt=desc_ok,
    )
    assert plan_ok.needs_desc_rewrite is False
    assert plan_ok.needs_work is False

    # Case 2: same tags, but desc has the wrong title → rewrite + work needed.
    desc_bad = tmp_path / "bad.txt"
    desc_bad.write_text(f"Book title: Wrong Title\nAuthor: {author}\n", encoding="utf-8")
    plan_bad = FixPlan(
        book_dir=tmp_path,
        m4b=m4b,
        source=None,
        desired_title=title,
        desired_author=author,
        desired_album=title,
        desired_date="1997",
        desired_narrator="",
        desired_stem=title,
        current=TagSnapshot(
            title=title,
            artist=author,
            album=title,
            albumartist=author,
            date="1997",
            path=m4b,
        ),
        desc_txt=desc_bad,
    )
    assert plan_bad.needs_desc_rewrite is True
    assert plan_bad.needs_work is True

    # Case 3 (Cleopatra): folder prior 2007, then id3+OL consensus → 1997; tags+desc already good.
    desc_cleo = tmp_path / "cleo.txt"
    desc_cleo.write_text(f"Book title: {title}\nAuthor: {author}\n", encoding="utf-8")
    plan_cleo = FixPlan(
        book_dir=tmp_path / "The Memoirs of Cleopatra (2007)",
        m4b=m4b,
        source=None,
        desired_title=title,
        desired_author=author,
        desired_album=title,
        desired_date="2007",
        desired_narrator="",
        desired_stem=title,
        current=TagSnapshot(
            title=title,
            artist=author,
            album=title,
            albumartist=author,
            date="1997",
            path=m4b,
        ),
        desc_txt=desc_cleo,
        fs_date="2007",
        ol_status="match",
        ol_year="1997",
    )
    assert plan_cleo.needs_work is True  # date mismatch before consensus
    _apply_date_consensus(plan_cleo)
    assert plan_cleo.desired_date == "1997"
    assert plan_cleo.needs_desc_rewrite is False
    assert plan_cleo.needs_work is False


def test_year_consensus_two_of_three():
    assert _year_consensus("2007", "1997", "1997") == "1997"
    assert _year_consensus("2008", "2017", "2008") == "2008"
    assert _year_consensus("2008", "2008", "2008") == "2008"
    assert _year_consensus("2008", "2017", "2010") is None
    assert _year_consensus("2008", "", "2008") == "2008"
    assert _year_consensus("2008", "2017", "") is None


def test_apply_date_consensus_id3_ol_over_folder(tmp_path: Path):
    """Cleopatra case: folder 2007 outlier loses to id3+OL 1997."""
    m4b = tmp_path / "The Memoirs of Cleopatra.m4b"
    m4b.touch()
    plan = FixPlan(
        book_dir=tmp_path / "The Memoirs of Cleopatra (2007)",
        m4b=m4b,
        source=None,
        desired_title="The Memoirs of Cleopatra",
        desired_author="Margaret George",
        desired_album="The Memoirs of Cleopatra",
        desired_date="2007",  # local folder prior before consensus
        desired_narrator="",
        desired_stem="The Memoirs of Cleopatra",
        current=TagSnapshot(
            title="The Memoirs of Cleopatra",
            artist="Margaret George",
            date="1997",
            path=m4b,
        ),
        fs_date="2007",
        ol_status="match",
        ol_year="1997",
    )
    _apply_date_consensus(plan)
    assert plan.desired_date == "1997"
    assert any("consensus" in r for r in plan.reasons)
    # OL agrees with desired → would color mint; FS disagrees
    assert _prop_equal(plan.ol_year, _truth_props(plan)["date"], is_date=True)
    assert not _prop_equal(plan.fs_date, _truth_props(plan)["date"], is_date=True)


def test_apply_date_consensus_skips_when_no_majority(tmp_path: Path):
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
    _apply_date_consensus(plan)
    assert plan.desired_date == "2008"
