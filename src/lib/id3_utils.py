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

from src.lib.ffprobe_utils import ffprobe_file
from src.lib.formatters import strip_leading_the
from src.lib.books_tree import BooksTree
from src.lib.cleaners import (
    minimalist_title,
    strip_leading_articles,
    strip_leading_author_dash,
    title_case_ol_title,
)
from src.lib.fs_utils import find_first_audio_file
from src.lib.misc import compare_trim
from src.lib.ol_lookup import (
    id3_prefer_colon_separator,
    open_library_lookup_author,
    open_library_lookup_title,
)
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


def _sanitize_tags_for_write(
    tags: Id3TagDictWithDnumTnum,
    *,
    fallback_stem: str,
) -> Id3TagDictWithDnumTnum:
    """Final gate before writing tags: Title/Album must never be blank.

    Prefer existing tag values; otherwise use ``fallback_stem`` (usually the
    output filename stem). Artist/albumartist may remain blank — e.g. when the
    title came only from the filename.
    """
    out: dict = dict(tags)
    title = str(out.get("title") or "").strip()
    album = str(out.get("album") or "").strip()
    stem = (fallback_stem or "").strip() or "Unknown Audiobook"

    if not title:
        title = stem
        out["title"] = title
    if not album:
        out["album"] = title
    if not str(out.get("sortalbum") or "").strip():
        out["sortalbum"] = strip_leading_articles(str(out["album"]))
    return cast(Id3TagDictWithDnumTnum, out)


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
        f["\xa9too"] = "brandonscript/auto-m4b"

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
    # Absolute last line of defense: never write blank Title/Album to disk.
    tags = _sanitize_tags_for_write(tags, fallback_stem=path.stem)
    if path.suffix.lower() in [".m4b", ".m4a"]:
        try:
            write_m4b_tags(path, tags, cover=cover)
        except Exception as e:
            # Some inbox/fixture files are MP3/ADTS content with an .m4b extension
            # (common with incomplete remuxes). Fall back to the MP3 writer so we
            # can still fill Title/Album instead of fatally crashing.
            if "not a MP4" not in str(e) and e.__class__.__name__ != "MP4StreamInfoError":
                raise
            print_debug(f"write_m4b_tags failed ({e}); falling back to mp3 tag writer for {path.name}")
            write_mp3_tags(path, tags, cover=cover)
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

    # Guarantee title/album before comparing — convert can leave them blank when
    # source tags + fs parse both fail (e.g. boxed-set folders with Books1-3 names).
    ensure_title_and_album(book)

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
            for c in sorted(ol_author_candidates, key=lambda x: x[0].score(fallback=0.0) if x[0] else 0.0, reverse=True)
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
        author_for_title = book.artist or book.author or ""
        if bool(ol_title):
            if ol_title.has_match and ol_title.score(fallback=0.0) >= 0.5:
                new_title = _normalize_ol_title(NotNone(ol_title).title)
                # Shared Phase-3 transforms (colon subtitle + always-minimalist).
                # Date consensus (_apply_date_consensus) is intentionally not
                # wired here yet — see docs/metadata-conflicts.md.
                new_title = _finalize_convert_title(new_title, author=author_for_title)
                # If book.title already matches the words, prefer it only when it
                # is at least as "Title-Cased" as the normalized OL title (more/equal
                # capitals). That keeps intentional casing like brand names while
                # still upgrading sentence-cased book.title values from OL.
                if book.title and new_title.lower() == book.title.lower():
                    book_caps = sum(1 for c in book.title if c.isupper())
                    new_caps = sum(1 for c in new_title if c.isupper())
                    if book_caps >= new_caps:
                        new_title = (
                            strip_leading_the(book.title) if id3_tag == "sortalbum" else book.title
                        )
                # Skip only when the tag already has the exact desired value
                # (including casing). Sentence-case tags must still be upgraded.
                if new_title == (tag_value or ""):
                    return
                title_needs_updating = True
                updates.append(lambda: _print_needs_updating(orop, tag_value, new_title))
                new_tags[id3_tag] = new_title
                new_tags["sortalbum"] = strip_leading_the(new_title)
                # Keep book.* in sync so the final ensure_title_and_album pass
                # does not clobber Title-Cased OL values with sentence-cased book.title.
                if id3_tag in ("title", "album"):
                    book.title = new_title
                    book.album = new_title
                    book.sortalbum = strip_leading_the(new_title)
        elif book.title:
            # Strip edition suffixes even when OL isn't configured —
            # source tags sometimes embed LibriVox/archive.org edition info
            # (e.g. ", Version 3", ", Brown Cloth") that shouldn't appear in
            # the final audiobook title tag.
            cleaned_title = _finalize_convert_title(
                _strip_ol_edition_suffix(book.title), author=author_for_title
            )
            if tag_value != cleaned_title:
                title_needs_updating = True
                updates.append(lambda: _print_needs_updating(orop, tag_value, cleaned_title))
                new_tags[id3_tag] = cleaned_title
                new_tags["sortalbum"] = strip_leading_the(cleaned_title)
                if id3_tag in ("title", "album"):
                    book.title = cleaned_title
                    book.album = cleaned_title
                    book.sortalbum = strip_leading_the(cleaned_title)

    def _check_author(prop: str, id3_tag: TagSource):
        nonlocal author_needs_updating, narrator_needs_updating, new_tags
        tag_value = getattr(book_to_check, f"id3_{id3_tag}")

        if bool(ol_title):
            if ol_title.has_match and (
                ol_title.author_score(fallback=0.0) >= 0.5 or ol_title.author_and_narrator_swapped
            ):
                new_author = NotNone(ol_title).author  # will return correct author or narrator if swapped
                # Never overwrite a valid author with an empty string — OL may
                # match a title but not know the author for this edition.
                if not new_author:
                    pass
                else:
                    author_needs_updating = True
                    updates.append(lambda: _print_needs_updating(prop, tag_value, new_author))
                    new_tags[id3_tag] = new_author
                if ol_title.author_and_narrator_swapped:
                    narrator_needs_updating = True
                    new_narrator = NotNone(ol_title).narrator
                    updates.append(lambda: _print_needs_updating(prop, tag_value, new_narrator))
                    new_tags["composer"] = new_narrator
        elif bool(ol_author):
            if ol_author.has_match and (ol_author.score(fallback=0.0) >= 0.5 or author_prop == "narrator"):
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
        if ol_title and not ol_years_match and ol_title.score(fallback=0) > 0.75:
            date_needs_updating = True
            new_date = ol_title.date
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

    # Final pass: never leave Title/Album blank on disk, even if no other field
    # needed updating. Author may remain blank when title came from the filename.
    # Also strip OL/LibriVox edition suffixes so the ensure pass cannot re-inject
    # ", Version 3" etc. after _check_title cleaned new_tags.
    if book.title:
        book.title = _strip_ol_edition_suffix(book.title)
    if book.album:
        book.album = _strip_ol_edition_suffix(book.album)
    ensure_title_and_album(book)
    new_tags["title"] = book.title
    new_tags["album"] = book.album or book.title
    new_tags["sortalbum"] = book.sortalbum or strip_leading_articles(book.title)
    if not (book_to_check.id3_title or "").strip() or not (book_to_check.id3_album or "").strip():
        # Force a write; _check_title usually already queued notices when book.title
        # was known, so only add a notice if somehow nothing was queued yet.
        title_needs_updating = True
        if not updates:
            if not (book_to_check.id3_title or "").strip():
                updates.append(lambda: _print_needs_updating("Title", None, book.title))
            if not (book_to_check.id3_album or "").strip():
                updates.append(
                    lambda: _print_needs_updating("Album (title)", None, book.album or book.title)
                )

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


