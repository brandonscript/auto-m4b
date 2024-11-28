import os
import re
import string
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, cast, Literal, overload, TYPE_CHECKING, TypeVar

import spacy
from spacy.matcher import Matcher
from spacy.ml import Doc

nlp = spacy.load("en_core_web_sm")
matcher = Matcher(nlp.vocab)
matcher.add("PERSON", [[{"IS_ALPHA": True}]])
matcher.add("WORK_OF_ART", [[{"IS_ALPHA": True}]])
matcher.add("PRODUCT", [[{"IS_ALPHA": True}]])
matcher.add("EVENT", [[{"IS_ALPHA": True}]])
matcher.add("ORG", [[{"IS_ALPHA": True}]])

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


def to_words(s: str, *, sep=r"[\s_.]") -> list[str]:
    return [w.strip() for w in re.split(sep, s) if w.strip()]


def strip_leading_nums_and_punct(s: str) -> str:
    return re.sub(r"^\d+[\W_]*", "", s)


def strip_symbols_and_nums(s: str) -> str:
    """Strips all non-alphanumeric characters from a string except those commonly found in names"""
    exceptions = r"'.-"

    # Strip {space}-{space} instances, since hyphentated names don't have spaces around the hyphen
    s = re.sub(r" - ", "", s)

    # Strip numbers
    s = re.sub(r"\d", "", s)

    # Make sure we don't strip out diacritics and handle exceptions
    return re.sub(rf"[^\w\s{exceptions}]", "", s).strip()


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
    s_start_num = get_start_num(s)

    if not s2:
        # If there is no second to compare it to, we want to be conservative
        # and only return True if we don't think this is a series
        return bool(s_matches_part_number and not is_maybe_multiple_books_or_series(s))

    s2_matches_part_number = partno_or_ch_match_pattern2.search(s2)
    s2_start_num = get_start_num(s2)

    if s_start_num or s2_start_num and (s_start_num != s2_start_num):
        # If the two strings are maybe series, but the numbers don't match, they're parts
        return True

    return re_group(s_matches_part_number, "num1") != re_group(s2_matches_part_number, "num1")


def startswith_partno(s: str, s2: str | None = None) -> bool:
    if s2:
        first = get_start_num(s)
        second = get_start_num(s2)
        return bool(first >= 0 and second >= 0) and first == second
    return bool(get_start_num(s) >= 0)


def nlp_get_names(s: str) -> list[str]:
    s = re.sub(r"[-_]", ",", strip_leading_nums_and_punct(s))
    doc: Doc = nlp(s)
    return [ent.text for ent in doc.ents if ent.label_ == "PERSON"]


def nlp_get_titles(s: str) -> list[str]:
    s = re.sub(r"[-_]", ",", strip_leading_nums_and_punct(s))
    doc: Doc = nlp(s)
    return [ent.text for ent in doc.ents if ent.label_ in ["WORK_OF_ART", "PRODUCT", "EVENT", "ORG"]]


