import re
from pathlib import Path
from typing import Any, cast, overload, TYPE_CHECKING, TypeVar

from lazy.lazy import lazy

from lib.compare import (
    cached_similarity,
    get_list_similarity,
    get_similarity,
    get_uniqueness,
    list_items_match_each_other,
    list_items_match_value,
    unique_items,
)
from lib.misc import truthiness
from lib.typing import SimilarityComparable, SimilarityComparisonMethod
from src.lib.books_tree.books_tree_utils import (
    are_nums_contiguous,
    get_all_nums_in_string,
    get_common_nums_in_strings,
    get_missing_nums,
    get_part_num,
    only_gte_0,
    only_gte_0_tuple,
)
from src.lib.parsers import get_disc_num, get_series_num, get_start_num

if TYPE_CHECKING:
    from src.lib.books_tree.books_tree import BooksTree
    from src.lib.books_tree.books_tree_node import TreeNode

T = TypeVar("T")
F = TypeVar("F", bound=Any)


class TreeNodeList:

    def __init__(self, trees: list["BooksTree"], curr: "TreeNode | None" = None):

        if not curr:
            ...

        self._trees = trees
        self.node = cast("TreeNode", curr)
        self.id3_tags = (
            [t for t in (p.id3_tags for p in self._trees if p.id3_tags) if t and not t.BAD] if self._trees else []
        )

        self._album_similarity_cache = {}
        self._albumartist_similarity_cache = {}
        self._artist_similarity_cache = {}
        self._disc_nums_similarity_cache = {}
        self._track_nums_similarity_cache = {}
        self._title_similarity_cache = {}

    def __repr__(self):
        di = self.disc_nums
        pa = self.part_nums
        se = self.series_nums
        st = self.start_nums

        disc_nums = f"💽 {di[0]}-{di[-1]}" if len(di) > 1 else di[0] if di else ""
        part_nums = f"🎉 {pa[0]}-{pa[-1]}" if len(pa) > 1 else pa[0] if pa else ""
        series_nums = f"📺 {se[0]}-{se[-1]}" if len(se) > 1 else se[0] if se else ""
        start_nums = f"🔥 {st[0]}-{st[-1]}" if len(st) > 1 else st[0] if st else ""
        path_sim = f"🚴‍♀️ {self.similarity('pathnames', distinct=True, fallback=0.0)}"
        album_sim = f"📘 {self.similarity('id3_albums', distinct=True, fallback=0.0)}" if self.have_albums else ""
        author_sim = f"🧑‍🎨 {self.similarity('id3_artists', distinct=True, fallback=0.0)}" if self._have_artists else ""
        return " ".join(
            (str(v) for v in (disc_nums, part_nums, series_nums, start_nums, path_sim, album_sim, author_sim) if v)
        )

    def __str__(self):
        return self.__repr__()

    @lazy
    def disc_nums(self):
        return only_gte_0([get_disc_num(p.name) for p in self._trees])

    @lazy
    def part_nums(self):
        return only_gte_0([get_part_num(t.name) for t in self._trees])

    @lazy
    def series_nums(self):
        return only_gte_0([get_series_num(t.name) for t in self._trees])

    @lazy
    def start_nums(self):
        return only_gte_0([get_start_num(t.name) for t in self._trees])

    @lazy
    def all_path_nums(self) -> list[list[tuple[int | float, ...]]]:
        """Returns a list of lists of tuples, where each tuple contains the number and its position in the pathname.
        e.g. if there are two paths with ["10 apples, 14 pears", "12 apples, 20 pears"]], it would return:
        [ [(10, 0), (14, 11)], [(12, 0), (20, 11)] ]
            ^ num    ^ num       ^ num    ^ num
            pos ^    pos ^       pos ^    pos ^
        """
        return [only_gte_0_tuple(get_all_nums_in_string(Path(p.name).stem), 0) for p in self._trees]

    @lazy
    def all_path_nums_reverse(self) -> list[list[tuple[int | float, ...]]]:
        """Same as all_path_nums, but with numbers detected in reverse order from the end of the pathname - useful
        if filenames have different lengths, but you want to match numbers at the end of the pathname."""
        return [only_gte_0_tuple(get_all_nums_in_string(Path(p.name).stem, reverse=True), 0) for p in self._trees]

    @lazy
    def all_path_nums_completion(self):
        from src.lib.books_tree.books_tree_utils import get_common_nums_in_strings

        # Given a return value of e.g. `[ [(10, 0), (14, 11)], [(12, 0), (20, 11)] ]` from all_path_nums,
        # returns the completion for all path nums positions that match.

        if not self.all_path_nums and not self.all_path_nums_reverse:
            return None

        max_nums = max(len(x) for x in self.all_path_nums + self.all_path_nums_reverse)

        apn = self.all_path_nums
        # Unshift if the first path has no numbers, because it is the curr node
        if len(apn) > 1 and not apn[0]:
            apn = apn[1:]

        apnr = self.all_path_nums_reverse
        # Unshift if the first path has no numbers, because it is the curr node
        if len(apnr) > 1 and not apnr[0]:
            apnr = apnr[1:]

        apn = get_common_nums_in_strings(apn) or []
        apnr = get_common_nums_in_strings(apnr) or []

        most = max((max(apn or [[]], key=len), max(apnr or [[]], key=len)))
        return round(len(most) / max_nums, 3) if most else 0.0

    @lazy
    def all_path_nums_are_contiguous(self):

        if not self.all_path_nums and not self.all_path_nums_reverse:
            return None

        apn = self.all_path_nums
        if len(apn) > 1 and not apn[0]:
            apn = apn[1:]

        apnr = self.all_path_nums_reverse
        if len(apnr) > 1 and not apnr[0]:
            apnr = apnr[1:]

        apn = get_common_nums_in_strings(apn) or []
        apnr = get_common_nums_in_strings(self.all_path_nums_reverse) or []

        pivoted_apn = (
            [[x[i][0] for x in apn if i < len(x)] for i in range(max((len(x) for x in apn or [[]])))] if apn else []
        )
        pivoted_apnr = (
            [[x[i][0] for x in apnr if i < len(x)] for i in range(max((len(x) for x in apnr or [[]])))] if apnr else []
        )

        # Remove any where all the numbers are the same
        pivoted_apn = [x for x in pivoted_apn if len(set(x)) > 1]
        pivoted_apnr = [x for x in pivoted_apnr if len(set(x)) > 1]

        apn_contiguous = truthiness([bool(are_nums_contiguous(x, sort=True, skips_ok=True)) for x in pivoted_apn])
        apnr_contiguous = truthiness([bool(are_nums_contiguous(x, sort=True, skips_ok=True)) for x in pivoted_apnr])

        return max(apn_contiguous, apnr_contiguous) == 1.0

    @lazy
    def id3_albums(self):
        return [a for a in (id3.album for id3 in self.id3_tags if id3) if a]

    @lazy
    def id3_albumartists(self):
        return [aa for aa in (id3.albumartist for id3 in self.id3_tags if id3) if aa]

    @lazy
    def id3_artists(self):
        return [a for a in (id3.artist for id3 in self.id3_tags if id3) if a]

    @lazy
    def id3_disc_nums(self):
        return only_gte_0([id3.disc_num for id3 in self.id3_tags if id3 and id3.disc_num is not None])

    @lazy
    def id3_disc_total(self):
        return max(self.id3_disc_nums) if self.id3_disc_nums else None

    @lazy
    def id3_titles(self):
        return [t for t in (id3.title for id3 in self.id3_tags if id3) if t]

    @lazy
    def id3_track_nums(self):
        return only_gte_0([id3.track_num for id3 in self.id3_tags if id3 and id3.track_num is not None])

    @lazy
    def id3_track_total(self):
        return max(self.id3_track_nums) if self.id3_track_nums else None

    @lazy
    def pathnames(self):
        return [p.name for p in self._trees]

    @overload
    def similarity(
        self,
        prop: SimilarityComparable,
        comparison: SimilarityComparisonMethod | None = None,
        *,
        distinct: bool = True,
        include_curr: bool = True,
        fallback: None = None,
    ) -> float | None: ...

    @overload
    def similarity(
        self,
        prop: SimilarityComparable,
        comparison: SimilarityComparisonMethod | None = None,
        *,
        distinct: bool = True,
        include_curr: bool = True,
        fallback: F,
    ) -> float | F: ...

    @cached_similarity
    def similarity(
        self,
        prop: SimilarityComparable,
        comparison: SimilarityComparisonMethod | None = None,
        *,
        distinct: bool = True,
        include_curr: bool = True,
        fallback: F | None = None,
    ) -> float | F:
        """Base method for calculating similarity between values of a property"""

        if prop is None:
            raise ValueError("TreeNodeList.similarity: prop cannot be None")

        if prop == "id3_authors":
            a = self.similarity(
                "id3_artists", comparison, distinct=distinct, include_curr=include_curr, fallback=fallback
            )
            aa = self.similarity(
                "id3_albumartists", comparison, distinct=distinct, include_curr=include_curr, fallback=fallback
            )
            return max(a or fallback or 0.0, aa or fallback or 0.0)

        values = [*getattr(self, prop)]
        if include_curr and (curr := getattr(self.node, re.sub(r"s?$", "", prop), None)) and curr:
            values.insert(0, curr)
        if len(values) < 2:
            return cast(F, fallback)
        return cast(F, get_similarity(values, comparison=comparison, distinct=distinct, fallback=fallback))

    @lazy
    def disc_nums_are_contiguous(self):

        return are_nums_contiguous(self.disc_nums, sort=True, skips_ok=True)

    @lazy
    def disc_nums_completion(self):
        """Return the ratio of disc numbers / total disc numbers, from 0-1"""

        if not self.have_disc_nums:
            return None

        return len(self.disc_nums) / len(self._trees)

    @lazy
    def disc_nums_match_curr(self):

        return list_items_match_value(self.disc_nums, self.node.disc_num)

    @lazy
    def disc_nums_match_each_other(self):

        return list_items_match_each_other(self.disc_nums)

    @lazy
    def disc_nums_uniqueness(self):
        """Return the ratio of unique disc numbers to total disc numbers"""
        return get_uniqueness(self.disc_nums)

    @lazy
    def have_any_nums(self):
        return any([bool(x) for x in self.all_path_nums]) or self.have_disc_nums or self.have_track_nums

    @lazy
    def have_albums(self):
        return any([x for x in self.id3_albums])

    @lazy
    def _have_albumartists(self):
        return any([x for x in self.id3_albumartists])

    @lazy
    def _have_artists(self):
        return any([x for x in self.id3_artists])

    @lazy
    def have_authors(self):
        return self._have_albumartists or self._have_artists

    @lazy
    def have_disc_nums(self):
        if self.id3_disc_nums:
            return any([x > -1 for x in self.id3_disc_nums])
        return any([x > -1 for x in self.disc_nums])

    @lazy
    def have_part_nums(self):
        return any([x > -1 for x in self.part_nums])

    @lazy
    def have_series_nums(self):
        return any([x > -1 for x in self.series_nums])

    @lazy
    def have_start_nums(self):
        return any([x > -1 for x in self.start_nums])

    @lazy
    def have_track_nums(self):
        # Sometimes track numbers are written as 1/1, so we want to ignore those.
        return any([x > -1 for x in self.id3_track_nums])

    @lazy
    def missing_disc_nums(self):
        """If there are any disc nums, return a list of the missing ones"""

        return get_missing_nums(self.disc_nums)

    @lazy
    def missing_part_nums(self):

        return get_missing_nums(self.part_nums)

    @lazy
    def missing_series_nums(self):

        return get_missing_nums(self.series_nums)

    @lazy
    def missing_start_nums(self):

        return get_missing_nums(self.start_nums)

    @lazy
    def missing_track_nums(self):

        return get_missing_nums(self.id3_track_nums)

    @lazy
    def part_nums_are_contiguous(self):

        return are_nums_contiguous(self.part_nums, sort=True, skips_ok=True)

    @lazy
    def part_nums_completion(self):
        """Return the ratio of part numbers / total part numbers, from 0-1"""
        if not self.have_part_nums:
            return None
        return len(self.part_nums) / len(self._trees)

    @lazy
    def part_nums_match_curr(self):

        return list_items_match_value(self.part_nums, self.node.part_num)

    @lazy
    def part_nums_match_each_other(self):

        return list_items_match_each_other(self.part_nums)

    @lazy
    def part_nums_uniqueness(self):
        """Return the ratio of unique part numbers to total part numbers"""

        return get_uniqueness(self.part_nums)

    @lazy
    def series_nums_are_contiguous(self):

        return are_nums_contiguous(self.series_nums, sort=True, skips_ok=True)

    @lazy
    def series_nums_completion(self):
        """Return the ratio of series numbers / total series numbers, from 0-1"""
        if not self.have_series_nums:
            return None
        return len(self.series_nums) / len(self._trees)

    @lazy
    def series_nums_match_curr(self):
        """Returns True if all series numbers match the current's series or start number"""

        return list_items_match_value(self.series_nums, self.node.series_num)

    @lazy
    def series_nums_match_each_other(self):
        """Returns True if all series numbers match each other"""

        return list_items_match_each_other(self.series_nums)

    @lazy
    def series_nums_uniqueness(self):
        """Return the ratio of unique series numbers to total series numbers"""

        return get_uniqueness(self.series_nums)

    @lazy
    def start_nums_are_contiguous(self):
        """Returns True if all start numbers are contiguous"""

        return are_nums_contiguous(self.start_nums, sort=True, skips_ok=True)

    @lazy
    def start_nums_completion(self):
        """Return the ratio of start numbers / total start numbers, from 0-1"""
        if not self.have_start_nums:
            return None
        return len(self.start_nums) / len(self._trees)

    @lazy
    def start_nums_match_curr(self):
        """Returns True if all start numbers match the current's series or start number"""

        return list_items_match_value(self.start_nums, self.node.start_num)

    @lazy
    def start_nums_match_each_other(self):

        return list_items_match_each_other(self.start_nums)

    @property
    def start_vs_track_nums_similarity(self):
        """Return the similarity score between the start numbers and the track numbers (0-1)"""
        if not self.have_start_nums or not self.have_track_nums:
            return None
        return get_list_similarity(self.start_nums, self.id3_track_nums)

    @lazy
    def start_nums_uniqueness(self):
        """Return the percentage of start numbers that are unique, from 0-1"""

        return get_uniqueness(self.start_nums)

    @lazy
    def track_nums_are_contiguous(self):
        """Returns True if all track numbers are contiguous"""

        return are_nums_contiguous(self.id3_track_nums, sort=True, skips_ok=True)

    @lazy
    def track_nums_completion(self):
        """Return the ratio of track numbers / total track numbers, from 0-1"""
        if not self.have_track_nums:
            return None
        return len(self.id3_track_nums) / len(self._trees)

    @lazy
    def track_nums_match_curr(self):
        """Returns True if all track numbers match the current's track number"""

        return list_items_match_value(self.id3_track_nums, self.node.id3_track_num)

    @lazy
    def track_nums_match_each_other(self):
        """Returns True if all track numbers match each other"""

        return list_items_match_each_other(self.id3_track_nums)

    @lazy
    def track_nums_uniqueness(self):
        """Return the percentage of track numbers that are unique, from 0-1"""

        return get_uniqueness(self.id3_track_nums)

    @lazy
    def unique_disc_nums(self):
        """Return a list of unique disc numbers"""

        return unique_items(self.disc_nums)

    @lazy
    def unique_part_nums(self):
        """Return a list of unique part numbers"""

        return unique_items(self.part_nums)

    @lazy
    def unique_series_nums(self):
        """Return a list of unique series numbers"""

        return unique_items(self.series_nums)

    @lazy
    def unique_start_nums(self):
        """Return a list of unique start numbers"""

        return unique_items(self.start_nums)

    @lazy
    def unique_track_nums(self):
        """Return a list of unique track numbers"""

        return unique_items(self.id3_track_nums)
