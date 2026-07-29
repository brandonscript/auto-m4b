"""Fix ID3 tags + filenames for already-converted m4b files (no re-encode).

Usage examples::

    poetry run python -m src.fix_metadata --dry-run \\
      "/media/.../#plex/Le Guin, Ursula K." --recursive

    poetry run python -m src.fix_metadata --apply \\
      "/media/.../#plex/French, Tana/The Searcher (2020)"

    poetry run python -m src.fix_metadata --apply --ignore "*.bak" PATH
"""

from __future__ import annotations

import argparse
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

_YEAR_SUFFIX = re.compile(r"\s*\(\d{4}\)\s*$")
_NARRATOR_BRACKET = re.compile(r"\s*\[[^\]]+\]")
_SERIES_PREFIX = re.compile(r"^(.+?)\s+-\s+(.+)$")
_COLLECTIONS_PREFIX = re.compile(r"^\[Collections\]\s*", re.I)
_QUALITY_TXT = re.compile(r"^(.+?)\s+\[.+kbps.+\].txt$", re.I)


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
    # Narrator brackets — keep last for narrator parse, strip for title.
    s = _NARRATOR_BRACKET.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # "Series NN - Title" → Title
    m = _SERIES_PREFIX.match(s)
    if m and not re.search(r"\bCycle\b|\bTrilogy\b|\bSeries\b", m.group(2), re.I):
        # Prefer right side when left looks like series (has digits or known words)
        left, right = m.group(1), m.group(2)
        if re.search(r"\d", left) or re.search(r"\b(Cycle|Trilogy|Annals|Catwings|Orsinia|Hainish)\b", left, re.I):
            s = right
    elif m and re.search(r"\d", m.group(1)):
        s = m.group(2)
    return s.strip(" -")


def folder_narrator_hint(folder_name: str) -> str:
    brackets = _NARRATOR_BRACKET.findall(folder_name)
    if not brackets:
        return ""
    # Last bracket is usually narrator; skip [AB], [Boxed Set], [Collections], etc.
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

    # Title: prefer source ID3 title over album when they differ; else folder hint.
    # If source title looks unrelated to the folder story name, trust the folder.
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

    # Author: source albumartist/artist, else parent folder, else current if matches parent.
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
        # Only keep current if it agrees with parent/source hints
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

    # If current author disagrees with preferred, note it.
    cur_author = current.albumartist or current.artist or ""
    if cur_author and fuzz.token_set_ratio(cur_author, author) / 100 < 0.5:
        reasons.append(f"author {cur_author!r} → {author!r}")

    if current.title and fuzz.token_set_ratio(current.title, title) / 100 < 0.55:
        reasons.append(f"title {current.title!r} → {title!r}")

    album = title  # audiobook convention: album == title

    # Date: prefer source year.
    date = ""
    if source and source.date:
        date = source.date
        if _year(current.date) and _year(current.date) != _year(date):
            reasons.append(f"date {_year(current.date)} → {_year(date)}")
    elif current.date:
        date = current.date

    # Narrator: folder bracket if not the author; never keep author-as-narrator.
    narrator = ""
    if folder_narr and fuzz.token_set_ratio(folder_narr, author) / 100 < 0.5:
        # Bracket may be last name only — keep as-is (better than wrong author).
        narrator = folder_narr
    # If m4b composer is author, clear it.
    if current.composer and fuzz.token_set_ratio(current.composer, author) / 100 >= 0.7:
        reasons.append(f"clear narrator/composer {current.composer!r} (was author)")
        narrator = narrator  # keep folder narrator if any
    elif current.composer and not narrator:
        # Keep existing composer only if it doesn't look like the wrong OL author
        # and isn't the preferred author.
        if fuzz.token_set_ratio(current.composer, author) / 100 < 0.5:
            # Drop if it looks like it was the preferred author demoted (same as preferred)
            pass

    return title, author, album, date, narrator, reasons


def _looks_like_title(name: str, title: str) -> bool:
    if not name or not title:
        return False
    return fuzz.token_set_ratio(name, title) / 100 >= 0.85


def _find_source_and_m4b(
    book_dir: Path,
    ignore_globs: list[str],
) -> tuple[Path | None, Path | None]:
    import fnmatch

    files = [p for p in book_dir.iterdir() if p.is_file()]
    filtered: list[Path] = []
    for p in files:
        if any(fnmatch.fnmatch(p.name, g) for g in ignore_globs):
            continue
        filtered.append(p)

    sources = [p for p in filtered if p.suffix.lower() in _SOURCE_EXTS]
    m4bs = [p for p in filtered if p.suffix.lower() in _OUTPUT_EXTS]

    source = max(sources, key=lambda p: p.stat().st_size) if sources else None
    m4b = max(m4bs, key=lambda p: p.stat().st_size) if m4bs else None
    return source, m4b


