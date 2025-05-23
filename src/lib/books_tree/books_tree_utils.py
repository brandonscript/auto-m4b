import re
from pathlib import Path
from typing import Any, cast, TYPE_CHECKING, TypeVar

import cachetools
import cachetools.func
import regex as rex

from lib.misc import re_group
from lib.parsers import try_parse_num
from lib.patterns import (
    part_or_ch_match_words,
    partno_or_ch_match_pattern2,
    rex,
)
from lib.typing import Id3TagDict, MEMO_TTL, NumericIterable

if TYPE_CHECKING:
    from lib.books_tree import BooksTree
    from lib.books_tree.books_tree_node import TreeNode

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
    if not part_or_ch_match_words.search(s):
        return -1
    return int(re_group(partno_or_ch_match_pattern2.search(s), "num1", default=-1))


def get_track_num_from_id3(id3: Id3TagDict) -> tuple[int, int]:

    if not id3:
        return -1, -1

    return _parse_id3_disc_or_track_num(cast(Id3TagDict, id3).get("track"))


def are_nums_sequential(nums: list[int], *, sort=False, skips_ok=False) -> bool | None:
    """Returns True if the numbers are sequential, or False if they're not. If nums is < 2, returns None"""
    if len(nums) < 2:
        return None
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


def get_missing_nums(nums: list[int]) -> list[int]:
    """Return a list of missing numbers in a sequence"""
    if len(nums) < 2 or are_nums_sequential(nums):
        return []
    min_num, max_num = min(nums), max(nums)
    return [x for x in range(min_num, max_num + 1) if x not in nums]


def only_gte_0(lst: NumericIterable) -> NumericIterable:
    return cast(NumericIterable, [n for n in lst if n >= 0])


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