def extract_path_info(book: "Audiobook", quiet: bool = False) -> "Audiobook":
    # FIXME: This is completely broken and doesn't work at all, more false positives than negatives.
    # Replace single occurrences of . with spaces
    from src.lib.cleaners import strip_part_number

    if (
        parse_author(book.basename, "fs", fallback="") == "Matthew"
        or parse_author(book.basename, "fs", fallback="") == "Alexandre"
    ):
        ...

    dir_title = re_group(book_title_pattern.search(book.basename), "book_title")
    dir_author = parse_author(book.basename, "fs", fallback="")
    dir_nlp_names = nlp_get_names(book.basename)
    dir_nlp_titles = nlp_get_titles(book.basename)
    dir_year = re_group(year_pattern.search(book.basename), "year")
    dir_narrator = parse_narrator(book.basename, "fs", fallback="")

    # remove suffix/extension from files
    files = [f.path.stem for f in book.tree.files_recursive]
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

    file_title = re_group(book_title_pattern.search(orig_file_name), "book_title")
    file_author = parse_author(orig_file_name, "fs", fallback="")
    file_nlp_titles = nlp_get_titles(orig_file_name)
    file_nlp_names = nlp_get_names(orig_file_name)
    file_year = parse_year(orig_file_name)

    meta = {
        "author": dir_author,
        "narrator": dir_narrator,
        "year": dir_year,
        "title": dir_title,
    }

    longest_author = max([dir_author, file_author, *dir_nlp_names, *file_nlp_names], key=len)
    longest_title = max([dir_title, file_title, *dir_nlp_titles, *file_nlp_titles], key=len)
    longest_year = max([dir_year, file_year], key=len)

    if longest_author in longest_title:
        longest_author = ""
    if meta["narrator"] in longest_title:
        meta["narrator"] = ""

    for k, v in zip(
        ["author", "title", "year"],
        [longest_author, longest_title, longest_year],
    ):
        if v:
            print_debug(f"parsed {k} from fs: '{v}'")
            meta[k] = v

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

    def _split(s: str, seps: list[str]) -> list[str]:
        """
        Splits a string at any non-alphanumeric character preceding any of the separators,
        ensuring that the separator is included at the start of the following substring.

        e.g.
        Input: "Alexandre Dumas The Count of Monte Cristo Alexandre Dumas The Count of Monte Cristo"
            with ["the", "a", "of"]
        Output: ['Alexandre Dumas', 'The Count', 'of Monte Cristo Alexandre Dumas', 'The Count', 'of Monte Cristo']

        Args:
            s (str): The input string to split.
            seps (list[str]): A list of case-insensitive separators used to split the string.

        Returns:
            list[str]: The list of substrings split by the separators.
        """
        # Escape and join all separators into a regex pattern, case-insensitive
        escaped_seps = "|".join(re.escape(sep) for sep in seps)

        # Use re.split to split the string and keep the separators as part of the output
        split_parts = [
            p.strip() for p in re.split(rf"(?:\b|_)(?=(?:{escaped_seps})(?=(?:\b|_)))", s, flags=re.I) if p.strip()
        ]

        # Combine separator tokens with the following substring
        result = []
        i = 0
        while i < len(split_parts):
            if i + 1 < len(split_parts) and re.match(rf"^{escaped_seps}$", split_parts[i], re.I):  # Separator found
                result.append(split_parts[i] + split_parts[i + 1])  # Prefix separator to the next part
                i += 2  # Skip the next part (already processed)
            else:
                result.append(split_parts[i])
                i += 1

        # Filter out any empty strings from the result
        return [part for part in result if part.strip()]

    # split on articles and conjunctions, remove any empty strings
    candidates = [c for c in _split(s, ["the", "and", "or", "of", "a"]) if c]

    # get the first candidate
    s = candidates[0] if candidates else s

    return s.strip()


def get_nltk_names(s: str) -> list[tuple[str, str]]:
    from nltk import ne_chunk, pos_tag, word_tokenize
    from nltk.tree import Tree

    # Tokenize and process with NLTK
    tokens = word_tokenize(s)
    nltk_results = ne_chunk(pos_tag(tokens))
    names = []
    current_name = []
    num_person_chunks = len([r for r in nltk_results if isinstance(r, Tree) and r.label() == "PERSON"])
    last_was_person = False

    for i, nltk_result in enumerate(nltk_results):
        label = nltk_result.label() if isinstance(nltk_result, Tree) else None
        if isinstance(nltk_result, Tree) and label in ["PERSON", "ORGANIZATION", "NOUN"]:
            # Collect tokens that are part of a PERSON entity
            if label == "PERSON" or (label != "PERSON" and last_was_person):
                current_name.append(" ".join(leaf[0] for leaf in nltk_result.leaves()))
            last_was_person: bool = label == "PERSON"
        elif last_was_person and isinstance(nltk_result, tuple) and nltk_result[1] in ["NNP", "NN"]:
            # Append the last collected name if we hit a non-PERSON chunk
            current_name.append(nltk_result[0])
        elif (
            # fmt: off
            i > 0 and i < len(nltk_results) - 1 and
            isinstance(nltk_results[i - 1], Tree) and nltk_results[i - 1].label() == "PERSON" and
            isinstance(nltk_results[i + 1], Tree) and nltk_results[i + 1].label() == "PERSON" and
            nltk_result[1] in ["NNP", "NN"] and (s := str(nltk_result[0])) and (s.endswith(".") or (len(s) == 1 and re.match(r'[A-Z]', s)))
            # fmt: on
        ):
            # Treat abbreviations as part of the current name
            current_name.append(nltk_result[0])
            last_was_person: bool = True
        else:
            # Append completed name if we hit a non-PERSON chunk
            if current_name:
                names.append(("PERSON", " ".join(current_name)))
                current_name = []
            last_was_person = False

    # Append the last collected name (if any)
    if num_person_chunks > 0 and current_name:
        names.append(("PERSON", " ".join(current_name)))

    # Handle short string edge case
    if len(tokens) <= 3 and not names:  # Assume short strings might be a name
        return [("PERSON", " ".join(tokens))]

    return names