def _find_desc_txt(book_dir: Path, m4b: Path) -> Path | None:
    # Prefer txt matching m4b stem quality pattern; else any [*kbps*].txt
    candidates = list(book_dir.glob("*.txt"))
    for p in candidates:
        if p.stem.startswith(m4b.stem) or m4b.stem in p.stem:
            return p
    for p in candidates:
        if _QUALITY_TXT.match(p.name):
            return p
    return None


def plan_fix(book_dir: Path, ignore_globs: list[str] | None = None) -> FixPlan | None:
    ignore_globs = ignore_globs or []
    if not book_dir.is_dir():
        return None
    source_path, m4b = _find_source_and_m4b(book_dir, ignore_globs)
    if not m4b:
        return None

    source = TagSnapshot.from_file(source_path) if source_path else None
    current = TagSnapshot.from_file(m4b)
    title, author, album, date, narrator, reasons = _pick_desired(book_dir, source, current)

    stem = safe_filename(title)
    rename_to = m4b.with_name(f"{stem}.m4b") if stem and m4b.stem != stem else None
    if rename_to == m4b:
        rename_to = None

    desc = _find_desc_txt(book_dir, m4b)
    rename_desc = None
    if desc and rename_to:
        # Preserve [quality] suffix if present
        m = _QUALITY_TXT.match(desc.name)
        if m:
            quality_part = desc.name[len(m.group(1)) :]  # includes leading space + [quality].txt
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
    # Try to preserve quality line from existing desc or filename.
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
                    # first Size: is converted
                    if "Duration:" in old.split(line)[0]:
                        size = line.split(":", 1)[1].strip() or size
                elif line.startswith("(Original)"):
                    orig_block = "\n".join(old.split("(Original)")[1:]).strip()
                    break
        except OSError:
            pass
    if not orig_block and plan.source:
        orig_block = f"File name: {plan.source.name}\nFormat: {plan.source.suffix.lstrip('.') or 'N/A'}\nSize: N/A"

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
        smart_print(f"[dry-run] {plan.book_dir.name}")
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
            smart_print(f"  rename desc: {plan.desc_txt.name if plan.desc_txt else '?'} → {plan.rename_desc_to.name}")
        elif plan.desc_txt:
            smart_print(f"  rewrite desc: {plan.desc_txt.name}")
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
        # Create a simple companion txt next to m4b
        desc_out = target.with_name(f"{plan.desired_stem}.txt")
    if plan.desc_txt and plan.rename_desc_to and plan.desc_txt.exists():
        if plan.rename_desc_to.exists() and plan.rename_desc_to.resolve() != plan.desc_txt.resolve():
            # Write new, remove old if different
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


def iter_book_dirs(paths: Iterable[Path], *, recursive: bool) -> list[Path]:
    out: list[Path] = []

    def _has_audio(d: Path) -> bool:
        try:
            return any(c.suffix.lower() in _AUDIO_EXTS for c in d.iterdir() if c.is_file())
        except OSError:
            return False

    for p in paths:
        p = p.resolve()
        if not p.exists():
            smart_print(f"skip missing path: {p}")
            continue
        if p.is_file():
            out.append(p.parent)
            continue
        # Book folder (has audio here) — always include, even with --recursive.
        if _has_audio(p):
            out.append(p)
            continue
        if recursive:
            for child in sorted(p.iterdir()):
                if child.is_dir() and not child.name.startswith(".") and _has_audio(child):
                    out.append(child)
        else:
            out.append(p)
    # Dedupe preserving order
    seen: set[Path] = set()
    uniq: list[Path] = []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.fix_metadata",
        description="Correct ID3 tags, m4b filenames, and companion .txt for converted audiobooks (no re-encode).",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Book folder(s), or an author folder with --recursive",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help="Treat each path as an author/library folder and process child book dirs",
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
    parser.add_argument("--debug", action="store_true", help="Verbose debug")

    args = parser.parse_args(argv)
    dry_run = not args.apply

    book_dirs = iter_book_dirs(args.paths, recursive=args.recursive)
    if not book_dirs:
        smart_print("No book folders found.")
        return 1

    plans: list[FixPlan] = []
    for d in book_dirs:
        plan = plan_fix(d, ignore_globs=args.ignore)
        if plan:
            plans.append(plan)
        elif args.debug:
            print_debug(f"ok / no changes: {d.name}")

    smart_print(f"{'Dry-run' if dry_run else 'Applying'}: {len(plans)} book(s) need fixes ({len(book_dirs)} scanned)")
    for plan in plans:
        if not dry_run:
            smart_print(f"fixing {plan.book_dir.name}")
        apply_fix(plan, dry_run=dry_run)

    if dry_run and plans:
        smart_print("\nRe-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
