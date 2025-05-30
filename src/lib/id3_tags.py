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
    """A simple cache for ID3 tags."""

    _cache: dict[str, CacheValue] = {}
    _ttl: int = ID3_TAGS_CACHE_TTL  # Cache TTL in seconds

    def get(self, key: str) -> CacheValue | None:
        """Get a value from the cache."""
        if key in self._cache:
            return self._cache[key]
        return None

    def set(self, key: str, value: CacheValue) -> None:
        """Set a value in the cache."""
        self._cache[key] = value

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


def extract_id3_tags(file: "BooksTree | Path", *tags: "TagSource | AdditionalTags", throw=False) -> Id3TagDict:
    from src.lib.books_tree.books_tree import BooksTree

    """Extract ID3 tags from a file."""
    path = file.path if isinstance(file, BooksTree) else Path(file) if file else None

    if not path or not path.is_file():
        if throw:
            raise FileNotFoundError(f"Error: Cannot extract id3 tags, '{file}' does not exist")
        return {}

    try:
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
    def from_file(cls, file: Path, *tags: TagSource | AdditionalTags, throw: bool = False) -> "Id3Tags | None":
        """Extract ID3 tags from a file, using cache if available and not expired."""

        if not file.is_file():
            return None

        current_time = datetime.now().timestamp()
        cache_key = str(file)

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
        # Get the raw model dump
        data = self.model_dump(
            exclude_none=True,
            exclude={"disc_num", "disc_total", "track_num", "track_total", "updated", "BAD"},
        )
        # Filter to only include valid tag names
        return {k: v for k, v in data.items() if k in TagSource.__args__ or k in AdditionalTags.__args__}

    def __getitem__(self, key: TagSource | AdditionalTags) -> str | float | None:
        """Allow dictionary-style access to tags."""
        # Map raw field names to their underscored versions
        return getattr(self, key, None)

    def get(self, key: TagSource | AdditionalTags, default: Any = None) -> str | float | None:
        """Get a tag value with a default if not found."""
        # Map raw field names to their underscored versions
        return getattr(self, key, default)
