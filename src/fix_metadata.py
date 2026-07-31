"""Fix ID3 tags + filenames for already-converted m4b files (no re-encode).

Usage examples::

    # Default: scan CLI_CONVERTED_FOLDER (or CONVERTED_FOLDER), auto-recursive
    poetry run python -m src.fix_metadata
    poetry run python -m src.fix_metadata -i

    # Relative author / book under converted
    poetry run python -m src.fix_metadata -i "George, Margaret"
    poetry run python -m src.fix_metadata "George, Margaret/Helen of Troy (2006)"

    # Explicit source tree (nesting must match converted scope)
    poetry run python -m src.fix_metadata -i -s /path/to/originals "George, Margaret"

    # Force Open Library match for a single book
    poetry run python -m src.fix_metadata --apply --ol OL45804W \\
      "George, Margaret/Elizabeth I (2011)"

    # External abs path (e.g. #plex) — source audio must sit beside the m4b, or pass -s
    poetry run python -m src.fix_metadata --apply \\
      "/media/.../#plex/French, Tana/The Searcher (2020)"

Host CLI paths (set in shell; mirror compose var names)::

    CLI_CONVERTED_FOLDER=/mnt/.../#auto-m4b/converted
    CLI_ARCHIVE_FOLDER=/mnt/.../#auto-m4b/archive
    CLI_INBOX_FOLDER=/mnt/.../#auto-m4b/inbox
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from mutagen import File as MutagenFile
from rapidfuzz import fuzz

from src.lib.cleaners import (
    clean_string,
    is_author_only_name,
    looks_like_marketing_subtitle,
    minimalist_title,
    strip_leading_author_dash,
    title_case_ol_title,
)
from src.lib.compare import find_greatest_common_string
from src.lib.fs_utils import ensure_audio_ext, safe_filename, try_relative_to
from src.lib.id3_utils import write_id3_tags_mutagen
from src.lib.misc import parse_bool
from src.lib.parsers import get_year_from_date, swap_firstname_lastname
from src.lib.term import (
    LIGHT_GREY_COLOR,
    border,
    divider,
    print_amber,
    print_banana,
    print_dark_grey,
    print_debug,
    print_green,
    print_grey,
    print_mint,
    print_orange,
    print_red,
    smart_print,
    tint_path,
)

_SOURCE_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wav"}
_OUTPUT_EXTS = {".m4b"}
_AUDIO_EXTS = _SOURCE_EXTS | _OUTPUT_EXTS
_MAX_RECURSE_DEPTH = 4

_YEAR_SUFFIX = re.compile(r"\s*\(\d{4}\)\s*$")
_FOLDER_YEAR = re.compile(r"\((\d{4})\)\s*$")
_NARRATOR_BRACKET = re.compile(r"\s*\[[^\]]+\]")
_SERIES_PREFIX = re.compile(r"^(.+?)\s+-\s+(.+)$")
_COLLECTIONS_PREFIX = re.compile(r"^\[Collections\]\s*", re.I)
_QUALITY_TXT = re.compile(r"^(.+?)\s+\[.+kbps.+\].txt$", re.I)


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
    ol_year: str = ""
    ol_key: str = ""
    ol_url: str = ""
    ol_score: float = 0.0
    ol_status: str = ""  # match | low_confidence | none | skipped | forced

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
        return bool(self.desc_txt) and _desc_needs_rewrite(self.desc_txt, self)

    @property
    def needs_work(self) -> bool:
        return self.needs_tag_write or self.needs_rename or self.needs_desc_rewrite


def folder_title_hint(folder_name: str) -> str:
    """Best story title from a #plex-style book folder name."""
    s = _COLLECTIONS_PREFIX.sub("", folder_name)
    s = _YEAR_SUFFIX.sub("", s)
    s = _NARRATOR_BRACKET.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    m = _SERIES_PREFIX.match(s)
    if m and not re.search(r"\bCycle\b|\bTrilogy\b|\bSeries\b", m.group(2), re.I):
        left, right = m.group(1), m.group(2)
        if re.search(r"\d", left) or re.search(
            r"\b(Cycle|Trilogy|Annals|Catwings|Orsinia|Hainish)\b", left, re.I
        ):
            s = right
    elif m and re.search(r"\d", m.group(1)):
        s = m.group(2)
    return s.strip(" -")


def folder_narrator_hint(folder_name: str) -> str:
    brackets = _NARRATOR_BRACKET.findall(folder_name)
    if not brackets:
        return ""
    for raw in reversed(brackets):
        inner = raw.strip().strip("[]").strip()
        if not inner:
            continue
        if re.fullmatch(
            r"AB|UNABRIDGED|BOXED\s+SET|COMPLETE|COLLECTIONS?|ANTHOLOGY",
            inner,
            re.I,
        ):
            continue
        if len(inner) < 2:
            continue
        return inner
    return ""


def parent_author_hint(book_dir: Path) -> str:
    parent = book_dir.parent.name.strip()
    if not parent or parent.startswith("#"):
        return ""
    return swap_firstname_lastname(parent)


def filesystem_extracted(book_dir: Path) -> tuple[str, str, str, str]:
    """Title / author / date / narrator priors from folder path alone."""
    title = folder_title_hint(book_dir.name)
    author = parent_author_hint(book_dir)
    narrator = folder_narrator_hint(book_dir.name)
    ym = _FOLDER_YEAR.search(book_dir.name)
    date = ym.group(1) if ym else ""
    return title, author, date, narrator


def _title_usable(title: str) -> bool:
    t = (title or "").strip()
    if not t or len(t) < 2:
        return False
    if t.isdigit():
        return False
    return True


