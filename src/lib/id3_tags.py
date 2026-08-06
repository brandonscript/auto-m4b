import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast, Literal, Optional, TYPE_CHECKING, Union

import bidict
from mutagen.mp3 import HeaderNotFoundError
from pydantic import BaseModel, computed_field, Field, field_validator

from src.lib.ffprobe_utils import ffprobe_file
from src.lib.typing import AdditionalTags, Id3TagDict, TagSource

CacheValue = Union[Id3TagDict, Literal["__BAD__"]]

if TYPE_CHECKING:
    from src.lib.books_tree.books_tree import BooksTree

ID3_TAGS_CACHE_TTL = 300


class Id3Cache:
    """A simple TTL cache for ID3 tags."""

    _cache: dict[str, tuple[CacheValue, float]] = {}
    _ttl: int = ID3_TAGS_CACHE_TTL

    def get(self, key: str) -> CacheValue | None:
        """Return cached value if present and not expired, otherwise evict and return None."""
        if entry := self._cache.get(key):
            value, ts = entry
            if time.monotonic() - ts < self._ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: CacheValue) -> None:
        """Store value with the current timestamp."""
        self._cache[key] = (value, time.monotonic())

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()


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


def id3_tags_raw_to_source(in_dict: dict[str, str]) -> dict["TagSource | AdditionalTags", str]:
    """Takes raw id3 tag keys and converts them to the source tag names"""
    return {cast(TagSource, id3_tag_map.get(k, k)): v for k, v in in_dict.items()}


# Global cache instance
id3Cache = Id3Cache()


def _mutagen_tags_to_source(raw: dict[str, Any]) -> Id3TagDict:
    """Normalize mutagen Easy* tag dicts into the same key space as ffprobe."""
    # mutagen easy uses tracknumber/discnumber; ffprobe uses track/disc.
    aliases = {
        "tracknumber": "track",
        "discnumber": "discnumber",
        "albumartist": "albumartist",
        "album_artist": "albumartist",
        "encodedby": "encoder",
        "encoded_by": "encoder",
        "organization": "publisher",
    }
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        if isinstance(value, (bytes, bytearray)):
            continue
        text = str(value).strip()
        if not text:
            continue
        k = aliases.get(key.lower(), key.lower())
        normalized[k] = text
    return cast(Id3TagDict, id3_tags_raw_to_source(normalized))


def _extract_id3_tags_mutagen(path: Path) -> Id3TagDict:
    """Fast in-process tag read via mutagen. Returns {} on failure/empty."""
    try:
        from mutagen import File as MutagenFile
        from mutagen.easyid3 import EasyID3

        # Ensure comment frames are visible through the EasyID3 interface.
        try:
            EasyID3.RegisterTextKey("comment", "COMM")
        except Exception:
            pass

        audio = MutagenFile(str(path), easy=True)
        if audio is None:
            return {}
        tags = getattr(audio, "tags", None)
        raw: dict[str, Any]
        if tags:
            raw = dict(tags)
        elif len(audio):
            raw = dict(audio)
        else:
            raw = {}

        # EasyID3 sometimes omits COMM even after RegisterTextKey — pull it
        # directly from the underlying ID3/MP4 atoms when missing.
        # EasyMP4 also omits composer/encoder (©wrt / ©too) by default; those
        # are required for narrator (composer) and tool-identity checks.
        try:
            suffix = path.suffix.lower()
            lower_keys = {k.lower() for k in raw}
            if suffix == ".mp3":
                if "comment" not in lower_keys:
                    from mutagen.id3 import ID3

                    id3 = ID3(str(path))
                    for frame in id3.values():
                        if getattr(frame, "FrameID", "") == "COMM" or frame.__class__.__name__.startswith("COMM"):
                            text = getattr(frame, "text", None)
                            if text:
                                raw["comment"] = text[0]
                                break
            elif suffix in {".m4a", ".m4b", ".mp4", ".m4v"}:
                from mutagen.mp4 import MP4

                mp4 = MP4(str(path))
                atoms = mp4.tags or {}
                atom_map = {
                    "comment": "\xa9cmt",
                    "composer": "\xa9wrt",
                    "encoder": "\xa9too",
                    "description": "desc",
                }
                for dest, atom in atom_map.items():
                    if dest in lower_keys or atom not in atoms:
                        continue
                    val = atoms[atom]
                    if isinstance(val, (list, tuple)):
                        val = val[0] if val else ""
                    if val:
                        raw[dest] = val
        except Exception:
            pass

        return _mutagen_tags_to_source(raw) if raw else {}
    except Exception:
        return {}


