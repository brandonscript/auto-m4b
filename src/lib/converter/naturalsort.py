"""Natural sort helpers — port of PHP FileLoader::sortFilesByName (strnatcmp)."""

from __future__ import annotations

import re
from pathlib import Path


def _natural_key(text: str) -> list[int | str]:
    """Split *text* into a mixed list of ints and lowercase strings so that
    `sorted(..., key=_natural_key)` produces strnatcmp-equivalent order."""
    parts: list[int | str] = []
    for chunk in re.split(r"(\d+)", text):
        parts.append(int(chunk) if chunk.isdigit() else chunk.lower())
    return parts


def natural_sort_files(files: list[Path]) -> list[Path]:
    """Sort *files* by their path components using natural (strnatcmp) order,
    matching the behaviour of PHP FileLoader::sortFilesByName:

    - Files at different depths: shallower paths come first.
    - Files at the same depth: compare component-by-component with natural sort;
      basename is the last tiebreaker.
    """

    def sort_key(f: Path) -> tuple[int, list[list[int | str]]]:
        parts = f.parts
        depth = len(parts)
        component_keys = [_natural_key(p) for p in parts]
        return depth, component_keys

    return sorted(files, key=sort_key)
