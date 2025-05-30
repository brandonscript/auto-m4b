from pathlib import Path
from typing import Self, TYPE_CHECKING

from lazy.lazy import lazy

from src.lib.books_tree.books_tree_utils import (
    get_all_nums_in_string,
    get_part_num,
)
from src.lib.id3_tags import Id3Tags
from src.lib.parsers import get_disc_num, get_series_num
from src.lib.term import print_warning

if TYPE_CHECKING:
    from src.lib.books_tree.books_tree import BooksTree


class TreeNode:
    disc_num: int = -1
    part_num: int = -1
    series_num: int = -1
    start_num: int = -1
    all_nums: list[int | float] = []
    pathname: str = ""
    id3_title: str | None = None
    id3_album: str | None = None
    id3_albumartist: str | None = None
    id3_artist: str | None = None
    id3_disc_num: int = -1
    id3_disc_total: int = -1
    id3_track_num: int = -1
    id3_track_total: int = -1
    _curr: Self | None = None
    id3_tags: Id3Tags | None = None

    def __init__(self, tree: "BooksTree", curr: Self | None = None):
        from src.lib.config import cfg
        from src.lib.parsers import get_start_num

        # Check if it matches INBOX_DIR and if so, abort
        if tree.path == cfg.inbox_dir:
            print_warning(f"TreeNode: {tree} is the INBOX_DIR, this should not happen")
            return

        self._tree = tree
        self._curr = curr
        self.id3_tags = tree.id3_tags
        if self.id3_tags:
            self.id3_album = self.id3_tags.album
            self.id3_albumartist = self.id3_tags.albumartist
            self.id3_artist = self.id3_tags.artist
            self.id3_disc_num = self.id3_tags.disc_num or -1
            self.id3_disc_total = self.id3_tags.disc_total or -1
            self.id3_title = self.id3_tags.title
            self.id3_track_num = self.id3_tags.track_num or -1
            self.id3_track_total = self.id3_tags.track_total or -1
        self.pathname = self._tree.name
        self.disc_num = get_disc_num(self._tree.name)
        self.part_num = get_part_num(self._tree.name)
        self.series_num = get_series_num(self._tree.name)
        self.start_num = get_start_num(self._tree.name)
        self.all_nums = [n for (n, _) in get_all_nums_in_string(Path(self._tree.name).stem)]

    def __repr__(self):

        disc = f"💽 {self.disc_num}" if self.disc_num > -1 else ""
        part = f"🎉 {self.part_num}" if self.part_num > -1 else ""
        series = f"📺 {self.series_num}" if self.series_num > -1 else ""
        start = f"🔥 {self.start_num}" if self.start_num > -1 else ""

        info = " ".join((str(v) for v in [disc, part, series, start] if v)).strip()
        return f"{self._tree.rel_path} {info}"

    def __str__(self):
        return self.__repr__()

    @classmethod
    def empty(cls, tree: "BooksTree"):
        empty = cls.__new__(cls)
        empty._tree = tree
        empty._curr = None
        empty.id3_tags = None
        empty.pathname = "__root__"
        empty.disc_num = -1
        empty.part_num = -1
        empty.series_num = -1
        empty.start_num = -1
        empty.all_nums = []
        return empty

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