def extract_id3_tags(file: "BooksTree | Path", *tags: "TagSource | AdditionalTags", throw=False) -> Id3TagDict:
    from src.lib.books_tree.books_tree import BooksTree

    """Extract ID3 tags from a file.

    Prefers mutagen (in-process, ~10x faster than spawning ffprobe) and falls
    back to ffprobe when mutagen cannot read the file.
    """
    path = file.path if isinstance(file, BooksTree) else Path(file) if file else None

    if not path or not path.is_file():
        if throw:
            raise FileNotFoundError(f"Error: Cannot extract id3 tags, '{file}' does not exist")
        return {}

    try:
        tag_dict: Id3TagDict = _extract_id3_tags_mutagen(path)
        if not tag_dict:
            if ffresult := cast(dict[str, Any], ffprobe_file(path, throw=throw)):
                tag_dict = id3_tags_raw_to_source(
                    {key.lower(): value for key, value in (ffresult["format"]["tags"] or {}).items()}
                )
        if not tags:
            return cast(Id3TagDict, tag_dict)
        return cast(Id3TagDict, {tag: tag_dict.get(tag, "") for tag in tags})
    except Exception as e:
        if throw:
            raise HeaderNotFoundError(
                f"Error: Could not extract id3 tags from {path} with tags {', '.join(tags)}"
            ) from e

    return {}


def _parse_id3_disc_or_track_num(v: Any) -> tuple[int, int]:
    if not v:
        return -1, -1
    # Try and parse as {num}/{total}
    if "/" in v:
        try:
            v, total = map(int, v.split("/"))
            return v, max(v, total)
        except ValueError:
            ...
    if v.isdigit():
        return int(v), -1
    return -1, -1


