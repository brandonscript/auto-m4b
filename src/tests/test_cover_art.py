"""Cover art extraction — ffmpeg demux + mutagen covr/APIC fallback."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from src.lib.cover_images import ensure_embeddable_cover, is_image_file
from src.lib.fs_utils import find_cover_art_file
from src.lib.id3_utils import extract_cover_art
from src.tests.helpers.pytest_dumps import FIXTURES_ROOT


@pytest.fixture
def m4b_with_cover(tmp_path: Path) -> Path:
    src = FIXTURES_ROOT / "basic_with_cover__standalone_m4b.m4b"
    dst = tmp_path / "book.m4b"
    shutil.copy2(src, dst)
    return dst


def test_extract_cover_art_from_m4b(m4b_with_cover: Path):
    out = extract_cover_art(m4b_with_cover, save_to_file=True)
    assert isinstance(out, Path)
    assert out.is_file()
    assert out.stat().st_size > 1000
    assert out.suffix.lower() in {".jpg", ".jpeg", ".png"}


def test_extract_cover_art_mutagen_fallback_when_ffmpeg_fails(m4b_with_cover: Path):
    """Sea of Silver Light case: ffprobe sees attached_pic, but ffmpeg demux is empty."""

    def _ffmpeg_fails(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    with patch("src.lib.id3_utils.subprocess.check_output", side_effect=_ffmpeg_fails):
        data = extract_cover_art(m4b_with_cover, save_to_file=False)

    assert isinstance(data, bytes)
    assert len(data) > 1000


def test_extract_cover_art_mutagen_fallback_when_ffmpeg_writes_empty(m4b_with_cover: Path, tmp_path: Path):
    def _ffmpeg_empty(cmd, *args, **kwargs):
        # File-output form: last arg is the destination path
        if cmd and str(cmd[-1]).endswith((".jpg", ".png", ".webp")):
            Path(cmd[-1]).write_bytes(b"")
            return b""
        # image2pipe form
        return b""

    with patch("src.lib.id3_utils.subprocess.check_output", side_effect=_ffmpeg_empty):
        out = extract_cover_art(m4b_with_cover, save_to_file=True, filename="recovered")

    assert isinstance(out, Path)
    assert out.is_file()
    assert out.stat().st_size > 1000


def test_find_cover_art_file_matches_stem(tmp_path: Path):
    # Prefer cover.* by stem even when other larger images exist
    other = tmp_path / "artwork.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20000)
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"y" * 8000)

    found = find_cover_art_file(tmp_path)
    assert found == cover


def _write_rgb_cover(path: Path, fmt: str, size: tuple[int, int] = (320, 320)) -> Path:
    img = Image.new("RGB", size, color=(40, 120, 200))
    img.save(path, format=fmt)
    # find_cover_art_file rejects files under 7KB; pad compressed formats as needed.
    if path.stat().st_size < 7168:
        path.write_bytes(path.read_bytes() + b"\0" * (7168 - path.stat().st_size))
    return path


@pytest.mark.parametrize("name,fmt", [("cover.webp", "WEBP"), ("folder.avif", "AVIF"), ("Cover.JPEG", "JPEG")])
def test_find_cover_art_file_modern_and_case_insensitive(tmp_path: Path, name: str, fmt: str):
    cover = _write_rgb_cover(tmp_path / name, fmt)
    assert is_image_file(cover)
    found = find_cover_art_file(tmp_path)
    assert found == cover


@pytest.mark.parametrize("fmt,ext", [("WEBP", ".webp"), ("AVIF", ".avif"), ("PNG", ".png")])
def test_ensure_embeddable_cover_converts_modern_formats(tmp_path: Path, fmt: str, ext: str):
    src = tmp_path / f"cover{ext}"
    Image.new("RGB", (64, 64), color=(10, 20, 30)).save(src, format=fmt)
    out = ensure_embeddable_cover(src, dest=tmp_path / "out.jpg")
    assert out.suffix.lower() in {".jpg", ".jpeg", ".png"}
    assert out.is_file() and out.stat().st_size > 0
    # Round-trip: Pillow can open the embeddable result
    with Image.open(out) as im:
        assert im.size == (64, 64)
