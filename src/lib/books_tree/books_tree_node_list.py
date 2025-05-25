from collections.abc import Callable
from pathlib import Path
from typing import cast, Literal, TYPE_CHECKING, TypeVar

from lazy.lazy import lazy

from lib.books_tree.books_tree_utils import (
    are_nums_sequential,
    get_all_nums_in_string,
    get_missing_nums,
    get_part_num,
    only_gte_0,
)
from lib.compare import cached_similarity, get_list_similarity, get_similarity, SimilarityComparisonMethod, unique_items
from lib.parsers import get_disc_num, get_series_num, get_start_num
from src.lib.compare import (
    get_similarity,
    get_uniqueness,
    list_items_match_each_other,
    list_items_match_value,
)
from src.lib.misc import (
    clamp,
    is_gt_50mb,
    percent_truthy_in_list,
)

if TYPE_CHECKING:
    from lib.books_tree.books_tree import BooksTree
    from lib.books_tree.books_tree_node import TreeNode

T = TypeVar("T")


class TreeNodeList:

    def __init__(self, trees: list["BooksTree"], curr: "TreeNode | None" = None):

        if not curr:
            ...

        self._trees = trees
        self._node = cast("TreeNode", curr)
        if not self._trees:
            self._id3 = []
            return

        self._id3 = [p.id3_tags for p in self._trees if p.id3_tags]

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

        first_last_di = f"{di[0]}-{di[-1]}" if len(di) > 1 else di[0] if di else "—"
        first_last_pa = f"{pa[0]}-{pa[-1]}" if len(pa) > 1 else pa[0] if pa else "—"
        first_last_se = f"{se[0]}-{se[-1]}" if len(se) > 1 else se[0] if se else "—"
        first_last_st = f"{st[0]}-{st[-1]}" if len(st) > 1 else st[0] if st else "—"
        return f"{{d: {first_last_di}, p: {first_last_pa}, s: {first_last_se}, ^: {first_last_st}, ~: {self.pathname_similarity(distinct=True)}}}"

    def __str__(self):
        return self.__repr__()

    @lazy
    def disc_nums(self):
        return only_gte_0([get_disc_num(p.name) for p in self._trees])

    @lazy
    def part_nums(self):
        return only_gte_0([get_part_num(p.name) for p in self._trees])

    @lazy
    def series_nums(self):
        return only_gte_0([get_series_num(p.name) for p in self._trees])

    @lazy
    def start_nums(self):
        return only_gte_0([get_start_num(p.name) for p in self._trees])

    @lazy
    def all_path_nums(self):
        return [only_gte_0([n for (n, _) in get_all_nums_in_string(Path(p.name).stem)]) for p in self._trees]

    @lazy
    def id3_albums(self):
        return [a for a in (id3.album for id3 in self._id3 if id3) if a]

    @lazy
    def id3_albumartists(self):
        return [aa for aa in (id3.albumartist for id3 in self._id3 if id3) if aa]

    @lazy
    def id3_artists(self):
        return [a for a in (id3.artist for id3 in self._id3 if id3) if a]

    @lazy
    def id3_disc_nums(self):
        return only_gte_0([id3.disc_num for id3 in self._id3 if id3 and id3.disc_num is not None])

    @lazy
    def id3_disc_total(self):
        return max(self.id3_disc_nums) if self.id3_disc_nums else None

    @lazy
    def id3_titles(self):
        return [t for t in (id3.title for id3 in self._id3 if id3) if t]

    @lazy
    def id3_track_nums(self):
        return only_gte_0([id3.track_num for id3 in self._id3 if id3 and id3.track_num is not None])

    @lazy
    def id3_track_total(self):
        return max(self.id3_track_nums) if self.id3_track_nums else None

    def _calculate_similarity(
        self,
        prop: str,
        comparison: SimilarityComparisonMethod | None = None,
        distinct: bool = True,
        include_curr: bool = False,
        *,
        get_values: Callable[[], list[str]] | None = None,
    ) -> float | None:
        """Base method for calculating similarity between values of a property"""
        if get_values:
            values = get_values()
        else:
            values = getattr(self, prop)
        if include_curr and (curr := getattr(self._node, prop, None)) and curr:
            values.insert(0, curr)
        if len(values) < 2:
            return None
        return get_similarity(values, comparison=comparison, distinct=distinct)

    @cached_similarity("_album_similarity_cache")
    def album_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._calculate_similarity("id3_albums", comparison, distinct, include_curr)

    @cached_similarity("_albumartist_similarity_cache")
    def albumartist_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._calculate_similarity("id3_albumartists", comparison, distinct, include_curr)

    @cached_similarity("_artist_similarity_cache")
    def artist_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._calculate_similarity("id3_artists", comparison, distinct, include_curr)

    @cached_similarity("_disc_nums_similarity_cache")
    def disc_nums_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._calculate_similarity("id3_disc_nums", comparison, distinct, include_curr)

    @cached_similarity("_title_similarity_cache")
    def title_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._calculate_similarity("id3_titles", comparison, distinct, include_curr)

    @cached_similarity("_track_nums_similarity_cache")
    def track_nums_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._calculate_similarity("id3_track_nums", comparison, distinct, include_curr)

    @cached_similarity("_pathname_similarity_cache")
    def pathname_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._calculate_similarity(
            "name", comparison, distinct, include_curr, get_values=lambda: [p.name for p in self._trees]
        )

    def are_maybe(self, structure: Literal["multi_disc", "multi_part", "series", "unknown"]) -> bool:
        md = self.score_multi_disc or 0.0
        mp = self.score_multi_part or 0.0
        s = self.score_series or 0.0

        match structure:
            case "multi_disc":
                return md > mp and md > s
            case "multi_part":
                return mp > md and mp > s
            case "series":
                return s > md and s > mp
            case "unknown":
                return not sum((self.are_maybe("multi_disc"), self.are_maybe("multi_part"), self.are_maybe("series")))

    @lazy
    def disc_nums_are_sequential(self):

        return are_nums_sequential(self.disc_nums, sort=True, skips_ok=True)

    @lazy
    def disc_nums_completion(self):
        """Return the ratio of disc numbers / total disc numbers, from 0-1"""
        if not self.have_disc_nums:
            return None
        # return percent_truthy_in_list([x > -1 for x in self.disc_nums]) / 100
        files = [t for t in self._trees if t.is_file()]
        return len(self.disc_nums) / len(files) if files else None

    @lazy
    def disc_nums_match_curr(self):

        return list_items_match_value(self.disc_nums, self._node.disc_num)

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
    def have_albumartists(self):
        return any([x for x in self.id3_albumartists])

    @lazy
    def have_artists(self):
        return any([x for x in self.id3_artists])

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
    def part_nums_are_sequential(self):

        return are_nums_sequential(self.part_nums, sort=True, skips_ok=True)

    @lazy
    def part_nums_completion(self):
        """Return the ratio of part numbers / total part numbers, from 0-1"""
        if not self.have_part_nums:
            return None
        # return percent_truthy_in_list([x > -1 for x in self.part_nums]) / 100
        files = [t for t in self._trees if t.is_file()]
        return len(self.part_nums) / len(files) if files else None

    @lazy
    def part_nums_match_curr(self):

        return list_items_match_value(self.part_nums, self._node.part_num)

    @lazy
    def part_nums_match_each_other(self):

        return list_items_match_each_other(self.part_nums)

    @lazy
    def part_nums_uniqueness(self):
        """Return the ratio of unique part numbers to total part numbers"""

        return get_uniqueness(self.part_nums)

    @lazy
    def series_nums_are_sequential(self):

        return are_nums_sequential(self.series_nums, sort=True, skips_ok=True)

    @lazy
    def series_nums_completion(self):
        """Return the ratio of series numbers / total series numbers, from 0-1"""
        if not self.have_series_nums:
            return None
        # return percent_truthy_in_list([x > -1 for x in self.series_nums]) / 100
        files = [t for t in self._trees if t.is_file()]
        return len(self.series_nums) / len(files) if files else None

    @lazy
    def series_nums_match_curr(self):
        """Returns True if all series numbers match the current's series or start number"""

        return list_items_match_value(self.series_nums, self._node.series_num)

    @lazy
    def series_nums_match_each_other(self):
        """Returns True if all series numbers match each other"""

        return list_items_match_each_other(self.series_nums)

    @lazy
    def series_nums_uniqueness(self):
        """Return the ratio of unique series numbers to total series numbers"""

        return get_uniqueness(self.series_nums)

    @lazy
    def score_multi_disc(self):
        """Likelihood the TreeNodeList is a multi-disc book, from 0-1"""
        if not self.have_disc_nums:
            return 0.0
        return round(percent_truthy_in_list([x > -1 for x in self.disc_nums]) / 100, 2)

    @lazy
    def score_multi_part(self):
        """Likelihood the TreeNodeList is a multi-part book, from 0-1"""
        part_or_track_nums = self.id3_track_nums if self.have_track_nums else self.part_nums
        base_score = 0.0

        should_check_track_nums = (
            self.have_track_nums and (self.track_nums_uniqueness or 0) > 0.9 and self.track_nums_are_sequential
        )
        should_check_part_nums = (
            self.have_part_nums and (self.part_nums_uniqueness or 0) > 0.9 and self.part_nums_are_sequential
        )
        should_check_start_nums = (
            self.have_start_nums and (self.start_nums_uniqueness or 0) > 0.9 and self.start_nums_are_sequential
        )

        if should_check_track_nums:
            base_score = 0.5
            if len(self.missing_track_nums) / len(part_or_track_nums) < 0.1:
                base_score += 0.5
        elif should_check_part_nums or should_check_start_nums:
            base_score = 0.5
            file_sizes = [t.size for t in self._trees]
            largest_file_size = max(file_sizes)
            base_score += -0.5 + int(is_gt_50mb(largest_file_size))
        return round(clamp(base_score, 0.0, 1.0), 2)

    @lazy
    def score_series(self):
        """Likelihood the TreeNodeList is a series, from 0-1"""
        from src.lib.parsers import is_maybe_multiple_books_or_series

        # Convert percent_truthy_in_list results from 0-100 to 0-1
        multi_string_agg = (
            percent_truthy_in_list([is_maybe_multiple_books_or_series(t.name) for t in self._trees]) / 100
        )
        part_num_agg = percent_truthy_in_list([x > -1 for x in self.part_nums]) / 100
        series_num_agg = percent_truthy_in_list([x > -1 for x in self.series_nums]) / 100
        start_num_agg = percent_truthy_in_list([x > -1 for x in self.start_nums]) / 100

        num_checks = max([multi_string_agg, series_num_agg, start_num_agg])
        if part_num_agg:
            # Penalize if there are part numbers, as they are often used to indicate a multi-part book, not a series
            num_checks -= part_num_agg / 2

        # Penalize for series num uniqueness
        if (u := self.series_nums_uniqueness or 1) < 1:
            num_checks -= 1 - u

        id3_checks = 0.0

        album_similarity = self.album_similarity(distinct=True) or None
        albumartist_similarity = self.albumartist_similarity(distinct=True) or None
        artist_similarity = self.artist_similarity(distinct=True) or None
        track_num_similarity = self.track_nums_similarity(distinct=True) or None

        if albumartist_similarity is not None:
            # Adjust for albumartist
            id3_checks += -0.5 + albumartist_similarity
        if artist_similarity is not None:
            # Adjust for artist
            id3_checks += -0.5 + artist_similarity
        if album_similarity is not None:
            # Adjust for album (penalize if it's similar, boost if it's not)
            if album_similarity == 1:
                # Significantly penalize if the album is identical
                id3_checks = -2.0
            else:
                id3_checks -= 2.0 * (album_similarity or 0)
        if self.have_track_nums:
            # Adjust for track numbers (penalize if they're unique, boost if they're similar)
            id3_checks += 2.0 * (-0.5 + (track_num_similarity or 0))
        if self.track_nums_uniqueness is not None:
            # Adjust for track numbers uniqueness (penalize if it's unique, boost if it's not)
            # If track uniqueness is 1, significantly penalize
            if self.track_nums_uniqueness == 1:
                id3_checks = -2.0
            else:
                id3_checks += -2.0 * (self.track_nums_uniqueness or 0)

        return round(clamp(num_checks + id3_checks, 0.0, 1.0), 3)

    @lazy
    def start_nums_are_sequential(self):
        """Returns True if all start numbers are sequential"""

        return are_nums_sequential(self.start_nums, sort=True, skips_ok=True)

    @lazy
    def start_nums_completion(self):
        """Return the ratio of start numbers / total start numbers, from 0-1"""
        if not self.have_start_nums:
            return None
        # return percent_truthy_in_list([x > -1 for x in self.start_nums]) / 100
        files = [t for t in self._trees if t.is_file()]
        return len(self.start_nums) / len(files) if files else None

    @lazy
    def start_nums_match_curr(self):
        """Returns True if all start numbers match the current's series or start number"""

        return list_items_match_value(self.start_nums, self._node.start_num)

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
    def track_nums_are_sequential(self):
        """Returns True if all track numbers are sequential"""

        return are_nums_sequential(self.id3_track_nums, sort=True, skips_ok=True)

    @lazy
    def track_nums_completion(self):
        """Return the ratio of track numbers / total track numbers, from 0-1"""
        if not self.have_track_nums:
            return None
        # return percent_truthy_in_list([x > -1 for x in self.id3_track_nums]) / 100
        files = [t for t in self._trees if t.is_file()]
        return len(self.id3_track_nums) / len(files) if files else None

    @lazy
    def track_nums_match_curr(self):
        """Returns True if all track numbers match the current's track number"""

        return list_items_match_value(self.id3_track_nums, self._node.id3_track_num)

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
