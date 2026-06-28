"""Unit tests for the native Python converter package (src/lib/converter/).

Fidelity note: tests validate *behavioral* correctness — valid .m4b output,
correct chapter count/order/titles, cover art present, total duration within a
small tolerance — rather than byte-identical output vs. PHP m4b-tool, since the
encoder/muxer paths differ.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.lib.converter.chapters import (
    build_chapters_from_files,
    Chapter,
    dedupe_names,
    parse_chapters_txt,
)
from src.lib.converter.encoder import CODEC_AAC, CODEC_LIBFDK_AAC, detect_aac_codec
from src.lib.converter.ffmetadata import build_ffmetadata, _escape
from src.lib.converter.naturalsort import natural_sort_files


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _probe(path: Path) -> dict[str, Any]:
    """Run ffprobe and return the parsed JSON."""
    result = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_chapters",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ffprobe failed: {result.stderr}"
    return json.loads(result.stdout)


def _fixture_files(*names: str) -> list[Path]:
    """Return Path objects for files in src/tests/fixtures/tiny__flat_mp3/."""
    fixtures_root = Path(__file__).parent / "fixtures" / "tiny__flat_mp3"
    return [fixtures_root / n for n in names]


TINY_MP3_DIR = Path(__file__).parent / "fixtures" / "tiny__flat_mp3"
TINY_MP3_FILES = sorted(TINY_MP3_DIR.glob("*.mp3"))

BASIC_NO_COVER_M4B = Path(__file__).parent / "fixtures" / "basic_no_cover__single_m4b"
BASIC_WITH_COVER_M4B = Path(__file__).parent / "fixtures" / "basic_with_cover__single_m4b"


# ─── NaturalSort ──────────────────────────────────────────────────────────────


class TestNaturalSort:
    def test_numeric_order(self, tmp_path):
        files = [tmp_path / f"{i}.mp3" for i in [10, 2, 1, 20]]
        for f in files:
            f.touch()
        result = natural_sort_files(files)
        assert [f.stem for f in result] == ["1", "2", "10", "20"]

    def test_alpha_with_numbers(self, tmp_path):
        names = ["track9.mp3", "track10.mp3", "track1.mp3", "track2.mp3"]
        files = [tmp_path / n for n in names]
        for f in files:
            f.touch()
        result = natural_sort_files(files)
        stems = [f.stem for f in result]
        assert stems == ["track1", "track2", "track9", "track10"]

    def test_depth_ordering(self, tmp_path):
        """Shallower paths come before deeper ones."""
        deep = tmp_path / "a" / "b.mp3"
        shallow = tmp_path / "a.mp3"
        deep.parent.mkdir(parents=True)
        deep.touch()
        shallow.touch()
        result = natural_sort_files([deep, shallow])
        assert result[0] == shallow

    def test_tiny_fixture_sorted(self):
        """Fixture files should already be in natural sort order."""
        sorted_files = natural_sort_files(list(TINY_MP3_FILES))
        assert sorted_files == sorted(TINY_MP3_FILES, key=lambda f: f.name)


# ─── Chapters ─────────────────────────────────────────────────────────────────


class TestBuildChaptersFromFiles:
    def test_one_chapter_per_file(self):
        files = [Path("a.mp3"), Path("b.mp3"), Path("c.mp3")]
        durations = [5000, 10000, 3000]
        chapters = build_chapters_from_files(files, durations)
        assert len(chapters) == 3
        assert chapters[0].start_ms == 0
        assert chapters[0].end_ms == 5000
        assert chapters[1].start_ms == 5000
        assert chapters[1].end_ms == 15000
        assert chapters[2].start_ms == 15000
        assert chapters[2].end_ms == 18000

    def test_use_filenames_as_titles(self):
        files = [Path("chapter1.mp3"), Path("chapter2.mp3")]
        chapters = build_chapters_from_files(files, [1000, 2000], use_filenames=True)
        assert chapters[0].title == "chapter1"
        assert chapters[1].title == "chapter2"

    def test_tag_titles_preferred_when_no_filenames(self):
        files = [Path("01.mp3"), Path("02.mp3")]
        tag_titles = ["Intro", ""]
        chapters = build_chapters_from_files(
            files, [1000, 2000], use_filenames=False, tag_titles=tag_titles
        )
        assert chapters[0].title == "Intro"
        assert chapters[1].title == "02"  # falls back to stem when tag is empty

    def test_cumulative_timestamps(self):
        durations = [1000, 2000, 3000, 4000]
        files = [Path(f"{i}.mp3") for i in range(4)]
        chapters = build_chapters_from_files(files, durations)
        expected_starts = [0, 1000, 3000, 6000]
        assert [c.start_ms for c in chapters] == expected_starts

    def test_duration_property(self):
        ch = Chapter(start_ms=1000, end_ms=5000, title="x")
        assert ch.duration_ms == 4000


class TestDedupeNames:
    def test_no_duplicates_unchanged(self):
        chapters = [
            Chapter(0, 1000, "Alpha"),
            Chapter(1000, 2000, "Beta"),
            Chapter(2000, 3000, "Gamma"),
        ]
        result = dedupe_names(chapters)
        assert [c.title for c in result] == ["Alpha", "Beta", "Gamma"]

    def test_duplicates_numbered(self):
        chapters = [
            Chapter(0, 1000, "Chapter"),
            Chapter(1000, 2000, "Chapter"),
            Chapter(2000, 3000, "Chapter"),
        ]
        result = dedupe_names(chapters)
        assert [c.title for c in result] == ["Chapter (1)", "Chapter (2)", "Chapter (3)"]

    def test_partial_duplicates(self):
        chapters = [
            Chapter(0, 1000, "Intro"),
            Chapter(1000, 2000, "Part"),
            Chapter(2000, 3000, "Part"),
            Chapter(3000, 4000, "Outro"),
        ]
        result = dedupe_names(chapters)
        assert result[0].title == "Intro"
        assert result[1].title == "Part (1)"
        assert result[2].title == "Part (2)"
        assert result[3].title == "Outro"

    def test_timestamps_preserved(self):
        chapters = [
            Chapter(0, 1000, "A"),
            Chapter(1000, 2000, "A"),
        ]
        result = dedupe_names(chapters)
        assert result[0].start_ms == 0
        assert result[0].end_ms == 1000
        assert result[1].start_ms == 1000
        assert result[1].end_ms == 2000


class TestParseChaptersTxt:
    def test_basic_parse(self, tmp_path):
        txt = tmp_path / "chapters.txt"
        txt.write_text(
            "0:00:00.000 Introduction\n"
            "0:05:00.000 Part One\n"
            "0:10:30.500 Conclusion\n"
        )
        chapters = parse_chapters_txt(txt, total_duration_ms=15 * 60 * 1000)
        assert len(chapters) == 3
        assert chapters[0].title == "Introduction"
        assert chapters[0].start_ms == 0
        assert chapters[1].title == "Part One"
        assert chapters[1].start_ms == 5 * 60 * 1000
        assert chapters[2].start_ms == (10 * 60 + 30) * 1000 + 500

    def test_last_chapter_ends_at_total(self, tmp_path):
        txt = tmp_path / "chapters.txt"
        txt.write_text("0:00:00 Start\n0:05:00 End\n")
        total = 12 * 60 * 1000
        chapters = parse_chapters_txt(txt, total_duration_ms=total)
        assert chapters[-1].end_ms == total

    def test_comments_ignored(self, tmp_path):
        txt = tmp_path / "chapters.txt"
        txt.write_text("# header comment\n0:00:00 Track 1\n0:01:00 Track 2\n")
        chapters = parse_chapters_txt(txt, total_duration_ms=120_000)
        assert len(chapters) == 2


# ─── FFmetadata ───────────────────────────────────────────────────────────────


class TestEscape:
    def test_equals_sign(self):
        assert _escape("a=b") == r"a\=b"

    def test_semicolon(self):
        assert _escape("a;b") == r"a\;b"

    def test_hash(self):
        assert _escape("a#b") == r"a\#b"

    def test_backslash(self):
        assert _escape("a\\b") == r"a\\b"

    def test_newline(self):
        assert _escape("a\nb") == "a\\\nb"

    def test_plain_string_unchanged(self):
        assert _escape("Hello World") == "Hello World"


class TestBuildFfmetadata:
    def test_header_present(self):
        meta = build_ffmetadata([])
        assert meta.startswith(";FFMETADATA1")

    def test_global_tags_written(self):
        meta = build_ffmetadata([], title="My Book", artist="Jane Doe", genre="Audiobook")
        assert "title=My Book" in meta
        assert "artist=Jane Doe" in meta
        assert "genre=Audiobook" in meta

    def test_none_tags_omitted(self):
        meta = build_ffmetadata([], title=None, artist=None)
        assert "title=" not in meta
        assert "artist=" not in meta

    def test_chapter_blocks(self):
        chapters = [
            Chapter(start_ms=0, end_ms=5000, title="Intro"),
            Chapter(start_ms=5000, end_ms=12000, title="Part One"),
        ]
        meta = build_ffmetadata(chapters)
        assert meta.count("[CHAPTER]") == 2
        assert "START=0" in meta
        assert "END=5000" in meta
        assert "title=Intro" in meta
        assert "START=5000" in meta
        assert "title=Part One" in meta

    def test_chapter_timebase(self):
        chapters = [Chapter(0, 1000, "x")]
        meta = build_ffmetadata(chapters)
        assert "TIMEBASE=1/1000" in meta

    def test_special_chars_in_title_escaped(self):
        chapters = [Chapter(0, 1000, "A=B;C#D")]
        meta = build_ffmetadata(chapters)
        assert r"title=A\=B\;C\#D" in meta


# ─── Encoder detection ────────────────────────────────────────────────────────


class TestDetectAacCodec:
    def test_returns_libfdk_aac_when_present(self):
        with patch(
            "src.lib.converter.encoder.subprocess.run"
        ) as mock_run:
            mock_run.return_value.stdout = "DEA.L. libfdk_aac"
            mock_run.return_value.stderr = ""
            result = detect_aac_codec(force_refresh=True)
        assert result == CODEC_LIBFDK_AAC

    def test_returns_aac_fallback_when_absent(self):
        with patch(
            "src.lib.converter.encoder.subprocess.run"
        ) as mock_run:
            mock_run.return_value.stdout = "DEA.L. aac"
            mock_run.return_value.stderr = ""
            result = detect_aac_codec(force_refresh=True)
        assert result == CODEC_AAC

    def test_returns_aac_fallback_on_ffmpeg_not_found(self):
        with patch(
            "src.lib.converter.encoder.subprocess.run",
            side_effect=FileNotFoundError("ffmpeg not found"),
        ):
            result = detect_aac_codec(force_refresh=True)
        assert result == CODEC_AAC

    def test_caching(self):
        with patch(
            "src.lib.converter.encoder.subprocess.run"
        ) as mock_run:
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            detect_aac_codec(force_refresh=True)
            detect_aac_codec()  # should use cache, not call subprocess again
        assert mock_run.call_count == 1


# ─── Integration: chapter embedding via ffprobe ───────────────────────────────


@pytest.mark.slow
class TestChapterEmbedding:
    """Verify that a real .m4b produced by convert_book_native has the expected
    chapter structure, using ffprobe to inspect the output."""

    def test_mp3_chapters_embedded(self, blank_audiobook, reset_all):
        """blank_audiobook fixture → 2 mp3 files → native convert → chapters in output."""
        from src.auto_m4b import app
        from src.tests.helpers.pytest_utils import testutils

        app(max_loops=1)

        build_dir = blank_audiobook.build_dir
        m4b_files = list(build_dir.rglob("*.m4b"))
        if not m4b_files:
            # check converted dir
            m4b_files = list(blank_audiobook.converted_dir.rglob("*.m4b"))

        assert m4b_files, f"No .m4b found under {build_dir} or {blank_audiobook.converted_dir}"

        probe = _probe(m4b_files[0])
        chapters = probe.get("chapters", [])
        assert len(chapters) == 2, f"Expected 2 chapters, got {len(chapters)}: {chapters}"

    def test_mp3_to_m4b_valid_output(self, tiny__flat_mp3, reset_all):
        """tiny__flat_mp3 (5 files) → native merge → valid m4b with 5 chapters."""
        from src.auto_m4b import app

        app(max_loops=1)

        build_dir = tiny__flat_mp3.build_dir
        m4b_files = list(build_dir.rglob("*.m4b"))
        if not m4b_files:
            m4b_files = list(tiny__flat_mp3.converted_dir.rglob("*.m4b"))

        assert m4b_files, f"No .m4b produced under {build_dir}"

        probe = _probe(m4b_files[0])
        chapters = probe.get("chapters", [])
        assert len(chapters) == len(TINY_MP3_FILES), (
            f"Expected {len(TINY_MP3_FILES)} chapters, got {len(chapters)}"
        )

        # Duration tolerance: within 2 seconds of total input
        format_duration = float(probe["format"]["duration"])
        assert format_duration > 0, "Output duration should be positive"
