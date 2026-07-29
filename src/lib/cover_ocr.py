"""Optional cover-art OCR helpers (Tesseract, no LLM).

Used as a boost/veto signal for Open Library early extraction when
``COVER_OCR=1`` and tesseract/pytesseract/Pillow are available. Never required
for a successful convert — missing deps or covers yield empty text.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from src.lib.term import print_debug

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook

_MIN_IMAGE_PX = 200
_AUTHOR_PARTIAL_MIN = 70
_TITLE_TOKEN_MIN = 0.55


def cover_ocr_available() -> bool:
    """True when COVER_OCR is enabled and tesseract + Pillow import cleanly."""
    from src.lib.config import cfg

    if not getattr(cfg, "COVER_OCR", False):
        return False
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def _preprocess_image(img: "Image.Image") -> "Image.Image":  # type: ignore[name-defined]
    """Grayscale + mild contrast; skip tiny images by returning None via caller."""
    from PIL import ImageEnhance, ImageOps

    gray = ImageOps.grayscale(img)
    return ImageEnhance.Contrast(gray).enhance(1.4)


def ocr_image_bytes(data: bytes) -> str:
    """Run Tesseract on raw image bytes; return cleaned lowercase-ish text."""
    if not data:
        return ""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    try:
        img = Image.open(io.BytesIO(data))
    except Exception as e:
        print_debug(f"cover OCR: could not open image bytes: {e}")
        return ""

    if min(img.size) < _MIN_IMAGE_PX:
        return ""

    try:
        processed = _preprocess_image(img)
        text = pytesseract.image_to_string(processed) or ""
    except Exception as e:
        print_debug(f"cover OCR: tesseract failed: {e}")
        return ""

    return re.sub(r"\s+", " ", text).strip()


def ocr_image_path(path: Path) -> str:
    """OCR a cover/folder image file on disk."""
    if not path or not path.is_file():
        return ""
    try:
        return ocr_image_bytes(path.read_bytes())
    except OSError as e:
        print_debug(f"cover OCR: could not read {path}: {e}")
        return ""


def extract_cover_ocr_text(book: "Audiobook") -> str:
    """Best-effort OCR from sidecar cover, then embedded cover in sample audio.

    Returns "" when COVER_OCR is off, deps missing, or no usable cover.
    """
    if not cover_ocr_available():
        return ""

    from src.lib.fs_utils import find_cover_art_file
    from src.lib.id3_utils import _extract_cover_art_mutagen

    # Sidecar first (often sharper / larger than embedded).
    try:
        root = book.path if book.path.is_dir() else book.path.parent
        sidecar = find_cover_art_file(root)
        if sidecar:
            text = ocr_image_path(sidecar)
            if text:
                return text
    except Exception as e:
        print_debug(f"cover OCR: sidecar failed: {e}")

    # Embedded cover from sample audio.
    try:
        sample = getattr(book, "sample_audio1", None)
        if sample and Path(sample).is_file():
            mutagen_cover = _extract_cover_art_mutagen(Path(sample))
            if mutagen_cover:
                data, _fmt = mutagen_cover
                text = ocr_image_bytes(data)
                if text:
                    return text
    except Exception as e:
        print_debug(f"cover OCR: embedded cover failed: {e}")

    return ""


def ocr_mentions_name(ocr_text: str, name: str) -> bool:
    """True if *name* (or a substantial last-name token) appears in OCR text."""
    blob = (ocr_text or "").lower()
    n = (name or "").strip()
    if not blob or not n:
        return False
    if n.lower() in blob:
        return True
    tokens = [t for t in re.split(r"[\s,]+", n) if len(t) >= 4]
    if tokens and tokens[-1].lower() in blob:
        return True
    return fuzz.partial_ratio(n.lower(), blob) >= _AUTHOR_PARTIAL_MIN


def ocr_supports_title(ocr_text: str, title: str) -> bool:
    """True when OCR text is reasonably similar to a story title candidate."""
    if not ocr_text or not (title or "").strip():
        return False
    return fuzz.token_set_ratio(title.strip().lower(), ocr_text.lower()) / 100 >= _TITLE_TOKEN_MIN
