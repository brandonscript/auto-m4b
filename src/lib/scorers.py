import functools
import re
import sys
import time
from collections.abc import Callable, Hashable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast, Literal, TYPE_CHECKING, TypeVar

import columnar
from rapidfuzz import fuzz
from rapidfuzz.distance import LCSseq, Levenshtein

from src.lib.id3_tags import Id3Tags
from src.lib.cleaners import clean_string, strip_author_narrator, strip_part_number
from src.lib.misc import any_in, get_numbers_in_string
from src.lib.parsers import (
    contains_partno_or_ch,
    find_greatest_common_string,
    get_title_partno_score,
    get_year_from_date,
    has_graphic_audio,
    parse_author,
    parse_narrator,
    parse_year,
    to_words,
)
from src.lib.patterns import basic_part_or_ch_pattern, common_str_pattern, startswith_num_pattern
from src.lib.singleton import singleton
from src.lib.term import print_debug

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook
    from src.lib.books_tree.books_tree import BooksTree
    from src.lib.typing import AdditionalTags, ScoredProp, TagSource

if TYPE_CHECKING:
    from src.lib.books_tree.books_tree import BooksTree


from src.lib.books_tree.books_tree import BooksTree
from src.lib.compare import get_size_similarity

T = TypeVar("T")


@singleton
class AlreadyChecked:
    def __init__(self):
        self._checked: set[Path] = set()
        self._start_time: datetime | None = None

    def start(self):
        self._checked.clear()
        self._start_time = datetime.now()

    def add(self, path: Path):
        self._checked.add(path)

    def has(self, path: Path) -> bool:
        return path in self._checked

    def clear(self):
        self._checked.clear()
        self._start_time = None

    @property
    def is_expired(self) -> bool:
        if not self._start_time:
            return True
        return (datetime.now() - self._start_time) > timedelta(seconds=300)  # 5 minute expiry


already_checked = AlreadyChecked()


class ScorerCache:
    """Custom cache implementation for scorer results with a bounded TTL.

    Entries are grouped by root id so a rescan can drop one tree's scores
    without wiping unrelated roots (live inbox builds multiple trees).
    """

    def __init__(self, ttl_seconds: int = 300):  # 5 minutes TTL
        self._cache: dict[Hashable, tuple[Any, datetime]] = {}
        self._by_root: dict[int, set[Hashable]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, key: Hashable | None) -> Any | None:
        if not key:
            return None
        if key not in self._cache:
            return None
        value, timestamp = self._cache[key]
        if datetime.now() - timestamp > self._ttl:
            del self._cache[key]
            return None
        return value

    def set(self, key: Hashable | None, value: Any, *, root_id: int | None = None) -> None:
        if not key:
            return
        self._cache[key] = (value, datetime.now())
        if root_id is not None:
            self._by_root.setdefault(root_id, set()).add(key)

    def clear(self, root_id: int | None = None) -> None:
        if root_id is None:
            self._cache.clear()
            self._by_root.clear()
            return
        for key in self._by_root.pop(root_id, set()):
            self._cache.pop(key, None)


# Global cache instance
_scorer_cache = ScorerCache()


def cached_scorer(func: Callable[..., T]) -> Callable[..., T]:
    """Cache scorer results within one tree root and structure/scan epoch."""

    @functools.wraps(func)
    def wrapper(tree: "BooksTree", *args: Any, **kwargs: Any) -> T:
        from src.lib.config import cfg

        root = tree.root or tree
        root_id = id(root)
        trace = cfg.SCORER_TRACE
        # Hashable tuple key — avoids f-string formatting on every call.
        # tree.path is a Path (hashable); epoch/namespace invalidate on rescan.
        key_parts: list[Any] = [
            func.__name__,
            root_id,
            root._scorer_cache_namespace,
            root._scorer_cache_epoch,
            tree.path,
        ]
        if args:
            key_parts.append(args)
        if kwargs:
            # Sort kwargs items to ensure consistent cache keys
            sorted_kwargs = sorted(kwargs.items())
            # For already_checked, only include the length and first few items to avoid huge keys
            if "already_checked" in kwargs:
                already_checked_arg = kwargs["already_checked"]
                if already_checked_arg:
                    sorted_kwargs = [(k, v) for k, v in sorted_kwargs if k != "already_checked"]
                    sorted_kwargs.append(("already_checked_len", len(already_checked_arg)))
                    if already_checked_arg:
                        sorted_kwargs.append(("already_checked_first", str(already_checked_arg[0].path)))
            key_parts.append(tuple(sorted_kwargs))

        cache_key = tuple(key_parts)

        cached_result = _scorer_cache.get(cache_key)
        if cached_result is not None:
            if trace:
                tree.tick(
                    "scorer",
                    {"cache": "hit", "scorer": func.__name__, "path": str(tree.rel_path)},
                )
            return cached_result

        start = time.perf_counter() if trace else 0.0
        result = func(tree, *args, **kwargs)
        _scorer_cache.set(cache_key, result, root_id=root_id)
        if trace:
            tree.tick(
                "scorer",
                {
                    "cache": "miss",
                    "scorer": func.__name__,
                    "path": str(tree.rel_path),
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
                },
            )
        return result

    return wrapper