def percent_human_name_chars_in_str(s: str) -> float:
    """Returns the percentage (0.0 - 1.0) of characters in a string that are part of a human name"""
    if not s:
        return 0.0
    human_name_chars = sum(1 for c in s if c.isalpha())
    return human_name_chars / len(s)


def parse_names(s: str, target: NameParserTarget, *, fallback: str | None = None) -> AuthorNarrator:
    if fallback is None:
        fallback = s
    fallback = strip_symbols_and_nums(fallback)
    if not s or graphic_audio_pattern.search(s):
        return AuthorNarrator(fallback, fallback)
    # author_ok = percent_human_name_chars_in_str(s) > 0.7
    # narrator_ok = author_ok

    author = strip_leading_nums_and_punct(s)
    narrator = strip_leading_nums_and_punct(s)

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

    author_ok = percent_human_name_chars_in_str(author) > 0.7
    narrator_ok = percent_human_name_chars_in_str(narrator) > 0.7

    author = " ".join(to_words(strip_symbols_and_nums(author), sep=r"\s+")[:6])
    narrator = " ".join(to_words(strip_symbols_and_nums(narrator), sep=r"\s+")[:6])

    if not any([author, narrator]):
        return AuthorNarrator(fallback, fallback)

    if author != narrator:
        _author = author
        _narrator = narrator
        if author_ok and author and (author in narrator):
            _narrator = re.sub(author, "", narrator)
        if narrator_ok and narrator and (narrator in author):
            _author = re.sub(narrator, "", author)
        author = _author
        narrator = _narrator

    # use nltk to look for names
    if author_nltk := get_nltk_names(author):
        author = max(author_nltk, key=lambda x: len(x[1]))[1]
        author_ok = True
    else:
        author_ok = False
    if narrator_nltk := get_nltk_names(narrator):
        narrator = max(narrator_nltk, key=lambda x: len(x[1]))[1]
        narrator_ok = True
    else:
        narrator_ok = False

    author = get_name_from_str(author) if author_ok else fallback
    narrator = get_name_from_str(narrator) if narrator_ok else fallback

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


def try_parse_num(s: str, fallback: Any = None) -> int | float | None:
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return fallback


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
def get_series_num(s: str | Path) -> int:
    return int(re_group(book_series_pattern.search(str(s)), "num", default=-1))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_multiple_books_or_series(s: str | Path) -> bool:
    s = str(s)
    return not is_maybe_multi_disc(s) and bool(book_series_pattern.search(s))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_disc_num(s: str | Path) -> int:
    return int(re_group(multi_disc_pattern.search(str(s)), "num", default=-1))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_multi_disc(s: str | Path) -> bool:
    return get_disc_num(str(s)) > -1


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_part_num(s: str | Path) -> int:
    s = str(s)
    if not part_or_ch_match_words.search(s):
        return -1
    return int(re_group(partno_or_ch_match_pattern2.search(s), "num1", default=-1))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_multi_part(s: str) -> bool:
    return (
        not is_maybe_multi_disc(s) and not is_maybe_multiple_books_or_series(s) and bool(multi_part_pattern.search(s))
    )


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_start_num(s: str | Path) -> int:
    return int(re_group(startswith_num_pattern.search(str(s).lstrip()), "num", default=-1))


def are_nums_sequential(nums: list[int], *, sort=False, skips_ok=False) -> bool:
    if sort:
        nums = sorted(nums)
    if not skips_ok:
        return all(nums[i] == nums[i - 1] + 1 for i in range(1, len(nums)))
    # otherwise just check if they're in ascending order
    return nums == list(range(nums[0], nums[-1] + 1))


def get_all_nums_in_string(s: str) -> list[tuple[int | float, int]]:
    """Finds all numbers (int and float) in a string, and returns a list of tuples with the number and its position in the string"""
    return list(
        filter(
            lambda x: x[0] is not None,
            [(try_parse_num(m.group()), m.start()) for m in rex.finditer(r"\d+(?:\.\d+)?", s) if m],
        )
    )  # type: ignore
