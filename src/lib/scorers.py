import functools
import re
from pathlib import Path
from typing import cast, Literal, TYPE_CHECKING

from columnar import columnar
from rapidfuzz import fuzz
from rapidfuzz.distance import LCSseq, Levenshtein

from lib.compare import get_similarity
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
from src.lib.patterns import common_str_pattern, startswith_num_pattern
from src.lib.term import print_debug

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook
    from src.lib.books_tree.books_tree import BooksTree
    from src.lib.typing import AdditionalTags, ScoredProp, TagSource


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


def score_container_mixed(tree: "BooksTree") -> tuple[Literal["container", "mixed"] | None, float, float]:
    """Tries to determine if a directory is a container or mixed

    Returns:
        tuple[Literal["container", "mixed"], float, float]:
            - The type of structure (container or mixed)
            - The score for the container
            - The score for the mixed
    """

    try:
        from src.lib.misc import is_gt_50mb, is_gt_75mb, percent_truthy_in_list

        if tree.is_file() or tree.is_root or not tree.children_recursive or tree.structure:
            return (None, 0.0, 0.0)

        cri = tree.i.children_recursive

        files_sim = tree.i.files.pathname_similarity(distinct=True) or 0.0
        dirs_sim = tree.i.dirs.pathname_similarity(distinct=True) or 0.0
        children_sim = 1.0 - (tree.i.children.pathname_similarity(distinct=True) or 0.0)
        pathnames_sim = tree.i.files.pathname_similarity(distinct=True) or 0.0

        has_multiple_files = len(tree.files) > 1
        has_files_and_dirs = bool(tree.parent and (tree.parent.files or tree.parent.dirs))
        standalones = -0.5 + percent_truthy_in_list([score_standalone_file(f) > 0.4 for f in tree.files]) / 100
        files_gt_50mb = percent_truthy_in_list([is_gt_50mb(f.size) for f in tree.files]) / 100
        files_gt_75mb = percent_truthy_in_list([is_gt_75mb(f.size) for f in tree.files]) / 100
        dirs_gt_75mb = percent_truthy_in_list([is_gt_75mb(c.size) for c in tree.dirs.values()]) / 100

        known_structures = tree.known_structures_r
        missing_structures = len(tree.children_without_structure_r) / len(tree.children_recursive)
        incomplete_path_nums = (0.0 if not cri.all_path_nums else (-1.0 + (cri.all_path_nums_completion or 0.0))) / 4

        mixed_score = 0.0
        container_score = 0.0

        # container_score = (
        #     percent_truthy_in_list(
        #         [
        #             dissimilar_files,
        #             dissimilar_dirs,
        #             has_multiple_files,
        #             has_files_and_dirs,
        #             pathnames_similarity,
        #             standalones > 0,
        #         ]
        #     )
        #     / 100
        # )

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

        container_score = round(container_score, 3)
        mixed_score = round(mixed_score, 3)

        if container_score > mixed_score:
            return ("container", container_score, mixed_score)
        elif mixed_score > container_score:
            return ("mixed", container_score, mixed_score)
        else:
            return (None, container_score, mixed_score)

        # try:
        #     from src.lib.misc import is_gt_75mb, percent_truthy_in_list

        #     if not tree.children_recursive or tree.is_file():
        #         return 0.0

        #     if tree.is_match:
        #         ...

        #     if tree.structure:
        #         return 0.0

        #     cri = tree.i.children_recursive

        #     dissimilar_children = 1.0 - (tree.i.children.pathname_similarity(distinct=True) or 0)
        #     children_gt_75mb = percent_truthy_in_list([is_gt_75mb(c.size) for c in tree.files]) / 100
        #     standalone_ratio = dissimilar_children + children_gt_75mb
        #     if children_gt_75mb == 0:
        #         # If there are no likely standalone files, strongly boost mixed (negative standalone ratio)
        #         standalone_ratio -= 1.0

        #     container = max(score_container(tree), 0)
        #     complexity = tree_complexity(tree)
        #     incomplete_path_nums = 0.0 if not cri.all_path_nums else 1.0 - (cri.all_path_nums_completion or 0)

        #     return round(complexity + incomplete_path_nums - container - standalone_ratio, 3)
        # except Exception as e:
        #     print_debug(f"Error scoring mixed: {e}")
        #     return 0.0

        # return round(container_score, 3)

    except Exception as e:
        print_debug(f"Error scoring container/mixed: {e}")
        return (None, 0.0, 0.0)


