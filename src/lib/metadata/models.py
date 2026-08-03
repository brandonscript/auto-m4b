"""Shared metadata models for fix_metadata and (later) convert."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mutagen import File as MutagenFile
from rapidfuzz import fuzz

from src.lib.parsers import get_year_from_date


class SourceResolutionError(Exception):
    """Raised when a book has an m4b but no usable source audio can be found."""

    def __init__(self, book_dir: Path, message: str):
        self.book_dir = book_dir
        self.message = message
        super().__init__(f"{book_dir.name}: {message}")



@dataclass
class CliPaths:
    converted: Path | None = None
    archive: Path | None = None
    inbox: Path | None = None

    @property
    def log_file(self) -> Path | None:
        if self.converted:
            return self.converted / "auto-m4b.log"
        return None



@dataclass
class TagSnapshot:
    title: str = ""
    artist: str = ""
    album: str = ""
    albumartist: str = ""
    composer: str = ""
    date: str = ""
    path: Path | None = None

    @classmethod
    def from_file(cls, path: Path) -> "TagSnapshot":
        try:
            f = MutagenFile(str(path), easy=True)
        except Exception:
            f = None
        if not f:
            return cls(path=path)

        def _get(key: str) -> str:
            v = f.get(key)
            if not v:
                return ""
            return str(v[0] if isinstance(v, list) else v).strip()

        return cls(
            title=_get("title"),
            artist=_get("artist"),
            album=_get("album"),
            albumartist=_get("albumartist"),
            composer=_get("composer"),
            date=_get("date") or _get("year"),
            path=path,
        )



@dataclass
class FixPlan:
    book_dir: Path
    m4b: Path
    source: Path | None
    desired_title: str
    desired_author: str
    desired_album: str
    desired_date: str
    desired_narrator: str
    desired_stem: str
    current: TagSnapshot
    reasons: list[str] = field(default_factory=list)
    rename_m4b_to: Path | None = None
    desc_txt: Path | None = None
    rename_desc_to: Path | None = None
    # Folder / path priors (shown in "Filesystem")
    fs_title: str = ""
    fs_author: str = ""
    fs_date: str = ""
    fs_narrator: str = ""
    fs_files: str = ""  # LCS stem + original ext, e.g. "Author - Title.mp3"
    # Open Library (display; tags only forced via --ol / interactive o)
    ol_title: str = ""
    ol_author: str = ""
    ol_narrator: str = ""
    ol_year: str = ""
    ol_key: str = ""
    ol_url: str = ""
    ol_score: float = 0.0
    ol_status: str = ""  # match | low_confidence | none | skipped | forced
    # Goodreads / provider comparison
    goodreads_title: str = ""
    goodreads_author: str = ""
    goodreads_year: str = ""
    goodreads_key: str = ""
    goodreads_url: str = ""
    goodreads_score: float = 0.0
    goodreads_status: str = ""  # match | low_confidence | none | skipped | forced
    selected_provider: str = ""
    provider_conflicts: list[str] = field(default_factory=list)

    @property
    def needs_tag_write(self) -> bool:
        cur = self.current
        date_changed = bool(self.desired_date) and get_year_from_date(cur.date) != get_year_from_date(self.desired_date)
        narrator_changed = False
        if self.desired_narrator:
            narrator_changed = (cur.composer or "") != self.desired_narrator
        elif cur.composer and fuzz.token_set_ratio(cur.composer, self.desired_author) / 100 >= 0.7:
            narrator_changed = True  # clear author demoted to narrator
        return any(
            [
                (cur.title or "") != self.desired_title,
                (cur.artist or "") != self.desired_author,
                (cur.albumartist or "") != self.desired_author,
                (cur.album or "") != self.desired_album,
                date_changed,
                narrator_changed,
            ]
        )

    @property
    def needs_rename(self) -> bool:
        return self.rename_m4b_to is not None and self.rename_m4b_to != self.m4b

    @property
    def needs_desc_rewrite(self) -> bool:
        from src.lib.metadata.apply import _desc_needs_rewrite

        return bool(self.desc_txt) and _desc_needs_rewrite(self.desc_txt, self)

    @property
    def needs_work(self) -> bool:
        return self.needs_tag_write or self.needs_rename or self.needs_desc_rewrite