def _extract_cover_art_mutagen(path: Path) -> tuple[bytes, Literal["jpg", "png"]] | None:
    """Pull embedded cover bytes via mutagen (MP4 ``covr`` / MP3 ``APIC``).

    Some Apple/Audible-style m4b files expose PNG attached-pic streams to ffprobe
    that ffmpeg cannot demux (empty output). Mutagen still reads the ``covr`` atom.
    """
    suffix = path.suffix.lower()
    try:
        if suffix in {".m4b", ".m4a", ".mp4"}:
            from mutagen.mp4 import MP4, MP4Cover

            covers = ((MP4(path).tags or {}).get("covr")) or []
            if not covers:
                return None
            cover = covers[0]
            data = bytes(cover)
            if not data:
                return None
            if getattr(cover, "imageformat", None) == MP4Cover.FORMAT_PNG:
                return data, "png"
            return data, "jpg"

        if suffix == ".mp3":
            from mutagen.id3 import ID3

            apics = ID3(path).getall("APIC")
            if not apics:
                return None
            data = bytes(apics[0].data)
            if not data:
                return None
            mime = (getattr(apics[0], "mime", None) or "").lower()
            return data, "png" if "png" in mime else "jpg"
    except Exception:
        return None
    return None


def extract_cover_art(file: "BooksTree | Path", save_to_file: bool = False, filename: str = "cover") -> bytes | Path:
    from src.lib.config import cfg

    path = file.path if isinstance(file, BooksTree) else file

    out_file = path.parent / filename

    def _finish(data: bytes, ext: Literal["jpg", "png"]) -> bytes | Path:
        if save_to_file:
            dest = out_file.with_suffix(f".{ext}")
            dest.write_bytes(data)
            return dest
        return data

    # 1. Prefer ffmpeg stream demux when attached_pic streams are present.
    try:
        if ffresult := ffprobe_file(path):
            # find a stream that is jpg or png and has a disposition of attached_pic
            for stream in ffresult.get("streams", []):
                if stream.get("codec_name") in ["mjpeg", "png"] and stream.get("disposition", {}).get("attached_pic"):
                    content_type = stream.get("codec_name")
                    ext: Literal["jpg", "png"] = "png" if content_type == "png" else "jpg"
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
                        dest = out_file.with_suffix(f".{ext}")
                        subprocess.check_output([*common_steps, dest])
                        if dest.is_file() and dest.stat().st_size > 0:
                            return dest
                        # ffmpeg reported success but wrote nothing usable — try mutagen
                        continue
                    data = subprocess.check_output(
                        [
                            *common_steps,
                            "-f",
                            "image2pipe",
                            "-vcodec",
                            "png" if content_type == "png" else "mjpeg",
                            "-",
                        ]
                    )
                    if data:
                        return data
    except (KeyError, subprocess.CalledProcessError, OSError):
        if cfg.DEBUG:
            print_debug(f"Could not extract cover art from {file}'s streams")

    # 2. Mutagen fallback for covr/APIC atoms ffmpeg cannot demux.
    if mutagen_cover := _extract_cover_art_mutagen(path):
        return _finish(*mutagen_cover)

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


