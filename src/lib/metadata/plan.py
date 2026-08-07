"""Shim: re-export from the standalone fixm4b package."""
from __future__ import annotations

import importlib as _importlib

_impl = _importlib.import_module("fixm4b.metadata.plan")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
__all__ = getattr(_impl, "__all__", [k for k in vars(_impl) if not k.startswith("_")])
