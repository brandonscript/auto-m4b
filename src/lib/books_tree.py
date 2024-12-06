import re
import time
from collections.abc import Callable, Sequence
from functools import cached_property
from pathlib import Path
from typing import Any, cast, Literal, overload, Self, TYPE_CHECKING, TypeVar

from pydantic import BaseModel, Field

from src.lib.misc import (
    any_in,
    any_matching,
    flatlist,
    isorted,
    percent_truthy_in_list,
)
from src.lib.term import print_debug, print_warning
from src.lib.typing import AudiobookFmt, BookStructure2, copy_kwargs

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook


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
        list[Path | BooksTree] | str,
        (
            [try_relative_to(str(p), root or Path()) for p in match_filter]
            if isinstance(match_filter, list)
            else match_filter
        ),
    )

    def _is_wanted_path(t: BooksTree | Path | str | None):
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


NumDictType = TypeVar("NumDictType", bound="TreeNumInfo.NumDict")


class TreeNumInfo:
    # We're going to add the following functions into this class so we can use them in the determine_structure method
    # num_funcs = [get_disc_no, get_part_no, get_series_no, get_start_no]
    # (And since they com back as an array of different num funcs, we'll use them by name instead of by index)

    # curr_nums = [f(self.path.name) for f in num_funcs]
    # curr_has_nums: list[bool] = [n > -1 for n in curr_nums]
    # parent_nums = [f(parent.path.name) for f in num_funcs]
    # parent_has_nums: list[bool] = [n > -1 for n in parent_nums]
    # children_nums = [[f(c.path.name) for f in num_funcs] for c in self.children]
    # children_have_nums = [[n > -1 for n in nums] for nums in children_nums]
    # sibling_nums = [[f(s.path.name) for f in num_funcs] for s in siblings]
    # siblings_have_nums = [[n > -1 for n in nums] for nums in sibling_nums]

    curr: "NumDict"
    parent: "NumDict | None"
    children: "ArrNumDict"
    siblings: "ArrNumDict"

    def __init__(self, tree: "BooksTree"):

        self._tree = tree
        self.curr = self.NumDict(tree.path.name)
        self.parent = self.NumDict(tree.parent.path.name, self.curr) if tree.parent else None
        self.children = self.ArrNumDict([c.path.name for c in tree.children], self.curr)
        self.children_recursive = self.ArrNumDict([c.path.name for c in tree.children_recursive], self.curr)
        self.files = self.ArrNumDict([f.path.name for f in tree.files], self.curr)
        self.files_recursive = self.ArrNumDict([f.path.name for f in tree.files_recursive], self.curr)
        self.dirs = self.ArrNumDict([d.path.name for d in tree.dirs.values()], self.curr)
        self.dirs_recursive = self.ArrNumDict([d.path.name for d in tree.dirs_recursive], self.curr)
        self.siblings = self.ArrNumDict([s.path.name for s in (tree.siblings or [])], self.curr)

    def __repr__(self):
        likely = (
            "series"
            if self.is_likely_series
            else "multi_disc" if self.is_likely_multi_disc else "multi_part" if self.is_likely_multi_part else "unknown"
        )
        return f"{self.curr._path}: likely {likely}"

    def __str__(self):
        return self.__repr__()

    @property
    def is_likely_series(self) -> bool:
        _is_likely_series = [
            self.curr.is_likely("series"),
            self.children.are_likely("series"),
            self.siblings.are_likely("series"),
        ].count(True) >= 2
        if (
            _is_likely_series
            and self._tree.is_file()
            and (cr := self._tree.container_root)
            and (parent := self._tree.parent)
        ):
            size_gt_100mb = self._tree.size > 100 * 1e6
            _container_root_files_similarity = cr.ni.files_recursive.similarity
            sibling_files_similarity = parent.ni.children.similarity

            parent_siblings_likely_series = bool(
                (parent := self._tree.parent) and parent.depth > 1 and parent.ni.siblings.are_likely("series")
            )
            sibling_files_likely_series = False

            _is_likely_series = (
                self._tree.is_file()
                and parent_siblings_likely_series
                and ((size_gt_100mb or not sibling_files_similarity > 0.5 or sibling_files_likely_series))
            )
        # if self._tree.is_file() and (parent := self._tree.parent):
        #     files_only_too_similar = self.siblings.similarity > 0.5 and not parent._dirs
        #     mixed_too_similar = self.siblings.similarity > 0.7 and parent.has_files_and_dirs
        # else:
        #     files_only_too_similar = self.children.similarity > 0.5 and not self._tree._dirs
        #     mixed_too_similar = self.children.similarity > 0.7 and self._tree.has_files_and_dirs
        # parent = self._tree.parent
        # num_sibling_mp3s = len(parent._files_of_type("mp3") if parent else [])
        # num_sibling_m4bs = len(parent._files_of_type("m4b") if parent else [])
        # num_sibling_m4as = len(parent._files_of_type("m4a") if parent else [])
        # num_sibling_wmas = len(parent._files_of_type("wma") if parent else [])
        # has_multiple_file_types = sum(x > 0 for x in [num_sibling_mp3s, num_sibling_m4bs, num_sibling_m4as, num_sibling_wmas]) >= 2
        # primary_file_type, primary_type_count = max(
        #     [("mp3", num_sibling_mp3s), ("m4b", num_sibling_m4bs), ("m4a", num_sibling_m4as), ("wma", num_sibling_wmas)],
        #     key=lambda x: x[1],
        # )

        return (
            _is_likely_series
            and not self.siblings.nums_match_each_other
            and not self.siblings.are_missing_nums
            # and (size_gt_100mb or not (files_only_too_similar or mixed_too_similar))
            # primary_type_count,
        )

    @property
    def is_likely_multi_disc(self):
        return [
            self.curr.is_likely("multi_disc"),
            self.children.are_likely("multi_disc"),
            self.siblings.are_likely("multi_disc"),
        ].count(True) >= 2

    @property
    def is_likely_multi_part(self):
        return [
            self.curr.is_likely("multi_part"),
            self.children.are_likely("multi_part"),
            self.siblings.are_likely("multi_part"),
        ].count(True) >= 2

    class NumDict:
        disc_num: int = -1
        part_num: int = -1
        series_num: int = -1
        start_num: int = -1
        all_nums: list[int | float] = []
        _curr: Self | None = None

        def __init__(self, path: str, curr: Self | None = None):

            from src.lib.parsers import (
                get_all_nums_in_string,
                get_disc_num,
                get_part_num,
                get_series_num,
                get_start_num,
            )

            self._path = path
            self._curr = curr
            self.disc_num = get_disc_num(path)
            self.part_num = get_part_num(path)
            self.series_num = get_series_num(path)
            self.start_num = get_start_num(path)
            self.all_nums = [n for (n, _) in get_all_nums_in_string(Path(path).stem)]

        def __repr__(self):
            return f"{{d: {self.disc_num}, p: {self.part_num}, s: {self.series_num}, ^: {self.start_num}}}"

        def __str__(self):
            return self.__repr__()

        @property
        def best_num(self):
            return next((n for n in [self.disc_num, self.part_num, self.series_num, self.start_num] if n > -1), -1)

        def is_likely(self, structure: Literal["multi_disc", "multi_part", "series", "unknown"]) -> bool:
            match structure:
                case "multi_disc":
                    return self.has_disc_num
                case "multi_part":
                    return self.has_part_num
                case "series":
                    return self.has_series_num or self.has_start_num
                case "unknown":
                    return not any(
                        (self.is_likely("multi_disc"), self.is_likely("multi_part"), self.is_likely("series"))
                    )

        @property
        def has_disc_num(self):
            return self.disc_num > -1

        @property
        def has_part_num(self):
            return self.part_num > -1

        @property
        def has_series_num(self):
            return self.series_num > -1

        @property
        def has_start_num(self):
            return self.start_num > -1

        @property
        def has_any_num(self):
            return bool(self.all_nums)

        @property
        def disc_num_matches_curr(self):
            return self._curr and self._curr.disc_num > -1 and self.disc_num == self._curr.disc_num

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
        def any_num_matches_curr(self):
            return self._curr and any(
                [
                    self.disc_num_matches_curr,
                    self.part_num_matches_curr,
                    self.series_num_matches_curr,
                    self.start_num_matches_curr,
                ]
            )

    class ArrNumDict:
        disc_nums: list[int] = []
        part_nums: list[int] = []
        series_nums: list[int] = []
        start_nums: list[int] = []
        all_nums: list[list[int | float]] = []

        def __init__(self, paths: list[str], curr: NumDictType | None = None):  # type: ignore

            from src.lib.parsers import (
                get_all_nums_in_string,
                get_disc_num,
                get_part_num,
                get_series_num,
                get_start_num,
            )

            self._paths = paths
            self._curr = cast(TreeNumInfo.NumDict, curr)
            self.disc_nums = [get_disc_num(p) for p in paths]
            self.part_nums = [get_part_num(p) for p in paths]
            self.series_nums = [get_series_num(p) for p in paths]
            self.start_nums = [get_start_num(p) for p in paths]
            self.all_nums = [[n for (n, _) in get_all_nums_in_string(Path(p).stem)] for p in paths]

        def __repr__(self):
            return f"{{d: {self.disc_nums}, p: {self.part_nums}, s: {self.series_nums}, ^: {self.start_nums}}}, sim: {self.similarity}"

        def __str__(self):
            return self.__repr__()

        @property
        def best_nums(self):
            return [
                next((n for n in [d, p, s, st] if n > -1), -1)
                for d, p, s, st in zip(self.disc_nums, self.part_nums, self.series_nums, self.start_nums)
            ]

        @property
        def have_disc_nums(self):
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
        def have_any_nums(self):
            return any([bool(x) for x in self.all_nums])

        def are_likely(self, structure: Literal["multi_disc", "multi_part", "series", "unknown"]) -> bool:
            match structure:
                case "multi_disc":
                    return self.have_disc_nums and self.maybe_multi_disc > 0
                case "multi_part":
                    return self.have_part_nums and self.maybe_multi_part > 0
                case "series":
                    return (self.have_series_nums or self.have_start_nums) and self.maybe_series > 0
                case "unknown":
                    return not any(
                        (self.are_likely("multi_disc"), self.are_likely("multi_part"), self.are_likely("series"))
                    )

        @property
        def maybe_multi_disc(self):
            return percent_truthy_in_list([x > -1 for x in self.disc_nums])

        @property
        def maybe_multi_part(self):
            return percent_truthy_in_list([x > -1 for x in self.part_nums])

        @property
        def maybe_series(self):
            from src.lib.parsers import is_maybe_multiple_books_or_series

            check1 = percent_truthy_in_list([is_maybe_multiple_books_or_series(p) for p in self._paths])
            check2 = percent_truthy_in_list([x > -1 for x in self.series_nums])
            check3 = percent_truthy_in_list([x > -1 for x in self.start_nums])

            return max([check1, check2, check3])

        @property
        def are_missing_nums(self):
            missing_disc_nums = self.have_disc_nums and any((x == -1 for x in self.disc_nums))
            missing_part_nums = self.have_part_nums and any((x == -1 for x in self.part_nums))
            missing_series_nums = self.have_series_nums and any((x == -1 for x in self.series_nums))
            missing_start_nums = self.have_start_nums and any((x == -1 for x in self.start_nums))

            return any((missing_disc_nums, missing_part_nums, missing_series_nums, missing_start_nums))

        @property
        def nums_are_sequential(self):
            return any(
                (
                    self.disc_nums_are_sequential,
                    self.part_nums_are_sequential,
                    self.series_nums_are_sequential,
                    self.start_nums_are_sequential,
                )
            )

        @property
        def disc_nums_match_each_other(self) -> bool:
            return all((self.have_disc_nums, *[c == self.disc_nums[0] for c in self.disc_nums]))

        @property
        def part_nums_match_each_other(self) -> bool:
            return all((self.have_part_nums, *[c == self.part_nums[0] for c in self.part_nums]))

        @property
        def series_nums_match_each_other(self) -> bool:
            return all((self.have_series_nums, *[c == self.series_nums[0] for c in self.series_nums]))

        @property
        def start_nums_match_each_other(self) -> bool:
            return all((self.have_start_nums, *[c == self.start_nums[0] for c in self.start_nums]))

        @property
        def nums_match_each_other(self):
            return all(
                (
                    self.disc_nums_match_each_other,
                    self.part_nums_match_each_other,
                    self.series_nums_match_each_other,
                    self.start_nums_match_each_other,
                )
            )

        @property
        def disc_nums_match_curr(self):
            return all((self._curr.has_disc_num, *[x == self._curr.disc_num for x in self.disc_nums]))

        @property
        def part_nums_match_curr(self):
            return all((self._curr.has_part_num, *[x == self._curr.part_num for x in self.part_nums]))

        @property
        def series_nums_match_curr(self):
            """Returns True if all series numbers match the current's series or start number"""
            return all((self._curr.has_start_num, *[x == self._curr.start_num for x in self.series_nums])) or all(
                (self._curr.has_series_num, *[x == self._curr.series_num for x in self.series_nums])
            )

        @property
        def start_nums_match_curr(self):
            """Returns True if all start numbers match the current's series or start number"""
            return all((self._curr.has_start_num, *[x == self._curr.start_num for x in self.start_nums])) or all(
                (self._curr.has_series_num, *[x == self._curr.series_num for x in self.start_nums])
            )

        @property
        def any_no_matches_curr(self):
            return self._curr and any(
                [
                    self.disc_nums_match_curr,
                    self.part_nums_match_curr,
                    self.series_nums_match_curr,
                    self.start_nums_match_curr,
                ]
            )

        @property
        def disc_nums_are_sequential(self):
            from src.lib.parsers import are_nums_sequential

            return self.have_disc_nums and are_nums_sequential(self.disc_nums, sort=True, skips_ok=True)

        @property
        def part_nums_are_sequential(self):
            from src.lib.parsers import are_nums_sequential

            return self.have_part_nums and are_nums_sequential(self.part_nums, sort=True, skips_ok=True)

        @property
        def series_nums_are_sequential(self):
            from src.lib.parsers import are_nums_sequential

            return self.have_series_nums and are_nums_sequential(self.series_nums, sort=True, skips_ok=True)

        @property
        def start_nums_are_sequential(self):
            from src.lib.parsers import are_nums_sequential

            return self.have_start_nums and are_nums_sequential(self.start_nums, sort=True, skips_ok=True)

        def _similarity(self, median: bool = False, distinct: bool = False):
            from src.lib.fs_utils import get_similarity

            if not self._paths:
                return 0.0

            return get_similarity(self._paths, distinct=distinct, median=median)

        @property
        def similarity(self):
            return self._similarity()

        @property
        def median_similarity(self):
            return self._similarity(median=True)

        @property
        def distinct_similarity(self):
            return self._similarity(distinct=True)

        @property
        def similarity_to_curr(self):
            from src.lib.fs_utils import get_similarity

            if not self._paths:
                return 0.0

            curr = [self._curr._path] if self._curr else []
            return get_similarity([*curr, *self._paths], distinct=True)