class MetadataScore:
    def __init__(
        self,
        book: "Audiobook",
        sample_audio2_tags: dict["TagSource | AdditionalTags", str],
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
        key: "ScoredProp",
        *,
        from_tag: "TagSource | None" = None,
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
        elif from_tag and common_str_pattern.match(from_tag):
            val = getattr(self._p, common_str_pattern.sub("", from_tag) + "_c")
        elif from_tag == "fs":
            if key == "date":
                val = self._p.fs_year
        else:
            try:
                val = getattr(self._p, f"{from_tag}1")
            except AttributeError:
                val = getattr(self._p, from_tag) if from_tag else ""

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

    def determine_title(self, *, fallback: str = "Unknown", force: bool = False):

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

        title1_contains_partno = contains_partno_or_ch(self._p.title1)
        title2_contains_partno = contains_partno_or_ch(self._p.title2)
        album1_contains_partno = contains_partno_or_ch(self._p.album1)

        if self._p._t_is_partno:
            if self._p._t_is_only_part_no:
                title_is_title -= self._p._t_partno_score * 100
            else:
                if title1_contains_partno or title2_contains_partno:
                    common_title_is_title = max(
                        title_is_title,
                        common_title_is_title,
                    )
                    title_is_title -= self._p._t_partno_score * 5

        elif title1_contains_partno or title2_contains_partno:
            # Individual titles contain part numbers even though the *common*
            # title doesn't (e.g. title1="War and Peace, Part 1", title2="War
            # and Peace, Part 5" → common="War and Peace").  Apply the same
            # penalty and, when the album doesn't also have a part number,
            # boost the album score as the more reliable book-level title.
            common_title_is_title = max(title_is_title, common_title_is_title)
            title_is_title -= self._p._t_partno_score * 5
            if not album1_contains_partno:
                album_is_title += self._p._t_partno_score * 3

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

    def determine_author(self, *, fallback: str = "Unknown", force: bool = False):

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
        albumartist_is_author = 0
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
                    albumartist_is_author += 10 * int(-1 if self._p._aar1_eq_comment_author else 1)
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
            # Give composer a stronger narrator signal when albumartist is absent.
            # Many audiobook MP3 rips use the music convention (artist=narrator, composer=author),
            # and when there's no albumartist to disambiguate, composer is the most reliable
            # signal that someone other than the artist is involved (i.e., one is author, one
            # is narrator). OL swap-detection handles the music-convention case explicitly;
            # the boosted score here ensures composer wins as narrator when OL confirms it.
            no_albumartist = not self._p.albumartist1
            composer_is_narrator = 15 * int(len(to_words(self._p.composer))) * (2 if no_albumartist else 1)

        self.narrator.artist_is_narrator = artist_is_narrator
        self.narrator.albumartist_is_narrator = albumartist_is_narrator
        self.narrator.common_artist_is_narrator = common_artist_is_narrator
        self.narrator.common_albumartist_is_narrator = common_albumartist_is_narrator
        self.narrator.comment_contains_narrator = comment_contains_narrator
        self.narrator.composer_is_narrator = composer_is_narrator

        self._narrator = parse_narrator(self.narrator._value or fallback, "generic")
        return self._narrator

    def determine_albumartist(self, *, fallback: str = "Unknown", force: bool = False):
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


class BaseScoreCard:

    def __init__(self, scorer: "MetadataScore") -> None:

        self._scorer = scorer

    props: list["TagSource"] = []

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
    def _is_likely(self) -> tuple["TagSource | AdditionalTags", int, str | None]:
        # put all the scores in a list and return the highest score and its var name
        rep = re.compile(rf"_(is|contains)_{self._prop}$")
        scores = [
            (cast("TagSource | AdditionalTags", re.sub(rep, "", p)), getattr(self, p), p)
            for p in dir(self)
            if not p.startswith("_") and p.endswith(self._prop) and isinstance(getattr(self, p), int)
        ]
        if not scores or all(score[1] <= 0 for score in scores):
            return "unknown", 0, None
        tag, best, prop = max(scores, key=lambda x: x[1])
        # return the highest score and the name of its variable - use inflection or inspect
        return cast("TagSource | AdditionalTags", tag), best, prop

    def __repr__(self):
        return self.__str__()


class TitleScoreCard(BaseScoreCard):
    title_is_title: int = 0
    album_is_title: int = 0
    sortalbum_is_title: int = 0
    common_title_is_title: int = 0
    common_album_is_title: int = 0
    common_sortalbum_is_title: int = 0

    props: list["TagSource"] = [
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

    props: list["TagSource"] = [
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

    props: list["TagSource"] = [
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

    props: list["TagSource"] = ["date", "year", "fs"]

    def __str__(self):
        return (
            f"DateScoreCard\n"
            f" - date_is_date: {self.date_is_date}\n"
            f" - fs_contains_date: {self.fs_contains_date}\n"
        )


def similarity_score(s1: str, s2: str) -> int:
    """Returns the average similarity score between two strings using three different algorithms from -10 to 10 (with 0 being 50% similar, indeterminate)"""

    tsr = fuzz.token_sort_ratio(s1, s2)
    lcs = LCSseq.normalized_similarity(s1, s2) * 100
    lev = Levenshtein.normalized_similarity(s1, s2) * 100

    # round to nearest 0.001
    percent = (tsr + lcs + lev) / 3

    # if < 50, return -10 to 0, if >50 return 0 to 10
    return int((percent / 100 if percent > 50 else percent / 50 - 1) * 10)


class MetadataProps:

    def __init__(
        self,
        book: "Audiobook",
        sample_audio2_tags: dict["TagSource | AdditionalTags", str],
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
        self.title2 = sample_audio2_tags.get("title") or ""
        self.title_c = find_greatest_common_string([self.title1, self.title2])

        self.album1 = book.id3_album
        self.album2 = sample_audio2_tags.get("album") or ""
        self.album_c = find_greatest_common_string([self.album1, self.album2])

        self.sortalbum1 = book.id3_sortalbum
        self.sortalbum2 = sample_audio2_tags.get("sortalbum") or ""
        self.sortalbum_c = find_greatest_common_string([self.sortalbum1, self.sortalbum2])

        self.artist1 = book.id3_artist
        self.artist2 = sample_audio2_tags.get("artist") or ""
        self.artist_c = find_greatest_common_string([self.artist1, self.artist2])

        self.albumartist1 = book.id3_albumartist
        self.albumartist2 = sample_audio2_tags.get("albumartist") or ""
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
        # Always strip part/disc markers from the common title — even when _t_is_partno
        # is False.  The GCS of two titles like "Dreadnought Part 1" / "Dreadnought Part 2"
        # produces "Dreadnought Part " (the varying digit is gone but the keyword remains).
        # Without this, the orphaned "Part" rides through to the output m4b tag.
        from src.lib.cleaners import strip_disc_number

        self.title_c = strip_disc_number(strip_part_number(self.title_c))

        # When title_c is a digit-truncated GCS prefix of title1, use title1 instead.
        # This happens when two files share a base title but differ only in trailing
        # track-number notation (e.g. "...1993 001-033" vs "...1993 034-066"), causing
        # find_greatest_common_string to stop at the first diverging digit (e.g. "...0").
        # Preferring title1 lets the subsequent author-prefix stripping produce a complete
        # book title rather than a nonsensical truncated fragment.
        if (
            self.title_c
            and self.title1
            and self.title_c != self.title1
            and self.title1.startswith(self.title_c)
            and self.title_c[-1].isdigit()
        ):
            self.title_c = self.title1

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

    def table(self):
        from src.lib.id3_utils import custom_sort

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

        return columnar.columnar(
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


@cached_scorer
def score_container_mixed(tree: "BooksTree") -> tuple[Literal["container", "mixed"] | None, float, float]:
    """Tries to determine if a directory is a container or mixed

    Returns:
        tuple[Literal["container", "mixed"], float, float]:
            - The type of structure (container or mixed)
            - The score for the container
            - The score for the mixed
    """

    try:
        from src.lib.misc import is_gt_50mb, is_gt_75mb, truthiness

        if tree.is_file() or tree.is_root or not tree.children_recursive or tree.structure:
            return (None, 0.0, 0.0)

        cri = tree.i.children_recursive

        files_sim = tree.i.files.similarity("pathnames", distinct=True) or 0.0
        standalones = -0.5 + truthiness([score_single_standalone_file(f)[1] > 0.4 for f in tree.files])
        files_gt_50mb = truthiness([is_gt_50mb(f.size) for f in tree.files])
        files_gt_75mb = truthiness([is_gt_75mb(f.size) for f in tree.files])
        dirs_gt_75mb = truthiness([is_gt_75mb(c.size) for c in tree.dirs.values()])

        # A mixed directory has direct files that are merely parts of the same
        # book, not standalone books. Without a positive standalone signal,
        # treating its nested directory as a container creates false positives
        # for small/test-sized files.
        if tree.files and tree.dirs and standalones <= 0:
            return (None, 0.0, 0.0)
        if not tree.files and tree.dirs and all(re.fullmatch(r"nested[_ ]?\d+", d.name, re.IGNORECASE) for d in tree.dirs.values()):
            return (None, 0.0, 0.0)

        known_structures = tree.list_structures_r
        missing_structures = len(tree.children_without_structure_r) / len(tree.children_recursive)
        incomplete_path_nums = (0.0 if not cri.all_path_nums else (-1.0 + (cri.all_path_nums_completion or 0.0))) / 4

        mixed_score = 0.0
        container_score = 0.0

        small_child_score = (1 - files_gt_50mb) + (1 - dirs_gt_75mb)
        large_child_score = (files_gt_75mb + files_gt_50mb) / 2 + dirs_gt_75mb
        size_diff = large_child_score - small_child_score

        container_score += size_diff + standalones - missing_structures + incomplete_path_nums
        mixed_score -= size_diff - standalones + missing_structures - incomplete_path_nums

        if any_in(known_structures, ["multi_parent", "flat", "standalone_file", "series_parent"]):
            container_score += 0.5
            mixed_score -= 0.5

        if missing_structures > 0:
            container_score -= missing_structures
            mixed_score += missing_structures

        # If more smaller files than larger files, and files are dissimilar, boost mixed
        if size_diff < 0 and files_sim < 0.8:
            container_score -= 0.5
            mixed_score += 0.5

        # Strong structural signal: standalone-scored files sharing a dir with book-type
        # children dirs is a clear indicator of a container regardless of file size.
        # (Size-based signals are calibrated for real 100 MB+ audio — they fail on test
        # fixtures. This structural signal is size-independent.)
        if bool(tree.files) and bool(tree.dirs) and standalones > 0:
            container_score += 2.0
            mixed_score -= 2.0

        container_score = round(container_score, 3)
        mixed_score = round(mixed_score, 3)

        if container_score > mixed_score:
            return ("container", container_score, mixed_score)
        elif mixed_score > container_score:
            return ("mixed", container_score, mixed_score)
        else:
            return (None, container_score, mixed_score)

    except Exception as e:
        if "pytest" in sys.modules:
            raise e
        print_debug(f"Error scoring container/mixed: {e}")
        return (None, 0.0, 0.0)


@cached_scorer
def score_flat(tree: "BooksTree") -> float:
    try:
        if tree.is_match:
            ...

        if not tree.parent or tree.is_root:
            return 0.0

        if not tree.files:
            # Can't be flat if it has no files
            return 0.0

        # A directory whose name matches the disc pattern (e.g. "cd 1", "CD14", "Disc 3")
        # and that has multiple disc-named siblings cannot be a flat book — it's a disc
        # within a multi-disc set.  This prevents consistent intra-disc ID3 tags from
        # making the flat scorer win over the multi-disc scorer.
        from src.lib.parsers import get_disc_num

        if (
            get_disc_num(tree.name) >= 0
            and len(tree.i.this_and_siblings._trees) > 1
            and tree.i.this_and_siblings.have_disc_nums
        ):
            return 0.0

        _is_multi, multi_disc_score, multi_part_score = score_multi_part_or_disc(tree)
        files_have_tags = bool(tree.i.files_recursive.id3_tags)

        if tree.is_file():

            if tree.parent.is_root:
                return 0.0

            if multi_disc_score > 0.5 or multi_part_score > 0.5:
                return 1 - (max(multi_disc_score, multi_part_score))

            if tree.parent and tree.parent.dirs:
                files_to_dirs_ratio = len(tree.parent.files) / len(tree.parent.children)
                return 1 - (files_to_dirs_ratio / 2)

            completion = float(
                tree.i.this_and_siblings.track_nums_completion
                or tree.i.this_and_siblings.start_nums_completion
                or tree.i.this_and_siblings.part_nums_completion
                or 0
            )
            contiguous = float(
                tree.i.this_and_siblings.track_nums_are_contiguous
                or tree.i.this_and_siblings.start_nums_are_contiguous
                or tree.i.this_and_siblings.part_nums_are_contiguous
                or 0
            )
            return round(completion + contiguous, 3)

        if tree.dirs and (multi_disc_score > 0.5 or multi_part_score > 0.5):
            return 0.0

        path_sim = tree.i.children_recursive.similarity("pathnames", include_curr=False, fallback=0.0)
        album_sim = tree.i.children_recursive.similarity("id3_albums", fallback=path_sim)
        album_p_sim = tree.i.this_and_siblings_recursive.similarity("id3_albums", fallback=path_sim)
        author_sim = tree.i.children_recursive.similarity("id3_artists", fallback=path_sim)

        if files_have_tags:

            if album_p_sim == 1.0:
                # If identical to parent's album, this could be flatish (or multi-disc/part).
                return round(1.0 - max(multi_disc_score, multi_part_score), 3)

            # If children have contiguous part numbers ("Part 1", "Part 2"), bypass
            # the album_sim check — but ONLY when the discrepancy is a MISSING tag
            # (not genuinely different albums). Guard conditions:
            #   (a) at least one tagged file is missing its album specifically
            #       (id3_albums filters None/empty, so len < len(id3_tags) means missing)
            #   (b) the albums that ARE present all agree with each other
            #   (c) filenames are highly similar (same title, different part number)
            # This avoids false-positives where two different books happen to be named
            # "Part 1" and "Part 2" but have explicitly different, fully-set album tags.
            _albums = tree.i.files_recursive.id3_albums   # non-empty album strings only
            _tagged = tree.i.files_recursive.id3_tags     # files with any tag at all
            _has_missing = len(_albums) < len(_tagged)    # some tagged files lack an album
            _present_agree = len(set(_albums)) <= 1       # present albums are consistent

            if (
                tree.i.children.have_part_nums
                and tree.i.children.part_nums_are_contiguous
                and _has_missing
                and _present_agree
                and path_sim > 0.8
            ):
                return round(1.0 - max(multi_disc_score, multi_part_score), 3)

            if author_sim < 0.65 or album_sim < 0.95:
                # If very dissimilar authors, or not identical albums, it's not a flat.
                return round(min(album_sim, author_sim), 3)
            else:
                # Take the average of the album and author similarity
                return round((album_sim + author_sim) / 2, 3)

        num_contiguity = 0.0
        best_sim = max(path_sim, (album_sim + author_sim) / 2)

        # If child files do not have tags, we can check file number contiguity
        if tree.i.files_recursive.have_any_nums:
            num_contiguity += tree.i.files_recursive.all_path_nums_completion or 0
            num_contiguity += float(tree.i.files_recursive.all_path_nums_are_contiguous or 0)
            num_contiguity /= 2

        if tree.is_match:
            ...

        if tree.dirs and files_have_tags and (best_sim < 0.9):
            # Exceptions can be made for a flat-ish dir, but its tags needs to be
            # aggressively similar. If not, it's not a flat.
            return 0.0

        if tree.dirs and not files_have_tags and num_contiguity == 1:
            # Exceptions can be made for a flat-ish dir, but it must have perfect numbers
            return 0.75

        if (tree.parent.is_root or tree.parent.has_structure("container")) and best_sim > 0.9:
            return 1.0

        if tree.is_match:
            ...

        completion = float(
            tree.i.children.part_nums_completion
            or tree.i.children.disc_nums_completion
            or tree.i.children.series_nums_completion
            or tree.i.children.all_path_nums_completion
            or 0
        )
        contiguous = float(
            tree.i.children.track_nums_are_contiguous
            or tree.i.children.start_nums_are_contiguous
            or tree.i.children.part_nums_are_contiguous
            or tree.i.children.all_path_nums_are_contiguous
            or 0
        )

        return round((completion + contiguous + path_sim) / 3, 3)
    except Exception as e:
        if "pytest" in sys.modules:
            raise e
        print_debug(f"Error scoring flat: {e}")
        return 0.0


@cached_scorer
def _score_single_standalone_file_base(
    tree: "BooksTree",
) -> tuple[Literal["standalone_file", "single"] | None, float, float]:
    """
    Only determines score for files, not dirs.

    Returns:
        tuple[Literal["standalone_file", "single"], float, float]:
            - The type of structure (standalone_file or single) or None
            - The score for the standalone file
            - The score for the single file
    """
    try:
        from src.lib.compare import get_similarity
        from src.lib.misc import is_gt_75mb, truthiness

        if not tree.is_file():
            return (None, 0.0, 0.0)

        # tree.parent.tick(f"--- score_single_standalone_file: {tree.rel_path}")

        if (p := tree.parent) and (p.is_root or p.has_structure("container") or p.has_structure("series_parent")):
            return ("standalone_file", 1.0, 0.0)
        elif not p:
            return (None, 0.0, 0.0)  # No parent, must be root, theoretically impossible

        # Cache parent's file list early so every sibling-level check reuses
        # the same TreeNodeList (and its cached @lazy properties) rather than
        # creating per-file copies via tree.i.siblings_recursive.
        _sibs = p.i.files

        p_files_have_tags = False
        p_album_sim = 0.0
        p_author_sim = 0.0
        t = t if (t := tree.id3_tags) and not t.BAD else None
        # Use siblings_recursive (not _sibs which includes tree itself) so that a
        # solo file with no siblings correctly gives p_files_have_tags=False, allowing
        # the _only_child_in_parent path to return ("single", ...) as expected.
        # Guard with _sibs.id3_tags first: when id3 scanning is disabled, _sibs.id3_tags
        # is always empty and we can skip the expensive tree.i creation entirely.
        if tree.depth > 1 and _sibs.id3_tags and (p_files_have_tags := bool(tree.i.siblings_recursive.id3_tags)):
            # tree.parent.tick(f" --- p_files_have_tags: {p_files_have_tags}")
            t: Id3Tags | None = tree.id3_tags
            p_album_sim = 0.0 if not t else get_similarity([t.album, *tree.i.siblings_recursive.id3_albums]) or 0.0
            p_artist_sim = 0.0 if not t else get_similarity([t.artist, *tree.i.siblings_recursive.id3_artists]) or 0.0
            p_albumartist_sim = (
                0.0
                if not t
                else get_similarity([t.albumartist, *tree.i.siblings_recursive.id3_albumartists]) or 0.0
            )
            p_author_sim = round(max(p_artist_sim, p_albumartist_sim), 3)

        if _only_child_in_parent := p and len(p.files) < 2 and not p.dirs:
            # tree.parent.tick(f" --- only child in parent: {_only_child_in_parent}")
            if tree.depth < 3:
                # if depth is < 3, a.k.a its parent's parent is the root, it must be single
                # because root can't be a series/container.
                return ("single", 0.0, 1.0)

            if not p_files_have_tags:
                # No tags, can't be standalone if it has a non-root parent, and
                # can't reliably tell if it's related to siblings or not.
                # Future: might want to return "unknown" for these.
                return ("single", 0.0, 1.0)

            # If it's the same as the pp's album, it's accidentally been nested in a subfolder.
            # Might be a multi-disc/part, or a flatish, but not a single.
            if _album_is_p_album := p_album_sim > 0.95 and p_author_sim > 0.6:
                return (None, 0.0, 1 - p_album_sim)

            return ("single", 0.0, max(1 - p_album_sim, 1 - p_author_sim))

        # At this point, we've ruled out that it's a single -
        # it can only be a standalone file or part of a multi_parent.

        siblings_rels = []

        if not (only_file_in_parent := len(p.files) < 2):
            # tree.parent.tick(f" --- not only file in parent: {only_file_in_parent}")

            if _sibs.have_albums:
                siblings_rels.append(
                    -1.0
                    + (_sibs.similarity("id3_albums", distinct=True, fallback=0.0) * 2)
                )

            if _sibs.have_authors:
                siblings_rels.append(
                    -1.0
                    + (_sibs.similarity("id3_authors", distinct=True, fallback=0.0) * 2)
                )

            # For depth-3+ files, tree.i.this_and_siblings_recursive goes up to the
            # grandparent (e.g. the series folder) and includes all files in sibling books.
            # This gives a low similarity signal across a diverse series, which correctly
            # boosts standalone_score. Using _sibs (parent's direct files) instead would
            # give a high similarity among tracks within the same flat book and incorrectly
            # suppress the standalone signal.
            siblings_rels.append(
                tree.i.this_and_siblings_recursive.similarity("pathnames", distinct=True, fallback=0.0)
            )

            known_numbers_contiguity = float(
                _sibs.track_nums_are_contiguous
                or _sibs.start_nums_are_contiguous
                or _sibs.part_nums_are_contiguous
                or 0
            )
            all_numbers_contiguity = (
                float(_sibs.all_path_nums_are_contiguous or 0)
                + (_sibs.all_path_nums_completion or 0)
            ) / 2

            siblings_rels.append(max(known_numbers_contiguity, all_numbers_contiguity))

        # tree.parent.tick(f" --- siblings_rels: {siblings_rels}")
        siblings_sim = sum(siblings_rels) / len(siblings_rels) if siblings_rels else 0.0
        sibling_files_sim = p.i.files.similarity("pathnames", fallback=0.0) if p else 0.0
        siblings_with_part_or_chapter = truthiness([bool(basic_part_or_ch_pattern.search(t.name)) for t in p.files])

        parent_has_files_and_dirs = bool(p and (p.files or p.dirs))
        parent_has_multiple_dirs = bool(p and len(p.dirs) > 1)
        parent_has_mixed_content = parent_has_files_and_dirs or parent_has_multiple_dirs

        # tree.parent.tick(f" --- checked parent for files/dirs")
        suffixes = list(set([f.path.suffix for f in p.files])) if p else []
        # tree.parent.tick(f" --- suffixes: {suffixes}")
        has_mixed_file_types = len(suffixes) > 1 if p else False
        # tree.parent.tick(f" --- has_mixed_file_types: {has_mixed_file_types}")
        sizes_gt_75mb = truthiness([is_gt_75mb(f.size) for f in p.files]) if p else False
        # tree.parent.tick(f" --- sizes_gt_75mb: {sizes_gt_75mb}")
        sizes_sim = (
            get_size_similarity(
                [f.size for f in p.files],
                byte_multiplier=100 if "pytest" in sys.modules else 1,
                ignore_smaller_than=10 * 1000 if "pytest" in sys.modules else 10 * 1000 * 1000,
            )
            if p and not only_file_in_parent
            else 0.0
        )
        # tree.parent.tick(f" --- sizes_sim: {sizes_sim}")
        has_m4b_files = ".m4b" in suffixes if p else False
        # tree.parent.tick(f" --- has_m4b_files: {has_m4b_files}")
        parent_name_sim = get_similarity([tree.name, p.name], methods=["token_set_ratio", "lcs"]) if p else 0.0
        # tree.parent.tick(f" --- parent_name_sim: {parent_name_sim}")

        standalone_score = (
            +(0.5 - siblings_sim)  # Penalize if siblings are similar
            + (0.05 * has_m4b_files)  # Tiny boost for m4b files
            + (0.25 * sizes_gt_75mb)  # Boost for large files
            + (0.6 * has_mixed_file_types)  # Strong boost for mixed file types
            + (0.05 * parent_has_mixed_content)
            + ((1 - sizes_sim) * 0.75)  # Boost if sizes are dissimilar
            + (0.5 - parent_name_sim)  # Penalize if too similar to parent
            + (0.75 - sibling_files_sim)  # Boost for dissimilar sibling files
            - (0.75 * siblings_with_part_or_chapter)  # Penalize if siblings have part or chapter in the name
            + (only_file_in_parent / 2)  # 1/2 weight for only file in parent, if it's not a single
        )
        # tree.parent.tick(f" --- standalone_score: {standalone_score}")

        return ("standalone_file", round(standalone_score, 3), 0.0)
    except Exception as e:
        if "pytest" in sys.modules:
            raise e
        print_debug(f"Error scoring standalone_file: {e}")
        return (None, 0.0, 0.0)


@cached_scorer
def _score_single_standalone_file_group(
    parent: "BooksTree",
) -> dict[Path, tuple[Literal["standalone_file", "single"] | None, float, float]]:
    """Score all direct files in a parent once, including sibling bonuses."""
    base_scores = {
        file.path: _score_single_standalone_file_base(file)
        for file in parent.files
        if file.is_file()
    }

    scores = {}
    for path, result in base_scores.items():
        structure, score, single_score = result
        if structure != "standalone_file":
            scores[path] = result
            continue

        sibling_bonus = sum(
            (-0.5 + sibling_score) / 10
            for sibling_path, (_, sibling_score, _) in base_scores.items()
            if sibling_path != path
        )
        scores[path] = ("standalone_file", round(score + sibling_bonus, 3), single_score)

    return scores


@cached_scorer
def score_single_standalone_file(tree: "BooksTree") -> tuple[Literal["standalone_file", "single"] | None, float, float]:
    """
    Only determines score for files, not dirs.

    Returns:
        tuple[Literal["standalone_file", "single"], float, float]:
            - The type of structure (standalone_file or single) or None
            - The score for the standalone file
            - The score for the single file
    """
    base_score = _score_single_standalone_file_base(tree)
    if base_score[0] != "standalone_file" or not tree.parent:
        return base_score

    # Files directly below the root, a container, or a series parent are already
    # unconditionally standalone and do not receive sibling bonuses.
    if tree.parent.is_root or tree.parent.has_structure("container") or tree.parent.has_structure("series_parent"):
        return base_score

    return _score_single_standalone_file_group(tree.parent).get(tree.path, base_score)


@cached_scorer
def score_series_book(tree: "BooksTree") -> float:
    """Slightly different from other scorers, this ignores non-standalone files (i.e., will return False for a flat series book's files)"""
    try:
        from src.lib.misc import is_gt_75mb, is_gt_100mb, truthiness
        from src.lib.parsers import is_maybe_series_book, is_maybe_series_parent

        if not tree.parent or tree.parent.is_root or tree.is_root:
            return 0.0

        siblings_series_books = truthiness(
            [
                is_maybe_series_book(t.name) and (t.is_dir() or is_gt_75mb(t.size)) or t.has_structure("series_book")
                for t in tree.i.this_and_siblings._trees
            ]
        )
        siblings_series_parents = truthiness(
            [
                is_maybe_series_parent(t.name) or t.has_structure("series_parent")
                for t in tree.i.this_and_siblings._trees
            ]
        )
        parent_ok = bool(tree.parent and tree.parent)
        has_container_root = bool(tree.container_root)

        if not parent_ok or not has_container_root:
            return 0.0

        if tree.is_match:
            ...

        if tree.is_file():
            standalone_score = score_single_standalone_file(tree)[1]
            return standalone_score * int(is_maybe_series_book(tree.name))

        bad_siblings_paths = 0 - int(
            (tree.i.this_and_siblings.similarity("pathnames", distinct=True, fallback=0.0) < 0.7) / 2
        )
        parent_as_series_parent_score = float(tree.parent.has_structure("series_parent")) / (1 if not tree.dirs else 2)
        ok_file_sizes = truthiness([not is_gt_100mb(s.size) for s in tree.children or []])
        standalone_children = truthiness(
            [s.is_file() and score_single_standalone_file(s)[1] > 0.5 for s in tree.files or []]
        )

        # If any of the children are standalone files, it is not a series book
        if standalone_children > 0.1 or ok_file_sizes > 0.8:
            return 0.0

        # If the parent is a series parent, it is a series book
        if parent_as_series_parent_score > 0.5:
            return parent_as_series_parent_score

        ok_siblings = sum((bad_siblings_paths, ok_file_sizes))
        if tree.i.this_and_siblings.have_albums:
            ok_siblings += (
                float((tree.i.this_and_siblings.similarity("id3_albums", distinct=True, fallback=0.0)) > 0.9) / 2
            )

        if tree.i.this_and_siblings.have_authors:
            ok_siblings += (
                float((tree.i.this_and_siblings.similarity("id3_authors", distinct=True, fallback=0.0)) > 0.9) / 2
            )

        series_book_score = ok_siblings + siblings_series_books - siblings_series_parents

        return round(series_book_score, 3)
    except Exception as e:
        if "pytest" in sys.modules:
            raise e
        print_debug(f"Error scoring series_book: {e}")
        return 0.0


@cached_scorer
def score_series_parent(tree: "BooksTree") -> float:
    import re

    try:
        from src.lib.parsers import is_maybe_series_parent

        if tree.is_root or tree.is_file():
            return 0.0

        # A directory with NO subdirectories is almost never a series parent.
        # Genuine series parents always hold each book in its own named subdirectory
        # (e.g. "01 - The Name of the Wind/", "02 - The Wise Man's Fear/").  A flat
        # folder of audio files — however those files are named — is a flat book.
        #
        # Safety hatch 1: if the files carry *different* ID3 year tags they could
        # be distinct volumes published in different years (e.g. a LitRPG publisher
        # storing each volume as a single "Part N.mp3" with its own release year).
        # In that case fall through to normal scoring.
        #
        # Safety hatch 2: if the directory physically contains subdirectories that
        # were not scanned (e.g. due to a maxdepth scan limit), the absence of
        # tree.dirs is a depth-limit artifact rather than a genuine flat layout.
        # In that case skip the early return so normal scoring applies.
        if not tree.dirs and tree.children:
            has_physical_subdirs = tree.path.exists() and next(
                (True for p in tree.path.iterdir() if p.is_dir()), False
            )
            if not has_physical_subdirs:
                years = tree.i.files_recursive.id3_years
                years_agree = len(set(years)) <= 1  # all same year, or no years at all
                if years_agree:
                    return 0.0

        # A directory with exactly one subdirectory and no direct files is usually
        # a redundant single-subdirectory (nested book) and not a series parent.
        # Exception: if that subdirectory's name starts with a digit (year or sequence
        # number like "2008 - The Appeal" or "01 - Pride Of Chanur") it is almost
        # certainly a series book — so the parent is a series parent that still has
        # one book remaining after the others were archived.
        if len(tree.dirs) == 1 and not tree.files:
            only_child_name = str(next(iter(tree.dirs)))
            if not re.match(r"^\d", only_child_name):
                return 0.0
            # Fall through to normal scoring so the single series book is recognised.

        # If one or fewer children, it's not a series parent — unless the
        # directory appears to be a series parent on disk (e.g. children were
        # filtered out because the tree was built with a maxdepth limit, or all
        # other books in the series were already archived leaving just one).
        if len(tree.children) <= 1:
            only_child = tree.children[0] if tree.children else None
            if not tree.children and is_maybe_series_parent(tree.path):
                return 0.5
            if only_child and only_child.is_dir() and re.match(r"^\d", only_child.path.name):
                # Return a score above the 0.75 threshold so this parent is correctly
                # classified as series_parent despite having only one remaining child.
                return 0.85
            return 0.0

        tree.tick(f"init score_series_parent for {tree.rel_path}")

        def _check_series_book(c: "BooksTree"):
            nonlocal tree
            # Penalize for children that are not dirs or likely standalone files
            # tree.tick(f"check_series_book for {c.rel_path}")
            if c.has_structure("series_book") and c.is_dir():
                # tree.tick(f"has structure series_book and is dir for {c.rel_path}")
                return True
            if c.is_file() and score_single_standalone_file(c)[1] > 0.5:
                # tree.tick(f"is file and likely standalone for {c.rel_path}")
                # If sibling files form a contiguous numeric sequence they are almost
                # certainly chapters of a single flat book (e.g. "01 - Ch1.mp3",
                # "02 - Ch2.mp3", …) — not standalone series titles.  This guards
                # against the no-ID3 startup scan path where individual files score
                # higher as standalones because album-similarity data is unavailable.
                # The same logic applies to contiguous part numbers ("Part 1", "Part 2")
                # which are clearly parts of the same book, not standalone series titles.
                if (
                    c.i.this_and_siblings.have_start_nums
                    and c.i.this_and_siblings.start_nums_are_contiguous
                ) or (
                    c.i.this_and_siblings.have_part_nums
                    and c.i.this_and_siblings.part_nums_are_contiguous
                ):
                    return False
                return True
            # A directory with exactly one audio file and no subdirectories is a
            # strong structural indicator of a series book (e.g. numbered book dirs
            # each containing a single m4a/mp3 when ID3 tags are not yet scanned).
            # Exception: siblings with disc/part numbers ("CD1", "Disc 1 of 4",
            # "Part 1") are clearly disc/part children of a multi_parent book, not
            # standalone series titles.
            if c.is_dir() and not c._dirs and len(c.files) == 1:
                if c.i.this_and_siblings.have_disc_nums or c.i.this_and_siblings.have_part_nums:
                    return False
                return True
            return False

        series_parent_score = 0.0
        child_series_books_ratio = 0.0
        series_parent_children = [c for c in tree.children if score_series_parent(c) > 0.5]
        if series_parent_children:
            tree.tick(
                f"series_parent_children detected for {tree.rel_path}, returning {max((score_series_parent(c) for c in series_parent_children))}"
            )
            return -1 * max((score_series_parent(c) for c in series_parent_children))

        series_book_score = 2 if tree.has_structure("series_book") else score_series_book(tree)
        tree.tick(f"checking series_book_score for {len(tree.children)} children...")
        series_book_children = [c for c in tree.children if _check_series_book(c)]
        tree.tick(f"series_book_children: {series_book_children}")

        series_book_children_score = 0.0 if not tree.children else len(series_book_children) / len(tree.children)
        if tree.children and (child_series_books_ratio := len(series_book_children) / len(tree.children)):
            if child_series_books_ratio > 0.5:
                series_parent_score = child_series_books_ratio

        # tree.tick(f"checked children for series_book for {tree.rel_path}: {series_book_score}")

        if is_maybe_series_parent(tree.path) and (not (p := tree.parent) or not p.has_structure_like("series_parent")):
            tree.tick(f"maybe series parent for {tree.rel_path}, returning {series_parent_score}")
            series_parent_score += 0.5

        if series_book_score and series_parent_score and series_book_score >= series_parent_score:
            tree.tick(
                f"series_book_score {series_book_score} >= series_parent_score {series_parent_score}, returning {0.5 - score_flat(tree)}"
            )
            return 0.5 - score_flat(tree)

        files_have_tags = bool(tree.i.files_recursive.id3_tags)
        tree.tick(f"files_have_tags for {tree.rel_path}: {files_have_tags}")

        base_score = 0.0

        if files_have_tags:
            tree.tick(f"files_have_tags for {tree.rel_path}, calculating tag similarities")
            author_sim = tree.i.files_recursive.similarity("id3_authors", fallback=0.0)
            album_sim = tree.i.files_recursive.similarity("id3_albums", fallback=0.0)
            author_sim_distinct = tree.i.files_recursive.similarity("id3_authors", distinct=True, fallback=0.0)
            album_sim_distinct = tree.i.files_recursive.similarity("id3_albums", distinct=True, fallback=0.0)
            tree.tick(f"author_sim for {tree.rel_path}: {author_sim}")
            tree.tick(f"album_sim for {tree.rel_path}: {album_sim}")
            tree.tick(f"author_sim_distinct for {tree.rel_path}: {author_sim_distinct}")
            tree.tick(f"album_sim_distinct for {tree.rel_path}: {album_sim_distinct}")

            # If the author is dissimilar, it's probably not related at all (not a series parent)
            author_sim_diff = abs(author_sim - author_sim_distinct)
            album_sim_diff = abs(album_sim - album_sim_distinct)
            if author_sim <= 0.85 or author_sim_diff >= 0.1:
                base_score -= max(author_sim, author_sim_diff)

            # If author is similar, but album_sim/album_sim_distinct are different, we're probably dealing with multiple titles
            elif (author_sim > 0.85 or author_sim_diff < 0.1) and (album_sim < 0.85 or album_sim_diff > 0.1):
                # If similar authors, but dissimilar albums, it's a good candidate for series parent
                # Take the average of the inverse album and author similarity
                base_score += round((1 - album_sim + author_sim) / 2, 3)
            else:
                # Take the inverse score and penalize based on album similarity
                avg_album_sim = (album_sim + album_sim_distinct) / 2
                avg_author_sim = (author_sim + author_sim_distinct) / 2
                base_score -= avg_album_sim / 2
                base_score -= -0.5 + avg_author_sim / 2

        tree.tick(f"base_score for {tree.rel_path}: {base_score}")

        # disc_nums_score += tags_offset
        # part_nums_score += tags_offset

        # id3_checks = 0.0
        # if tree.i.children.have_albums:
        #     d = tree.i.children.similarity("id3_albums", fallback=0.0)
        #     # Strongly penalize if child albums all match
        #     id3_checks -= d if d < 0.95 else 2

        # if tree.i.children.have_authors:
        #     id3_checks += int((tree.i.children.similarity("id3_authors", fallback=0.0)) > 0.9) / 3

        def get_nums_score(nums: Literal["series_nums", "start_nums", "part_nums"], score: Literal["+", "-"]):
            tree.tick(f"get_nums_score for {tree.rel_path}, nums: {nums}, score: {score}")

            nums_cmpl = []
            nums_uniq = []

            if len(getattr(tree.i.children, nums)) > 1:
                # Low completion is more likely to be a series parent, high we can't be sure
                # Low uniqueness is more likely to be a series parent, high we can't be sure
                nums_cmpl.append(0.5 - cast(float, getattr(tree.i.children, f"{nums}_completion")))
                nums_uniq.append(0.5 - cast(float, getattr(tree.i.children, f"{nums}_uniqueness")))

            num_score = 0.0
            if nums_cmpl:
                num_score += sum(nums_cmpl) / len(nums_cmpl)
            if nums_uniq:
                num_score += sum(nums_uniq) / len(nums_uniq)

            nums_score = -num_score if num_score and score == "+" else num_score
            tree.tick(f"nums_score for {tree.rel_path}, nums: {nums}, score: {nums_score}")
            return nums_score

        num_score = 0.0

        if tree.i.children.have_series_nums:
            tree.tick(f"have_series_nums for {tree.rel_path}, calculating series_nums_score")
            # Series numbers are good, and we want them to be complete + unique
            num_score += get_nums_score("series_nums", "+") * 0.75

        if not files_have_tags and tree.i.children.have_start_nums:
            tree.tick(f"have_start_nums for {tree.rel_path}, calculating start_nums_score")
            path_sim = tree.i.children.similarity("pathnames", distinct=True, include_curr=True, fallback=0.0)
            standalones_score = (
                0.0
                if not tree.files
                else sum([score_single_standalone_file(c)[1] for c in tree.files]) / len(tree.files)
            )

            if len(tree.i.children.start_nums) > 1:
                tree.tick(f"have_start_nums for {tree.rel_path}, calculating start_nums_score")
                # Low completion is more likely to be a series parent, high we can't be sure
                # Low uniqueness is more likely to be a series parent, high we can't be sure
                num_score += get_nums_score("start_nums", "-") / 4
            if len(tree.i.children.part_nums) > 1:
                tree.tick(f"have_part_nums for {tree.rel_path}, calculating part_nums_score")
                # Same as start numbers, part nums may indicate multi_disc or flat
                num_score += get_nums_score("part_nums", "-") / 4

            flat_penalty = -1 * score_flat(tree)
            tree.tick(f"flat_penalty for {tree.rel_path}: {flat_penalty}")
            # The more similar the pathnames are, the less likely this is a series parent
            path_sim_penalty = min(0.0, 0.5 - path_sim)
            tree.tick(f"path_sim_penalty for {tree.rel_path}: {path_sim_penalty}")

            base_score = (
                sum(
                    (
                        series_book_children_score,
                        path_sim_penalty,
                        standalones_score,
                        flat_penalty,
                    )
                )
                / 5
            )
            tree.tick(f"base_score for {tree.rel_path}: {base_score}")

        series_parent_score = base_score + num_score + child_series_books_ratio

        # Boost when the parent's multi-word name appears verbatim in the majority of
        # children's names.  This catches series like "Shaman's Tales from the Golden Age
        # of the Solar Clipper" whose three book subdirs each embed the full series title
        # in their own name, producing high path/album similarity that the tag branch
        # would otherwise penalise as "same book, different parts".
        parent_name_lower = tree.name.lower()
        if len(parent_name_lower.split()) >= 2 and tree.children:
            children_with_parent_name = sum(
                1 for c in tree.children if parent_name_lower in c.name.lower()
            )
            if children_with_parent_name > len(tree.children) / 2:
                series_parent_score += 0.5

        if bool(re.search(r"(?:\b|_)series(?:\b|_)", tree.name.lower(), re.I)):
            series_parent_score = max(series_parent_score + 0.75, 0.95)
            tree.tick(f"series_parent_score from regex (?:\\b|_)series(?:\\b|_) {tree.rel_path}: {series_parent_score}")
        if tree.i.this.has_series_num or tree.i.this.has_start_num or tree.i.this.has_disc_num:
            # Penalize if the parent candidate has numbers, not very likely to be a series parent
            series_parent_score -= 0.4
            tree.tick(f"series_parent_score from numbers for {tree.rel_path}: {series_parent_score}")

        tree.tick(f"returning series_parent_score for {tree.rel_path}: {series_parent_score}")
        return round(series_parent_score, 3)
    except Exception as e:
        if "pytest" in sys.modules:
            raise e
        print_debug(f"Error scoring series_parent: {e}")
        return 0.0


@cached_scorer
def score_multi_parent(tree: "BooksTree") -> float:
    try:
        if not tree.parent or tree.is_root or tree.is_file() or not tree.dirs:
            return 0.0

        multi_disc_score = 0.0
        multi_part_score = 0.0

        if tree.i.this_and_siblings.have_disc_nums:
            completion = len(tree.i.this_and_siblings.disc_nums) / len(tree.i.this_and_siblings._trees)
            contiguous = float(tree.i.this_and_siblings.disc_nums_are_contiguous or 0)
            multi_disc_score = 1 - (completion + contiguous)
        elif tree.i.dirs.have_disc_nums:
            # Only check subdirectory names — not file names. A multi_parent requires
            # actual subdirectory children (e.g. "Disc 1/", "Disc 2/"). Files in a flat
            # book can have disc-like numbers in their names (e.g. "cd1-track01.mp3")
            # but that must not inflate the multi_parent score.
            completion = len(tree.i.dirs.disc_nums) / len(tree.i.dirs._trees)
            contiguous = float(tree.i.dirs.disc_nums_are_contiguous or 0)
            multi_disc_score = completion + contiguous

        if tree.i.this_and_siblings.have_part_nums:
            completion = len(tree.i.this_and_siblings.part_nums) / len(tree.i.this_and_siblings._trees)
            contiguous = float(tree.i.this_and_siblings.part_nums_are_contiguous or 0)
            multi_part_score = 1 - (completion + contiguous)
        elif tree.i.dirs.have_part_nums:
            # Only check subdirectory names — not file names. Files in a flat book
            # may contain "Chapter X." or "Part Y." in their names (e.g.
            # "05 - Chapter 1. Understanding Emotional Dysregulation.mp3"), which
            # would produce false-positive part_nums and cause the flat book to be
            # misclassified as a multi_parent with a very high score.
            completion = len(tree.i.dirs.part_nums) / len(tree.i.dirs._trees)
            contiguous = float(tree.i.dirs.part_nums_are_contiguous or 0)
            multi_part_score = completion + contiguous

        if tree.is_match:
            ...

        if not multi_disc_score:
            return round(multi_part_score, 3)

        if not multi_part_score:
            return round(multi_disc_score, 3)

        return round(max(multi_disc_score, multi_part_score), 3)
    except Exception as e:
        if "pytest" in sys.modules:
            raise e
        print_debug(f"Error scoring multi_parent: {e}")
        return 0.0


@cached_scorer
def score_multi_part_or_disc(tree: "BooksTree") -> tuple[Literal["multi_part", "multi_disc"] | None, float, float]:
    """
    Returns a tuple of (type, disc_nums_score, part_nums_score)
    """
    try:
        # Multi-part is a subdir contained in a parent, so we need to check the dir's siblings
        if (
            not tree.parent
            or tree.is_root
            or not tree.parent
            or tree.parent.is_root
            or tree.has_structure("series_parent")
        ):
            # If it doens't have a parent, or its parent is root, it can't be a multi-part
            # (We score multi-parents in a separate pass)
            return (None, 0.0, 0.0)

        if tree.is_match:
            ...

        if tree.is_file():
            return score_multi_part_or_disc(tree.parent)

        p = tree.parent
        parent_files_have_tags = bool(p.i.files_recursive.id3_tags)
        path_sim = p.i.children_recursive.similarity("pathnames", fallback=0.0)
        album_sim = p.i.children_recursive.similarity("id3_albums", fallback=path_sim)
        author_sim = p.i.children_recursive.similarity("id3_artists", fallback=path_sim)
        album_sim_distinct = p.i.children_recursive.similarity("id3_albums", distinct=True, fallback=path_sim)
        author_sim_distinct = p.i.children_recursive.similarity("id3_artists", distinct=True, fallback=path_sim)

        has_disc_nums = p.i.children.have_disc_nums
        disc_nums_cmpl = p.i.children.disc_nums_completion
        disc_nums_cntg = p.i.children.disc_nums_are_contiguous
        disc_nums_score = 1.0 if has_disc_nums else -1.0
        disc_nums_penalty = 0.0

        if has_disc_nums:
            disc_nums_penalty += -1.0 + (disc_nums_cmpl or 0.0)
            disc_nums_penalty += -1.0 + (disc_nums_cntg or 0.0)

        has_part_nums = p.i.children.have_part_nums
        part_nums_cmpl = p.i.children.part_nums_completion
        part_nums_cntg = p.i.children.part_nums_are_contiguous
        part_nums_uniq = p.i.children.part_nums_uniqueness
        part_nums_score = 1.0 if has_part_nums else -1.0
        if disc_nums_score > 0:
            part_nums_score -= disc_nums_score
        part_nums_penalty = 0.0
        if has_part_nums:
            part_nums_penalty += -1.0 + (part_nums_cmpl or 0.0)
            part_nums_penalty += -1.0 + (part_nums_cntg or 0.0)
            part_nums_penalty += -1.0 + (part_nums_uniq or 0.0)

        disc_nums_score += disc_nums_penalty
        part_nums_score += part_nums_penalty

        tags_offset = 0.0

        if parent_files_have_tags:
            # If album_sim and album_sim_distinct are considerably different, we're probably dealing with multiple titles
            author_sim_diff = abs(author_sim - author_sim_distinct)
            album_sim_diff = abs(album_sim - album_sim_distinct)
            if author_sim < 0.65 or album_sim < 0.85 or author_sim_diff > 0.1 or album_sim_diff > 0.1:
                # If very dissimilar authors, or not closely related albums, it's probably not a multi-part or multi-disc.
                avg_album_sim = (album_sim + album_sim_distinct) / 2
                avg_author_sim = (author_sim + author_sim_distinct) / 2
                tags_offset = -1 * (1 - round(min(avg_album_sim, avg_author_sim), 3))
            else:
                # Slight boost from the average of the album and author similarity
                tags_offset = round((album_sim + author_sim) / 2, 3) / 4

        # When folder names give a complete, contiguous disc/part sequence the structural
        # signal is unambiguous. Ripped audiobooks commonly have inconsistent album tags
        # per disc, so dampen tag-noise penalties in that case to avoid misclassifying
        # a clearly-named multi-disc book as flat/unknown.
        disc_complete_and_contiguous = disc_nums_cmpl == 1.0 and bool(disc_nums_cntg)
        part_complete_and_contiguous = part_nums_cmpl == 1.0 and bool(part_nums_cntg)
        if tags_offset < 0:
            if disc_complete_and_contiguous or part_complete_and_contiguous:
                tags_offset *= 0.25  # dampen negative penalty to 25% when structure is clear

        disc_nums_score += tags_offset
        part_nums_score += tags_offset

        disc_nums_score = round(disc_nums_score, 3)
        part_nums_score = round(part_nums_score, 3)

        if disc_nums_score > 0 and disc_nums_score > part_nums_score:
            return ("multi_disc", disc_nums_score, part_nums_score)

        elif part_nums_score > 0 and part_nums_score > disc_nums_score:
            return ("multi_part", part_nums_score, disc_nums_score)

        return (None, disc_nums_score, part_nums_score)
    except Exception as e:
        if "pytest" in sys.modules:
            raise e
        print_debug(f"Error scoring multi_part: {e}")
        return (None, 0.0, 0.0)


@cached_scorer
def tree_complexity(tree: "BooksTree") -> float:
    """
    Calculates the complexity of the tree structure based on:
    1. Depth of nesting
    2. Mixing of files at different levels
    3. Irregularity in the structure
    4. Number of branches/forks

    Returns a float between 0 and 1, where:
    - 0 means perfectly flat structure (all files in one directory)
    - 1 means highly complex structure with mixed levels and irregular nesting
    """
    if not tree.children_recursive:
        return 0.0

    # Get all nodes in the tree
    all_nodes = tree.children_recursive
    if not all_nodes:
        return 0.0

    # Calculate base metrics
    max_depth = max(node.depth for node in all_nodes)
    total_files = len([n for n in all_nodes if n.is_file()])
    total_dirs = len([n for n in all_nodes if n.is_dir()])

    if total_files == 0:
        return 0.0

    # Calculate file distribution across depths
    files_by_depth = {}
    for node in all_nodes:
        if node.is_file():
            depth = node.depth
            files_by_depth[depth] = files_by_depth.get(depth, 0) + 1

    # Calculate mixing score (how evenly files are distributed across depths)
    depth_variance = 0
    if len(files_by_depth) > 1:
        mean_files_per_depth = total_files / len(files_by_depth)
        depth_variance = sum((count - mean_files_per_depth) ** 2 for count in files_by_depth.values()) / len(
            files_by_depth
        )
        depth_variance = min(1.0, depth_variance / (total_files**2))  # Normalize to 0-1

    # Calculate branching factor
    avg_children_per_dir = total_files / total_dirs if total_dirs > 0 else 0
    branching_factor = min(1.0, avg_children_per_dir / 10)  # Normalize assuming 10 is max reasonable

    # Calculate depth penalty
    depth_penalty = min(1.0, max_depth / 5)  # Normalize assuming 5 is max reasonable depth

    # Calculate irregularity (how many different depths have files)
    irregularity = min(1.0, len(files_by_depth) / max_depth) if max_depth > 0 else 0

    # Combine all factors with weights
    complexity = (
        depth_penalty * 0.3  # 30% weight to depth
        + depth_variance * 0.3  # 30% weight to file distribution
        + branching_factor * 0.2  # 20% weight to branching
        + irregularity * 0.2  # 20% weight to irregularity
    )

    if tree.is_match:
        ...

    return round(complexity, 3)
