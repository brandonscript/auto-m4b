import os
import pickle
import re
import sqlite3
import string
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from itertools import combinations, zip_longest
from pathlib import Path
from typing import Any, cast, Literal, overload, TYPE_CHECKING, TypeVar

import cachetools
import cachetools.func
from nltk import pos_tag, word_tokenize

from lib import nlp
from lib.cleaners import clean_name_abbreviations
from lib.ol_lookup import open_library_lookup_author
from src.lib.misc import (
    get_numbers_in_string,
    isorted,
    re_group,
)
from src.lib.nlp import (
    english_words,
    inflect,
    nlp,
    nlp_trf,
    restore_original_name,
    squash_nlp_results,
    squash_trf_results,
)
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


def strip_symbols_and_nums(s: str, *, exceptions: str = r"'.-") -> str:
    """Strips all non-alphanumeric characters from a string except those commonly found in names"""

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


def swap_firstname_lastname_in_long(s: str) -> str:
    """Looks for name-like strings and swaps the first and last names as it finds them.
    Splits on strong word boundaries like <space><dash><space>, <colon>, <semicolon>, <em- and emdash>, and brackets.
    """
    split = re.split(r"(\s+[-–—_]\s+|[:;()\[\]{}<>]|(?<=[a-z]\.))", s)
    if len(split) < 2:
        return swap_firstname_lastname(s)
    for i, w in enumerate(split):
        split[i] = swap_firstname_lastname(w)
    return "".join(split)


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
    if not s:
        return False
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


def extract_path_info(book: "Audiobook", console: bool = False) -> "Audiobook":
    from src.lib.cleaners import strip_part_number

    dir_title = re_group(book_title_pattern.search(book.basename), "book_title")
    dir_author = parse_author(book.basename, "fs", fallback="")
    dir_nlp_people, dir_nlp_titles = spaCy_extract(book.basename)
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
    file_nlp_people, file_nlp_titles = spaCy_extract(orig_file_name)
    file_year = parse_year(orig_file_name)

    author_candidates: list[tuple[str, str, float]] = [*dir_nlp_people, *file_nlp_people]
    if dir_author and (n := get_nlp_names(dir_author)):
        author_candidates.extend(n)
    if file_author and (n := get_nlp_names(file_author)):
        author_candidates.extend(n)
    author_candidates = sorted(author_candidates, key=lambda x: x[2], reverse=True)
    best_author = next(iter(author_candidates), ("", "UNKNOWN", 0))[0]

    narrator_candidates: list[tuple[str, str, float]] = n if dir_narrator and (n := get_nlp_names(dir_narrator)) else []
    narrator_candidates = sorted(narrator_candidates, key=lambda x: x[2], reverse=True)
    best_narrator = next(iter(narrator_candidates), ("", "UNKNOWN", 0))[0]

    dir_nlp_titles_n = [t for (t, _, _) in dir_nlp_titles]
    file_nlp_titles_n = [t for (t, _, _) in file_nlp_titles]

    longest_title = max([dir_title, file_title, *dir_nlp_titles_n, *file_nlp_titles_n], key=len)
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


def lookup_and_score_names(candidates: list[tuple[str, str, float]]) -> list[tuple[str, str, float]]:
    scores = {}
    for name, label, existing_score in candidates:
        entity_score = existing_score if existing_score is not None else 0.0
        entity_label = label

        # Count the number of times the name appears in candidates
        name_count = sum(1 for _, _, s in candidates if s == existing_score)

        # Check if spaCy detects it as a PERSON entity
        if not label.endswith("SPACY"):
            doc = nlp(name)
            for ent in doc.ents:
                if ent.label_.startswith("PER") and ent.text == name:
                    entity_score = (
                        existing_score if existing_score is not None else 0.5
                    )  # High confidence if spaCy recognizes it too

        # Fall back on heuristics if no entity detected
        if h_score := heuristic_score(name):
            entity_score += h_score * max(0.2, entity_score)

        # if label.startswith("PER"):
        #     entity_score += 0.25

        lookups = [
            open_library_lookup_author(name, method="score"),
            open_library_lookup_author(name, method="similarity"),
        ]
        for lookup in lookups:
            if lookup and (ol_score := lookup.score()) is not None:
                if ol_score == 1.0:
                    entity_score = max(entity_score, 1.0)
                    entity_label = "AUTHOR"
                elif ol_score > 0:
                    entity_score = (entity_score + ol_score) / 2

        entity_score *= name_count
        # entity_score = min(1.0, entity_score)

        if not name in scores:
            scores[name] = (entity_label, round(entity_score, 5))
        else:
            scores[name] = (entity_label, round(max(scores[name][1], entity_score), 5))

    return [(n, l, sc) for n, (l, sc) in sorted(scores.items(), key=lambda item: item[1][1], reverse=True)]


