from pathlib import Path
from typing import Any, Literal, overload

import cachetools.func

from src.lib.misc import fix_ffprobe

fix_ffprobe()

import ffmpeg
from ffmpeg import probe as ffprobe

from src.lib.books_tree import BooksTree
from src.lib.config import AUDIO_EXTS
from src.lib.formatters import format_duration, get_nearest_standard_bitrate
from src.lib.fs_utils import only_audio_files
from src.lib.term import print_error
from src.lib.typing import DurationFmt, MEMO_TTL


def get_file_duration_py(file_path: Path) -> float:
    try:
        return float(ffprobe(str(file_path))["format"]["duration"])
    except ffmpeg.Error as e:
        from src.lib.logger import write_err_file

        write_err_file(file_path, e, "ffprobe", e.stderr.decode())
        print_error(f"Error getting duration for {file_path}")
        return 0


@overload
def get_duration(path: Path, fmt: Literal["seconds"] = "seconds") -> float: ...


@overload
def get_duration(path: Path, fmt: Literal["human"] = "human") -> str: ...


def get_duration(path: Path, fmt: DurationFmt = "human") -> str | float:
    if not path.exists():
        raise ValueError(f"Error getting duration: Path {path} does not exist")

    duration = 0

    if path.is_file():
        if path.suffix not in AUDIO_EXTS:
            raise ValueError(f"File {path} is not an audio file")

        duration = get_file_duration_py(path)

    elif path.is_dir():
        files = only_audio_files(list(path.glob("**/*")))
        if not files:
            raise ValueError(f"No audio files found in {path}")

        duration = 0
        for file in files:
            duration += get_file_duration_py(file)

    return format_duration(duration, fmt)


# def extract_id3_tag(file: Path, tag: str) -> str:
#     command = f"ffprobe -hide_banner -loglevel 0 -of flat -i {file} -select_streams a -show_entries format_tags={tag} -of default=noprint_wrappers=1:nokey=1"
#     result = subprocess.check_output(command, shell=True).decode().strip()
#     return result


# def get_bitrate(file: Path, round: bool = True) -> int:
#     command = f"ffprobe -hide_banner -loglevel 0 -select_streams a:0 -show_entries stream=bit_rate -of default=noprint_wrappers=1:nokey=1 {file}"
#     bitrate = subprocess.check_output(command, shell=True).decode().strip()
#     return round_bitrate(int(bitrate)) if round else int(bitrate)


def is_variable_bitrate(file: "BooksTree | Path") -> bool:
    path = file.path if isinstance(file, BooksTree) else file
    bitrate, nearest_std_bitrate = get_bitrate_py(path)
    return abs(bitrate - nearest_std_bitrate) > 0.5


@cachetools.func.ttl_cache(maxsize=128, ttl=MEMO_TTL)
def get_bitrate_py(file: "BooksTree | Path") -> tuple[int, int]:
    """Returns the bitrate of an audio file in bits per second.

    Args:
        file (Path): Path to the audio file
        round_result (bool, optional): Whether to round the result to the nearest standard bitrate. Defaults to True.

    Returns:
        tuple[int, int]: (in kbps) The nearest standard bitrate, and the actual bitrate rounded to the nearest int.
    """
    path = file.path if isinstance(file, BooksTree) else file
    try:
        probe_result = ffmpeg.probe(str(path))
        actual_bitrate = int(probe_result["streams"][0]["bit_rate"])
        return get_nearest_standard_bitrate(actual_bitrate), actual_bitrate
    except ffmpeg.Error as e:
        from src.lib.logger import write_err_file

        write_err_file(path, e, "ffprobe", e.stderr.decode())
        print_error(f"Error getting bitrate for {path}")
        return 0, 0


# def get_samplerate(file: Path) -> int:
#     command = f"ffprobe -hide_banner -loglevel 0 -of flat -i {file} -select_streams a -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1"
#     sample_rate = subprocess.check_output(command, shell=True).decode().strip()
#     return int(sample_rate)


@cachetools.func.ttl_cache(maxsize=128, ttl=MEMO_TTL)
def get_samplerate_py(file: "BooksTree | Path") -> int:
    path = file.path if isinstance(file, BooksTree) else file
    try:
        probe_result = ffmpeg.probe(str(path))
        sample_rate = probe_result["streams"][0]["sample_rate"]
        return int(sample_rate)
    except ffmpeg.Error as e:
        from src.lib.logger import write_err_file

        write_err_file(path, e, "ffprobe", e.stderr.decode())
        print_error(f"Error getting sample rate for {path}")
        return 0


def build_id3_tags_args(
    title: str = "", author: str = "", year: str | None = "", comment: str = ""
) -> list[tuple[str, Any]]:

    # build m4b-tool command switches based on which properties are defined
    # --name[=NAME]                              $title
    # --sortname[=SORTNAME]                      $title
    # --album[=ALBUM]                            $title
    # --sortalbum[=SORTALBUM]                    $title
    # --artist[=ARTIST]                          $author
    # --sortartist[=SORTARTIST]                  $author
    # --genre[=GENRE]                            always Audiobook
    # --writer[=WRITER]                          $author
    # --albumartist[=ALBUMARTIST]                $author
    # --year[=YEAR]                              $year
    # --description[=DESCRIPTION]                $description
    # --comment[=COMMENT]                        $comment
    # --encoded-by[=ENCODED-BY]                  always PHNTM

    id3tags = {}

    if title:
        id3tags.update(
            {
                "name": title,
                "sortname": title,
                "album": title,
                "sortalbum": title,
            }
        )

    if author:
        id3tags.update(
            {
                "artist": author,
                "sortartist": author,
                "writer": author,
                "albumartist": author,
            }
        )

    if year:
        id3tags["year"] = year

    if comment:
        id3tags["comment"] = comment

    id3tags.update({"encoded-by": "PHNTM", "genre": "Audiobook"})

    return [(f"--{k}", v) for k, v in id3tags.items()]
