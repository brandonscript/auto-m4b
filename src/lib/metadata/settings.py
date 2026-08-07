"""Auto-m4b settings bridge: live ``cfg`` unless an explicit override is injected."""

from __future__ import annotations

from typing import Any

from fixm4b.settings import Fixm4bSettings, settings_from_cfg

_override: Fixm4bSettings | None = None


def get_settings() -> Fixm4bSettings:
    """Prefer an explicit test/CLI override; otherwise adapt auto-m4b ``cfg`` live."""
    if _override is not None:
        return _override
    from src.lib.config import cfg

    return settings_from_cfg(cfg)


def set_settings(settings: Fixm4bSettings | None) -> None:
    """Inject settings for tests / one-off overrides. ``None`` clears the override."""
    global _override
    _override = settings


__all__ = [
    "Fixm4bSettings",
    "get_settings",
    "set_settings",
    "settings_from_cfg",
]
