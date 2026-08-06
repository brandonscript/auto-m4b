"""Source-dir resolution and multi-file GCS helpers for metadata planning."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from src.lib.cleaners import clean_string
from src.lib.compare import find_greatest_common_string
from src.lib.fs_utils import try_relative_to
from src.lib.metadata.models import CliPaths, SourceResolutionError, TagSnapshot
from src.lib.metadata.pick import _title_usable
from src.lib.term import print_debug

_SOURCE_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wav"}
_OUTPUT_EXTS = {".m4b"}
_AUDIO_EXTS = _SOURCE_EXTS | _OUTPUT_EXTS

_QUALITY_TXT = re.compile(r"^(.+?)\s+\[.+kbps.+\].txt$", re.I)
_GENERIC_FILENAME = re.compile(r"^(?:track|audio|file|part|chapter)[ _-]?\d+$", re.I)


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


def source_common_title(
    source_dir: Path,
    ignore_globs: list[str] | None = None,
    *,
    _files: list[Path] | None = None,
) -> tuple[str, str]:
    """Derive a book title from multi-file sources via GCS + part/disc strip.

    Returns ``(title, reason)`` where reason is empty if nothing useful found.
    Mirrors conversion scorers: greatest common string across titles (or filenames),
    then ``clean_string`` to strip ``Part N`` / ``Disc N`` / orphaned Part.
    """
    ignore_globs = ignore_globs or []
    files = _files if _files is not None else _source_audio_files(source_dir, ignore_globs)
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


def source_common_filename(
    source_dir: Path,
    ignore_globs: list[str] | None = None,
    *,
    _files: list[Path] | None = None,
) -> str:
    """Part/disc-stripped GCS of source *filenames* (stems), for m4b rename.

    Unlike ``source_common_title``, this always prefers filenames over ID3 titles,
    so e.g. ``Author - Title, Part 1/2`` → ``Author - Title``.
    """
    ignore_globs = ignore_globs or []
    files = _files if _files is not None else _source_audio_files(source_dir, ignore_globs)
    if not files:
        return ""
    return _clean_gcs_values([f.stem for f in files])


def filename_gcs_context(filename_stem: str, book_dir: Path, title: str) -> str:
    """Choose useful filename GCS with title-directory context when needed."""
    stem = (filename_stem or "").strip()
    if not stem or _GENERIC_FILENAME.fullmatch(stem):
        return title.strip()
    folder = book_dir.name.strip()
    if folder and title and not _GENERIC_FILENAME.fullmatch(stem):
        folder_core = re.sub(r"\s*\(\d{4}\)\s*$", "", folder).strip()
        if (
            folder_core
            and folder_core.casefold() not in stem.casefold()
            and (len(stem.split()) > 1 or stem[:1].isdigit())
        ):
            return f"{folder_core} - {stem}"
    return stem


def source_files_display(
    source_dir: Path,
    ignore_globs: list[str] | None = None,
    *,
    _files: list[Path] | None = None,
) -> str:
    """``<LCS stem>.<ext>`` for Filesystem ``Original file(s)`` row.

    Extension is the most common suffix among source audio files.
    """
    ignore_globs = ignore_globs or []
    files = _files if _files is not None else _source_audio_files(source_dir, ignore_globs)
    if not files:
        return ""
    stem = _clean_gcs_values([f.stem for f in files])
    if not stem:
        return ""
    from collections import Counter

    ext = Counter(f.suffix.lower() for f in files).most_common(1)[0][0]
    return f"{stem}{ext}"


def _source_audio_file(
    source_dir: Path,
    ignore_globs: list[str],
    *,
    _files: list[Path] | None = None,
) -> Path | None:
    """Largest taggable audio in a source dir (prefer non-m4b, else any audio)."""
    files = _files if _files is not None else _source_audio_files(source_dir, ignore_globs)
    candidates = [p for p in files if p.suffix.lower() in _SOURCE_EXTS]
    pref = max(candidates, key=lambda p: p.stat().st_size, default=None)
    if pref:
        return pref
    return max(files, key=lambda p: p.stat().st_size, default=None)

