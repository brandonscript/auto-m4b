"""Post-conversion hook runner.

Runs a user-supplied Python or bash script after each successful conversion.
Failures in the hook are logged but never abort the conversion cycle.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from src.lib.term import print_debug, print_warning

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook


def _build_script_env(book: "Audiobook") -> dict[str, str]:
    """Build AUTO_M4B_* env vars describing the converted book."""
    from src.lib.config import cfg

    watch_source = ""
    if cfg.watch_dir and book.key:
        watch_source = str(cfg.watch_dir / book.key)

    return {
        "AUTO_M4B_INBOX_PATH": str(book.inbox_dir),
        "AUTO_M4B_CONVERTED_PATH": str(book.converted_file) if book.converted_file else "",
        "AUTO_M4B_CONVERTED_DIR": str(book.converted_dir),
        "AUTO_M4B_TITLE": book.title or "",
        "AUTO_M4B_AUTHOR": book.author or "",
        "AUTO_M4B_KEY": book.key or "",
        "AUTO_M4B_WATCH_SOURCE": watch_source,
    }


def _resolve_command(script: Path) -> list[str]:
    """Choose how to invoke *script* based on extension / executable bit."""
    suffix = script.suffix.lower()
    if suffix == ".py":
        return [sys.executable, str(script)]
    if suffix == ".sh":
        return ["bash", str(script)]
    if os.access(script, os.X_OK):
        return [str(script)]
    # Fallback: treat unknown non-executable scripts as bash
    return ["bash", str(script)]


def _append_post_convert_log(
    book: "Audiobook",
    *,
    script_name: str,
    status: str,
    exit_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
    error: str = "",
) -> None:
    """Write post-convert details to a dedicated ``.post-convert.log`` next to the .m4b."""
    log_path = getattr(book, "post_convert_log_file", None)
    if not log_path:
        return
    try:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = [
            f"Post-convert script: {script_name}",
            f"Status: {status}",
            f"Time: {ts}",
        ]
        if exit_code is not None:
            lines.append(f"Exit code: {exit_code}")
        if error:
            lines.append(f"Error: {error}")
        if stdout.strip():
            lines.append("stdout:")
            lines.append(stdout.rstrip())
        if stderr.strip():
            lines.append("stderr:")
            lines.append(stderr.rstrip())
        lines.append("")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError as exc:
        print_warning(f"[post-convert] could not write post-convert log: {exc}")


def _warn_with_output(message: str, stdout: str = "", stderr: str = "") -> None:
    """Print a warning and include script output so failures aren't swallowed."""
    print_warning(message)
    detail = (stderr or stdout or "").rstrip()
    if detail:
        # Cap so a chatty script doesn't flood the console.
        max_chars = 2000
        if len(detail) > max_chars:
            detail = detail[:max_chars] + "\n… (truncated)"
        print_warning(f"[post-convert] details:\n{detail}")


def run_post_convert_script(book: "Audiobook") -> None:
    """Run ``POST_CONVERT_SCRIPT`` for *book* if configured.

    Never raises — a failing or missing script only logs a warning so the
    conversion cycle continues uninterrupted. Script stdout/stderr (and
    failure details) are always written to ``auto-m4b.<title>.post-convert.log``
    next to the converted ``.m4b``.
    """
    from src.lib.config import cfg

    script_path = cfg.POST_CONVERT_SCRIPT
    if not script_path:
        return

    script = Path(script_path)
    if not script.is_file():
        msg = f"script not found: {script}"
        print_warning(f"[post-convert] {msg}")
        _append_post_convert_log(book, script_name=str(script), status="missing", error=msg)
        return

    cmd = _resolve_command(script)
    env = {**os.environ, **_build_script_env(book)}
    timeout = cfg.POST_CONVERT_SCRIPT_TIMEOUT or 60

    print_debug(f"[post-convert] running: {' '.join(cmd)} (timeout={timeout}s)")
    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        msg = f"script timed out after {timeout}s: {script.name}"
        _warn_with_output(f"[post-convert] {msg}", stdout, stderr)
        _append_post_convert_log(
            book,
            script_name=script.name,
            status="timeout",
            error=msg,
            stdout=stdout,
            stderr=stderr,
        )
        return
    except OSError as exc:
        msg = f"failed to start script: {exc}"
        print_warning(f"[post-convert] {msg}")
        _append_post_convert_log(
            book, script_name=script.name, status="start_error", error=msg
        )
        return

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if stdout:
        print_debug(f"[post-convert] stdout:\n{stdout.rstrip()}")
    if stderr:
        print_debug(f"[post-convert] stderr:\n{stderr.rstrip()}")

    if result.returncode != 0:
        msg = f"script exited {result.returncode}: {script.name}"
        _warn_with_output(f"[post-convert] {msg}", stdout, stderr)
        _append_post_convert_log(
            book,
            script_name=script.name,
            status="failed",
            exit_code=result.returncode,
            stdout=stdout,
            stderr=stderr,
        )
        return

    print_debug(f"[post-convert] script completed: {script.name}")
    # Always persist output (Deluge soft failures often exit 0 but print details).
    if stdout.strip() or stderr.strip():
        _append_post_convert_log(
            book,
            script_name=script.name,
            status="ok",
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
        )
    else:
        _append_post_convert_log(
            book,
            script_name=script.name,
            status="ok",
            exit_code=0,
        )
