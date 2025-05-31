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
from nltk import pos_tag, word_tokenize
from spacy.ml import Doc

from src.lib.misc import (
    any_in,
    get_numbers_in_string,
    isorted,
    re_group,
)
from src.lib.nlp import english_words, inflect, nlp
from src.lib.patterns import *
from src.lib.patterns import book_series_pattern, multi_disc_pattern
from src.lib.term import print_debug
from src.lib.typing import AuthorNarrator, MEMO_TTL, NameParserTarget

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook


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

    @classmethod
    def to_int(cls, s: str | int) -> int:
        """Converts a roman numeral string to an integer. If s is an integer, returns it as-is.
        If no roman numeral is found, returns -1."""
        if isinstance(s, int):
            return s
        s = str(s).strip()
        if _is_numeric := re.match(r"^\d+$", s):
            return int(s)
        codex = {
            "I": 1,
            "V": 5,
            "X": 10,
            "L": 50,
            "C": 100,
            "D": 500,
            "M": 1000,
            "IV": 4,
            "IX": 9,
            "XL": 40,
            "XC": 90,
            "CD": 400,
            "CM": 900,
        }
        roman = m[0] if (m := romans.find_all(s)) else None

        if not roman:
            return -1

        if len(m) > 1:
            print_debug(f"[romans.to_int]: found multiple roman numerals in {s}: {m}")

        roman = roman.upper()
        i = 0
        num = 0
        while i < len(roman):
            if i + 1 < len(roman) and roman[i : i + 2] in codex:
                num += codex[roman[i : i + 2]]
                i += 2
            else:
                num += codex[roman[i]]
                i += 1
        return num


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
        if not file1 or not file2:
            continue
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
        return bool(s_matches_part_number and not is_maybe_series_book(s))

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


# def nlp_get_names(s: str) -> list[str]:
#     s = re.sub(r"[-_]", ",", strip_leading_nums_and_punct(s))
#     doc: Doc = nlp(s)
#     return [ent.text for ent in doc.ents if ent.label_ == "PERSON"]


def nlp_get_titles(s: str) -> list[str]:
    s = re.sub(r"[-_]", ",", strip_leading_nums_and_punct(s))
    doc: Doc = nlp(s)
    objects = [ent.text for ent in doc.ents if ent.label_ in ["WORK_OF_ART", "PRODUCT", "EVENT", "ORG"]]
    people = [ent.text for ent in doc.ents if ent.label_ == "PERSON"]
    # Remove people from the string
    no_people = re.sub(r"\b" + "|".join(people) + r"\b", "", s)
    # Clean up the string by:
    # 1. Replace multiple spaces with a single space
    # 2. Strip leading/trailing non-alphanumeric characters (preserving diacritics)
    no_people = re.sub(r"\s+", " ", no_people)  # Normalize spaces
    # Strip leading/trailing non-alphanumeric chars while preserving diacritics
    no_people = leading_trailing_non_alphanum_pattern.sub("", no_people)
    return [no_people, *objects]