def score_flat(tree: "BooksTree") -> float:
    try:
        if tree.is_match:
            ...

        if not tree.parent or tree.is_root:
            return 0.0

        multi_disc_score = score_multi_disc(tree)

        if tree.is_file():

            if tree.parent.is_root or (tree.parent and tree.parent.dirs) or multi_disc_score > 0.5:
                return 0.0

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

        if tree.dirs or multi_disc_score > 0.5:
            return 0.0

        album_similarity = tree.i.children_recursive.album_similarity() or 0
        author_similarity = tree.i.children_recursive.author_similarity() or 0
        pathname_similarity = tree.i.children_recursive.pathname_similarity(distinct=True) or 0

        if (tree.parent.is_root or tree.parent.has_structure("container")) and (
            album_similarity > 0.9 and author_similarity > 0.9
        ):
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
        return round((completion + contiguous + pathname_similarity) / 3, 3)
    except Exception as e:
        print_debug(f"Error scoring flat: {e}")
        return 0.0


def score_standalone_file(tree: "BooksTree") -> float:
    try:
        from src.lib.misc import is_gt_75mb, percent_truthy_in_list

        if not tree.is_file():
            return 0.0

        if (p := tree.parent) and (
            p.is_root
            or p.has_structure("container")
            or p.has_structure("multi_parent")
            or p.has_structure("series_parent")
        ):
            return 1.0

        if tree.is_match:
            ...

        parent_has_files_and_dirs = bool(p and (p.files or p.dirs))
        parent_has_multiple_dirs = bool(p and len(p.dirs) > 1)
        parent_has_mixed_content = parent_has_files_and_dirs or parent_has_multiple_dirs

        dissimilar_siblings = (tree.i.this_and_siblings.pathname_similarity(distinct=True) or 0) < 0.8
        contiguous_siblings = (
            tree.i.this_and_siblings.track_nums_are_contiguous
            or tree.i.this_and_siblings.start_nums_are_contiguous
            or tree.i.this_and_siblings.part_nums_are_contiguous
        )
        suffixes = list(set([f.path.suffix for f in p.files])) if p else []
        has_mixed_file_types = len(suffixes) > 1 if p else False
        all_sizes_gt_75mb = all(is_gt_75mb(f.size) for f in p.files) if p else False
        has_m4b_files = ".m4b" in suffixes if p else False

        standalone_score = (
            percent_truthy_in_list(
                [
                    dissimilar_siblings,
                    not contiguous_siblings,
                    has_mixed_file_types,
                    all_sizes_gt_75mb,
                    has_m4b_files,
                    parent_has_mixed_content,
                ]
            )
            / 100
        )

        if tree.is_match:
            ...

        if tree.i.this_and_siblings.have_albums and (
            (siblings_album_similarity := tree.i.this_and_siblings.album_similarity(distinct=True) or 0) < 0.9
        ):
            standalone_score += 1 - siblings_album_similarity

        if tree.i.this_and_siblings.have_authors and (
            (siblings_author_similarity := tree.i.this_and_siblings.author_similarity(distinct=True) or 0) < 0.7
        ):
            standalone_score += 1 - siblings_author_similarity

        # if it has a track number/total other than None, 1, or 1/1, subtract 1.5
        if tree.i.this.has_track_num and (tree.i.this.id3_track_num > 1 or not tree.i.this.id3_track_total > 1):
            standalone_score -= 1.5

        # if it has a disc number/total other than None, 1, or 1/1, subtract 1.5
        if tree.i.this.has_disc_num and (tree.i.this.id3_disc_num > 1 or not tree.i.this.id3_disc_total > 1):
            standalone_score -= 1.5

        return round(standalone_score, 3)
    except Exception as e:
        print_debug(f"Error scoring standalone_file: {e}")
        return 0.0


