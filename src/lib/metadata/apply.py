"""Apply a FixPlan: write ID3 tags, rename files, rewrite description txt."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from src.lib.id3_utils import write_id3_tags_mutagen
from src.lib.cleaners import fix_smart_quotes
from src.lib.metadata.models import CliPaths, FixPlan
from src.lib.term import LIGHT_GREY_COLOR, print_green, print_orange


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



def apply_fix(
    plan: FixPlan,
    *,
    dry_run: bool = True,
    cli: CliPaths | None = None,
    quiet: bool = False,
    progress: Callable[[str], None] | None = None,
) -> None:
    tags = {
        "title": fix_smart_quotes(plan.desired_title),
        "album": fix_smart_quotes(plan.desired_album),
        "artist": fix_smart_quotes(plan.desired_author),
        "albumartist": fix_smart_quotes(plan.desired_author),
        "date": plan.desired_date,
        "composer": fix_smart_quotes(plan.desired_narrator or ""),
    }

    if dry_run:
        from src.fix_metadata import print_plan

        print_plan(plan, label="dry-run", cli=cli)
        return

    target = plan.m4b
    if plan.needs_tag_write:
        if progress:
            progress("Writing tags...")
        write_id3_tags_mutagen(target, tags)
        if not quiet:
            print_green(f"  ✓ wrote tags → [[{target.name}]]", highlight_color=LIGHT_GREY_COLOR)

    if plan.rename_m4b_to:
        if progress:
            progress("Renaming file...")
        if plan.rename_m4b_to.exists() and plan.rename_m4b_to.resolve() != target.resolve():
            print_orange(f"  ⚠ SKIP rename, target exists: [[{plan.rename_m4b_to.name}]]")
        else:
            target.rename(plan.rename_m4b_to)
            target = plan.rename_m4b_to
            plan.m4b = target
            if not quiet:
                print_green(f"  ✓ renamed m4b → [[{target.name}]]", highlight_color=LIGHT_GREY_COLOR)

    desc_out = plan.rename_desc_to or plan.desc_txt
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
    elif desc_out is not None and desc_out.exists():
        _write_desc(plan, desc_out)
        if not quiet:
            print_green(f"  ✓ wrote desc → [[{desc_out.name}]]", highlight_color=LIGHT_GREY_COLOR)

