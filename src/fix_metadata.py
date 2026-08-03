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
import copy
import os
import shutil
import sys
from pathlib import Path
from collections.abc import Iterable
from typing import NoReturn

from rapidfuzz import fuzz

from src.lib.cleaners import minimalist_title
from src.lib.metadata import (
    CliPaths,
    FixPlan,
    SourceResolutionError,
    TagSnapshot,
    apply_fix,
    filesystem_extracted,
    folder_narrator_hint,
    folder_title_hint,
    map_source_dir,
    parent_author_hint,
    plan_fix,
    resolve_minimalist,
    resolve_source_dir,
    source_common_filename,
    source_common_title,
    source_files_display,
)
from src.lib.metadata.ol_attach import (
    _apply_date_consensus,
    _apply_ol_fields_to_desired,
    _attach_open_library,
    _year_consensus,
)
from src.lib.metadata.priors import _is_cli_root, _loose_m4b_in_author_folder
from src.lib.metadata.sources import _has_audio, _is_under
from src.lib.metadata.sources import _QUALITY_TXT
from src.lib.metadata.plan import _apply_cleanup_filename
from src.lib.metadata.stem import _stem_matches_book_title
from src.lib.parsers import get_year_from_date
from src.lib.fs_utils import ensure_audio_ext, safe_filename
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
    print_pink,
    print_red,
    smart_print,
    tint_path,
)

_MAX_RECURSE_DEPTH = 4

# Re-exports for existing tests that import from src.fix_metadata
__all__ = [
    "CliPaths",
    "FixPlan",
    "SourceResolutionError",
    "TagSnapshot",
    "apply_fix",
    "filesystem_extracted",
    "folder_narrator_hint",
    "folder_title_hint",
    "iter_book_dirs",
    "map_source_dir",
    "minimalist_title",
    "parent_author_hint",
    "parse_apply_prompt",
    "plan_fix",
    "print_plan",
    "resolve_cli_paths",
    "resolve_minimalist",
    "resolve_source_dir",
    "resolve_target_paths",
    "source_common_filename",
    "source_common_title",
    "source_files_display",
    # Private helpers re-exported for existing tests
    "_apply_date_consensus",
    "_apply_ol_fields_to_desired",
    "_attach_open_library",
    "_banner_fixing_clause",
    "_banner_missing_clause",
    "_format_mode_banner",
    "_format_planning_progress",
    "_id3_already_correct_style",
    "_is_cli_root",
    "_loose_m4b_in_author_folder",
    "_prop_equal",
    "_stem_matches_book_title",
    "_truth_props",
    "_year_consensus",
]


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
    description_update: bool = False,
) -> None:
    """Print Proposed fixes with aligned tag columns; rename on its own line.

    Each tag row is ``(label, old_raw, new_raw, is_date)``.
    *unknown* (both empty): dark grey ``(unknown)`` only, no arrow.
    *missing* (old empty, new set): ``(missing) » new``.
    """
    from tinta import Tinta

    if not tag_rows and not rename and not description_update:
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
    if description_update:
        smart_print(
            Tinta()
            .banana("│ ", sep="")
            .grey("Conversion log needs updating", sep="")
            .to_str()
        )
    _framed_footer(style="banana")


def _print_proposed_plan(plan: FixPlan, *, show_rename: bool = True) -> None:
    """Print the consolidated proposed-fixes block for a plan."""
    cur = plan.current
    artist_diff = not _prop_equal(cur.artist, plan.desired_author)
    albumartist_diff = not _prop_equal(cur.albumartist, plan.desired_author)
    if artist_diff:
        author_display = cur.artist
    elif albumartist_diff:
        author_display = cur.albumartist
    else:
        author_display = cur.albumartist or cur.artist
    title_diff = not _prop_equal(cur.title, plan.desired_title)
    album_diff = not _prop_equal(cur.album, plan.desired_album)
    title_display = cur.title if title_diff or not album_diff else cur.album
    tag_rows: list[tuple[str, str | None, str | None, bool]] = [
        ("Title", title_display, plan.desired_title, False),
        ("Author", author_display, plan.desired_author, False),
        (
            "Date",
            get_year_from_date(cur.date) or cur.date,
            get_year_from_date(plan.desired_date) or plan.desired_date,
            True,
        ),
        ("Narrator", cur.composer, plan.desired_narrator, False),
    ]
    rename = None
    if show_rename and plan.rename_m4b_to:
        rename = (plan.m4b.name, plan.rename_m4b_to.name)
    _print_proposed_block(
        tag_rows,
        rename=rename,
        description_update=plan.needs_desc_rewrite,
    )