def score_series_book(tree: "BooksTree") -> float:
    """Slightly different from other scorers, this ignores non-standalone files (i.e., will return False for a flat series book's files)"""
    try:
        from src.lib.misc import is_gt_75mb, is_gt_100mb, percent_truthy_in_list
        from src.lib.parsers import is_maybe_series_book, is_maybe_series_parent

        if not tree.parent or tree.parent.is_root or tree.is_root:
            return 0.0

        siblings_series_books = (
            percent_truthy_in_list(
                [
                    is_maybe_series_book(t.name)
                    and (t.is_dir() or is_gt_75mb(t.size))
                    or t.has_structure("series_book")
                    for t in tree.i.this_and_siblings._trees
                ]
            )
            / 100
        )
        siblings_series_parents = (
            percent_truthy_in_list(
                [
                    is_maybe_series_parent(t.name) or t.has_structure("series_parent")
                    for t in tree.i.this_and_siblings._trees
                ]
            )
            / 100
        )
        parent_ok = bool(tree.parent and tree.parent)
        has_container_root = bool(tree.container_root)

        if not parent_ok or not has_container_root:
            return 0.0

        if tree.is_match:
            ...

        if tree.is_file():
            standalone_score = score_standalone_file(tree)
            return standalone_score * int(is_maybe_series_book(tree.name))

        bad_siblings_paths = 0 - int((tree.i.this_and_siblings.pathname_similarity(distinct=True) or 0) < 0.7) / 2
        parent_as_series_parent_score = float(tree.parent.has_structure("series_parent")) / (1 if not tree.dirs else 2)
        ok_file_sizes = percent_truthy_in_list([not is_gt_100mb(s.size) for s in tree.children or []]) / 100
        standalone_children = (
            percent_truthy_in_list([s.is_file() and score_standalone_file(s) > 0.5 for s in tree.files or []]) / 100
        )

        # If any of the children are standalone files, it is not a series book
        if standalone_children > 0.1 or ok_file_sizes > 0.8:
            return 0.0

        # If the parent is a series parent, it is a series book
        if parent_as_series_parent_score > 0.5:
            return parent_as_series_parent_score

        ok_siblings = sum((bad_siblings_paths, ok_file_sizes))
        if tree.i.this_and_siblings.have_albums:
            ok_siblings += float((tree.i.this_and_siblings.album_similarity(distinct=True) or 0) > 0.9) / 2

        if tree.i.this_and_siblings.have_authors:
            ok_siblings += float((tree.i.this_and_siblings.author_similarity(distinct=True) or 0) > 0.9) / 2

        series_book_score = ok_siblings + siblings_series_books - siblings_series_parents

        return round(series_book_score, 3)
    except Exception as e:
        print_debug(f"Error scoring series_book: {e}")
        return 0.0


