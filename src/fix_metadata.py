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
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from mutagen import File as MutagenFile
from rapidfuzz import fuzz

from src.lib.fs_utils import safe_filename
from src.lib.id3_utils import write_id3_tags_mutagen
from src.lib.term import print_debug, smart_print

_SOURCE_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wav"}
_OUTPUT_EXTS = {".m4b"}
_AUDIO_EXTS = _SOURCE_EXTS | _OUTPUT_EXTS
_MAX_RECURSE_DEPTH = 4

_YEAR_SUFFIX = re.compile(r"\s*\(\d{4}\)\s*$")
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

    @property
    def needs_tag_write(self) -> bool:
        cur = self.current
        date_changed = bool(self.desired_date) and _year(cur.date) != _year(self.desired_date)
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
    def needs_work(self) -> bool:
        return self.needs_tag_write or self.needs_rename or bool(self.desc_txt)


def _year(date: str) -> str:
    m = re.search(r"(\d{4})", date or "")
    return m.group(1) if m else ""


def _last_first_to_first_last(name: str) -> str:
    name = (name or "").strip()
    if "," not in name:
        return name
    last, first = name.split(",", 1)
    return f"{first.strip()} {last.strip()}".strip()


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
    return _last_first_to_first_last(parent)


def _title_usable(title: str) -> bool:
    t = (title or "").strip()
    if not t or len(t) < 2:
        return False
    if t.isdigit():
        return False
    return True