_READ_BY_PATTERN = re.compile(r"^\s*(?:read|narrated)\s+by\s+", re.I)

# Matches OL edition suffixes like ", Version 3", ", Second Edition", ", Brown Cloth"
_OL_EDITION_SUFFIX = re.compile(
    r",\s+(?:Version\s+\d+|\d+(?:st|nd|rd|th)?\s+Edition|[A-Z][a-z]+\s+(?:Edition|Cloth|Cover|Print))\s*$",
    re.I,
)


def _strip_ol_edition_suffix(title: str) -> str:
    """Remove OL edition suffixes that are not part of the canonical book title."""
    return _OL_EDITION_SUFFIX.sub("", title).strip()


def _normalize_ol_title(title: str) -> str:
    """Strip OL edition suffixes and Title-Case the result.

    OL often returns sentence case; this is the single choke point used wherever
    an OL title is assigned to ``book.title`` or written into ID3 tags.
    """
    return title_case_ol_title(_strip_ol_edition_suffix(title))


def _finalize_convert_title(title: str, author: str | None = None) -> str:
    """Shared colon + always-minimalist transforms for convert titles.

    Phase 3 wires convert outputs through ``id3_prefer_colon_separator`` and
    ``minimalist_title`` without replacing OCR / MetadataScore / OL-early
    selection. Phase 4 may replace that selection path with ``plan_fix``.
    """
    if not (title or "").strip():
        return title or ""
    out = id3_prefer_colon_separator(title)
    out = minimalist_title(out, author=author)
    return out


