import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import ffmpeg

from src.lib.term import print_debug, print_error, print_warning
from src.lib.typing import BadFileError

FFPROBE_REPAIRS = 0


def ffprobe_paths():
    paths_to_add = ["/opt/homebrew/bin", "/usr/local/bin/"]
    for path in paths_to_add:
        if Path(path) not in sys.path and Path(path).exists():
            sys.path.append(path)

    return os.pathsep.join(paths_to_add)


def fix_ffprobe(counter: int = 0):

    def check_ffprobe():
        import ffmpeg
        from ffmpeg import Error, probe  # type: ignore

        assert ffmpeg.probe  # type: ignore
        assert Error
        assert probe
        subprocess.check_output(["which", "ffprobe"]).decode().strip()
        assert (
            subprocess.run(
                "ffprobe -version",
                capture_output=True,
                shell=True,
                env={
                    "PATH": ffprobe_paths(),
                },
            ).returncode
            == 0
        )

    # Get the path to the .venv
    src_root = Path(__file__).parent.parent.parent
    venv_path = src_root / ".venv"
    binary = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = venv_path / f"lib/{binary}/site-packages"
    bin_root = venv_path / "bin" / binary
    if not site_packages.exists():
        raise RuntimeError(f"auto_m4b's site_packages not found at '{site_packages}', cannot fix ffprobe")

    fix_cmd = f"{bin_root} -m pip uninstall ffmpeg-python python-ffmpeg -y && {bin_root} -m pip install ffmpeg-python --target {site_packages} --force-reinstall --upgrade"

    try:
        check_ffprobe()
    except Exception as _e:
        # if counter == 0:
        #     print_warning("ffmpeg's ffprobe is not installed or not working — attempting to fix...\n")

        # Look for ffprobe in PATH and known locations
        known_locations = ["/opt/homebrew/bin", "/usr/local/bin"]
        for location in known_locations:
            if Path(location).exists():
                os.environ["PATH"] = f"{location}:{os.environ['PATH']}"

        ffprobe_path = subprocess.check_output(["which", "ffprobe"]).decode().strip()
        if ffprobe_path and not (d := os.path.dirname(ffprobe_path)) in os.environ["PATH"]:
            os.environ["PATH"] = f"{d}:{os.environ['PATH']}"

        code = subprocess.run(
            fix_cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        if code == 0:
            return
        if counter < 3:
            counter += 1
            fix_ffprobe(counter)
        else:
            raise ImportError(f"ffmpeg's ffprobe is not installed, please fix it manually:\n\n $ {fix_cmd}\n\n")


def ffprobe_file(file: Path | None, *, options: dict[str, Any] | None = None, throw: bool = False):
    """Extract metadata from a file using ffprobe."""

    global FFPROBE_REPAIRS

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

        if "No such file or directory: 'ffprobe'" in err_str and FFPROBE_REPAIRS <= 3:
            fix_ffprobe()
            FFPROBE_REPAIRS += 1
            return ffprobe_file(file, options=options, throw=throw)

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
