import re
import time
from collections.abc import Callable, Sequence
from functools import cached_property
from pathlib import Path
from typing import Any, cast, Literal, overload, Self, TYPE_CHECKING, TypeVar

from pydantic import BaseModel, Field

from src.lib.books_tree.books_tree_summary import TreeNodeSummary
from src.lib.books_tree.books_tree_utils import filter_matches, match_filter_path, match_filter_paths
from src.lib.id3_tags import Id3Tags
from src.lib.misc import (
    any_in,
    any_matching,
    flatlist,
    isorted,
)
from src.lib.term import print_debug
from src.lib.typing import AudiobookFmt, BookStructure2, copy_kwargs

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook


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
    # size: int = 0
    # mindepth: int | None = None
    # maxdepth: int | None = None
    structure: tuple[BookStructure2, ...] = Field(default_factory=tuple)
    root: "BooksTree | None" = None
    _match_filter: list[Path] | str | None = None
    _last_scan: float | None = None
    id3_tags: Id3Tags | None = None

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
        scan_id3: bool = True,
    ):
        super().__init__()
        if isinstance(path, BooksTree):
            self = path
            return

        from src.lib.audiobook import Audiobook
        from src.lib.config import cfg
        from src.lib.fs_utils import try_relative_to

        self.path = path.path if isinstance(path, (Audiobook, self.__class__)) else Path(path)
        self.root = (
            root
            if isinstance(root, BooksTree)
            else BooksTree(root, scan=False, match_filter=match_filter, scan_id3=False) if root is not None else None
        )

        self._files: list["BooksTree"] = []
        self._dirs: dict[str, "BooksTree"] = {}

        if r := self.root:
            if self.path != r.path and (existing := r.get_path(self.path)) and existing.structure:
                self = existing
                assert id(self) == id(
                    existing
                ), f"Instance for '{self.path}' should be the same as the existing one because it already exists in self.root"
                return
            if not self.parent and (rel_to_root := try_relative_to(self.path, r.path)) and len(rel_to_root.parts) > 1:
                self.parent = r.get_like(rel_to_root.parent)
            else:
                self.parent = r

        self._match_filter = match_filter or cfg.MATCH_FILTER
        if scan or (scan is None and not root):
            self.scan(
                mindepth=mindepth,
                maxdepth=maxdepth,
                allow_file_root=allow_file_root,
                determine_structure=determine_structure,
                scan_id3=scan_id3,
            )
        # self.size = size
        # if structure:
        #     self.structure = structure

    def __repr__(self):
        if self.is_root or not self.root:
            return f"🌳 (root)"
        return f"🌳 {self.path.relative_to(self.root.path)} – {self.structure}"

    def __str__(self):
        return str(self.path)

    # Pydantic built-ins/overrides
    def model_post_init(self, __context):
        self.root = None if self.root is None else BooksTree(self.root, scan=False, scan_id3=False)

    @classmethod
    def cast(
        cls,
        path: "Path | BooksTree | str",
        *,
        root: "Path | BooksTree | None",
        match_filter: list[Path] | str | None = None,
        scan_id3: bool = False,
    ):
        """Casts a path to a TreePath without scanning it"""
        return BooksTree(path, root=root, scan=False, match_filter=match_filter, scan_id3=scan_id3)

    def _scan(
        self,
        *,
        mindepth: int | None = None,
        maxdepth: int | None = None,
        allow_file_root: bool = False,
        allow_non_root: bool = False,
        determine_structure: bool = True,
        scan_id3: bool = True,
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
            audio_files = match_filter_paths(audio_files, self.match_filter, root=root)
            for i, part in enumerate(parts):
                if part not in subtree._dirs:
                    parent_p = Path(root.path, *parts[: i + 1])
                    if not match_filter_path(parent_p, self.match_filter, root=root):
                        continue
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
                BooksTree.cast(f, root=root, match_filter=self.match_filter)
                for f in match_filter_paths(only_audio_files(filter_ignored(rglob)), self.match_filter, root=root)
                if f.parent == self.path and filter_depth(f, root.path, mindepth=mindepth, maxdepth=maxdepth, offset=-1)
            ]
        )

        self._last_scan = time.time()

        if scan_id3:
            if self.is_root:
                for f in [f for f in self.files_recursive if not f.id3_tags]:
                    f.id3_tags = Id3Tags.from_file(f.path)
            elif self.is_file() and not self.id3_tags:
                self.id3_tags = Id3Tags.from_file(self.path)

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
            raise ValueError(".get(): rel_path or key cannot be empty")

        root = self.root or self

        if isinstance(rel, BooksTree):
            rel = rel.path
        if isinstance(rel, str):
            rel = Path(rel)
        if isinstance(rel, Path) and rel.is_absolute():
            rel = rel.relative_to(root.path)
        if rel == Path("."):
            return self

        # Find the path in self.children_recursive
        return next((c for c in self.children_recursive if c.key == rel or c.rel_path == rel), None)

    def get_like(self, q: str | Path, case_sensitive: bool = False):
        """
        Gets a file or directory from the tree by a partial match or regex of its name.
        """
        if not q:
            raise ValueError(".get_like(): q cannot be empty")

        root = self.root or self

        if isinstance(q, Path):
            q = str(q)
        exp = re.compile(q, re.I) if not case_sensitive else re.compile(q)

        return next(
            (c for c in root.children_recursive if exp.search(str(c.rel_path))),
            None,
        )

    def get_path(self, q: Path):
        """
        Gets a file or directory from the tree by its path.
        """
        from src.lib.fs_utils import try_relative_to

        if not q or not isinstance(q, Path) or q == Path("."):
            raise ValueError(".get_like(): q cannot be empty or ('.')")

        root = self.root or self

        if (rel_to_root := try_relative_to(q, root.path)) and not rel_to_root == Path("."):
            if found := next(
                (c for c in root.children_recursive if c.rel_path == rel_to_root),
                None,
            ):
                return found
        return None

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
            if self.is_root:
                return None
            print_debug(f"No root found for '{self.name}' when accessing `key` prop")
            return self.name

        from src.lib.fs_utils import try_relative_to

        path_rel = (
            try_relative_to(self.path, root.path) if self.is_book_root or self.has_structure("series_parent") else None
        )
        name_rel = try_relative_to(self.path.name, root.path)

        return str(path_rel) if path_rel and path_rel != Path(".") else str(name_rel) if name_rel else None

    @property
    def size(self):
        try:
            if self.is_file():
                return self.path.stat().st_size
            return sum(f.size for f in self.files_recursive)
        except FileNotFoundError:
            return -1

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

        if not self.root or self.is_root or (self.depth < 2 and self.is_file()):
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
    def i(self) -> TreeNodeSummary:
        if self.is_root:
            return None  # type: ignore
        return TreeNodeSummary(self)

    @property
    def has_only_dirs(self):
        return bool(self._dirs and not self._files)

    @property
    def has_only_files(self):
        return bool(self._files and not self._dirs)

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
    def children_without_structure_r(self) -> list["BooksTree"]:
        return [c for c in self.children_recursive if not c.structure]

    @property
    def list_structures_r(self) -> list[BookStructure2]:
        """A list (set) of all structures found in all children."""
        return list(set([s for c in self.children_recursive for s in c.structure]))

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

        if self.is_match:
            ...

        if self.is_root or self.has_only_structure("container"):
            self._is_book_root = False
            return self._is_book_root

        if self.has_any_structure("standalone_file", "multi_parent"):
            self._is_book_root = True
            return self._is_book_root

        if self.has_structure("single") and (p := self.parent) and p.not_has_structure("single"):
            self._is_book_root = True
            return self._is_book_root

        if self.has_structure("flatish"):
            self._is_book_root = False
            return self._is_book_root

        if self.has_any_structure("flat", "mixed", "nested") and (
            self.depth == 1 or (p := self.parent) and p.has_any_structure("container", "series_parent", "multi_parent")
        ):
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

    @property
    def is_match(self):
        if not self.match_filter or not self.root:
            return False
        return bool(match_filter_paths([self.path], self.match_filter, root=self.root))

    def get_files_in_dirs(self):
        return [f for d in self._dirs.values() for f in d._files]

    @property
    def type(self):
        return "dir" if self.is_dir() else "file" if self.is_file() else "unknown"

    @property
    def score_container_mixed(self):
        from src.lib.scorers import score_container_mixed

        return score_container_mixed(self)

    @property
    def score_flat(self):
        from src.lib.scorers import score_flat

        return score_flat(self)

    @property
    def score_multi_part_or_disc(self):
        from src.lib.scorers import score_multi_part_or_disc

        return score_multi_part_or_disc(self)

    @property
    def score_multi_parent(self):
        from src.lib.scorers import score_multi_parent

        return score_multi_parent(self)

    @property
    def score_multi_part(self):
        from src.lib.scorers import score_multi_part_or_disc

        return score_multi_part_or_disc(self)

    @property
    def score_series_book(self):
        from src.lib.scorers import score_series_book

        return score_series_book(self)

    @property
    def score_series_parent(self):
        from src.lib.scorers import score_series_parent

        return score_series_parent(self)

    @property
    def score_single_standalone_file(self):
        from src.lib.scorers import score_single_standalone_file

        return score_single_standalone_file(self)

    def determine_structure(
        self,
        *,
        parent: "BooksTree | None" = None,
    ) -> tuple[BookStructure2, ...]:
        """Determines the structure for a tree of audio files and directories."""

        # Trying a multi-pass approach
        # 1. Find all flat dirs
        # 2. Find all standalone files
        # 3. Find all multi-disc dirs

        if not self.parent:
            self.parent = parent

        if not parent:
            parent = self

        root = parent.root or parent

        depth = len(self.path.relative_to(root.path).parts) if root else 0

        is_root = depth == 0

        if self.is_match:
            ...

        if (self.is_root and not is_root) or (not self.is_root and is_root):
            raise ValueError(
                f"Root status of the current path and the root path do not match: {self.is_root=}, {is_root=}"
            )

        if is_root:
            self.set_structures("_root_")
            if not self.dirs and not self.files:
                return self.structure

            [d.determine_structure(parent=self) for d in self.dirs.values()]
            [f.determine_structure(parent=self) for f in self.files]
            # Note: Disable this assertion when debugging with _match_filter_func()
            if self.children_without_structure_r:
                raise ValueError(
                    f"Expected structure to be determined for: {'\n'.join([str(c) for c in self.children_without_structure_r])}"
                )
            [c.determine_if_book_root() for c in self.children_recursive]
            return self.structure

        if self.is_match:
            ...

        if self.structure:
            return self.structure

        this_file = [self] if self.is_file() else []
        this_dir = [self] if self.is_dir() else []

        # File pass #1: standalone, single
        for f in this_file + self.files_recursive:

            std_or_single, standalone_score, single_score = f.score_single_standalone_file
            # standalone_gt_single = f.score_standalone_file > f.score_single

            if not std_or_single or (standalone_score < 0.5 and single_score < 0.5):
                continue

            f.add_structures(std_or_single)

        # Dir pass #1: single, multi-disc, multi-part, flat
        for d in this_dir + self.dirs_recursive:
            if self.is_match:
                ...
            # If dir is empty, set it to 'empty'
            if not d.files and not d.dirs:
                d.set_structures("empty")
                continue

            def check_nested(d: BooksTree):
                if (p := d.parent) and not p.is_root and len(p.dirs) == 1:
                    p.add_structures("nested", recursive=True)

            is_single = bool(d.files) and all(f.has_structure("single") for f in d.files)
            is_multi, multi_disc_score, multi_part_score = d.score_multi_part_or_disc
            is_flat = d.score_flat > 0.75 and all(
                d.score_flat > x for x in (multi_disc_score, multi_part_score, d.score_series_parent)
            )
            is_series_parent = d.score_series_parent > 0.75 and d.score_series_parent > d.score_series_book

            # if all files in dir are 'single', set dir to 'single' too
            if is_single:
                d.add_structures("single")
                check_nested(d)
            elif is_multi:
                if not self.structure:
                    self.set_structures(is_multi, "multi_parent")
                d.add_structures(is_multi, recursive=True)
                check_nested(d)
            elif is_flat:
                d.add_structures("flat", recursive=True)
                [cc.add_structures("flatish", recursive=True) for cc in d.children_recursive if cc.is_dir()]
                check_nested(d)
            elif is_series_parent:
                d.set_structures("series_parent")
                [cc.add_structures("series_book", recursive=True) for cc in d.children_recursive]
                [f.add_structures("standalone_file") for f in d.files if f.score_single_standalone_file[1] > 0.5]

        # Dir pass #2: mixed (too complex to determine)
        for c in this_file + this_dir + self.children_without_structure_r:
            if c.structure:
                continue

            container_or_mixed, _, _ = self.score_container_mixed
            if container_or_mixed == "container":
                c.set_structures(container_or_mixed)
            elif container_or_mixed == "mixed":
                c.set_structures("mixed", recursive=True)
            else:
                c.set_structures("unknown")

        # Determine uncaught nested for remaining dirs
        for d in this_dir + [c for c in self.children_without_structure_r if c.is_dir()]:
            if (
                inner_dir := (list(d.dirs.values())[0] if len(d.dirs) == 1 and not d.files else None)
            ) and inner_dir.has_any_structure("flat", "multi_parent"):
                d.add_structures(*inner_dir.structure)
                d.add_structures("nested", recursive=True)

        if self.is_match:
            ...

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

        if not structure:
            raise ValueError(
                "No structure provided when trying to add structures. Did you mean to call remove_structures() or clear_structure()?"
            )

        if "unknown" in self.structure:
            self.remove_structures("unknown")

        if any_in(structure, ["flat"]) and any_in(self.structure, ["single", "standalone_file"]):
            self.remove_structures("single", "standalone_file")
        elif any_in(structure, ["single", "standalone_file"]) and self.has_structure("flat"):
            self.remove_structures("flat")

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
            # raise ValueError(f"Tried to add {structure} to {self.path} which has {self.structure}")
            print_debug(f"Tried to add {structure} to {self.path} which has {self.structure}")

        # After all the checks, set the structure
        for s in structure:
            if not s in self.structure:
                self.structure += (s,)

        children = []
        match recursive:
            case "files":
                children = self.files_recursive
            case "dirs":
                children = self.dirs_recursive
            case "all" | True:
                children = self.children_recursive
        [c.add_structures(*structure) for c in children]

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
