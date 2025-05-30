import os
import statistics
from collections.abc import Callable, Iterable
from functools import wraps
from itertools import combinations, zip_longest
from math import log10
from pathlib import Path
from typing import Any, cast, overload, TYPE_CHECKING, TypeVar

from rapidfuzz import fuzz, process
from rapidfuzz.distance import LCSseq, Levenshtein

from lib.misc import ensure_list, isorted
from lib.term import print_error
from lib.typing import SimilarityComparable, SimilarityComparisonMethod, SimilarityFuncMethod

if TYPE_CHECKING:
    from rapidfuzz.process import _Scorer


def sim_func(*methods: SimilarityFuncMethod | None):
    if "extract" in methods:
        return "extract"  # Signal special handling
    base_funcs = []
    for method in methods:
        if method == "ratio":
            base_funcs.append(lambda s1, s2, *args, **kwargs: fuzz.ratio(s1, s2, *args, **kwargs) / 100)
        elif method == "token_set_ratio":
            base_funcs.append(lambda s1, s2, *args, **kwargs: fuzz.token_set_ratio(s1, s2, *args, **kwargs) / 100)
        elif method == "token_sort_ratio":
            base_funcs.append(lambda s1, s2, *args, **kwargs: fuzz.token_sort_ratio(s1, s2, *args, **kwargs) / 100)
        elif method == "lcs":
            base_funcs.append(LCSseq.normalized_similarity)
        elif method == "lev":
            base_funcs.append(Levenshtein.normalized_similarity)
        else:
            raise ValueError(f"Unsupported method: {method}")

    if not base_funcs:
        return fuzz.ratio

    def calc(s1: Any, s2: Any, *args: Any, **kwargs: Any) -> float:
        return sum(func(str(s1), str(s2), *args, **kwargs) for func in base_funcs) / len(base_funcs)

    return calc


