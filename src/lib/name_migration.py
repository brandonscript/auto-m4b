"""Bounded, idempotent migration of state created before the otto-m4b rename."""

from __future__ import annotations

import os
import re
import warnings
from pathlib import Path

LEGACY_NAME = "auto-m4b"
NAME = "otto-m4b"
LEGACY_MARKER = f".{LEGACY_NAME}"
MARKER = f".{NAME}"


def migrate_path(old: Path, new: Path, *, critical: bool = False) -> Path:
    """Move without overwriting; retain conflicting data as a numbered backup."""
    if old.is_symlink() or new.is_symlink():
        raise RuntimeError(f"Resolve symlink state before migration: {old} -> {new}")
    if not old.exists():
        return new
    if not new.exists():
        old.rename(new)
    elif old.is_dir() and new.is_dir():
        for child in sorted(old.iterdir()):
            migrate_path(child, new / child.name, critical=critical or child.name in {"fatal.log", "running.pid"})
        old.rmdir()
    elif old.is_file() and new.is_file() and old.read_bytes() == new.read_bytes():
        old.unlink()
    elif critical:
        raise RuntimeError(
            f"Conflicting processing state: {old} and {new}. Stop both converters and resolve before restarting."
        )
    else:
        backup = new.with_name(new.name + ".legacy-backup")
        index = 1
        while backup.exists():
            if backup.is_file() and old.is_file() and backup.read_bytes() == old.read_bytes():
                old.unlink()
                return new
            backup = new.with_name(new.name + f".legacy-backup.{index}")
            index += 1
        old.rename(backup)
        warnings.warn(f"Preserved legacy state at {backup}", stacklevel=2)
    return new


def marker_path(source: Path) -> Path:
    old, new = source / LEGACY_MARKER, source / MARKER
    try:
        return migrate_path(old, new, critical=True)
    except OSError as exc:
        warnings.warn(f"Cannot migrate legacy marker {old}: {exc}; continuing to recognize it", stacklevel=2)
        return old if old.exists() else new


def migrate_home(home: Path) -> Path:
    new = migrate_path(home / LEGACY_MARKER, home / MARKER)
    new.mkdir(parents=True, exist_ok=True)
    return new


def assert_stopped(directory: Path) -> None:
    pid_file = directory / "running.pid"
    if not pid_file.exists():
        return
    match = re.search(r"pid=(\d+)", pid_file.read_text())
    if match is None:
        raise RuntimeError(f"Unrecognized process lock {pid_file}; confirm converter is stopped before removing it.")
    pid = int(match[1])
    if pid <= 0:
        raise RuntimeError(f"Invalid process lock {pid_file}")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    raise RuntimeError(f"Converter process {pid} may still be running ({pid_file}); stop it before migration.")


def migrate_temp(parent: Path, *, working: Path | None = None) -> Path:
    old, new = parent / LEGACY_NAME, parent / NAME
    for directory in (old, new):
        assert_stopped(directory)
    if old.exists():
        unexpected = [
            p
            for p in old.iterdir()
            if p.name not in {"fatal.log", "running.pid"}
            and not (
                p.name in {"build", "merge", "trash"}
                and p.is_dir()
                and not p.is_symlink()
                and not any(item.is_file() or item.is_symlink() for item in p.rglob("*"))
            )
        ]
        if unexpected:
            raise RuntimeError(f"Legacy temporary work remains in {old}; preserve and resolve it before restarting.")
        if working is not None and working.resolve() == old.resolve():
            # An explicit WORKING_FOLDER remains at its configured location.
            new.mkdir(parents=True, exist_ok=True)
            for name in ("fatal.log", "running.pid"):
                migrate_path(old / name, new / name, critical=True)
        else:
            migrate_path(old, new, critical=True)
    new.mkdir(parents=True, exist_ok=True)
    return new


def migrate_logs(root: Path) -> None:
    """Walk only configured roots; do not follow directory symlinks."""
    if not root.is_dir():
        return
    for directory, _, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            if name.startswith(LEGACY_NAME + ".") and name.endswith(".log"):
                old = Path(directory) / name
                migrate_path(old, old.with_name(NAME + name[len(LEGACY_NAME) :]))