F = TypeVar("F", bound="Callable[..., Any]")


def requires_scan(func: F) -> F:
    def wrapper(self: "BooksTree", *args, **kwargs):
        if (root := self if self.is_root else self.root) and root and not root._last_scan:
            raise ValueError(f"Cannot call 'BooksTree.{func.__name__}' without first scanning the tree")

        return func(self, *args, **kwargs)

    return cast(F, wrapper)


def requires_structure(func: F) -> F:
    def wrapper(self: "BooksTree", *args, **kwargs):
        if not self.structure:
            raise ValueError(f"Cannot call 'BooksTree.{func.__name__}' without first determining this node's structure")

        return func(self, *args, **kwargs)

    return cast(F, wrapper)


class BooksTree(BaseModel):
    _is_file: bool | None = None
    _is_dir: bool | None = None
    _is_book_root: bool | None = None
    path: Path = Field(default_factory=Path)
    parent: "BooksTree | None" = None
    size: int = 0
    # mindepth: int | None = None
    # maxdepth: int | None = None
    structure: tuple[BookStructure2, ...] = Field(default_factory=tuple)
    root: "BooksTree | None" = None
    _match_filter: list[Path] | str | None = None
    _last_scan: float | None = None

    model_config = {
        "arbitrary_types_allowed": True,
    }

    def __init__(
        self,
        path: "Path | Audiobook | BooksTree | str" = ".",
        *,
        root: "Path | Audiobook | BooksTree | None" = None,
        # files: Sequence["str | Path | BooksTree"] = [],
        # dirs: Mapping[str, "str | Path | BooksTree"] = {},
        mindepth: int | None = None,
        maxdepth: int | None = None,
        allow_file_root: bool = False,
        match_filter: list[Path] | str | None = None,
        # structure: tuple[BookStructure2, ...] = (),
        # size: int = 0,
        scan: bool | None = None,
        determine_structure: bool = True,
    ):
        super().__init__()
        if isinstance(path, BooksTree):
            self.__dict__.update(path.__dict__)
            return

        from src.lib.audiobook import Audiobook
        from src.lib.config import cfg

        self.path = path.path if isinstance(path, (Audiobook, self.__class__)) else Path(path)
        self.root = (
            root
            if isinstance(root, BooksTree)
            else BooksTree(root, scan=False, match_filter=match_filter) if root is not None else None
        )
        self._files: list["BooksTree"] = []
        self._dirs: dict[str, "BooksTree"] = {}

        # if files:
        #     self.files = [BooksTree(f, root=self.root, scan=False) for f in files]
        # if dirs:
        #     self.dirs = {k: BooksTree(v, root=self.root, scan=False) for k, v in dirs.items()}
        self._match_filter = match_filter or cfg.MATCH_FILTER
        if scan or (scan is None and not root):
            self.scan(
                mindepth=mindepth,
                maxdepth=maxdepth,
                allow_file_root=allow_file_root,
                determine_structure=determine_structure,
            )
        # self.size = size
        # if structure:
        #     self.structure = structure

    def __repr__(self):
        return f"BooksTree({self.path})"

    def __str__(self):
        return str(self.path)

    # Pydantic built-ins/overrides
    def model_post_init(self, __context):
        self.root = None if self.root is None else BooksTree(self.root, scan=False)

    @classmethod
    def cast(
        cls,
        path: "Path | BooksTree | str",
        *,
        root: "Path | BooksTree | None",
        match_filter: list[Path] | str | None = None,
    ):
        """Casts a path to a TreePath without scanning it"""
        return BooksTree(path, root=root, scan=False, match_filter=match_filter)

    def _scan(
        self,
        *,
        mindepth: int | None = None,
        maxdepth: int | None = None,
        allow_file_root: bool = False,
        allow_non_root: bool = False,
        determine_structure: bool = True,
    ):

        from src.lib.fs_utils import filter_depth, filter_ignored, only_audio_files

        root: Self | BooksTree = self if self.is_root or not self.root else self.root

        if not self.is_root and not allow_non_root:
            raise RuntimeError("scan() should only be called on the root of the tree")

        if not root.exists():
            return self

        if root.is_file() and allow_file_root:
            return self

        # Do a recursive glob of all files in the directory, and prepend the root so we can get standalone files
        rglob = isorted([root.path, *root.path.rglob("*")])

        self._files = []
        self._dirs = {}

        # Function to recursively add keys to the tree dict
        def _add_to_tree(at_path: Path, audio_files: Sequence[Path | BooksTree]):
            rel_path = at_path.relative_to(root.path)
            parts = rel_path.parts
            subtree = self
            for i, part in enumerate(parts):
                if part not in subtree._dirs:
                    parent_p = Path(root.path, *parts[: i + 1])
                    subtree._dirs[part] = BooksTree.cast(parent_p, root=root, match_filter=self.match_filter)
                subtree = subtree._dirs[part]
            subtree._files = isorted(
                [BooksTree.cast(p, root=root, match_filter=self.match_filter) for p in [*subtree._files, *audio_files]]
            )

        # Build a tree of the audio files and dirs
        for d in [x for x in rglob if x.is_dir()]:
            # If d is not within the mindepth and maxdepth, skip it
            if not filter_depth(d, root.path, mindepth=mindepth, maxdepth=maxdepth):
                continue

            # If x is a dir, make sure the path and its parents exists in the tree
            audio_files_in_dir = [
                f
                for f in only_audio_files(filter_ignored(rglob))
                if f.parent == d and filter_depth(f, root.path, mindepth=mindepth, maxdepth=maxdepth, offset=-1)
            ]
            if audio_files_in_dir:
                _add_to_tree(d, audio_files_in_dir)

        # Add files from the current level to self.files
        self._files = isorted(
            [
                BooksTree.cast(f, root=root)
                for f in only_audio_files(filter_ignored(rglob))
                if f.parent == self.path and filter_depth(f, root.path, mindepth=mindepth, maxdepth=maxdepth, offset=-1)
            ]
        )

        self._last_scan = time.time()
        if determine_structure:
            self.determine_structure()
        return self

    @copy_kwargs(_scan)
    def scan(self, *args, **kwargs) -> "BooksTree":
        """Given a path, returns a TreePath of all directories containing audio files, and their subdirectories, and the audio files within them.
        E.g., if the directory is:
        /path/to/dir

        it could return:

        {
            files: [
                "/path/to/dir/file1.mp3",
                "/path/to/dir/file2.mp3"
            ],
            dirs: {
                    "subdir1": {
                        files: [
                            "/path/to/dir/subdir1/file3.mp3",
                            "/path/to/dir/subdir1/file4.mp3"
                        ]
                    },
                    "subdir2": {
                        files: [
                            "/path/to/dir/subdir2/file5.mp3",
                            "/path/to/dir/subdir2/file6.mp3"
                        ]
                    }
                }
            }
        }
        """

        self._scan(*args, **kwargs)
        self._last_scan = time.time()
        return self

    def get(self, rel: "str | Path | BooksTree"):
        """
        Gets a file or directory from the tree by its relative path (string), Path, or TreePath object.

        Returns the TreePath object for the file or dir if it exists, otherwise None

        Examples:
        >>> tree.get("file1.mp3")
        >>> tree.get(Path("file1.mp3"))
        >>> tree.get(TreePath("file1.mp3"), allow_file_root=True)
        >>> tree.get("subdir")
        >>> tree.get("subdir/nested/file1.mp3")
        """
        if not rel:
            raise ValueError(".get(): Key cannot be empty")
        if isinstance(rel, BooksTree):
            rel = rel.path
        if isinstance(rel, str):
            rel = Path(rel)
        if isinstance(rel, Path) and rel.is_absolute():
            rel = rel.relative_to(self.root.path if self.root else self.path)
        if rel == Path("."):
            return self

        # Find the path in self.children_recursive
        return next((c for c in self.children_recursive if c.key == rel or c.rel_path == rel), None)

    def get_like(self, key: str, case_sensitive: bool = False):
        """
        Gets a file or directory from the tree by a partial match or regex of its name.
        """
        if not key:
            raise ValueError(".get_like(): Key cannot be empty")
        exp = re.compile(key, re.I) if not case_sensitive else re.compile(key)
        return next(
            (c for c in self.children_recursive if (c.key and exp.search(c.key)) or exp.search(str(c.rel_path))), None
        )

    @property
    def match_filter(self) -> list[Path] | str | None:
        from src.lib.config import cfg

        return self._match_filter or (self.root.match_filter if self.root else cfg.MATCH_FILTER)

    @property
    def rel_path(self):
        return Path(self.path.relative_to(self.root.path) if self.root else self.path.name)

    def count_files(
        self,
        *,
        mindepth: int | None = None,
        maxdepth: int | None = None,
    ) -> int:
        """
        Count the number of audio files in a directory and its subdirectories.

        Parameters:
        mindepth (int | None, optional): The minimum depth of directories to search. This is 0-based,
                                         so a mindepth of 0 includes files directly in the base directory.
                                         Defaults to None, which includes all depths.
        maxdepth (int | None, optional): The maximum depth of directories to search. This is 0-based,
                                         so a maxdepth of 0 includes only files directly in the base directory.
                                         Defaults to None, which includes all depths.

        Returns:
        int: The number of audio files found.
        """

        return len(self.__class__(self.path, root=self.root, mindepth=mindepth, maxdepth=maxdepth).files_recursive)

    @property
    def name(self):
        return self.path.name

    @property
    def key(self):
        if not (root := self.root):
            print_debug(f"No root found for '{self.name}' when accessing `key` prop")
            return self.name

        from src.lib.fs_utils import try_relative_to

        return (
            str(self.path.relative_to(root.path))
            if self.is_book_root or self.has_structure("series_parent")
            else str(try_relative_to(self.path.name, root.path))
        )

    @property
    def date_created(self):
        return self.path.stat().st_ctime

    @property
    def date_modified(self):
        return self.path.stat().st_mtime

    @property
    def date_accessed(self):
        return self.path.stat().st_atime

    @cached_property
    def depth(self):
        if self.is_root:
            return 0
        if not self.root:
            raise ValueError(f"{self} does not have a root, cannot determine depth")

        return len(self.path.relative_to(self.root.path).parts)

    @cached_property
    def container_root(self):
        """The root dir that contains the path, i.e. depth 1 parent."""

        if not self.root or self.is_root:
            return None
        # Get the first child off the root that's in the current path's parents, and is relative to the root.
        parent = self
        while parent and (p_up := parent.parent) and p_up.depth > 0 and not p_up.is_root:
            parent = p_up
        return parent

    @overload
    def first_audio_file(
        self, ext: AudiobookFmt | None = None, *, ignore_errors: Literal[False] = False
    ) -> "BooksTree": ...

    @overload
    def first_audio_file(
        self, ext: AudiobookFmt | None = None, *, ignore_errors: Literal[True] = True
    ) -> "BooksTree | None": ...

    @overload
    def first_audio_file(
        self, ext: AudiobookFmt | None = None, *, ignore_errors: bool = True
    ) -> "BooksTree | None": ...

    def first_audio_file(self, ext: AudiobookFmt | None = None, *, ignore_errors: bool = False):
        from src.lib.fs_utils import find_first_audio_file

        if self.has_structure("_root_"):
            raise ValueError(f"Cannot look for audio files for _root_; did you forget to set the root for '{self}'?")

        if self.has_any_structure("container", "series_parent"):
            return None

        if not (first := find_first_audio_file(self.path, ext=ext, ignore_errors=ignore_errors)):
            if not ignore_errors:
                raise FileNotFoundError(f"No audio files found in '{self}'")
            return None

        return self.get(first)

    @overload
    def next_audio_file(
        self,
        first: "BooksTree | None" = None,
        ext: AudiobookFmt | None = None,
        *,
        ignore_errors: Literal[False] = False,
    ) -> "BooksTree": ...

    @overload
    def next_audio_file(
        self, first: "BooksTree | None" = None, ext: AudiobookFmt | None = None, *, ignore_errors: Literal[True] = True
    ) -> "BooksTree | None": ...

    @overload
    def next_audio_file(
        self, first: "BooksTree | None" = None, ext: AudiobookFmt | None = None, *, ignore_errors: bool = True
    ) -> "BooksTree | None": ...

    def next_audio_file(
        self, first: "BooksTree | None" = None, ext: AudiobookFmt | None = None, *, ignore_errors: bool = False
    ):

        from src.lib.fs_utils import find_next_audio_file

        if self.is_file():
            return None

        if not (first := first or self.first_audio_file(ext, ignore_errors=ignore_errors)):
            if not ignore_errors:
                raise FileNotFoundError(f"No audio files found in '{self}'")
            return None

        if not (next_file := find_next_audio_file(self.path, first=first.path, ext=ext, ignore_errors=ignore_errors)):
            if not ignore_errors:
                raise FileNotFoundError(f"No audio files found in '{self}'")
            return None

        return BooksTree.cast(next_file, root=self.root, match_filter=self.match_filter)

    @property
    def ni(self):
        return TreeNumInfo(self)

    @property
    def has_only_dirs(self):
        return bool(self._dirs and not self._files)

    @property
    def has_only_files(self):
        return bool(self._files and not self._dirs)

    @property
    def has_files_and_dirs(self):
        return bool(self._files and self._dirs)

    @property
    def has_multiple_files_and_no_dirs(self):
        return bool(len(self._files) > 1 and not self._dirs)

    @property
    def has_no_files_or_dirs(self):
        return bool(not self._files and not self._dirs)

    @property
    @filter_matches
    def dirs_f(self):
        return self._dirs

    @property
    def dirs(self):
        return self._dirs

    @property
    @filter_matches
    def dirs_recursive_f(self) -> list["BooksTree"]:
        return self.dirs_recursive

    @property
    def dirs_recursive(self) -> list["BooksTree"]:
        # Recursively walks the tree to return a flat list of all directories, excluding the root
        return isorted(
            d
            for d in (
                *self._dirs.values(),
                *sum([d.dirs_recursive for d in self._dirs.values()], []),
            )
            if not d.is_root
        )

    @property
    @filter_matches
    def files_f(self):
        return self._files

    @property
    def files(self):
        return self._files

    @property
    @filter_matches
    def files_recursive_f(self):
        return self.files_recursive

    @property
    def files_recursive(self) -> list["BooksTree"]:
        # Recursively walks the tree to return a flat list of all files
        return isorted((*self._files, *sum([d.files_recursive for d in self._dirs.values()], [])))

    @filter_matches
    def files_of_type_f(self, fmt: AudiobookFmt) -> list["BooksTree"]:
        return self.files_of_type(fmt)

    def files_of_type(self, fmt: AudiobookFmt) -> list["BooksTree"]:
        from src.lib.formatters import ensure_dot

        return [f for f in self.files_recursive if f.path.suffix == ensure_dot(fmt)]

    @property
    @filter_matches
    def children_f(self) -> list["BooksTree"]:
        return self.children

    @property
    def children(self) -> list["BooksTree"]:
        return isorted((*self._files, *self._dirs.values()))

    @property
    @filter_matches
    def children_recursive_f(self) -> list["BooksTree"]:
        return self.children_recursive

    @property
    def children_recursive(self) -> list["BooksTree"]:
        # Recursively walks the tree to return a flat list of all paths
        return isorted(
            flatlist(
                [*self._files, *self._dirs.values(), *sum([d.children_recursive for d in self._dirs.values()], [])]
            )
        )

    @property
    @filter_matches
    def siblings_f(self):
        return self.siblings

    @property
    def siblings(self):
        if not self.parent or self.is_root:
            return None
        return isorted((c for c in self.parent.children if c != self))

    @property
    @filter_matches
    def books_f(self):
        """
        Returns all dirs and files that are books. If any of the children are
        containers, it will return the children of those containers as well.
        """

        return self.books

    @property
    def books(self):
        return list(filter(lambda x: not x.has_structure("series_parent"), self.books_and_series))

    @property
    @filter_matches
    def books_and_series_f(self) -> list["BooksTree"]:
        """
        Returns all dirs and files that are books or series parents. If any of the children are
        containers, it will return the children of those containers as well.
        """
        return self.books_and_series

    @property
    def books_and_series(self) -> list["BooksTree"]:
        return list(filter(lambda x: x.is_book_root or x.has_structure("series_parent"), self.children_recursive))

    @property
    @filter_matches
    def series_parents_f(self) -> list["BooksTree"]:
        """
        Returns all dirs that series parents.
        """
        return self.series_parents

    @property
    def series_parents(self) -> list["BooksTree"]:
        return list(filter(lambda x: x.has_structure("series_parent"), self.children_recursive))

    @property
    @filter_matches
    def standalone_files_f(self):
        """
        Returns all standalone files in the root (files with no parent).
        """
        return self.standalone_files

    @property
    def standalone_files(self):
        return list(filter(lambda x: x.has_structure("standalone_file"), self.children_recursive))

    @property
    def is_root(self):
        return self.root is None or self == self.root

    def is_file(self, *, recheck: bool = False):
        if recheck:
            self._is_file = None
        if self._is_file is None:
            self._is_file = self.path.is_file()
        return self._is_file

    def is_dir(self, *, recheck: bool = False):
        if recheck:
            self._is_dir = None
        if self._is_dir is None:
            self._is_dir = self.path.is_dir()
        return self._is_dir

    def exists(self):
        return self.path.exists()

    @requires_structure
    @requires_scan
    def determine_if_book_root(self):

        if self.is_root or self.has_only_structure("container"):
            self._is_book_root = False
            return self._is_book_root

        if self.has_any_structure("standalone_file", "multi_parent"):
            self._is_book_root = True
            return self._is_book_root

        if self.has_structure("single") and self.parent and self.parent.not_has_structure("single"):
            self._is_book_root = True
            return self._is_book_root

        if self.depth == 1 and self.has_any_structure("flat", "mixed", "nested"):
            self._is_book_root = True
            return self._is_book_root

        if self.parent and self.parent.has_structure("series_parent"):
            self._is_book_root = True
            return self._is_book_root

        is_flat_with_unrelated_siblings = (
            self.parent
            and self.parent.has_structure("container")
            and self.has_structure("flat")
            and len(self.parent._dirs) > 1
        )
        is_container_with_single_child = (
            self.has_structure("container")
            and not any([f.has_structure("standalone_file") for f in self._files])
            and not any([d.has_any_structure("mixed", "series_parent", "multi_parent") for d in self._dirs.values()])
        )

        if is_flat_with_unrelated_siblings or is_container_with_single_child:
            self._is_book_root = True
            return self._is_book_root

        self._is_book_root = False
        return self._is_book_root

    @property
    @requires_scan
    def is_book_root(self):
        """
        Returns True if the current path is a whole book, i.e., it is a
        standalone file or itself contains all files for a single title.
        """
        return self._is_book_root

    # TODO: Duplicate method for flat_files

    def get_files_in_dirs(self):
        return [f for d in self._dirs.values() for f in d._files]

    @property
    def type(self):
        return "dir" if self.is_dir() else "file" if self.is_file() else "unknown"

    def determine_structure(
        self,
        parent: "BooksTree | None" = None,
    ) -> tuple[BookStructure2, ...]:
        """Determines the structure for a tree of audio files and directories."""

        if not self.parent:
            self.parent = parent

        if not parent:
            parent = self

        root = parent.root or parent

        depth = len(self.path.relative_to(root.path).parts) if root else 0

        is_root = depth == 0

        if (self.is_root and not is_root) or (not self.is_root and is_root):
            raise ValueError(
                f"Root status of the current path and the root path do not match: {self.is_root=}, {is_root=}"
            )

        if is_root:
            self.set_structures("_root_")
            [d.determine_structure(self) for d in self._dirs.values()]
            [f.determine_structure(self) for f in self._files]
            for c in self.children_recursive:
                # Disable this assertion when debugging with _match_filter_func()
                assert c.structure, f"Expected structure to be determined for {c}\nRoot: {self}"
            [c.determine_if_book_root() for c in self.children_recursive]
            return self.structure

        # DEBUG only: bypass the structure determination if the current path does not match the filter
        # if not _match_filter_func([self.path], self.match_filter, root=root):
        #     return self.structure

        # if "breakpoint-book-name" in self.name.lower():
        #     ...

        # --- standalone (no parent / parent == root)
        if self.is_file():
            if depth < 2:
                self.add_structures("standalone_file")
            else:

                # size_gt_100mb = self.path.stat().st_size > 100 * 1e6
                # num_siblings_of_same_type = len([f for f in parent._files if f.path.suffix == self.path.suffix])
                container_root = self.container_root or parent
                single_file = len(parent._files) == 1
                mixed_file_types = len(set([f.path.suffix for f in parent._files])) > 1

                if (
                    (single_file or mixed_file_types or container_root.ni.files_recursive.similarity < 0.7)
                    and not parent.ni.children_recursive.nums_match_each_other
                    and not parent.has_structures_like("multi_", "series_", "flat")
                ):
                    self.add_structures("single")
                    if (
                        parent.has_any_structure("single", "container")
                        and depth > 2
                        and not self.ni.siblings.are_likely("series")
                    ):
                        self.add_structures("nested")
                elif parent.has_structure("mixed"):
                    self.add_structures("mixed")
                elif not parent.has_structures_like("multi_", "series_"):
                    self.add_structures("flat")
                    if parent.has_any_structure("nested", "container") and depth > 2:
                        self.add_structures("nested")
                if parent.has_any_structure("multi_disc") or (
                    self.ni.is_likely_multi_disc and parent.has_files_and_dirs
                ):
                    if parent and not parent.has_structure("multi_disc"):
                        parent.set_structures("multi_parent", "multi_disc")
                    self.add_structures("multi_disc")
                elif parent.has_any_structure("multi_part") or (
                    self.ni.is_likely_multi_part and parent.has_files_and_dirs
                ):
                    if parent and not parent.has_structure("multi_part"):
                        parent.set_structures("multi_parent", "multi_part")
                    self.add_structures("multi_part")
                elif parent.has_any_structure("series_parent") or self.ni.is_likely_series:
                    if not self.ni.curr.has_any_num:
                        # If the current file has no numbers, but the parent is a series parent, it's likely a false positive and we should set the parent to mixed
                        parent.set_structures("mixed", recursive=True)
                    else:
                        if not parent.has_structure("series_book"):
                            parent.set_structures("series_parent")
                        self.add_structures("series_book")

            return self.structure

        if depth > 1 and not parent.structure:
            raise ValueError("Parent structure should be determined already for non-base directories")
        else:
            parent.structure = cast(tuple[BookStructure2, ...], parent.structure)

        has_one_file_and_no_dirs = bool(len(self._files) == 1 and not self._dirs)

        if depth < 2 and len(self.files_recursive) == 1:
            self.set_structures("single", recursive=True)
        elif has_one_file_and_no_dirs and not self.has_structure_like("multi_"):
            self.add_structures("single")
        elif self.has_multiple_files_and_no_dirs:
            self.set_structures("flat", recursive=True)
            if parent.has_any_structure("nested", "container"):
                self.add_structures("nested")
        elif self.has_files_and_dirs:
            self.set_structures("container")
        elif self.has_no_files_or_dirs:
            self.set_structures("empty")
            return self.structure

        if len(self._dirs) == 1 and len(self.files_recursive) == 1:
            nested_dir = self._dirs[next(iter(self._dirs.keys()))]
            nested_dir.add_structures("single", "nested", recursive=True)

        # recursively check to see if there is only one nested dir in each dir
        if (
            self._dirs
            and not self._files
            and parent.has_any_structure("_root_", "container")
            and len(self.files_recursive) > 1
            and not any((len(self._dirs) > 1, *[len(d._dirs) > 1 for d in self.dirs_recursive]))
        ):
            self.add_structures("flat", "nested", recursive=True)

        # if multi_disc_parent:
        if not parent.is_root:
            if parent.has_all_structures("multi_disc", "multi_parent"):
                self.set_structures("multi_disc")

            if parent.has_all_structures("multi_part", "multi_parent"):
                self.set_structures("multi_part")

            if parent.has_structure("series_parent"):
                self.add_structures("series_book")

            if not self.structure:
                self.set_structures("unknown")

            if (
                depth > 1
                and (self.has_only_dirs and self.has_any_structure("single", "flat", "series_book"))
                or parent.has_structure("container")
            ):
                self.add_structures("nested")

            if any((self.ni.is_likely_series, self.ni.is_likely_multi_disc, self.ni.is_likely_multi_part)):

                # Most of the time series are named sensibly with numbers, but occasionally they are not.
                # If we think this is a series but is missing numbers, we need to check the children.
                # - If all children have the same series number, or none at all, it's probably a false positive.
                # - If the children have different series numbers, it's likely a series parent.
                # - If the children don't have series numbers, but are all files with dissimilar names, and
                #   sufficiently sized to be standalones, this is likely a series parent.

                is_known_multi = False

                parent_ok = False
                children_ok = False
                siblings_seq = False
                siblings_match = False

                if self.ni.is_likely_multi_disc:
                    # It's multi_disc or multi_part if:
                    #   - it has a disc or part no., and the children do not (or they match)
                    #   - its parent does not have a disc or part no.
                    #   - siblings have disc or part nos. that are sequential

                    parent_ok = not self.ni.parent or not self.ni.parent.has_disc_num
                    children_ok = not self.ni.children.have_disc_nums or self.ni.children.disc_nums_match_curr
                    siblings_seq = self.ni.siblings.disc_nums_are_sequential
                    siblings_match = self.ni.siblings.disc_nums_match_each_other

                elif self.ni.is_likely_multi_part:

                    parent_ok = not self.ni.parent or not self.ni.parent.has_part_num
                    children_ok = not self.ni.children.have_part_nums or self.ni.children.part_nums_match_curr
                    siblings_seq = self.ni.siblings.part_nums_are_sequential
                    siblings_match = self.ni.siblings.part_nums_match_each_other

                elif self.ni.is_likely_series:

                    parent_ok = not self.ni.parent or (
                        (not self.ni.parent.has_series_num and not self.ni.parent.has_start_num)
                        or not self.ni.parent.any_num_matches_curr
                        or re.search(r"(?:\b|_)series(?:\b|_)", parent.name.lower(), re.I)
                    )
                    children_ok = (
                        not self.ni.children.have_series_nums or self.ni.children.series_nums_match_curr
                    ) and (not self.ni.children.have_start_nums or self.ni.children.start_nums_are_sequential)
                    siblings_seq = (
                        self.ni.siblings.have_series_nums and self.ni.siblings.series_nums_are_sequential
                    ) or (self.ni.siblings.have_start_nums and self.ni.siblings.start_nums_are_sequential)
                    siblings_match = (
                        self.ni.siblings.have_series_nums and self.ni.siblings.series_nums_match_each_other
                    ) or (self.ni.siblings.have_start_nums and self.ni.siblings.start_nums_match_each_other)

                if self.ni.is_likely_multi_disc or self.ni.is_likely_multi_part:
                    _structure = "multi_disc" if self.ni.is_likely_multi_disc else "multi_part"
                    if (self.ni.curr.has_disc_num or self.ni.curr.has_part_num) and children_ok and parent_ok:
                        # We can safely recur on the parent, because we know it is a single title
                        # parent.add_structures(_structure, recursive=True)
                        if siblings_seq:
                            parent.set_structures("multi_parent")
                            parent.add_structures(_structure, recursive=True)
                        self.add_structures(_structure, recursive=True)
                        is_known_multi = True

                elif self.ni.is_likely_series:
                    # It's a series_book if:
                    #   - it has a series no., and the children do not (or they match)
                    #   - its parent does not have a series no.

                    if (self.ni.curr.has_series_num or self.ni.curr.has_start_num) and children_ok and parent_ok:
                        if siblings_seq:
                            # If the siblings are sequential, its parent is a series_parent
                            parent.set_structures("series_parent")
                            # [s.add_structures("series_book", recursive=True) for s in self.siblings or []]
                        elif siblings_match:
                            # If the siblings have the same series number, it can be contained in a series book,
                            # but its parent can't be a series_parent
                            parent.remove_structures("series_parent")

                        self.add_structures("series_book", recursive=True)

                        is_known_multi = True

                        if not self._dirs:
                            self.add_structures("flat", recursive="files")

                        # We can check siblings files to see if they are standalone
                        for f in parent._files:
                            # gcs_percent = calculate_gcs_percentage(
                            #     [self.path.name, *[f.path.name for f in parent._files]]
                            # )
                            # size_gt_100mb = f.path.stat().st_size > 100 * 1e6
                            # If the file names are dissimilar or the size is greater than 75mb, it's
                            # likely a single file and we probably don't want to merge it.
                            if f.ni.is_likely_series or parent.has_structure("series_parent"):
                                f.add_structures("single", "series_book")

                    # If curr does not have series numbers but the children do,
                    # they must all be different (or we might have a false positive)
                    if not self.ni.curr.has_any_num and self.ni.children.have_any_nums:
                        if self.ni.children.nums_match_each_other:
                            print_warning(
                                f"'{self}' might be a series_parent, but all its children have the same book number"
                            )
                            self.set_structures("mixed", recursive=True)

                    elif self.ni.curr.has_any_num and self.ni.parent and self.ni.parent.any_num_matches_curr:
                        print_warning(f"'{self}' might be a series_book, but its parent has the same book number")

                # Add nested if it has a <struc> no. and child dirs
                # TODO: Don't think we want this
                # if is_known_multi and self.ni.curr.has_any_num and self._dirs:
                #     self.add_structures("nested", recursive="dirs")

                if not is_known_multi and self.siblings and not self.ni.siblings.have_any_nums:
                    # Set to "mixed"
                    self.add_structures("mixed", recursive=True)

                # Clean up parent structures that are invalid
                if self.has_any_structure(
                    "multi_disc",
                    "multi_parent",
                    "multi_part",
                    "series_parent",
                    "series_book",
                    "mixed",
                ):
                    # If current is a multi-disc, its parent cannot be flat, single, or standalone
                    parent.remove_structures("flat", "single", "standalone_file")

                # If self has multi_mixed and more than one other multi_ structure, raise
                if self.has_structure("mixed") and len([s for s in self.structure if "multi_" in s]) > 1:
                    print_debug(
                        f"{self.path} has {self.structure} but has more than one multi_ structure, so removing all other structures"
                    )
                    self.set_structures("mixed", recursive=True)
                    # [p.set_structures("mixed") for p in [*self._files, *self._dirs.values()]]

            if not parent.structure or parent.has_structure("unknown"):
                parent.set_structures(*self.structure)

        # first pass check for single/standalone files
        [f.determine_structure(self) for f in self._files]

        # if all children have structures that support container, add container to self
        if (
            all(
                [
                    c.has_any_structure("standalone_file", "single", "flat", "series_parent", "multi_parent")
                    for c in self.children
                ]
            )
            and self._dirs
            and not self._files
            and self.has_any_structure("mixed", "unknown")
        ):
            self.add_structures("container")
        elif not self.has_any_structure(
            "series_parent",
            "series_book",
            "multi_parent",
            "multi_disc",
            "multi_part",
            "flat",
            "single",
            "standalone_file",
        ):

            has_only_single_or_standalone_files = all(
                (f.has_any_structure("standalone_file", "single") for f in self._files)
            )

            if not self._files and len(self._dirs) == 1:
                # Nested dirs cannot contain files, and can only contain one dir.
                self.add_structures("nested")
            elif (
                self._dirs
                and has_only_single_or_standalone_files
                and not self.ni.children.nums_are_sequential
                and not self.ni.children.are_missing_nums
            ):
                if len(self._files) > 1 and self.ni.files.distinct_similarity > 0.8:
                    # If we have files that are very similar, but still other dirs/files, we can't be sure if we should treat it as a container or not – treat it as mixed
                    self.add_structures("mixed")
                else:
                    # Containers are inherently not book roots, which means they can only contain standalone files, single/flat titles, or series parents
                    self.add_structures("container")
            elif self.has_files_and_dirs and (
                not has_only_single_or_standalone_files
                or self.ni.children.are_missing_nums
                or self.ni.children.distinct_similarity < 0.7
            ):
                # If there are more than one dir or file (or both), it's a mixed
                self.set_structures("mixed")
            else:
                self.set_structures("unknown")

        # second pass check for single/standalone files
        # [f.determine_structure(self) for f in self._files]
        # determine child dir structures
        [d.determine_structure(self) for d in self._dirs.values()]

        # If we've reached the end and anything in the tree is mixed, overwrite the structure with mixed
        if any((c.has_structure("mixed") for c in (self, *self.children_recursive))):
            self.set_structures("mixed", recursive=True)

        if not self.structure or self.has_structure("unknown"):
            raise ValueError(f"Did not determine structure for '{self}'")

        # Check all files and make sure none are unknown or ()
        if any([f.has_structure("unknown") for f in self._files]):
            raise ValueError(f"Did not determine structure for '{self}''s files, {self._files}")

        # add any details from dir structures to the current path's structure if they are:
        # - standalone
        # - single
        # - flat
        # - multi_disc
        # - series_book (-> series_parent)

        # child_files_structures = tuple(set(flatlist([f.structure for f in self.files])))
        # child_dirs_structures = tuple(
        #     set(flatlist([d.structure for d in self.dirs.values()]))
        # )
        # parent.add_structures(
        #     *[
        #         s
        #         for s in child_dirs_structures

        # )
        # TODO: Don't think we need this next line anymore
        # self.add_structures(*[s for s in self.files_flat if s in ("mixed",)])
        # if any([b.has_structure("series_book") for b in self.children_recursive]):
        #     self.add_structures("series_parent")

        assert self.structure, f"Expected structure to be determined for {self}\nRoot: {self.root}"

        return self.structure

    def has_structure(self, structure: BookStructure2):
        return structure in self.structure

    def has_structure_like(self, match: str | BookStructure2):
        return any_matching(self.structure, [match])

    def has_structures_like(self, *matches: str | BookStructure2):
        return any_matching(self.structure, list(matches))

    def not_has_structure(self, structure: BookStructure2):
        return self.not_has_structures(structure)

    def has_any_structure(self, *structure: BookStructure2):
        return any([s in self.structure for s in structure])

    def not_has_structures(self, *structure: BookStructure2):
        return not self.has_any_structure(*structure)

    def has_all_structures(self, *structure: BookStructure2):
        return all([s in self.structure for s in structure])

    def has_only_structure(self, structure: BookStructure2):
        return self.has_only_structures(structure)

    def has_only_structures(self, *structure: BookStructure2):
        return len(self.structure) == len(structure) and all([s in self.structure for s in structure])

    def add_structures(
        self,
        *structure: BookStructure2,
        recursive: bool | Literal["files", "dirs", "all", "none"] = False,
    ):

        if self.has_any_structure("series_parent"):
            ...

        if not structure:
            raise ValueError(
                "No structure provided when trying to add structures. Did you mean to call remove_structures() or clear_structure()?"
            )

        if "unknown" in self.structure:
            self.remove_structures("unknown")

        if any_in(structure, ["mixed"]) and any_matching(self.structure, ["multi_", "series_", "container"]):
            # print_debug(
            #     f"{self.path} has {self.structure} but about to add 'mixed' which supercedes all structures, so removing all other structures"
            # )
            self.set_structures("mixed", recursive=recursive)
            return self.structure

        if self.has_structure("mixed") and not structure == ("mixed",):
            # print_debug(f"{self.key} has 'mixed' which is not compatible with {structure}, removing 'mixed'")
            self.remove_structures("mixed", recursive=recursive)

        if any_matching(structure, ["_parent"]):
            self.remove_structures("standalone_file", "single", "flat", "multi_disc", "multi_parent")

        if any_in(structure, ["series_book"]):
            self.remove_structures("series_parent")

        if any_in(structure, ["series_parent"]):
            self.remove_structures("series_book")

        if any_matching(
            structure,
            ["multi_", "mixed", "container"],
        ):
            self.remove_structures("flat", "single", "standalone_file")

        if any_in(structure, ["flat", "single", "standalone_file"]) and any_matching(
            self.structure, ["multi_", "series_parent", "container", "mixed"]
        ):
            raise ValueError(f"Tried to add {structure} to {self.path} which has {self.structure}")

        # After all the checks, set the structure
        for s in structure:
            if not s in self.structure:
                self.structure += (s,)

        children = []
        match recursive:
            case "files":
                children = self._files
            case "dirs":
                children = self._dirs.values()
            case "all" | True:
                children = [*self._files, *self._dirs.values()]
        [c.add_structures(*structure, recursive=recursive) for c in children]

        return self.structure

    def remove_structures(
        self,
        *structure: BookStructure2,
        recursive: bool | Literal["files", "dirs", "all", "none"] = False,
    ):

        if not structure:
            raise ValueError("No structure provided when trying to remove structures")

        self.structure = tuple([s for s in self.structure if s not in structure])
        children = []
        match recursive:
            case "files":
                children = self._files
            case "dirs":
                children = self._dirs.values()
            case "all" | True:
                children = [*self._files, *self._dirs.values()]
        [c.remove_structures(*structure, recursive=recursive) for c in children]
        return self.structure

    def set_structures(
        self,
        # *structure: "BookStructure2 | tuple[BookStructure2, ...]",
        *structure: BookStructure2,
        recursive: bool | Literal["files", "dirs", "all", "none"] = False,
    ):
        # if len(structure) == 1 and isinstance(structure[0], tuple):
        #     structures = *structure[0]
        # else:
        #     self.structure = cast("tuple[BookStructure2, ...]", structure)
        if self.has_structure("series_parent") and not "series_parent" in structure:
            raise ValueError(f"Tried to set {structure} to {self.path} which has {self.structure}")
        self.clear_structure(recursive=recursive)
        self.add_structures(*structure, recursive=recursive)
        return self.structure

    def clear_structure(self, recursive: bool | Literal["files", "dirs", "all", "none"] = False):
        self.structure = ()
        children = []
        match recursive:
            case "files":
                children = self._files
            case "dirs":
                children = self._dirs.values()
            case "all" | True:
                children = [*self._files, *self._dirs.values()]
        [c.clear_structure(recursive=recursive) for c in children]
        return self.structure

    def to_dict(self, *, fs_only: bool = False):
        if fs_only:
            return {
                "_files": [f.path.name for f in self._files],
                "_dirs": {k: v.to_dict(fs_only=fs_only) for k, v in self._dirs.items()},
            }
        return {
            "path": str(self.path),
            "files": [f.to_dict() for f in self._files],
            "dirs": {k: v.to_dict() for k, v in self._dirs.items()},
            "size": self.size,
            "structure": self.structure,
        }

    def __eq__(self, other):
        if not isinstance(other, BooksTree):
            return False
        return self.path == other.path

    def __lt__(self, other):
        if not isinstance(other, BooksTree):
            return False
        return self.path < other.path

    def __le__(self, other):
        if not isinstance(other, BooksTree):
            return False
        return self.path <= other.path

    def __gt__(self, other):
        if not isinstance(other, BooksTree):
            return False
        return self.path > other.path

    def __ge__(self, other):
        if not isinstance(other, BooksTree):
            return False
        return self.path >= other.path

    def __hash__(self):
        return hash(self.path)