def extract_path_info(book: "Audiobook", quiet: bool = False) -> "Audiobook":
    from src.lib.cleaners import strip_part_number

    dir_title = re_group(book_title_pattern.search(book.basename), "book_title")
    dir_author = parse_author(book.basename, "fs", fallback="")
    # dir_nlp_names = nlp_get_names(book.basename)
    dir_nlp_titles = nlp_get_titles(book.basename)
    dir_year = re_group(year_pattern.search(book.basename), "year")
    dir_narrator = parse_narrator(book.basename, "fs", fallback="")

    # remove suffix/extension from files
    files = [f.path.stem for f in book.tree.files_recursive]
    # Get filename common text
    orig_file_name = find_greatest_common_string(files)

    orig_file_name = strip_part_number(orig_file_name)
    orig_file_name = orig_file_name.rstrip().rstrip(string.punctuation)

    # strip underscores
    orig_file_name = orig_file_name.replace("_", " ")

    # strip leading and trailing -._ spaces and punctuation
    orig_file_name = path_junk_pattern.sub("", orig_file_name)

    file_title = re_group(book_title_pattern.search(orig_file_name), "book_title")
    file_author = parse_author(orig_file_name, "fs", fallback="")
    file_nlp_titles = nlp_get_titles(orig_file_name)
    # file_nlp_names = nlp_get_names(orig_file_name)
    file_year = parse_year(orig_file_name)

    author_candidates: list[tuple[str, float]] = []
    if dir_author and (n := get_nltk_names(dir_author)):
        author_candidates.extend(n)
    if file_author and (n := get_nltk_names(file_author)):
        author_candidates.extend(n)
    author_candidates = sorted(author_candidates, key=lambda x: x[1], reverse=True)
    best_author = next(iter(author_candidates), ("", 0))[0]

    narrator_candidates: list[tuple[str, float]] = n if dir_narrator and (n := get_nltk_names(dir_narrator)) else []
    narrator_candidates = sorted(narrator_candidates, key=lambda x: x[1], reverse=True)
    best_narrator = next(iter(narrator_candidates), ("", 0))[0]

    longest_title = max([dir_title, file_title, *dir_nlp_titles, *file_nlp_titles], key=len)
    longest_year = max([dir_year, file_year], key=len)

    meta = {
        "author": best_author,
        "narrator": best_narrator,
        "year": dir_year,
        "title": dir_title,
    }

    if best_author in longest_title:
        best_author = ""
    if meta["narrator"] in longest_title:
        meta["narrator"] = ""

    for k, v in zip(
        ["author", "title", "year"],
        [best_author, longest_title, longest_year],
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


def is_generic_word(word):
    # Load English words from nltk corpus
    return word.lower() in english_words


def get_singular(word):
    return word if not inflect.singular_noun(word) else inflect.singular_noun(word)


# Basic name scoring fallback
def heuristic_score(name: str) -> float:
    tokens = word_tokenize(name)

    if not tokens:
        return 0.0

    tags = pos_tag(tokens)

    # Score based on heuristics
    score = 0

    # Create an increment based on the number of words
    incr = max(0.1, 1.0 / len(tokens))

    score += sum(incr for _, tag in tags if tag == "NNP")  # Reward proper nouns
    # score += sum(1 for token in tokens if token.lower() in COMMON_NAMES)  # Reward known names
    score -= sum(incr for token in tokens if is_generic_word(get_singular(token)))  # Penalize generic words
    score -= abs(len(tokens) - 2) * incr  # Penalize names that aren't 2-3 tokens long
    return min(9.0, max(0.0, score))  # Ensure score is non-negative, capped at 9.0


def score_name_candidates(candidates: list[tuple[str, str]]) -> dict[str, float]:
    scores = {}
    for _label, name in candidates:
        doc = nlp(name)

        # Check if spaCy detects it as a PERSON entity
        entity_score = 0
        for ent in doc.ents:
            if ent.label_ == "PERSON" and ent.text == name:
                entity_score = 1.0  # High confidence if spaCy recognizes it

        # Fall back on heuristics if no entity detected
        if entity_score == 0:
            entity_score = heuristic_score(name)

        scores[name] = entity_score
    return dict(sorted(scores.items(), key=lambda item: item[1], reverse=True))


def get_nltk_names(s: str) -> list[tuple[str, float]]:
    from nltk import ne_chunk, pos_tag, word_tokenize
    from nltk.tree import Tree

    # Tokenize and process with NLTK
    tokens = word_tokenize(s)
    nltk_results = ne_chunk(pos_tag(tokens))
    names = [("PERSON", x[0]) for x in get_nltk_names(swap_firstname_lastname(s).replace(",", " "))] if "," in s else []
    current_name = []
    num_person_chunks = len([r for r in nltk_results if isinstance(r, Tree) and r.label() == "PERSON"])
    last_was_person = False

    def _end_name():
        nonlocal current_name, names, last_was_person
        if current_name:
            names.append(("PERSON", " ".join(current_name)))
            current_name = []
        last_was_person = False

    skip = False
    for i, nltk_result in enumerate(nltk_results):
        if skip:
            skip = False
            continue
        label = nltk_result.label() if isinstance(nltk_result, Tree) else None
        has_prev = i > 0
        has_next = has_prev and i < len(nltk_results) - 1
        prev_tree = p if has_prev and (p := nltk_results[i - 1]) and isinstance(p, Tree) else None
        nltk_tree = cast(Tree, nltk_result) if isinstance(nltk_result, Tree) else None
        next_tree = n if has_next and (n := nltk_results[i + 1]) and isinstance(n, Tree) else None
        (match, catg) = cast(tuple[str, str], nltk_result) if isinstance(nltk_result, tuple) else (None, None)
        (next_match, _) = (
            cast(tuple[str, str], n)
            if has_next and (n := nltk_results[i + 1]) and isinstance(n, tuple)
            else (None, None)
        )
        catg = (
            catg
            if catg
            else ("NNP" if nltk_tree and any_in([leaf[1] for leaf in nltk_tree.leaves()], ["NNP", "NN"]) else None)  # type: ignore
        )
        last_was_person_tree = bool(prev_tree and prev_tree.label() == "PERSON")
        next_is_person_tree = bool(next_tree and next_tree.label() == "PERSON")
        curr_label_is_maybe_person = bool(
            label and label in ["PERSON", "ORGANIZATION", "NOUN"] or (label != "PERSON" and last_was_person_tree)
        )
        curr_is_abbr_letters = bool(match and abbreviated_names_pattern.match(match))
        if _match_is_only_nonalpha := bool(match and only_non_alphanum_pattern.match(match)):
            _end_name()
            continue

        curr_is_noun = bool(catg and catg in ["NNP", "NN"] and match)
        if nltk_tree and curr_label_is_maybe_person:
            # Collect tokens that are part of a PERSON entity
            if label == "PERSON" or (label != "PERSON" and last_was_person):
                current_name.append(" ".join(leaf[0] for leaf in nltk_tree.leaves()))  # type: ignore
            last_was_person: bool = label == "PERSON"
        elif (
            (last_was_person_tree and next_is_person_tree) or (last_was_person and curr_is_noun) or curr_is_abbr_letters
        ):
            # Abbreviations are part of the current name, or
            # if prev and next are both PERSON, or
            # if the current token is a noun and the last token was a PERSON
            if curr_is_abbr_letters and next_match == ".":
                match = f"{match}."
                skip = True
            current_name.append(match)
            last_was_person: bool = True
        else:
            # Append completed name if we hit a non-PERSON chunk
            _end_name()

    # Append the last collected name (if any)
    if num_person_chunks > 0 and current_name:
        names.append(("PERSON", " ".join(current_name)))

    # Handle short string edge case
    if len(tokens) <= 3 and not names:  # Assume short strings might be a name
        names = [("PERSON", " ".join(tokens))]

    # If we have multiple PERSON entities, score them and return the highest-scoring one
    results = [(k, v) for k, v in score_name_candidates(names).items()]
    if len(names) > 1:

        # Remove any results from the names list that are a subset of another result
        # e.g., if we get ("Andrea Smith", "Andrea") and ("Andrea Smith", "Smith"), we only want to keep the former
        return list(
            filter(lambda x: not any(x[0] in n[0] for n in results if x != n), results),
        )

    return results


def percent_human_name_chars_in_str(s: str) -> float:
    """Returns the percentage (0.0 - 1.0) of characters in a string that are part of a human name"""
    if not s:
        return 0.0
    human_name_chars = sum(1 for c in s if c.isalpha())
    return human_name_chars / len(s)


@cachetools.func.ttl_cache(maxsize=128, ttl=MEMO_TTL)
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

    # author_ok = percent_human_name_chars_in_str(author) > 0.7
    # narrator_ok = percent_human_name_chars_in_str(narrator) > 0.7

    # author = " ".join(to_words(strip_symbols_and_nums(author), sep=r"\s+")[:6])
    # narrator = " ".join(to_words(strip_symbols_and_nums(narrator), sep=r"\s+")[:6])

    # if not any([author, narrator]):
    #     return AuthorNarrator(fallback, fallback)

    if author != narrator:
        _author = author
        _narrator = narrator
        if author and (author in narrator):
            _narrator = re.sub(author, "", narrator)
        if narrator and (narrator in author):
            _author = re.sub(narrator, "", author)
        author = _author
        narrator = _narrator

    nltk_s = next((n for (n, score) in get_nltk_names(s) if score > 0), None)
    nltk_author = None if not author else next((n for (n, score) in get_nltk_names(author) if score > 0.7), None)
    nltk_narrator = None if not narrator else next((n for (n, score) in get_nltk_names(narrator) if score > 0.7), None)

    if nltk_s and (not fallback or len(nltk_s) > len(fallback)):
        fallback = nltk_s

    author = nltk_author if nltk_author else (get_name_from_str(author) or fallback)
    narrator = nltk_narrator if nltk_narrator else (get_name_from_str(narrator) or fallback)

    if all((is_generic_word(a) for a in to_words(author))):
        author = fallback

    if all((is_generic_word(n) for n in to_words(narrator))):
        narrator = fallback

    return AuthorNarrator(author=author, narrator=narrator)


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


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_series_parent(s: str | Path) -> bool:
    from src.lib.misc import is_gt_75mb, truthiness

    if Path(s).is_file():
        return False

    series_book_children = 0.0
    if Path(s).is_dir():
        series_book_children = truthiness(
            [is_maybe_series_book(c.name) and (c.is_dir() or is_gt_75mb(c.stat().st_size)) for c in Path(s).iterdir()]
        )
    series_in_name = bool(series_parent_pattern.search(str(s)))
    return not is_maybe_multi_disc(s) and (series_book_children > 0.5 or series_in_name)


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_series_book(s: str | Path) -> bool:
    s = str(s)
    return not is_maybe_multi_disc(s) and bool(book_series_pattern.search(s))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_disc_num(s: str | Path) -> int:
    return int(re_group(multi_disc_pattern.search(str(s)), "num", default=-1))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_multi_disc(s: str | Path) -> bool:
    return get_disc_num(str(s)) > -1


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def is_maybe_multi_part(s: str) -> bool:
    return not is_maybe_multi_disc(s) and not is_maybe_series_book(s) and bool(multi_part_pattern.search(s))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_start_num(s: str | Path) -> int:
    return int(re_group(startswith_num_pattern.search(str(s).lstrip()), "num", default=-1))


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
