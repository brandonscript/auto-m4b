"""AAC encoder detection — port of Ffmpeg::loadHighestAvailableQualityAacCodec."""

from __future__ import annotations

import subprocess

_cached_codec: str | None = None

CODEC_LIBFDK_AAC = "libfdk_aac"
CODEC_AAC = "aac"


def detect_aac_codec(*, force_refresh: bool = False) -> str:
    """Return 'libfdk_aac' if available in the system ffmpeg, else 'aac'.

    Result is cached for the lifetime of the process; pass force_refresh=True
    to re-probe (useful in tests).
    """
    global _cached_codec

    if _cached_codec is not None and not force_refresh:
        return _cached_codec

    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-codecs"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout + result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _cached_codec = CODEC_AAC
        return _cached_codec

    _cached_codec = CODEC_LIBFDK_AAC if CODEC_LIBFDK_AAC in output else CODEC_AAC
    return _cached_codec
