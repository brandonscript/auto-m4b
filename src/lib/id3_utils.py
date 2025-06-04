import datetime
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, cast, Literal, NamedTuple, overload, TYPE_CHECKING, Union

import bidict
import ffmpeg
from mutagen.mp3 import HeaderNotFoundError
from tinta import Tinta

from lib.ffprobe_utils import ffprobe_file
from lib.formatters import strip_leading_the
from lib.ol_lookup import open_library_lookup_author, open_library_lookup_title
from src.lib.books_tree import BooksTree
from src.lib.cleaners import strip_leading_articles
from src.lib.fs_utils import find_first_audio_file
from src.lib.misc import compare_trim
from src.lib.parsers import (
    get_year_from_date,
    parse_narrator,
)
from src.lib.scorers import (
    MetadataScore,
)
from src.lib.term import (
    nl,
    PATH_COLOR,
    print_debug,
    print_error,
    print_list_item,
    smart_print,
)
from src.lib.typing import AdditionalTags, BadFileError, Id3TagDict, Id3TagDictWithDnumTnum, NotNone, TagSource

MissingApplicationError = ValueError

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook

CacheValue = Union[Id3TagDict, Literal["__BAD__"]]


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
        ("sortalbum", str),
        ("albumartist", str),
        ("composer", str),
        ("date", str),
        ("track_num", tuple[int, int]),
        ("comment", str),
    ],
)


def _tags_from_dict(tags: Id3TagDictWithDnumTnum) -> TagSet:
    title = str(tags.get("title", ""))
    artist = str(tags.get("artist", ""))  # type: ignore
    album = str(tags.get("album", ""))
    sortalbum = str(tags.get("sortalbum", album))
    albumartist = str(tags.get("albumartist", ""))
    composer = str(tags.get("composer", ""))
    date = str(tags.get("date", ""))
    track_num = cast(tuple[int, int], tags.get("track_num", tags.get("track", (1, 1))))
    if not track_num:
        track_num = cast(tuple[int, int], tags.get("track", (1, 1)))
    comment = str(tags.get("comment", ""))

    try:
        d = datetime.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        d = None
    year = get_year_from_date(date, to_int=True) or (d.year if d else None)
    if year or d:
        date = d.strftime("%Y-%m-%d") if d else f"{year}-01-01"

    return TagSet(title, artist, album, sortalbum, albumartist, composer, date, track_num, comment)


def write_m4b_tags(
    file: Path,
    tags: Id3TagDictWithDnumTnum,
    *,
    cover: Path | None = None,
):
    """Uses mutagen to write id3 tags to an m4b file"""
    try:
        from mutagen.mp4 import MP4, MP4Cover
    except ImportError:
        raise MissingApplicationError(
            "Error: mutagen is not available, please install it with\n\n $ pip install mutagen\n\n...then try again"
        )

    if not file.exists():
        raise FileNotFoundError(f"Error: Cannot write id3 tags, '{file}' does not exist")

    title, artist, album, sortalbum, albumartist, composer, date, _tn, comment = _tags_from_dict(tags)

    if f := MP4(file):
        f["\xa9nam"] = title
        f["\xa9ART"] = artist
        f["\xa9alb"] = album
        f["\xa9soa"] = sortalbum
        f["aART"] = albumartist
        f["\xa9wrt"] = composer
        f["\xa9day"] = date
        f["trkn"] = [(1, 1)]
        f["disk"] = ""
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
    file: "Path | BooksTree",
    tags: Id3TagDictWithDnumTnum,
    *,
    cover: Path | None = None,
) -> None:
    from src.lib.id3_tags import Id3Tags

    path = file.path if isinstance(file, BooksTree) else file
    if path.suffix in [".m4b", ".m4a"]:
        write_m4b_tags(path, tags, cover=cover)
    else:
        write_mp3_tags(path, tags, cover=cover)
    # Delete from tags cache
    Id3Tags.rm_from_cache(path)
    ...
    ...