def score_series_parent(tree: "BooksTree") -> float:
    try:
        from src.lib.misc import is_gt_50mb, percent_truthy_in_list
        from src.lib.parsers import is_maybe_series_book, is_maybe_series_parent

        if tree.is_root or tree.is_file() or (len(tree.dirs) == 1 and not tree.files):
            return 0.0

        series_parent_score = 0.0
        child_series_books_ratio = 0.0
        series_parent_children = [c for c in tree.children if c.score_series_parent > 0.5]
        series_book_score = 2 if tree.has_structure("series_book") else score_series_book(tree)
        series_book_children = [
            c for c in tree.children if c.has_structure("series_book") or score_series_book(c) > 0.5
        ]
        if tree.is_match:
            ...
        # Penalize children that are not dirs or likely standalone files
        series_book_children = [c for c in series_book_children if c.is_dir() or score_standalone_file(c) > 0.5]
        if tree.children and (child_series_books_ratio := len(series_book_children) / len(tree.children)):
            if child_series_books_ratio > 0.5:
                series_parent_score = child_series_books_ratio

        if is_maybe_series_parent(tree.path) and (not (p := tree.parent) or not p.has_structure_like("series_parent")):
            if tree.is_match:
                ...
            series_parent_score += 0.5

        if series_parent_children:
            return -1 * max((c.score_series_parent for c in series_parent_children))

        if series_book_score >= series_parent_score:
            return 0.5 - score_flat(tree)

        id3_checks = 0.0
        if tree.i.children.have_albums:
            d = tree.i.children.album_similarity() or 0
            # Strongly penalize if child albums all match
            id3_checks -= d if d < 0.95 else 2

        if tree.i.children.have_authors:
            id3_checks += int((tree.i.children.author_similarity() or 0) > 0.9) / 3

        ok_children = id3_checks

        if (
            not bool(id3_checks)
            # and not self.this.has_series_num
            # and not self.this.has_start_num
            and (tree.i.children.have_series_nums or tree.i.children.have_start_nums)
        ):
            series_book_children = -0.5 + (
                percent_truthy_in_list([is_maybe_series_book(t.name) for t in tree.children]) / 100
            )
            path_similarity = -0.5 + (tree.i.children.pathname_similarity(distinct=True, include_curr=True) or 0.5)
            child_sizes = -0.5 + percent_truthy_in_list([is_gt_50mb(p.size) for p in tree.children]) / 100
            series_completion = 0
            series_uniqueness = 0
            if tree.i.children.have_series_nums:
                series_completion = -0.5 + float((tree.i.children.series_nums_completion or 1) > 0.95)
                series_uniqueness = float(((tree.i.children.series_nums_uniqueness or 1) > 0.2) / 2)
            start_completion = 0
            if tree.i.children.have_start_nums:
                start_completion = -0.5 + float((tree.i.children.start_nums_completion or 1) > 0.95)
            part_completion = 0
            if tree.i.children.have_part_nums:
                part_completion = -0.5 + float((tree.i.children.part_nums_completion or 1) > 0.5)
            part_uniqueness = -0.5 + float(
                not tree.i.children.have_part_nums or (tree.i.children.part_nums_uniqueness or 0) < 0.1
            )
            if tree.is_match:
                ...

            ok_children = float(
                sum(
                    (
                        series_book_children,
                        path_similarity,
                        child_sizes,
                        series_completion,
                        part_completion,
                        start_completion,
                        series_uniqueness,
                        part_uniqueness,
                        -1 * score_flat(tree),
                    )
                )
            )

        series_parent_score = ok_children + child_series_books_ratio
        if bool(re.search(r"(?:\b|_)series(?:\b|_)", tree.name.lower(), re.I)):
            series_parent_score += 1
        if tree.i.this.has_series_num or tree.i.this.has_start_num or tree.i.this.has_disc_num:
            # Penalize if the parent candidate has numbers, not very likely to be a series parent
            series_parent_score -= 0.5

        return round(series_parent_score, 3)
    except Exception as e:
        print_debug(f"Error scoring series_parent: {e}")
        return 0.0


def score_single(tree: "BooksTree") -> float:
    """
    Only determines if a file is a single file, not dirs that contain them.
    """
    try:

        if not tree.is_file() or (p := tree.parent) and p.is_root:
            return 0.0

        if not (_only_file_in_parent := p and len(p.files) == 1 and not p.dirs):
            return 0.0

        return round(get_similarity([tree.name, tree.parent.name]), 3) if tree.parent else 1.0
    except Exception as e:
        print_debug(f"Error scoring single: {e}")
        return 0.0


# def score_mixed(tree: "BooksTree") -> float:
#     """Only determines mixed for dirs, not files"""
#     try:
#         from src.lib.misc import is_gt_75mb, percent_truthy_in_list

#         if not tree.children_recursive or tree.is_file():
#             return 0.0

#         if tree.is_match:
#             ...

#         if tree.structure:
#             return 0.0

#         cri = tree.i.children_recursive

