import os
import re
import string
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, cast, Literal, overload, TYPE_CHECKING, TypeVar

import cachetools
import cachetools.func
import regex as rex

from src.lib.misc import (
    get_numbers_in_string,
    isorted,
    re_group,
)
from src.lib.term import print_debug
from src.lib.typing import AuthorNarrator, MEMO_TTL, NameParserTarget

# TODO: Add test coverage for narrator with /
# fmt: off
_titlecase_word = r"[A-Z][\p{Ll}\.'-]*"
_author_prefixes = r"[Ww]ritten.?[Bb]y|[Aa]uthor"
_narrator_prefixes = r"(?:[Rr]ead|[Nn]arrated|[Pp]erformed).?[Bb]y|[Nn]arrator"
def _name_substr(ignore_if_trailing: str = '', max_l_of_comma: int = 4, max_r_of_comma: int = 4):
    if ignore_if_trailing:
        ignore_if_trailing = f"(?!{ignore_if_trailing})"
    # (?:[Ww]ritten.?[Bb]y|[Pp]erformed.?[Bb]y|[Rr]ead.?[Bb]y)\W+(?P<name>(?:(?:(?<= )(?: ?[A-Z][a-z\.-]*){1,4})),? ?(?:(?: ?[A-Z][a-z\.-]*){1,4}(?!Performed by)))
    return rf"(?:(?:(?:^|(?<= ))(?: ?{_titlecase_word}){{1,{max_l_of_comma}}})),? ?(?:(?: ?{_titlecase_word}){{1,{max_r_of_comma}}}{ignore_if_trailing})"
_div = r"[-_–—.\s]*?"
wordsplit_pat = re.compile(r"[\s_.]")

author_fs_pattern = re.compile(r"^(?P<author>.*?)[\W\s]*[-_–—\(]", re.I)
author_comment_pattern = rex.compile(rf"(?:{_author_prefixes})\W+(?P<author>{_name_substr(_narrator_prefixes)})", rex.V1)
author_generic_pattern = rex.compile(rf"(?P<author>{_name_substr()})", rex.V1)
narrator_comment_pattern = rex.compile(rf"(?:{_narrator_prefixes})\W+(?P<narrator>{_name_substr(_author_prefixes)})", rex.V1)
narrator_generic_pattern = rex.compile(rf"(?P<narrator>{_name_substr()})", rex.V1)
narrator_slash_pattern = re.compile(r"(?P<author>.+)\/(?P<narrator>.+)", re.I)
narrator_in_artist_pattern = re.compile(rf"(?P<author>.*)\W+{narrator_comment_pattern}", re.I)
graphic_audio_pattern = re.compile(r"graphic\s*audio", re.I)
lastname_firstname_pattern = re.compile(r"^(?P<lastname>.*?), (?P<firstname>.*)$", re.I)
firstname_lastname_pattern = re.compile(r"^(?P<firstname>.*?).*\s(?P<lastname>\S+)$", re.I)