# Early-extraction acceptance floors (title similarity is 0..1).
_OL_TITLE_RATIO_MIN = 0.85
_OL_TITLE_TOKEN_SET_MIN = 0.9
_OL_AUTHOR_AGREE_MIN = 0.5
_OL_SOURCE_ANCHOR_MIN = 0.55

_SUBTITLE_STRIP = re.compile(
    r"\s*:\s*A\s+(?:Novel|Novella|Memoir|Story|Romance|Thriller|Mystery|Fantasy)\s*$",
    re.I,
)


def _ol_title_variants(title: str) -> list[str]:
    """Expand a title candidate with common subtitle-stripped variants."""
    t = (title or "").strip()
    if not t:
        return []
    out = [t]
    stripped = _SUBTITLE_STRIP.sub("", t).strip()
    if stripped and stripped not in out:
        out.append(stripped)
    return out


def _id3_tag_blob(*tags: Any, book: "Audiobook | None" = None) -> str:
    """Lowercased blob of ID3/path strings for conflict checks."""
    parts: list[str] = []
    attrs = (
        "title",
        "album",
        "artist",
        "albumartist",
        "composer",
        "comment",
        "copyright",
        "sortalbum",
        "genre",
    )
    for tag in tags:
        if not tag:
            continue
        for attr in attrs:
            v = getattr(tag, attr, None)
            if v:
                parts.append(str(v))
    if book is not None:
        for attr in (
            "fs_author",
            "fs_title",
            "fs_narrator",
            "id3_title",
            "id3_album",
            "id3_artist",
            "id3_albumartist",
            "id3_composer",
            "id3_comment",
        ):
            v = getattr(book, attr, None)
            if v:
                parts.append(str(v))
    return " ".join(parts).lower()


def _name_mentioned_in_blob(name: str, blob: str) -> bool:
    """True if *name* (or a substantial last-name token) appears in *blob*."""
    from rapidfuzz import fuzz

    from src.lib.ol_lookup import _title_sim

    n = (name or "").strip()
    if not n or not blob:
        return False
    if n.lower() in blob:
        return True
    # Last token often survives "Last, First" / "First Last" forms.
    tokens = [t for t in re.split(r"[\s,]+", n) if len(t) >= 4]
    if tokens and tokens[-1].lower() in blob:
        return True
    ratio, token = _title_sim(n, blob)
    return ratio >= 0.5 or token >= 0.6 or fuzz.partial_ratio(n.lower(), blob) >= 70


def _ol_title_passes_floor(query: str, ol_title: str) -> bool:
    from src.lib.ol_lookup import _title_sim

    ratio, token = _title_sim(query, ol_title)
    return ratio >= _OL_TITLE_RATIO_MIN or token >= _OL_TITLE_TOKEN_SET_MIN


def _ol_author_agrees(preferred: str, ol_author: str, author_score: float | None) -> bool:
    from src.lib.ol_lookup import _title_sim

    if author_score is not None and author_score >= _OL_AUTHOR_AGREE_MIN:
        return True
    ratio, token = _title_sim(preferred, ol_author or "")
    return ratio >= _OL_AUTHOR_AGREE_MIN or token >= _OL_AUTHOR_AGREE_MIN