class Id3Tags(BaseModel):
    """A class to handle ID3 tag extraction and caching."""

    # Raw ID3 tag fields
    title: Optional[str] = Field(default=None)
    album: Optional[str] = Field(default=None)
    sortalbum: Optional[str] = Field(default=None)
    common_title: Optional[str] = Field(default=None)
    common_album: Optional[str] = Field(default=None)
    common_sortalbum: Optional[str] = Field(default=None)
    artist: Optional[str] = Field(default=None)
    albumartist: Optional[str] = Field(default=None)
    common_artist: Optional[str] = Field(default=None)
    common_albumartist: Optional[str] = Field(default=None)
    comment: Optional[str] = Field(default=None)
    composer: Optional[str] = Field(default=None)
    date: Optional[str] = Field(default=None)
    year: Optional[str] = Field(default=None)
    fs: Optional[str] = Field(default=None)
    unknown: Optional[str] = Field(default=None)
    cover: Optional[str] = Field(default=None)
    track: Optional[str] = Field(default=None, alias="track")
    discnumber: Optional[str] = Field(default=None, alias="discnumber")
    encoded_by: Optional[str] = Field(default=None)
    genre: Optional[str] = Field(default=None)
    publisher: Optional[str] = Field(default=None)
    updated: Optional[float] = Field(default=None, exclude=True)
    BAD: bool = Field(default=False, exclude=True)

    model_config = {
        "arbitrary_types_allowed": True,
        "validate_assignment": True,
        "coerce_numbers_to_str": True,
        "populate_by_name": True,
    }

    @field_validator(
        "title",
        "album",
        "sortalbum",
        "common_title",
        "common_album",
        "common_sortalbum",
        "artist",
        "albumartist",
        "common_artist",
        "common_albumartist",
        "comment",
        "composer",
        "date",
        "year",
        "fs",
        "unknown",
        "cover",
        "track",
        "discnumber",
        "encoded_by",
        "genre",
        "publisher",
        mode="before",
    )
    @classmethod
    def validate_str_fields(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v) or None

    @field_validator("updated", mode="before")
    @classmethod
    def validate_float_fields(cls, v: Any) -> Optional[float]:
        if v is None:
            return None
        return float(v) if v else None

    @computed_field
    @property
    def disc_num(self) -> Optional[int]:
        """Get the disc number from the discnumber tag."""
        if not self.discnumber:
            return None
        num, _ = _parse_id3_disc_or_track_num(self.discnumber)
        return num if num != -1 else None

    @computed_field
    @property
    def disc_total(self) -> Optional[int]:
        """Get the total number of discs from the discnumber tag."""
        if not self.discnumber:
            return None
        _, total = _parse_id3_disc_or_track_num(self.discnumber)
        return total if total != -1 else None

    @computed_field
    @property
    def track_num(self) -> Optional[int]:
        """Get the track number from the track tag."""
        if not self.track:
            return None
        num, _ = _parse_id3_disc_or_track_num(self.track)
        return num if num != -1 else None

    @computed_field
    @property
    def track_total(self) -> Optional[int]:
        """Get the total number of tracks from the track tag."""
        if not self.track:
            return None
        _, total = _parse_id3_disc_or_track_num(self.track)
        return total if total != -1 else None

    @classmethod
    def from_file(
        cls, file: Path, *tags: TagSource | AdditionalTags, throw: bool = False, no_cache: bool = False
    ) -> "Id3Tags | None":
        """Extract ID3 tags from a file, using cache if available and not expired."""

        if not file.is_file():
            return None

        current_time = datetime.now().timestamp()
        cache_key = str(file)

        if not no_cache:
            # Check global cache first
            cached_result = id3Cache.get(cache_key)
            if cached_result is not None:
                if cached_result == "__BAD__":
                    if throw:
                        raise HeaderNotFoundError(f"Error: Previously failed to extract id3 tags from {file}")
                    return cls(updated=current_time, BAD=True)
                return cls(**cached_result, updated=current_time)  # type: ignore

        # Try to extract tags
        try:
            extracted_tags = extract_id3_tags(file, *tags, throw=throw)
            if not extracted_tags:
                id3Cache.set(cache_key, "__BAD__")
                return cls(updated=current_time, BAD=True)
            id3Cache.set(cache_key, extracted_tags)
            return cls(**extracted_tags, updated=current_time)  # type: ignore
        except Exception as e:
            id3Cache.set(cache_key, "__BAD__")
            if throw:
                raise HeaderNotFoundError(
                    f"Error: Could not extract id3 tags from {file} with tags {', '.join(tags)}"
                ) from e
            return cls(updated=current_time, BAD=True)

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the global ID3 tags cache."""
        id3Cache.clear()

    @classmethod
    def rm_from_cache(cls, file: Path) -> None:
        """Remove a specific file from the global cache."""
        id3Cache._cache.pop(str(file), None)

    def to_dict(self) -> dict[str, Any]:
        """Convert the Id3Tags instance to a dictionary."""
        return self.model_dump(
            exclude_none=True,
            exclude={"disc_num", "disc_total", "track_num", "track_total", "updated", "BAD"},
        )

    def __getitem__(self, key: TagSource | AdditionalTags) -> str | float | None:
        """Allow dictionary-style access to tags."""
        # Map raw field names to their underscored versions
        return getattr(self, key, None)

    def get(self, key: TagSource | AdditionalTags, default: Any = None) -> str | float | None:
        """Get a tag value with a default if not found."""
        # Map raw field names to their underscored versions
        return getattr(self, key, default)
