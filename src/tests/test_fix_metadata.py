"""Fast unit tests for fix_metadata helpers (no real media fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.fix_metadata import (
    CliPaths,
    SourceResolutionError,
    TagSnapshot,
    folder_narrator_hint,
    folder_title_hint,
    iter_book_dirs,
    map_source_dir,
    parse_apply_prompt,
    plan_fix,
    resolve_cli_paths,
    resolve_source_dir,
    resolve_target_paths,
    source_common_title,
    _last_first_to_first_last,
)
from src.lib.ol_lookup import parse_ol_ref


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


def test_last_first_conversion():
    assert _last_first_to_first_last("Le Guin, Ursula K.") == "Ursula K. Le Guin"
    assert _last_first_to_first_last("French, Tana") == "Tana French"
    assert _last_first_to_first_last("Ursula K. Le Guin") == "Ursula K. Le Guin"


def test_parse_apply_prompt():
    assert parse_apply_prompt("") == "n"
    assert parse_apply_prompt("y") == "y"
    assert parse_apply_prompt("Yes") == "y"
    assert parse_apply_prompt("n") == "n"
    assert parse_apply_prompt("skip") == "n"
    assert parse_apply_prompt("a") == "a"
    assert parse_apply_prompt("all") == "a"
    assert parse_apply_prompt("o") == "o"
    assert parse_apply_prompt("ol") == "o"
    assert parse_apply_prompt("q") == "q"
    assert parse_apply_prompt("quit") == "q"
    assert parse_apply_prompt("maybe") == "n"


def test_parse_ol_ref():
    assert parse_ol_ref("https://openlibrary.org/works/OL45804W") == ("works", "OL45804W")
    assert parse_ol_ref("/works/OL45804W") == ("works", "OL45804W")
    assert parse_ol_ref("OL45804W") == ("works", "OL45804W")
    assert parse_ol_ref("https://openlibrary.org/books/OL123M") == ("books", "OL123M")
    assert parse_ol_ref("OL123M") == ("books", "OL123M")
    assert parse_ol_ref("not-a-ref") is None
    assert parse_ol_ref("") is None


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
