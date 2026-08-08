"""Fast unit tests for cover OCR helpers (mocked tesseract; synthetic PNG)."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, PropertyMock, patch


def _png_bytes(text: str = "Ursula K. Le Guin\nSolitude", size: tuple[int, int] = (400, 400)) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, color=(240, 240, 230))
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), text, fill=(10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_ocr_mentions_name_and_title_helpers():
    from src.lib.cover_ocr import ocr_mentions_name, ocr_supports_title

    blob = "Ursula K. Le Guin  Solitude  Nebula Awards"
    assert ocr_mentions_name(blob, "Ursula K. Le Guin")
    assert ocr_mentions_name(blob, "Le Guin, Ursula K.")
    assert not ocr_mentions_name(blob, "Anthony Storr")
    assert ocr_supports_title(blob, "Solitude")
    assert not ocr_supports_title(blob, "The Best American Spiritual Writing 2008")


def test_ocr_image_bytes_returns_tesseract_text():
    from src.lib import cover_ocr

    png = _png_bytes()
    mock_tess = MagicMock()
    mock_tess.image_to_string.return_value = "Ursula K. Le Guin\nSolitude"
    with patch.dict("sys.modules", {"pytesseract": mock_tess}):
        # Reload import inside function by calling with patched module
        text = cover_ocr.ocr_image_bytes(png)
    assert "Le Guin" in text
    assert cover_ocr.ocr_mentions_name(text, "Ursula K. Le Guin")


def test_ocr_image_bytes_skips_tiny_images():
    from src.lib import cover_ocr

    tiny = _png_bytes(size=(50, 50))
    mock_tess = MagicMock()
    mock_tess.image_to_string.return_value = "should not run"
    with patch.dict("sys.modules", {"pytesseract": mock_tess}):
        text = cover_ocr.ocr_image_bytes(tiny)
    assert text == ""
    mock_tess.image_to_string.assert_not_called()


def test_ocr_image_bytes_empty_on_bad_bytes():
    from src.lib.cover_ocr import ocr_image_bytes

    assert ocr_image_bytes(b"not-an-image") == ""


def test_cover_ocr_disabled_by_default():
    from src.lib.config import cfg
    from src.lib.cover_ocr import cover_ocr_available, extract_cover_ocr_text

    with patch.object(type(cfg), "COVER_OCR", new_callable=PropertyMock, return_value=False):
        assert cover_ocr_available() is False
        assert extract_cover_ocr_text(MagicMock()) == ""


def test_extract_cover_ocr_text_uses_sidecar_when_enabled(tmp_path):
    from src.lib.config import cfg
    from src.lib.cover_ocr import extract_cover_ocr_text

    cover = tmp_path / "cover.png"
    # find_cover_art_file ignores images under 7KB — make a large-enough PNG.
    cover.write_bytes(_png_bytes("Tana French\nThe Searcher", size=(800, 800)))
    # Pad so size >= 7168
    if cover.stat().st_size < 7168:
        cover.write_bytes(cover.read_bytes() + b"\0" * (7168 - cover.stat().st_size))

    book = MagicMock()
    book.path = tmp_path
    book.sample_audio1 = tmp_path / "missing.mp3"

    with patch.object(type(cfg), "COVER_OCR", new_callable=PropertyMock, return_value=True):
        with patch("src.lib.cover_ocr.cover_ocr_available", return_value=True):
            with patch("src.lib.cover_ocr.ocr_image_path", return_value="Tana French The Searcher") as mock_path:
                text = extract_cover_ocr_text(book)

    assert "Tana French" in text
    mock_path.assert_called_once()


