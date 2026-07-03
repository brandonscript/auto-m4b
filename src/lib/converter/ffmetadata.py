"""FFmetadata generation — port of Ffmpeg::buildFfmetadata."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.lib.converter.chapters import Chapter

# Characters that must be escaped in ffmetadata values: = ; # \ and newline
_ESCAPE_RE_CHARS = str.maketrans(
    {
        "=": r"\=",
        ";": r"\;",
        "#": r"\#",
        "\\": "\\\\",
        "\n": "\\\n",
    }
)


def _escape(value: str) -> str:
    return value.translate(_ESCAPE_RE_CHARS)


def build_ffmetadata(
    chapters: list[Chapter],
    *,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    album_artist: Optional[str] = None,
    composer: Optional[str] = None,
    comment: Optional[str] = None,
    genre: Optional[str] = None,
    date: Optional[str] = None,
    track: Optional[str] = None,
    encoder: Optional[str] = None,
    description: Optional[str] = None,
    sort_name: Optional[str] = None,
    sort_artist: Optional[str] = None,
    sort_album: Optional[str] = None,
) -> str:
    """Build a complete FFMETADATA1 string with optional global tags and chapter
    blocks (one per *chapters* entry).

    Timestamps use TIMEBASE=1/1000 (milliseconds).
    """
    lines: list[str] = [";FFMETADATA1"]

    # Global tags — only emit non-empty ones
    tag_map: list[tuple[str, Optional[str]]] = [
        ("title", title),
        ("artist", artist),
        ("album", album),
        ("album_artist", album_artist),
        ("composer", composer),
        ("comment", comment),
        ("genre", genre),
        ("date", date),
        ("track", track),
        ("encoder", encoder),
        ("description", description),
        ("sort_name", sort_name),
        ("sort_artist", sort_artist),
        ("sort_album", sort_album),
    ]
    for key, val in tag_map:
        if val:
            lines.append(f"{key}={_escape(val)}")

    # Chapter blocks
    for ch in chapters:
        lines.append("")
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={ch.start_ms}")
        lines.append(f"END={ch.end_ms}")
        lines.append(f"title={_escape(ch.title)}")

    return "\n".join(lines) + "\n"


def write_ffmetadata(
    path: Path,
    chapters: list[Chapter],
    **kwargs,
) -> Path:
    """Write the ffmetadata to *path* and return it."""
    path.write_text(build_ffmetadata(chapters, **kwargs), encoding="utf-8")
    return path