def print_plan(
    plan: FixPlan,
    *,
    label: str = "dry-run",
    cli: CliPaths | None = None,
    proposed_only: bool = False,
    show_rename: bool = True,
) -> None:
    """Print review blocks + consolidated proposed fixes (mockup layout)."""
    from tinta import Tinta

    del label, cli  # layout is the same for propose / dry-run
    truth = _truth_props(plan)

    if proposed_only:
        _print_proposed_plan(plan, show_rename=show_rename)
        return

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
                    .purple(plan.ol_url, sep="")
                    .to_str()
                )
        _framed_footer(style="light_grey")

    if plan.goodreads_status in ("match", "forced", "none", "low_confidence", "error"):
        header = "goodreads (forced)" if plan.goodreads_status == "forced" else "goodreads"
        _framed_header(header, style="light_grey")
        if plan.goodreads_status in ("none", "error"):
            message = "(No matches found)" if plan.goodreads_status == "none" else "(lookup failed)"
            smart_print(
                Tinta()
                .dark_grey("│ ", sep="")
                .pink(message, sep="")
                .to_str()
            )
        else:
            low = plan.goodreads_status == "low_confidence"

            def _goodreads_row(label: str, value: str, truth_val: str = "") -> None:
                empty = not (value or "").strip()
                display = value if not empty else "(missing)"
                s = Tinta().dark_grey("│ ", sep="").grey(f"{label}: ", sep="")
                if empty:
                    s.dark_grey(display, sep="")
                elif low and not _prop_equal(value, truth_val):
                    s.amber(display, sep="")
                elif _prop_equal(value, truth_val):
                    s.mint(display, sep="")
                else:
                    s.amber(display, sep="")
                smart_print(s.to_str())

            _goodreads_row("Title", plan.goodreads_title, truth["title"])
            _goodreads_row("Author", plan.goodreads_author, truth["author"])
            _goodreads_row("Date", plan.goodreads_year, truth["date"])
            if plan.goodreads_key:
                smart_print(
                    Tinta()
                    .dark_grey("│ ", sep="")
                    .grey("Book: ", sep="")
                    .grey(plan.goodreads_key, sep="")
                    .to_str()
                )
            if plan.goodreads_url:
                smart_print(
                    Tinta()
                    .dark_grey("│ ", sep="")
                    .grey("Link: ", sep="")
                    .purple(plan.goodreads_url, sep="")
                    .to_str()
                )
        if plan.provider_conflicts:
            for conflict in plan.provider_conflicts:
                smart_print(
                    Tinta()
                    .dark_grey("│ ", sep="")
                    .amber(f"Comparison: {conflict}", sep="")
                    .to_str()
                )
        _framed_footer(style="light_grey")

    _print_proposed_plan(plan, show_rename=show_rename)


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
    """Normalize an interactive prompt response to y/t/r/s/e/o/m/c/q (default s)."""
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
    if s in ("e", "edit"):
        return "e"
    if s in ("c", "cancel"):
        return "c"
    if s in ("q", "quit"):
        return "q"
    if len(s) == 1 and s in ("y", "t", "r", "s", "o", "m", "e", "c", "q", "n"):
        return "s" if s == "n" else s
    return "s"


def _can_reassign_author_to_narrator(plan: FixPlan) -> bool:
    """Whether the current ID3 author plausibly belongs in the narrator field."""
    current_author = (plan.current.artist or "").strip()
    desired_author = (plan.desired_author or "").strip()
    return bool(
        current_author
        and desired_author
        and not (plan.current.composer or "").strip()
        and not _prop_equal(current_author, desired_author)
        and fuzz.token_set_ratio(current_author, desired_author) / 100 < 0.7
    )


def _prompt_edit_value(
    label: str,
    current: str,
    *,
    can_clear: bool = True,
    filename: bool = False,
    input_default: str | None = None,
) -> str:
    """Prompt for one proposed value, prefilling it when readline is available."""
    from tinta import Tinta

    input_default = current if input_default is None else input_default
    prompt = (
        Tinta()
        .banana(label, sep="")
        .banana(" [", sep="")
        .dark_grey(current, sep="")
        .banana("]: ", sep="")
        .to_str()
    )
    try:
        import readline
    except ImportError:
        readline = None

    try:
        if readline is not None and sys.stdin.isatty():
            readline.set_startup_hook(lambda: readline.insert_text(input_default))
        raw = input(prompt)
    except EOFError:
        smart_print("")
        return current
    except KeyboardInterrupt:
        smart_print("")
        raise
    finally:
        if readline is not None:
            readline.set_startup_hook()

    if not raw.strip():
        return input_default
    if raw.strip() == "_":
        if filename:
            print_orange("  Filename cannot be blank.")
            return current
        return "" if can_clear else current
    return raw.strip()