def write_mp3_tags(
    file: Path,
    tags: Id3TagDictWithDnumTnum,
    *,
    cover: Path | None = None,
    exclude: list[Literal["track_num", "disc_num"]] = [],
) -> None:
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

    title, artist, album, sortalbum, albumartist, composer, date, _tn, comment = _tags_from_dict(tags)

    if f := EasyID3(file):
        f["title"] = title
        f["artist"] = artist
        f["album"] = album
        f["albumsort"] = sortalbum
        f["albumartist"] = albumartist
        f["author"] = artist
        f["composer"] = composer
        f["comment"] = comment
        f["tracknumber"] = "1/1"
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

    book_to_check = Audiobook(m4b_to_check).extract_metadata()

    title_needs_updating = False
    author_needs_updating = False
    narrator_needs_updating = False
    date_needs_updating = False
    comment_needs_updating = False
    cover_needs_updating = False

    updates = []

    new_tags = book.to_id3_tags()
    # We don't want to write track/disc tags to the m4b
    new_tags.pop("track_num", None)
    new_tags.pop("disc_num", None)

    ol_author_candidates = [
        (open_library_lookup_author(book.author, method="score"), "author"),
        (open_library_lookup_author(book.author, method="similarity"), "author"),
        (open_library_lookup_author(book.narrator, method="similarity"), "narrator"),
    ]
    ol_title = open_library_lookup_title(book.title, author=book.author, narrator=book.narrator, method="similarity")
    ol_author, author_prop = next(
        (
            c
            for c in sorted(ol_author_candidates, key=lambda x: x[0].score(fallback=999) if x[0] else 0.0)
            if c[0] and c[0].has_match
        ),
        (None, None),
    )

    def _print_needs_updating(what: str, left_value: str | None, right_value: str) -> None:
        if left_value:
            s = Tinta().dark_grey(f"- ").grey(what).dark_grey("needs updating:")
            s.amber(left_value)
        else:
            s = Tinta().dark_grey(f"- ").grey(what).dark_grey("is missing")
        s.dark_grey("»").mint(right_value)
        smart_print(s.to_str())

    def _check_title(orop: str, id3_tag: TagSource):
        nonlocal title_needs_updating, new_tags
        tag_value = getattr(book_to_check, f"id3_{id3_tag}")
        if bool(ol_title):
            if ol_title.has_match and ol_title.score(fallback=999) < 0.9:
                title_needs_updating = True
                new_title = NotNone(ol_title).title
                updates.append(lambda: _print_needs_updating(orop, tag_value, new_title))
                new_tags[id3_tag] = new_title
                new_tags["sortalbum"] = strip_leading_the(new_title)
        elif book.title and (tag_value != book.title):
            title_needs_updating = True
            updates.append(lambda: _print_needs_updating(orop, tag_value, book.title))
            new_tags[id3_tag] = book.title
            new_tags["sortalbum"] = strip_leading_the(book.title)

    def _check_author(prop: str, id3_tag: TagSource):
        nonlocal author_needs_updating, narrator_needs_updating, new_tags
        tag_value = getattr(book_to_check, f"id3_{id3_tag}")

        if bool(ol_title):
            if ol_title.has_match and (
                ol_title.author_score(fallback=999) < 0.9 or ol_title.author_and_narrator_swapped
            ):
                author_needs_updating = True
                new_author = NotNone(ol_title).author  # will return correct author or narrator if swapped
                updates.append(lambda: _print_needs_updating(prop, tag_value, new_author))
                new_tags[id3_tag] = new_author
                if ol_title.author_and_narrator_swapped:
                    narrator_needs_updating = True
                    new_narrator = NotNone(ol_title).narrator
                    updates.append(lambda: _print_needs_updating(prop, tag_value, new_narrator))
                    new_tags["composer"] = new_narrator
        elif bool(ol_author):
            if ol_author.has_match and (ol_author.score(fallback=999) < 0.9 or author_prop == "narrator"):
                if author_prop == "author":
                    author_needs_updating = True
                    new_author = NotNone(ol_author).name
                    updates.append(lambda: _print_needs_updating(prop, tag_value, NotNone(ol_author).name))
                    new_tags[id3_tag] = new_author
                elif author_prop == "narrator":
                    narrator_needs_updating = True
                    new_narrator = NotNone(ol_author).name
                    updates.append(lambda: _print_needs_updating(prop, tag_value, new_narrator))
                    new_tags["composer"] = new_narrator
        elif book.author and (tag_value != book.author):
            author_needs_updating = True
            updates.append(lambda: _print_needs_updating(prop, tag_value, book.author))
            new_tags[id3_tag] = book.author

    def _check_narrator(prop: str, id3_tag: TagSource):
        nonlocal narrator_needs_updating
        tag_value = getattr(book_to_check, f"id3_{id3_tag}")
        if bool(ol_title):
            if ol_title.has_match and ol_title.author_and_narrator_swapped:
                narrator_needs_updating = True
                new_author = NotNone(ol_title).author
                updates.append(lambda: _print_needs_updating(prop, tag_value, new_author))
                new_tags["artist"] = new_author
                new_tags["albumartist"] = new_author
        elif bool(ol_author):
            if ol_author.has_match and author_prop == "narrator":
                narrator_needs_updating = True
                new_narrator = NotNone(ol_author).name
                updates.append(lambda: _print_needs_updating(prop, tag_value, new_narrator))
                new_tags["composer"] = new_narrator
        elif book.narrator and (tag_value != book.narrator):
            narrator_needs_updating = True
            updates.append(lambda: _print_needs_updating(prop, tag_value, book.narrator))
            new_tags["composer"] = book.narrator

    def _check_date(prop: str, id3_tag: TagSource):
        nonlocal date_needs_updating, new_tags
        tag_value = getattr(book_to_check, f"id3_{id3_tag}")
        tags_years_match = get_year_from_date(tag_value) == get_year_from_date(book.date)
        ol_years_match = (
            bool(ol_title) and ol_title.has_match and get_year_from_date(ol_title.date) == get_year_from_date(book.date)
        )
        if not ol_years_match and NotNone(ol_title).score(fallback=0) > 0.75:
            date_needs_updating = True
            new_date = NotNone(ol_title).date
            updates.append(lambda: _print_needs_updating(prop, tag_value, new_date))
            new_tags[id3_tag] = new_date
        elif book.date and not tags_years_match:
            date_needs_updating = True
            updates.append(lambda: _print_needs_updating(prop, tag_value, book.date))
            new_tags[id3_tag] = book.date

    # Title - because multi-file books usually have unique titles for each track,
    # but a merged m4b only gets one title (usually the same as the album name)
    # if bool(ol_title):
    #     if ol_title.has_match and ol_title.score() < 0.9:
    #         title_needs_updating = True
    #         updates.append(lambda: _print_needs_updating("Title", book_to_check.id3_title, ol_title.name))
    # elif book.title and (book_to_check.id3_title != book.title):
    #     title_needs_updating = True
    #     updates.append(lambda: _print_needs_updating("Title", book_to_check.id3_title, book.title))
    _check_title("Title", "title")

    # Author
    # if bool(ol_title):
    #     if ol_title.has_match and (ol_title.author_score() < 0.9 or ol_title.author_is_narrator):
    #         author_needs_updating = True
    #         updates.append(lambda: _print_needs_updating("Artist (author)", book_to_check.id3_artist, ol_title.author))
    # elif bool(ol_author):
    #     if ol_author.has_match and (ol_author.score() < 0.9 or author_prop == "narrator"):
    #         author_needs_updating = True
    #         updates.append(lambda: _print_needs_updating("Artist (author)", book_to_check.id3_artist, ol_author.name))
    # elif book.author and (book_to_check.id3_artist != book.author):
    #     author_needs_updating = True
    #     updates.append(lambda: _print_needs_updating("Artist (author)", book_to_check.id3_artist, book.author))
    _check_author("Artist (author)", "artist")

    # Album
    # if bool(ol_title):
    #     if ol_title.has_match and ol_title.score() < 0.9:
    #         title_needs_updating = True
    #         updates.append(lambda: _print_needs_updating("Album (title)", book_to_check.id3_album, ol_title.name))
    # elif book.title and book_to_check.id3_album != book.title:
    #     title_needs_updating = True
    #     updates.append(lambda: _print_needs_updating("Album (title)", book_to_check.id3_album, book.title))
    _check_title("Album (title)", "album")

    # Sort album
    # if bool(ol_title):
    #     if ol_title.has_match and ol_title.score() < 0.9:
    #         title_needs_updating = True
    #         updates.append(
    #             lambda: _print_needs_updating("Sort album (title)", book_to_check.id3_sortalbum, ol_title.name)
    #         )
    # elif book.title and book_to_check.id3_sortalbum != book.title:
    #     title_needs_updating = True
    #     updates.append(lambda: _print_needs_updating("Sort album (title)", book_to_check.id3_sortalbum, book.title))
    _check_title("Sort album (title)", "sortalbum")

    # if book.author and book_to_check.id3_albumartist != book.author:
    #     author_needs_updating = True
    #     updates.append(
    #         lambda: _print_needs_updating("Album artist (author)", book_to_check.id3_albumartist, book.author)
    #     )
    _check_author("Album artist (author)", "albumartist")

    # if book.narrator and book_to_check.id3_composer != book.narrator:
    #     narrator_needs_updating = True
    #     updates.append(lambda: _print_needs_updating("Composer (narrator)", book_to_check.id3_composer, book.narrator))
    _check_narrator("Composer (narrator)", "composer")

    # if book.date and get_year_from_date(book_to_check.id3_date) != get_year_from_date(book.date):
    #     date_needs_updating = True
    #     updates.append(lambda: _print_needs_updating("Date", book_to_check.id3_date, book.date))
    #     new_tags["date"] = book.date
    _check_date("Date", "date")

    if book.comment and compare_trim(book_to_check.id3_comment, book.comment):
        comment_needs_updating = True
        updates.append(lambda: _print_needs_updating("Comment", book_to_check.id3_comment, book.comment))
        new_tags["comment"] = book.comment

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
        write_id3_tags_mutagen(m4b_to_check, new_tags, cover=book.cover_art_file)
        [update() for update in updates]
        smart_print(Tinta("\nDone").mint("✓").to_str())

    else:
        smart_print(Tinta().mint(" ✓\n").to_str())

    nl()


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
            # find a stream that is jpg or png and has a disposition of attached_pic
            for stream in ffresult.get("streams", []):
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
                        f"0:{stream['index']}",  # type: ignore
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


