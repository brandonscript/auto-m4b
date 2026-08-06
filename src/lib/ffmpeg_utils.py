from pathlib import Path
from typing import Any, Literal, overload

import cachetools.func
import ffmpeg
from ffmpeg import probe as ffprobe

from src.lib.books_tree import BooksTree
from src.lib.config import AUDIO_EXTS
from src.lib.formatters import format_duration, get_nearest_standard_bitrate
from src.lib.fs_utils import only_audio_files
from src.lib.term import print_error, print_warning
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
    # --encoded-by[=ENCODED-BY]                  always BOOKSY

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

    id3tags.update({"encoded-by": "BOOKSY", "genre": "Audiobook"})

    return [(f"--{k}", v) for k, v in id3tags.items()]


def shrink_mp3_to_size(file: Path, target_size: int) -> Path:
    """Shrink an audio file toward ``target_size``.

    Prefers a stream-copy trim (no re-encode). That preserves the original
    bitrate/sample-rate, works without ``libmp3lame``, and is what fixture
    tests rely on. Falls back to libmp3lame re-encode when available.
    """
    if not file.exists():
        raise ValueError(f"[shrink_mp3_to_size]: file {file} does not exist")

    if file.suffix not in AUDIO_EXTS:
        return file

    current_size = file.stat().st_size

    # if the file is already smaller than the target size, do nothing
    if current_size < target_size:
        return file

    # get the duration of the file
    duration = max(1.0, float(get_duration(file, fmt="seconds")))

    # get the bitrate of the file, in bps
    bitrate, _ = get_bitrate_py(file)

    # get the samplerate of the file, in Hz
    samplerate = get_samplerate_py(file)

    # Create a temporary file for processing
    tmp_file = file.with_suffix(f".tmp{file.suffix}")

    def _restore_tags(src: Path, dst: Path) -> None:
        """ffmpeg stream-copy often drops ID3/MP4 atoms; reinstate from ``src``."""
        try:
            if src.suffix.lower() == ".mp3":
                from mutagen.id3 import ID3

                ID3(src).save(dst)
            elif src.suffix.lower() in {".m4a", ".m4b", ".mp4"}:
                from mutagen.mp4 import MP4

                src_tags, dst_tags = MP4(src), MP4(dst)
                for key, value in src_tags.items():
                    dst_tags[key] = value
                dst_tags.save()
        except Exception:
            # Best-effort: shrinking still succeeds even if tags cannot be copied.
            pass

    def _replace_if_smaller() -> bool:
        if not tmp_file.exists():
            return False
        new_size = tmp_file.stat().st_size
        if new_size < current_size:
            _restore_tags(file, tmp_file)
            tmp_file.replace(file)
            return True
        tmp_file.unlink(missing_ok=True)
        return False

    # Fast path: stream-copy trim. Size ≈ bitrate/8 * seconds (+ tags/cover).
    # Drop embedded cover/video streams so artwork cannot keep us over budget.
    if bitrate > 0:
        for budget_factor in (0.75, 0.45, 0.25, 0.12):
            trim_t = max(1.0, min(duration, (target_size * budget_factor * 8) / bitrate))
            try:
                (
                    ffmpeg.input(str(file), t=trim_t)
                    .output(
                        str(tmp_file),
                        **{
                            "c": "copy",
                            "map": "0:a:0",
                            "map_metadata": "0",
                            "map_chapters": "0",
                            "sn": None,
                            "dn": None,
                        },
                    )
                    .overwrite_output()
                    .run(quiet=True)
                )
                if tmp_file.exists() and tmp_file.stat().st_size <= target_size:
                    _restore_tags(file, tmp_file)
                    tmp_file.replace(file)
                    return file
                if _replace_if_smaller() and file.stat().st_size <= target_size:
                    return file
            except ffmpeg.Error:
                tmp_file.unlink(missing_ok=True)
                break

        if file.stat().st_size <= target_size:
            return file

    try:

        in_stream = ffmpeg.input(str(file))

        # Check if there's a cover art stream and get its dimensions
        probe = ffprobe(str(file))
        cover_stream = next((s for s in probe["streams"] if s.get("codec_type") == "video"), None)

        cover_adj = {
            "vcodec": "copy",
        }
        if bool(cover_stream) and cover_stream.get("width", 0) > 100:
            # If cover art is larger than 100px, resize it
            cover_adj = {
                "vcodec": "mjpeg",
                "vf": "scale=100:100:force_original_aspect_ratio=decrease",
                "qscale": 2,
            }

        # Fallback: re-encode with libmp3lame when the build supports it.
        target_bitrate = int((target_size * 8) / duration)
        target_bitrate = min(bitrate or target_bitrate, max(target_bitrate, 24 * 1000))

        predicted_size = int((target_bitrate / 8) * duration)

        trim_seconds = 0
        while predicted_size > target_size and trim_seconds < duration - 1:
            trim_seconds += 1
            predicted_size = int((target_bitrate / 8) * (duration - trim_seconds))

        check_size = current_size
        i = 0
        params = [
            {
                "t": max(1, duration - trim_seconds),
                "audio_bitrate": f"{target_bitrate/1000}k",
                "ar": samplerate,
                "compression_level": 7,
            },
            {
                "t": max(1, duration - trim_seconds),
                "audio_bitrate": f"{target_bitrate/1000}k",
                "ar": 22050,
                "compression_level": 8,
            },
            {
                "t": max(1, duration - trim_seconds),
                "audio_bitrate": "16k",
                "ar": 22050,
                "compression_level": 9,
            },
            {
                "t": max(1, duration - trim_seconds),
                "audio_bitrate": "16k",
                "ar": 22050,
                "compression_level": 9,
            },
        ]
        base_offset = len(params) - 2

        while check_size > target_size and i < len(params):

            out_stream = ffmpeg.output(
                in_stream,
                str(tmp_file),
                acodec="libmp3lame",
                map_metadata="0",  # Copy all metadata including cover art
                map_chapters="0",  # Copy chapters
                **params[i],
                **cover_adj,
            )

            ffmpeg.run(out_stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)
            check_size = tmp_file.stat().st_size

            if i == len(params) - 1:
                offset = i - base_offset
                params.append({**params[i], "t": max(1, duration - trim_seconds - offset)})

            if i > 2:
                print_warning(f"Shrinking {file}: on third attempt, consider using a more aggressive approach")

            i += 1

        # Final size check
        if (size := tmp_file.stat().st_size) > target_size:
            print_warning(f"Shrinking {file}: could not achieve target size of {target_size} b, got {size} b")

        tmp_file.replace(file)
        return file

    except ffmpeg.Error as e:
        from src.lib.logger import write_err_file

        write_err_file(file, e, "ffmpeg", e.stderr.decode())
        print_error(f"Error shrinking {file}")
        return file
    finally:
        # Clean up temporary file if it exists
        if tmp_file.exists():
            tmp_file.unlink()