def _set_plan_filename(plan: FixPlan, value: str) -> bool:
    """Set a proposed filename and its companion description rename."""
    name = Path(value.strip()).name
    if not name or name in (".", ".."):
        print_orange("  Filename cannot be blank.")
        return False
    if Path(name).suffix:
        print_orange("  Filename must not include an extension.")
        return False
    stem = name
    stem = safe_filename(stem)
    if not stem:
        print_orange("  Filename is not usable.")
        return False
    target = plan.m4b.with_name(ensure_audio_ext(stem, ".m4b"))
    plan.desired_stem = target.stem
    plan.rename_m4b_to = None if target == plan.m4b else target
    plan.rename_desc_to = None
    if plan.desc_txt and plan.rename_m4b_to:
        quality_match = _QUALITY_TXT.match(plan.desc_txt.name)
        suffix = (
            plan.desc_txt.name[len(quality_match.group(1)) :]
            if quality_match
            else ".txt"
        )
        plan.rename_desc_to = plan.desc_txt.with_name(f"{stem}{suffix}")
    return True


def edit_plan(plan: FixPlan) -> None:
    """Edit proposed metadata fields in display order."""
    smart_print("")
    print_pink("Edit:")
    print_dark_grey("Type _ to clear, [Return] to accept, Ctrl+C to quit")
    smart_print("")
    plan.desired_title = _prompt_edit_value("Title", plan.desired_title)
    plan.desired_album = plan.desired_title
    plan.desired_author = _prompt_edit_value("Author", plan.desired_author)
    plan.desired_date = _prompt_edit_value("Date", plan.desired_date)
    plan.desired_narrator = _prompt_edit_value("Narrator", plan.desired_narrator)
    filename = plan.rename_m4b_to.name if plan.rename_m4b_to else plan.m4b.name
    while True:
        edited_filename = _prompt_edit_value(
            "Filename",
            filename,
            can_clear=False,
            filename=True,
            input_default=Path(filename).stem,
        )
        if _set_plan_filename(plan, edited_filename):
            break


def _save_interactive_plan(
    plan: FixPlan, *, cli: CliPaths, index: int, total: int
) -> None:
    """Write one interactive plan using the standard saving/Done display."""
    print()
    apply_fix(
        plan,
        dry_run=False,
        cli=cli,
        quiet=True,
        progress=_print_status_line,
    )
    from tinta import Tinta

    _finish_status_line(
        Tinta().light_grey("Done ", sep="").mint("✓", sep="").to_str()
    )
    print()
    if index < total - 1:
        divider()


def _save_interactive_tags_only(
    plan: FixPlan, *, cli: CliPaths, index: int, total: int
) -> None:
    """Write tags and the existing description without renaming either file."""
    tags_only_plan = _tags_only_plan(plan)
    print()
    apply_fix(
        tags_only_plan,
        dry_run=False,
        cli=cli,
        quiet=True,
        progress=_print_status_line,
    )
    from tinta import Tinta

    _finish_status_line(
        Tinta().light_grey("Done ", sep="").mint("✓", sep="").to_str()
    )
    print()
    if index < total - 1:
        divider()


def _tags_only_plan(plan: FixPlan) -> FixPlan:
    """Return a writable plan with both file renames disabled."""
    tags_only_plan = copy.copy(plan)
    tags_only_plan.rename_m4b_to = None
    tags_only_plan.rename_desc_to = None
    return tags_only_plan


