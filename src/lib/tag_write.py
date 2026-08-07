"""Thin mutagen tag writer — no BooksTree / OCR / convert deps.

Used by ``apply_fix`` and by ``id3_utils.write_id3_tags_mutagen`` (which adds
BooksTree/path unwrap + Id3Tags cache invalidation).
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import Any, NamedTuple, cast

from src.lib.cleaners import fix_smart_quotes, strip_leading_articles
from src.lib.parsers import get_year_from_date
from src.lib.term import print_debug

MissingMutagenError = ValueError

TagDict = MutableMapping[str, Any]


class TagSet(NamedTuple):
    title: str
    artist: str
    album: str
    sortalbum: str
    albumartist: str
    composer: str
    date: str
    track_num: tuple[int, int]
    comment: str


def tags_from_dict(tags: Mapping[str, Any]) -> TagSet:
    title = str(tags.get("title", ""))
    artist = str(tags.get("artist", ""))
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


def sanitize_tags_for_write(
    tags: Mapping[str, Any],
    *,
    fallback_stem: str,
) -> dict[str, Any]:
    """Final gate before writing tags: Title/Album must never be blank."""
    out: dict[str, Any] = dict(tags)
    for key in ("title", "album", "sortalbum", "artist", "albumartist", "composer", "comment"):
        if key in out and out[key] is not None:
            out[key] = fix_smart_quotes(str(out[key]))
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
    return out


def _embed_cover_m4b(f: Any, cover: Path, MP4Cover: Any) -> None:
    from src.lib.cover_images import ensure_embeddable_cover

    embed_cover = ensure_embeddable_cover(cover)
    with open(embed_cover, "rb") as img_in:
        image_data = img_in.read()

    suffix = embed_cover.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime_type = MP4Cover.FORMAT_JPEG
    elif suffix == ".png":
        mime_type = MP4Cover.FORMAT_PNG
    else:
        raise IOError(f"Error: Could not set cover art, '{cover}' is not a supported image file")
    f["covr"] = [MP4Cover(image_data, mime_type)]


def _embed_cover_mp3(file: Path, cover: Path) -> None:
    from mutagen.id3 import APIC, ID3

    from src.lib.cover_images import ensure_embeddable_cover

    embed_cover = ensure_embeddable_cover(cover)
    with open(embed_cover, "rb") as img_in:
        image_data = img_in.read()

    suffix = embed_cover.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    elif suffix == ".png":
        mime_type = "image/png"
    else:
        raise IOError(f"Error: Could not set cover art, '{cover}' is not a supported image file")

    f = ID3(file)
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


def write_m4b_tags(
    file: Path,
    tags: Mapping[str, Any],
    *,
    cover: Path | None = None,
    encoder_tag: str = "brandonscript/fixm4b",
) -> None:
    try:
        from mutagen.mp4 import MP4, MP4Cover
    except ImportError as exc:
        raise MissingMutagenError(
            "Error: mutagen is not available, please install it with\n\n $ pip install mutagen\n\n...then try again"
        ) from exc

    if not file.exists():
        raise FileNotFoundError(f"Error: Cannot write id3 tags, '{file}' does not exist")

    title, artist, album, sortalbum, albumartist, composer, date, _tn, comment = tags_from_dict(tags)

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
        f["\xa9too"] = encoder_tag

        if cover and cover.is_file():
            _embed_cover_m4b(f, cover, MP4Cover)

        f.save()


def write_mp3_tags(
    file: Path,
    tags: Mapping[str, Any],
    *,
    cover: Path | None = None,
) -> None:
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.mp3 import HeaderNotFoundError

        EasyID3.RegisterTextKey("comment", "COMM")
    except ImportError as exc:
        raise MissingMutagenError(
            "Error: mutagen is not available, please install it with\n\n $ pip install mutagen\n\n...then try again"
        ) from exc

    if not file.exists():
        raise FileNotFoundError(f"Error: Cannot write id3 tags, '{file}' does not exist")

    title, artist, album, sortalbum, albumartist, composer, date, _tn, comment = tags_from_dict(tags)

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

        if cover and cover.is_file():
            _embed_cover_mp3(file, cover)
    else:
        raise HeaderNotFoundError(f"Error: Could not load '{file}' for tagging, it may be corrupt or not an audio file")


def write_id3_tags(
    path: Path,
    tags: Mapping[str, Any],
    *,
    cover: Path | None = None,
    on_write: Callable[[Path], None] | None = None,
    encoder_tag: str = "brandonscript/fixm4b",
) -> None:
    """Write tags to an audio file. Plain ``Path`` only — no BooksTree."""
    sanitized = sanitize_tags_for_write(tags, fallback_stem=path.stem)
    if path.suffix.lower() in [".m4b", ".m4a"]:
        try:
            write_m4b_tags(path, sanitized, cover=cover, encoder_tag=encoder_tag)
        except Exception as e:
            if "not a MP4" not in str(e) and e.__class__.__name__ != "MP4StreamInfoError":
                raise
            print_debug(f"write_m4b_tags failed ({e}); falling back to mp3 tag writer for {path.name}")
            write_mp3_tags(path, sanitized, cover=cover)
    else:
        write_mp3_tags(path, sanitized, cover=cover)
    if on_write is not None:
        on_write(path)