def is_id3_tag_dict(id3: Any) -> bool:
    """Checks if the id3 tag dict is valid by looking for the most common tags"""
    if not isinstance(id3, dict):
        return False
    if not all(isinstance(v, str) for v in id3.values()):
        return False
    return "title" in id3 or "album" in id3 or "artist" in id3 or "albumartist" in id3


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


def extract_metadata(book: "Audiobook", console: bool = False) -> "Audiobook":

    from src.lib.id3_tags import Id3Tags

    if console:
        smart_print(
            f"Sampling [[{book.sample_audio1.name}]] for book metadata and quality info:",
            highlight_color=PATH_COLOR,
        )

    t1 = time.time()
    li = print_list_item if console else lambda *_: None

    # read id3 tags of audio file
    sample_audio1_tags = Id3Tags.from_file(book.sample_audio1)
    sample_audio2_tags = Id3Tags.from_file(
        book.sample_audio2 or book.sample_audio1  # if only one audio file, fall back to the same file
    )

    t2 = time.time()

    for tag, value in ((s := sample_audio1_tags) and s.to_dict() or {}).items():
        if hasattr(book, f"id3_{tag}"):
            setattr(book, f"id3_{tag}", value)

    book.id3_year = get_year_from_date(book.id3_date)
    # Note: only works for mp3 files, will always return None for m4b files
    book.has_id3_cover = bool(extract_cover_art(book.sample_audio1))

    id3_score = MetadataScore(book, sample_audio2_tags)  # type: ignore

    t3 = time.time()
    book.title = id3_score.determine_title(fallback=book.fs_title)
    book.album = book.title
    book.sortalbum = strip_leading_articles(book.title)

    book.artist = id3_score.determine_author(fallback=book.fs_author)
    book.narrator = id3_score.determine_narrator(fallback=book.fs_narrator)
    book.albumartist = id3_score.determine_albumartist(fallback=book.fs_author)

    t4 = time.time()

    li(f"Title: {book.title}")
    li(f"Author: {book.artist}")
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

    t5 = time.time()

    _all_times = {
        "get_files_and_extract_id3_tags": t2 - t1,
        "metadata_score": t3 - t2,
        "author_narrator": t4 - t3,
        "end": t5 - t4,
        "total": t5 - t1,
    }

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