# def get_nltk_names_smash(s: str) -> list[tuple[str, float]]:
#     from nltk import ne_chunk, pos_tag, word_tokenize
#     from nltk.tree import Tree

#     # Tokenize and process with NLTK
#     tokens = word_tokenize(s)
#     nltk_results = ne_chunk(pos_tag(tokens))
#     names = (
#         [("PERSON", x[0]) for x in get_nltk_names_smash(swap_firstname_lastname(s).replace(",", " "))]
#         if "," in s
#         else []
#     )
#     current_name = []
#     num_person_chunks = 0
#     # person_chunks = [r for r in nltk_results if isinstance(r, Tree) and r.label() == "PERSON"]
#     # num_person_chunks = len(person_chunks)

#     def _end_name():
#         nonlocal current_name, names
#         if current_name:
#             names.append(("PERSON", " ".join(current_name)))
#             current_name = []

#     def _is_proper_noun(tk: Any) -> bool:
#         if (
#             (isinstance(tk, tuple) and tk[1] in ["NNP", "NNPS"])
#             or _is_tree(tk)
#             and any_in([leaf[1] for leaf in cast(Tree, tk).leaves()], ["NNP", "NNPS"])
#         ):
#             return True
#         return False

#     def _is_non_name_char(c: str | tuple[str, str] | None) -> bool:
#         if not c:
#             return False
#         _c = c[0] if isinstance(c, tuple) else c
#         return bool(junk_chars_name_pattern.search(_c))

#     def _is_period(tk: Any) -> bool:
#         return isinstance(tk, tuple) and tk[0].strip() == "."

#     def _is_tuple(tk: Any) -> bool:
#         return isinstance(tk, tuple) and len(tk) == 2

#     def _is_tree(tk: Any) -> bool:
#         return isinstance(tk, Tree)

#     def _is_gpe_noun(tk: Any) -> bool:
#         return isinstance(tk, Tree) and tk.label() == "GPE" and tk.leaves()[0][1].startswith("NN")

#     def _is_person(tk: Any) -> bool:
#         nonlocal num_person_chunks
#         if is_person := (isinstance(tk, Tree) and tk.label() == "PERSON"):
#             num_person_chunks += 1
#         return is_person

#     def _is_abbreviated_name(tk: Any) -> bool:
#         return isinstance(tk, tuple) and (
#             bool(abbreviated_names_pattern.match(tk[0])) or bool(uppercase_1_3_letters_pattern.match(tk[0]))
#         )

#     def _is_part_of_name(prev: Any, curr: Any, nxt: Any) -> bool:
#         if _is_person(curr):
#             return True
#         if _is_gpe_noun(curr) and all(any((p is None, _is_abbreviated_name(p), _is_person(p))) for p in [prev, nxt]):
#             return True
#         if _is_non_name_char(curr[0]):
#             return False
#         if _is_proper_noun(curr) and _is_person(prev):
#             return True
#         if _is_proper_noun(nxt) and _is_person(curr):
#             return True
#         if _is_proper_noun(prev) and (_is_person(curr) or _is_period(curr)):
#             return True
#         if (_is_proper_noun(curr) or _is_period(curr)) and _is_person(nxt):
#             return True
#         if _is_abbreviated_name(curr):
#             return True
#         if _is_abbreviated_name(prev) and _is_proper_noun(curr):
#             return True
#         return False

