"""Injectable settings for the shared metadata planner.

Standalone ``fixm4b`` uses XDG ``config.toml``; auto-m4b adapts its ``cfg``
singleton via :func:`settings_from_cfg` so Docker/env still win in-container.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Fixm4bSettings:
    cleanup_filenames: bool = False
    goodscraps_user_agent: str | None = None
    goodscraps_timeout: float = 30.0
    open_library_user_agent: str | None = None
    open_library_timeout: float = 15.0
    bookpeek: bool = False
    cache_dir: Path | None = None
    # CLI path defaults (standalone / XDG config); empty means unresolved.
    inbox_folder: str = ""
    converted_folder: str = ""
    archive_folder: str = ""
    minimalist: bool | None = None
    app_name_path: Path | None = None

    def with_overrides(self, **kwargs: Any) -> Fixm4bSettings:
        return replace(self, **{k: v for k, v in kwargs.items() if v is not None or k in kwargs})


_settings: Fixm4bSettings | None = None


def get_settings() -> Fixm4bSettings:
    """Return injected settings, or adapt auto-m4b ``cfg`` when unset."""
    if _settings is not None:
        return _settings
    return settings_from_cfg()


def set_settings(settings: Fixm4bSettings | None) -> None:
    """Inject settings for library callers (tests / standalone CLI)."""
    global _settings
    _settings = settings


def settings_from_cfg(cfg: Any | None = None) -> Fixm4bSettings:
    """Adapt auto-m4b's ``cfg`` singleton into :class:`Fixm4bSettings`."""
    if cfg is None:
        from src.lib.config import cfg as auto_cfg

        cfg = auto_cfg

    meta_dir = getattr(cfg, "META_DIR", None)
    cache_dir = Path(meta_dir) if meta_dir is not None else None
    app_name = (cache_dir / "app_name") if cache_dir is not None else None
    return Fixm4bSettings(
        cleanup_filenames=bool(getattr(cfg, "CLEANUP_FILENAMES", False)),
        goodscraps_user_agent=(getattr(cfg, "GOODSCRAPS_USER_AGENT", None) or None) or None,
        goodscraps_timeout=float(getattr(cfg, "GOODSCRAPS_TIMEOUT", 30) or 30),
        open_library_user_agent=(getattr(cfg, "OPEN_LIBRARY_USER_AGENT", None) or None) or None,
        open_library_timeout=float(getattr(cfg, "OPEN_LIBRARY_TIMEOUT", 15) or 15),
        bookpeek=bool(getattr(cfg, "BOOKPEEK", False)),
        cache_dir=cache_dir,
        inbox_folder=os.environ.get("CLI_INBOX_FOLDER", "") or "",
        converted_folder=os.environ.get("CLI_CONVERTED_FOLDER", "") or "",
        archive_folder=os.environ.get("CLI_ARCHIVE_FOLDER", "") or "",
        minimalist=None,
        app_name_path=app_name,
    )