def _ol_early_extraction(book: "Audiobook", tag1: Any, tag2: Any) -> "OpenLibraryTitle | None":
    """Try Open Library *before* heuristic scoring.

    Author-first strategy:
    1. Collect person candidates (fs_author first; never album-as-author).
    2. Optionally validate them via OL author lookup; prefer folder author.
    3. Search titles with the preferred author (and narrator alternate); never
       fall back to title-only when a preferred author is known.
    4. Accept only when title floors, source-title anchor, and author agreement
       (plus ID3 conflict demotion) all pass.
    """
    from rapidfuzz import fuzz

    from src.lib.config import cfg
    from src.lib.ol_lookup import _title_sim
    from src.lib.parsers import contains_partno_or_ch

    if not cfg.OPEN_LIBRARY_USER_AGENT:
        return None

    def _clean(v: str) -> str:
        return _READ_BY_PATTERN.sub("", (v or "").strip()).strip()

    raw_title = (tag1.title or "").strip()
    raw_album = (tag1.album or "").strip()
    title_has_partno = bool(raw_title and contains_partno_or_ch(raw_title))
    album_has_partno = bool(raw_album and contains_partno_or_ch(raw_album))
    basename = book.basename
    try:
        if book.path.is_file():
            basename = Path(basename).stem
    except OSError:
        pass

    # Title candidates: prefer story title over anthology album, except when the
    # track title is a part number and album is the whole-book name.
    if title_has_partno and not album_has_partno and raw_album:
        raw_order = [tag1.album, tag1.title, tag1.sortalbum, book.fs_title, basename]
    else:
        raw_order = [tag1.title, book.fs_title, tag1.sortalbum, tag1.album, basename]

    title_cands: list[str] = []
    for v in raw_order:
        for variant in _ol_title_variants((v or "").strip()):
            if variant and variant not in title_cands:
                title_cands.append(variant)

    if not title_cands:
        return None

    # Source-title anchor: ID3 title or fs_title (not album).
    source_title = raw_title or (book.fs_title or "").strip()

    # Person candidates — never use album (a title) as an author hint.
    person_cands: list[str] = []
    for v in [book.fs_author, tag1.albumartist, tag1.artist, tag1.composer]:
        cleaned = _clean(v or "")
        if cleaned and cleaned not in person_cands:
            person_cands.append(cleaned)

    narrator_cands: list[str] = []
    for v in [book.fs_narrator, getattr(tag2, "artist", None), getattr(tag2, "composer", None)]:
        cleaned = _clean(v or "")
        if cleaned and cleaned not in narrator_cands and cleaned not in person_cands[:1]:
            narrator_cands.append(cleaned)
    # Explicit "read by …" on artist/composer of sample 1
    for v in [tag1.artist, tag1.composer]:
        raw = (v or "").strip()
        if raw and _READ_BY_PATTERN.search(raw):
            cleaned = _clean(raw)
            if cleaned and cleaned not in narrator_cands:
                narrator_cands.append(cleaned)

    # Validate people via OL author lookup (best-effort; local names still preferred).
    validated: dict[str, Any] = {}
    for name in person_cands[:4]:
        ol_a = open_library_lookup_author(name, method="similarity")
        if ol_a and ol_a.has_match and (ol_a.work_count > 0 or (ol_a.score(fallback=0.0) or 0) > 0):
            validated[name] = ol_a

    preferred_author: str | None = None
    preferred_canonical: str | None = None
    # Prefer mirrored folder author when present — strongest prior for #plex layout.
    if book.fs_author and _clean(book.fs_author):
        preferred_author = _clean(book.fs_author)
    elif person_cands:
        for name in person_cands:
            if name in validated:
                preferred_author = name
                break
        if not preferred_author:
            preferred_author = person_cands[0]

    if preferred_author and preferred_author in validated:
        preferred_canonical = validated[preferred_author].name or preferred_author

    # Optional cover OCR: boost preferred author / reinforce source-title anchor.
    ocr_text = ""
    ocr_prefers_source_title = False
    if getattr(cfg, "COVER_OCR", False):
        from src.lib.cover_ocr import (
            extract_cover_ocr_text,
            ocr_mentions_name,
            ocr_supports_title,
        )

        ocr_text = extract_cover_ocr_text(book)
        if ocr_text:
            # If folder/ID3 author was weak but cover names a person candidate, prefer it.
            if not preferred_author:
                for name in person_cands:
                    if ocr_mentions_name(ocr_text, name):
                        preferred_author = name
                        if name in validated:
                            preferred_canonical = validated[name].name or name
                        break
            if source_title and ocr_supports_title(ocr_text, source_title):
                if not raw_album or not ocr_supports_title(ocr_text, raw_album):
                    ocr_prefers_source_title = True

    # Narrator alternate: folder narrator, or another person cand that isn't preferred.
    narrator_hint: str | None = None
    for name in narrator_cands + [n for n in person_cands if n != preferred_author]:
        if name and name != preferred_author:
            narrator_hint = name
            break

    tag_blob = _id3_tag_blob(tag1, tag2, book=book)
    if ocr_text:
        tag_blob = f"{tag_blob} {ocr_text.lower()}".strip()

    best_ol: "OpenLibraryTitle | None" = None
    best_score = 0.0
    best_query = ""

    # Never title-only when we have a preferred author — that is how Toyne/Storr wins.
    author_hints: list[str | None]
    if preferred_author:
        author_hints = [preferred_author]
        for name in person_cands:
            if name != preferred_author and name not in author_hints and name in validated:
                author_hints.append(name)
                if len(author_hints) >= 3:
                    break
    else:
        author_hints = [None]

    for title_cand in title_cands:
        for author_hint in author_hints:
            ol = open_library_lookup_title(
                title_cand,
                author=author_hint,
                narrator=narrator_hint if author_hint else None,
                method="similarity",
            )
            if not (ol and ol.has_match and ol.title and ol.author):
                continue

            score = ol.score(fallback=0.0)
            if not _ol_title_passes_floor(title_cand, ol.title):
                continue

            # Source-title anchor: album/anthology searches cannot replace a
            # dissimilar story title (About A Poem → Best American Spiritual…).
            if source_title:
                src_ratio, src_token = _title_sim(source_title, ol.title)
                album_differs = bool(
                    raw_album
                    and fuzz.token_set_ratio(source_title, raw_album) / 100 < _OL_TITLE_RATIO_MIN
                )
                searching_album = bool(raw_album and title_cand == raw_album)
                if album_differs and searching_album:
                    if src_ratio < _OL_TITLE_RATIO_MIN and src_token < _OL_TITLE_TOKEN_SET_MIN:
                        continue
                    # Cover OCR saw the story title but not the anthology album → veto.
                    if ocr_prefers_source_title:
                        continue
                # Soft anchor for any candidate: OL title should not be wildly
                # unrelated to the known story title when one exists.
                if src_ratio < _OL_SOURCE_ANCHOR_MIN and src_token < _OL_SOURCE_ANCHOR_MIN:
                    continue

            ol_author = ol.author or ""
            ascore = ol.author_score(fallback=None)

            if preferred_author:
                if not _ol_author_agrees(preferred_author, ol_author, ascore):
                    # Also try canonical OL name for the preferred local author.
                    if not (
                        preferred_canonical
                        and _ol_author_agrees(preferred_canonical, ol_author, ascore)
                    ):
                        continue
                # ID3/OCR conflict: preferred author is in tags/cover, OL author is not → reject.
                if _name_mentioned_in_blob(preferred_author, tag_blob) and not _name_mentioned_in_blob(
                    ol_author, tag_blob
                ):
                    # Allow when OL author is just a canonicalization of preferred
                    # (already agreed above) — only reject if names are clearly different.
                    if fuzz.token_set_ratio(preferred_author, ol_author) / 100 < _OL_AUTHOR_AGREE_MIN:
                        continue
                # Cover explicitly names preferred author but not OL author → veto.
                if ocr_text:
                    from src.lib.cover_ocr import ocr_mentions_name as _ocr_name

                    if _ocr_name(ocr_text, preferred_author) and not _ocr_name(ocr_text, ol_author):
                        if fuzz.token_set_ratio(preferred_author, ol_author) / 100 < _OL_AUTHOR_AGREE_MIN:
                            continue

            if score > best_score:
                best_score = score
                best_ol = ol
                best_query = title_cand
            if best_score >= 0.9:
                break
        if best_score >= 0.9:
            break

    if best_ol is None or not best_ol.title or not best_ol.author:
        return None
    if not _ol_title_passes_floor(best_query or best_ol.title, best_ol.title):
        return None

    # Never demote a validated preferred author to narrator on a conflicting hit —
    # conflicting hits are already rejected above. Apply title + agreed author.
    book.title = _normalize_ol_title(best_ol.title)
    book.album = book.title
    book.sortalbum = strip_leading_articles(book.title)

    if preferred_author and _ol_author_agrees(
        preferred_canonical or preferred_author, best_ol.author, best_ol.author_score(fallback=None)
    ):
        # Prefer OL canonical when it agrees; keeps "Ursula K. Le Guin" tidy.
        book.artist = best_ol.author
        book.albumartist = best_ol.author
        if best_ol.author_and_narrator_swapped and best_ol.narrator:
            # Genuine swap: preferred was the performer; OL author is correct.
            # Only set narrator from swap if it isn't the preferred author.
            if best_ol.narrator.lower() != (preferred_author or "").lower():
                book.narrator = best_ol.narrator
    elif preferred_author:
        book.artist = preferred_canonical or preferred_author
        book.albumartist = book.artist
    else:
        book.artist = best_ol.author
        book.albumartist = best_ol.author

    return best_ol