#     prev = None
#     nxt = None
#     for i, tk in enumerate(nltk_results):
#         curr_tuple = cast(tuple[str, str], tk) if _is_tuple(tk) else (None, None)
#         curr_tree = cast(Tree, tk) if _is_tree(tk) else None
#         has_next = i < len(nltk_results) - 1
#         nxt = nltk_results[i + 1] if has_next else None

#         if _is_part_of_name(prev, tk, nxt) and not _is_non_name_char(curr_tuple[0]):
#             # Collect tokens that are part of a PERSON entity
#             if curr_tree:
#                 current_name.append(" ".join(leaf[0] for leaf in curr_tree.leaves()))  # type: ignore
#             elif curr_tuple:
#                 # append to newest part in current_name if len(current_name) > 0
#                 if current_name and _is_period(tk):
#                     current_name[-1] += f"{curr_tuple[0]}"
#                 else:
#                     current_name.append(curr_tuple[0])
#         else:
#             # Append completed name if we hit a non-PERSON chunk
#             _end_name()

#         prev = tk

#     # Append the last collected name (if any)
#     if num_person_chunks > 0 and current_name:
#         names.append(("PERSON", " ".join(current_name)))

#     # Handle short string edge case
#     if len(tokens) <= 3 and not names:  # Assume short strings might be a name
#         names = [
#             (
#                 "UNKNOWN",
#                 " ".join(
#                     (
#                         t
#                         for p, t, n in iter_prev_curr_next(tokens)
#                         if t and len(t) < 11 and not any(map(_is_non_name_char, [p, t, n]))
#                     )
#                 ),
#             )
#         ]

#     # Use nlp to double check
#     spaCy_people, _ = spaCy_extract(s)
#     names.extend([("PERSON_SPACY", p) for p in spaCy_people])

#     # Check names, and if all the words in the name are generic, change the type to "GENERIC"
#     for name in names:
#         if all(is_generic_word(w) for w in to_words(name[1])):
#             name = ("GENERIC", name[1])

#     # If we have multiple PERSON entities, score them and return the highest-scoring one
#     results = [(k, v) for k, v in lookup_and_score_names(names).items()]
#     if len(names) > 1:

#         # Remove any results from the names list that are a subset of another result
#         # e.g., if we get ("Andrea Smith", "Andrea") and ("Andrea Smith", "Smith"), we only want to keep the former
#         return list(
#             filter(lambda x: not any(x[0] in n[0] for n in results if x != n), results),
#         )

#     return results


# def spaCy_extract_sm(s: str) -> tuple[list[str], list[str]]:
#     """Extracts objects and people from a string using spaCy's named entity recognition.
#     Returns a tuple of lists: (people, objects)
#     """
#     s = re.sub(r"[-_]", ",", strip_leading_nums_and_punct(s))
#     doc: Doc = nlp(s)
#     objects = [tk for tk in doc.ents if tk.label_ in ["WORK_OF_ART", "PRODUCT", "EVENT", "ORG", "GPE", "LAW"]]
#     people = [tk for tk in doc.ents if tk.label_ in ["PERSON", "GPE"]]
#     junk = [tk for tk in doc if not tk.is_alpha]

#     # Remove junk from people
#     people = [p for p in people if not any(j.text in p.text for j in junk)]

#     # Remove junk from objects
#     objects = [o for o in objects if not any(j.text in o.text for j in junk)]

#     # If the same token is in both people and objects, keep the one that is nearest other
#     # found strings. E.g. For "Trenton Lee Stewart – The Mysterious Benedict Society", if the tokens are:
#     # people: ["Trenton", "Lee Stewart"]
#     # objects: ["Trenton", "The Mysterious Benedict Society"]
#     # We want to keep "Trenton Lee Stewart" and "The Mysterious Benedict Society"
#     # because "Trenton" is closer to "Lee Stewart" than it is to "The Mysterious Benedict Society"
#     duplicates = [o for o in objects if o in people]
#     o_ranges = [(s.find(o.text), len(o.text)) for o in objects if not o in duplicates]
#     p_ranges = [(s.find(p.text), len(p.text)) for p in people if not p in duplicates]