def _env_truthy(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    if v == "on":
        return True
    return parse_bool(v) if v else False


def resolve_minimalist(*, flag_on: bool = False, flag_off: bool = False) -> bool:
    """Resolve minimalist mode: explicit flags beat ``CLI_MINIMALIST`` env."""
    if flag_off:
        return False
    if flag_on:
        return True
    return _env_truthy("CLI_MINIMALIST")


def _pick_desired(
    book_dir: Path,
    source: TagSnapshot | None,
    current: TagSnapshot,
    *,
    minimalist: bool = False,
) -> tuple[str, str, str, str, str, list[str]]:
    """Return (title, author, album, date, narrator, reasons)."""
    reasons: list[str] = []
    folder_title = folder_title_hint(book_dir.name)
    folder_narr = folder_narrator_hint(book_dir.name)
    parent_author = parent_author_hint(book_dir)

    src_title = (source.title if source else "") or ""
    src_album = (source.album if source else "") or ""
    title = ""
    if _title_usable(src_title):
        if folder_title and fuzz.token_set_ratio(src_title, folder_title) / 100 < 0.5:
            title = folder_title
            reasons.append(f"prefer folder title over source {src_title!r}")
        else:
            title = src_title
            if src_album and fuzz.token_set_ratio(src_title, src_album) / 100 < 0.85:
                reasons.append(f"keep source title over album ({src_album!r})")
    elif _title_usable(folder_title):
        title = folder_title
        reasons.append("title from folder name")
    elif _title_usable(current.title) and fuzz.token_set_ratio(
        current.title, folder_title or current.title
    ) / 100 >= 0.55:
        title = current.title
    else:
        title = folder_title or current.title or book_dir.name

    # Provisional author early so title cleanup can strip leading "Author - ".
    src_author = ""
    if source:
        src_author = source.albumartist or source.artist or ""
    provisional_author = ""
    if src_author and not _looks_like_title(src_author, title or folder_title):
        provisional_author = src_author
    elif parent_author:
        provisional_author = parent_author
    elif (current.artist or "").strip() and not _looks_like_title(
        current.artist, title or folder_title
    ):
        provisional_author = current.artist.strip()

    if provisional_author and title:
        deauthored = strip_leading_author_dash(title, provisional_author)
        if deauthored != title and _title_usable(deauthored):
            reasons.append(f"strip author prefix from title {title!r}")
            title = deauthored

    if minimalist and title:
        from src.lib.ol_lookup import _subtitle_sep_normalized, id3_prefer_colon_separator

        stripped = minimalist_title(title, author=provisional_author)
        candidates: list[str] = []
        for cand in (current.title or "", folder_title, stripped):
            if not _title_usable(cand):
                continue
            deauthored_cand = strip_leading_author_dash(cand, provisional_author)
            cand_core = minimalist_title(cand, author=provisional_author)
            if is_author_only_name(cand_core, provisional_author):
                continue
            # still has marketing junk relative to cleaned core
            if cand_core.casefold() != deauthored_cand.strip().casefold():
                continue
            if fuzz.token_set_ratio(cand, stripped) / 100 >= 0.85:
                c = deauthored_cand.strip() or cand.strip()
                if c not in candidates and not is_author_only_name(c, provisional_author):
                    candidates.append(c)
        if not candidates:
            candidates = (
                [stripped]
                if not is_author_only_name(stripped, provisional_author)
                else [title]
            )
        # Prefer colon form when candidates only differ by ": " vs " - "
        chosen = candidates[0]
        for cand in candidates:
            if _subtitle_sep_normalized(cand) != _subtitle_sep_normalized(chosen):
                continue
            if ": " in cand and ": " not in chosen:
                chosen = cand
        chosen = id3_prefer_colon_separator(chosen)
        if chosen != title:
            reasons.append(f"minimalist title {title!r} → {chosen!r}")
            title = chosen
    elif title:
        from src.lib.ol_lookup import id3_prefer_colon_separator

        normalized = id3_prefer_colon_separator(title)
        if normalized != title:
            reasons.append(f"id3 colon subtitle {title!r} → {normalized!r}")
            title = normalized
    author = ""
    if src_author and not _looks_like_title(src_author, title):
        author = src_author
    elif parent_author:
        author = parent_author
        reasons.append(f"author from parent folder ({book_dir.parent.name!r})")
    elif current.albumartist or current.artist:
        cand = current.albumartist or current.artist
        if parent_author and fuzz.token_set_ratio(cand, parent_author) / 100 >= 0.5:
            author = cand
        elif src_author and fuzz.token_set_ratio(cand, src_author) / 100 >= 0.5:
            author = cand
        else:
            author = parent_author or src_author or cand
            if parent_author or src_author:
                reasons.append(f"replace wrong author {cand!r}")
    else:
        author = parent_author or "Unknown Author"

    cur_author = current.albumartist or current.artist or ""
    if cur_author and fuzz.token_set_ratio(cur_author, author) / 100 < 0.5:
        reasons.append(f"author {cur_author!r} → {author!r}")

    if current.title and fuzz.token_set_ratio(current.title, title) / 100 < 0.55:
        reasons.append(f"title {current.title!r} → {title!r}")

    album = title

    folder_year = ""
    ym = _FOLDER_YEAR.search(book_dir.name)
    if ym:
        folder_year = ym.group(1)

    date = ""
    if folder_year:
        cur_y = get_year_from_date(current.date)
        src_y = get_year_from_date(source.date) if source and source.date else ""
        # ±1 year near-tie (publication vs audiobook/edition): leave id3 alone.
        if cur_y and abs(int(cur_y) - int(folder_year)) == 1:
            date = cur_y
        else:
            date = folder_year
            if cur_y and cur_y != folder_year:
                reasons.append(f"date {cur_y} → {folder_year}")
            elif src_y and src_y != folder_year:
                reasons.append(f"date from folder ({folder_year}) over source {src_y}")
    elif source and source.date:
        date = source.date
        if get_year_from_date(current.date) and get_year_from_date(current.date) != get_year_from_date(date):
            reasons.append(f"date {get_year_from_date(current.date)} → {get_year_from_date(date)}")
    elif current.date:
        date = current.date

    narrator = ""
    if folder_narr and fuzz.token_set_ratio(folder_narr, author) / 100 < 0.5:
        narrator = folder_narr
    if current.composer and fuzz.token_set_ratio(current.composer, author) / 100 >= 0.7:
        reasons.append(f"clear narrator/composer {current.composer!r} (was author)")
        narrator = narrator
    elif current.composer and not narrator:
        if fuzz.token_set_ratio(current.composer, author) / 100 < 0.5:
            pass

    return title, author, album, date, narrator, reasons


def _usable_rename_stem(s: str, author: str = "") -> bool:
    return bool(s) and not is_author_only_name(s, author)


def _stem_matches_book_title(stem: str, title: str, author: str = "") -> bool:
    """True when *stem* already names the book (title or Author - Title).

    Treats ``: `` and `` - `` as the same separator so ``The Searcher - A Novel``
    matches title ``The Searcher: A Novel``.
    """
    from src.lib.ol_lookup import _subtitle_sep_normalized

    s_norm = _subtitle_sep_normalized(stem)
    if not s_norm:
        return False
    candidates: list[str] = []
    t = (title or "").strip()
    if t:
        candidates.append(safe_filename(t))
        candidates.append(t)
    a = (author or "").strip()
    if a and t:
        title_fs = safe_filename(t)
        candidates.append(f"{a} - {title_fs}")
        candidates.append(safe_filename(f"{a} - {t}"))
    for c in candidates:
        if c and s_norm == _subtitle_sep_normalized(c):
            return True
    return False


def _looks_like_title(name: str, title: str) -> bool:
    if not name or not title:
        return False
    return fuzz.token_set_ratio(name, title) / 100 >= 0.85


def _is_ignored(name: str, ignore_globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in ignore_globs)


def _has_audio(d: Path, *, exts: set[str] | None = None) -> bool:
    use = exts or _AUDIO_EXTS
    try:
        return any(c.suffix.lower() in use for c in d.iterdir() if c.is_file())
    except OSError:
        return False


def _largest_audio(
    book_dir: Path,
    ignore_globs: list[str],
    *,
    exts: set[str],
) -> Path | None:
    try:
        files = [p for p in book_dir.iterdir() if p.is_file()]
    except OSError:
        return None
    candidates = [
        p for p in files if p.suffix.lower() in exts and not _is_ignored(p.name, ignore_globs)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def _find_source_and_m4b(
    book_dir: Path,
    ignore_globs: list[str],
) -> tuple[Path | None, Path | None]:
    """Beside-m4b lookup: source = non-m4b audio; m4b = largest .m4b."""
    source = _largest_audio(book_dir, ignore_globs, exts=_SOURCE_EXTS)
    m4b = _largest_audio(book_dir, ignore_globs, exts=_OUTPUT_EXTS)
    return source, m4b


def _find_desc_txt(book_dir: Path, m4b: Path) -> Path | None:
    candidates = list(book_dir.glob("*.txt"))
    for p in candidates:
        if p.stem.startswith(m4b.stem) or m4b.stem in p.stem:
            return p
    for p in candidates:
        if _QUALITY_TXT.match(p.name):
            return p
    return None


def _env_path(name: str) -> Path | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def resolve_cli_paths() -> CliPaths:
    """Resolve converted/archive/inbox from CLI_* env, else compose-style cfg paths."""
    converted = _env_path("CLI_CONVERTED_FOLDER")
    archive = _env_path("CLI_ARCHIVE_FOLDER")
    inbox = _env_path("CLI_INBOX_FOLDER")

    if converted and archive and inbox:
        return CliPaths(converted=converted, archive=archive, inbox=inbox)

    try:
        from src.lib.config import cfg

        if not converted:
            try:
                p = cfg.converted_dir
                if p and Path(p).exists():
                    converted = Path(p).resolve()
            except Exception:
                pass
        if not archive:
            try:
                p = cfg.archive_dir
                if p and Path(p).exists():
                    archive = Path(p).resolve()
            except Exception:
                pass
        if not inbox:
            try:
                p = cfg.inbox_dir
                if p and Path(p).exists():
                    inbox = Path(p).resolve()
            except Exception:
                pass
    except Exception:
        pass

    return CliPaths(converted=converted, archive=archive, inbox=inbox)


def resolve_target_paths(raw_paths: list[Path], cli: CliPaths) -> list[Path]:
    """No paths → converted; relative → under converted if present; else as-is."""
    if not raw_paths:
        if not cli.converted:
            raise SystemExit(
                "No paths given and CLI_CONVERTED_FOLDER / CONVERTED_FOLDER is unset or missing."
            )
        return [cli.converted]

    out: list[Path] = []
    for raw in raw_paths:
        if raw.is_absolute():
            out.append(raw)
            continue
        if cli.converted:
            under = (cli.converted / raw).resolve()
            if under.exists():
                out.append(under)
                continue
        out.append((Path.cwd() / raw).resolve())
    return out


def _is_under(child: Path, parent: Path | None) -> bool:
    if parent is None:
        return False
    return try_relative_to(child.resolve(), parent.resolve()) is not None


def map_source_dir(
    book_dir: Path,
    source_root: Path,
    scope_root: Path,
) -> Path | None:
    """Map a converted book dir to a folder under ``source_root`` by relative nesting."""
    source_root = source_root.resolve()
    book_dir = book_dir.resolve()
    scope_root = scope_root.resolve()

    try:
        rel = book_dir.relative_to(scope_root)
        cand = source_root / rel
        if cand.is_dir() and _has_audio(cand):
            return cand
    except ValueError:
        pass

    cand = source_root / book_dir.name
    if cand.is_dir() and _has_audio(cand):
        return cand

    if source_root.name == book_dir.name and source_root.is_dir() and _has_audio(source_root):
        return source_root

    return None


def resolve_source_dir(
    book_dir: Path,
    *,
    beside_source: Path | None,
    cli: CliPaths,
    scope_root: Path,
    source_root: Path | None,
    debug: bool = False,
) -> Path:
    """Locate the unconverted / archive source directory for *book_dir*."""
    book_dir = book_dir.resolve()

    if source_root is not None:
        mapped = map_source_dir(book_dir, source_root, scope_root)
        if mapped is None:
            raise SourceResolutionError(
                book_dir,
                f"no matching folder under -s {source_root} "
                f"(expected relative nesting from {scope_root.name!r})",
            )
        return mapped

    if beside_source is not None:
        return book_dir

    if _is_under(book_dir, cli.converted) and cli.archive and cli.converted:
        try:
            rel = book_dir.relative_to(cli.converted.resolve())
            arch = cli.archive.resolve() / rel
            if arch.is_dir() and _has_audio(arch):
                if debug and cli.log_file and cli.log_file.is_file():
                    try:
                        from src.lib.logger import get_log_entry

                        entry = get_log_entry(book_dir, cli.log_file)
                        if entry:
                            print_debug(f"log hit for {book_dir.name}: {entry[:80]}…")
                    except Exception:
                        pass
                return arch
            raise SourceResolutionError(
                book_dir,
                f"no archive source at {arch} (pass -s/--source to point at originals)",
            )
        except SourceResolutionError:
            raise
        except ValueError:
            pass

    raise SourceResolutionError(
        book_dir,
        "no source audio beside m4b and path is outside converted "
        "(pass -s/--source, or place originals next to the m4b)",
    )


def _source_audio_files(source_dir: Path, ignore_globs: list[str]) -> list[Path]:
    """All audio files in *source_dir* (source exts preferred order not required)."""
    try:
        files = [p for p in source_dir.iterdir() if p.is_file()]
    except OSError:
        return []
    return sorted(
        p for p in files if p.suffix.lower() in _AUDIO_EXTS and not _is_ignored(p.name, ignore_globs)
    )


def _clean_gcs_values(values: list[str]) -> str:
    """GCS across *values*, then ``clean_string`` to strip Part/Disc markers."""
    if not values:
        return ""
    if len(values) == 1:
        return clean_string(values[0]).strip(" -_,.")
    gcs = find_greatest_common_string(values)
    if not gcs:
        return clean_string(values[0]).strip(" -_,.")
    # Prefer original casing from the first value that contains the gcs
    gcs_l = gcs.lower()
    for v in values:
        idx = v.lower().find(gcs_l)
        if idx >= 0:
            raw = v[idx : idx + len(gcs)]
            break
    else:
        raw = gcs
    cleaned = clean_string(raw).strip(" -_,.")
    # Digit-truncated GCS guard (same idea as scorers): if GCS ends in a digit
    # and is a prefix of the first value, prefer cleaning the first full value.
    if cleaned and values[0].lower().startswith(cleaned.lower()) and cleaned[-1].isdigit():
        return clean_string(values[0]).strip(" -_,.")
    return cleaned


def source_common_title(source_dir: Path, ignore_globs: list[str] | None = None) -> tuple[str, str]:
    """Derive a book title from multi-file sources via GCS + part/disc strip.

    Returns ``(title, reason)`` where reason is empty if nothing useful found.
    Mirrors conversion scorers: greatest common string across titles (or filenames),
    then ``clean_string`` to strip ``Part N`` / ``Disc N`` / orphaned Part.
    """
    ignore_globs = ignore_globs or []
    files = _source_audio_files(source_dir, ignore_globs)
    if not files:
        return "", ""

    titles: list[str] = []
    albums: list[str] = []
    for f in files:
        snap = TagSnapshot.from_file(f)
        if snap.title:
            titles.append(snap.title)
        if snap.album:
            albums.append(snap.album)

    title = _clean_gcs_values(titles)
    if _title_usable(title):
        reason = "title from common source (stripped parts)" if len(titles) > 1 or (
            titles and clean_string(titles[0]) != titles[0]
        ) else ""
        return title, reason

    album = _clean_gcs_values(albums)
    if _title_usable(album):
        return album, "title from common album (stripped parts)"

    stem_title = _clean_gcs_values([f.stem for f in files])
    if _title_usable(stem_title):
        return stem_title, "title from common filenames (stripped parts)"

    return "", ""


def source_common_filename(source_dir: Path, ignore_globs: list[str] | None = None) -> str:
    """Part/disc-stripped GCS of source *filenames* (stems), for m4b rename.

    Unlike ``source_common_title``, this always prefers filenames over ID3 titles,
    so e.g. ``Author - Title, Part 1/2`` → ``Author - Title``.
    """
    ignore_globs = ignore_globs or []
    files = _source_audio_files(source_dir, ignore_globs)
    if not files:
        return ""
    return _clean_gcs_values([f.stem for f in files])


def source_files_display(source_dir: Path, ignore_globs: list[str] | None = None) -> str:
    """``<LCS stem>.<ext>`` for Filesystem ``Original file(s)`` row.

    Extension is the most common suffix among source audio files.
    """
    ignore_globs = ignore_globs or []
    files = _source_audio_files(source_dir, ignore_globs)
    if not files:
        return ""
    stem = _clean_gcs_values([f.stem for f in files])
    if not stem:
        return ""
    from collections import Counter

    ext = Counter(f.suffix.lower() for f in files).most_common(1)[0][0]
    return f"{stem}{ext}"


def _source_audio_file(source_dir: Path, ignore_globs: list[str]) -> Path | None:
    """Largest taggable audio in a source dir (prefer non-m4b, else any audio)."""
    pref = _largest_audio(source_dir, ignore_globs, exts=_SOURCE_EXTS)
    if pref:
        return pref
    return _largest_audio(source_dir, ignore_globs, exts=_AUDIO_EXTS)


def _attach_open_library(
    plan: FixPlan,
    *,
    ol_ref: str | None = None,
    apply_ol_tags: bool = False,
    minimalist: bool = False,
) -> FixPlan:
    """Lookup or fetch Open Library metadata onto *plan* (mutates and returns it)."""
    from src.lib.ol_lookup import (
        _best_matching_edition_base_title,
        _best_matching_edition_subtitle,
        _desired_matches_edition_title,
        _get_open_library_user_agent,
        id3_prefer_colon_separator,
        join_title_subtitle,
        ol_match_band,
        ol_title_uses_dash_separator,
        open_library_fetch_by_ref,
        open_library_lookup_title,
    )

    try:
        if ol_ref:
            ol = open_library_fetch_by_ref(
                ol_ref,
                original_author=plan.desired_author,
                original_narrator=plan.desired_narrator or None,
            )
            if ol is None:
                plan.ol_status = "none"
                plan.reasons.append(f"Open Library fetch failed for {ol_ref!r} (is OPEN_LIBRARY_USER_AGENT set?)")
                return plan
            plan.ol_status = "forced"
        else:
            # Always try full + stripped core so marketing junk does not block matches.
            queries: list[str] = []
            for q in (
                plan.desired_title,
                minimalist_title(plan.desired_title or "", author=plan.desired_author),
                folder_title_hint(plan.book_dir.name),
            ):
                q = (q or "").strip()
                if q and q.casefold() not in {x.casefold() for x in queries}:
                    queries.append(q)

            best_ol = None
            best_band = "skipped"
            best_score = -1.0
            band_rank = {"match": 3, "low_confidence": 2, "none": 1, "skipped": 0}
            for q in queries:
                cand = open_library_lookup_title(
                    q,
                    author=plan.desired_author,
                    narrator=plan.desired_narrator or None,
                    method="similarity",
                )
                band = ol_match_band(cand)
                score = float(cand.score(fallback=0.0)) if cand is not None else 0.0
                if band_rank.get(band, 0) > band_rank.get(best_band, 0) or (
                    band == best_band and score > best_score
                ):
                    best_ol, best_band, best_score = cand, band, score

            ol = best_ol
            if best_band == "skipped":
                plan.ol_status = "skipped"
                return plan
            if best_band == "none":
                plan.ol_status = "none"
                return plan
            plan.ol_status = best_band  # match | low_confidence
    except ValueError as e:
        plan.ol_status = "none"
        plan.reasons.append(str(e))
        return plan
    except Exception:
        plan.ol_status = "none"
        return plan

    plan.ol_title = title_case_ol_title(ol.title) if ol and ol.title else ""
    plan.ol_author = ol.author if ol else ""
    plan.ol_year = ol.date if ol else ""
    plan.ol_key = ol.key if ol else ""
    plan.ol_url = ol.url if ol else ""
    plan.ol_score = float(ol.score(fallback=0.0)) if ol else 0.0

    # Enrich title with edition subtitle when local naming already attests those tokens.
    # Prefer an edition base closest to local naming (e.g. Eon) over a regional
    # alternate work title (e.g. The Two Pearls of Wisdom). Never use a marketing
    # source-only title (e.g. Dragoneye Reborn alone) as the join base.
    agent = _get_open_library_user_agent()
    if agent and plan.ol_key and plan.ol_status in ("match", "low_confidence", "forced"):
        work_title = (plan.ol_title or "").strip()
        corpus = " ".join(
            p
            for p in (
                plan.book_dir.name,
                folder_title_hint(plan.book_dir.name),
                plan.fs_files or "",
                plan.fs_title or "",
                plan.desired_title or "",
            )
            if p
        )
        prefer_local = (plan.desired_title or plan.fs_title or "").strip() or None
        # Keep a local title that already matches an edition form (US Eon vs AU work title).
        already_good = bool(
            prefer_local
            and _desired_matches_edition_title(plan.ol_key, prefer_local, agent=agent)
        )
        base_title = _best_matching_edition_base_title(
            plan.ol_key,
            corpus,
            work_title=work_title,
            prefer_local=prefer_local,
            agent=agent,
        )
        sub = None
        if not already_good:
            sub = _best_matching_edition_subtitle(
                plan.ol_key,
                corpus,
                base_title=base_title,
                agent=agent,
                prefer_local=prefer_local,
            )
        # Never re-attach trilogy/Book N/unabridged noise (esp. in minimalist mode).
        if sub and looks_like_marketing_subtitle(sub):
            sub = None
        if sub and base_title:
            # id3 defaults to colon; dash only if OL title is already dash-form.
            prefer_dash = ol_title_uses_dash_separator(
                plan.ol_title or "", base_title, sub
            )
            enriched = title_case_ol_title(
                join_title_subtitle(base_title, sub, prefer_dash=prefer_dash)
            )
            enriched = id3_prefer_colon_separator(
                enriched, ol_title_hint=plan.ol_title if prefer_dash else None
            )
            if enriched and enriched != plan.desired_title:
                # Minimalist: do not grow a clean desired title with OL subtitle noise
                if (
                    minimalist
                    and minimalist_title(enriched, author=plan.desired_author)
                    != enriched.strip()
                ):
                    pass
                else:
                    plan.desired_title = enriched
                    plan.desired_album = enriched
                    plan.ol_title = enriched
                    plan.reasons.append(f"title + OL subtitle ({sub!r})")

    if apply_ol_tags and plan.ol_status == "forced":
        _apply_ol_fields_to_desired(plan)
    else:
        # Auto OL is display-only for tags, but date can adopt a 2-of-3 consensus.
        _apply_date_consensus(plan)
    return plan


def _normalize_year(value: str | None) -> str:
    """Extract a 4-digit year string, or empty if none."""
    return get_year_from_date(value or "") or ""


def _year_consensus(*years: str | None) -> str | None:
    """Return a year shared by at least two non-empty inputs, else None."""
    counts: dict[str, int] = {}
    for raw in years:
        y = _normalize_year(raw)
        if not y:
            continue
        counts[y] = counts.get(y, 0) + 1
    winners = [y for y, n in counts.items() if n >= 2]
    if len(winners) == 1:
        return winners[0]
    return None


def _apply_date_consensus(plan: FixPlan) -> None:
    """If FS / id3 / OL agree 2-of-3 on a year, adopt that as desired_date.

    Local planning still prefers folder year (except ±1 near-tie). Once OL is
    attached, a clear majority (e.g. id3+OL 1997 vs folder 2007) overrides the
    folder prior so we don't churn a correct publication year toward an
    audiobook/folder year.
    """
    if plan.ol_status not in ("match", "low_confidence"):
        return
    ol_y = _normalize_year(plan.ol_year)
    if not ol_y:
        return
    fs_y = _normalize_year(plan.fs_date)
    id3_y = _normalize_year(plan.current.date)
    winner = _year_consensus(fs_y, id3_y, ol_y)
    if not winner:
        return
    cur = _normalize_year(plan.desired_date)
    if winner == cur:
        return
    plan.reasons.append(f"date consensus {cur or '(none)'} → {winner} (2 of FS/id3/OL)")
    plan.desired_date = winner


def _apply_ol_fields_to_desired(plan: FixPlan) -> None:
    """Copy stored OL fields into desired_* tags (does not change rename stem)."""
    if plan.ol_title:
        plan.desired_title = plan.ol_title
        plan.desired_album = plan.desired_title
        plan.reasons.append(f"title from Open Library ({plan.ol_key})")
    if plan.ol_author:
        plan.desired_author = plan.ol_author
        plan.reasons.append(f"author from Open Library ({plan.ol_author!r})")
    if plan.ol_year:
        if get_year_from_date(plan.desired_date) != get_year_from_date(str(plan.ol_year)):
            plan.reasons.append(f"date from Open Library ({plan.ol_year})")
        plan.desired_date = str(plan.ol_year)


def plan_fix(
    book_dir: Path,
    ignore_globs: list[str] | None = None,
    *,
    cli: CliPaths | None = None,
    scope_root: Path | None = None,
    source_root: Path | None = None,
    debug: bool = False,
    require_source: bool = True,
    ol_ref: str | None = None,
    lookup_ol: bool = True,
    minimalist: bool = False,
) -> FixPlan | None:
    """Build a fix plan for one book dir.

    Raises SourceResolutionError when ``require_source`` and no source can be resolved.
    Returns None when the book needs no changes (unless ``ol_ref`` forces a rewrite).
    """
    ignore_globs = ignore_globs or []
    cli = cli or CliPaths()
    book_dir = book_dir.resolve()
    scope_root = (scope_root or book_dir).resolve()

    if not book_dir.is_dir():
        return None
    beside_source, m4b = _find_source_and_m4b(book_dir, ignore_globs)
    if not m4b:
        return None

    source_path: Path | None = None
    source_snap: TagSnapshot | None = None
    reasons_prefix: str | None = None
    common_title_reason: str = ""
    filename_stem: str = ""
    fs_files: str = ""

    if require_source:
        src_dir = resolve_source_dir(
            book_dir,
            beside_source=beside_source,
            cli=cli,
            scope_root=scope_root,
            source_root=source_root,
            debug=debug,
        )
        filename_stem = source_common_filename(src_dir, ignore_globs)
        fs_files = source_files_display(src_dir, ignore_globs)
        if beside_source and src_dir == book_dir:
            source_path = beside_source
            source_snap = TagSnapshot.from_file(beside_source)
            # Still strip Part N from a lone beside-m4b source title
            cleaned = clean_string(source_snap.title or "").strip(" -_,.")
            if cleaned and cleaned != source_snap.title:
                source_snap.title = cleaned
                common_title_reason = "title stripped part/disc markers"
            if not filename_stem:
                filename_stem = clean_string(beside_source.stem).strip(" -_,.")
            if not fs_files:
                fs_files = beside_source.name
        else:
            source_path = _source_audio_file(src_dir, ignore_globs)
            if source_path is None:
                raise SourceResolutionError(book_dir, f"no audio files in source dir {src_dir}")
            if src_dir != book_dir:
                reasons_prefix = f"source from {src_dir}"
            source_snap = TagSnapshot.from_file(source_path)
            common_title, common_title_reason = source_common_title(src_dir, ignore_globs)
            if common_title:
                source_snap.title = common_title
                # Prefer common album too when titles were part-split
                if not source_snap.album or fuzz.token_set_ratio(source_snap.album, common_title) / 100 < 0.5:
                    source_snap.album = common_title
    elif beside_source:
        source_path = beside_source
        source_snap = TagSnapshot.from_file(beside_source)
        filename_stem = clean_string(beside_source.stem).strip(" -_,.")
        fs_files = beside_source.name

    current = TagSnapshot.from_file(m4b)
    title, author, album, date, narrator, reasons = _pick_desired(
        book_dir, source_snap, current, minimalist=minimalist
    )
    # Local determinations (folder + source) before any Open Library override.
    # fs_date is the folder (YYYY) prior, not the picked desired date.
    folder_date = filesystem_extracted(book_dir)[2]
    fs_title, fs_author, fs_date, fs_narrator = (
        title,
        author,
        folder_date,
        narrator,
    )
    if reasons_prefix:
        reasons.insert(0, reasons_prefix)
    if common_title_reason:
        reasons.insert(0 if not reasons_prefix else 1, common_title_reason)

    # Rename stem = part-stripped GCS of source filenames (not the ID3 title).
    # Never emit an author-only stem — prefer the original source filename, then
    # title, then the current m4b name (minimalist or not).
    raw_stem = filename_stem or title or m4b.stem
    stem = safe_filename(raw_stem) if raw_stem else ""
    title_stem = safe_filename(title) if title else ""
    original_stem = safe_filename(filename_stem) if filename_stem else ""

    if minimalist and raw_stem:
        cleaned = minimalist_title(raw_stem, author=author)
        cleaned = safe_filename(cleaned) if cleaned else ""
        if _usable_rename_stem(cleaned, author):
            if cleaned != stem:
                reasons.append(f"minimalist rename stem {stem!r} → {cleaned!r}")
            stem = cleaned
        elif _usable_rename_stem(title_stem, author):
            if title_stem != stem:
                reasons.append(
                    f"minimalist rename stem rejected {cleaned or stem!r}; "
                    f"using title {title_stem!r}"
                )
            stem = title_stem
        elif _usable_rename_stem(original_stem, author):
            if original_stem != stem:
                reasons.append(
                    f"minimalist rename stem rejected {cleaned or stem!r}; "
                    f"keeping source {original_stem!r}"
                )
            stem = original_stem
        else:
            if m4b.stem != stem:
                reasons.append(
                    f"minimalist rename stem rejected {cleaned or stem!r}; "
                    f"keeping {m4b.stem!r}"
                )
            stem = m4b.stem
    elif not _usable_rename_stem(stem, author):
        # Non-minimalist: still never rename to author-only.
        if _usable_rename_stem(original_stem, author):
            reasons.append(
                f"rename stem rejected author-only {stem!r}; "
                f"keeping source {original_stem!r}"
            )
            stem = original_stem
        elif _usable_rename_stem(title_stem, author):
            reasons.append(
                f"rename stem rejected author-only {stem!r}; "
                f"using title {title_stem!r}"
            )
            stem = title_stem
        else:
            reasons.append(
                f"rename stem rejected author-only {stem!r}; "
                f"keeping {m4b.stem!r}"
            )
            stem = m4b.stem

    # If the current .m4b already matches the title (or Author - Title), keep it —
    # don't rename to a glued source stem like TheSearcherANovel_ep7.
    if _stem_matches_book_title(m4b.stem, title, author):
        if stem != m4b.stem:
            reasons.append(f"keep current filename {m4b.stem!r} (matches title)")
        stem = m4b.stem

    rename_to = m4b.with_name(ensure_audio_ext(stem, ".m4b")) if stem and m4b.stem != stem else None
    if rename_to == m4b:
        rename_to = None

    desc = _find_desc_txt(book_dir, m4b)
    rename_desc = None
    if desc and rename_to:
        m = _QUALITY_TXT.match(desc.name)
        if m:
            quality_part = desc.name[len(m.group(1)) :]
            rename_desc = desc.with_name(f"{stem}{quality_part}")
        else:
            rename_desc = desc.with_name(f"{stem}.txt")

    plan = FixPlan(
        book_dir=book_dir,
        m4b=m4b,
        source=source_path,
        desired_title=title,
        desired_author=author,
        desired_album=album,
        desired_date=date,
        desired_narrator=narrator,
        desired_stem=stem,
        current=current,
        reasons=reasons,
        rename_m4b_to=rename_to,
        desc_txt=desc,
        rename_desc_to=rename_desc if rename_desc and rename_desc != desc else None,
        fs_title=fs_title,
        fs_author=fs_author,
        fs_date=fs_date,
        fs_narrator=fs_narrator,
        fs_files=fs_files,
    )
    if desc and _desc_needs_rewrite(desc, plan):
        if "update description txt contents" not in plan.reasons:
            plan.reasons.append("update description txt contents")

    if ol_ref or lookup_ol:
        _attach_open_library(
            plan, ol_ref=ol_ref, apply_ol_tags=bool(ol_ref), minimalist=minimalist
        )

    if not plan.needs_work:
        return None
    return plan


def _desc_needs_rewrite(desc: Path, plan: FixPlan) -> bool:
    try:
        text = desc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    if f"Book title: {plan.desired_title}" not in text:
        return True
    if f"Author: {plan.desired_author}" not in text:
        return True
    return False


def _write_desc(plan: FixPlan, out_path: Path, bitrate_line: str = "") -> None:
    quality = "N/A"
    duration = "N/A"
    size = "N/A"
    orig_block = ""
    if plan.desc_txt and plan.desc_txt.is_file():
        try:
            old = plan.desc_txt.read_text(encoding="utf-8", errors="replace")
            for line in old.splitlines():
                if line.startswith("Quality:"):
                    quality = line.split(":", 1)[1].strip() or quality
                elif line.startswith("Duration:"):
                    duration = line.split(":", 1)[1].strip() or duration
                elif line.startswith("Size:") and "(Original)" not in old[: old.find(line)]:
                    if "Duration:" in old.split(line)[0]:
                        size = line.split(":", 1)[1].strip() or size
                elif line.startswith("(Original)"):
                    orig_block = "\n".join(old.split("(Original)")[1:]).strip()
                    break
        except OSError:
            pass
    if not orig_block and plan.source:
        orig_block = (
            f"File name: {plan.source.name}\n"
            f"Format: {plan.source.suffix.lstrip('.') or 'N/A'}\n"
            f"Size: N/A"
        )

    content = f"""Book title: {plan.desired_title}
Author: {plan.desired_author}
Date: {plan.desired_date}
Narrator: {plan.desired_narrator}
Format: m4b
Quality: {quality}
Duration: {duration}
Size: {size}

(Original)
{orig_block}
"""
    out_path.write_text(content, encoding="utf-8")


def _short_path(path: Path | str, cli: CliPaths | None = None) -> str:
    """Prefer path relative to converted/archive/inbox; else ellipsize long abs paths."""
    p = Path(path)
    bases: list[Path] = []
    if cli:
        for b in (cli.converted, cli.archive, cli.inbox):
            if b:
                bases.append(b.resolve())
    for base in bases:
        try:
            rel = p.resolve().relative_to(base)
            # Label which root we relativized against
            label = base.name  # converted | archive | inbox
            return f"{label}/{rel.as_posix()}"
        except ValueError:
            continue
    parts = p.parts
    if len(parts) > 5:
        return "…/" + "/".join(parts[-4:])
    return str(p)


def _prop_equal(a: str | None, b: str | None, *, is_date: bool = False) -> bool:
    if is_date:
        ya, yb = get_year_from_date(a or ""), get_year_from_date(b or "")
        if ya or yb:
            return ya == yb and bool(ya)
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def _prop_display(value: str | None, *, empty_label: str = "(missing)", is_date: bool = False) -> str:
    raw = (value or "").strip()
    if not raw:
        return empty_label
    if is_date:
        return get_year_from_date(raw) or raw
    return raw


def _truth_props(plan: FixPlan) -> dict[str, str]:
    """Canonical values used to color FS / id3 rows (what we would write).

    Open Library is display-only for auto matches — do not use OL fields as truth
    for FS/id3 coloring, or near-tie dates / local titles paint as "wrong".
    """
    return {
        "title": plan.desired_title or "",
        "author": plan.desired_author or "",
        "date": get_year_from_date(plan.desired_date) or plan.desired_date or "",
        "narrator": plan.desired_narrator or "",
    }


def _id3_already_correct_style(
    fs_value: str | None,
    truth: str,
    *,
    is_date: bool = False,
) -> str:
    """Mint when FS is wrong so the correct id3 value is green, not grey+amber."""
    fs = (fs_value or "").strip()
    if fs and not _prop_equal(fs, truth, is_date=is_date):
        return "mint"
    return "light_grey"


def _print_reviewing_box(book_name: str) -> None:
    """Nested dashed/solid box matching conversion book headers."""
    from tinta import Tinta

    # Match term.box() spacing: space after ││ and before closing ││
    plain = f"Reviewing {book_name}"
    max_len = len(plain)
    border(max_len + 2, l="╭", c="╌", r="╮")
    smart_print(
        Tinta()
        .dark_grey("││", sep=" ")
        .light_grey("Reviewing ", sep="")
        .mint(book_name, sep=" ")
        .dark_grey("││", sep="")
        .to_str()
    )
    border(max_len + 2, l="╰", c="╌", r="╯")


def _framed_header(title: str, *, style: str) -> None:
    """``┌─ Title`` rail header. style: dark_grey | banana."""
    from tinta import Tinta

    smart_print("")
    if style == "banana":
        smart_print(Tinta().banana(f"┌─ {title}").to_str())
    else:
        # Dim rail like the reviewing box border; title text is white
        smart_print(
            Tinta().dark_grey("┌─ ", sep="").white(title, sep="").to_str()
        )


def _framed_footer(*, style: str) -> None:
    from tinta import Tinta

    if style == "banana":
        smart_print(Tinta().banana("└─").to_str())
    else:
        smart_print(Tinta().dark_grey("└─").to_str())


def _print_framed_prop(
    label: str,
    value: str | None,
    truth: str,
    *,
    frame_style: str = "dark_grey",
    is_date: bool = False,
    already_correct_style: str = "mint",
) -> None:
    """Property row inside a ``│`` frame, colored vs *truth* (no label padding)."""
    from tinta import Tinta

    empty = not (value or "").strip()
    # Empty with no truth → unknown; empty with truth → missing (shown in proposed)
    empty_label = "(unknown)" if empty and not (truth or "").strip() else "(missing)"
    display = _prop_display(value, empty_label=empty_label, is_date=is_date)
    if frame_style == "banana":
        s = Tinta().banana("│ ", sep="")
    else:
        s = Tinta().dark_grey("│ ", sep="")
    s.grey(f"{label}: ", sep="")
    if empty or display in ("(missing)", "(unknown)"):
        s.dark_grey(display, sep="")
    elif _prop_equal(value, truth, is_date=is_date):
        if already_correct_style == "light_grey":
            s.light_grey(display, sep="")
        else:
            s.mint(display, sep="")
    else:
        s.amber(display, sep="")
    smart_print(s.to_str())


def _print_proposed_block(
    tag_rows: list[tuple[str, str | None, str | None, bool]],
    rename: tuple[str, str] | None = None,
) -> None:
    """Print Proposed fixes with aligned tag columns; rename on its own line.

    Each tag row is ``(label, old_raw, new_raw, is_date)``.
    *unknown* (both empty): dark grey ``(unknown)`` only, no arrow.
    *missing* (old empty, new set): ``(missing) » new``.
    """
    from tinta import Tinta

    if not tag_rows and not rename:
        return

    # Precompute displays for alignment (only rows that show an arrow/change pair)
    prepared: list[tuple[str, str, str, str]] = []
    # kind: unknown | missing | equal | change
    for label, old, new, is_date in tag_rows:
        old_empty = not (old or "").strip()
        new_empty = not (new or "").strip()
        if old_empty and new_empty:
            prepared.append((label, "unknown", "(unknown)", ""))
        elif old_empty and not new_empty:
            prepared.append((
                label,
                "missing",
                "(missing)",
                _prop_display(new, is_date=is_date),
            ))
        else:
            old_d = _prop_display(old, is_date=is_date)
            new_d = _prop_display(new, empty_label="(unknown)", is_date=is_date)
            kind = "equal" if _prop_equal(old, new, is_date=is_date) else "change"
            prepared.append((label, kind, old_d, new_d))

    label_w = max(
        [len(f"{label}:") for label, *_ in prepared]
        + ([len("Rename:")] if rename else [])
        + [len("Narrator:")]
    )
    paired = [(old_d, new_d) for _, kind, old_d, new_d in prepared if kind != "unknown"]
    old_w = max((len(o) for o, _ in paired), default=0)

    _framed_header("Proposed fixes", style="banana")
    for label, kind, old_d, new_d in prepared:
        label_s = f"{label}:"
        s = Tinta().banana("│ ", sep="").grey(f"{label_s:<{label_w}} ", sep="")
        if kind == "unknown":
            s.dark_grey("(unknown)", sep="")
        elif kind == "equal":
            s.light_grey(f"{old_d:<{old_w}}", sep="").dark_grey(" » ", sep="").light_grey(
                new_d, sep=" "
            ).mint("✓", sep="")
        elif kind == "missing":
            s.dark_grey(f"{old_d:<{old_w}}", sep="").dark_grey(" » ", sep="").mint(new_d, sep="")
        else:
            s.amber(f"{old_d:<{old_w}}", sep="").dark_grey(" » ", sep="").mint(new_d, sep="")
        smart_print(s.to_str())

    if rename:
        old_name, new_name = rename
        s = (
            Tinta()
            .banana("│ ", sep="")
            .grey("Rename: ", sep="")
            .amber(old_name, sep="")
            .dark_grey(" » ", sep="")
            .mint(new_name, sep="")
        )
        smart_print(s.to_str())
    _framed_footer(style="banana")


def print_plan(plan: FixPlan, *, label: str = "dry-run", cli: CliPaths | None = None) -> None:
    """Print review blocks + consolidated proposed fixes (mockup layout)."""
    from tinta import Tinta

    del label, cli  # layout is the same for propose / dry-run
    truth = _truth_props(plan)

    smart_print("")
    _print_reviewing_box(plan.book_dir.name)

    _framed_header("Filesystem", style="light_grey")
    if plan.fs_files:
        smart_print(
            Tinta()
            .dark_grey("│ ", sep="")
            .grey("Original file(s): ", sep="")
            .mint(plan.fs_files, sep="")
            .to_str()
        )
    _print_framed_prop("Title", plan.fs_title, truth["title"])
    _print_framed_prop("Author", plan.fs_author, truth["author"])
    _print_framed_prop("Date", plan.fs_date, truth["date"], is_date=True)
    _print_framed_prop("Narrator", plan.fs_narrator, truth["narrator"])
    _framed_footer(style="light_grey")

    cur = plan.current
    _framed_header("id3 tags", style="light_grey")
    _print_framed_prop(
        "Title",
        cur.title,
        truth["title"],
        already_correct_style=_id3_already_correct_style(plan.fs_title, truth["title"]),
    )
    _print_framed_prop(
        "Author",
        cur.albumartist or cur.artist,
        truth["author"],
        already_correct_style=_id3_already_correct_style(
            plan.fs_author, truth["author"]
        ),
    )
    _print_framed_prop(
        "Date",
        get_year_from_date(cur.date) or cur.date,
        truth["date"],
        is_date=True,
        already_correct_style=_id3_already_correct_style(
            plan.fs_date, truth["date"], is_date=True
        ),
    )
    _print_framed_prop(
        "Narrator",
        cur.composer,
        truth["narrator"],
        already_correct_style=_id3_already_correct_style(
            plan.fs_narrator, truth["narrator"]
        ),
    )
    _framed_footer(style="light_grey")

    if plan.ol_status in ("match", "forced", "none", "low_confidence"):
        # Always show when OL ran (UA set); skip only when lookup was disabled
        if plan.ol_status == "forced":
            header = "openlibrary (forced)"
        else:
            header = "openlibrary"
        _framed_header(header, style="light_grey")
        if plan.ol_status == "none":
            smart_print(
                Tinta()
                .dark_grey("│ ", sep="")
                .pink("(No matches found)", sep="")
                .to_str()
            )
        else:
            low = plan.ol_status == "low_confidence"
            if low:
                score_s = f"{plan.ol_score:.1f}".rstrip("0").rstrip(".") or "0"
                smart_print(
                    Tinta()
                    .dark_grey("│ ", sep="")
                    .pink(f"(Low confidence match • {score_s})", sep="")
                    .to_str()
                )

            def _ol_row(
                label: str,
                value: str,
                truth_val: str = "",
                *,
                primary: bool = True,
                is_date: bool = False,
            ) -> None:
                empty = not (value or "").strip()
                display = (
                    _prop_display(value, empty_label="(missing)", is_date=is_date)
                    if not empty
                    else ("(unknown)" if label == "Narrator" else "(missing)")
                )
                s = Tinta().dark_grey("│ ", sep="").grey(f"{label}: ", sep="")
                if empty:
                    s.dark_grey(display, sep="")
                elif not primary:
                    s.grey(display, sep="")
                elif low and not _prop_equal(value, truth_val, is_date=is_date):
                    # Low-confidence + disagrees with desired → amber
                    s.amber(display, sep="")
                elif _prop_equal(value, truth_val, is_date=is_date):
                    s.mint(display, sep="")
                else:
                    # Confident OL that disagrees with desired (e.g. lost 2-of-3 vote)
                    s.amber(display, sep="")
                smart_print(s.to_str())

            _ol_row("Title", plan.ol_title, truth["title"])
            _ol_row("Author", plan.ol_author, truth["author"])
            _ol_row(
                "Date",
                get_year_from_date(plan.ol_year) or plan.ol_year,
                truth["date"],
                is_date=True,
            )
            _ol_row("Narrator", "", primary=False)
            if plan.ol_key:
                work_id = plan.ol_key.rsplit("/", 1)[-1]
                smart_print(
                    Tinta()
                    .dark_grey("│ ", sep="")
                    .grey("Work: ", sep="")
                    .grey(work_id, sep="")
                    .to_str()
                )
            if plan.ol_url:
                smart_print(
                    Tinta()
                    .dark_grey("│ ", sep="")
                    .grey("Link: ", sep="")
                    .grey(plan.ol_url, sep="")
                    .to_str()
                )
        _framed_footer(style="light_grey")

    tag_rows: list[tuple[str, str | None, str | None, bool]] = [
        ("Title", cur.title, plan.desired_title, False),
        ("Author", cur.albumartist or cur.artist, plan.desired_author, False),
        (
            "Date",
            get_year_from_date(cur.date) or cur.date,
            get_year_from_date(plan.desired_date) or plan.desired_date,
            True,
        ),
        ("Narrator", cur.composer, plan.desired_narrator, False),
    ]
    rename = None
    if plan.rename_m4b_to:
        rename = (plan.m4b.name, plan.rename_m4b_to.name)
    _print_proposed_block(tag_rows, rename=rename)


def print_source_failure(err: SourceResolutionError, cli: CliPaths | None = None) -> None:
    """Pretty-print a source resolution failure."""
    print_red(f"  ×  [[{err.book_dir.name}]]")
    msg = err.message
    # Pull a path out of common message shapes for a second muted line.
    if "no archive source at " in msg:
        rest = msg.split("no archive source at ", 1)[1]
        path_part, _, hint = rest.partition(" (pass ")
        print_dark_grey(f"     missing: {tint_path(_short_path(path_part.strip(), cli))}")
        if hint:
            print_dark_grey(f"     hint:    pass {hint.rstrip(')')}")
    elif "no matching folder under -s " in msg:
        print_dark_grey(f"     {msg}")
    else:
        print_dark_grey(f"     {msg}")


def parse_apply_prompt(raw: str) -> str:
    """Normalize an interactive prompt response to y/s/o/m/q (default s)."""
    s = (raw or "").strip().lower()
    if not s:
        return "s"
    if s in ("y", "yes"):
        return "y"
    if s in ("s", "skip", "n", "no"):
        return "s"
    if s in ("o", "ol", "openlibrary", "open library"):
        return "o"
    if s in ("m", "match", "use match"):
        return "m"
    if s in ("q", "quit"):
        return "q"
    if len(s) == 1 and s in ("y", "s", "o", "m", "q", "n"):
        return "s" if s == "n" else s
    return "s"


def prompt_apply(plan: FixPlan) -> str:
    """Ask whether to apply *plan*.

    Returns ``y``, ``s`` (skip), ``o`` (open library), ``m`` (use low-confidence
    match), ``q`` (quit), or ``interrupt`` (Ctrl+C).
    """
    try:
        from tinta import Tinta

        smart_print("")
        print_amber("Apply this fix?")
        smart_print("")
        # 2-space indent; two spaces between key and description
        smart_print(
            Tinta()
            .dark_grey("  ", sep="")
            .amber("y", sep="")
            .dark_grey("  ", sep="")
            .light_grey("yes", sep="")
            .to_str()
        )
        smart_print(
            Tinta()
            .dark_grey("  ", sep="")
            .amber("s", sep="")
            .dark_grey("  ", sep="")
            .light_grey("skip", sep="")
            .dark_grey(" (default)", sep="")
            .to_str()
        )
        if plan.ol_status == "low_confidence":
            smart_print(
                Tinta()
                .dark_grey("  ", sep="")
                .amber("m", sep="")
                .dark_grey("  ", sep="")
                .light_grey("use this openlibrary match", sep="")
                .to_str()
            )
        smart_print(
            Tinta()
            .dark_grey("  ", sep="")
            .amber("o", sep="")
            .dark_grey("  ", sep="")
            .light_grey("provide an openlibrary id or url...", sep="")
            .to_str()
        )
        smart_print(
            Tinta()
            .dark_grey("  ", sep="")
            .amber("q", sep="")
            .dark_grey("  ", sep="")
            .light_grey("quit", sep="")
            .to_str()
        )
        smart_print("")
        choice_keys = "y/S/m/o/q" if plan.ol_status == "low_confidence" else "y/S/o/q"
        t = Tinta().dark_grey("[", sep="")
        for ch in choice_keys:
            if ch == "/":
                t.dark_grey("/", sep="")
            else:
                t.amber(ch, sep="")
        t.dark_grey("]: ", sep="")
        raw = input(t.to_str()).strip()
    except EOFError:
        return "s"
    except KeyboardInterrupt:
        smart_print("")  # move off the prompt line
        return "interrupt"
    return parse_apply_prompt(raw)


def prompt_ol_ref() -> str | None:
    """Ask for an Open Library URL or id. Empty / Ctrl+C → None."""
    try:
        from tinta import Tinta

        smart_print("")
        print_amber("Open Library override")
        smart_print("")
        print_dark_grey("Paste a work/edition URL or id, then press Enter.")
        print_dark_grey("Examples:")
        smart_print(
            Tinta().dark_grey("  ").to_str() + tint_path("https://openlibrary.org/works/OL45804W")
        )
        smart_print(Tinta().dark_grey("  ").to_str() + tint_path("OL45804W"))
        print_dark_grey("Leave blank to cancel.")
        smart_print("")
        raw = input(Tinta().amber("OL ref ").dark_grey(": ").to_str()).strip()
    except (EOFError, KeyboardInterrupt):
        smart_print("")
        return None
    return raw or None


def print_ol_session_notice(*, no_ol: bool = False) -> None:
    """Session-level Open Library status (below auto-recursive, once)."""
    if no_ol:
        print_dark_grey("openlibrary  (disabled via --no-ol)")
        return
    ua = (os.environ.get("OPEN_LIBRARY_USER_AGENT") or "").strip()
    if not ua:
        print_dark_grey("openlibrary unavailable (set OPEN_LIBRARY_USER_AGENT to enable)")


def apply_fix(
    plan: FixPlan, *, dry_run: bool = True, cli: CliPaths | None = None, quiet: bool = False
) -> None:
    tags = {
        "title": plan.desired_title,
        "album": plan.desired_album,
        "artist": plan.desired_author,
        "albumartist": plan.desired_author,
        "date": plan.desired_date,
        "composer": plan.desired_narrator or "",
    }

    if dry_run:
        print_plan(plan, label="dry-run", cli=cli)
        return

    target = plan.m4b
    if plan.needs_tag_write:
        write_id3_tags_mutagen(target, tags)
        if not quiet:
            print_green(f"  ✓ wrote tags → [[{target.name}]]", highlight_color=LIGHT_GREY_COLOR)

    if plan.rename_m4b_to:
        if plan.rename_m4b_to.exists() and plan.rename_m4b_to.resolve() != target.resolve():
            print_orange(f"  ⚠ SKIP rename, target exists: [[{plan.rename_m4b_to.name}]]")
        else:
            target.rename(plan.rename_m4b_to)
            target = plan.rename_m4b_to
            plan.m4b = target
            if not quiet:
                print_green(f"  ✓ renamed m4b → [[{target.name}]]", highlight_color=LIGHT_GREY_COLOR)

    desc_out = plan.rename_desc_to or plan.desc_txt
    if desc_out is None:
        desc_out = target.with_name(f"{plan.desired_stem}.txt")
    if plan.desc_txt and plan.rename_desc_to and plan.desc_txt.exists():
        if plan.rename_desc_to.exists() and plan.rename_desc_to.resolve() != plan.desc_txt.resolve():
            _write_desc(plan, plan.rename_desc_to)
            plan.desc_txt.unlink(missing_ok=True)
            if not quiet:
                print_green(
                    f"  ✓ rewrote+renamed desc → [[{plan.rename_desc_to.name}]]",
                    highlight_color=LIGHT_GREY_COLOR,
                )
        else:
            plan.desc_txt.rename(plan.rename_desc_to)
            _write_desc(plan, plan.rename_desc_to)
            if not quiet:
                print_green(
                    f"  ✓ renamed+rewrote desc → [[{plan.rename_desc_to.name}]]",
                    highlight_color=LIGHT_GREY_COLOR,
                )
    else:
        _write_desc(plan, desc_out)
        if not quiet:
            print_green(f"  ✓ wrote desc → [[{desc_out.name}]]", highlight_color=LIGHT_GREY_COLOR)


def _child_dirs(d: Path) -> list[Path]:
    try:
        return sorted(c for c in d.iterdir() if c.is_dir() and not c.name.startswith("."))
    except OSError:
        return []


def _descendant_book_dirs(root: Path, *, max_depth: int = _MAX_RECURSE_DEPTH) -> list[Path]:
    """Dirs under *root* (not including root) that directly contain audio."""
    found: list[Path] = []

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        for child in _child_dirs(d):
            if _has_audio(child):
                found.append(child)
            else:
                walk(child, depth + 1)

    walk(root, 1)
    return found


def iter_book_dirs(paths: Iterable[Path], *, recursive: bool) -> list[Path]:
    """Collect book dirs with smart / explicit recursion.

    - No audio + nested book dirs → auto-recursive (notice printed).
    - Audio here + child book dirs → this dir only unless ``recursive``; warn if not.
    - Explicit ``recursive`` → include descendant book dirs.
    """
    out: list[Path] = []

    for p in paths:
        p = p.resolve()
        if not p.exists():
            print_orange(f"Path does not exist: [[{p}]]\n")
            continue
        if p.is_file():
            out.append(p.parent)
            continue

        has_here = _has_audio(p)
        child_with_audio = [c for c in _child_dirs(p) if _has_audio(c)]
        descendants = _descendant_book_dirs(p)

        if has_here and child_with_audio:
            out.append(p)
            if recursive:
                for d in descendants:
                    out.append(d)
            else:
                print_amber(
                    f"warn: [[{p.name}]] also has {len(child_with_audio)} child book dir(s); "
                    f"pass --recursive to include them",
                    highlight_color=LIGHT_GREY_COLOR,
                )
        elif has_here:
            out.append(p)
            if recursive and descendants:
                for d in descendants:
                    out.append(d)
        else:
            if descendants:
                if not recursive:
                    print_dark_grey(
                        f"Recursively processing: [[{p.name}]] — {len(descendants)} nested book dir(s)"
                    )
                for d in descendants:
                    out.append(d)
            else:
                print_orange(f"skip: no book dirs under [[{p}]]")

    seen: set[Path] = set()
    uniq: list[Path] = []
    for d in out:
        d = d.resolve()
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def _scope_for_book(book_dir: Path, scopes: list[Path]) -> Path:
    """Pick the narrowest input scope that contains *book_dir*."""
    book_dir = book_dir.resolve()
    matches = []
    for s in scopes:
        s = s.resolve()
        if book_dir == s or _is_under(book_dir, s):
            matches.append(s)
    if not matches:
        return book_dir
    return max(matches, key=lambda p: len(p.parts))


def _banner_fixing_clause(need_n: int, total_n: int) -> str:
    """Human phrase for how many books need fixing in a scan."""
    if need_n <= 0:
        return "No books need fixing"
    verb = "needs" if need_n == 1 else "need"
    if need_n == total_n:
        return f"{need_n} {verb} fixing"
    return f"{need_n} of {total_n} {verb} fixing"


def _banner_missing_clause(failed: int) -> str:
    if failed <= 0:
        return "No missing source files"
    unit = "file" if failed == 1 else "files"
    return f"{failed} missing source {unit}"


def _format_mode_banner(mode_label: str, need_n: int, total_n: int, failed: int) -> str:
    """Mode // needs-fixing · missing-sources (omit missing when both are zero)."""
    fixing = _banner_fixing_clause(need_n, total_n)
    if need_n <= 0 and failed <= 0:
        return f"{mode_label} // {fixing}"
    return f"{mode_label} // {fixing} · {_banner_missing_clause(failed)}"


def _format_planning_progress(i: int, total: int, name: str) -> str:
    """Progress line for the eager plan_fix loop."""
    return f"Planning {i}/{total} · {name}"


def _planning_progress_width() -> int:
    return min(100, max(40, shutil.get_terminal_size((100, 20)).columns - 1))


def _print_planning_progress(i: int, total: int, name: str) -> None:
    """Overwrite-friendly planning progress (dark grey; cleared when done)."""
    from tinta import Tinta

    line = _format_planning_progress(i, total, name)
    width = _planning_progress_width()
    shown = line if len(line) <= width else line[: width - 1] + "…"
    padded = f"{shown:<{width}}"
    colored = Tinta().dark_grey(padded, sep="").to_str()
    sys.stdout.write(f"\r{colored}")
    sys.stdout.flush()


def _clear_planning_progress() -> None:
    width = _planning_progress_width()
    sys.stdout.write(f"\r{' ' * width}\r")
    sys.stdout.flush()


class _FixMetadataParser(argparse.ArgumentParser):
    """Friendlier argparse errors — no usage wall, colored message."""

    def error(self, message: str) -> None:
        # Avoid stock "prog: error:" + full usage dump.
        smart_print("")
        msg = (message or "").strip()
        if msg.lower().startswith("unrecognized arguments:"):
            bad = msg.split(":", 1)[1].strip()
            print_red("Unrecognized argument(s)")
            print_red(f"  [[{bad}]]")
        elif msg.lower().startswith("the following arguments are required:"):
            need = msg.split(":", 1)[1].strip()
            print_red("Missing required argument(s)")
            print_red(f"  [[{need}]]")
        else:
            print_red(msg)
        usage = self.format_usage().strip()
        if usage.lower().startswith("usage:"):
            usage = usage[6:].strip()
        print_dark_grey(f"Usage:  {usage}")
        print_dark_grey(f"Help:   {self.prog} -h")
        self.exit(2)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = _FixMetadataParser(
        prog="fix_metadata",
        description=(
            "Correct ID3 tags, m4b filenames, and companion .txt for converted audiobooks "
            "(no re-encode). Defaults to CLI_CONVERTED_FOLDER with smart recursion; "
            "resolves source audio from archive or -s/--source."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Book/author folder(s); relative paths resolve under converted. Default: converted root",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Include child book dirs when the path itself is also a book (mixed folders)",
    )
    parser.add_argument(
        "-s",
        "--source",
        type=Path,
        default=None,
        metavar="PATH",
        help="Unconverted originals root; relative nesting must match the converted scope",
    )
    parser.add_argument(
        "-o",
        "--ol",
        dest="ol_ref",
        default=None,
        metavar="URL_OR_ID",
        help="Force Open Library work/edition (URL or OL…W / OL…M); requires a single book target",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="GLOB",
        help="Ignore matching filenames (repeatable), e.g. --ignore '*.bak'",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write tags / rename files (default is dry-run only)",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Show each planned fix and prompt before applying (implies write; default answer is skip)",
    )
    parser.add_argument(
        "--no-ol",
        action="store_true",
        help="Skip automatic Open Library lookup (still allows -o / interactive o)",
    )
    parser.add_argument(
        "--minimalist",
        action="store_true",
        help="Prefer core titles; strip series/Book N/(Unabridged) junk (or set CLI_MINIMALIST=1)",
    )
    parser.add_argument(
        "--no-minimalist",
        action="store_true",
        help="Disable minimalist title mode even if CLI_MINIMALIST is set",
    )
    parser.add_argument("--debug", action="store_true", help="Verbose debug")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    interactive = bool(args.interactive)
    dry_run = not (args.apply or interactive)
    minimalist = resolve_minimalist(flag_on=args.minimalist, flag_off=args.no_minimalist)

    cli = resolve_cli_paths()
    if cli.converted or cli.archive or args.source:
        print_dark_grey("─" * 60)
    if cli.converted:
        print_grey(f"converted  {tint_path(cli.converted)}")
    if cli.archive:
        print_grey(f"archive    {tint_path(cli.archive)}")
    if args.source:
        print_grey(f"source     {tint_path(args.source.resolve())}")
    if cli.converted or cli.archive or args.source:
        print_dark_grey("─" * 60)

    try:
        target_paths = resolve_target_paths(list(args.paths), cli)
    except SystemExit as e:
        print_red(str(e))
        return 1

    book_dirs = iter_book_dirs(target_paths, recursive=args.recursive)
    if not book_dirs:
        print_orange("No book folders found.")
        return 1

    print_ol_session_notice(no_ol=bool(args.no_ol))

    source_root = args.source.resolve() if args.source else None
    if source_root is not None and not source_root.exists():
        print_red(f"source path does not exist: [[{source_root}]]")
        return 1

    ol_ref = args.ol_ref
    if ol_ref and len(book_dirs) != 1:
        print_red(
            f"-o/--ol requires a single book target, but {len(book_dirs)} book dir(s) were selected"
        )
        return 1

    # Interactive and forced-OL can retag from folder/m4b alone (no archive source).
    require_source = not (interactive or bool(ol_ref))
    # Interactive (without forced -o): local scan first; OL attaches per book on review.
    defer_ol = interactive and not bool(ol_ref)
    lookup_ol_upfront = (not args.no_ol or bool(ol_ref)) and not defer_ol

    plans: list[FixPlan] = []
    failures: list[SourceResolutionError] = []
    total_dirs = len(book_dirs)
    for idx, d in enumerate(book_dirs, start=1):
        _print_planning_progress(idx, total_dirs, d.name)
        scope = _scope_for_book(d, target_paths)
        try:
            plan = plan_fix(
                d,
                ignore_globs=args.ignore,
                cli=cli,
                scope_root=scope,
                source_root=source_root,
                debug=args.debug,
                require_source=require_source,
                ol_ref=ol_ref,
                lookup_ol=lookup_ol_upfront,
                minimalist=minimalist,
            )
        except SourceResolutionError as e:
            failures.append(e)
            continue
        if plan:
            plans.append(plan)
        elif args.debug:
            _clear_planning_progress()
            print_debug(f"ok / no changes: {d.name}")

    _clear_planning_progress()
    smart_print("")

    failed = len(failures)
    if failures:
        smart_print("")
        print_red("Can't find source files")
        for err in failures:
            print_source_failure(err, cli)
        smart_print("")

    # Interactive defer-OL: attach OL to local candidates before the banner so
    # "needs fixing" matches what you'll actually be prompted for.
    if defer_ol and not args.no_ol:
        kept: list[FixPlan] = []
        for plan in plans:
            _attach_open_library(plan, apply_ol_tags=False, minimalist=minimalist)
            if plan.needs_work:
                kept.append(plan)
        plans = kept

    if interactive:
        mode_label = "Interactive"
        mode_print = print_banana
    elif dry_run:
        mode_label = "Dry-run"
        mode_print = print_mint
    else:
        mode_label = "Applying"
        mode_print = print_green

    total_n = len(book_dirs)
    mode_print(_format_mode_banner(mode_label, len(plans), total_n, failed))

    last_book_printed_done = False
    for i, plan in enumerate(plans):
        if dry_run:
            apply_fix(plan, dry_run=True, cli=cli)
            continue

        if interactive:
            while True:
                print_plan(plan, label="propose", cli=cli)
                choice = prompt_apply(plan)
                if choice in ("q", "interrupt"):
                    # smart_print collapses consecutive empties; force a blank gap
                    print()
                    from tinta import Tinta

                    smart_print(Tinta().light_pink("Meow.").to_str())
                    smart_print("")
                    if failed:
                        return 1
                    return 0
                if choice == "s":
                    print_dark_grey("(skipped)")
                    last_book_printed_done = False
                    break
                if choice == "o":
                    ref = prompt_ol_ref()
                    if not ref:
                        print_dark_grey("  (cancelled — showing proposal again)")
                        continue
                    _attach_open_library(
                        plan, ol_ref=ref, apply_ol_tags=True, minimalist=minimalist
                    )
                    if plan.ol_status != "forced":
                        print_orange("  Could not apply that Open Library ref; try again or skip.")
                    continue
                if choice == "m":
                    if plan.ol_status != "low_confidence":
                        print_orange("  No low-confidence Open Library match to accept.")
                        continue
                    _apply_ol_fields_to_desired(plan)
                    plan.ol_status = "forced"
                    print_mint("  Using Open Library match", highlight_color=LIGHT_GREY_COLOR)
                    continue
                if choice == "y":
                    apply_fix(plan, dry_run=False, cli=cli, quiet=True)
                    # smart_print collapses consecutive empties; match conversion spacing
                    print()
                    from tinta import Tinta

                    smart_print(Tinta().light_grey("Done ", sep="").mint("✓", sep="").to_str())
                    print()
                    last_book_printed_done = i == len(plans) - 1
                    if i < len(plans) - 1:
                        # print_plan leads with one blank; do not add another here
                        divider()
                    break
            continue

        print_mint(f"fixing [[{plan.book_dir.name}]]", highlight_color=LIGHT_GREY_COLOR)
        apply_fix(plan, dry_run=False, cli=cli)

    smart_print("")
    if dry_run and plans:
        print_dark_grey("Re-run with --apply to write changes, or -i to confirm each fix.")
    elif (interactive or not dry_run) and not last_book_printed_done:
        from tinta import Tinta

        smart_print(Tinta().light_grey("Done ", sep="").mint("✓", sep="").to_str())

    if failed:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        smart_print("")
        from tinta import Tinta

        smart_print(Tinta().light_pink("Meow.").to_str())
        sys.exit(130)
