import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast, Literal, overload, Self, TypeVar

from pydantic import BaseModel, Field

from src.lib.misc import (
    any_in,
    any_matching,
    flatlist,
    isorted,
    percent_truthy_in_list,
)
from src.lib.term import print_debug, print_warning
from src.lib.typing import BookStructure2

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
        self.siblings = self.ArrNumDict([s.path.name for s in (tree.siblings or [])], self.curr)

    @property
    def likely_series(self):
        return [self.curr.is_likely, self.children.are_likely, self.siblings.are_likely].count("series") >= 2

    @property
    def likely_multi_disc(self):
        return [self.curr.is_likely, self.children.are_likely, self.siblings.are_likely].count("multi_disc") >= 2

    @property
    def likely_multi_part(self):
        return [self.curr.is_likely, self.children.are_likely, self.siblings.are_likely].count("multi_part") >= 2

    # @property
    # def curr_has_nums(self):
    #     """
    #     Returns True if the current path has any numbers in it (disc, part, series, start)
    #     """
    #     return self.curr.has_any_num

    # @property
    # def parent_has_nums(self):
    #     """
    #     Returns True if the parent path has any numbers in it (disc, part, series, start)
    #     """
    #     return self.parent and self.parent.has_any_num

    # @property
    # def children_have_nums(self):
    #     """
    #     Returns True if any of the children paths have any numbers in them (disc, part, series, start)
    #     """
    #     return self.children.have_any_nums

    # @property
    # def siblings_have_nums(self):
    #     """
    #     Returns True if any of the sibling paths have any numbers in them (disc, part, series, start)
    #     """
    #     return self.siblings.have_any_nums

    class NumDict:
        disc_num: int = -1
        part_num: int = -1
        series_num: int = -1
        start_num: int = -1
        _curr: Self | None = None

        def __init__(self, path: str, curr: Self | None = None):

            from src.lib.parsers import get_disc_no, get_part_no, get_series_no, get_start_no

            self._path = path
            self._curr = curr
            self.disc_num = get_disc_no(path)
            self.part_num = get_part_no(path)
            self.series_num = get_series_no(path)
            self.start_num = get_start_no(path)

        def __repr__(self):
            return f"{{d: {self.disc_num}, p: {self.part_num}, s: {self.series_num}, ^: {self.start_num}}}"

        def __str__(self):
            return self.__repr__()

        @property
        def best_num(self):
            return next((n for n in [self.disc_num, self.part_num, self.series_num, self.start_num] if n > -1), -1)

        @property
        def is_likely(self) -> Literal["multi_disc", "multi_part", "series", "unknown"]:
            if self.has_disc_num:
                return "multi_disc"
            if self.has_part_num:
                return "multi_part"
            if self.has_series_num or self.has_start_num:
                return "series"
            return "unknown"

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
            return any([self.has_disc_num, self.has_part_num, self.has_series_num, self.has_start_num])

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

        def __init__(self, paths: list[str], curr: NumDictType | None = None):  # type: ignore

            from src.lib.parsers import get_disc_no, get_part_no, get_series_no, get_start_no

            self._paths = paths
            self._curr = cast(TreeNumInfo.NumDict, curr)
            self.disc_nums = [get_disc_no(p) for p in paths]
            self.part_nums = [get_part_no(p) for p in paths]
            self.series_nums = [get_series_no(p) for p in paths]
            self.start_nums = [get_start_no(p) for p in paths]

        def __repr__(self):
            return f"{{d: {self.disc_nums}, p: {self.part_nums}, s: {self.series_nums}, ^: {self.start_nums}}}"

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
            return any([self.have_disc_nums, self.have_part_nums, self.have_series_nums, self.have_start_nums])

        @property
        def are_likely(self) -> Literal["multi_disc", "multi_part", "series", "unknown"]:
            if self.have_disc_nums and self.maybe_multi_disc > 0:
                return "multi_disc"
            if self.have_part_nums and self.maybe_multi_part > 0:
                return "multi_part"
            if (self.have_series_nums or self.have_start_nums) and self.maybe_series > 0:
                return "series"
            return "unknown"

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
        def nums_are_sequential(self):
            return all(
                [
                    not self.have_disc_nums or self.disc_nums_are_sequential,
                    not self.have_part_nums or self.part_nums_are_sequential,
                    not self.have_series_nums or self.series_nums_are_sequential,
                    not self.have_start_nums or self.start_nums_are_sequential,
                ]
            )

        @property
        def disc_nums_match_each_other(self) -> bool:
            return self.have_disc_nums and all([c == self.disc_nums[0] for c in self.disc_nums])

        @property
        def part_nums_match_each_other(self) -> bool:
            return self.have_part_nums and all([c == self.part_nums[0] for c in self.part_nums])

        @property
        def series_nums_match_each_other(self) -> bool:
            return self.have_series_nums and all([c == self.series_nums[0] for c in self.series_nums])

        @property
        def start_nums_match_each_other(self) -> bool:
            return self.have_start_nums and all([c == self.start_nums[0] for c in self.start_nums])

        @property
        def nums_match_each_other(self):
            return all(
                [
                    self.disc_nums_match_each_other,
                    self.part_nums_match_each_other,
                    self.series_nums_match_each_other,
                    self.start_nums_match_each_other,
                ]
            )

        @property
        def disc_nums_match_curr(self):
            return self._curr.has_disc_num and all([x == self._curr.disc_num for x in self.disc_nums])

        @property
        def part_nums_match_curr(self):
            return self._curr.has_part_num and all([x == self._curr.part_num for x in self.part_nums])

        @property
        def series_nums_match_curr(self):
            """Returns True if all series numbers match the current's series or start number"""
            return (self._curr.has_series_num or self._curr.has_start_num) and (
                all([x == self._curr.start_num for x in self.series_nums])
                or all([x == self._curr.series_num for x in self.series_nums])
            )

        @property
        def start_nums_match_curr(self):
            """Returns True if all start numbers match the current's series or start number"""
            return (self._curr.has_series_num or self._curr.has_start_num) and (
                all([x == self._curr.start_num for x in self.start_nums])
                or all([x == self._curr.series_num for x in self.start_nums])
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


class BooksTree(BaseModel):
    _is_file: bool | None = None
    _is_dir: bool | None = None
    path: Path = Field(default_factory=Path)
    files: list["BooksTree"] = []
    dirs: dict[str, "BooksTree"] = {}
    parent: "BooksTree | None" = None
    size: int = 0
    mindepth: int | None = None
    maxdepth: int | None = None
    structure: tuple[BookStructure2, ...] = ()
    root: "BooksTree | None" = None
    matching_paths: list[Path] | None = None
    _last_scan: float | None = None

    model_config = {
        "arbitrary_types_allowed": True,
    }

    def __init__(
        self,
        path: "Path | BooksTree | str" = ".",
        *,
        root: "Path | BooksTree | None" = None,
        files: Sequence["str | Path | BooksTree"] = [],
        dirs: Mapping[str, "str | Path | BooksTree"] = {},
        mindepth: int | None = None,
        maxdepth: int | None = None,
        allow_file_root: bool = False,
        matching_paths: list[Path] | None = None,
        structure: tuple[BookStructure2, ...] = (),
        size: int = 0,
        scan: bool = True,
    ):
        super().__init__()
        if isinstance(path, BooksTree):
            self.__dict__.update(path.__dict__)
            return
        self.path = Path(path)
        self.root = BooksTree(root, scan=False) if root is not None else None
        if matching_paths:
            self.set_matching_paths(matching_paths)
        if scan:
            self.scan(mindepth=mindepth, maxdepth=maxdepth, allow_file_root=allow_file_root)
        if files:
            self.files = [BooksTree(f, root=root, scan=False) for f in files]
        if dirs:
            self.dirs = {k: BooksTree(v, root=root, scan=False) for k, v in dirs.items()}
        self.size = size
        if structure:
            self.structure = structure

    def __repr__(self):
        return f"TreePath({self.path})"

    def __str__(self):
        return str(self.path)

    @classmethod
    def cast(
        cls,
        path: "Path | BooksTree | str" = ".",
        *,
        root: "Path | BooksTree | None" = None,
        matching_paths: list[Path] | None = None,
    ):
        """Casts a path to a TreePath without scanning it"""
        return BooksTree(path, root=root, scan=False, matching_paths=matching_paths)

    def scan(
        self,
        *,
        mindepth: int | None = None,
        maxdepth: int | None = None,
        ignore_errors: bool = False,
        allow_file_root: bool = False,
    ) -> "BooksTree":
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

        from src.lib.fs_utils import filter_ignored, only_audio_files, try_relative_to

        root = (root := self.root or self).path

        if not root.is_dir():
            if ignore_errors:
                return self
            if root.is_file() and allow_file_root:
                return self
            raise NotADirectoryError(f"Error: {root} is not a directory")

        # Do a recursive glob of all files in the directory, and prepend the root so we can get standalone files
        rglob = isorted([root, *root.rglob("*")])

        # Filter out files/dirs if matching_paths and the current path is not relative to any of the paths
        if self.matching_paths:
            rglob = [
                p
                for p in rglob
                if p in self.matching_paths or any((try_relative_to(p, m) for m in self.matching_paths))
            ]

        # Function to recursively add keys to the tree dict
        def _add_to_tree(at_path: Path, audio_files: Sequence[Path | BooksTree]):
            rel_path = at_path.relative_to(root)
            parts = rel_path.parts
            subtree = self
            for i, part in enumerate(rel_path.parts):
                if part not in self.dirs:
                    parent_p = Path(root, *parts[: i + 1])
                    subtree.dirs[part] = BooksTree.cast(parent_p, root=root)
                subtree = subtree.dirs[part]
            subtree.files = isorted([BooksTree.cast(p, root=root) for p in [*subtree.files, *audio_files]])

        # Build a tree of the audio files and dirs
        # tree = TreePath(root)
        for d in [x for x in rglob if x.is_dir()]:
            # If d is not within the mindepth and maxdepth, skip it
            if not all(
                [
                    mindepth is None or len(d.relative_to(root).parts) >= mindepth,
                    maxdepth is None or len(d.relative_to(root).parts) <= maxdepth,
                ]
            ):
                continue

            # If x is a dir, make sure the path and its parents exists in the tree
            audio_files_in_dir = [f for f in only_audio_files(filter_ignored(rglob)) if f.parent == d]
            audio_files_in_dir = [
                f
                for f in only_audio_files(filter_ignored(rglob))
                if f.parent == d
                and (mindepth is None or len(f.relative_to(root).parts) - 1 >= mindepth)
                and (maxdepth is None or len(f.relative_to(root).parts) - 1 <= maxdepth)
            ]
            if audio_files_in_dir:
                _add_to_tree(d, audio_files_in_dir)

        # Add files from the current level to self.files
        self.files = isorted(
            [
                BooksTree.cast(f, root=root)
                for f in only_audio_files(filter_ignored(rglob))
                if f.parent == self.path
                and (mindepth is None or len(f.relative_to(root).parts) - 1 >= mindepth)
                and (maxdepth is None or len(f.relative_to(root).parts) - 1 <= maxdepth)
            ]
        )

        self.determine_structure()
        self._last_scan = time.time()
        return self

    def get(self, key: "str | Path | BooksTree"):
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
        if not key:
            raise ValueError(".get(): Key cannot be empty")
        if isinstance(key, BooksTree):
            key = key.path
        if isinstance(key, str):
            key = Path(key)
        if isinstance(key, Path) and key.is_absolute():
            key = key.relative_to(self.path)
        if key == Path("."):
            return self

        # Find the path in self.children_recursive
        return next((c for c in self.children_recursive if c.path.relative_to(self.path) == key), None)

    def count_files(
        self,
        *,
        mindepth: int | None = None,
        maxdepth: int | None = None,
    ) -> int:
        """
        Count the number of audio files in a directory and its subdirectories.

        Parameters:
        mindepth (int | None, optional): The minimum depth of directories to search. This is 0-based, so a mindepth of 0 includes files directly in the base directory. Defaults to None, which includes all depths.
        maxdepth (int | None, optional): The maximum depth of directories to search. This is 0-based, so a maxdepth of 0 includes only files directly in the base directory. Defaults to None, which includes all depths.

        Returns:
        int: The number of audio files found.
        """

        return len(self.__class__(self.path, root=self.root, mindepth=mindepth, maxdepth=maxdepth).files_recursive)

    def set_matching_paths(self, paths: list[Path]):
        from src.lib.fs_utils import try_relative_to

        # If matching_paths is set, delete keys if curr_path is not relative to any of the paths
        if paths or self.matching_paths:
            self.matching_paths = paths or self.matching_paths or []
            matching_file_paths = [f for f in self.matching_paths if f.is_file() or f.suffix]
            matching_dir_paths = [d for d in self.matching_paths if d.is_dir() or not d.suffix]

            self.files = (
                []
                if not matching_file_paths
                else [
                    f
                    for f in self.files
                    if f in matching_file_paths or any((try_relative_to(f.path, m) for m in matching_file_paths))
                ]
            )
            self.dirs = (
                {}
                if not matching_dir_paths
                else {
                    d.path.name: d
                    for d in self.dirs.values()
                    if d.path in matching_dir_paths or any((try_relative_to(d.path, m) for m in matching_dir_paths))
                }
            )

    @property
    def name(self):
        return self.path.name

    @property
    def key(self):
        return str(self.path.relative_to(self.root.path)) if self.root and self.is_book_root else None

    @property
    def date_created(self):
        return self.path.stat().st_ctime

    @property
    def date_modified(self):
        return self.path.stat().st_mtime

    @property
    def date_accessed(self):
        return self.path.stat().st_atime

    @property
    def depth(self):
        if self.is_root:
            return 0
        if not self.root:
            raise ValueError(f"{self} does not have a root, cannot determine depth")

        return len(self.path.relative_to(self.root.path).parts)

    @overload
    def first_audio_file(self, ext: str | None = None, *, ignore_errors: Literal[False] = False) -> "BooksTree": ...

    @overload
    def first_audio_file(
        self, ext: str | None = None, *, ignore_errors: Literal[True] = True
    ) -> "BooksTree | None": ...

    def first_audio_file(self, ext: str | None = None, *, ignore_errors: bool = False) -> "BooksTree | None":
        from src.lib.fs_utils import find_first_audio_file

        return find_first_audio_file(self, ext=ext, ignore_errors=ignore_errors)  # type: ignore

    @overload
    def next_audio_file(
        self, current_file: "BooksTree | None" = None, ext: str | None = None, *, ignore_errors: Literal[False] = False
    ) -> "BooksTree": ...

    @overload
    def next_audio_file(
        self, current_file: "BooksTree | None" = None, ext: str | None = None, *, ignore_errors: Literal[True] = True
    ) -> "BooksTree | None": ...

    def next_audio_file(
        self, current_file: "BooksTree | Path | None" = None, ext: str | None = None, *, ignore_errors: bool = False
    ):

        if self.is_file():
            return None

        err = f"No more audio files found in '{self}'"
        if ext:
            err += f" with extension '{ext}'"
        if not current_file:
            current_file = self.first_audio_file(ext, ignore_errors=ignore_errors)  # type: ignore
        if not current_file:
            if not ignore_errors:
                raise FileNotFoundError(err)
            return None
        files = sorted(
            filter(lambda x: x.path.suffix == ext or not ext, self.files_recursive), key=lambda x: x.path.name
        )
        try:
            # if current file is a Path not a TreePath, convert it to a TreePath
            if isinstance(current_file, Path):
                current_file = BooksTree(current_file, root=self.root, scan=False)
            next_file = next(iter(files[files.index(current_file) + 1 :]), None)
            if not next_file and not ignore_errors:
                raise FileNotFoundError(err)
            return next_file
        except IndexError:
            if not ignore_errors:
                raise FileNotFoundError(err)
            return None

    @property
    def files_recursive(self):
        # Recursively walks the tree to return a flat list of all files
        return cast(
            list["BooksTree"],
            [*self.files, *sum([d.files_recursive for d in self.dirs.values()], [])],
        )

    @property
    def dirs_recursive(self):
        # Recursively walks the tree to return a flat list of all directories, excluding the root
        return [
            d
            for d in cast(
                list["BooksTree"],
                [
                    *self.dirs.values(),
                    *sum([d.dirs_recursive for d in self.dirs.values()], []),
                ],
            )
            if not d.is_root
        ]

    @property
    def children(self):
        return [*self.files, *self.dirs.values()]

    @property
    def children_recursive(self):
        # Recursively walks the tree to return a flat list of all paths
        return cast(
            list["BooksTree"],
            isorted(
                flatlist(
                    [*self.files, *self.dirs.values(), *sum([d.children_recursive for d in self.dirs.values()], [])]
                )
            ),
        )

    @property
    def siblings(self):
        if not self.parent or self.is_root:
            return None
        return [c for c in self.parent.children if c != self]

    @property
    def books(self):
        """
        Returns all dirs and files that are books. If any of the children are
        containers, it will return the children of those containers as well.
        """

        return list(filter(lambda x: not x.has_structure("series_parent"), self.books_and_series))

    @property
    def books_and_series(self) -> list["BooksTree"]:
        from src.lib.config import cfg

        books = sorted(
            list(filter(lambda x: x.is_book_root or x.has_structure("series_parent"), self.children_recursive)),
            key=lambda x: x.date_modified,
        )
        if not cfg.CONVERT_SERIES:
            books = list(filter(lambda x: not x.has_structure_like("series"), books))
        return isorted(books)

    @property
    def standalone_files(self):
        return list(filter(lambda x: x.has_structure("standalone_file"), self.children_recursive))

    def model_post_init(self, __context):
        self.root = None if self.root is None else BooksTree(self.root, scan=False)

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

    @property
    def is_book_root(self):
        """
        Returns True if the current path is a whole book, i.e., it is a
        standalone file or itself contains all files for a single title.
        """
        if self.is_root:
            return False

        if self.has_structure("standalone_file") or self.has_any_structure("multi_parent"):
            return True

        if self.depth == 1 and self.has_any_structure("flat", "single", "mixed"):
            return True

        parent_is_series_parent = self.parent and self.parent.has_structure("series_parent")
        is_flat_with_unrelated_siblings = (
            self.parent
            and self.parent.has_structure("container")
            and self.has_structure("flat")
            and len(self.parent.dirs) > 1
        )
        is_container_with_single_child = (
            self.has_structure("container")
            and not any([f.has_structure("standalone_file") for f in self.files])
            and not any([d.has_any_structure("mixed", "series_parent", "multi_parent") for d in self.dirs.values()])
        )

        if parent_is_series_parent or is_flat_with_unrelated_siblings or is_container_with_single_child:
            return True

        return False

    # TODO: Duplicate method for flat_files
    def get_files_in_dirs(self):
        return [f for d in self.dirs.values() for f in d.files]

    def get_children_sorted(self) -> list["BooksTree"]:
        return list(sorted([*self.files, *self.dirs.values()], key=lambda x: x.path.name))

    @property
    def type(self):
        return "dir" if self.is_dir() else "file" if self.is_file() else "unknown"

    def determine_structure(
        self,
        parent: "BooksTree | None" = None,
    ) -> tuple[BookStructure2, ...]:
        """Determines the structure for a tree of audio files and directories. The tree should be in the
        format returned by find_tree_of_audio_files_in_dir()."""

        from src.lib.fs_utils import avg_path_name_similarity

        # from src.lib.parsers import (
        #     is_maybe_multiple_books_or_series,
        # )

        if not self.parent:
            self.parent = parent

        if not parent:
            parent = self

        root = parent.root or parent

        # if self already has structure, return it and don't re-calculate
        if self.structure and not self.has_structure("unknown"):
            return self.structure

        depth = len(self.path.relative_to(root.path).parts) if root else 0

        is_root = depth == 0

        if (self.is_root and not is_root) or (not self.is_root and is_root):
            raise ValueError(
                f"Root status of the current path and the root path do not match: {self.is_root=}, {is_root=}"
            )

        if is_root:
            self.set_structures("_root_")
            [d.determine_structure(self) for d in self.dirs.values()]
            [f.determine_structure(self) for f in self.files]
            return self.structure

        # --- standalone (no parent / parent == root)
        if self.is_file():
            if depth < 2:
                self.add_structures("standalone_file")
            else:
                if parent.has_structure("mixed"):
                    self.add_structures("mixed")
                elif parent.has_any_structure("multi_disc"):
                    self.add_structures("multi_disc")
                elif parent.has_any_structure("multi_part"):
                    self.add_structures("multi_part")
                elif parent.has_any_structure("series_parent"):
                    self.add_structures("series_book")
                else:
                    sibling_files = [f.path for f in parent.files]
                    if len(sibling_files) == 1:
                        self.add_structures("single")
                    else:
                        self.add_structures("flat")
                        if parent.has_any_structure("nested", "container"):
                            self.add_structures("nested")
            return self.structure

        if depth > 1 and not parent.structure:
            raise ValueError("Parent structure should be determined already for non-base directories")
        else:
            parent.structure = cast(tuple[BookStructure2, ...], parent.structure)

        parent_is_maybe_multi_or_series = (
            parent.dirs and not parent.is_root and not parent.has_any_structure("container")
        )
        only_has_dirs = bool(self.dirs and not self.files)
        has_files_and_dirs = bool(self.files and self.dirs)
        _only_has_files = bool(self.files and not self.dirs)

        if has_files_and_dirs or parent.has_structure("mixed"):
            # dir_struct = ("mixed",)
            self.set_structures("mixed")
        elif len(self.files) == 1 and not self.dirs:
            # dir_struct = ("single",)
            self.set_structures("single")
        elif len(self.files) > 1 and not self.dirs:
            # dir_struct = ("flat",)
            self.set_structures("flat")
            if parent.has_any_structure("nested", "container"):
                self.add_structures("nested")

        # if multi_disc_parent:
        if not parent.is_root:
            if parent.has_all_structures("multi_disc", "multi_parent"):
                self.set_structures("multi_disc")

            if parent.has_all_structures("multi_part", "multi_parent"):
                self.set_structures("multi_part")

            if parent.has_structure("series_parent"):
                self.add_structures("series_book")

            if self.has_no_structure():
                self.set_structures("unknown")

            if (
                depth > 1
                and (only_has_dirs and self.has_any_structure("single", "flat", "series_book"))
                or parent.has_structure("container")
            ):
                self.add_structures("nested")

            if parent_is_maybe_multi_or_series:

                # Most of the time series are named sensibly with numbers, but occasionally they are not.
                # If we think this is a series but is missing numbers, we need to check the children.
                # - If all children have the same series number, or none at all, it's probably a false positive.
                # - If the children have different series numbers, it's likely a series parent.
                # - If the children don't have series numbers, but are all files with dissimilar names, and
                #   sufficiently sized to be standalones, this is likely a series parent.

                is_known_multi = False

                n = TreeNumInfo(self)

                parent_ok = False
                children_ok = False
                siblings_seq = False
                siblings_match = False

                if n.likely_multi_disc:
                    # It's multi_disc or multi_part if:
                    #   - it has a disc or part no., and the children do not (or they match)
                    #   - its parent does not have a disc or part no.
                    #   - siblings have disc or part nos. that are sequential

                    parent_ok = not n.parent or not n.parent.has_disc_num
                    children_ok = not n.children.have_disc_nums or n.children.disc_nums_match_curr
                    siblings_seq = n.siblings.disc_nums_are_sequential
                    siblings_match = n.siblings.disc_nums_match_each_other

                elif n.likely_multi_part:

                    parent_ok = not n.parent or not n.parent.has_part_num
                    children_ok = not n.children.have_part_nums or n.children.part_nums_match_curr
                    siblings_seq = n.siblings.part_nums_are_sequential
                    siblings_match = n.siblings.part_nums_match_each_other

                elif n.likely_series:

                    parent_ok = not n.parent or (
                        (not n.parent.has_series_num and not n.parent.has_start_num)
                        or not n.parent.any_num_matches_curr
                    )
                    children_ok = (not n.children.have_series_nums or n.children.series_nums_match_curr) and (
                        not n.children.have_start_nums or n.children.start_nums_match_curr
                    )
                    siblings_seq = (n.siblings.have_series_nums and n.siblings.series_nums_are_sequential) or (
                        n.siblings.have_start_nums and n.siblings.start_nums_are_sequential
                    )
                    siblings_match = (n.siblings.have_series_nums and n.siblings.series_nums_match_each_other) or (
                        n.siblings.have_start_nums and n.siblings.start_nums_match_each_other
                    )

                if n.likely_multi_disc or n.likely_multi_part:
                    _structure = "multi_disc" if n.likely_multi_disc else "multi_part"
                    if (n.curr.has_disc_num or n.curr.has_part_num) and children_ok and parent_ok:
                        # We can safely recur on the parent, because we know it is a single title
                        # parent.add_structures(_structure, recursive=True)
                        if siblings_seq:
                            parent.set_structures("multi_parent")
                            parent.add_structures(_structure, recursive=True)
                        self.add_structures(_structure, recursive=True)
                        is_known_multi = True

                elif n.likely_series:
                    # It's a series_book if:
                    #   - it has a series no., and the children do not (or they match)
                    #   - its parent does not have a series no.

                    if (n.curr.has_series_num or n.curr.has_start_num) and children_ok and parent_ok:
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

                        if not self.dirs:
                            self.add_structures("flat", recursive="files")

                        # We can check siblings files to see if they are standalone
                        for f in parent.files:
                            f_similarity = avg_path_name_similarity(f.path, *[f.path for f in parent.files])
                            size_gt_100mb = f.path.stat().st_size > 1e8
                            # If the file names are dissimilar or the size is greater than 100mb, it's
                            # likely a standalone file and we probably don't want to merge it.
                            if f_similarity < 0.3 or size_gt_100mb:
                                f.add_structures("standalone_file", "series_book")

                    # If curr does not have series numbers but the children do,
                    # they must all be different (or we might have a false positive)
                    if not n.curr.has_any_num and n.children.have_any_nums:
                        if n.children.nums_match_each_other:
                            print_warning(
                                f"'{self}' might be a series_parent, but all its children have the same book number"
                            )
                            self.set_structures("mixed", recursive=True)
                    elif n.curr.has_any_num and n.parent and n.parent.any_num_matches_curr:
                        print_warning(f"'{self}' might be a series_book, but its parent has the same book number")

                # Add nested if it has a <struc> no. and child dirs
                if is_known_multi and n.curr.has_any_num and self.dirs:
                    self.add_structures("nested", recursive="dirs")

                if not is_known_multi:
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
                    self.set_structures("mixed")
                    [p.set_structures("mixed") for p in [*self.files, *self.dirs.values()]]

            if not parent.structure or parent.has_structure("unknown"):
                parent.set_structures(*self.structure)

        if not any([self.files, self.dirs]):
            self.set_structures("empty")
            return self.structure

        # If by this point there's no structure, we just have an arbitrary container
        if not self.structure or self.has_structure("unknown"):
            # If there are more than one dir or file (or both), it's a multi-mixed
            if len(self.files) + len(self.dirs) > 1:
                self.add_structures("mixed")
            elif self.dirs and not self.files:
                self.add_structures("container")

        # determine child structures
        [f.determine_structure(self) for f in self.files]
        [d.determine_structure(self) for d in self.dirs.values()]

        if not self.structure or self.has_structure("unknown"):
            raise ValueError(f"Did not determine structure for '{self}'")

        # Check all files and make sure none are unknown or ()
        if any([f.has_structure("unknown") for f in self.files]):
            raise ValueError(f"Did not determine structure for '{self}''s files, {self.files}")

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

        return self.structure

    def has_structure(self, structure: BookStructure2):
        return structure in self.structure

    def has_structure_like(self, match: str | BookStructure2):
        return any_matching(self.structure, [match])

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

    def has_no_structure(self):
        return not self.structure

    def add_structures(
        self,
        *structure: BookStructure2,
        recursive: bool | Literal["files", "dirs", "all", "none"] = False,
    ):
        if not structure:
            raise ValueError(
                "No structure provided when trying to add structures. Did you mean to call remove_structures() or clear_structure()?"
            )

        if "unknown" in self.structure:
            self.remove_structures("unknown")

        if any_in(structure, ["mixed"]) and any_matching(self.structure, ["multi_", "series_", "container"]):
            print_debug(
                f"{self.path} has {self.structure} but about to add 'mixed' which supercedes all structures, so removing all other structures"
            )
            self.set_structures("mixed", recursive=recursive)
            return self.structure

        if self.has_structure("mixed") and not structure == ("mixed",):
            print_debug(f"{self.path} has 'mixed' which is not compatible with {structure}, removing 'mixed'")
            self.remove_structures("mixed", recursive=recursive)

        if any_matching(structure, ["_parent"]):
            self.remove_structures("standalone_file", "single", "flat", "multi_disc", "multi_parent")

        if any_in(structure, ["series_book"]):
            self.remove_structures("series_parent")

        if any_in(structure, ["series_parent"]):
            self.remove_structures("series_book")

        if any_matching(
            structure,
            ["multi_", "series_", "container"],
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
                children = self.files
            case "dirs":
                children = self.dirs.values()
            case "all" | True:
                children = [*self.files, *self.dirs.values()]
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
                children = self.files
            case "dirs":
                children = self.dirs.values()
            case "all" | True:
                children = [*self.files, *self.dirs.values()]
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
        self.clear_structure(recursive=recursive)
        self.add_structures(*structure, recursive=recursive)
        return self.structure

    def clear_structure(self, recursive: bool | Literal["files", "dirs", "all", "none"] = False):
        self.structure = ()
        children = []
        match recursive:
            case "files":
                children = self.files
            case "dirs":
                children = self.dirs.values()
            case "all" | True:
                children = [*self.files, *self.dirs.values()]
        [c.clear_structure(recursive=recursive) for c in children]
        return self.structure

    def to_dict(self, *, fs_only: bool = False):
        if fs_only:
            return {
                "_files": [f.path.name for f in self.files],
                "_dirs": {k: v.to_dict(fs_only=fs_only) for k, v in self.dirs.items()},
            }
        return {
            "path": str(self.path),
            "files": [f.to_dict() for f in self.files],
            "dirs": {k: v.to_dict() for k, v in self.dirs.items()},
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
