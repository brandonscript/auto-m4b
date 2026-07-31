"""Folder / path priors for metadata planning."""

from __future__ import annotations

import re
from pathlib import Path

from src.lib.fs_utils import try_relative_to
from src.lib.metadata.models import CliPaths
from src.lib.parsers import swap_firstname_lastname

_YEAR_SUFFIX = re.compile(r"\s*\(\d{4}\)\s*$")
_FOLDER_YEAR = re.compile(r"\((\d{4})\)\s*$")
_NARRATOR_BRACKET = re.compile(r"\s*\[[^\]]+\]")
_SERIES_PREFIX = re.compile(r"^(.+?)\s+-\s+(.+)$")
_COLLECTIONS_PREFIX = re.compile(r"^\[Collections\]\s*", re.I)


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


def _is_cli_root(path: Path, cli: CliPaths | None) -> bool:
    """True when *path* is the converted / archive / inbox root from CLI env."""
    if cli is None:
        return False
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in (cli.converted, cli.archive, cli.inbox):
        if root is None:
            continue
        try:
            if resolved == root.resolve():
                return True
        except OSError:
            continue
    return False


def _rel_under_converted(book_dir: Path, cli: CliPaths | None) -> Path | None:
    """Relative path of *book_dir* under CLI converted root, or None."""
    if cli is None or cli.converted is None:
        return None
    try:
        return try_relative_to(book_dir.resolve(), cli.converted.resolve())
    except OSError:
        return None


def _loose_m4b_in_author_folder(book_dir: Path, cli: CliPaths | None = None) -> bool:
    """True when *book_dir* is a direct child of the converted root.

    Layout: ``{converted}/Author/*.m4b`` — no nested book folder. Relative path
    under converted has exactly one part (not ``.`` / empty = at the root itself).
    """
    rel = _rel_under_converted(book_dir, cli)
    if rel is None:
        return False
    # At converted root → not an author folder
    if str(rel) in (".", ""):
        return False
    return len(rel.parts) == 1


def parent_author_hint(book_dir: Path, cli: CliPaths | None = None) -> str:
    """Author from parent folder name — never the converted/archive/inbox root."""
    if _is_cli_root(book_dir, cli):
        return ""
    parent = book_dir.parent
    if _is_cli_root(parent, cli):
        return ""
    name = parent.name.strip()
    if not name or name.startswith("#"):
        return ""
    return swap_firstname_lastname(name)


def filesystem_extracted(
    book_dir: Path, cli: CliPaths | None = None
) -> tuple[str, str, str, str]:
    """Title / author / date / narrator priors from folder path alone."""
    if _loose_m4b_in_author_folder(book_dir, cli):
        # {converted}/Author/*.m4b — folder is author, not title.
        author = swap_firstname_lastname(book_dir.name.strip())
        return "", author, "", folder_narrator_hint(book_dir.name)
    title = folder_title_hint(book_dir.name)
    author = parent_author_hint(book_dir, cli)
    narrator = folder_narrator_hint(book_dir.name)
    ym = _FOLDER_YEAR.search(book_dir.name)
    date = ym.group(1) if ym else ""
    return title, author, date, narrator

