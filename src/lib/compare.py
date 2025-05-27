import os
import statistics
from collections.abc import Callable, Iterable
from functools import wraps
from itertools import zip_longest
from pathlib import Path
from typing import Any, Literal, overload, TypeVar

from lib.typing import SimilarityComparisonMethod


@overload
def calc_similarity(lst: list[str], flatten: Literal[True]) -> list[tuple[tuple[str, str], int | float, int]]: ...


@overload
def calc_similarity(lst: list[str], flatten: Literal[False]) -> dict[str, list[tuple[str, int | float, int]]]: ...


def calc_similarity(
    lst: list[str], flatten=True
) -> dict[str, list[tuple[str, int | float, int]]] | list[tuple[tuple[str, str], int | float, int]]:
    """
    Calculates the similarity of a list of strings.
    Returns (if flatten=True) a list of tuples of ((key, value), similarity score, index)
    Returns (if flatten=False) a dictionary of unique strings and their similarity scores against all other strings in the list
    """
    from rapidfuzz import process

    scores = {
        key: process.extract(key, [item for next_idx, item in enumerate(lst) if idx != next_idx])
        for idx, key in enumerate(lst)
    }

    if not flatten:
        return scores

    # Create a set to track which comparisons we've already seen
    seen_comparisons = set()
    flattened = []

    for key, comparisons in scores.items():
        for comp_str, score, comp_idx in comparisons:
            # Create a unique identifier for this comparison pair
            # Sort the strings to ensure consistent ordering regardless of direction
            pair = tuple(sorted([key, comp_str]))
            if pair not in seen_comparisons:
                seen_comparisons.add(pair)
                flattened.append(((key, comp_str), score, comp_idx))

    return flattened


def get_similarity(
    values: Iterable[Any],
    precision: int = 3,
    comparison: SimilarityComparisonMethod = None,
    distinct: bool = True,
) -> float:
    """Uses the Levenshtein distance to calculate the similarity of a list of strings.
    Determines the average similarity of strings/paths (0-1), rounded to the specified precision.
    Optionally computes the median similarity instead of the average.
    Setting distinct=True will only compare distinct pairs of strings.
    """
    median = comparison == "median"
    lowest = comparison == "min"
    highest = comparison == "max"

    if not values:
        return 0.0

    # if there are no values to compare to, return 1
    if len(list(values)) < 2:
        return 1.0

    def avg(lst: list[float], div: int = 1) -> float:
        if distinct:
            lst = list(set(lst))
        return round((sum(lst) / len(lst)) / div, precision)

    def med(lst: list[float], div: int = 1) -> float:
        if distinct:
            lst = list(set(lst))
        return round(statistics.median(lst) / div, precision)

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

    # Compare left and right strings
    scores = calc_similarity(str_vals, flatten=True)
    flat_scores = [score for _, score, _ in scores]

    if not flat_scores:
        return 0.0

    if lowest:
        # Return the lowest score
        return round(min(flat_scores) / 100, precision)

    elif highest:
        # Return the highest score
        return round(max(flat_scores) / 100, precision)

    # Find the median score
    elif median:
        return med(flat_scores, 100)

    # Average the scores
    else:
        return avg(flat_scores, 100)


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
    if not strs:
        return 0.0

    # Find the greatest common string
    gcs = find_greatest_common_string(strs, min_chars=min_chars)

    # Determine the length of the longest filename
    longest_filename_length = max(len(str(f.name if isinstance(f, Path) else f)) for f in strs)

    # Calculate the percentage
    return round(len(gcs or "") / longest_filename_length, precision)


T = TypeVar("T")


def cached_similarity(cache_attr: str):
    """Decorator to handle caching of similarity calculations"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(
            self,
            comparison: SimilarityComparisonMethod | None = None,
            distinct: bool = True,
            include_curr: bool = True,
        ) -> T:
            cache = getattr(self, cache_attr, None)
            if not cache:
                cache = {
                    "comparison": comparison,
                    "distinct": distinct,
                    "include_curr": include_curr,
                }
                setattr(self, cache_attr, cache)

            if (
                cache["comparison"] == comparison
                and cache["distinct"] == distinct
                and cache["include_curr"] == include_curr
                and "result" in cache
            ):
                return cache["result"]

            result = func(self, comparison, distinct, include_curr=include_curr)
            cache["result"] = result
            return result

        return wrapper

    return decorator
