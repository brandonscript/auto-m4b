import sys
from pathlib import Path
from typing import Any, cast

import ffmpeg

from src.lib.term import print_debug, print_error, print_warning
from src.lib.typing import BadFileError


def ffprobe_file(file: Path | None, *, options: dict[str, Any] | None = None, throw: bool = False):
    """Extract metadata from a file using ffprobe."""

    from src.lib.config import cfg

    if file is None:
        return None

    if file and not file.exists():
        raise FileNotFoundError(f"Error: Cannot extract id3 tag, '{file}' does not exist")
    try:
        options = options or {}
        probe_result = ffmpeg.probe(str(file), cmd="ffprobe", **options)
    except Exception as e:
        from src.lib.logger import write_err_file

        err_str = str(cast(ffmpeg.Error, e).stderr) if isinstance(e, ffmpeg.Error) else str(e)

        # Some mock files are not readable by ffprobe, so we return None
        if "pytest" in sys.modules and "mock_" in err_str and "Invalid data" in err_str:
            return None

        write_err_file(file, e, "ffprobe")
        base_msg = f"Error: Could run ffprobe on file '{file}' with options {options}."
        if throw:
            raise BadFileError(base_msg) from e
        if "ffprobe version" in err_str:
            print_warning(f"{base_msg}\n{err_str}")
        else:
            print_error(f"{base_msg}\nTry running `./scripts/fix-ffprobe.sh`...")
        if cfg.DEBUG:
            print_debug(err_str)
        return None

    return cast(dict, probe_result)
