import re
from itertools import zip_longest
from pathlib import Path
from typing import Any, cast, TYPE_CHECKING, TypeVar

import cachetools
import cachetools.func
import regex as rex

from src.lib.misc import re_group
from src.lib.parsers import try_parse_num
from src.lib.patterns import (
    part_or_ch_match_words,
    partno_or_ch_match_pattern2,
    rex,
)
from src.lib.typing import Id3TagDict, MEMO_TTL, NumericIterable

if TYPE_CHECKING:
    from src.lib.books_tree import BooksTree
    from src.lib.books_tree.books_tree_node import TreeNode

TreeNodeType = TypeVar("TreeNodeType", bound="TreeNode")


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


def get_disc_num_from_id3(id3: Id3TagDict) -> tuple[int, int]:

    if not id3:
        return -1, -1

    return _parse_id3_disc_or_track_num(id3.get("discnumber"))


@cachetools.func.ttl_cache(maxsize=32, ttl=MEMO_TTL)
def get_part_num(s: str | Path) -> int:
    s = str(s)
    if not (substr := re_group(part_or_ch_match_words.search(s), 0)):
        return -1
    return int(re_group(partno_or_ch_match_pattern2.search(substr), "num1", default=-1))


def get_track_num_from_id3(id3: Id3TagDict) -> tuple[int, int]:

    if not id3:
        return -1, -1

    return _parse_id3_disc_or_track_num(cast(Id3TagDict, id3).get("track"))


def are_nums_contiguous(
    nums: list[int] | list[float] | list[int | float], *, sort=False, skips_ok=False
) -> bool | None:
    """Returns True if the numbers are contiguous, or False if they're not. If nums is < 2, returns None"""
    if len(nums) < 2:
        return None
    if sort:
        nums = sorted(nums)
    # For integers, check that no numbers are skipped
    if not skips_ok and all(isinstance(n, int) for n in nums):
        return all(nums[i] == nums[i - 1] + 1 for i in range(1, len(nums)))
    # otherwise just check if they're in ascending order
    return len(set(nums)) == len(nums) and sorted(nums) == nums


def get_all_nums_in_string(s: str, reverse: bool = False) -> list[tuple[int | float, int]]:
    """Finds all numbers (int and float) in a string, and returns a list of tuples with the number and its position in the string
    If reverse is True, detects numbers in reverse order from the end of the string instead of the start.
    """
    if reverse:
        s = s[::-1]
    matches: list[tuple[int | float | None, int]] = [
        (try_parse_num(m.group()), m.start()) for m in rex.finditer(r"\d+(?:\.\d+)?", s) if m
    ]
    if reverse:
        # For reverse mode, we need to:
        # 1. Re-reverse the numbers (e.g. "10" -> "01")
        # 2. Re-parse to strip leading zeros
        matches = [(try_parse_num(str(num)[::-1]), pos) for num, pos in matches]
    return list(filter(lambda x: x[0] is not None, matches))  # type: ignore


def get_missing_nums(nums: list[int]) -> list[int]:
    """Return a list of missing numbers in a sequence"""
    if len(nums) < 2 or are_nums_contiguous(nums):
        return []
    min_num, max_num = min(nums), max(nums)
    return [x for x in range(min_num, max_num + 1) if x not in nums]


def only_gte_0(lst: NumericIterable) -> NumericIterable:
    return cast(NumericIterable, [n for n in lst if n >= 0])


def only_gte_0_tuple(lst: list[tuple[int | float, ...]], index: int) -> list[tuple[int | float, ...]]:
    # Check all tuples in the list at index, and return only those where the value is >= 0
    return [t for t in lst if t[index] >= 0]


def filter_matches(func):
    def wrapper(self, *args, **kwargs):
        paths = func(self, *args, **kwargs)
        if not paths:
            return paths
        return _match_filter_func(paths, self.match_filter, root=self.root or self)

    return wrapper


def _match_filter_func(
    paths: "list[Path | BooksTree] | dict[str, BooksTree]",
    match_filter: list[Path] | str | None,
    *,
    root: "BooksTree | Path",
):
    from src.lib.config import cfg
    from src.lib.fs_utils import try_relative_to

    match_filter = match_filter or cfg.MATCH_FILTER

    if not match_filter or not paths:
        return paths

    if root is None:
        raise ValueError("match_filter: root should never be None")

    rel_match_filter = cast(
        list["Path | BooksTree"] | str,
        (
            [try_relative_to(str(p), root or Path()) for p in match_filter]
            if isinstance(match_filter, list)
            else match_filter
        ),
    )

    def _is_wanted_path(t: "BooksTree | Path | str | None"):
        if not (rel_path := try_relative_to(str(t), root or Path())):
            return False
        if isinstance(rel_match_filter, str):
            return bool(re.search(rel_match_filter, str(rel_path), re.I))
        while (p := rel_path) and p.parent != p:
            if p in rel_match_filter:
                return True
            rel_path = p.parent
        return False

    return (
        {k: v for k, v in paths.items() if _is_wanted_path(v)}
        if isinstance(paths, dict)
        else [p for p in paths if _is_wanted_path(p)]
    )


def get_common_nums_in_strings(
    nums_lists: list[list[tuple[int | float, ...]]],
) -> list[list[tuple[int | float, int]]]:
    """Find numbers that appear at the same positions across multiple strings.

    Args:
        strings: List of strings to search for numbers
        reverse: Whether to detect numbers in reverse order from the end of each string

    Returns:
        List of lists of (number, position) tuples, filtered to only include positions
        that appear in every string. Returns None if no common positions found.
    """
    if not nums_lists:
        return []

    flat_positions = [[n[1] for n in lst] for lst in nums_lists]
    padded = list(zip_longest(*flat_positions, fillvalue=-1))

    indexes_common_to_all = set()
    for plst in padded:
        # if all the numbers in the plst are the same, add the index to the set
        if all(n == plst[0] for n in plst):
            indexes_common_to_all.add(plst[0])

    # Filter nums_lists to only include numbers at matching positions
    filtered_nums = []
    for nums_list in nums_lists:
        if not nums_list:
            continue
        filtered = [(num, pos) for num, pos in nums_list if pos in indexes_common_to_all]
        if filtered:
            filtered_nums.append(filtered)

    return filtered_nums if filtered_nums else []
