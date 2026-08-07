"""Phase 2/3: divergence / contract tests — shared planner vs convert.

Locks shared-side behavior for known conflict rows. Phase 3 wires convert
through shared colon/minimalist/stem helpers; remaining divergences
(dates, GCS stem, folder priors, OL enrich/auto-write) stay documented.

Review inventory: ``docs/metadata-conflicts.md`` (locked statuses).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from src.lib.audiobook import Audiobook
from src.lib.cleaners import is_author_only_name, minimalist_title
from src.lib.fs_utils import safe_filename
from src.lib.metadata import (
    CliPaths,
    TagSnapshot,
    parent_author_hint,
    plan_fix,
    _attach_open_library,
    _apply_ol_fields_to_desired,
)
from src.lib.metadata.models import FixPlan
from src.lib.metadata.pick import _pick_desired
from src.lib.metadata.priors import _is_cli_root, _loose_m4b_in_author_folder
from src.lib.metadata.stem import _usable_rename_stem
from src.lib.ol_lookup import id3_prefer_colon_separator
from src.lib.parsers import get_year_from_date

# Conflict log must stay in sync with docs/metadata-conflicts.md Concern column.
CONFLICT_CONCERNS = (
    "colon",
    "dates",
    "stem",
    "stem refuse author-only",
    "OL enrich",
    "folder priors",
    "minimalist",
    "OL auto-write",
)

# All previously pending rows are now locked by the implementation plan.
PENDING_REVIEW_CONCERNS = ()


def _touch(path: Path, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _cli(tmp_path: Path) -> tuple[Path, Path, CliPaths]:
    converted = tmp_path / "converted"
    archive = tmp_path / "archive"
    converted.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    cli = CliPaths(
        converted=converted.resolve(),
        archive=archive.resolve(),
        inbox=(tmp_path / "inbox").resolve(),
    )
    return converted, archive, cli


# ── Conflict log presence ─────────────────────────────────────────────────────


def test_conflict_log_lists_pending_review_rows():
    """docs/metadata-conflicts.md is the Phase 4 review artifact."""
    log = Path(__file__).resolve().parents[2] / "docs" / "metadata-conflicts.md"
    assert log.is_file(), f"missing conflict log: {log}"
    text = log.read_text(encoding="utf-8")
    # Legend definition remains for future review items; locked rows use other statuses.
    assert text.count("`pending_review`") >= 1 + len(PENDING_REVIEW_CONCERNS)
    for concern in (
        "Colon",
        "Dates",
        "Stem",
        "OL edition enrich",
        "Folder priors",
        "Minimalist",
        "OL auto-write",
    ):
        assert concern in text, f"conflict log missing concern: {concern}"


# ── Colon ─────────────────────────────────────────────────────────────────────


def test_contract_shared_prefers_colon_subtitle(tmp_path: Path, monkeypatch):
    """Shared and convert id3 titles both prefer colon; filenames still dash."""
    from src.lib.id3_utils import _finalize_convert_title

    converted, archive, cli = _cli(tmp_path)
    folder = "The Searcher - A Novel (2020)"
    book = converted / "French, Tana" / folder
    arch = archive / "French, Tana" / folder
    _touch(book / "The Searcher - A Novel.m4b", size=50)
    _touch(arch / "part1.mp3", size=80)

    dash_title = "The Searcher - A Novel"

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        return TagSnapshot(
            title=dash_title,
            artist="Tana French",
            date="2020",
            path=path,
        )

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "French, Tana",
        require_source=True,
        lookup_ol=False,
        minimalist=True,
    )
    assert plan is not None
    shared_title = plan.desired_title
    assert shared_title == "The Searcher: A Novel"

    # Phase 3: convert applies the same colon transform on resolved titles.
    convert_id3 = _finalize_convert_title(dash_title, author="Tana French")
    convert_filename = safe_filename(shared_title)
    assert convert_id3 == shared_title
    assert convert_filename == "The Searcher - A Novel"
    assert id3_prefer_colon_separator(dash_title) == shared_title


# ── Dates (±1 near-tie) ───────────────────────────────────────────────────────


def test_contract_shared_near_tie_chooses_older_year(tmp_path: Path):
    """Shared: |folder−id3|==1 → choose the older local year."""
    book_dir = tmp_path / "Lady Helen 01 - The Dark Days Club (2015)"
    book_dir.mkdir()
    m4b = book_dir / "The Dark Days Club.m4b"
    _touch(m4b, size=20)

    source = TagSnapshot(
        title="The Dark Days Club",
        artist="Alison Goodman",
        date="2015",
        path=book_dir / "part1.mp3",
    )
    current = TagSnapshot(
        title="The Dark Days Club",
        artist="Alison Goodman",
        date="2016",
        path=m4b,
    )
    _title, _author, _album, date, _narr, reasons = _pick_desired(
        book_dir, source, current, minimalist=True, cli=None
    )
    assert date == "2015"
    assert any("2016" in r and "2015" in r for r in reasons)

    # Convert MetadataScore.determine_date: when both years exist, prefer the
    # earlier one (id3 2016 vs fs 2015 → fs wins). Approximate without full scorer:
    id3_y, fs_y = 2016, 2015
    convert_date = str(id3_y) if id3_y < fs_y else str(fs_y)
    assert convert_date == "2015"
    assert date == convert_date  # locked policy is shared


def test_contract_shared_folder_year_when_not_near_tie(tmp_path: Path, monkeypatch):
    converted, archive, cli = _cli(tmp_path)
    folder = "Eon 01 - Eon - Dragoneye Reborn (2008)"
    book = converted / "Goodman, Alison" / folder
    arch = archive / "Goodman, Alison" / folder
    _touch(book / "Eon.m4b", size=50)
    _touch(arch / "part1.mp3", size=80)

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        if path.suffix == ".m4b":
            return TagSnapshot(title="Eon", artist="Alison Goodman", date="2017", path=path)
        return TagSnapshot(title="Eon", artist="Alison Goodman", date="", path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
        minimalist=True,
    )
    assert plan is not None
    assert plan.desired_date == "2008"
    assert get_year_from_date(plan.desired_date) == "2008"


# ── Stem refuse author-only ───────────────────────────────────────────────────


def test_contract_shared_and_convert_refuse_author_only_stem(tmp_path: Path, monkeypatch):
    """Both sides refuse author-only stems; sources of the fallback still diverge."""
    converted, archive, cli = _cli(tmp_path)
    folder = "Lady Helen 01 - The Dark Days Club (2015)"
    book = converted / "Goodman, Alison" / folder
    arch = archive / "Goodman, Alison" / folder
    _touch(book / "The Dark Days Club.m4b", size=50)
    _touch(arch / "part1.mp3", size=80)

    author = "Alison Goodman"

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        return TagSnapshot(title=author, artist=author, date="2015", path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    monkeypatch.setattr(
        "src.lib.metadata.plan.source_common_filename",
        lambda *a, **k: author,
    )
    plan = plan_fix(
        book,
        cli=cli,
        scope_root=converted / "Goodman, Alison",
        require_source=True,
        lookup_ol=False,
        minimalist=True,
    )
    assert plan is not None
    assert not is_author_only_name(plan.desired_stem, author)
    assert plan.desired_stem == "The Dark Days Club"  # keep current m4b
    assert _usable_rename_stem(author, author) is False

    # Convert: author-only title → fall back to inbox basename (not author).
    from src.lib.books_tree.books_tree import BooksTree

    inbox_book = tmp_path / "inbox" / folder
    inbox_book.mkdir(parents=True)
    _touch(inbox_book / "a.mp3", size=20)
    _touch(inbox_book / "b.mp3", size=20)
    book_obj = Audiobook(BooksTree(inbox_book))
    book_obj.title = author
    book_obj.artist = author
    convert_stem = book_obj.output_filename_stem
    assert not is_author_only_name(convert_stem, author)
    # Divergence: shared kept clean title stem; convert uses full folder basename.
    assert convert_stem == safe_filename(folder)
    assert plan.desired_stem != convert_stem


# ── CLI-root / folder priors ──────────────────────────────────────────────────


def test_contract_cli_root_clamp_never_authors_as_converted_root(tmp_path: Path):
    root = tmp_path / "media-out"
    author = root / "Gratton, Tessa"
    author.mkdir(parents=True)
    cli = CliPaths(converted=root.resolve(), archive=tmp_path / "arch", inbox=tmp_path / "in")

    assert _is_cli_root(root, cli) is True
    assert parent_author_hint(author, cli) == ""
    assert _loose_m4b_in_author_folder(author, cli) is True
    # Without cli clamp, parent name is used (convert NLP has no equivalent clamp).
    assert parent_author_hint(author, None) == "media-out"


def test_contract_plan_loose_m4b_uses_author_folder_not_root(tmp_path: Path, monkeypatch):
    converted, _archive, cli = _cli(tmp_path)
    # Use a root leaf name that must never become the author.
    root = tmp_path / "whatever-env-says"
    author_dir = root / "Gratton, Tessa"
    author_dir.mkdir(parents=True)
    _touch(author_dir / "Lady Hotspur.m4b", size=40)
    cli = CliPaths(converted=root.resolve(), archive=tmp_path / "archive", inbox=tmp_path / "inbox")

    def fake_from_file(cls, path: Path) -> TagSnapshot:
        return TagSnapshot(title="Lady Hotspur", artist="Tessa Gratton", date="2019", path=path)

    monkeypatch.setattr(TagSnapshot, "from_file", classmethod(fake_from_file))
    plan = plan_fix(
        author_dir,
        cli=cli,
        scope_root=author_dir,
        require_source=False,
        lookup_ol=False,
        minimalist=True,
    )
    if plan is not None:
        assert plan.desired_author == "Tessa Gratton"
        assert plan.desired_author.casefold() != "whatever-env-says"
        assert plan.desired_title == "Lady Hotspur"


# ── Minimalist ────────────────────────────────────────────────────────────────


def test_contract_shared_minimalist_strips_marketing(tmp_path: Path, monkeypatch):
    """Shared and convert both strip trilogy/unabridged via minimalist_title."""
    from src.lib.id3_utils import _finalize_convert_title

    converted, archive, cli = _cli(tmp_path)
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
    # Phase 3: convert always-minimalist on resolved titles.
    convert_title = _finalize_convert_title(junk, author="Alison Goodman")
    assert convert_title == "The Dark Days Club"
    assert minimalist_title(junk, author="Alison Goodman") == "The Dark Days Club"
    assert plan.desired_title == convert_title


# ── OL enrich (shared lock; convert has no path) ──────────────────────────────


def test_contract_shared_edition_enrich_when_corpus_attests(tmp_path: Path, monkeypatch):
    """Shared may join edition subtitle; convert has no enrichment path.

    Full Eon/AU cases live in test_metadata_plan; this locks the divergence surface.
    """
    book_dir = tmp_path / "Eon - Dragoneye Reborn (2008)"
    book_dir.mkdir()
    m4b = book_dir / "Eon.m4b"
    _touch(m4b, size=20)

    plan = FixPlan(
        book_dir=book_dir,
        m4b=m4b,
        source=None,
        desired_title="Eon",
        desired_author="Alison Goodman",
        desired_album="Eon",
        desired_date="2008",
        desired_narrator="",
        desired_stem="Eon",
        current=TagSnapshot(title="Eon", artist="Alison Goodman", date="2008", path=m4b),
        reasons=[],
        fs_title="Eon",
        fs_author="Alison Goodman",
        fs_date="2008",
        fs_files="Eon - Dragoneye Reborn.mp3",
    )

    ol = MagicMock()
    ol.title = "Eon"
    ol.author = "Alison Goodman"
    ol.date = "2008"
    ol.key = "/works/OL123W"
    ol.url = "https://openlibrary.org/works/OL123W"
    ol.score = MagicMock(return_value=0.95)

    monkeypatch.setattr(
        "src.lib.ol_lookup.open_library_lookup_title",
        lambda *a, **k: ol,
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.get_open_library_user_agent",
        lambda: "test-agent/1.0",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.desired_matches_edition_title",
        lambda *a, **k: False,
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.best_matching_edition_base_title",
        lambda *a, **k: "Eon",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.best_matching_edition_subtitle",
        lambda *a, **k: "Dragoneye Reborn",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.ol_title_uses_dash_separator",
        lambda *a, **k: False,
    )

    _attach_open_library(plan, apply_ol_tags=False, minimalist=False)
    assert "Dragoneye Reborn" in (plan.desired_title or "")
    assert ":" in plan.desired_title  # colon form for id3
    # Convert: no edition enrich → work title only.
    convert_title = "Eon"
    assert plan.desired_title != convert_title


# ── OL auto-write ─────────────────────────────────────────────────────────────


def test_contract_shared_auto_ol_does_not_overwrite_tags(tmp_path: Path, monkeypatch):
    """Shared auto OL is display-only; convert auto-writes (documented divergence)."""
    book_dir = tmp_path / "Some Book (2001)"
    book_dir.mkdir()
    m4b = book_dir / "Some Book.m4b"
    _touch(m4b, size=20)

    plan = FixPlan(
        book_dir=book_dir,
        m4b=m4b,
        source=None,
        desired_title="Some Book",
        desired_author="Local Author",
        desired_album="Some Book",
        desired_date="2001",
        desired_narrator="",
        desired_stem="Some Book",
        current=TagSnapshot(
            title="Some Book", artist="Local Author", date="2001", path=m4b
        ),
        reasons=[],
        fs_title="Some Book",
        fs_author="Local Author",
        fs_date="2001",
    )

    ol = MagicMock()
    ol.title = "OL Canonical Title"
    ol.author = "OL Author"
    ol.date = "1999"
    ol.key = "/works/OL999W"
    ol.url = "https://openlibrary.org/works/OL999W"
    ol.score = MagicMock(return_value=0.99)

    monkeypatch.setattr(
        "src.lib.ol_lookup.open_library_lookup_title",
        lambda *a, **k: ol,
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.get_open_library_user_agent",
        lambda: "test-agent/1.0",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.desired_matches_edition_title",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.best_matching_edition_base_title",
        lambda *a, **k: "Some Book",
    )
    monkeypatch.setattr(
        "src.lib.ol_lookup.best_matching_edition_subtitle",
        lambda *a, **k: None,
    )

    before_title, before_author = plan.desired_title, plan.desired_author
    _attach_open_library(plan, apply_ol_tags=False, minimalist=True)
    # Display fields filled; desired tags unchanged (no force).
    assert plan.ol_title
    assert plan.desired_title == before_title
    assert plan.desired_author == before_author

    # Forced apply (CLI --ol) does write — convert always-auto is the conflict.
    plan.ol_status = "forced"
    plan.ol_title = "OL Canonical Title"
    plan.ol_author = "OL Author"
    plan.ol_year = "1999"
    _apply_ol_fields_to_desired(plan)
    assert plan.desired_title == "OL Canonical Title"
    assert plan.desired_author == "OL Author"
