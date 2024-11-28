import datetime
import functools
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast, Literal, NamedTuple, overload, TYPE_CHECKING

from src.lib.misc import fix_ffprobe

fix_ffprobe()

import bidict
import ffmpeg
from columnar import columnar
from mutagen.mp3 import HeaderNotFoundError
from rapidfuzz import fuzz
from rapidfuzz.distance import LCSseq, Levenshtein
from tinta import Tinta

from src.lib.books_tree import BooksTree
from src.lib.cleaners import clean_string, strip_author_narrator, strip_leading_articles, strip_part_number
from src.lib.fs_utils import find_first_audio_file
from src.lib.misc import compare_trim, get_numbers_in_string
from src.lib.parsers import (
    common_str_pattern,
    contains_partno_or_ch,
    find_greatest_common_string,
    get_title_partno_score,
    get_year_from_date,
    has_graphic_audio,
    parse_author,
    parse_narrator,
    parse_year,
    startswith_num_pattern,
    to_words,
)
from src.lib.term import (
    nl,
    PATH_COLOR,
    print_debug,
    print_error,
    print_list_item,
    smart_print,
)
from src.lib.typing import AdditionalTags, BadFileError, ScoredProp, TagSource

MissingApplicationError = ValueError

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook


def write_id3_tags_exiftool(file: Path, exiftool_args: list[str]) -> None:
    api_opts = ["-api", 'filter="s/ \\(approx\\)//"']  # remove (approx) from output

    # if file doesn't exist, throw error
    if not file.is_file():
        raise RuntimeError(f"Error: Cannot write id3 tags, {file} does not exist")

    # make sure the exiftool command exists
    if not shutil.which("exiftool"):
        raise RuntimeError(
            "exiftool is not available, please install it with\n\n $ apt-get install exiftool\n\n...or make sure it is in your PATH variable, then try again"
        )

    # write tag to file, using eval so that quotes are not escaped
    subprocess.run(
        ["exiftool", "-overwrite_original"] + exiftool_args + api_opts + [str(file)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


TagSet = NamedTuple(
    "TagsSet",
    [
        ("title", str),
        ("artist", str),
        ("album", str),
        ("albumartist", str),
        ("composer", str),
        ("date", str),
        ("track_num", tuple[int, int]),
        ("comment", str),
    ],
)


def _tags_from_book_or_dict(book_or_dict: "Audiobook | dict[str, Any]") -> TagSet:
    if isinstance(book_or_dict, dict):
        title = str(book_or_dict.get("title", ""))
        artist = str(book_or_dict.get("artist", ""))
        album = str(book_or_dict.get("album", ""))
        albumartist = str(book_or_dict.get("albumartist", ""))
        composer = str(book_or_dict.get("composer", ""))
        date = str(book_or_dict.get("date", ""))
        track_num = book_or_dict.get("track_num", (1, 1))
        comment = str(book_or_dict.get("comment", ""))
    else:
        title = book_or_dict.title
        artist = book_or_dict.artist
        album = book_or_dict.album
        albumartist = book_or_dict.albumartist
        composer = book_or_dict.composer
        date = book_or_dict.date
        track_num = book_or_dict.track_num
        comment = book_or_dict.comment

    try:
        d = datetime.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        d = None
    year = get_year_from_date(date, to_int=True) or (d.year if d else None)
    if year or d:
        date = d.strftime("%Y-%m-%d") if d else f"{year}-01-01"

    return TagSet(title, artist, album, albumartist, composer, date, track_num, comment)


def write_m4b_tags(file: Path, book: "Audiobook | dict[str, Any]", cover: Path | None = None):
    """Uses mutagen to write id3 tags to an m4b file"""
    try:
        from mutagen.mp4 import MP4, MP4Cover
    except ImportError:
        raise MissingApplicationError(
            "Error: mutagen is not available, please install it with\n\n $ pip install mutagen\n\n...then try again"
        )

    if not file.exists():
        raise FileNotFoundError(f"Error: Cannot write id3 tags, '{file}' does not exist")

    title, artist, album, albumartist, composer, date, track_num, comment = _tags_from_book_or_dict(book)

    if f := MP4(file):
        f["\xa9nam"] = title
        f["\xa9ART"] = artist
        f["\xa9alb"] = album
        f["aART"] = albumartist
        f["\xa9wrt"] = composer
        f["\xa9day"] = date
        f["trkn"] = [(track_num[0], track_num[1])]
        f["\xa9cmt"] = comment

        # if cover exists, determine if it is jpg or png and set it
        if cover and cover.is_file():
            with open(cover, "rb") as img_in:
                image_data = img_in.read()

            if cover.suffix in [".jpg", ".jpeg"]:
                mime_type = MP4Cover.FORMAT_JPEG
            elif cover.suffix == ".png":
                mime_type = MP4Cover.FORMAT_PNG
            else:
                raise IOError(f"Error: Could not set cover art, '{cover}' is not a valid .jpg or .png file")
                return
            f["covr"] = [MP4Cover(image_data, mime_type)]

        f.save()


def write_id3_tags_mutagen(
    file: "Path | BooksTree", book: "Audiobook | dict[str, Any]", cover: Path | None = None
) -> None:
    path = file.path if isinstance(file, BooksTree) else file
    if path.suffix in [".m4b", ".m4a"]:
        write_m4b_tags(path, book, cover)
    else:
        write_mp3_tags(path, book, cover)


def write_mp3_tags(file: Path, book: "Audiobook | dict[str, Any]", cover: Path | None = None) -> None:
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import APIC, ID3

        EasyID3.RegisterTextKey("comment", "COMM")

    except ImportError:
        raise MissingApplicationError(
            "Error: mutagen is not available, please install it with\n\n $ pip install mutagen\n\n...then try again"
        )

    if not file.exists():
        raise FileNotFoundError(f"Error: Cannot write id3 tags, '{file}' does not exist")

    title, artist, album, albumartist, composer, date, track_num, comment = _tags_from_book_or_dict(book)

    if f := EasyID3(file):
        f["title"] = title
        f["artist"] = artist
        f["album"] = album
        f["albumartist"] = albumartist
        f["author"] = artist
        f["composer"] = composer
        f["comment"] = comment
        f["tracknumber"] = f"{track_num[0]}/{track_num[1]}"
        f["discnumber"] = ""
        f["date"] = date
        f["originaldate"] = date

        f.save()

        # if cover exists, determine if it is jpg or png and set it
        if cover and cover.is_file() and (f := ID3(file)):
            with open(cover, "rb") as img_in:
                image_data = img_in.read()

            if cover.suffix == ".jpg":
                mime_type = "image/jpeg"
            elif cover.suffix == ".png":
                mime_type = "image/png"
            else:
                raise IOError(f"Error: Could not set cover art, '{cover}' is not a valid .jpg or .png file")
                return
            image = APIC(
                encoding=3,
                mime=mime_type,
                type=3,
                desc=cover.name,
                data=image_data,
            )
            f.delall("APIC")
            f.add(image)
            f.save()
    else:
        raise HeaderNotFoundError(f"Error: Could not load '{file}' for tagging, it may be corrupt or not an audio file")


def verify_and_update_id3_tags(book: "Audiobook", *, in_dir: Literal["build", "converted"]) -> None:
    # takes the inbound book, then checks the converted file and verifies that the id3 tags match the extracted metadata
    # if they do not match, it will print a notice and update the id3 tags

    from src.lib.audiobook import Audiobook

    m4b_to_check = book.converted_file if in_dir == "converted" else book.build_file

    if not m4b_to_check.is_file():
        m4b_to_check = find_first_audio_file(book.converted_dir, ext="m4b")
        if not m4b_to_check.is_file():
            raise FileNotFoundError(f"Cannot verify id3 tags, {m4b_to_check} does not exist")

    smart_print("\nVerifying id3 tags...", end="")

    book_to_check = Audiobook(m4b_to_check).extract_metadata(quiet=True)

    title_needs_updating = False
    author_needs_updating = False
    narrator_needs_updating = False
    date_needs_updating = False
    comment_needs_updating = False
    cover_needs_updating = False

    updates = []

    def _print_needs_updating(what: str, left_value: str | None, right_value: str) -> None:
        s = Tinta().dark_grey(f"- ").grey(what).dark_grey("needs updating:")
        if left_value:
            s.amber(left_value)
        else:
            s.light_grey("Missing")
        s.dark_grey("»").mint(right_value)
        smart_print(s.to_str())

    if book.title and book_to_check.id3_title != book.title:
        title_needs_updating = True
        updates.append(lambda: _print_needs_updating("Title", book_to_check.id3_title, book.title))

    if book.author and book_to_check.id3_artist != book.author:
        author_needs_updating = True
        updates.append(lambda: _print_needs_updating("Artist (author)", book_to_check.id3_artist, book.author))

    if book.title and book_to_check.id3_album != book.title:
        title_needs_updating = True
        updates.append(lambda: _print_needs_updating("Album (title)", book_to_check.id3_album, book.title))

    if book.title and book_to_check.id3_sortalbum != book.title:
        title_needs_updating = True
        updates.append(lambda: _print_needs_updating("Sort album (title)", book_to_check.id3_sortalbum, book.title))

    if book.author and book_to_check.id3_albumartist != book.author:
        author_needs_updating = True
        updates.append(
            lambda: _print_needs_updating("Album artist (author)", book_to_check.id3_albumartist, book.author)
        )

    if book.narrator and book_to_check.id3_composer != book.narrator:
        narrator_needs_updating = True
        updates.append(lambda: _print_needs_updating("Composer (narrator)", book_to_check.id3_composer, book.narrator))

    if book.date and get_year_from_date(book_to_check.id3_date) != get_year_from_date(book.date):
        date_needs_updating = True
        updates.append(lambda: _print_needs_updating("Date", book_to_check.id3_date, book.date))

    if book.comment and compare_trim(book_to_check.id3_comment, book.comment):
        comment_needs_updating = True
        updates.append(lambda: _print_needs_updating("Comment", book_to_check.id3_comment, book.comment))

    if (cover := book.cover_art_file) and cover.exists() and not book_to_check.has_id3_cover:
        cover_needs_updating = True
        updates.append(lambda: _print_needs_updating("Cover art", None, cover.name))

    needs_update = any(
        (
            title_needs_updating,
            author_needs_updating,
            narrator_needs_updating,
            date_needs_updating,
            comment_needs_updating,
            cover_needs_updating,
        )
    )
    if needs_update:
        nl()
        write_id3_tags_mutagen(m4b_to_check, book, book.cover_art_file)
        [update() for update in updates]
        smart_print(Tinta("\nDone").mint("✓").to_str())

    else:
        smart_print(Tinta().mint(" ✓\n").to_str())

    nl()


def ffprobe_file(file: Path | None, *, options: dict[str, Any] | None = None, throw: bool = False):
    from src.lib.config import cfg

    if file is None:
        return None

    if file and not file.exists():
        raise FileNotFoundError(f"Error: Cannot extract id3 tag, '{file}' does not exist")
    try:
        options = options or {}
        probe_result = ffmpeg.probe(str(file), cmd="ffprobe", **options)
    except ffmpeg.Error as e:
        from src.lib.logger import write_err_file

        write_err_file(file, e, "ffprobe")
        msg = f"Error: Could run ffprobe on file '{file}' with options {options}.\nTry running `pipenv run fix-ffprobe`..."
        if throw:
            raise BadFileError(msg) from e
        print_error(msg)
        if cfg.DEBUG:
            print_debug(e.stderr)
        return None

    return cast(dict, probe_result)


def ffmpeg_file(file: Path, *, options: dict[str, Any] | None = None, throw: bool = False):
    from src.lib.config import cfg

    if file is None:
        return None

    if file and not file.exists():
        raise FileNotFoundError(f"Error: Cannot extract id3 tag, '{file}' does not exist")
    try:
        options = options or {}
        ffmpeg_result = ffmpeg.run(str(file), cmd="ffmpeg", **options)
    except ffmpeg.Error as e:
        from src.lib.logger import write_err_file

        write_err_file(file, e, "ffmpeg")
        if throw:
            raise BadFileError(f"Error: Could run ffmpeg on file '{file}' with options {options}") from e
        print_error(f"Error: Could run ffmpeg on file '{file}' with options {options}")
        if cfg.DEBUG:
            print_debug(e.stderr)
        return None

    return cast(dict, ffmpeg_result)


@overload
def extract_cover_art(file: "BooksTree | Path", save_to_file: Literal[False] = False) -> bytes: ...


@overload
def extract_cover_art(file: "BooksTree | Path", save_to_file: Literal[True], filename: str = "cover") -> Path: ...


def extract_cover_art(file: "BooksTree | Path", save_to_file: bool = False, filename: str = "cover") -> bytes | Path:
    from src.lib.config import cfg

    path = file.path if isinstance(file, BooksTree) else file

    out_file = path.parent / filename

    try:
        if ffresult := ffprobe_file(path):
            # '-s': '320x240'}):
            # find a stream that is jpg or png and has a disposition of attached_pic
            for stream in ffresult["streams"]:
                if stream.get("codec_name") in ["mjpeg", "png"] and stream.get("disposition", {}).get("attached_pic"):
                    content_type = stream.get("codec_name")
                    common_steps = [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "0",
                        "-i",
                        str(path),
                        "-map",
                        f"0:{stream['index']}",
                        "-c",
                        "copy",
                    ]
                    if save_to_file:
                        ext = "png" if content_type == "png" else "jpg"
                        out_file = out_file.with_suffix(f".{ext}")
                        subprocess.check_output(
                            [
                                *common_steps,
                                out_file,
                            ]
                        )
                        return out_file
                    return subprocess.check_output(
                        [
                            *common_steps,
                            "-f",
                            "image2pipe",
                            "-vcodec",
                            "png" if content_type == "png" else "mjpeg",
                            "-",
                        ]
                    )
    except KeyError:
        if cfg.DEBUG:
            print_debug(f"Could not extract cover art from {file}'s streams")
    return out_file.with_suffix(".jpg") if save_to_file else b""


id3_tag_map = bidict.bidict(
    {
        "title": "title",
        "artist": "artist",
        "album_artist": "albumartist",
        "album": "album",
        "composer": "composer",
        "comment": "comment",
        "genre": "genre",
        "date": "date",
        "track": "track",
        "sort_name": "sortname",
        "sort_artist": "sortartist",
        "sort_album": "sortalbum",
        "description": "description",
        "encoder": "encoder",
    }
)


def id3_tags_raw_to_source(
    in_dict: dict[str, str],
) -> dict[TagSource | AdditionalTags, str]:
    """Takes raw id3 tag keys and converts them to the source tag names"""
    return {cast(TagSource, id3_tag_map.get(k, k)): v for k, v in in_dict.items()}


def id3_tags_source_to_raw(
    in_dict: dict[TagSource | AdditionalTags, str],
) -> dict[str, str]:
    """Takes raw id3 tag keys and converts them to the source tag names"""
    return {cast(TagSource, id3_tag_map.inv.get(k, k)): v for k, v in in_dict.items()}


def extract_id3_tags(
    file: "BooksTree | Path | None", *tags: TagSource | AdditionalTags, throw=False
) -> dict[TagSource | AdditionalTags, str]:

    path = file.path if isinstance(file, BooksTree) else Path(file) if file else None

    if not path or not path.exists():
        if throw:
            raise HeaderNotFoundError(f"Error: Cannot extract id3 tags, '{file}' does not exist")
        return {}

    try:
        if ffresult := ffprobe_file(path, throw=throw):
            tag_dict = id3_tags_raw_to_source(
                {key.lower(): value for key, value in (ffresult["format"]["tags"] or {}).items()}
            )
            if not tags:
                return tag_dict
            return {tag: tag_dict.get(tag, "") for tag in tags}
    except Exception as e:
        if throw:
            raise HeaderNotFoundError(
                f"Error: Could not extract id3 tags from {path} with tags {', '.join(tags)}"
            ) from e
        # if cfg.DEBUG:
        #     print_debug(
        #         f"Could not read '{tag}' from {path}'s id3 tags, it probably doesn't exist"
        #     )
    return {}


class BaseScoreCard:

    def __init__(self, scorer: "MetadataScore") -> None:

        self._scorer = scorer

    props: list[TagSource] = []

    def reset(self):
        for attr in dir(self):
            if not attr.startswith("_") and isinstance(getattr(self, attr), int):
                setattr(self, attr, 0)

    @property
    def _choices(self):
        available = list(set([p.split("_")[-1] for p in self.props]))
        return {
            k: getattr(self._scorer._p, k)
            for k in [_k for _k in dir(self._scorer._p) if not _k.startswith("_") and any((p in _k for p in available))]
        }

    @property
    def _prop(self):
        return self.__class__.__name__.split("ScoreCard")[0].lower()

    @property
    def _value(self):
        return self._scorer._tag_matcher(self._prop, self._is_likely[0], "")

    @property
    def _is_likely(self) -> tuple[TagSource, int, str | None]:
        # put all the scores in a list and return the highest score and its var name
        rep = re.compile(rf"_(is|contains)_{self._prop}$")
        scores = [
            (cast(TagSource, re.sub(rep, "", p)), getattr(self, p), p)
            for p in dir(self)
            if not p.startswith("_") and p.endswith(self._prop) and isinstance(getattr(self, p), int)
        ]
        if not scores or all(score[1] <= 0 for score in scores):
            return "unknown", 0, None
        tag, best, prop = max(scores, key=lambda x: x[1])
        # return the highest score and the name of its variable - use inflection or inspect
        return tag, best, prop

    def __repr__(self):
        return self.__str__()


class TitleScoreCard(BaseScoreCard):
    title_is_title: int = 0
    album_is_title: int = 0
    sortalbum_is_title: int = 0
    common_title_is_title: int = 0
    common_album_is_title: int = 0
    common_sortalbum_is_title: int = 0

    props: list[TagSource] = [
        "title",
        "album",
        "sortalbum",
        "common_title",
        "common_album",
        "common_sortalbum",
    ]

    def __str__(self):
        return (
            f"TitleScoreCard\n"
            f" - title_is_title: {self.title_is_title}\n"
            f" - album_is_title: {self.album_is_title}\n"
            f" - sortalbum_is_title: {self.sortalbum_is_title}\n"
            f" - common_title_is_title: {self.common_title_is_title}\n"
            f" - common_album_is_title: {self.common_album_is_title}\n"
            f" - common_sortalbum_is_title: {self.common_sortalbum_is_title}\n"
        )


class AuthorScoreCard(BaseScoreCard):
    artist_is_author: int = 0
    albumartist_is_author: int = 0
    common_artist_is_author: int = 0
    common_albumartist_is_author: int = 0
    comment_contains_author: int = 0

    props: list[TagSource] = [
        "artist",
        "albumartist",
        "common_artist",
        "common_albumartist",
        "comment",
    ]

    def __str__(self):
        return (
            f"AuthorScoreCard\n"
            f" - artist_is_author: {self.artist_is_author}\n"
            f" - albumartist_is_author: {self.albumartist_is_author}\n"
            f" - common_artist_is_author: {self.common_artist_is_author}\n"
            f" - common_albumartist_is_author: {self.common_albumartist_is_author}\n"
            f" - comment_contains_author: {self.comment_contains_author}\n"
        )


class NarratorScoreCard(BaseScoreCard):
    artist_is_narrator: int = 0
    albumartist_is_narrator: int = 0
    common_artist_is_narrator: int = 0
    common_albumartist_is_narrator: int = 0
    comment_contains_narrator: int = 0
    composer_is_narrator: int = 0

    props: list[TagSource] = [
        "artist",
        "albumartist",
        "common_artist",
        "common_albumartist",
        "comment",
        "composer",
    ]

    def __str__(self):
        return (
            f"NarratorScoreCard\n"
            f" - artist_is_narrator: {self.artist_is_narrator}\n"
            f" - albumartist_is_narrator: {self.albumartist_is_narrator}\n"
            f" - common_artist_is_narrator: {self.common_artist_is_narrator}\n"
            f" - common_albumartist_is_narrator: {self.common_albumartist_is_narrator}\n"
            f" - composer_is_narrator: {self.composer_is_narrator}\n"
            f" - comment_contains_narrator: {self.comment_contains_narrator}\n"
        )


class DateScoreCard(BaseScoreCard):
    date_is_date: int = 0
    fs_contains_date: int = 0

    props: list[TagSource] = ["date", "year", "fs"]

    def __str__(self):
        return (
            f"DateScoreCard\n"
            f" - date_is_date: {self.date_is_date}\n"
            f" - fs_contains_date: {self.fs_contains_date}\n"
        )


KEY_MAP = {
    "_aar": "albumartist",
    "_ar": "artist",
    "_al": "album",
    "_comment": "comment",
    "_sal": "sortalbum",
    "_t": "title",
    "_fs": "fs",
    # add more mappings here if needed
}


def similarity_score(s1: str, s2: str) -> int:
    """Returns the average similarity score between two strings using three different algorithms from -10 to 10 (with 0 being 50% similar, indeterminate)"""
    tsr = fuzz.token_sort_ratio(s1, s2)
    lcs = LCSseq.normalized_similarity(s1, s2) * 100
    lev = Levenshtein.normalized_similarity(s1, s2) * 100

    # round to nearest 0.001
    percent = (tsr + lcs + lev) / 3

    # if < 50, return -10 to 0, if >50 return 0 to 10
    return int((percent / 100 if percent > 50 else percent / 50 - 1) * 10)


def custom_sort(key: str, next_key: str) -> int:
    underscored = key.startswith("_")
    next_underscored = next_key.startswith("_")
    # next_group = not next_key.startswith("_") and re.sub(r"(^[a-z])", "", next_key)
    mapped_key = None if not underscored else next((KEY_MAP[i] for i in KEY_MAP if key.startswith(i)), None)
    next_mapped_key = (
        None if not next_underscored else next((KEY_MAP[i] for i in KEY_MAP if next_key.startswith(i)), None)
    )

    # if neither have mapped keys, just compare them as is
    if not mapped_key and not next_mapped_key:
        return -1 if key < next_key else int(key > next_key)

    group = mapped_key if mapped_key else re.sub(r"([^a-z]*)$", "", key)
    next_group = next_mapped_key if next_mapped_key else re.sub(r"([^a-z]*)$", "", next_key)
    # next_group = not next_key.startswith("_") and re.sub(r"(^[a-z])", "", next_key)
    groups_match = group == next_group

    # groups don't match, so compare them
    if not groups_match:
        return -1 if group < next_group else int(group > next_group)

    # otherwise we can assume same group, so we have to compare more granularly
    if underscored and not next_underscored:
        return 1
    elif not underscored and next_underscored:
        return -1

    return -1 if key < next_key else int(key > next_key)


class MetadataProps:

    def __init__(
        self,
        book: "Audiobook",
        sample_audio2_tags: dict[TagSource | AdditionalTags, str],
    ):

        common_filename = (
            find_greatest_common_string([book.sample_audio1.name, book.sample_audio2.name])
            if book.sample_audio2
            else book.sample_audio1.name
        )
        self.fs_basename = book.basename
        self.fs_filename_c = common_filename
        self.fs_name = str(Path(book.basename) / common_filename)
        self.fs_name_lower = self.fs_name.lower()
        self.fs_year = parse_year(self.fs_name)

        self.title1 = book.id3_title
        self.title2 = sample_audio2_tags.get("title", "")
        self.title_c = find_greatest_common_string([self.title1, self.title2])

        self.album1 = book.id3_album
        self.album2 = sample_audio2_tags.get("album", "")
        self.album_c = find_greatest_common_string([self.album1, self.album2])

        self.sortalbum1 = book.id3_sortalbum
        self.sortalbum2 = sample_audio2_tags.get("sortalbum", "")
        self.sortalbum_c = find_greatest_common_string([self.sortalbum1, self.sortalbum2])

        self.artist1 = book.id3_artist
        self.artist2 = sample_audio2_tags.get("artist", "")
        self.artist_c = find_greatest_common_string([self.artist1, self.artist2])

        self.albumartist1 = book.id3_albumartist
        self.albumartist2 = sample_audio2_tags.get("albumartist", "")
        self.albumartist_c = find_greatest_common_string([self.albumartist1, self.albumartist2])

        self.date = book.id3_date
        self.year = get_year_from_date(self.date)
        self.comment = book.id3_comment
        self.composer = book.id3_composer

        self.author_in_comment = parse_author(self.comment, "comment", fallback="")
        self.narrator_in_comment = parse_narrator(self.comment, "comment", fallback="")

        self._t_is_partno, self._t_partno_score, self._t_is_only_part_no = get_title_partno_score(
            self.title1, self.title2, self.album1, self.sortalbum1
        )
        if self._t_is_partno:
            self.title_c = strip_part_number(self.title_c)

        # Title
        self._t1_numbers = ""
        self._t2_numbers = ""
        self._t1_is_numeric = False
        self._t2_is_numeric = False
        self._t1_startswith_num = False
        self._t2_startswith_num = False
        self._t1_is_in_fs_name = False
        self._t1_similarity_to_fs_name = 0
        self._t1_similarity_to_t2 = 0
        self._t1_eq_t2 = False
        self._t1_is_missing = not self.title1
        if self.title1:
            self._t1_numbers = get_numbers_in_string(self.title1)
            self._t1_startswith_num = startswith_num_pattern.match(self.title1)
            self._t1_is_numeric = self._t1_numbers == self.title1
            self._t1_is_in_fs_name = self.title1.lower() in self.fs_name_lower
            self._t1_similarity_to_fs_name = similarity_score(self.title1.lower(), self.fs_name_lower)
            self._t1_eq_t2 = self.title1 == self.title2
            self._t1_similarity_to_t2 = similarity_score(self.title1.lower(), self.title2.lower())

        self._t2_is_in_fs_name = False
        self._t2_is_missing = not self.title2
        if self.title2:
            self._t2_numbers = get_numbers_in_string(self.title2)
            self._t2_startswith_num = startswith_num_pattern.match(self.title2)
            self._t2_is_numeric = self._t2_numbers == self.title2
            self._t2_is_in_fs_name = self.title2.lower() in self.fs_name_lower

        self._tc_is_numeric = False
        self._tc_is_in_fs_name = False
        self._tc_similarity_to_fs_name = 0
        if self.title_c:
            self._tc_is_numeric = get_numbers_in_string(self.title_c) == self.title_c
            self._tc_is_in_fs_name = self.title_c.lower() in self.fs_name_lower
            self._tc_similarity_to_fs_name = similarity_score(self.title_c.lower(), self.fs_name_lower)

        # Album
        self._al1_eq_al2 = False
        self._al1_similarity_to_fs_name = 0
        self._al1_similarity_to_al2 = 0
        self._al1_is_in_fs_name = False
        self._al1_is_in_title = False
        self._al1_numbers = ""
        self._al1_startswith_num = False
        self._al1_is_missing = not self.album1
        if self.album1:
            self._al1_eq_al2 = self.album1 == self.album2
            self._al1_similarity_to_fs_name = similarity_score(self.album1.lower(), self.fs_name_lower)
            self._al1_similarity_to_al2 = similarity_score(self.album1.lower(), self.album2.lower())
            self._al1_is_in_fs_name = self.album1.lower() in self.fs_name_lower
            self._al1_is_in_title = self.album1.lower() in self.title1.lower()
            self._al1_numbers = get_numbers_in_string(self.album1)
            self._al1_startswith_num = startswith_num_pattern.match(self.album1)

        self._al2_is_in_fs_name = False
        self._al2_is_in_title = False
        self._al2_numbers = ""
        self._al2_startswith_num = False
        self._al2_is_missing = not self.album2
        if self.album2:
            self._al2_is_in_fs_name = self.album2.lower() in self.fs_name_lower
            self._al2_is_in_title = self.album2.lower() in self.title2.lower()
            self._al2_numbers = get_numbers_in_string(self.album2)
            self._al2_startswith_num = startswith_num_pattern.match(self.album2)

        # Sort Album
        self._sal1_eq_sal2 = False
        self._sal1_similarity_to_fs_name = 0
        self._sal1_similarity_to_sal2 = 0
        self._sal1_is_in_fs_name = False
        self._sal1_is_in_title = False
        self._sal1_numbers = ""
        self._sal1_startswith_num = False
        self._sal1_is_missing = not self.sortalbum1
        if self.sortalbum1:
            self._sal1_eq_sal2 = self.sortalbum1 == self.sortalbum2
            self._sal1_similarity_to_fs_name = similarity_score(self.sortalbum1.lower(), self.fs_name_lower)
            self._sal1_similarity_to_sal2 = similarity_score(self.sortalbum1.lower(), self.sortalbum2.lower())
            self._sal1_is_in_fs_name = self.sortalbum1.lower() in self.fs_name_lower
            self._sal1_is_in_title = self.sortalbum1.lower() in self.title1.lower()
            self._sal1_numbers = get_numbers_in_string(self.sortalbum1)
            self._sal1_startswith_num = startswith_num_pattern.match(self.sortalbum1)

        self._sal2_is_in_fs_name = False
        self._sal2_is_in_title = False
        self._sal2_numbers = ""
        self._sal2_startswith_num = False
        self._sal2_is_missing = not self.sortalbum2
        if self.sortalbum2:
            self._sal2_is_in_fs_name = self.sortalbum2.lower() in self.fs_name_lower
            self._sal2_is_in_title = self.sortalbum2.lower() in self.title2.lower()
            self._sal2_numbers = get_numbers_in_string(self.sortalbum2)
            self._sal2_startswith_num = startswith_num_pattern.match(self.sortalbum2)

        # Combo Title/Album/Sort Album
        self._al_similarity_to_t = 0
        self._al_similarity_to_sal = 0
        self._t_similarity_to_al = 0
        self._t_similarity_to_sal = 0
        self._sal_similarity_to_t = 0
        self._sal_similarity_to_al = 0
        if all((self.title1, self.album1)):
            self._al_similarity_to_t = similarity_score(self.album1.lower(), self.title1.lower())
            self._al_similarity_to_t = self._al_similarity_to_t

        if all((self.title1, self.sortalbum1)):
            self._sal_similarity_to_t = similarity_score(self.sortalbum1.lower(), self.title1.lower())
            self._sal_similarity_to_t = self._sal_similarity_to_t

        if all((self.album1, self.sortalbum1)):
            self._al_similarity_to_sal = similarity_score(self.album1.lower(), self.sortalbum1.lower())
            self._al_similarity_to_sal = self._al_similarity_to_sal

        # Artist
        self._ar1_is_in_fs_name = False
        self._ar1_similarity_to_fs_name = 0
        self._ar1_is_graphic_audio = False
        self._ar1_eq_comment_narrator = False
        self._ar1_eq_ar2 = False
        self._ar1_is_missing = not self.artist1
        if self.artist1:
            self._ar1_eq_ar2 = self.artist1 == self.artist2
            self._ar1_is_in_fs_name = self.artist1.lower() in self.fs_name_lower
            self._ar1_similarity_to_fs_name = similarity_score(self.artist1.lower(), self.fs_name_lower)
            self._ar1_is_graphic_audio = has_graphic_audio(self.artist1)

        self._ar2_is_in_fs_name = False
        self._ar2_is_graphic_audio = False
        self._ar2_is_missing = not self.artist2
        if self.artist2:
            self._ar2_is_in_fs_name = self.artist2.lower() in self.fs_name_lower
            self._ar2_is_graphic_audio = has_graphic_audio(self.artist2)

        # Album Artist
        self._aar1_is_in_fs_name = False
        self._aar1_similarity_to_fs_name = 0
        self._aar1_is_graphic_audio = False
        self._aar1_eq_aar2 = False
        self._aar1_is_missing = not self.albumartist1
        if self.albumartist1:
            self._aar1_eq_aar2 = self.albumartist1 == self.albumartist2
            self._aar1_is_in_fs_name = self.albumartist1.lower() in self.fs_name_lower
            self._aar1_similarity_to_fs_name = similarity_score(self.albumartist1.lower(), self.fs_name_lower)
            self._aar1_is_graphic_audio = has_graphic_audio(self.albumartist1)

        self._aar2_is_missing = not self.albumartist2
        if self.albumartist2:
            self._aar2_is_in_fs_name = self.albumartist2.lower() in self.fs_name_lower
            self._aar2_is_graphic_audio = has_graphic_audio(self.albumartist2)

        # Combo Artist/Album Artist
        self._ar_similarity_to_aar = 0
        self._aar_similarity_to_ar = 0
        if all((self.artist1, self.albumartist1)):
            self._ar_similarity_to_aar = similarity_score(self.artist1.lower(), self.albumartist1.lower())
            self._ar_similarity_to_aar = self._ar_similarity_to_aar

        self._ar1_parsed_author = parse_author(self.artist1, "generic")
        self._ar1_parsed_narrator = parse_narrator(self.artist1, "generic")
        self._ar1_parsed_author_similarity_to_narrator = (
            similarity_score(self._ar1_parsed_author, self._ar1_parsed_narrator) if self._ar1_parsed_author else 0
        )
        self._aar1_parsed_author = parse_author(self.albumartist1, "generic")
        self._aar1_parsed_narrator = parse_narrator(self.albumartist1, "generic")
        self._aar1_parsed_author_similarity_to_narrator = (
            similarity_score(self._aar1_parsed_author, self._aar1_parsed_narrator) if self._aar1_parsed_author else 0
        )

        # Comment
        self._ar1_eq_comment_author = False
        self._ar1_eq_comment_narrator = False
        self._aar1_eq_comment_author = False
        self._aar1_eq_comment_narrator = False
        self._comment_author_eq_comment_narrator = False

        # Complex
        self._ar_eq_aar = bool(self.artist1 and self.albumartist1 and self.artist1 == self.albumartist1)
        self._ar_but_no_aar = bool(self.artist1 and not self.albumartist1)
        self._aar_but_no_ar = bool(self.albumartist1 and not self.artist1)
        self._ar_has_slash = bool("/" in self.artist1)
        self._aar_has_slash = bool("/" in self.albumartist1)

        if self.author_in_comment:
            self._comment_author_eq_comment_narrator = self.narrator_in_comment == self.author_in_comment
            if self.artist1:
                self._ar1_eq_comment_author = self.author_in_comment == self.artist1
            if self.albumartist1:
                self._aar1_eq_comment_author = self.author_in_comment == self.albumartist1

        if self.narrator_in_comment:
            if self.artist1:
                self._ar1_eq_comment_narrator = self.narrator_in_comment == self.artist1
            if self.albumartist1:
                self._aar1_eq_comment_narrator = self.narrator_in_comment == self.albumartist1

        str(self)

    def table(self):
        data = [
            [f" - {k}", v]
            for k, v in [
                (k, getattr(self, k))
                for k in sorted(
                    [k for k in dir(self) if not k.startswith("__")],
                    key=functools.cmp_to_key(custom_sort),
                )
            ]
            if not callable(v)
        ]

        return columnar(
            data,
            headers=["key", "value"],
            terminal_width=1000,
            preformatted_headers=True,
            no_borders=True,
            max_column_width=800,
            wrap_max=0,  # don't wrap
        )

    def __str__(self):

        return f"MetadataScore\n" f"{self.table()}\n"


class MetadataScore:
    def __init__(
        self,
        book: "Audiobook",
        sample_audio2_tags: dict[TagSource | AdditionalTags, str],
    ):

        self.author = AuthorScoreCard(self)
        self.narrator = NarratorScoreCard(self)
        self.title = TitleScoreCard(self)
        self.date = DateScoreCard(self)

        self._p = MetadataProps(book, sample_audio2_tags)

        self._title: str = ""
        self._author: str = ""
        self._narrator: str = ""
        self._date: str = ""
        self._albumartist: str = ""

    def __str__(self):

        return (
            f"MetadataScore\n"
            f" - author is likely:  {self.determine_author()}\n"
            f" - narrator is likely:  {self.determine_narrator()}\n"
            f" - title is likely:   {self.determine_title()}\n"
            f" - date is likely:  {self.determine_date()}\n"
        )

    def __repr__(self):
        return self.__str__()

    def get(
        self,
        key: ScoredProp,
        *,
        from_tag: TagSource | None = None,
        fallback: str = "",
    ) -> str:

        getattr(self, f"calc_{key}_scores")()
        if from_tag is None:
            from_tag, _score, _prop = getattr(self, key).is_likely

        if from_tag == "unknown":
            return fallback

        val: str = ""
        if from_tag == "comment":
            val = getattr(self._p, f"{key}_in_comment")
        elif common_str_pattern.match(from_tag):
            val = getattr(self._p, common_str_pattern.sub("", from_tag) + "_c")
        elif from_tag == "fs":
            if key == "date":
                val = self._p.fs_year
        else:
            try:
                val = getattr(self._p, f"{from_tag}1")
            except AttributeError:
                val = getattr(self._p, from_tag)

        val = clean_string(val if val else fallback)
        match key:
            case "author":
                val = parse_author(val, "generic")
            case "narrator":
                val = parse_narrator(val, "generic")
        return val

    def _tag_matcher(self, prop: str, tag: str, fallback: str = "") -> str:
        if tag == "unknown":
            return fallback

        if common_str_pattern.match(tag):
            return getattr(self._p, common_str_pattern.sub("", tag) + "_c")

        if tag == "comment":
            return getattr(self._p, f"{prop}_in_comment")

        if tag == "fs":
            try:
                val = getattr(self._p, f"fs_{tag}")
            except AttributeError:
                ...
        try:
            val = getattr(self._p, f"{tag}1")
        except AttributeError:
            val = getattr(self._p, tag)

        if prop == "title":
            self.determine_author()
            self.determine_narrator()
            val = strip_author_narrator(val, self._author, self._narrator)

        return clean_string(val if val else fallback)

    def determine_title(self, fallback: str = "Unknown", *, force: bool = False):

        if not force and self._title:
            return self._title

        self.title.reset()

        if all(
            (
                self._p._t1_is_missing,
                self._p._t2_is_missing,
                self._p._al1_is_missing,
                self._p._al2_is_missing,
                self._p._sal1_is_missing,
                self._p._sal2_is_missing,
            )
        ):
            return fallback

        title_is_title = 0
        album_is_title = 0
        sortalbum_is_title = 0
        common_title_is_title = 0
        common_album_is_title = 0
        common_sortalbum_is_title = 0

        # Title weights
        if self._p.title1:
            title_is_title += int(self._p._t1_is_in_fs_name)
            title_is_title += 2 * int(self._p._t1_similarity_to_fs_name)
            title_is_title += int(2 if self._p._t1_eq_t2 else -2)
            title_is_title += int(len(self._p.title1) / 10)
            title_is_title -= 2 * int(self._p._t1_is_numeric)
            title_is_title += 2 * self._p._t1_similarity_to_t2

        else:
            title_is_title = -404

        if self._p.title2:
            title_is_title += int(self._p._t2_is_in_fs_name)
            title_is_title -= 2 * int(self._p._t2_is_missing)
            title_is_title -= 2 * int(self._p._t2_is_numeric)

        if self._p.title1 and self._p.title2:
            common_title_is_title = max(0, title_is_title)
            common_title_is_title += int(self._p._tc_is_in_fs_name)
            common_title_is_title += 3 * self._p._tc_similarity_to_fs_name
            common_title_is_title -= 2 * int(self._p._tc_is_numeric)
            common_title_is_title += int(
                (len(self._p.title_c) if not self._p._t1_eq_t2 else -len(self._p.title_c)) / 10
            )
            common_title_is_title += 4 * self._p._t1_similarity_to_t2

        if self._p._t_is_partno:
            if self._p._t_is_only_part_no:
                title_is_title -= self._p._t_partno_score * 100
            else:
                title1_contains_partno = contains_partno_or_ch(self._p.title1)
                title2_contains_partno = contains_partno_or_ch(self._p.title2)
                if title1_contains_partno or title2_contains_partno:
                    common_title_is_title = max(
                        title_is_title,
                        common_title_is_title,
                    )
                    title_is_title -= self._p._t_partno_score * 5

        else:
            title_is_title += self._p._t_partno_score

        # Album weights
        if self._p.album1:
            album_is_title += int(self._p._al1_is_in_fs_name)
            album_is_title += int(self._p._al1_similarity_to_fs_name)
            album_is_title += 2 * self._p._al1_similarity_to_al2
            album_is_title += int(self._p._al1_is_in_title)
            album_is_title += int(len(self._p.album1) / 10)

        else:
            album_is_title = -404

        if self._p.album2:
            album_is_title += int(self._p._al2_is_in_fs_name)
            album_is_title += int(self._p._al2_is_in_title)
            album_is_title += int(2 if self._p._al1_eq_al2 else -2)

        if self._p.album1 and self._p.album2:
            common_album_is_title = max(0, album_is_title)
            common_album_is_title += int(
                (len(self._p.album_c) if not self._p._al1_eq_al2 else -len(self._p.album_c)) / 10
            )
            common_album_is_title += 4 * int(self._p._al1_similarity_to_al2)

        # Sortalbum weights
        if self._p.sortalbum1:
            sortalbum_is_title += int(self._p._sal1_is_in_fs_name)
            sortalbum_is_title += int(self._p._sal1_similarity_to_fs_name)
            sortalbum_is_title += 2 * self._p._sal1_similarity_to_sal2
            sortalbum_is_title += int(self._p._sal1_is_in_title)
            sortalbum_is_title += len(self._p.sortalbum1)

        else:
            sortalbum_is_title = -404

        if self._p.sortalbum2:
            sortalbum_is_title += int(self._p._sal2_is_in_fs_name)
            sortalbum_is_title += int(self._p._sal2_is_in_title)
            sortalbum_is_title += int(2 if self._p._sal1_eq_sal2 else -2)

        if self._p.sortalbum1 and self._p.sortalbum2:
            common_sortalbum_is_title = max(0, sortalbum_is_title)
            common_sortalbum_is_title += int(
                (len(self._p.sortalbum_c) if not self._p._sal1_eq_sal2 else -len(self._p.sortalbum_c)) / 10
            )
            common_sortalbum_is_title += 4 * int(self._p._sal1_similarity_to_sal2)

        # Update the scores
        self.title.title_is_title = title_is_title
        self.title.album_is_title = album_is_title
        self.title.sortalbum_is_title = sortalbum_is_title
        self.title.common_title_is_title = common_title_is_title
        self.title.common_album_is_title = common_album_is_title
        self.title.common_sortalbum_is_title = common_sortalbum_is_title

        self._title = self.title._value or fallback
        return self._title

    def determine_author(self, fallback: str = "Unknown", *, force: bool = False):

        if not force and self._author:
            return self._author

        self.author.reset()

        artist_is_author = 0
        albumartist_is_author = 0
        common_artist_is_author = 0
        common_albumartist_is_author = 0
        comment_contains_author = 0

        if all(
            (
                self._p._ar1_is_missing,
                self._p._ar2_is_missing,
                self._p._aar1_is_missing,
                self._p._aar2_is_missing,
                not self._p.author_in_comment,
            )
        ):
            return fallback

        if self._p.comment:
            comment_contains_author += 20 * int(bool(self._p.author_in_comment))

        # Artist weights
        if self._p.artist1:
            artist_is_author += int(self._p._ar1_is_in_fs_name)
            artist_is_author += max(0, int(self._p._ar1_similarity_to_fs_name))
            artist_is_author -= 500 * int(self._p._ar1_is_graphic_audio)
            artist_is_author += int(10 if self._p._ar1_parsed_author else -10)
            artist_is_author += self._p._ar1_parsed_author_similarity_to_narrator

            if self._p.author_in_comment:
                artist_is_author += similarity_score(self._p.author_in_comment, self._p.artist1)
            if self._p.narrator_in_comment:
                artist_is_author += 10 * int(-1 if self._p._ar1_eq_comment_narrator else 1)
        else:
            artist_is_author = -404

        if self._p.artist2:
            artist_is_author += int(self._p._ar2_is_in_fs_name)
            artist_is_author -= 250 * int(self._p._ar2_is_graphic_audio)

        if self._p.artist1 and self._p.artist2:
            common_artist_is_author = max(0, artist_is_author)
            common_artist_is_author += int(10 if not self._p._ar1_eq_ar2 else -10)
            artist_is_author += int(11 if self._p._ar1_eq_ar2 else -11)

        # Album Artist weights
        if self._p.albumartist1:
            albumartist_is_author += int(self._p._aar1_is_in_fs_name)
            albumartist_is_author += max(0, int(self._p._aar1_similarity_to_fs_name))
            albumartist_is_author -= 500 * int(self._p._aar1_is_graphic_audio)
            albumartist_is_author += int(10 if self._p._aar1_parsed_author else -10)
            albumartist_is_author += self._p._aar1_parsed_author_similarity_to_narrator

            if self._p.author_in_comment:
                albumartist_is_author += similarity_score(self._p.author_in_comment, self._p.albumartist1)

            if self._p.narrator_in_comment:
                albumartist_is_author += 10 * int(-1 if self._p._aar1_eq_comment_narrator else 1)
        else:
            albumartist_is_author = -404

        if self._p.albumartist2:
            albumartist_is_author += int(self._p._aar2_is_in_fs_name)
            albumartist_is_author -= 250 * int(self._p._aar2_is_graphic_audio)

        if self._p.albumartist1 and self._p.albumartist2:
            common_albumartist_is_author = max(0, albumartist_is_author)
            common_albumartist_is_author += int(10 if not self._p._aar1_eq_aar2 else -10)
            albumartist_is_author += int(10 if self._p._aar1_eq_aar2 else -10)

        if self._p.artist1 != self._p.albumartist1:
            artist_is_author += 1

        if self._p.author_in_comment and self._p.narrator_in_comment:
            comment_contains_author += 10 * int(-1 if self._p._comment_author_eq_comment_narrator else 1)

        # Update the scores
        self.author.artist_is_author = artist_is_author
        self.author.albumartist_is_author = albumartist_is_author
        self.author.common_artist_is_author = common_artist_is_author
        self.author.common_albumartist_is_author = common_albumartist_is_author
        self.author.comment_contains_author = comment_contains_author

        self._author = parse_author(self.author._value or fallback, "generic")
        return self._author

    def determine_narrator(self, fallback: str = "-", *, force: bool = False):

        if not force and self._narrator:
            return self._narrator

        self.narrator.reset()

        if all(
            (
                self._p._ar1_is_missing,
                self._p._ar2_is_missing,
                self._p._aar1_is_missing,
                self._p._aar2_is_missing,
                not self._p.narrator_in_comment,
            )
        ):
            return fallback

        artist_is_narrator = 0
        albumartist_is_narrator = 0
        composer_is_narrator = 0
        common_artist_is_narrator = 0
        common_albumartist_is_narrator = 0
        comment_contains_narrator = 0

        if self._p.comment:
            comment_contains_narrator += 40 * int(bool(self._p.narrator_in_comment))

        # If artist and album artist are the same, they're probably author, not narrator.
        # If either is missing, then the one that is present is probably the author.

        # Sometimes we get some false positives, where artist is narrator and composer is the author, but
        # we can only pick one.
        if any([self._p._ar_eq_aar, self._p._ar_but_no_aar, self._p._aar_but_no_ar]):
            artist_is_narrator = 7 if self._p._ar_has_slash else -99
            albumartist_is_narrator = 7 if self._p._aar_has_slash else -99

        else:
            # Artist weights
            if self._p.artist1 and not self.author._is_likely[0] == "artist":

                artist_is_narrator += int(self._p._ar1_is_in_fs_name)
                artist_is_narrator -= max(0, int(self._p._ar1_similarity_to_fs_name))
                artist_is_narrator -= 500 * int(self._p._ar1_is_graphic_audio)
                artist_is_narrator += int(10 if self._p._ar1_parsed_narrator else -10)
                artist_is_narrator -= self._p._ar1_parsed_author_similarity_to_narrator

                if self._p.narrator_in_comment:
                    artist_is_narrator += similarity_score(self._p.narrator_in_comment, self._p.artist1)
                if self._p.author_in_comment:
                    artist_is_narrator += 10 * int(-1 if self._p._ar1_eq_comment_author else 1)

            else:
                artist_is_narrator = -404

            if self._p.artist2:
                artist_is_narrator += int(self._p._ar2_is_in_fs_name)
                artist_is_narrator -= 10 * int(self._p._ar2_is_missing)
                artist_is_narrator -= 250 * int(self._p._ar2_is_graphic_audio)

            if self._p.artist1 and self._p.artist2:
                common_artist_is_narrator = max(0, artist_is_narrator)
                common_artist_is_narrator += int(10 if not self._p._ar1_eq_ar2 else -10)
                artist_is_narrator += int(10 if self._p._ar1_eq_ar2 else -10)

            # Album Artist weights
            if self._p.albumartist1 and not self.author._is_likely[0] == "albumartist":
                albumartist_is_narrator += int(self._p._aar1_is_in_fs_name)
                albumartist_is_narrator -= max(0, int(self._p._aar1_similarity_to_fs_name))
                albumartist_is_narrator -= 500 * int(self._p._aar1_is_graphic_audio)
                albumartist_is_narrator += int(10 if self._p._aar1_parsed_narrator else -10)
                albumartist_is_narrator -= self._p._aar1_parsed_author_similarity_to_narrator

                if self._p.narrator_in_comment:
                    albumartist_is_narrator += similarity_score(self._p.narrator_in_comment, self._p.albumartist1)

                if self._p.author_in_comment:
                    albumartist_is_narrator += 10 * int(-1 if self._p._aar1_eq_comment_author else 1)
            else:
                albumartist_is_narrator = -404

            if self._p.albumartist2:
                albumartist_is_narrator += int(self._p._aar2_is_in_fs_name)
                albumartist_is_narrator -= 10 * int(self._p._aar2_is_missing)
                albumartist_is_narrator -= 250 * int(self._p._aar2_is_graphic_audio)

            if self._p.albumartist1 and self._p.albumartist2:
                common_albumartist_is_narrator = max(0, albumartist_is_narrator)
                common_albumartist_is_narrator += int(10 if not self._p._aar1_eq_aar2 else -10)
                albumartist_is_narrator += int(10 if self._p._aar1_eq_aar2 else -10)

        if self._p.composer and self._p.composer != self._p.artist1:
            composer_is_narrator = 5 * int(len(to_words(self._p.composer)))

        self.narrator.artist_is_narrator = artist_is_narrator
        self.narrator.albumartist_is_narrator = albumartist_is_narrator
        self.narrator.common_artist_is_narrator = common_artist_is_narrator
        self.narrator.common_albumartist_is_narrator = common_albumartist_is_narrator
        self.narrator.comment_contains_narrator = comment_contains_narrator
        self.narrator.composer_is_narrator = composer_is_narrator

        self._narrator = parse_narrator(self.narrator._value or fallback, "generic")
        return self._narrator

    def determine_albumartist(self, *, force: bool = False):
        # If artist and albumartist are different, or if albumartist contains a / we want to process.

        if not force and self._albumartist:
            return self._albumartist

        if self._p._aar1_is_missing or self._p._aar1_eq_comment_narrator:
            self._albumartist = parse_author(self.author._value, "generic", fallback=self._p.author_in_comment)
        elif self._p._aar_has_slash or self.narrator._value != self.author._value:
            self._albumartist = parse_narrator(self._p.albumartist1, "generic")
        else:
            self._albumartist = parse_author(self._p.albumartist1, "generic")

        return self._albumartist

    def determine_date(self, fallback: str = "", *, force: bool = False):

        if not force and self._date:
            return self._date

        self.date.reset()

        date_is_date = 0
        fs_contains_date = 0

        if self._p.date and not self._p.fs_year:
            date_is_date += 10
        elif self._p.fs_year and not self._p.date:
            fs_contains_date += 10
        elif self._p.date and self._p.fs_year:
            if int(self._p.year) < int(self._p.fs_year):
                date_is_date += 1
            else:
                fs_contains_date += 1

        self.date.date_is_date = date_is_date
        self.date.fs_contains_date = fs_contains_date

        from_tag, _score, _prop = self.date._is_likely

        if from_tag == "fs":
            return self._p.fs_year

        self._date = self._tag_matcher("date", from_tag, fallback)

        return self._date


def extract_metadata(book: "Audiobook", quiet: bool = False) -> "Audiobook":

    if not quiet:
        smart_print(
            f"Sampling [[{book.sample_audio1.name}]] for book metadata and quality info:",
            highlight_color=PATH_COLOR,
        )

    li = print_list_item if not quiet else lambda *_: None

    # read id3 tags of audio file
    sample_audio1_tags = extract_id3_tags(book.sample_audio1)
    sample_audio2_tags = extract_id3_tags(
        book.sample_audio2 or book.sample_audio1  # if only one audio file, fall back to the same file
    )

    for tag, value in sample_audio1_tags.items():
        if hasattr(book, f"id3_{tag}"):
            setattr(book, f"id3_{tag}", value)

    book.id3_year = get_year_from_date(book.id3_date)
    # Note: only works for mp3 files, will always return None for m4b files
    book.has_id3_cover = bool(extract_cover_art(book.sample_audio1))

    id3_score = MetadataScore(book, sample_audio2_tags)

    book.title = id3_score.determine_title(book.fs_title)
    book.album = book.title
    book.sortalbum = strip_leading_articles(book.title)

    book.artist = id3_score.determine_author(book.fs_author)
    book.narrator = id3_score.determine_narrator(book.fs_narrator)
    book.albumartist = id3_score.determine_albumartist()

    li(f"Title: {book.title}")
    li(f"Author: {book.author}")
    if book.narrator:
        li(f"Narrator: {book.narrator}")

        # TODO: Author/Narrator and "Book name by Author" in folder name

        # If comment does not have narrator, but narrator is not empty,
        # pre-pend narrator to comment as "Narrated by <narrator>. <existing comment>"
        if not book.id3_comment:
            book.id3_comment = f"Read by {book.narrator}"
        elif not parse_narrator(book.id3_comment, "comment"):
            book.id3_comment = f"Read by {book.narrator} // {book.id3_comment}"
        book.composer = book.narrator

    book.date = id3_score.determine_date(book.fs_year)
    if book.date:
        li(f"Date: {book.date}")
    # extract 4 digits from date
    book.year = get_year_from_date(book.date)

    # convert bitrate and sample rate to friendly to kbit/s, rounding to nearest tenths, e.g. 44.1 kHz
    li(f"Quality: {book.bitrate_friendly} @ {book.samplerate_friendly}")
    li(f"Duration: {book.duration('inbox', 'human')}")
    if not book.has_id3_cover:
        li(f"No cover art")

    return book


def map_kid3_keys(in_dict: dict[str, Any]):
    """Renames keys from kid3 format to our format:

    - lowercase keys
    - remove spaces
    """

    out_dict = {}
    for key, value in in_dict.items():
        new_key = key.lower().replace(" ", "")
        out_dict[new_key] = value

    return out_dict