#     # Find the range that is closest to the other range
#     for d in duplicates:
#         # Get the position (range) where the duplicate is in the original string
#         d_i = s.find(d.text)
#         # Find the distance from the duplicate to all the other ranges
#         o_dist = [abs(d_i - r[0]) for r in o_ranges]
#         p_dist = [abs(d_i - r[0]) for r in p_ranges]
#         if o_dist and p_dist:
#             # if closer to object, remove person
#             if min(o_dist) < min(p_dist):
#                 people.remove(d)
#             # if closer to person, remove object
#             else:
#                 objects.remove(d)

#     clean_people = [p.text for p in people]
#     clean_objects = [o.text for o in objects]

#     # If any of the people are a substring of any object, strip the person from the object
#     # and vice-versa
#     for i, o in enumerate(objects):
#         for j, p in enumerate(people):
#             if p.text in o.text:
#                 clean_objects[i] = leading_trailing_non_alphanum_pattern.sub("", o.text.replace(p.text, "")).strip()
#             if o.text in p.text:
#                 clean_people[j] = leading_trailing_non_alphanum_pattern.sub("", p.text.replace(o.text, "")).strip()

#     # If any of the strings are contiguous in the original string, combine them.
#     # e.g., if people is ["Trenton", "Lee Stewart"] and objects is ["The", "Mysterious", "Benedict", "Society"],
#     # we want to combine "Trenton Lee Stewart" and "The Mysterious Benedict Society"

#     # Helper function to combine contiguous strings
#     def _combine_contiguous(strings: list[str], original: str) -> list[str]:
#         if not strings:
#             return []

#         # Sort strings by their position in the original string
#         sorted_strings = sorted(strings, key=lambda x: original.find(x))
#         result = []
#         current = sorted_strings[0]

#         for next_str in sorted_strings[1:]:
#             # Check if strings are contiguous in the original string
#             current_end = original.find(current) + len(current)
#             next_start = original.find(next_str)

#             # If they are contiguous (allowing for whitespace/punctuation)
#             if next_start <= current_end + 1:  # +1 to allow for a single space/punctuation
#                 current = f"{current} {next_str}".strip()
#             else:
#                 result.append(current)
#                 current = next_str

#         result.append(current)
#         return result

#     # Combine contiguous strings for both people and objects
#     clean_people = _combine_contiguous(clean_people, s)
#     clean_objects = _combine_contiguous(clean_objects, s)

#     return clean_people, clean_objects


def spaCy_extract(s: str) -> tuple[list[tuple[str, str, float]], list[tuple[str, str, float]]]:
    """Extracts people and objects using spaCy's NER with transformer model."""
    s = strip_leading_nums_and_punct(s)

    doc = nlp(s)

    entities = []

    default_score_map = {
        "PERSON": 1.0,
        "ORG": 0.8,
        "PRODUCT": 0.7,
        "WORK_OF_ART": 0.6,
        "EVENT": 0.6,
        "GPE": 0.5,
        "LAW": 0.4,
    }

    for ent in doc.ents:
        score = None
        if hasattr(ent._, "confidence"):
            score = ent._.confidence
        elif hasattr(ent._, "trf") and isinstance(ent._.trf, dict):
            score = ent._.trf.get("score", None)

        ent_score = score if score is not None else default_score_map.get(ent.label_, 0.3)
        entities.append((ent.text.strip(), ent.label_, ent_score))

    # Filter junk
    junk_tokens = {tok.text for tok in doc if not tok.is_alpha}
    entities = [(p, l, sc) for p, l, sc in entities if not any(j in p for j in junk_tokens)]

    # Add transformer results if we can derive them
    trf = squash_trf_results(nlp_trf(s))
    for ent in trf:
        # if any(k.startswith(ent["entity_group"]) for k in tuple(default_score_map.keys())):
        # If the entity as an exact match already exists, average the score and update it instead of adding
        if (found := next(((i, e) for i, e in enumerate(entities) if e[0] == ent["word"]), None)) is not None:
            i, (p, _, sc) = found
            l = ent["entity_group"]
            sc = min(sc, ent["score"])
            if not l.startswith("PER"):
                sc /= 2
            entities[i] = (p, l, sc)
        else:
            entities.append((ent["word"], ent["entity_group"], ent["score"]))

    # De-dupe people by substring
    entities.sort(key=lambda x: -len(x[0]))
    deduped_entities: list[tuple[str, str, float]] = []
    seen = set()
    for name, label, score in entities:
        norm = name.lower()
        if any(norm in other for other in seen):
            continue
        seen.add(norm)
        deduped_entities.append((name, label, score))

    people = [(n, "PERSON_SPACY", sc) for (n, l, sc) in deduped_entities if l.startswith("PER")]
    objects = [e for e in deduped_entities if e[0] not in [p[0] for p in people]]

    return people, objects


