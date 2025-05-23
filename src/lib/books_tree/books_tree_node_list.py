from pathlib import Path
from typing import cast, Literal, TYPE_CHECKING

from lib.books_tree.books_tree_utils import (
    are_nums_sequential,
    get_all_nums_in_string,
    get_disc_num_from_id3,
    get_missing_nums,
    get_part_num,
    get_track_num_from_id3,
    only_gte_0,
)
from lib.compare import get_list_similarity, get_similarity, SimilarityComparisonMethod, unique_items
from lib.parsers import get_disc_num, get_series_num
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
    from lib.books_tree.books_tree_node import TreeNode
    from lib.books_tree.books_tree_utils import TreeNodeType


class TreeNodeList:

    disc_nums: list[int] = []
    part_nums: list[int] = []
    series_nums: list[int] = []
    start_nums: list[int] = []
    all_path_nums: list[list[int | float]] = []
    id3_titles: list[str] = []
    id3_albums: list[str] = []
    id3_albumartists: list[str] = []
    id3_artists: list[str] = []
    id3_disc_nums: list[int] = []
    id3_disc_total: int | None = None
    id3_track_nums: list[int] = []
    id3_track_total: int | None = None

    def __init__(self, paths: list[str | Path], curr: "TreeNodeType | None" = None):  # type: ignore
        from src.lib.id3_utils import extract_id3_tags
        from src.lib.parsers import (
            get_start_num,
        )

        if not curr:
            ...

        self._paths = [Path(p) if isinstance(p, str) else p for p in paths]
        self._node = cast("TreeNode", curr)
        if not self._paths:
            return

        self._id3 = [extract_id3_tags(p) for p in self._paths if p.is_file()]

        self.disc_nums = only_gte_0([get_disc_num(p.name) for p in self._paths])
        self.part_nums = only_gte_0([get_part_num(p.name) for p in self._paths])
        self.series_nums = only_gte_0([get_series_num(p.name) for p in self._paths])
        self.start_nums = only_gte_0([get_start_num(p.name) for p in self._paths])
        self.all_path_nums = [
            only_gte_0([n for (n, _) in get_all_nums_in_string(Path(p.name).stem)]) for p in self._paths
        ]

        self.id3_albums = [a for a in (id3.get("album", None) for id3 in self._id3) if a]
        self.id3_albumartists = [aa for aa in (id3.get("albumartist", None) for id3 in self._id3) if aa]
        self.id3_artists = [a for a in (id3.get("artist", None) for id3 in self._id3) if a]
        id3_disc_info = [get_disc_num_from_id3(id3) for id3 in self._id3]
        self.id3_disc_nums = only_gte_0([d[0] for d in id3_disc_info])
        self.id3_disc_total = max(self.id3_disc_nums) if self.id3_disc_nums else None
        self.id3_titles = [t for t in (id3.get("title", None) for id3 in self._id3) if t]
        id3_track_info = [get_track_num_from_id3(id3) for id3 in self._id3]
        self.id3_track_nums = only_gte_0([t[0] for t in id3_track_info])
        self.id3_track_total = max(self.id3_track_nums) if self.id3_track_nums else None

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

    def album_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._id3_similarity("id3_albums", comparison=comparison, distinct=distinct, include_curr=include_curr)

    def albumartist_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._id3_similarity(
            "id3_albumartists", comparison=comparison, distinct=distinct, include_curr=include_curr
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

    def artist_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._id3_similarity("id3_artists", comparison=comparison, distinct=distinct, include_curr=include_curr)

    # @property
    # def are_missing_nums(self):
    #     missing_disc_nums = self.have_disc_nums and any((x == -1 for x in self.disc_nums))
    #     missing_part_nums = self.have_part_nums and any((x == -1 for x in self.part_nums))
    #     missing_series_nums = self.have_series_nums and any((x == -1 for x in self.series_nums))
    #     missing_start_nums = self.have_start_nums and any((x == -1 for x in self.start_nums))
    #     missing_id3_track_nums = self.have_track_nums and any((x == -1 for x in self.id3_track_nums))

    #     return any(
    #         (
    #             missing_disc_nums,
    #             missing_part_nums,
    #             missing_series_nums,
    #             missing_start_nums,
    #             missing_id3_track_nums,
    #         )
    #     )

    def disc_nums_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._id3_similarity(
            "id3_disc_nums", comparison=comparison, distinct=distinct, include_curr=include_curr
        )

    @property
    def disc_nums_are_sequential(self):

        return are_nums_sequential(self.disc_nums, sort=True, skips_ok=True)

    @property
    def disc_nums_completion(self):
        """Return the ratio of disc numbers / total disc numbers, from 0-1"""
        if not self.have_disc_nums:
            return None
        return percent_truthy_in_list([x > -1 for x in self.disc_nums]) / 100

    @property
    def disc_nums_match_curr(self):

        return list_items_match_value(self.disc_nums, self._node.disc_num)

    @property
    def disc_nums_match_each_other(self):

        return list_items_match_each_other(self.disc_nums)

    @property
    def disc_nums_uniqueness(self):
        """Return the ratio of unique disc numbers to total disc numbers"""
        return get_uniqueness(self.disc_nums)

    @property
    def have_any_nums(self):
        return any([bool(x) for x in self.all_path_nums]) or self.have_disc_nums or self.have_track_nums

    @property
    def have_albums(self):
        return any([x for x in self.id3_albums])

    @property
    def have_albumartists(self):
        return any([x for x in self.id3_albumartists])

    @property
    def have_artists(self):
        return any([x for x in self.id3_artists])

    @property
    def have_disc_nums(self):
        if self.id3_disc_nums:
            return any([x > -1 for x in self.id3_disc_nums])
        return any([x > -1 for x in self.disc_nums])

    @property
    def have_part_nums(self):
        return any([x > -1 for x in self.part_nums])

    @property
    def have_series_nums(self):
        return any([x > -1 for x in self.series_nums])

    @property
    def have_start_nums(self):
        return any([x > -1 for x in self.start_nums])

    @property
    def have_track_nums(self):
        # Sometimes track numbers are written as 1/1, so we want to ignore those.
        return any([x > -1 for x in self.id3_track_nums])

    @property
    def missing_disc_nums(self):
        """If there are any disc nums, return a list of the missing ones"""

        return get_missing_nums(self.disc_nums)

    @property
    def missing_part_nums(self):

        return get_missing_nums(self.part_nums)

    @property
    def missing_series_nums(self):

        return get_missing_nums(self.series_nums)

    @property
    def missing_start_nums(self):

        return get_missing_nums(self.start_nums)

    @property
    def missing_track_nums(self):

        return get_missing_nums(self.id3_track_nums)

    @property
    def part_nums_are_sequential(self):

        return are_nums_sequential(self.part_nums, sort=True, skips_ok=True)

    @property
    def part_nums_completion(self):
        """Return the ratio of part numbers / total part numbers, from 0-1"""
        if not self.have_part_nums:
            return None
        return percent_truthy_in_list([x > -1 for x in self.part_nums]) / 100

    @property
    def part_nums_match_curr(self):

        return list_items_match_value(self.part_nums, self._node.part_num)

    @property
    def part_nums_match_each_other(self):

        return list_items_match_each_other(self.part_nums)

    @property
    def part_nums_uniqueness(self):
        """Return the ratio of unique part numbers to total part numbers"""

        return get_uniqueness(self.part_nums)

    def pathname_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        paths = [p.name for p in self._paths]
        if include_curr:
            paths.insert(0, self._node._path.name)
        if len(paths) < 2:
            return None
        return get_similarity(paths, comparison=comparison, distinct=distinct)

    @property
    def series_nums_are_sequential(self):

        return are_nums_sequential(self.series_nums, sort=True, skips_ok=True)

    @property
    def series_nums_completion(self):
        """Return the ratio of series numbers / total series numbers, from 0-1"""
        if not self.have_series_nums:
            return None
        return percent_truthy_in_list([x > -1 for x in self.series_nums]) / 100

    @property
    def series_nums_match_curr(self):
        """Returns True if all series numbers match the current's series or start number"""

        return list_items_match_value(self.series_nums, self._node.series_num)

    @property
    def series_nums_match_each_other(self):
        """Returns True if all series numbers match each other"""

        return list_items_match_each_other(self.series_nums)

    @property
    def series_nums_uniqueness(self):
        """Return the ratio of unique series numbers to total series numbers"""

        return get_uniqueness(self.series_nums)

    @property
    def score_multi_disc(self):
        """Likelihood the TreeNodeList is a multi-disc book, from 0-1"""
        if not self.have_disc_nums:
            return 0.0
        return round(percent_truthy_in_list([x > -1 for x in self.disc_nums]) / 100, 2)

    @property
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
            file_sizes = [p.stat().st_size for p in self._paths]
            largest_file_size = max(file_sizes)
            base_score += -0.5 + int(is_gt_50mb(largest_file_size))
        return round(clamp(base_score, 0.0, 1.0), 2)

    @property
    def score_series(self):
        """Likelihood the TreeNodeList is a series, from 0-1"""
        from src.lib.parsers import is_maybe_multiple_books_or_series

        # Convert percent_truthy_in_list results from 0-100 to 0-1
        multi_string_agg = (
            percent_truthy_in_list([is_maybe_multiple_books_or_series(p.name) for p in self._paths]) / 100
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

    @property
    def start_nums_are_sequential(self):
        """Returns True if all start numbers are sequential"""

        return are_nums_sequential(self.start_nums, sort=True, skips_ok=True)

    @property
    def start_nums_completion(self):
        """Return the ratio of start numbers / total start numbers, from 0-1"""
        if not self.have_start_nums:
            return None
        return percent_truthy_in_list([x > -1 for x in self.start_nums]) / 100

    @property
    def start_nums_match_curr(self):
        """Returns True if all start numbers match the current's series or start number"""

        return list_items_match_value(self.start_nums, self._node.start_num)

    @property
    def start_nums_match_each_other(self):

        return list_items_match_each_other(self.start_nums)

    @property
    def start_vs_track_nums_similarity(self):
        """Return the similarity score between the start numbers and the track numbers (0-1)"""
        if not self.have_start_nums or not self.have_track_nums:
            return None
        return get_list_similarity(self.start_nums, self.id3_track_nums)

    @property
    def start_nums_uniqueness(self):
        """Return the percentage of start numbers that are unique, from 0-1"""

        return get_uniqueness(self.start_nums)

    def title_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._id3_similarity("id3_titles", comparison=comparison, distinct=distinct, include_curr=include_curr)

    @property
    def track_nums_are_sequential(self):
        """Returns True if all track numbers are sequential"""

        return are_nums_sequential(self.id3_track_nums, sort=True, skips_ok=True)

    @property
    def track_nums_completion(self):
        """Return the ratio of track numbers / total track numbers, from 0-1"""
        if not self.have_track_nums:
            return None
        return percent_truthy_in_list([x > -1 for x in self.id3_track_nums]) / 100

    @property
    def track_nums_match_curr(self):
        """Returns True if all track numbers match the current's track number"""

        return list_items_match_value(self.id3_track_nums, self._node.id3_track_num)

    @property
    def track_nums_match_each_other(self):
        """Returns True if all track numbers match each other"""

        return list_items_match_each_other(self.id3_track_nums)

    def track_nums_similarity(
        self, comparison: SimilarityComparisonMethod | None = None, distinct: bool = True, include_curr: bool = False
    ):
        return self._id3_similarity(
            "id3_track_nums", comparison=comparison, distinct=distinct, include_curr=include_curr
        )

    @property
    def track_nums_uniqueness(self):
        """Return the percentage of track numbers that are unique, from 0-1"""

        return get_uniqueness(self.id3_track_nums)

    @property
    def unique_disc_nums(self):
        """Return a list of unique disc numbers"""

        return unique_items(self.disc_nums)

    @property
    def unique_part_nums(self):
        """Return a list of unique part numbers"""

        return unique_items(self.part_nums)

    @property
    def unique_series_nums(self):
        """Return a list of unique series numbers"""

        return unique_items(self.series_nums)

    @property
    def unique_start_nums(self):
        """Return a list of unique start numbers"""

        return unique_items(self.start_nums)

    @property
    def unique_track_nums(self):
        """Return a list of unique track numbers"""

        return unique_items(self.id3_track_nums)

    def _id3_similarity(
        self,
        prop: str,
        comparison: SimilarityComparisonMethod | None = None,
        distinct: bool = True,
        *,
        include_curr: bool = False,
    ):
        values = getattr(self, prop)
        if include_curr and (curr := getattr(self._node, prop, None)) and curr:
            values.insert(0, curr)
        if len(values) < 2:
            return None
        return get_similarity(values, comparison=comparison, distinct=distinct)
