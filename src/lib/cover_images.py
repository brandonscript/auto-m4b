"""Cover image discovery helpers and normalization for embedding.

Audiobook containers (MP4 ``covr`` / ID3 ``APIC``) and many ffmpeg builds only
reliably accept JPEG/PNG cover payloads. Sidecar covers may be WebP, AVIF,
HEIC, TIFF, etc. — discover them, then convert to JPEG when embedding.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.lib.constants import IMAGE_EXTS

# Mutagen MP4Cover / APIC MIME types we can write without conversion.
_NATIVE_EMBED_EXTS = frozenset({".jpg", ".jpeg", ".png"})


def is_image_file(path: Path | str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def is_native_embed_cover(path: Path | str) -> bool:
    return Path(path).suffix.lower() in _NATIVE_EMBED_EXTS


def _register_optional_heif() -> None:
    """Register HEIC/HEIF opener when pillow-heif is installed (optional)."""
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass


def _pillow_to_jpeg(src: Path, dest: Path) -> None:
    from PIL import Image

    _register_optional_heif()
    with Image.open(src) as im:
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            rgb = background
        else:
            rgb = im.convert("RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        rgb.save(dest, format="JPEG", quality=92, optimize=True)


def _ffmpeg_to_jpeg(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-frames:v",
            "1",
            str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError(result.stderr.strip() or f"ffmpeg failed converting {src}")


def ensure_embeddable_cover(cover: Path, *, dest: Path | None = None) -> Path:
    """Return a JPEG/PNG path suitable for mutagen and ffmpeg cover embedding.

    Native ``.jpg`` / ``.jpeg`` / ``.png`` files are returned unchanged. Other
    formats are converted to JPEG via Pillow (preferred) with an ffmpeg fallback.
    """
    if not cover.is_file():
        raise FileNotFoundError(f"Cover art not found: {cover}")

    if is_native_embed_cover(cover):
        return cover

    out = dest or cover.with_name(f"{cover.stem}.embed.jpg")
    try:
        if out.exists() and out.stat().st_mtime >= cover.stat().st_mtime and out.stat().st_size > 0:
            return out
    except OSError:
        pass

    errors: list[str] = []
    try:
        _pillow_to_jpeg(cover, out)
        if out.is_file() and out.stat().st_size > 0:
            return out
        errors.append("Pillow produced an empty file")
    except Exception as e:
        errors.append(f"Pillow: {e}")

    try:
        _ffmpeg_to_jpeg(cover, out)
        if out.is_file() and out.stat().st_size > 0:
            return out
        errors.append("ffmpeg produced an empty file")
    except Exception as e:
        errors.append(f"ffmpeg: {e}")

    raise IOError(
        f"Could not convert cover art '{cover}' to JPEG for embedding "
        f"({'; '.join(errors)}). Install Pillow codecs or pillow-heif for HEIC."
    )
