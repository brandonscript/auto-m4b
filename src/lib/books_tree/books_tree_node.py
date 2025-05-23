from pathlib import Path
from typing import cast, Literal, Self, TYPE_CHECKING

from lib.books_tree.books_tree_utils import (
    get_all_nums_in_string,
    get_disc_num_from_id3,
    get_part_num,
    get_track_num_from_id3,
)
from lib.fs_utils import only_audio_files
from lib.parsers import get_disc_num, get_series_num
from src.lib.term import print_warning
from src.lib.typing import Id3TagDict

if TYPE_CHECKING:
    pass


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
    _id3: Id3TagDict | dict[str, Id3TagDict] = {}

    def __init__(self, path: str | Path, curr: Self | None = None):

        from src.lib.config import cfg

        # Check if it matches INBOX_DIR and if so, abort
        if Path(path) == cfg.inbox_dir:
            print_warning(f"TreeNode: {path} is the INBOX_DIR, this should not happen")
            return

        from src.lib.id3_utils import extract_id3_tags
        from src.lib.parsers import (
            get_start_num,
        )

        self._path = Path(path) if isinstance(path, str) else path
        self._curr = curr
        self._id3 = {}
        if self._path.is_file():
            self._id3 = cast(Id3TagDict, extract_id3_tags(self._path))
        elif self._path.is_dir() and len((audio_files := only_audio_files(self._path.glob("*")))) == 1:
            # If there is only one audio file in the directory, we can use that to get id3
            self._id3 = cast(Id3TagDict, extract_id3_tags(audio_files[0]))
        if self._id3:
            self.id3_album = self._id3.get("album", "")
            self.id3_albumartist = self._id3.get("albumartist", "")
            self.id3_artist = self._id3.get("artist", "")
            self.id3_disc_num, self.id3_disc_total = get_disc_num_from_id3(self._id3)
            self.id3_title = self._id3.get("title", "")
            self.id3_track_num, self.id3_track_total = get_track_num_from_id3(cast(Id3TagDict, self._id3))
        self.disc_num = get_disc_num(self._path.name)
        self.part_num = get_part_num(self._path.name)
        self.series_num = get_series_num(self._path.name)
        self.start_num = get_start_num(self._path.name)
        self.all_nums = [n for (n, _) in get_all_nums_in_string(Path(self._path.name).stem)]

    def __repr__(self):
        return f"{{d: {self.disc_num}, p: {self.part_num}, s: {self.series_num}, ^: {self.start_num}}}"

    def __str__(self):
        return self.__repr__()

    # @property
    # def best_num(self):
    #     return next(
    #         (
    #             n
    #             for n in [
    #                 self._id3_disc_num,
    #                 self.id3_track_num,
    #                 self.disc_num,
    #                 self.part_num,
    #                 self.series_num,
    #                 self.start_num,
    #             ]
    #             if n > -1
    #         ),
    #         -1,
    #     )

    # def is_maybe(self, structure: Literal["multi_disc", "multi_part", "series", "unknown"]) -> bool:
    #     md = self.score_multi_disc or 0
    #     mp = self.score_multi_part or 0
    #     s = self.score_series() or 0

    #     match structure:
    #         case "multi_disc":
    #             return md > mp and md > s
    #         case "multi_part":
    #             return mp > md and mp > s
    #         case "series":
    #             return s > md and s > mp
    #         case "unknown":
    #             return not any(
    #                 (self.are_maybe("multi_disc"), self.are_maybe("multi_part"), self.are_maybe("series"))
    # )
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

    @property
    def has_disc_num(self):
        return self.disc_num > -1 or self.has_id3_disc_num

    @property
    def has_id3_disc_num(self):
        return self.id3_disc_num > -1

    @property
    def has_part_num(self):
        return self.part_num > -1

    @property
    def has_track_num(self):
        return self.id3_track_num > -1

    @property
    def has_series_num(self):
        return self.series_num > -1

    @property
    def has_start_num(self):
        return self.start_num > -1

    @property
    def has_any_num(self):
        return bool(self.all_nums) or self.id3_disc_num > -1 or self.id3_track_num > -1

    @property
    def disc_num_matches_curr(self):
        disc_num = self.id3_disc_num if self.id3_disc_num > -1 else self.disc_num
        return self._curr and self._curr.disc_num > -1 and disc_num == self._curr.disc_num

    @property
    def part_num_matches_curr(self):
        return self._curr and self._curr.part_num > -1 and self.part_num == self._curr.part_num

    @property
    def series_num_matches_curr(self):
        return self._curr and self._curr.series_num > -1 and self.series_num == self._curr.series_num

    @property
    def start_num_matches_curr(self):
        return self._curr and self._curr.start_num > -1 and self.start_num == self._curr.start_num

    @property
    def track_num_matches_curr(self):
        return self._curr and self._curr.id3_track_num > -1 and self.id3_track_num == self._curr.id3_track_num

    @property
    def start_num_matches_disc_num(self):
        return self.disc_num > -1 and self.start_num > -1 and self.disc_num == self.start_num

    @property
    def start_num_matches_part_num(self):
        return self.part_num > -1 and self.start_num > -1 and self.part_num == self.start_num

    @property
    def start_num_matches_series_num(self):
        return self.series_num > -1 and self.start_num > -1 and self.series_num == self.start_num

    @property
    def start_num_matches_track_num(self):
        return self.id3_track_num > -1 and self.start_num > -1 and self.id3_track_num == self.start_num

    @property
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
