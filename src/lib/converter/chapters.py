"""Chapter building — port of ChapterHandler and ChaptersFromFileTracks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Chapter:
    start_ms: int
    end_ms: int
    title: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def build_chapters_from_files(
    files: list[Path],
    durations_ms: list[int],
    *,
    use_filenames: bool = True,
    tag_titles: Optional[list[Optional[str]]] = None,
) -> list[Chapter]:
    """Build one chapter per file with cumulative timestamps.

    Parameters
    ----------
    files:
        Audio files in playback order.
    durations_ms:
        Duration of each file in milliseconds, same order as *files*.
    use_filenames:
        When True, the chapter title is the filename stem.  When False and
        *tag_titles* is supplied, prefer the tag title (fall back to stem if
        the tag is empty).
    tag_titles:
        Optional list of title tags extracted from each file, same order as
        *files*.  Ignored when *use_filenames* is True.
    """
    chapters: list[Chapter] = []
    cursor = 0

    for i, (f, dur) in enumerate(zip(files, durations_ms)):
        if use_filenames or not tag_titles:
            title = f.stem
        else:
            title = (tag_titles[i] or "").strip() or f.stem

        start = cursor
        end = cursor + dur
        chapters.append(Chapter(start_ms=start, end_ms=end, title=title))
        cursor = end

    return chapters


def dedupe_names(chapters: list[Chapter]) -> list[Chapter]:
    """Append ' (n)' suffix to every occurrence of a duplicate title — port of
    ChapterHandler::adjustNamedChapters.

    PHP logic: count occurrences of each title; for any title that appears more
    than once, number every occurrence starting at 1.
    """
    from collections import Counter

    counts: Counter[str] = Counter(ch.title for ch in chapters)

    # Track which index we're at per duplicate title
    seen: dict[str, int] = {}
    result: list[Chapter] = []

    for ch in chapters:
        if counts[ch.title] > 1:
            seen[ch.title] = seen.get(ch.title, 0) + 1
            new_title = f"{ch.title} ({seen[ch.title]})"
            result.append(Chapter(start_ms=ch.start_ms, end_ms=ch.end_ms, title=new_title))
        else:
            result.append(ch)

    return result


_CHAPTERS_TXT_RE = re.compile(
    r"^(?P<hms>\d+:\d{2}:\d{2}(?:\.\d+)?|\d+:\d{2}(?:\.\d+)?)"  # HH:MM:SS.ms or MM:SS.ms
    r"\s+"
    r"(?P<title>.+)$"
)


def _hms_to_ms(hms: str) -> int:
    """Convert 'HH:MM:SS.mmm', 'H:MM:SS', 'MM:SS', or 'H:MM:SS.mmm' to milliseconds."""
    parts = hms.split(":")
    ms = 0
    for p in parts[:-1]:
        ms = ms * 60 + int(p)
    ms *= 60
    seconds = float(parts[-1])
    ms += int(seconds)
    frac = seconds - int(seconds)
    ms = ms * 1000 + round(frac * 1000)
    return ms


def parse_chapters_txt(path: Path, total_duration_ms: int) -> list[Chapter]:
    """Parse an Audible-style chapters.txt into Chapter objects.

    Expected format (one entry per line)::

        0:00:00.000 Chapter Title
        0:05:12.345 Another Chapter

    The end of each chapter is the start of the next; the last chapter ends at
    *total_duration_ms*.
    """
    chapters: list[Chapter] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _CHAPTERS_TXT_RE.match(line)
            if not m:
                continue
            start_ms = _hms_to_ms(m.group("hms"))
            title = m.group("title").strip()
            chapters.append(Chapter(start_ms=start_ms, end_ms=0, title=title))

    # Fill end times
    for i in range(len(chapters) - 1):
        chapters[i] = Chapter(
            start_ms=chapters[i].start_ms,
            end_ms=chapters[i + 1].start_ms,
            title=chapters[i].title,
        )
    if chapters:
        last = chapters[-1]
        chapters[-1] = Chapter(start_ms=last.start_ms, end_ms=total_duration_ms, title=last.title)

    return chapters
