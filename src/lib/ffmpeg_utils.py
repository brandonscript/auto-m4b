from pathlib import Path
from typing import Any, Literal, NamedTuple, overload

import cachetools.func
import ffmpeg
from ffmpeg import probe as ffprobe

from src.lib.books_tree import BooksTree
from src.lib.config import AUDIO_EXTS
from src.lib.formatters import format_duration, get_nearest_standard_bitrate
from src.lib.fs_utils import only_audio_files
from src.lib.term import print_error, print_warning
from src.lib.typing import DurationFmt, MEMO_TTL


class AudioTechProbe(NamedTuple):
    """Cached technical metadata from a single ffprobe invocation."""

    duration: float
    bitrate: int  # bits per second (0 if unknown)
    sample_rate: int  # Hz (0 if unknown)
    has_attached_pic: bool


@cachetools.func.ttl_cache(maxsize=256, ttl=MEMO_TTL)
def _probe_audio_tech(path_str: str) -> AudioTechProbe:
    """Run one ffprobe and return duration/bitrate/samplerate/cover presence.

    All public getters below share this cache so extract_metadata / logging /
    merge no longer spawn 2–3 probes for the same sample file.
    """
    try:
        probe_result = ffprobe(path_str)
    except ffmpeg.Error as e:
        from src.lib.logger import write_err_file

        path = Path(path_str)
        write_err_file(path, e, "ffprobe", e.stderr.decode())
        print_error(f"Error probing audio tech for {path}")
        return AudioTechProbe(0.0, 0, 0, False)

    fmt = probe_result.get("format") or {}
    streams = probe_result.get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if audio is None and streams:
        audio = streams[0]
    audio = audio or {}

    duration = float(fmt.get("duration") or 0.0)
    bitrate_raw = audio.get("bit_rate") or fmt.get("bit_rate") or 0
    try:
        bitrate = int(bitrate_raw)
    except (TypeError, ValueError):
        bitrate = 0
    try:
        sample_rate = int(audio.get("sample_rate") or 0)
    except (TypeError, ValueError):
        sample_rate = 0

    from src.lib.constants import COVER_STREAM_CODECS

    has_pic = any(
        s.get("codec_name") in COVER_STREAM_CODECS and (s.get("disposition") or {}).get("attached_pic")
        for s in streams
    )
    return AudioTechProbe(duration, bitrate, sample_rate, bool(has_pic))


def probe_audio_tech(file: "BooksTree | Path") -> AudioTechProbe:
    path = file.path if isinstance(file, BooksTree) else file
    return _probe_audio_tech(str(path))


def get_file_duration_py(file_path: Path) -> float:
    return _probe_audio_tech(str(file_path)).duration


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


def is_variable_bitrate(file: "BooksTree | Path") -> bool:
    path = file.path if isinstance(file, BooksTree) else file
    bitrate, nearest_std_bitrate = get_bitrate_py(path)
    return abs(bitrate - nearest_std_bitrate) > 0.5


def get_bitrate_py(file: "BooksTree | Path") -> tuple[int, int]:
    """Returns the bitrate of an audio file in bits per second.

    Returns:
        tuple[int, int]: (nearest standard bitrate, actual bitrate) in bps.
    """
    path = file.path if isinstance(file, BooksTree) else file
    actual_bitrate = _probe_audio_tech(str(path)).bitrate
    if not actual_bitrate:
        return 0, 0
    return get_nearest_standard_bitrate(actual_bitrate), actual_bitrate


def get_samplerate_py(file: "BooksTree | Path") -> int:
    path = file.path if isinstance(file, BooksTree) else file
    return _probe_audio_tech(str(path)).sample_rate


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
