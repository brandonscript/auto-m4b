"""Convert-path performance: OL caps, bookpeek gate, verify reuse."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from unittest.mock import PropertyMock, patch

import pytest

from src.lib.audiobook import Audiobook
from src.lib.metadata.providers import MetadataCandidate


def _ol_early_match(ol):
    from src.lib.metadata.ol_early import OlEarlyMatch
    return OlEarlyMatch(ol=ol, preferred_author=getattr(ol, "author", None), preferred_canonical=None)


def _make_ol_result(*, score=1.0, title="Map of Bones", author="James Rollins", date="2005", author_score=1.0):
    from unittest.mock import MagicMock

    r = MagicMock()
    r.__bool__ = lambda self: True
    r.has_match = True
    r.score = MagicMock(return_value=score)
    r.title = title
    r.author = author
    r.narrator = ""
    r.date = date
    r.key = "/works/OL1W"
    r.author_score = MagicMock(return_value=author_score)
    r.author_and_narrator_swapped = False
    return r


def _mock_ol_author(name: str):
    from unittest.mock import MagicMock

    a = MagicMock()
    a.has_match = True
    a.name = name
    a.work_count = 10
    a.score = MagicMock(return_value=2.0)
    return a


def test_bookpeek_skipped_when_provider_resolved_with_narrator(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    book = book_in_author_named_folder
    mock_id3_tags(
        (
            book.sample_audio1,
            {
                "title": "Map of Bones",
                "artist": "James Rollins",
                "album": "Map of Bones",
                "albumartist": "James Rollins",
                "composer": "Scott Brick",
            },
        ),
        (
            book.sample_audio2,
            {
                "title": "Map of Bones",
                "artist": "James Rollins",
                "album": "Map of Bones",
                "albumartist": "James Rollins",
                "composer": "Scott Brick",
            },
        ),
    )
    book.extract_path_info()
    book.fs_narrator = "Scott Brick"

    ol = _make_ol_result()
    with (
        patch("src.lib.metadata.ol_early.extract_ol_early", return_value=_ol_early_match(ol)) as ol_mock,
        patch("src.lib.id3_utils._goodreads_early_extraction", return_value=None),
        patch("src.lib.id3_utils._bookpeek_early_extraction") as bp_mock,
        patch("src.lib.metadata.bookpeek_provider.bookpeek_enabled", return_value=True),
    ):
        book.extract_metadata()

    bp_mock.assert_not_called()
    assert book._early_ol is ol
    assert book._early_resolved_by == "openlibrary"
    ol_mock.assert_called()


def test_bookpeek_online_false_when_narrator_missing(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    book = book_in_author_named_folder
    mock_id3_tags(
        (
            book.sample_audio1,
            {"title": "Map of Bones", "artist": "James Rollins", "album": "Map of Bones", "albumartist": "James Rollins"},
        ),
        (
            book.sample_audio2,
            {"title": "Map of Bones", "artist": "James Rollins", "album": "Map of Bones", "albumartist": "James Rollins"},
        ),
    )
    book.extract_path_info()
    book.fs_narrator = ""

    ol = _make_ol_result()
    bp = MetadataCandidate(
        provider="bookpeek",
        title="Map of Bones",
        author="James Rollins",
        narrator="Scott Brick",
        score=0.9,
        status="match",
    )
    with (
        patch("src.lib.metadata.ol_early.extract_ol_early", return_value=_ol_early_match(ol)),
        patch("src.lib.id3_utils._goodreads_early_extraction", return_value=None),
        patch("src.lib.id3_utils._bookpeek_early_extraction", return_value=bp) as bp_mock,
        patch("src.lib.metadata.bookpeek_provider.bookpeek_enabled", return_value=True),
    ):
        book.extract_metadata()

    bp_mock.assert_called_once()
    assert bp_mock.call_args.kwargs.get("online") is False
    assert book.narrator == "Scott Brick"


def test_verify_reuses_early_providers_without_network(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
    tmp_path: Path,
):
    from src.lib.id3_utils import verify_and_update_id3_tags

    book = book_in_author_named_folder
    mock_id3_tags(
        (
            book.sample_audio1,
            {"title": "Map of Bones", "artist": "James Rollins", "album": "Map of Bones", "albumartist": "James Rollins"},
        ),
    )
    book.extract_path_info()
    book.title = "Map of Bones"
    book.artist = "James Rollins"
    book.album = "Map of Bones"
    book.albumartist = "James Rollins"
    book.narrator = "Scott Brick"

    gr = MetadataCandidate(
        provider="goodreads",
        title="Map of Bones",
        author="James Rollins",
        year="2005",
        score=0.95,
        status="match",
    )
    book._early_ol = None
    book._early_gr = gr
    book._early_resolved_by = "goodreads"

    # Point build_file at a real copy of sample audio so tag read succeeds.
    build = tmp_path / "build.m4b"
    build.write_bytes(Path(book.sample_audio1).read_bytes())

    with (
        patch.object(type(book), "build_file", new_callable=PropertyMock, return_value=build),
        patch.object(type(book), "converted_file", new_callable=PropertyMock, return_value=build),
        patch("src.lib.id3_utils.lookup_metadata") as lookup_mock,
        patch("src.lib.id3_utils.open_library_lookup_title") as ol_title_mock,
        patch("src.lib.id3_utils.open_library_lookup_author") as ol_author_mock,
        patch("src.lib.id3_utils.write_id3_tags_mutagen"),
        patch("src.lib.id3_utils._read_m4b_tags_for_verify") as read_tags,
    ):
        read_tags.return_value = SimpleNamespace(
            id3_title="Map of Bones",
            id3_artist="James Rollins",
            id3_album="Map of Bones",
            id3_albumartist="James Rollins",
            id3_composer="Scott Brick",
            id3_date="2005",
            id3_comment="",
            id3_sortalbum="Map of Bones",
            has_id3_cover=True,
        )
        verify_and_update_id3_tags(book, in_dir="build")

    lookup_mock.assert_not_called()
    ol_title_mock.assert_not_called()
    ol_author_mock.assert_not_called()


def test_verify_skips_plan_fix_when_early_ol_still_matches(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
    tmp_path: Path,
):
    """Early OL reuse must not call plan_fix or re-hit GR/OL network."""
    from src.lib.config import cfg as real_cfg
    from src.lib.id3_utils import verify_and_update_id3_tags

    book = book_in_author_named_folder
    mock_id3_tags(
        (
            book.sample_audio1,
            {"title": "Map of Bones", "artist": "James Rollins", "album": "Map of Bones", "albumartist": "James Rollins"},
        ),
    )
    book.extract_path_info()
    book.title = "Map of Bones"
    book.artist = "James Rollins"
    book.album = "Map of Bones"
    book.albumartist = "James Rollins"
    book.narrator = "Scott Brick"
    book.date = "2005"

    ol = _make_ol_result()
    book._early_ol = ol
    book._early_gr = None
    book._early_resolved_by = "openlibrary"

    build = tmp_path / "build.m4b"
    build.write_bytes(Path(book.sample_audio1).read_bytes())

    with (
        patch.object(type(book), "build_file", new_callable=PropertyMock, return_value=build),
        patch.object(type(book), "converted_file", new_callable=PropertyMock, return_value=build),
        patch("src.lib.id3_utils.lookup_metadata") as lookup_mock,
        patch("src.lib.id3_utils.open_library_lookup_title") as ol_title_mock,
        patch("src.lib.id3_utils.open_library_lookup_author") as ol_author_mock,
        patch("src.lib.metadata.plan_fix") as plan_fix_mock,
        patch("src.lib.id3_utils.write_id3_tags_mutagen"),
        patch("src.lib.id3_utils._read_m4b_tags_for_verify") as read_tags,
        patch.object(
            type(real_cfg),
            "OPEN_LIBRARY_USER_AGENT",
            new_callable=PropertyMock,
            return_value="test-agent/1.0",
        ),
    ):
        read_tags.return_value = SimpleNamespace(
            id3_title="Map of Bones",
            id3_artist="James Rollins",
            id3_album="Map of Bones",
            id3_albumartist="James Rollins",
            id3_composer="Scott Brick",
            id3_date="2005",
            id3_comment="",
            id3_sortalbum="Map of Bones",
            has_id3_cover=True,
        )
        verify_and_update_id3_tags(book, in_dir="build")

    lookup_mock.assert_not_called()
    ol_title_mock.assert_not_called()
    ol_author_mock.assert_not_called()
    plan_fix_mock.assert_not_called()


def test_extract_skips_metadata_score_when_provider_resolved(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    book = book_in_author_named_folder
    mock_id3_tags(
        (
            book.sample_audio1,
            {
                "title": "Map of Bones",
                "artist": "James Rollins",
                "album": "Map of Bones",
                "albumartist": "James Rollins",
                "composer": "Scott Brick",
            },
        ),
        (
            book.sample_audio2,
            {
                "title": "Map of Bones",
                "artist": "James Rollins",
                "album": "Map of Bones",
                "albumartist": "James Rollins",
                "composer": "Scott Brick",
            },
        ),
    )
    book.extract_path_info()
    book.fs_narrator = "Scott Brick"

    ol = _make_ol_result()
    with (
        patch("src.lib.metadata.ol_early.extract_ol_early", return_value=_ol_early_match(ol)),
        patch("src.lib.id3_utils._goodreads_early_extraction", return_value=None),
        patch("src.lib.metadata.bookpeek_provider.bookpeek_enabled", return_value=False),
        patch("src.lib.id3_utils.MetadataScore") as score_mock,
    ):
        book.extract_metadata()

    score_mock.assert_not_called()
    assert book.narrator == "Scott Brick"


def test_gr_match_skips_ol_early(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    """When Goodreads resolves, do not call OL-early (GR-miss fallback only)."""
    book = book_in_author_named_folder
    mock_id3_tags(
        (
            book.sample_audio1,
            {"title": "Wrong", "artist": "Wrong", "album": "Wrong", "albumartist": "Wrong"},
        ),
        (
            book.sample_audio2,
            {"title": "Wrong", "artist": "Wrong", "album": "Wrong", "albumartist": "Wrong"},
        ),
    )
    book.extract_path_info()

    ol = _make_ol_result(title="OL Title", author="OL Author")
    gr = MetadataCandidate(
        provider="goodreads",
        title="GR Title",
        author="GR Author",
        year="2010",
        score=0.99,
        status="match",
    )
    with (
        patch("src.lib.metadata.ol_early.extract_ol_early", return_value=_ol_early_match(ol)) as ol_mock,
        patch("src.lib.id3_utils._goodreads_early_extraction", return_value=gr),
        patch("src.lib.metadata.bookpeek_provider.bookpeek_enabled", return_value=False),
    ):
        book.extract_metadata()

    ol_mock.assert_not_called()
    assert book.title == "GR Title"
    assert book.artist == "GR Author"
    assert book._early_resolved_by == "goodreads"
    assert book._early_gr is gr
    assert book._early_ol is None


def test_ol_early_runs_when_gr_misses(
    book_in_author_named_folder: Audiobook,
    mock_id3_tags: Callable[..., list[dict[str, str]]],
):
    book = book_in_author_named_folder
    mock_id3_tags(
        (
            book.sample_audio1,
            {"title": "Map of Bones", "artist": "James Rollins", "album": "Map of Bones", "albumartist": "James Rollins"},
        ),
        (
            book.sample_audio2,
            {"title": "Map of Bones", "artist": "James Rollins", "album": "Map of Bones", "albumartist": "James Rollins"},
        ),
    )
    book.extract_path_info()

    ol = _make_ol_result()
    with (
        patch("src.lib.metadata.ol_early.extract_ol_early", return_value=_ol_early_match(ol)) as ol_mock,
        patch("src.lib.id3_utils._goodreads_early_extraction", return_value=None),
        patch("src.lib.metadata.bookpeek_provider.bookpeek_enabled", return_value=False),
    ):
        book.extract_metadata()

    ol_mock.assert_called_once()
    assert book._early_resolved_by == "openlibrary"
    assert book._early_ol is ol


def test_map_parallel_preserves_order_and_serializes_when_small():
    from src.lib.converter.merge import _map_parallel

    assert _map_parallel(lambda x: x * 2, [1, 2, 3, 4], max_workers=4) == [2, 4, 6, 8]
    assert _map_parallel(lambda x: x + 1, [10], max_workers=8) == [11]
    assert _map_parallel(lambda x: x, [], max_workers=4) == []


def test_probe_threads_defaults_and_override(monkeypatch):
    from src.lib.config import cfg

    monkeypatch.setattr(cfg, "MAX_PROBE_THREADS", 0)
    cfg._env.pop("MAX_PROBE_THREADS", None)

    monkeypatch.setattr(cfg, "CPU_CORES", 32)
    assert cfg.probe_threads == 16  # capped

    monkeypatch.setattr(cfg, "CPU_CORES", 8)
    assert cfg.probe_threads == 8

    monkeypatch.setattr(cfg, "CPU_CORES", 2)
    assert cfg.probe_threads == 4  # floored

    monkeypatch.setattr(cfg, "MAX_PROBE_THREADS", 3)
    assert cfg.probe_threads == 3


def test_encode_cores_override_context():
    from src.lib.config import cfg
    from src.lib.converter.merge import reset_encode_cores_override, set_encode_cores_override

    token = set_encode_cores_override(2)
    try:
        assert cfg.encode_cores == 2
    finally:
        reset_encode_cores_override(token)
    assert cfg.encode_cores == max(1, int(cfg.CPU_CORES or 1))