def _pick_desired(
    book_dir: Path,
    source: TagSnapshot | None,
    current: TagSnapshot,
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

    src_author = ""
    if source:
        src_author = source.albumartist or source.artist or ""
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

    date = ""
    if source and source.date:
        date = source.date
        if _year(current.date) and _year(current.date) != _year(date):
            reasons.append(f"date {_year(current.date)} → {_year(date)}")
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
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


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


def _source_audio_file(source_dir: Path, ignore_globs: list[str]) -> Path | None:
    """Largest taggable audio in a source dir (prefer non-m4b, else any audio)."""
    pref = _largest_audio(source_dir, ignore_globs, exts=_SOURCE_EXTS)
    if pref:
        return pref
    return _largest_audio(source_dir, ignore_globs, exts=_AUDIO_EXTS)


def plan_fix(
    book_dir: Path,
    ignore_globs: list[str] | None = None,
    *,
    cli: CliPaths | None = None,
    scope_root: Path | None = None,
    source_root: Path | None = None,
    debug: bool = False,
    require_source: bool = True,
) -> FixPlan | None:
    """Build a fix plan for one book dir.

    Raises SourceResolutionError when ``require_source`` and no source can be resolved.
    Returns None when the book needs no changes.
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

    if require_source:
        src_dir = resolve_source_dir(
            book_dir,
            beside_source=beside_source,
            cli=cli,
            scope_root=scope_root,
            source_root=source_root,
            debug=debug,
        )
        if beside_source and src_dir == book_dir:
            source_path = beside_source
        else:
            source_path = _source_audio_file(src_dir, ignore_globs)
            if source_path is None:
                raise SourceResolutionError(book_dir, f"no audio files in source dir {src_dir}")
            if src_dir != book_dir:
                reasons_prefix = f"source from {src_dir}"
        source_snap = TagSnapshot.from_file(source_path)
    elif beside_source:
        source_path = beside_source
        source_snap = TagSnapshot.from_file(beside_source)

    current = TagSnapshot.from_file(m4b)
    title, author, album, date, narrator, reasons = _pick_desired(book_dir, source_snap, current)
    if reasons_prefix:
        reasons.insert(0, reasons_prefix)

    stem = safe_filename(title)
    rename_to = m4b.with_name(f"{stem}.m4b") if stem and m4b.stem != stem else None
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
    )
    if desc and _desc_needs_rewrite(desc, plan):
        if "update description txt contents" not in plan.reasons:
            plan.reasons.append("update description txt contents")
    if not plan.needs_tag_write and not plan.needs_rename and not (
        desc and _desc_needs_rewrite(desc, plan)
    ):
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


def print_plan(plan: FixPlan, *, label: str = "dry-run") -> None:
    """Print a human-readable summary of the planned fix."""
    smart_print(f"[{label}] {plan.book_dir.name}")
    for r in plan.reasons:
        smart_print(f"  - {r}")
    if plan.needs_tag_write:
        smart_print(
            f"  tags: title={plan.desired_title!r} author={plan.desired_author!r} "
            f"date={plan.desired_date!r} narrator={plan.desired_narrator!r}"
        )
    if plan.rename_m4b_to:
        smart_print(f"  rename: {plan.m4b.name} → {plan.rename_m4b_to.name}")
    if plan.rename_desc_to:
        smart_print(
            f"  rename desc: {plan.desc_txt.name if plan.desc_txt else '?'} → "
            f"{plan.rename_desc_to.name}"
        )
    elif plan.desc_txt:
        smart_print(f"  rewrite desc: {plan.desc_txt.name}")


def parse_apply_prompt(raw: str) -> str:
    """Normalize an interactive prompt response to y/n/a/q (default n)."""
    s = (raw or "").strip().lower()
    if not s:
        return "n"
    if s in ("y", "yes"):
        return "y"
    if s in ("a", "all"):
        return "a"
    if s in ("q", "quit"):
        return "q"
    if s in ("n", "no", "s", "skip"):
        return "n"
    if s[0] in ("y", "a", "q", "n"):
        return s[0]
    return "n"


def prompt_apply(plan: FixPlan) -> str:
    """Ask whether to apply *plan*. Returns ``y``, ``n``, ``a`` (all), or ``q`` (quit)."""
    try:
        raw = input("  Apply this fix? [y/N/a=all/q=quit] ").strip()
    except EOFError:
        return "n"
    return parse_apply_prompt(raw)


def apply_fix(plan: FixPlan, *, dry_run: bool = True) -> None:
    tags = {
        "title": plan.desired_title,
        "album": plan.desired_album,
        "artist": plan.desired_author,
        "albumartist": plan.desired_author,
        "date": plan.desired_date,
        "composer": plan.desired_narrator or "",
    }

    if dry_run:
        print_plan(plan, label="dry-run")
        return

    target = plan.m4b
    if plan.needs_tag_write:
        write_id3_tags_mutagen(target, tags)
        smart_print(f"  wrote tags → {target.name}")

    if plan.rename_m4b_to:
        if plan.rename_m4b_to.exists() and plan.rename_m4b_to.resolve() != target.resolve():
            smart_print(f"  SKIP rename, target exists: {plan.rename_m4b_to.name}")
        else:
            target.rename(plan.rename_m4b_to)
            target = plan.rename_m4b_to
            plan.m4b = target
            smart_print(f"  renamed m4b → {target.name}")

    desc_out = plan.rename_desc_to or plan.desc_txt
    if desc_out is None:
        desc_out = target.with_name(f"{plan.desired_stem}.txt")
    if plan.desc_txt and plan.rename_desc_to and plan.desc_txt.exists():
        if plan.rename_desc_to.exists() and plan.rename_desc_to.resolve() != plan.desc_txt.resolve():
            _write_desc(plan, plan.rename_desc_to)
            plan.desc_txt.unlink(missing_ok=True)
            smart_print(f"  rewrote+renamed desc → {plan.rename_desc_to.name}")
        else:
            plan.desc_txt.rename(plan.rename_desc_to)
            _write_desc(plan, plan.rename_desc_to)
            smart_print(f"  renamed+rewrote desc → {plan.rename_desc_to.name}")
    else:
        _write_desc(plan, desc_out)
        smart_print(f"  wrote desc → {desc_out.name}")


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
            smart_print(f"skip missing path: {p}")
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
                smart_print(
                    f"warn: {p.name} also has {len(child_with_audio)} child book dir(s); "
                    f"pass --recursive to include them"
                )
        elif has_here:
            out.append(p)
            if recursive and descendants:
                for d in descendants:
                    out.append(d)
        else:
            if descendants:
                if not recursive:
                    smart_print(
                        f"auto-recursive: {p.name} has no audio but "
                        f"{len(descendants)} nested book dir(s)"
                    )
                for d in descendants:
                    out.append(d)
            else:
                smart_print(f"skip: no book dirs under {p}")

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.fix_metadata",
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
        "--recursive",
        "-r",
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
    parser.add_argument("--debug", action="store_true", help="Verbose debug")

    args = parser.parse_args(argv)
    interactive = bool(args.interactive)
    dry_run = not (args.apply or interactive)

    cli = resolve_cli_paths()
    if cli.converted:
        smart_print(f"converted: {cli.converted}")
    if cli.archive:
        smart_print(f"archive:   {cli.archive}")
    if args.source:
        smart_print(f"source:    {args.source.resolve()}")

    try:
        target_paths = resolve_target_paths(list(args.paths), cli)
    except SystemExit as e:
        smart_print(str(e))
        return 1

    book_dirs = iter_book_dirs(target_paths, recursive=args.recursive)
    if not book_dirs:
        smart_print("No book folders found.")
        return 1

    source_root = args.source.resolve() if args.source else None
    if source_root is not None and not source_root.exists():
        smart_print(f"source path does not exist: {source_root}")
        return 1

    plans: list[FixPlan] = []
    failed = 0
    for d in book_dirs:
        scope = _scope_for_book(d, target_paths)
        try:
            plan = plan_fix(
                d,
                ignore_globs=args.ignore,
                cli=cli,
                scope_root=scope,
                source_root=source_root,
                debug=args.debug,
                require_source=True,
            )
        except SourceResolutionError as e:
            smart_print(f"FAIL {e.book_dir.name}: {e.message}")
            failed += 1
            continue
        if plan:
            plans.append(plan)
        elif args.debug:
            print_debug(f"ok / no changes: {d.name}")

    if interactive:
        mode_label = "Interactive"
    elif dry_run:
        mode_label = "Dry-run"
    else:
        mode_label = "Applying"
    smart_print(
        f"{mode_label}: {len(plans)} book(s) need fixes "
        f"({len(book_dirs)} scanned, {failed} source failures)"
    )

    apply_rest = False
    applied = 0
    skipped = 0
    for plan in plans:
        if dry_run:
            apply_fix(plan, dry_run=True)
            continue

        if interactive and not apply_rest:
            print_plan(plan, label="propose")
            choice = prompt_apply(plan)
            if choice == "q":
                smart_print("Quit — remaining books left unchanged.")
                break
            if choice == "n":
                smart_print("  skipped")
                skipped += 1
                continue
            if choice == "a":
                apply_rest = True
                smart_print("  applying this and all remaining…")

        smart_print(f"fixing {plan.book_dir.name}")
        apply_fix(plan, dry_run=False)
        applied += 1

    if dry_run and plans:
        smart_print("\nRe-run with --apply to write changes, or -i to confirm each fix.")
    elif interactive:
        smart_print(f"\nDone — applied {applied}, skipped {skipped}, source failures {failed}.")
    elif not dry_run:
        smart_print(f"\nDone — applied {applied}, source failures {failed}.")

    if failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