def calc_similarity(
    lst: list[str],
    *,
    precision: int = 3,
    methods: list[SimilarityFuncMethod] = ["extract", "ratio", "lcs", "lev"],
) -> list[tuple[tuple[str, str], int | float, int]]:
    if not lst:
        return []

    if len(lst) == 1:
        default_score = 1.0
        return [((lst[0], lst[0]), default_score, 0)]

    methods = ensure_list(methods)

    sim_fn = sim_func(*methods)

    if sim_fn == "extract":
        methods.remove("extract")
        sim_fn = sim_func(*methods)
        q = lst[0]
        choices = lst[1:]
        if not choices:
            return []
        matches = process.extract(q, choices, scorer=cast("_Scorer", sim_fn), limit=len(choices))
        return [((q, m), round(score, precision), lst.index(m)) for m, score, _ in matches]

    # Fallback to standard pairwise comparison logic
    seen_pairs = set()
    scores = {}

    for idx, key in enumerate(lst):
        key_scores = []
        for jdx, other in enumerate(lst):
            if idx == jdx:
                continue
            pair = tuple(sorted((key, other)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            score = round(sim_fn(key, other), precision)
            key_scores.append((other, score, jdx))
        scores[key] = key_scores

    flattened = []
    added_pairs = set()
    for key, comparisons in scores.items():
        for comp_str, score, comp_idx in comparisons:
            pair = tuple(sorted([key, comp_str]))
            if pair not in added_pairs:
                added_pairs.add(pair)
                flattened.append(((key, comp_str), score, comp_idx))

    return flattened


F = TypeVar("F")


@overload
def get_similarity(
    values: Iterable[Any],
    precision: int = 3,
    comparison: SimilarityComparisonMethod = None,
    *,
    distinct: bool = True,
    methods: list[SimilarityFuncMethod] = ["extract", "ratio", "lcs", "lev"],
    fallback: float = 0.0,
) -> float: ...


@overload
def get_similarity(
    values: Iterable[Any],
    precision: int = 3,
    comparison: SimilarityComparisonMethod = None,
    *,
    distinct: bool = True,
    methods: list[SimilarityFuncMethod] = ["extract", "ratio", "lcs", "lev"],
    fallback: F,
) -> float | F: ...


def get_similarity(
    values: Iterable[Any],
    precision: int = 3,
    comparison: SimilarityComparisonMethod = None,
    *,
    distinct: bool = True,
    methods: list[SimilarityFuncMethod] = ["extract", "ratio", "lcs", "lev"],
    fallback: F | float = 0.0,
) -> float | F:
    """Uses the Levenshtein distance to calculate the similarity of a list of strings.
    Determines the average similarity of strings/paths (0-1), rounded to the specified precision.
    Optionally computes the median similarity instead of the average.
    Setting distinct=True will only compare distinct pairs of strings.
    """
    median = comparison == "median"
    lowest = comparison == "min"
    highest = comparison == "max"

    if not values:
        return fallback

    def calc_avg(lst: list[float]) -> float:
        return round((sum(lst) / len(lst)), precision)

    def calc_med(lst: list[float]) -> float:
        return round(statistics.median(lst), precision)

    # Extract just the base filenames (without extensions) for path or pathlike
    str_vals: list[str] = []
    for v in values:
        if isinstance(v, Path) or isinstance(v, str):
            try:
                str_vals.append(Path(v).stem)
            except Exception:
                str_vals.append(str(v))
        else:
            str_vals.append(str(v))

    if distinct:
        str_vals = list(set(str_vals))

    # if there are no values to compare to, return 1
    if len(str_vals) < 2:
        return 1.0

    str_vals = isorted(str_vals)

    # Compare left and right strings
    scores = calc_similarity(str_vals, methods=methods)
    flat_scores = [score for _, score, _ in scores]

    if not flat_scores:
        return fallback

    if lowest:
        # Return the lowest score
        return round(min(flat_scores), precision)

    elif highest:
        # Return the highest score
        return round(max(flat_scores), precision)

    # Find the median score
    elif median:
        return calc_med(flat_scores)

    # Average the scores
    else:
        return calc_avg(flat_scores)


def get_size_similarity(
    sizes: list[int | float],
    *,
    precision: int = 3,
    zero_point: float = 6.05,
    curve_strength: float = 4,
    byte_multiplier: int = 1,
) -> float:
    """
    Computes a similarity score from 0 to 1 based on a logarithmic scale.
    1.0 = identical sizes, 0.0 = vastly different sizes.
    The score decreases logarithmically as the absolute differences increase,
    creating a natural scaling that's more sensitive to small differences
    and less sensitive to large ones.

    zero_point: is the power of 10 in bytes at which the score should be 0. e.g.,
    - 1 will make 10b score 0
    - 2 will make 100b score 0
    - 3 will make 1kb score 0
    - 4 will make 10kb score 0
    - 5 will make 100kb score 0
    - 6 will make 1mb score 0
    - 7 will make 10mb score 0
    ... etc.

    curve_strength: is used to control the rate at which the score approaches 1 as it increases from the 0
    score point. The higher the value, the faster the score approaches 1. This number should never be less
    than 3, otherwise it will cause near 0-byte values to score quite low.

    byte_multiplier: is the factor by which sizes are multiplied before calculating the similarity.
    This is useful for cases where sizes are in different units, such as bytes, kilobytes, megabytes, etc.
    For example, if sizes are in bytes, a byte_multiplier of 1000 will scale the sizes to kilobytes.
    """

    if not sizes:
        return 0.0
    if len(sizes) == 1 or all(size == sizes[0] for size in sizes):
        return 1.0

    curve_strength = max(3, curve_strength)

    sizes = [size * byte_multiplier for size in sizes]

    # Calculate the maximum absolute difference between any two sizes, ensuring it's at least 1
    max_diff = max(1, max(abs(a - b) for a, b in combinations(sizes, 2)))

    log_diff = log10(max_diff)

    # / 6 then ** 5, then cap to 0.999 (1 is identical)
    score = min(0.999, max(0.0, 1.0 - (log_diff / zero_point) ** curve_strength))

    return round(score, precision)


def get_list_similarity(
    list1: list[Any],
    list2: list[Any],
    *,
    comparison: SimilarityComparisonMethod = None,
    distinct: bool = True,
    sort: bool = True,
) -> float:
    """Uses the Levenshtein distance and some other heuristics to calculate the similarity of two lists.
    - First it cancels out any items that are the same in both lists, but leaving duplicates intact (i.e., [1,1,2,3] and [1,2,2,4]
      will only cancel out the first 1 and 2 it finds in both lists, leaving [1,2,3] and [1,2,4] respectively)
    - If one list is shorter than the other, it will be padded with None values to match the length of the longer list
    - Then it calculates the similarity of the remaining items, weighted by the original list lengths
    """
    if sort:
        list1 = sorted(list1)
        list2 = sorted(list2)

    # Create copies of the lists to avoid modifying while iterating
    remaining1 = list1.copy()
    remaining2 = list2.copy()
    longest = max(len(remaining1), len(remaining2))

    eq = 0

    # Cancel out any items that are the same in both lists, but leaving duplicates intact
    for item in list1:
        if item in remaining2:
            remaining1.remove(item)
            remaining2.remove(item)
            eq += 1

    # Remove None values from both lists
    remaining1 = [item for item in remaining1 if item is not None]
    remaining2 = [item for item in remaining2 if item is not None]

    # Calculate the similarity of the remaining items and return the average
    # If there are no remaining items, return the ratio of equal items
    if not remaining1 and not remaining2:
        return eq / longest

    # Pad the shorter list with None values to match the length of the longer list
    remaining = zip_longest(remaining1, remaining2)

    # Calculate similarity scores for remaining items
    remaining_scores = [
        get_similarity(l, r, comparison=comparison, distinct=distinct) if l and r else 0.0 for l, r in remaining
    ]

    # Calculate the weighted score
    # Equal items contribute 1.0 each, while remaining items contribute their similarity scores

    return round((eq + sum(remaining_scores)) / longest, 3)

    # remaining_score = sum(remaining_scores)

    # # Total score is the sum of equal items (weighted as 1.0 each) and remaining similarity scores
    # # divided by the length of the longer list
    # return (equal_score + remaining_score) / longest


def get_uniqueness(lst: list[Any]) -> float | None:
    """Return the percentage of unique items in a list, from 0-1, or None if the list has fewer than 2 items"""
    if len(lst) < 2:
        return None
    return round(len(set(lst)) / len(lst), 2)


def unique_items(lst: list[Any]) -> list[Any] | None:
    """Return a list of unique items in a list, or None if the list is empty"""
    if not lst:
        return None
    return list(set(lst))


def list_items_match_each_other(lst: list[Any]) -> bool | None:
    """Return True if all items in a list are the same, or None if the list has fewer than 2 items"""
    if len(lst) < 2:
        return None
    return all(x == lst[0] for x in lst)


def list_items_match_value(lst: list[Any], value: Any) -> bool | None:
    """Return True if all items in a list are the same as the value, or None if the list has fewer than 2 items"""
    return list_items_match_each_other([value] + lst)


def find_greatest_common_string(
    strs: list[str] | list[Path], *, case_sensitive: bool = False, min_chars: int = 2
) -> str | None:
    if not strs:
        return ""

    # Extract just the base filenames (without extensions)
    base_names = [os.path.splitext(f)[0] for f in strs]

    if not case_sensitive:
        base_names = [name.lower() for name in base_names]

    # Take the shortest filename as the reference (optimization)
    shortest_name = min(base_names, key=len)
    other_names = base_names

    gcs = ""

    # Iterate over all substrings of the shortest name
    for i in range(len(shortest_name)):
        for j in range(i + 1, len(shortest_name) + 1):
            substring = shortest_name[i:j]
            # Check if this substring is present in all filenames
            if all(substring in name for name in other_names):
                # Update GCS if this substring is longer than the current GCS
                if len(substring) > len(gcs):
                    gcs = substring

    return gcs if len(gcs) >= min_chars else None


def calculate_gcs_percentage(strs: list[str] | list[Path], *, precision: int = 3, min_chars: int = 2) -> float:
    """Calculate the percentage of the longest filename that is shared by all strings as a percentage between 0-1"""
    if not strs:
        return 0.0

    # Find the greatest common string
    gcs = find_greatest_common_string(strs, min_chars=min_chars)

    # Determine the length of the longest filename
    longest_filename_length = max(len(str(f.name if isinstance(f, Path) else f)) for f in strs)

    # Calculate the percentage
    return round(len(gcs or "") / longest_filename_length, precision)


T = TypeVar("T")


def cached_similarity(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to handle caching of similarity calculations"""

    @wraps(func)
    def decorator(
        self,
        prop: SimilarityComparable,
        comparison: SimilarityComparisonMethod | None = None,
        **kwargs: Any,
    ) -> T:
        try:
            cache = getattr(self, f"_{prop}_similarity_cache", None)
            fallback = kwargs.pop("fallback", None)
            if not cache:
                cache = {
                    "comparison": comparison,
                    **kwargs,
                }
                setattr(self, f"_{prop}_similarity_cache", cache)
            elif (
                _kwargs_match := all(False if not k in cache else cache[k] == v for k, v in (kwargs or {}).items())
                and cache["comparison"] == comparison
                and "result" in cache
            ):
                return cache["result"] or fallback

            result = func(self, prop, comparison, **kwargs, fallback=fallback)
            cache["result"] = result
            return result
        except Exception as e:
            print_error(f"Error calculating similarity for {prop}: {e}")
            raise e

    return decorator