def prompt_apply(
    plan: FixPlan,
    *,
    manual_ol_pending: bool = False,
    allow_author_to_narrator: bool = True,
    show_tags_only: bool = True,
) -> str:
    """Ask whether to apply *plan*.

    Returns ``y``, ``t`` (tags only), ``s`` (skip), ``o`` (open library),
    ``m`` (use low-confidence match), ``e`` (edit), ``r`` (reassign current author to narrator),
    ``c`` (cancel manual OL), ``q`` (quit), or ``interrupt`` (Ctrl+C).
    """
    try:
        from tinta import Tinta

        can_reassign = allow_author_to_narrator and _can_reassign_author_to_narrator(plan)
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
        if show_tags_only:
            smart_print(
                Tinta()
                .dark_grey("  ", sep="")
                .amber("t", sep="")
                .dark_grey("  ", sep="")
                .light_grey("yes, tags only", sep="")
                .to_str()
            )
        if can_reassign:
            smart_print(
                Tinta()
                .dark_grey("  ", sep="")
                .amber("r", sep="")
                .dark_grey("  ", sep="")
                .light_grey("assign author to narrator", sep="")
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
            .amber("e", sep="")
            .dark_grey("  ", sep="")
            .light_grey("edit proposed values", sep="")
            .to_str()
        )
        if manual_ol_pending:
            smart_print(
                Tinta()
                .dark_grey("  ", sep="")
                .amber("c", sep="")
                .dark_grey("  ", sep="")
                .light_grey("cancel manual openlibrary lookup", sep="")
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
        choice_keys = "y/S/m/o/e/c/q" if manual_ol_pending else (
            "y/S/m/o/e/q" if plan.ol_status == "low_confidence" else "y/S/o/e/q"
        )
        if show_tags_only:
            choice_keys = choice_keys.replace("y/", "y/t/")
        if can_reassign:
            choice_keys = choice_keys.replace("y/", "y/t/r/")
            if not show_tags_only:
                choice_keys = choice_keys.replace("y/t/r/", "y/r/")
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
    """Ask for an Open Library URL or id. Empty → None; Ctrl+C quits the CLI."""
    try:
        from tinta import Tinta

        smart_print("")
        print_amber("Open Library matching")
        smart_print("")
        print_dark_grey("Paste a work/edition URL or id, then press Enter.")
        print_dark_grey("Examples:")
        smart_print(
            Tinta().dark_grey("  ").to_str() + tint_path("https://openlibrary.org/works/OL45804W")
        )
        smart_print(Tinta().dark_grey("  ").to_str() + tint_path("OL45804W"))
        print_dark_grey("Leave blank to cancel.")
        smart_print("")
        raw = input(Tinta().amber("Url or ID").dark_grey(": ").to_str()).strip()
    except EOFError:
        smart_print("")
        return None
    return raw or None



def print_ol_session_notice(*, no_ol: bool = False, no_goodreads: bool = False) -> None:
    """Session-level metadata provider status (below auto-recursive, once)."""
    if no_ol:
        print_dark_grey("openlibrary  (disabled via --no-ol)")
        return
    ua = (os.environ.get("OPEN_LIBRARY_USER_AGENT") or "").strip()
    if not ua:
        print_dark_grey("openlibrary unavailable (set OPEN_LIBRARY_USER_AGENT to enable)")
    if no_goodreads:
        print_dark_grey("goodreads  (disabled via --no-goodreads)")
    elif not (os.environ.get("GOODSCRAPS_USER_AGENT") or "").strip():
        print_dark_grey("goodreads unavailable (set GOODSCRAPS_USER_AGENT to enable)")



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


def _print_status_line(msg: str) -> None:
    """Overwrite-friendly dark-grey status (e.g. Saving tags…)."""
    from tinta import Tinta

    width = _planning_progress_width()
    shown = msg if len(msg) <= width else msg[: width - 1] + "…"
    padded = f"{shown:<{width}}"
    colored = Tinta().dark_grey(padded, sep="").to_str()
    sys.stdout.write(f"\r{colored}")
    sys.stdout.flush()


def _finish_status_line(final: str) -> None:
    """Clear the status line and print *final* (already colored) + newline."""
    width = _planning_progress_width()
    sys.stdout.write(f"\r{' ' * width}\r")
    sys.stdout.write(final + "\n")
    sys.stdout.flush()


class _FixMetadataParser(argparse.ArgumentParser):
    """Friendlier argparse errors — no usage wall, colored message."""

    def error(self, message: str) -> NoReturn:
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
        "-g",
        "--goodreads",
        dest="goodreads_ref",
        default=None,
        metavar="URL_OR_ID",
        help="Force Goodreads book (URL or numeric ID); requires a single book target",
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
        "-t",
        "--tags-only",
        action="store_true",
        help="Write tags and update description contents without renaming files",
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
        "--no-goodreads",
        action="store_true",
        help="Skip automatic Goodreads lookup (still allows -g)",
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
    dry_run = not (args.apply or args.tags_only or interactive)
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

    print_ol_session_notice(
        no_ol=bool(args.no_ol),
        no_goodreads=bool(args.no_goodreads),
    )

    source_root = args.source.resolve() if args.source else None
    if source_root is not None and not source_root.exists():
        print_red(f"source path does not exist: [[{source_root}]]")
        return 1

    ol_ref = args.ol_ref
    goodreads_ref = args.goodreads_ref
    if ol_ref and len(book_dirs) != 1:
        print_red(
            f"-o/--ol requires a single book target, but {len(book_dirs)} book dir(s) were selected"
        )
        return 1
    if goodreads_ref and len(book_dirs) != 1:
        print_red(
            f"-g/--goodreads requires a single book target, but {len(book_dirs)} book dir(s) were selected"
        )
        return 1

    # Interactive and forced-OL can retag from folder/m4b alone (no archive source).
    require_source = not (interactive or bool(ol_ref))
    # Interactive (without forced -o): local scan first; OL attaches per book on review.
    # When Goodreads is enabled, query both providers during planning so
    # provider ties can be resolved before interactive review.
    defer_ol = interactive and not bool(ol_ref) and not bool(
        (os.environ.get("GOODSCRAPS_USER_AGENT") or "").strip()
    )
    lookup_ol_upfront = (not args.no_ol or bool(ol_ref)) and not defer_ol
    lookup_goodreads_upfront = not args.no_goodreads or bool(goodreads_ref)

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
                goodreads_ref=goodreads_ref,
                lookup_goodreads=lookup_goodreads_upfront,
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
            _apply_cleanup_filename(plan, plan.fs_title)
            if plan.needs_work:
                kept.append(plan)
        plans = kept

    if interactive and args.tags_only:
        plans = [
            plan
            for plan in plans
            if plan.needs_tag_write or plan.needs_desc_rewrite
        ]

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
            manual_ol_snapshot: FixPlan | None = None
            allow_author_to_narrator = True
            show_plan_details = True
            while True:
                print_plan(
                    plan,
                    label="propose",
                    cli=cli,
                    proposed_only=not show_plan_details,
                    show_rename=not args.tags_only,
                )
                choice = prompt_apply(
                    plan,
                    manual_ol_pending=manual_ol_snapshot is not None,
                    allow_author_to_narrator=allow_author_to_narrator,
                    show_tags_only=not args.tags_only,
                )
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
                if choice == "t":
                    _save_interactive_tags_only(
                        plan, cli=cli, index=i, total=len(plans)
                    )
                    last_book_printed_done = i == len(plans) - 1
                    break
                if choice == "c":
                    if manual_ol_snapshot is None:
                        print_orange("  No manual Open Library lookup to cancel.")
                        continue
                    plan = manual_ol_snapshot
                    manual_ol_snapshot = None
                    print_dark_grey("  (manual Open Library lookup cancelled)")
                    continue
                if choice == "r":
                    if not (
                        allow_author_to_narrator
                        and _can_reassign_author_to_narrator(plan)
                    ):
                        print_orange("  Cannot reassign the current author to narrator.")
                        continue
                    plan.desired_narrator = plan.current.artist.strip()
                    allow_author_to_narrator = False
                    smart_print("")
                    from tinta import Tinta

                    smart_print(
                        Tinta()
                        .dark_grey("Switching ", sep="")
                        .amber(plan.current.artist, sep="")
                        .dark_grey(" to narrator", sep="")
                        .to_str()
                    )
                    show_plan_details = False
                    continue
                if choice == "e":
                    edit_plan(plan)
                    save_plan = (
                        _save_interactive_tags_only
                        if args.tags_only
                        else _save_interactive_plan
                    )
                    save_plan(plan, cli=cli, index=i, total=len(plans))
                    last_book_printed_done = i == len(plans) - 1
                    break
                if choice == "o":
                    ref = prompt_ol_ref()
                    if not ref:
                        print_dark_grey("  (cancelled — showing proposal again)")
                        continue
                    if manual_ol_snapshot is None:
                        manual_ol_snapshot = copy.deepcopy(plan)
                    _attach_open_library(
                        plan, ol_ref=ref, apply_ol_tags=True, minimalist=minimalist
                    )
                    _apply_cleanup_filename(plan, plan.fs_title)
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
                    save_plan = (
                        _save_interactive_tags_only
                        if args.tags_only
                        else _save_interactive_plan
                    )
                    save_plan(plan, cli=cli, index=i, total=len(plans))
                    last_book_printed_done = i == len(plans) - 1
                    break
            continue

        print_mint(f"fixing [[{plan.book_dir.name}]]", highlight_color=LIGHT_GREY_COLOR)
        apply_plan = _tags_only_plan(plan) if args.tags_only else plan
        apply_fix(apply_plan, dry_run=False, cli=cli)

    if dry_run and plans:
        smart_print("")
        print_dark_grey("Re-run with --apply to write changes, or -i to confirm each fix.")
    elif (interactive or not dry_run) and not last_book_printed_done:
        smart_print("")
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