book_title_pattern = re.compile(r"(?<=[-_–—])[\W\s]*(?P<book_title>[\w\s]+?)\s*(?=\d{4}|\(|\[|$)", re.I)
# partno_or_ch_match_pattern = re.compile(rf",?{_div}(?:part|ch(?:\.|apter))?{_div}\W*(?P<num1>\d+)(?:$|{_div}(?:of|-){_div}(?P<num2>\d+)\W*$)", re.I)
partno_or_ch_match_pattern2 = re.compile(rf"(?:(?:(?:(?<=\W)|^)p|P)[Aa]?[Rr]?[Tt]|C[Hh]?(?:[\. ]|[Aa][Pp][Tt][Ee][Rr])|[^A-Za-z0-9\n]+?)\W*(?P<num1>\d+)(?:.?(?:of|-|to).?(?P<num2>\d+))?[^\n]*$")
part_or_ch_match_words = re.compile(rf"(?:(?<=\W)|^){_div}(?:pa?r?t|ch(?:\.|apter)){_div}\d+.*$", re.I)
path_junk_pattern = re.compile(r"^[ \,.\)\}\]_-]*|[ \,.\)\}\]_-]*$", re.I)
path_garbage_pattern = re.compile(r"^[ \,.\)\}\]]*", re.I)
path_strip_l_t_alphanum_pattern = re.compile(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$", re.I)
roman_numeral_pattern = re.compile(r"((?:^|(?<=[\W_]))[IVXLCDM]+(?:$|(?=[\W_])))", re.I)
roman_strip_pattern = re.compile(r"(?<=\w)(?=[\W_.-])|(?<=[\W_.-])(?=\w)|(?<=[a-z])(?=[A-Z])")

year_pattern = re.compile(r"(?P<year>\d{4})", re.I)

common_str_pattern = re.compile(r"(^common_|_c(ommon)?$)")
startswith_num_pattern = re.compile(r"(?P<num>^\d+)")

multi_disc_pattern = re.compile(r"(?:^|(?<=[\W_-]))(dis[ck]|cd)(\b|\s|[_.-])*#?(\b|\s|[_.-])*(?:\b|[\W_-])*(?P<num>\d+)", re.I)
book_series_pattern = re.compile(r"(^\d+|(?:^|(?<=[\W_-]))(bo{0,2}k|vol(?:ume)?|#)(?:\b|[\W_-])*(?P<num>\d+)|(?<=[\W_-])Series.*/.+)", re.I)
multi_part_pattern = re.compile(r"(?:^|(?<=[\W_-]))(pa?r?t|ch(?:\.|apter))(?:\b|[\W_-])*(\d+)", re.I)
# fmt: on

S = TypeVar("S", bound=str | Path)


@dataclass
class romans:
    ones = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
    tens = ["X", "XX", "XXX", "XL", "L", "LX", "LXX", "LXXX", "XC"]

    @classmethod
    def is_roman_numeral(cls, s: str) -> bool:
        """Test input against all possible valid roman numerals from 1 to 99"""
        s = str(s).upper()
        for ten in cls.tens:
            for one in cls.ones:
                if s == ten + one or s == ten or s == one:
                    return True
        return False

    @classmethod
    def find_all(cls, s: str) -> list[str]:
        """Finds all possible valid roman numerals from 1 to 99 in a string"""
        possible_matches: list[str] = roman_numeral_pattern.findall(s)
        return [p for p in possible_matches if p and cls.is_roman_numeral(p)]

    @classmethod
    def strip(cls, s: str) -> str:
        """Strips roman numerals from a string"""

        # split on word boundaries, and any boundary between lowercase/uppercase or letter/non-letter
        split = roman_strip_pattern.split(s)
        return "".join([p for p in split if not cls.is_roman_numeral(p)])

    @classmethod
    def strip_from_list(cls, l: Iterable[S] | Generator[S, None, None]) -> list[S]:

        l = list(l)
        to_path = lambda x: Path(x) if isinstance(l[0], Path) else x
        return cast(list[S], [to_path(cls.strip(str(s))) for s in l])


if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook


def to_words(s: str) -> list[str]:
    return [w.strip() for w in re.split(r"[\s_.]", s) if w.strip()]


def swap_firstname_lastname(name: str) -> str:
    lastname = ""
    firstname = ""

    if name.count(",") > 1 or name.count(" ") == 0 or len(to_words(name)) > 4:
        # ignore false negatives
        return name

    m = lastname_firstname_pattern.match(name)

    if m:
        lastname = m.group("lastname")
        firstname = m.group("firstname")

    # If there is a given name, swap the first and last name and return it
    if firstname and lastname:
        return f"{firstname} {lastname}"
    else:
        # Otherwise, return the original name
        return name


def find_greatest_common_string(s: list[str]) -> str:
    if not s:
        return ""

    common_prefixes = set()

    for file1, file2 in combinations(s, 2):
        prefix = os.path.commonprefix([file1, file2])
        common_prefixes.add(prefix)

    valid_prefixes = [prefix for prefix in common_prefixes if any(f.startswith(prefix) for f in s)]

    return max(valid_prefixes, key=len, default="")


def contains_partno_or_ch(s: str, s2: str | None = None) -> bool:
    s_matches_part_number = partno_or_ch_match_pattern2.search(s)
    s_start_num = get_start_no(s)

    if not s2:
        # If there is no second to compare it to, we want to be conservative
        # and only return True if we don't think this is a series
        return bool(s_matches_part_number and not is_maybe_multiple_books_or_series(s))

    s2_matches_part_number = partno_or_ch_match_pattern2.search(s2)
    s2_start_num = get_start_no(s2)

    if s_start_num or s2_start_num and (s_start_num != s2_start_num):
        # If the two strings are maybe series, but the numbers don't match, they're parts
        return True

    return re_group(s_matches_part_number, "num1") != re_group(s2_matches_part_number, "num1")


def startswith_partno(s: str, s2: str | None = None) -> bool:
    if s2:
        first = get_start_no(s)
        second = get_start_no(s2)
        return bool(first >= 0 and second >= 0) and first == second
    return bool(get_start_no(s) >= 0)


def extract_path_info(book: "Audiobook", quiet: bool = False) -> "Audiobook":
    # FIXME: This is completely broken and doesn't work at all, more false positives than negatives.
    # Replace single occurrences of . with spaces
    from src.lib.cleaners import strip_part_number

    dir_author = swap_firstname_lastname(re_group(author_fs_pattern.search(book.basename), "author"))

    dir_title = re_group(book_title_pattern.search(book.basename), "book_title")
    dir_year = re_group(year_pattern.search(book.basename), "year")
    dir_narrator = parse_narrator(book.basename, "fs")

    # remove suffix/extension from files
    files = [f.stem for f in Path(book.inbox_dir).iterdir() if f.is_file()]

    # Get filename common text
    orig_file_name = find_greatest_common_string(files)

    orig_file_name = strip_part_number(orig_file_name)
    # TODO: dupe? Probably remove
    # orig_file_name = re.sub(r"(part|chapter|ch\.)\s*$", "", orig_file_name, flags=re.I)
    orig_file_name = orig_file_name.rstrip().rstrip(string.punctuation)

    # strip underscores
    orig_file_name = orig_file_name.replace("_", " ")

    # strip leading and trailing -._ spaces and punctuation
    orig_file_name = path_junk_pattern.sub("", orig_file_name)

    file_author = parse_author(orig_file_name, "fs")
    file_title = re_group(book_title_pattern.search(orig_file_name), "book_title")
    file_year = parse_year(orig_file_name)

    meta = {
        "author": dir_author,
        "narrator": dir_narrator,
        "year": dir_year,
        "title": dir_title,
    }

    for d, f, o in zip(
        [dir_author, dir_title, dir_year],
        [file_author, file_title, file_year],
        ["author", "title", "year"],
    ):
        if len(f) > len(d):
            print_debug(f"{o}: file name '{f}' is longer than dir name '{d}', prefer file name")
            meta[o] = f

    book.fs_author = meta["author"]
    book.fs_title = meta["title"]
    book.fs_year = meta["year"]
    book.fs_narrator = meta["narrator"]

    def strip_garbage_chars(path: str) -> str:
        try:
            return path_garbage_pattern.sub("", re.sub(path, "", book.basename, flags=re.I))
        except re.error as e:
            print_debug(f"Error calling strip_garbage_chars: {e}")
            return path

    # everything else in the dir name after removing author, title, year, and narrator
    for f, d in zip([file_author, file_title, file_year], [dir_author, dir_title, dir_year]):
        book.dir_extra_junk = strip_garbage_chars(d)
        book.file_extra_junk = strip_garbage_chars(f)

    book.orig_file_name = path_strip_l_t_alphanum_pattern.sub("", orig_file_name)

    return book


def get_romans_dict(*ss: str) -> dict[str, int]:

    found_roman_numerals = {}

    if len(ss) == 1 and isinstance(ss[0], list):
        ss = ss[0]  # type: ignore

    for s in ss:
        for m in romans.find_all(s):
            found_roman_numerals[m] = found_roman_numerals.get(m, 0) + 1

    return found_roman_numerals


def find_paths_with_romans(d: Path) -> dict[str, int]:
    """Makes a dictionary of all the different roman numerals found in the directory"""
    from src.lib.fs_utils import only_audio_files

    return get_romans_dict(*(str(f) for f in only_audio_files(d.rglob("*"))))


def count_distinct_romans(d: Path) -> int:
    """Counts the number of unique roman numerals in a directory, ignoring 'I' to avoid false positives"""
    return len([n for n in find_paths_with_romans(d).keys() if n != "I"])


def roman_numerals_affect_file_order(d: Path) -> bool:
    """Compares the order of files in a directory, both with and without roman numerals.

    Args:
        d (Path): directory to compare

    Returns:
        bool: True if the files are in the same order, False otherwise
    """
    files = isorted((Path(f).stem for f in d.rglob("*")))
    files_no_roman = romans.strip_from_list(files)
    return files_no_roman != isorted(files_no_roman)


@overload
def get_year_from_date(date: Any) -> str: ...
@overload
def get_year_from_date(date: Any, to_int: Literal[True] = True) -> int: ...
def get_year_from_date(date: Any, to_int: bool = False) -> str | int:
    y = re_group(re.search(r"\d{4}", str(date)), default="")
    return int(y) if y and to_int else y


def get_name_from_str(s: str, max_words=6) -> str:
    if len(to_words(s)) > max_words:
        s = " ".join(to_words(s)[:max_words])
    if s.count(","):
        # drop the second comma and anything after it
        s = ",".join(s.split(",")[:2])
    # remove parens and anything inside them
    s = re.sub(r"\(.*?\)", "", s)
    return s.strip()


def parse_names(s: str, target: NameParserTarget, *, fallback: str | None = None) -> AuthorNarrator:
    if fallback is None:
        fallback = s
    if not s or graphic_audio_pattern.search(s):
        return AuthorNarrator(fallback, fallback)
    author = s
    narrator = s
    if any([w for w in to_words(s)[:6] if "/" in w]):
        m = narrator_slash_pattern.search(s)
        author = re_group(m, "author")
        narrator = re_group(m, "narrator")

    match target:
        case "generic":
            author_pattern = author_generic_pattern
            narrator_pattern = narrator_generic_pattern
        case "fs":
            author_pattern = author_fs_pattern
            narrator_pattern = narrator_generic_pattern
        case "comment":
            author_pattern = author_comment_pattern
            narrator_pattern = narrator_comment_pattern

    # author_default = (
    #     default if not re_group(narrator_pattern.search(narrator), "narrator") else ""
    # )
    # narrator_default = (
    #     default if not re_group(author_pattern.search(author), "author") else ""
    # )

    author = re_group(author_pattern.search(author), "author", default=fallback).strip()
    narrator = re_group(narrator_pattern.search(narrator), "narrator", default=fallback).strip()

    if not author and not narrator:
        return AuthorNarrator(fallback, fallback)

    if author != narrator:
        if author and author in narrator:
            narrator = re.sub(author, "", narrator)
        elif narrator and narrator in author:
            author = re.sub(narrator, "", author)

    author = get_name_from_str(author)
    narrator = get_name_from_str(narrator)

    return AuthorNarrator(
        author=swap_firstname_lastname(author),
        # narrator=swap_firstname_lastname(narrator),
        narrator=narrator,
    )


def parse_author(s: str, target: NameParserTarget, *, fallback: str | None = None) -> str:
    return parse_names(s, target, fallback=fallback).author


def has_graphic_audio(s: str) -> bool:
    return bool(graphic_audio_pattern.search(s))


def parse_narrator(s: str, target: NameParserTarget, *, fallback: str | None = None) -> str:
    return parse_names(s, target, fallback=fallback).narrator or fallback or ""


def parse_year(s: str) -> str:
    return re_group(year_pattern.search(s), "year")


def get_title_partno_score(title_1: str, title_2: str, album_1: str, sortalbum_1: str) -> tuple[bool, int, bool]:
    """Returns a score for the likelihood that the title(s) indicate the part number of a multi-part book, e.g. "Part 01" or "The Martian Part 014. A positive score indicates a likely part #, negative indicates not a part #."""
    from src.lib.cleaners import strip_part_number

    score = 0
    t1_part = contains_partno_or_ch(title_1)
    t2_part = contains_partno_or_ch(title_2)
    t1 = get_numbers_in_string(title_1)
    t2 = get_numbers_in_string(title_2)
    al1 = get_numbers_in_string(album_1)
    sal1 = get_numbers_in_string(sortalbum_1)

    if len(t1) > len(al1):
        score += 1

    if len(t1) > len(sal1):
        score += 1

    if t1 != t2:
        score += 1
        if t1_part:
            score += 1
        if t2_part:
            score += 1
    else:
        # if the numbers in both titles match, it's likely that the number is part of the book's name
        score -= 1
        if not t1_part and not t2_part:
            score -= 2

    contains_only_part = strip_part_number(title_1) == "" and strip_part_number(title_2) == ""

    return score > 0, score, contains_only_part


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_series_no(s: str | Path) -> int:
    return int(re_group(book_series_pattern.search(str(s)), "num", default=-1))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_multiple_books_or_series(s: str | Path) -> bool:
    s = str(s)
    return not is_maybe_multi_disc(s) and bool(book_series_pattern.search(s))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_disc_no(s: str | Path) -> int:
    return int(re_group(multi_disc_pattern.search(str(s)), "num", default=-1))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_multi_disc(s: str | Path) -> bool:
    return get_disc_no(str(s)) > -1


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_part_no(s: str | Path) -> int:
    s = str(s)
    if not part_or_ch_match_words.search(s):
        return -1
    return int(re_group(partno_or_ch_match_pattern2.search(s), "num1", default=-1))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_start_no(s: str | Path) -> int:
    return int(re_group(startswith_num_pattern.search(str(s)), "num", default=-1))


def are_nums_sequential(nums: list[int], *, sort=False, skips_ok=False) -> bool:
    if sort:
        nums = sorted(nums)
    if not skips_ok:
        return all(nums[i] == nums[i - 1] + 1 for i in range(1, len(nums)))
    # otherwise just check if they're in ascending order
    return nums == list(range(nums[0], nums[-1] + 1))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_multi_part(s: str) -> bool:
    return (
        not is_maybe_multi_disc(s) and not is_maybe_multiple_books_or_series(s) and bool(multi_part_pattern.search(s))
    )


# def determine_structure(
#     path: Path, *, adjacent_paths: list[Path] = [], root_dir: Path | None = None
# ) -> str:

#     if path.is_file():
#         return "standalone_file"

#     if not root_dir:
#         root_dir = path if path.is_dir() else path.parent

#     tree = get_path_tree(path)

#     dir_contents = ls_path_tree(tree)
#     if len(dir_contents) == 0:
#         return "empty"

#     sub_dirs = ls_path_tree(tree, only_dirs=True)
#     audio_files = ls_path_tree(tree, only_files=True)
#     if not sub_dirs:
#         if len(audio_files) == 1:
#             return "standalone_file"
#         elif len(audio_files) > 1:
#             return "flat"

#     # Check if there are audio files only in a single subdirectory
#     subdirs_with_audio_files = [
#         (d, f)
#         for d, f in [(d, ls_path_tree(d, only_files=True)) for d in sub_dirs]
#         if len(f) > 0
#     ]

#     if len(subdirs_with_audio_files) == 1:
#         files = subdirs_with_audio_files[0][1]
#         if len(files) > 1:
#             return "flat_nested"
#         return "standalone_nested"

#     if len(subdirs_with_audio_files) > 1:
#         # If all of the subdirs appear to contain a disc number,
#         # it's likely a multi-disc structure
#         if _maybe_multi_disc := all(
#             is_maybe_multi_disc(d.name) for d, _ in subdirs_with_audio_files
#         ):
#             return "multi_disc"

#         # If all of the subdirs or at least one of their files appear to
#         # contain a series or book number, it's likely a series structure

#         multi_book_nested = False
#         subdirs_maybe_series = [
#             (d.name, is_maybe_multiple_books_or_series(d.name))
#             for d, _ in subdirs_with_audio_files
#         ]
#         files_maybe_series = {
#             d.name: [(f.name, is_maybe_multiple_books_or_series(f.name)) for f in files]
#             for d, files in subdirs_with_audio_files
#         }
#         if _maybe_series := all(
#             [
#                 all((x, all([y for _f, y in files_maybe_series[d]])))
#                 for d, x in subdirs_maybe_series
#             ]
#         ):
#             return "series"

#         if _multi_book_nested := any(
#             [
#                 any([y for _f, y in files_maybe_series[d]])
#                 for d, _x in subdirs_maybe_series
#             ]
#         ):
#             return "multi_book_series"

#     if path.exists():
#         adjacent_paths = sorted(
#             [
#                 p.relative_to(root_dir)
#                 for p in path.parent.iterdir()
#                 if p != path and (p.is_dir() or is_audio_file(p))
#             ]
#         )

#     rel_parent = path.relative_to(root_dir).parent
#     # if it's a standalone (no adjacent paths) we can do some simple things:
#     if not adjacent_paths:
#         if is_maybe_multi_disc(str(path)):
#             # This can happen if the book is a multi-disc book split into multiple folders, e.g.:
#             #   - The Martian
#             #     - Disc 1
#             #       - Chapters 1-14.mp3
#             #     - Disc 2
#             #       - Chapters 15-28.mp3
#             # but is pretty rare.
#             return "multi_disc"

#         # Otherwise, there's a very good chance this is a standalone book.
#         return "standalone_file"

#     # If there are adjacent paths, we need to look at the paths to determine the structure.
#     # We'll start by checking if the paths are all in the same folder.
#     # If they are, we can assume it's a flat structure.
#     if all(p.parent == adjacent_paths[0].parent for p in adjacent_paths):
#         return "flat"

#     # If the parents are different, we should look for multi-disc or series structures next.
#     # If it's a multi-disc, we don't want to get a false-positive for a series structure.
#     # If more than 50% of the adjacent paths are multi-disc, we'll assume it's a multi-disc structure.
#     all_paths = [path, *adjacent_paths]
#     if sum(is_maybe_multi_disc(p.name) for p in all_paths) > len(all_paths) / 2:
#         return "multi_disc"

#     # If there are numbers in the path, it could be a series. We should
#     # check the parent first to see if it's a series_parent.

#     contig_nums = [
#         get_numbers_contiguous(path.name),
#         *[get_numbers_contiguous(p.name) for p in adjacent_paths if p.is_dir()],
#     ]

#     parent_is_maybe_series = any(
#         is_maybe_multiple_books_or_series(d.name) for d in dir_contents
#     )

#     if any(is_maybe_multiple_books_or_series(p.name) for p in all_paths):
#         return "series"

#     raise ValueError("Could not determine file structure")

#
