"""Shared metadata planning — backed by the standalone fixm4b package."""
from __future__ import annotations

import importlib as _importlib

_impl = _importlib.import_module("fixm4b.metadata")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})

# Settings helpers live at package root in fixm4b.
from fixm4b.settings import Fixm4bSettings, get_settings, set_settings, settings_from_cfg

__all__ = list(getattr(_impl, "__all__", [])) + [
    "Fixm4bSettings",
    "get_settings",
    "set_settings",
    "settings_from_cfg",
]