def get_nlp_cache_db() -> sqlite3.Connection:
    from src.lib.config import cfg

    """Get or create the SQLite database connection for NLP caching."""
    db_path = cfg.META_DIR / "nlp_cache.db"
    conn = sqlite3.connect(str(db_path))

    # Create table if it doesn't exist
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS nlp_cache (
            input_text TEXT,
            results BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (input_text)
        )
    """
    )
    return conn


def get_cached_nlp_results(text: str) -> list[tuple[str, str, float]] | None:
    """Get cached NLP results for the given text."""
    conn = get_nlp_cache_db()
    cursor = conn.cursor()

    cursor.execute("SELECT results FROM nlp_cache WHERE input_text = ?", (text,))
    result = cursor.fetchone()
    conn.close()

    if result is not None:
        try:
            return pickle.loads(result[0])
        except (pickle.UnpicklingError, EOFError):
            return None
    return None


def cache_nlp_results(text: str, results: list[tuple[str, str, float]]) -> None:
    """Cache NLP results for the given text."""
    conn = get_nlp_cache_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT OR REPLACE INTO nlp_cache (input_text, results) VALUES (?, ?)",
            (text, pickle.dumps(results)),
        )
        conn.commit()
    except Exception as e:
        print_debug(f"Failed to cache NLP results: {e}")
    finally:
        conn.close()


def get_nlp_names(s: str, *, no_cache: bool = False) -> list[tuple[str, str, float]]:
    """Extract name candidates using both NLTK and spaCy, score and rank."""
    # Try to get from cache first
    if not no_cache and (cached := get_cached_nlp_results(s)):
        return cached

    s = swap_firstname_lastname_in_long(s)

    from nltk import ne_chunk, pos_tag, word_tokenize
    from nltk.tree import Tree

    # --- NLTK ---
    tokens = word_tokenize(s)
    pos_tags = pos_tag(tokens)
    tree = ne_chunk(pos_tags)

    nltk_names: list[tuple[str, str, float] | tuple[str, str, None]] = []
    for subtree in tree:
        if isinstance(subtree, Tree) and (nltk_label := subtree.label()) == "PERSON_NLTK":
            name = " ".join(token for token, _ in subtree.leaves())
            nltk_names.append((name.strip(), nltk_label, None))

    # --- spaCy ---
    spacy_people, _ = spaCy_extract(s)
    spacy_names = [(n.strip(), l, sc) for n, l, sc in spacy_people]

    # --- Merge and dedupe substrings ---
    combined = squash_nlp_results(nltk_names + spacy_names)

    # --- Restore original name(s) if it's approximate, but has been mangled by nlp
    restored = restore_original_name(s, combined)

    # --- Score ---
    scored = lookup_and_score_names(restored)

    # --- Clean up name appreviations ---
    scored = [(clean_name_abbreviations(n, mode="periods"), l, sc) for n, l, sc in scored]

    results = sorted(scored, key=lambda x: -x[2])

    # --- Cache the results ---
    cache_nlp_results(s, results)

    return results


def percent_human_name_chars_in_str(s: str) -> float:
    """Returns the percentage (0.0 - 1.0) of characters in a string that are part of a human name"""
    if not s:
        return 0.0
    human_name_chars = sum(1 for c in s if c.isalpha())
    return human_name_chars / len(s)


@cachetools.func.ttl_cache(maxsize=128, ttl=MEMO_TTL)
def parse_names(
    s: str, target: NameParserTarget, *, fallback: str | None = None, max_chars: int = 500, _long_match: bool = False
) -> AuthorNarrator:
    if fallback is None:
        fallback = s

    # Prevent recursion by returning "" for separators
    if not any(c.isalpha() for c in s) or s in ["and", "or", "by", "," ";"]:
        return AuthorNarrator("", "")

    if len(s) > max_chars:
        s = s[:max_chars]

    if not _long_match:
        author_long_match = re_group(author_comment_pattern.search(s), 0, default="")
        narrator_long_match = re_group(narrator_comment_multiple_pattern.search(s), 0, default="")
        if author_long_match and narrator_long_match:
            return AuthorNarrator(
                parse_names(
                    author_long_match, target, fallback=narrator_long_match, max_chars=max_chars, _long_match=True
                ).author,
                parse_names(
                    narrator_long_match, target, fallback=author_long_match, max_chars=max_chars, _long_match=True
                ).narrator,
            )

    # If 's' is comma-separated, split it into a list of names, call this function recursively
    # for each name, then stitch the results back together with a comma
    # Since each call returns a tuple (author, narrator), we need to unpack each in the list
    # and join the authors with a comma, then the narrators with a comma.
    if names_split_pattern.search(s) or names_split_pattern.search(fallback):

        def _filter_split(parts: list[str]) -> list[str]:
            return [
                n
                for n in [names_split_pattern.sub("", n).strip() for n in parts]
                if n and not re.match(r"and|as", n, re.I)
            ]

        split_names = _filter_split(names_split_pattern.split(s))
        split_fallback = _filter_split(names_split_pattern.split(fallback))

        authors, narrators = zip(
            *[
                parse_names((n or "").strip(), target, fallback=(f or "").strip(), _long_match=_long_match)
                for n, f in zip_longest(split_names, split_fallback)
            ]
        )
        return AuthorNarrator(
            ", ".join(filter(lambda x: x, authors)),
            ", ".join(filter(lambda x: x, narrators)),
        )

    fallback = strip_symbols_and_nums(fallback, exceptions=r"'.,-")
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
            # if we're dealing with a filesystem author name, we need to replace underscores
            # used to join words with spaces because often these are junk in the filename.
            author = underscores_joining_words_pattern.sub(" ", author)
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

    # Remove junk chars
    author = junk_chars_name_pattern.sub("", author)
    narrator = junk_chars_name_pattern.sub("", narrator)

    if author == narrator:
        # if the author and narrator are the same, set the narrator to an empty string
        narrator = ""

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

    nltk_s = next((n for (n, _, sc) in get_nlp_names(junk_chars_name_pattern.sub("", s)) if sc > 0), None)
    nltk_author = None if not author else next((n for (n, _, sc) in get_nlp_names(author) if sc > 0.7), None)
    nltk_narrator = None if not narrator else next((n for (n, _, sc) in get_nlp_names(narrator) if sc > 0.7), None)  # type: ignore

    if nltk_s and (not fallback or len(nltk_s) > len(fallback)):
        fallback = nltk_s

    author = nltk_author if nltk_author else (get_name_from_str(author) or fallback)
    narrator = nltk_narrator if nltk_narrator else (get_name_from_str(narrator) or fallback)

    # Remove author name from narrator, then trip leading/trailing junk chars again
    if author in narrator:
        narrator = re.sub(author, "", narrator)
        narrator = strip_symbols_and_nums(narrator).strip()

    if all((is_generic_word(a) for a in to_words(author))):
        author = fallback

    if all((is_generic_word(n) for n in to_words(narrator))):
        narrator = fallback

    return AuthorNarrator(author=author, narrator=narrator)


def parse_author(s: str, target: NameParserTarget, *, fallback: str | None = None, max_chars: int = 40) -> str:
    """Parses an author name from a string, using the given target and fallback.
    If the author name is longer than max_chars, only from 0-max_chars will be used.
    """
    return parse_names(s, target, fallback=fallback, max_chars=max_chars).author or fallback or ""


def has_graphic_audio(s: str) -> bool:
    return bool(graphic_audio_pattern.search(s))


def parse_narrator(s: str, target: NameParserTarget, *, fallback: str | None = None, max_chars: int = 150) -> str:

    return parse_names(s, target, fallback=fallback, max_chars=max_chars).narrator or fallback or ""


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