#         dissimilar_children = 1.0 - (tree.i.children.pathname_similarity(distinct=True) or 0)
#         children_gt_75mb = percent_truthy_in_list([is_gt_75mb(c.size) for c in tree.files]) / 100
#         standalone_ratio = dissimilar_children + children_gt_75mb
#         if children_gt_75mb == 0:
#             # If there are no likely standalone files, strongly boost mixed (negative standalone ratio)
#             standalone_ratio -= 1.0

#         container = max(score_container(tree), 0)
#         complexity = tree_complexity(tree)
#         incomplete_path_nums = 0.0 if not cri.all_path_nums else 1.0 - (cri.all_path_nums_completion or 0)

#         return round(complexity + incomplete_path_nums - container - standalone_ratio, 3)
#     except Exception as e:
#         print_debug(f"Error scoring mixed: {e}")
#         return 0.0


def score_multi_parent(tree: "BooksTree") -> float:
    try:
        if not tree.parent or tree.is_root or tree.is_file():
            return 0.0

        multi_disc_score = 0.0
        multi_part_score = 0.0

        if tree.i.this_and_siblings.have_disc_nums:
            completion = len(tree.i.this_and_siblings.disc_nums) / len(tree.i.this_and_siblings._trees)
            contiguous = float(tree.i.this_and_siblings.disc_nums_are_contiguous or 0)
            multi_disc_score = 1 - (completion + contiguous)
        elif tree.i.children.have_disc_nums:
            completion = len(tree.i.children.disc_nums) / len(tree.i.children._trees)
            contiguous = float(tree.i.children.disc_nums_are_contiguous or 0)
            multi_disc_score = completion + contiguous

        if tree.i.this_and_siblings.have_part_nums:
            completion = len(tree.i.this_and_siblings.part_nums) / len(tree.i.this_and_siblings._trees)
            contiguous = float(tree.i.this_and_siblings.part_nums_are_contiguous or 0)
            multi_part_score = 1 - (completion + contiguous)
        elif tree.i.children.have_part_nums:
            completion = len(tree.i.children.part_nums) / len(tree.i.children._trees)
            contiguous = float(tree.i.children.part_nums_are_contiguous or 0)
            multi_part_score = completion + contiguous

        if tree.is_match:
            ...

        if not multi_disc_score:
            return round(multi_part_score, 3)

        if not multi_part_score:
            return round(multi_disc_score, 3)

        return round(max(multi_disc_score, multi_part_score), 3)
    except Exception as e:
        print_debug(f"Error scoring multi_parent: {e}")
        return 0.0


def score_multi_disc(tree: "BooksTree") -> float:
    try:
        if not tree.parent or tree.is_root:
            return 0.0

        if tree.is_match:
            ...

        if tree.is_file():
            return tree.i.this_and_siblings.disc_nums_completion or 0.0

        return tree.i.children.disc_nums_completion or tree.i.this_and_siblings.disc_nums_completion or 0.0
    except Exception as e:
        print_debug(f"Error scoring multi_disc: {e}")
        return 0.0


def score_multi_part(tree: "BooksTree") -> float:
    try:
        if not tree.parent or tree.is_root:
            return 0.0

        if tree.is_match:
            ...

        if tree.has_structure("series_parent"):
            return 0.1

        if tree.is_file():
            sibling_dirs = [s for s in tree.i.this_and_siblings._trees if s.is_dir()]
            sibling_dir_boost = len(sibling_dirs) / 5
            return (tree.i.this_and_siblings.part_nums_completion or 0.0) + sibling_dir_boost

        parent_num_penalty = (
            1
            if not tree.parent.is_root
            and not tree.i.this_and_siblings.have_part_nums
            or not tree.i.this_and_siblings.part_nums_are_contiguous
            else 0
        )

        children_dir_boost = len(tree.dirs) / 5
        return (tree.i.children.part_nums_completion or 0.0) + children_dir_boost - parent_num_penalty
    except Exception as e:
        print_debug(f"Error scoring multi_part: {e}")
        return 0.0


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