def _narrator_from_remaining_tags(book: "Audiobook") -> str:
    """Post-OL narrator detection: once the author is known, scan ID3 fields for
    the narrator.  Handles cases the heuristic scorer misses, e.g. the artist
    field carries 'read by Jenny Sterlin' with no albumartist present.
    """
    author_lower = (book.artist or "").lower()

    for raw in [book.id3_artist, book.id3_composer]:
        if not raw:
            continue
        stripped = _READ_BY_PATTERN.sub("", raw).strip()
        # Accept if the prefix was present OR the field doesn't match the author
        is_explicit_narrator = stripped != raw  # "read by …" or "narrated by …"
        is_not_author = author_lower and stripped.lower() != author_lower
        if is_explicit_narrator or is_not_author:
            return stripped

    return ""


def _usable_title_candidate(value: str | None) -> str:
    """Return a stripped title usable for ID3/Plex, or '' if empty/garbage."""
    from src.lib.audiobook import Audiobook

    t = (value or "").strip()
    if not t:
        return ""
    if Audiobook._is_garbage_output_title(t):
        return ""
    return t


def _fallback_title_from_book(book: "Audiobook") -> str:
    """Pick *something* when title/album would otherwise be blank.

    Order (OL already tried earlier in extract_metadata):
      1. Source ID3 title / album / sortalbum
      2. Filesystem-parsed title (``fs_title``)
      3. Inbox folder / file basename (e.g. ``Crescent City Fae [Boxed Set]``)
      4. Hardcoded last resort so Plex never shows ``[Unknown Album]``
    """
    for cand in (
        getattr(book, "id3_title", None),
        getattr(book, "id3_album", None),
        getattr(book, "id3_sortalbum", None),
        getattr(book, "fs_title", None),
    ):
        if u := _usable_title_candidate(cand):
            return u

    base = book.basename or ""
    try:
        if book.path.is_file():
            base = Path(base).stem
    except OSError:
        pass

    if u := _usable_title_candidate(base):
        return u

    # Even digit-only / tiny names beat an empty tag for Plex.
    return (base or "Unknown Audiobook").strip() or "Unknown Audiobook"


