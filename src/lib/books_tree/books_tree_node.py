from pathlib import Path
from typing import Literal, Self, TYPE_CHECKING

from lazy.lazy import lazy

from lib.books_tree.books_tree_utils import (
    get_all_nums_in_string,
    get_part_num,
)
from lib.parsers import get_disc_num, get_series_num
from src.lib.id3_tags import Id3Tags
from src.lib.term import print_warning

if TYPE_CHECKING:
    from src.lib.books_tree.books_tree import BooksTree


class TreeNode:
    disc_num: int = -1
    part_num: int = -1
    series_num: int = -1
    start_num: int = -1
    all_nums: list[int | float] = []
    id3_title: str | None = None
    id3_album: str | None = None
    id3_albumartist: str | None = None
    id3_artist: str | None = None
    id3_disc_num: int = -1
    id3_disc_total: int = -1
    id3_track_num: int = -1
    id3_track_total: int = -1
    _curr: Self | None = None
    _id3: Id3Tags | None = None

    def __init__(self, tree: "BooksTree", curr: Self | None = None):
        from src.lib.config import cfg
        from src.lib.parsers import get_start_num

        # Check if it matches INBOX_DIR and if so, abort
        if tree.path == cfg.inbox_dir:
            print_warning(f"TreeNode: {tree} is the INBOX_DIR, this should not happen")
            return

        self._tree = tree
        self._curr = curr
        self._id3 = tree.id3_tags
        if self._id3:
            self.id3_album = self._id3.album
            self.id3_albumartist = self._id3.albumartist
            self.id3_artist = self._id3.artist
            self.id3_disc_num = self._id3.disc_num or -1
            self.id3_disc_total = self._id3.disc_total or -1
            self.id3_title = self._id3.title
            self.id3_track_num = self._id3.track_num or -1
            self.id3_track_total = self._id3.track_total or -1
        self.disc_num = get_disc_num(self._tree.name)
        self.part_num = get_part_num(self._tree.name)
        self.series_num = get_series_num(self._tree.name)
        self.start_num = get_start_num(self._tree.name)
        self.all_nums = [n for (n, _) in get_all_nums_in_string(Path(self._tree.name).stem)]

    def __repr__(self):
        return f"{{d: {self.disc_num}, p: {self.part_num}, s: {self.series_num}, ^: {self.start_num}}}"

    def __str__(self):
        return self.__repr__()

    def is_maybe(self, structure: Literal["multi_disc", "multi_part", "series", "unknown"]) -> bool:
        match structure:
            case "multi_disc":
                return self.has_disc_num
            case "multi_part":
                return self.has_track_num or self.has_part_num
            case "series":
                return self.has_series_num or self.has_start_num
            case "unknown":
                return not any((self.is_maybe("multi_disc"), self.is_maybe("multi_part"), self.is_maybe("series")))

    @lazy
    def has_disc_num(self):
        return self.disc_num > -1 or self.has_id3_disc_num

    @lazy
    def has_id3_disc_num(self):
        return self.id3_disc_num > -1

    @lazy
    def has_part_num(self):
        return self.part_num > -1

    @lazy
    def has_track_num(self):
        return self.id3_track_num > -1

    @lazy
    def has_series_num(self):
        return self.series_num > -1

    @lazy
    def has_start_num(self):
        return self.start_num > -1

    @lazy
    def has_any_num(self):
        return bool(self.all_nums) or self.id3_disc_num > -1 or self.id3_track_num > -1

    @lazy
    def disc_num_matches_curr(self):
        disc_num = self.id3_disc_num if self.id3_disc_num > -1 else self.disc_num
        return self._curr and self._curr.disc_num > -1 and disc_num == self._curr.disc_num

    @lazy
    def part_num_matches_curr(self):
        return self._curr and self._curr.part_num > -1 and self.part_num == self._curr.part_num

    @lazy
    def series_num_matches_curr(self):
        return self._curr and self._curr.series_num > -1 and self.series_num == self._curr.series_num

    @lazy
    def start_num_matches_curr(self):
        return self._curr and self._curr.start_num > -1 and self.start_num == self._curr.start_num

    @lazy
    def track_num_matches_curr(self):
        return self._curr and self._curr.id3_track_num > -1 and self.id3_track_num == self._curr.id3_track_num

    @lazy
    def start_num_matches_disc_num(self):
        return self.disc_num > -1 and self.start_num > -1 and self.disc_num == self.start_num

    @lazy
    def start_num_matches_part_num(self):
        return self.part_num > -1 and self.start_num > -1 and self.part_num == self.start_num

    @lazy
    def start_num_matches_series_num(self):
        return self.series_num > -1 and self.start_num > -1 and self.series_num == self.start_num

    @lazy
    def start_num_matches_track_num(self):
        return self.id3_track_num > -1 and self.start_num > -1 and self.id3_track_num == self.start_num

    @lazy
    def any_num_matches_curr(self):
        return bool(
            self._curr
            and any(
                [
                    self.disc_num_matches_curr,
                    self.part_num_matches_curr,
                    self.series_num_matches_curr,
                    self.start_num_matches_curr,
                    self.track_num_matches_curr,
                ]
            )
        )