def ensure_title_and_album(book: "Audiobook") -> None:
    """Guarantee non-empty ``title`` / ``album`` / ``sortalbum`` for players like Plex.

    Never leaves Title/Album blank when any reasonable candidate exists (source
    tags, filesystem parse, or folder/file name).
    """
    from src.lib.audiobook import Audiobook

    title = (book.title or "").strip()
    if not title or Audiobook._is_garbage_output_title(title):
        book.title = _fallback_title_from_book(book)

    if not (book.album or "").strip():
        book.album = book.title
    if not (book.sortalbum or "").strip():
        book.sortalbum = strip_leading_articles(book.title)


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
    # Detect embedded cover art via ffprobe stream inspection — much faster than
    # extracting bytes with ffmpeg.  For m4b/m4a files the cover image is interleaved
    # with audio data inside the mdat chunk, so ffmpeg must scan the entire file to
    # extract it (O(filesize)), whereas ffprobe only reads the moov atom header.
    # Fall back to mutagen when streams are missing/unreadable but covr/APIC exists.
    _probe = ffprobe_file(book.sample_audio1) or {}
    book.has_id3_cover = any(
        s.get("codec_name") in ("mjpeg", "png") and s.get("disposition", {}).get("attached_pic")
        for s in _probe.get("streams", [])
    ) or bool(_extract_cover_art_mutagen(book.sample_audio1))

    # ── OL-first extraction ────────────────────────────────────────────────────
    # When OL is configured, ask it directly before heuristic scoring.
    # OL knows the canonical title/author, so a confident match avoids
    # misassigning fields (e.g. album="Laurie R. King", title="The God of
    # the Hive" → OL confirms title and author rather than guessing).
    ol_match = _ol_early_extraction(book, sample_audio1_tags, sample_audio2_tags)
    ol_resolved = ol_match is not None

    id3_score = MetadataScore(book, sample_audio2_tags)  # type: ignore

    t3 = time.time()

    if not ol_resolved:
        book.title = id3_score.determine_title(fallback=book.fs_title)
        book.album = book.title
        book.sortalbum = strip_leading_articles(book.title)
        book.artist = id3_score.determine_author(fallback=book.fs_author)
        book.albumartist = id3_score.determine_albumartist(fallback=book.fs_author)

    # Narrator: OL rarely stores narrator info, so always use the heuristic.
    # When OL resolved the author, try the targeted post-OL helper first —
    # it handles explicit "read by …" prefixes that the scorer's _ar_but_no_aar
    # branch misses (it only awards points when there's a slash in the artist).
    if ol_resolved:
        book.narrator = _narrator_from_remaining_tags(book) or id3_score.determine_narrator(
            fallback=book.fs_narrator
        )
    else:
        book.narrator = id3_score.determine_narrator(fallback=book.fs_narrator)

    # Guard: author == narrator is almost never correct.  Clear it to avoid
    # a person appearing in both roles.
    if book.narrator and book.narrator.lower() == (book.artist or "").lower():
        book.narrator = ""

    # Strip "Author - " prefix from the title when the title tag was set to the full
    # filesystem name (e.g. "Jeffery Deaver - The Cold Moon 2006" → "The Cold Moon 2006").
    # Many rippers embed the folder/filename verbatim as the title tag.  Only strip when
    # the author appears at the very start followed by a dash separator so we don't
    # accidentally truncate legitimate subtitles like "Cat's Cradle - A Novel".
    if not ol_resolved and book.title and book.artist:
        _remainder = strip_leading_author_dash(book.title, book.artist)
        if _remainder != book.title and _remainder:
            book.title = _remainder
            book.album = book.title
            book.sortalbum = strip_leading_articles(book.title)

    # Never leave Title/Album blank — Plex shows "[Unknown Album]" otherwise.
    # Falls back through ID3 → fs_title → folder/file basename.
    ensure_title_and_album(book)

    # Phase 3: shared colon + always-minimalist transforms on the resolved
    # title/album. Selection stays OCR / MetadataScore / OL-early for now;
    # Phase 4 may replace that path with plan_fix.
    _author_for_title = book.artist or book.author or ""
    _pre_title = (book.title or "").strip()
    if book.title:
        book.title = _finalize_convert_title(book.title, author=_author_for_title)
    # Convert normally keeps album == title; sync when album matched pre-finalize
    # title (or is empty), otherwise finalize album independently.
    _pre_album = (book.album or "").strip()
    if not _pre_album or _pre_album == _pre_title:
        book.album = book.title
    else:
        book.album = _finalize_convert_title(book.album, author=_author_for_title)
    if book.title:
        book.sortalbum = strip_leading_articles(book.title)

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

    # Use OL first-publish year when available; fall back to ID3 / filesystem.
    ol_year = ol_match.date if ol_match else ""
    book.date = ol_year or id3_score.determine_date(book.fs_year)
    if book.date:
        li(f"Date: {book.date}")
    # extract 4 digits from date
    book.year = get_year_from_date(book.date)

    # convert bitrate and sample rate to friendly to kbit/s, rounding to nearest tenths, e.g. 44.1 kHz
    li(f"Quality: {book.bitrate_friendly} @ {book.samplerate_friendly}")
    li(f"Duration: {book.duration('inbox', 'human')}")
    if not book.has_id3_cover:
        li(f"No cover art")

    # ── Open Library match summary ─────────────────────────────────────────────
    if console:
        from src.lib.config import cfg
        if cfg.OPEN_LIBRARY_USER_AGENT:
            print()
            if ol_match:
                ol_details = [f"Title: {ol_match.title}", f"Author: {ol_match.author}"]
                if ol_match.narrator:
                    ol_details.append(f"Narrator: {ol_match.narrator}")
                if ol_year:
                    ol_details.append(f"First published: {ol_year}")
                smart_print("Matched book on openlibrary.org:")
                for detail in ol_details:
                    li(detail)
            else:
                smart_print("Could not find a good match on openlibrary.org")

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
