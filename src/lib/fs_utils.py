import fnmatch
import os
import re
import shutil
import time
from collections.abc import Generator, Iterable
from pathlib import Path
from typing import Any, cast, Literal, NamedTuple, overload, TYPE_CHECKING

from src.lib.config import AUDIO_EXTS
from src.lib.misc import (
    flatlist,
    isorted,
    sh,
    try_get_stat_mtime,
)
from src.lib.term import (
    print_error,
    print_grey,
    print_notice,
    print_warning,
)
from src.lib.typing import (
    AudiobookFmt,
    BookHashesDict,
    copy_kwargs_omit_first_arg,
    Operation,
    OVERWRITE_MODES,
    OverwriteMode,
    PathType,
    SizeFmt,
)

if TYPE_CHECKING:
    from src.lib.books_tree import BooksTree

    pass


# @overload
# def find_files_in_dir(
#     d: Path,
#     *,
#     resolve: Literal[False] = False,
#     ignore_files: list[str] = [],
#     only_file_exts: list[str] = [],
#     mindepth: int | None = None,
#     maxdepth: int | None = None,
# ) -> list[str]: ...


@overload
def find_files_in_dir(
    d: Path,
    *,
    resolve: Literal[True] = True,
    ignore_files: list[str] | None = None,
    only_file_exts: list[str] | None = None,
    mindepth: int | None = None,
    maxdepth: int | None = None,
) -> list[Path]: ...


@overload
def find_files_in_dir(
    d: Path,
    *,
    resolve: Literal[False] = False,
    ignore_files: list[str] | None = None,
    only_file_exts: list[str] | None = None,
    mindepth: int | None = None,
    maxdepth: int | None = None,
) -> list[str | Path]: ...


def find_files_in_dir(  # type: ignore
    d: Path,
    *,
    resolve: bool | None = None,
    ignore_files: list | None = None,
    only_file_exts: list[str] | None = None,
    mindepth: int | None = None,
    maxdepth: int | None = None,
) -> list[str | Path]:
    """
    Finds all files in a directory and its subdirectories.

    Parameters:
    d (Path): The base directory to start the search from.
    resolve (bool, optional): Whether to resolve to absolute paths. Defaults to False (only returns files relative to the base directory).
    ignore_files (list[str], optional): A list of file names to ignore. Defaults to [].
    only_file_exts (list[str], optional): A list of file extensions to include in the count. Defaults to AUDIO_EXTS.
    mindepth (int | None, optional): The minimum depth of directories to search. This is 0-based, so a mindepth of 0 includes files directly in the base directory. Defaults to None, which includes all depths.
    maxdepth (int | None, optional): The maximum depth of directories to search. This is 0-based, so a maxdepth of 0 includes only files directly in the base directory. Defaults to None, which includes all depths.

    Returns:
    list[str | Path]: A list of file names (str) or Path objects (if absolute=True)
    """
    from src.lib.formatters import ensure_dot

    ignore_files = ignore_files or []
    only_file_exts = [ensure_dot(ext) for ext in only_file_exts or []]

    if d.is_file():
        raise NotADirectoryError(f"'find_files_in_dir': {d} is a file, not a directory")

    def depth(p: Path) -> int:
        return len(p.parts) - len(d.parts)

    return isorted(
        [
            f if resolve else str(f.relative_to(d))
            for f in d.rglob("*")
            if all(
                [
                    f.is_file(),
                    not f.name.startswith("."),
                    f.name not in ignore_files,
                    not only_file_exts or f.suffix in only_file_exts,
                    mindepth is None or depth(f) >= mindepth,
                    maxdepth is None or depth(f) <= maxdepth,
                ]
            )
        ]
    )


def count_audio_files_in_dir(
    d: Path,
    *,
    only_file_exts: list[str] = [],
    mindepth: int | None = None,
    maxdepth: int | None = None,
) -> int:
    """
    Count the number of audio files in a directory and its subdirectories.

    Parameters:
    d (Path): The base directory to start the search from.
    only_file_exts (list[str], optional): A list of file extensions to include in the count. Defaults to AUDIO_EXTS.
    mindepth (int | None, optional): The minimum depth of directories to search. This is 0-based, so a mindepth of 0 includes files directly in the base directory. Defaults to None, which includes all depths.
    maxdepth (int | None, optional): The maximum depth of directories to search. This is 0-based, so a maxdepth of 0 includes only files directly in the base directory. Defaults to None, which includes all depths.

    Returns:
    int: The number of audio files found.
    """

    audio_files = find_files_in_dir(
        d,
        resolve=True,
        only_file_exts=only_file_exts or AUDIO_EXTS,
        mindepth=mindepth,
        maxdepth=maxdepth,
    )

    return len(audio_files)


# def count_audio_files_in_inbox() -> int:
#     from src.lib.config import cfg

#     return count_audio_files_in_dir(cfg.inbox_dir, only_file_exts=cfg.AUDIO_EXTS)


# def count_standalone_books_in_inbox() -> int:
#     return len(find_standalone_books_in_inbox())


@overload
def get_size(path: Path, fmt: Literal["bytes"] = "bytes", only_file_exts: list[str] = []) -> int: ...


@overload
def get_size(path: Path, fmt: Literal["human"] = "human", only_file_exts: list[str] = []) -> str: ...


def get_size(path: Path, fmt: SizeFmt = "bytes", only_file_exts: list[str] = []) -> str | int:
    # takes a file or directory and returns the size in either bytes or human readable format, only counting audio files
    # if no path specified, assume current directory
    from src.lib.formatters import human_size

    if not path.exists():
        raise FileNotFoundError(f"Cannot get size, '{path}' does not exist")

    def file_ext_ok(f: Path) -> bool:
        return f.suffix in only_file_exts if only_file_exts else True

    size: int = -1

    # if path is a file, return its size
    if path.is_file():
        if not file_ext_ok(path):
            raise ValueError(f"File {path} is not an audio file")
        size = path.stat().st_size
    elif path.is_dir():
        size = sum(f.stat().st_size for f in path.glob("**/*") if f.is_file() and file_ext_ok(f))
    return human_size(size) if fmt == "human" else size


@overload
def get_audio_size(path: Path, fmt: Literal["bytes"] = "bytes") -> int: ...


@overload
def get_audio_size(path: Path, fmt: Literal["human"] = "human") -> str: ...


def get_audio_size(path: Path, fmt: SizeFmt = "bytes"):
    return get_size(path, fmt=fmt, only_file_exts=AUDIO_EXTS)


def is_ok_to_delete(
    path: Path,
    max_size: int = 10240,
    only_file_exts: list[str] = [],
    ignore_hidden: bool = True,
) -> bool:
    src_dir_size = get_size(path, fmt="bytes")

    if ignore_hidden:
        files = [f for f in path.rglob("*") if f.is_file() and not f.name.startswith(".")]

    else:
        files = [f for f in path.rglob("*") if f.is_file()]

    # ok to delete if no visible or un-ignored files or if size is less than 10kb
    return len(filter_ignored(files)) == 0 or src_dir_size < max_size


def check_src_dst(
    src: Path,
    src_type: PathType,
    dst: Path,
    dst_type: PathType,
    overwrite_mode: OverwriteMode | None = None,
):
    # valid overwrite modes are "skip" (default), "overwrite", and "overwrite-silent"
    if overwrite_mode and overwrite_mode not in OVERWRITE_MODES:
        raise ValueError("Invalid overwrite mode")

    # if dst should be dir but does not exist, try to create it
    if dst_type == "dir" and not dst.is_dir():
        dst.mkdir(parents=True, exist_ok=True)

    # if src or dst do not exist, raise an error
    if not src.exists():
        raise FileNotFoundError(f"Source {src_type} {src} does not exist")

    if not dst.exists():
        raise FileNotFoundError(f"Destination {dst_type} {dst} does not exist")

    if src_type == "dir" and not src.is_dir():
        raise NotADirectoryError(f"Source {src} is not a directory")

    if src_type == "file" and not src.is_file():
        raise FileNotFoundError(f"Source {src} is not a file")

    if dst_type == "dir" and not dst.is_dir():
        raise NotADirectoryError(f"Destination {dst} is not a directory")

    if dst_type == "file" and not dst.parent.is_dir():
        raise NotADirectoryError(f"Destination parent dir {dst.parent} does not exist")

    if dst_type == "file" and dst.is_file() and overwrite_mode == "skip":
        raise FileExistsError(f"Destination file {dst} already exists and overwrite mode is 'skip'")

    return True


def src_and_dst_are_on_same_partition(src: Path, dst: Path) -> bool:
    return src.stat().st_dev == dst.stat().st_dev


def rm_dir(dir_path: Path, ignore_errors: bool = False, even_if_not_empty: bool = False):
    # Remove the directory and handle errors
    if not dir_path.is_dir():
        return
    if not is_ok_to_delete(dir_path) and not even_if_not_empty:
        if ignore_errors:
            return
        raise OSError(f"Unable to delete {dir_path}, please delete it manually and try again")
    shutil.rmtree(dir_path, ignore_errors=True)


def rm_all_empty_dirs(dir_path: Path):
    # Recursively remove all empty directories in the current directory, using ok_to_del
    for current_dir in dir_path.glob("**"):
        if current_dir.is_dir() and not any(current_dir.iterdir()) and is_ok_to_delete(current_dir):
            rm_dir(current_dir, ignore_errors=True)


def _mv_or_cp_dir_contents(
    operation: Operation,
    src_dir: Path,
    dst_dir: Path,
    *,
    overwrite_mode: OverwriteMode | None = None,
    ignore_files: list[str] = [],
    silent_files: list[str] = [],
    only_file_exts: list[str] = [],
    keep_src_dir: bool = False,
):
    """Moves or copies the contents of a source directory into a destination directory. For example:

    `cp_dir_contents('/path/to/src', '/path/to_other/dst')` # or
    `mv_dir_contents('/path/to/src', '/path/to_other/dst')`

    ...will result in:

    `/path/to_other/dst/file1`
    `/path/to_other/dst/file2`
    `/path/to_other/dst/file3`

    If moving, and the source directory is empty after moving files, it will be removed.

    Default overwrite mode is 'skip', which will raise an error if the destination directory already exists, because we shouldn't ever be automatically overwriting an entire directory.
    """
    from src.lib.config import cfg

    if operation not in ["move", "copy"]:
        raise ValueError("Invalid operation")

    rm_empty_src_dir = operation == "move" and not keep_src_dir

    overwrite_mode = overwrite_mode or cfg.OVERWRITE_MODE

    if not check_src_dst(src_dir, "dir", dst_dir, "dir", overwrite_mode):
        raise FileNotFoundError("Source or destination directory does not exist")

    if operation == "move" and not src_and_dst_are_on_same_partition(src_dir, dst_dir):
        # print_debug(
        #     f"Source and destination are not on the same partition, using copy instead of move\n src: {src_dir}\n dst: {dst_dir}"
        # )
        operation = "copy"

    # ignore if src ends in .bak
    if str(src_dir).endswith(".bak"):
        print_notice(f"Source {src_dir} ends in .bak, ignoring")
        return

    verbed = "moved" if operation == "move" else "copied"
    verbing = "moving" if operation == "move" else "copying"

    # Check source and destination directories
    if not check_src_dst(src_dir, "dir", dst_dir, "dir", overwrite_mode):
        raise FileNotFoundError("Source or destination directory does not exist")

    # Check for files that may require overwriting
    files_common_to_both = set(find_files_in_dir(src_dir, ignore_files=ignore_files)) & set(
        find_files_in_dir(dst_dir, ignore_files=ignore_files)
    )

    # remove files that are in silent_files from files_common_to_both
    files_common_to_both = [f for f in files_common_to_both if f not in silent_files]

    if files_common_to_both and not overwrite_mode.endswith("silent"):
        if overwrite_mode == "overwrite":
            print_warning(f"Warning: Some files in {dst_dir} will be overwritten:")
        else:
            print_error(f"Error: Some files already exist in {dst_dir} and will not be {verbed}:")

        for file in files_common_to_both:
            print_grey(f"     - {file}")

    if not any(src_dir.iterdir()):
        # print_notice(f"No files found in {src_dir}, skipping")
        return

    def ok_to_mv_or_cp(src_file: Path, dst_file: Path) -> bool:

        if any(
            [
                (not src_file.is_file()),
                (src_file.name in ignore_files),
                (only_file_exts and src_file.suffix not in only_file_exts),
                (dst_file.is_file() and not overwrite_mode.startswith("overwrite")),
            ]
        ):
            return False

        return True

    files_not_verbed = []

    for src_file in src_dir.glob("*"):
        if src_file.is_dir():
            _mv_or_cp_dir_contents(
                operation,
                src_file,
                dst_dir / src_file.name,
                overwrite_mode=overwrite_mode,
                ignore_files=ignore_files,
                only_file_exts=only_file_exts,
            )
        dst_file = dst_dir / src_file.name
        if ok_to_mv_or_cp(src_file, dst_file):
            if operation == "copy":
                shutil.copy2(src_file, dst_file)
            elif operation == "move":
                shutil.move(src_file, dst_file)
            if not dst_file.is_file():
                files_not_verbed.append(src_file)

    # files_not_in_right = set(find_files(src_dir, ignore_files)) - set(
    #     find_files(dst_dir, ignore_files)
    # )

    if files_not_verbed:
        if not overwrite_mode.endswith("silent"):
            print_error(f"Error: Some files in {src_dir} could not be {verbed}:")
            for file in files_not_verbed:
                print_grey(f"     - {file}")
        if overwrite_mode == "overwrite":
            err = f"Some files in {src_dir} could not be {verbed}"
            raise FileNotFoundError(err)

    # Remove the source directory if empty and conditions permit, if moving
    if rm_empty_src_dir and operation == "move" and is_ok_to_delete(src_dir, only_file_exts=only_file_exts):
        try:
            rm_dir(src_dir)
        except OSError:
            print_warning(f"Warning: {src_dir} was not deleted after {verbing} files because it is not empty")


@copy_kwargs_omit_first_arg(_mv_or_cp_dir_contents)
def mv_dir_contents(*args, **kwargs):
    _mv_or_cp_dir_contents("move", *args, **kwargs)


@copy_kwargs_omit_first_arg(_mv_or_cp_dir_contents)
def cp_dir_contents(*args, **kwargs):
    _mv_or_cp_dir_contents("copy", *args, **kwargs)


def _mv_or_copy_dir(
    operation: Operation,
    src_dir: Path,
    dst_dir: Path,
    *,
    overwrite_mode: OverwriteMode = "skip",
    silent_files: list[str] = [],
):
    """Moves or copies the source directory *into* the destination directory. For example:

    `cp_dir('/path/to/src', '/path/to_other/dst')`

    ...will result in:

    `/path/to_other/dst/src`

    Default overwrite mode is 'skip', which will raise an error if the destination directory already exists, because we shouldn't ever be automatically overwriting an entire directory.
    """

    # check that both are dirs:
    check_src_dst(src_dir, "dir", dst_dir, "dir", overwrite_mode)

    # check that src_dir.name and dst_dir.name are not the same, if they are, append src_dir.name to dst_dir
    if src_dir.name == dst_dir.name:
        print_warning(
            f"Warning: It looks like you tried to use mv_dir or cp_dir by including the destination directory name in the path, e.g. mv_dir('/path/to/dir', '/path/to_other/dir'). This will result in the source directory being moved into the destination directory, e.g. /path/to_other/dir/dir. If you want to move the contents of the source directory into the destination directory, use mv_dir_contents or cp_dir_contents instead."
        )

    dst_dir = dst_dir / src_dir.name
    _mv_or_cp_dir_contents(
        operation,
        src_dir,
        dst_dir,
        overwrite_mode=overwrite_mode,
        silent_files=silent_files,
    )


@copy_kwargs_omit_first_arg(_mv_or_copy_dir)
def mv_dir(*args, **kwargs):
    """Moves a directory into the destination dir, creating the destination directory if it does not
    exist. For example, mv_dir('/path/to/src', '/path/to_other/dst') will result in /path/to_other/dst/src."""
    _mv_or_copy_dir("move", *args, **kwargs)


@copy_kwargs_omit_first_arg(_mv_or_copy_dir)
def cp_dir(*args, **kwargs):
    """Copies a directory into the destination dir, creating the destination directory if it does not
    exist. For example, cp_dir('/path/to/src', '/path/to_other/dst') will result in /path/to_other/dst/src."""
    _mv_or_copy_dir("copy", *args, **kwargs)


def rename_dir(dir_path: Path, new_name: str | Path, ignore_errors: bool = False):
    """Renames a directory. If the new name is a Path object, the directory is moved to the new path."""

    dst = dir_path.parent / new_name if isinstance(new_name, str) else new_name
    try:
        check_src_dst(dir_path, "dir", dst, "dir", overwrite_mode="skip")
    except Exception as e:
        if ignore_errors:
            return
        raise e
    if dst.exists() and (dst.is_file() or not dir_is_empty_ignoring_files(dst)):
        if ignore_errors:
            return
        raise FileExistsError(
            f"{dir_path} cannot be renamed to {new_name}, a file or folder with that name already exists"
        )

    _mv_or_cp_dir_contents("move", dir_path, dst, overwrite_mode="skip", keep_src_dir=False)


def mv_file_into_dir(
    source_file: Path,
    dst_dir: Path,
    *,
    new_filename: str | None = None,
    overwrite_mode: OverwriteMode | None = None,
) -> None:
    check_src_dst(source_file, "file", dst_dir, "dir", overwrite_mode)

    dst_file = dst_dir / source_file.name if new_filename is None else dst_dir / new_filename
    str_overwrite_mode = str(overwrite_mode)

    if dst_file.exists():
        if "skip" in str_overwrite_mode:
            if not "silent" in str_overwrite_mode:
                raise FileExistsError(f"Destination file '{dst_file}' already exists and overwrite mode is 'skip'")
            return
        elif not "silent" in str_overwrite_mode:
            print_warning(f"Warning: '{dst_file}' already exists and will be overwritten")
        dst_file.unlink(missing_ok=True)

    # Move the file
    shutil.move(source_file, dst_file)


def cp_file_into_dir(
    source_file: Path,
    dst_dir: Path,
    new_filename: str | None = None,
    overwrite_mode: OverwriteMode | None = None,
) -> None:
    # Check source and destination
    check_src_dst(source_file, "file", dst_dir, "dir", overwrite_mode)

    dst_file = dst_dir / new_filename if new_filename else dst_dir / source_file.name
    str_overwrite_mode = str(overwrite_mode)

    if dst_file.is_file():
        if "skip" in str_overwrite_mode:
            if not "silent" in str_overwrite_mode:
                raise FileExistsError(f"Destination file {dst_file} already exists and overwrite mode is 'skip'")
            return
        elif not "silent" in str_overwrite_mode:
            print_warning(f"Warning: {dst_file} already exists and will be overwritten")

    # Copy the file
    shutil.copy2(source_file, dst_dir)

    # Rename the file if new_filename is specified
    if new_filename:
        shutil.move(dst_dir / source_file.name, dst_file)


def dir_is_empty_ignoring_files(d: Path) -> bool:
    if not d.is_dir():
        return True
    return not any(filter_ignored(f for f in d.iterdir() if not f.name.startswith(".")))


def flatten_files_in_dir(
    path: Path,
    *,
    preview: bool = False,
    on_conflict: Literal["raise", "skip"] = "skip",
):
    """Given a directory, moves all files in any subdirectories to the root directory then removes the subdirectories."""
    if not path.is_dir():
        raise NotADirectoryError(f"Error: {path} is not a directory")

    # if path is a dir, get all files in the dir and its subdirs
    files = [f for f in filter_ignored(list(isorted(path.rglob("*")))) if f.is_file()]
    new_files = []
    for f in files:
        new_files.append(path / f.name)
        if not preview:
            # if file would overwrite an existing file, raise or skip
            if (path / f.name).exists():
                if on_conflict == "raise":
                    raise FileExistsError(f"Error: {path / f.name} already exists in the directory")
                elif on_conflict == "skip":
                    continue
            shutil.move(f, path / f.name)

    # remove the subdirs
    if not preview:
        for d in path.rglob("*"):
            if d.is_dir() and dir_is_empty_ignoring_files(d):
                shutil.rmtree(d, ignore_errors=True)

    return new_files


def flattening_files_in_dir_affects_order(path: Path) -> bool:
    """Compares the order of files in a directory, both before and after flattening, by checking if the file names are in the same order."""

    files_flat = [f.name for f in filter_ignored(flatten_files_in_dir(path, preview=True))]
    files_flat_sorted = isorted(list(set(files_flat)))
    if len(files_flat) != len(files_flat_sorted):
        return True

    return only_audio_files(files_flat_sorted) != only_audio_files(files_flat)


def name_matches(name: Any, match_filter: str | None = None) -> bool:
    from src.lib.config import cfg

    if cfg.MATCH_FILTER:
        match_filter = cfg.MATCH_FILTER

    if not match_filter:
        return True

    return re.search(match_filter, str(name), re.I) is not None


@overload
def try_relative_to(p: str, root: str) -> str | None: ...


@overload
def try_relative_to(p: Path, root: Path) -> Path | None: ...


@overload
def try_relative_to(p: str, root: Path) -> Path | None: ...


@overload
def try_relative_to(p: Path, root: str) -> Path | None: ...


@overload
def try_relative_to(p: "BooksTree", root: "BooksTree") -> str | Path | None: ...


@overload
def try_relative_to(p: str, root: "BooksTree") -> Path | None: ...


@overload
def try_relative_to(p: Path, root: "BooksTree") -> Path | None: ...


def try_relative_to(p: "str | Path | BooksTree", root: "str | Path | BooksTree") -> str | Path | None:
    from src.lib.books_tree import BooksTree

    try:
        _p = p.path if isinstance(p, BooksTree) else Path(p)
        _root = root.path if isinstance(root, BooksTree) else Path(root)
        rel = _p.relative_to(_root)
        if isinstance(_p, str) and isinstance(rel, Path):
            return str(rel)
        return cast(Path, rel)
    except ValueError:
        return None


def find_audio_files_in_dir(
    d: Path,
    ignore_errors: bool = False,
    only_file_exts: list[str] = [],
) -> list[Path]:
    """Given a path, returns a list of audio files immediately within the directory (does not search subdirectories)."""

    if not d.is_dir():
        if ignore_errors:
            return []
        raise NotADirectoryError(f"Error: {d} is not a directory")

    return only_audio_files(filter_ignored(isorted(d.glob("*"))))


def is_valid_dir(root: Path, d: Path, mindepth: int | None = None, maxdepth: int | None = None) -> bool:
    """Checks if a directory is valid based on the specified conditions."""

    def _depth(p: Path) -> int:
        return len(p.parts) - len(root.parts)

    return d.is_dir() and all(
        [
            count_audio_files_in_dir(d, mindepth=0, maxdepth=1) > 0,
            mindepth is None or _depth(d) >= mindepth,
            maxdepth is None or _depth(d) <= maxdepth,
        ]
    )


# def find_base_dirs_with_audio_files(
#     root: Path,
#     mindepth: int | None = None,
#     maxdepth: int | None = None,
#     ignore_errors: bool = False,
# ) -> list[Path]:
#     """Given a root directory, returns a list of all base directories that contain audio files. E.g.,
#     if the root directory is '/path/to' and contains:
#     - /path/to/folder1/file1
#     - /path/to/folder1/folder2/file2
#     - /path/to/folder1/folder2/file3
#     - /path/to/folder1/folder2/file4
#     - /path/to/folder2/file1
#     - /path/to/folder2/file2
#     - /path/to/folder2/folder3/file3

#     then the return value will be:
#     - /path/to/folder1
#     - /path/to/folder2
#     """

#     if not root.is_dir():
#         if ignore_errors:
#             return []
#         raise NotADirectoryError(f"Error: {root} is not a directory")

#     all_roots_with_audio_files = list(
#         set([root / d.relative_to(root).parts[0] for d in root.rglob("*") if is_valid_dir(root, d)])
#     )

#     return list(isorted(all_roots_with_audio_files))


# def find_series_parents_in_inbox():
#     return find_tree_of_audio_files_in_dir(cfg.inbox_dir, mindepth=1).dirs.values()


# def find_book_dirs_in_inbox(exclude_series_parents: bool = False, only_series_parents: bool = False) -> list[TreePath]:
#     from src.lib.config import cfg

#     if all([only_series_parents, exclude_series_parents]):
#         raise ValueError("`exclude_series_parents` and `only_series_parents` cannot both be True")

#     flat_dirs = find_tree_of_audio_files_in_dir(cfg.inbox_dir, mindepth=1).dirs_flat

#     # book_dirs = find_base_dirs_with_audio_files(cfg.inbox_dir, mindepth=1)
#     return list(find_tree_of_audio_files_in_dir(cfg.inbox_dir, mindepth=1).dirs.values())

# book_dirs = list(tree.dirs.values())

# books_info = [(d, *find_book_audio_files(d)) for d in book_dirs]
# # look in each book dir to see if it is maybe a multi-book series
# for path, structure, _ in books_info.copy():
#     if structure == "multi_book_series":
#         if only_series_parents:
#             continue
#         parent_idx = book_dirs.index(path)
#         series_book_dirs = find_base_dirs_with_audio_files(path, mindepth=1)
#         # splice the series book dirs into the main list
#         book_dirs[parent_idx + 1 : parent_idx + 1] = series_book_dirs
#         if exclude_series_parents:
#             book_dirs.remove(path)
#     elif only_series_parents:
#         book_dirs.remove(path)

# return book_dirs


def find_book_dirs_for_series(parent_dir: "BooksTree"):

    return parent_dir.books


# def find_standalone_books_in_inbox():
#     return find_tree_of_audio_files_in_dir(cfg.inbox_dir, mindepth=1).files
# return isorted(
#     [
#         file
#         for ext in AUDIO_EXTS
#         for file in cfg.inbox_dir.glob(f"*{ext}")
#         if len(file.relative_to(cfg.inbox_dir).parts) == 1
#     ]
# )


def find_adjacent_files_with_same_basename(path: Path, only_file_exts: list[str] = []) -> list[Path]:
    return isorted(
        [
            f
            for f in path.parent.glob(f"{path.stem}.*")
            if f.is_file() and (not only_file_exts or f.suffix in only_file_exts)
        ]
    )


# def find_books_in_inbox():
#     return isorted(find_book_dirs_in_inbox() + find_standalone_books_in_inbox())


# def find_book_audio_files(
#     book: "Audiobook | Path",
# ) -> tuple[BookStructure, InboxDirMap]:
#     """Given a book directory, returns a tuple of the book's directory structure type, and a map of the book's audio files."""
#     from src.lib.config import cfg
#     from src.lib.parsers import (
#         is_maybe_multi_disc,
#         is_maybe_multi_part,
#         is_maybe_multiple_books_or_series,
#     )

#     path = book if isinstance(book, Path) else book.inbox_dir

#     if path.is_file():
#         return ("standalone_file", [(path,)])

#     all_audio_files = find_files_in_dir(path, resolve=True, only_file_exts=cfg.AUDIO_EXTS)
#     root_audio_files = [f for f in all_audio_files if f.parent == path]

#     if not all_audio_files:
#         return ("empty", [])

#     if len(all_audio_files) == 1:
#         return ("single", [(all_audio_files[0],)])

#     root_audio_files_tuples: InboxDirMap = [(f,) for f in root_audio_files]

#     if len(root_audio_files) == len(all_audio_files):
#         return ("flat", root_audio_files_tuples)

#     # generate a dictionary of nested audio files keyed by the directory they're in
#     nested_audio_files_dict = {
#         d: [f for f in all_audio_files if f.parent == d]
#         for d in [f.parent for f in all_audio_files]
#         if d != path and d.is_dir()
#     }

#     nested_audio_dirs = nested_audio_files_dict.keys()

#     if not root_audio_files and len(nested_audio_files_dict) == 1:
#         first_nested_dir = next(iter(nested_audio_dirs))
#         return (
#             "flat_nested",
#             [
#                 (
#                     first_nested_dir,
#                     nested_audio_files_dict[first_nested_dir],
#                 )
#             ],
#         )

#     # if audio files exist in more than one level, return the structure as "mixed"
#     number_of_different_levels = len(set([len(f.relative_to(path).parts) for f in all_audio_files]))
#     if number_of_different_levels > 1:
#         nested_dirs_tuples: InboxDirMap = [(d, nested_audio_files_dict[d]) for d in nested_audio_files_dict]
#         return (
#             "mixed",
#             cast(InboxDirMap, root_audio_files_tuples + nested_dirs_tuples),
#         )

#     multi_disc = any(is_maybe_multi_disc(d.name) for d in nested_audio_dirs)
#     multi_part = any(is_maybe_multi_part(d.name) for d in nested_audio_dirs)
#     book_series = False

#     if not multi_disc and not multi_part:
#         if not (book_series := any(is_maybe_multiple_books_or_series(d.name) for d in nested_audio_dirs)):
#             nested_basenames = [str(d.relative_to(cfg.inbox_dir)) for d in nested_audio_dirs]
#             if any("series" in str(d).lower() for d in nested_basenames):
#                 book_series = any(is_maybe_multiple_books_or_series(b) for b in nested_basenames)

#     file_map = [
#         *[(f,) for f in root_audio_files],
#         *[(d, find_files_in_dir(d, resolve=True, only_file_exts=cfg.AUDIO_EXTS)) for d in nested_audio_dirs],
#     ]

#     struc: BookStructure
#     if book_series:
#         struc = "multi_book_series"
#     elif multi_disc:
#         struc = "multi_disc"
#     elif multi_part:
#         struc = "multi_part"
#     elif len(nested_audio_dirs) > 0 and number_of_different_levels == 1:
#         struc = "multi_nested"
#     else:
#         struc = "mixed"

#     return (
#         struc,
#         file_map,
#     )


def find_too_small_files(a: Path, b: Path) -> list[Path]:
    return [
        a
        for (a, b) in zip(
            [f for f in a.glob("*") if f.is_file()],
            [f for f in b.glob("*") if f.is_file()],
        )
        if a.stat().st_size > b.stat().st_size
    ]


def clean_dir(dir_path: Path) -> None:
    dir_path = dir_path.resolve()

    rm_dir(dir_path, ignore_errors=True, even_if_not_empty=True)

    # Recreate the directory
    dir_path.mkdir(parents=True, exist_ok=True)

    # Check if the directory is writable
    if not os.access(dir_path, os.W_OK):
        raise PermissionError(f"'{dir_path}' is not writable by current user, please fix permissions and try again")

    # Check if the directory is empty
    if any(filter_ignored(dir_path.iterdir())):
        raise OSError(f"'{dir_path}' is not empty, please empty it manually and try again")


def clean_dirs(dirs: list[Path]) -> None:
    for d in dirs:
        clean_dir(d)


def rm_dirs(dirs: list[Path], ignore_errors: bool = False, even_if_not_empty: bool = True) -> None:
    for d in dirs:
        rm_dir(d, ignore_errors, even_if_not_empty)


@overload
def find_first_audio_file(
    path: Path, *, ext: AudiobookFmt | None = None, ignore_errors: Literal[False] = False
) -> Path: ...


@overload
def find_first_audio_file(
    path: Path, *, ext: AudiobookFmt | None = None, ignore_errors: Literal[True] = True
) -> Path | None: ...


@overload
def find_first_audio_file(
    path: Path, *, ext: AudiobookFmt | None = None, ignore_errors: bool = True
) -> Path | None: ...


def find_first_audio_file(path: Path, *, ext: AudiobookFmt | None = None, ignore_errors: bool = False) -> Path | None:
    from src.lib.formatters import strip_dot

    if path.is_file():
        return path

    if not path.exists():
        if not ignore_errors:
            raise FileNotFoundError(f"Directory '{path}' does not exist")
        return None

    files = find_files_in_dir(path, resolve=True, only_file_exts=[ext] if ext else AUDIO_EXTS)

    if not files:
        if not ignore_errors:
            err = f"No audio files found in '{path}'"
            if fmt := strip_dot(ext) if ext else None:
                err += f" with extension '{fmt}'"
            raise FileNotFoundError(err)
        return None

    return files[0]


def find_next_audio_file(
    path: Path, *, first: Path | None, ext: AudiobookFmt | None = None, ignore_errors: bool = False
) -> Path | None:
    from src.lib.formatters import strip_dot

    if path.is_file():
        return None

    if not path.exists():
        if not ignore_errors:
            raise FileNotFoundError(f"Directory '{path}' does not exist")
        return None

    err = f"No more audio files found in '{path}'"
    if fmt := strip_dot(ext) if ext else None:
        err += f" with extension '{fmt}'"
    if not (first := first or find_first_audio_file(path, ext=ext, ignore_errors=ignore_errors)):
        if not ignore_errors:
            raise FileNotFoundError(err)
        return None
    files = find_files_in_dir(path, resolve=True, only_file_exts=[ext] if ext else AUDIO_EXTS)
    try:
        next_file = next(iter(files[files.index(first) + 1 :]), None)
        if not next_file and not ignore_errors:
            raise FileNotFoundError(err)
        return next_file
    except IndexError:
        if not ignore_errors:
            raise FileNotFoundError(err)
        return None


def find_cover_art_file(path: Path) -> Path | None:
    supported_image_exts = [".jpg", ".jpeg", ".png"]
    all_images_in_dir = [f for f in path.rglob("*") if f.suffix in supported_image_exts]

    # if any of the images match *cover* or *folder*, return it
    img = next((i for i in all_images_in_dir if i.name.lower() in ["cover", "folder"]), None)

    # otherwise, find the biggest image
    if not img and all_images_in_dir:
        img = max(all_images_in_dir, key=lambda f: f.stat().st_size)

    # if img less than 7kb, return None
    if img and img.stat().st_size < 7168:
        return None

    return img


def filter_ignored(
    paths: list[Path | None] | Iterable[Path | None] | Generator[Path, Any, Any],
) -> list[Path]:
    from src.lib.config import cfg

    paths = [p for p in flatlist(paths) if p and isinstance(p, Path)]

    return [p for p in paths if not any(fnmatch.filter([str(p.name)], ignore) for ignore in cfg.IGNORE_FILES)]


def is_audio_file(file: str | Path) -> bool:
    from src.lib.formatters import ensure_dot

    return ensure_dot(Path(file).suffix.lower()) in AUDIO_EXTS


def is_audio_ext(ext: str) -> bool:
    from src.lib.formatters import ensure_dot

    return ensure_dot(ext.lower()) in AUDIO_EXTS


def only_audio_files(path_or_paths: Path | Iterable[Path] | Iterable[str]):
    # make iterable if not already
    paths = [path_or_paths] if isinstance(path_or_paths, (str, Path)) else path_or_paths
    return [p for p in map(Path, paths) if is_audio_file(p)]


def find_recently_modified_files_and_dirs(
    path: Path,
    within_seconds: float = 0,
    *,
    since: float = 0,
    only_file_exts: list[str] = [],
) -> list[tuple[Path, float, float]]:
    import threading

    from src.lib.config import cfg

    if within_seconds == 0:
        within_seconds = cfg.SLEEP_TIME
    current_time = time.time()
    recent_items: list[tuple[Path, float, float]] = []

    found_items = list(
        sorted(
            [(f, try_get_stat_mtime(f)) for f in filter_ignored(path.rglob("*"))],
            key=lambda x: -x[1],
        )
    )

    # Create a lock
    lock = threading.Lock()

    for path, last_modified in found_items:
        with lock:
            # check p against cfg.IGNORE_FILES - a list of glob patterns to ignore
            if path.is_file() and only_file_exts and not path.suffix in only_file_exts:
                continue
            age = (since or current_time) - last_modified
            if age < within_seconds or within_seconds == -1:
                recent_items.append((path, age, last_modified))

    return recent_items


def last_updated_at(path: Path, *, only_file_exts: list[str] = []) -> float:
    find_all_sorted_by_modified = find_recently_modified_files_and_dirs(
        path, -1, since=0, only_file_exts=only_file_exts
    )
    paths_m = [m for _1, _2, m in find_all_sorted_by_modified]
    return max(paths_m, default=try_get_stat_mtime(path))


def last_updated_audio_files_at(path: Path) -> float:
    return last_updated_at(path, only_file_exts=AUDIO_EXTS)


@overload
def inbox_last_updated_at(friendly: Literal[False] = False) -> float: ...


@overload
def inbox_last_updated_at(friendly: Literal[True]) -> str: ...


def inbox_last_updated_at(friendly: bool = False) -> float | str:
    from src.lib.config import cfg
    from src.lib.formatters import friendly_date

    last_update = last_updated_at(cfg.inbox_dir, only_file_exts=cfg.AUDIO_EXTS)
    return friendly_date(last_update) if friendly else last_update


def was_recently_modified(
    path: Path,
    within_seconds: float = 0,
    since: float = 0,
    *,
    only_file_exts: list[str] = [],
) -> bool:
    from src.lib.config import cfg

    if within_seconds <= 0:
        within_seconds = cfg.WAIT_TIME

    within_seconds = max(within_seconds, 0)

    mtime = time.time() - try_get_stat_mtime(path) < within_seconds

    if path.is_file():
        if only_file_exts and path.suffix not in only_file_exts:
            return False
        return mtime

    recents = find_recently_modified_files_and_dirs(path, within_seconds, since=since, only_file_exts=only_file_exts)
    return bool(mtime or recents)


def inbox_was_recently_modified(within_seconds: float = 0) -> bool:
    from src.lib.config import cfg

    return was_recently_modified(cfg.inbox_dir, within_seconds=within_seconds, only_file_exts=cfg.AUDIO_EXTS)


def hash_path(path: Path, *, only_file_exts: list[str] = [], debug: bool = False, n: int = 8) -> str:
    """Makes a has of the dir's contents of filenames and file sizes in an array, sorted by filename
    then hashes the array"""
    import hashlib

    def make_hashable(f: Path) -> str:
        if any(
            [
                not f.is_file(),
                f.name.startswith("."),
                only_file_exts and f.suffix not in only_file_exts,
            ]
        ):
            return ""
        return f"{f.relative_to(path)}|{f.stat().st_size}"

    def hash_raw(*raw: str) -> str:
        _s = raw[0] if len(raw) == 1 else ":".join(raw)
        return sh(hashlib.md5(_s.encode()).hexdigest(), n)

    if path.is_file():
        return hash_raw(make_hashable(path))

    files = isorted(list(filter(None, [make_hashable(f) for f in filter_ignored(path.rglob("*"))])))
    if debug:
        return files  # type: ignore
    return hash_raw(*files)


def hash_path_audio_files(path: Path, *, debug: bool = False) -> str:
    """Makes a hash of the path's audio files' filenames and file sizes in an array, sorted by filename
    then hashes the array"""
    return hash_path(path, only_file_exts=AUDIO_EXTS, debug=debug)


def hash_entire_inbox():
    from src.lib.config import cfg

    return hash_path_audio_files(cfg.inbox_dir)


def hash_inbox_books(dirs: list[Path]) -> BookHashesDict:
    return {p.name: hash_path_audio_files(p) for p in dirs if p.exists()}


FlatListOfFilesInDir = NamedTuple(
    "FlatListOfFilesInDir",
    [
        ("original_order", list[Path]),
        ("sorted_alphabetically", list[Path]),
        ("is_same_order", bool),
    ],
)


def get_flat_list_of_files_in_dir(path: Path, only_file_exts: list[str] = []) -> tuple[list[Path], list[Path], bool]:
    """Takes a path of all nested files and returns a flat list of all files relative to the path. E.g.,
    if the path contains:
    - /path/to/folder/file1
    - /path/to/folder/nested/file2
    - /path/to/folder/nested/file3
    - /path/to/folder/nested2/file4
    then the return value will be:
    - /path/to/folder/file1
    - /path/to/folder/file2
    - /path/to/folder/file3
    - /path/to/folder/file4

    Returns a tuple:
     - a list contains all file names in their original order according to the subdirectory structure
     - a list contains all file names sorted alphabetically (flat)
     - a bool indicating whether the flat list would be in the same order as the original list if the dir structure were flattened.
    """

    if not path.is_dir():
        raise NotADirectoryError(f"Error: {path} is not a directory")

    # if path is a dir, get all files in the dir and its subdirs
    files = [f for f in path.rglob("*") if f.is_file()]
    if only_file_exts:
        files = [f for f in files if f.suffix in only_file_exts]

    flat_files_list = [path / f.name for f in files]
    sorted_files_list = sorted(flat_files_list)
    do_lists_order_match = flat_files_list == sorted_files_list

    return FlatListOfFilesInDir(
        original_order=flat_files_list,
        sorted_alphabetically=sorted_files_list,
        is_same_order=do_lists_order_match,
    )


def compare_dirs_by_files(dir1: Path, dir2: Path) -> list[tuple[Path, int, Path, int]]:
    """Finds files from one dir in another, and includes the file sizes of each"""
    files1 = filter_ignored(dir1.glob("**/*"))
    files2 = filter_ignored(dir2.glob("**/*"))

    # make a list of files matched by name and size, e.g. [(left, left_size, right, right_size), ...]
    files1 = [(f, f.stat().st_size) for f in files1 if f.is_file()]
    files2 = [(f, f.stat().st_size) for f in files2 if f.is_file()]

    mapped_files = []
    for f1, s1 in files1:
        found_in_right = False
        for f2, s2 in files2:
            if f1.name == f2.name and s1 == s2:
                mapped_files.append((f1, s1, f2, s2))
                found_in_right = True
                break
        if not found_in_right:
            mapped_files.append((f1, s1, None, 0))

    return mapped_files


def find_root_from_path(path: Path):
    from src.lib.config import cfg

    # loop through cfg.all_roots and see if path is relative to any of them. If it is, return the root
    for root in cfg.all_roots:
        if try_relative_to(path, root):
            return root
    return None


def filter_depth(
    p: Path,
    root: Path,
    *,
    mindepth: int | None = None,
    maxdepth: int | None = None,
    offset: int = 0,
) -> bool:
    return (
        root
        and p
        and (mindepth is None or len(p.relative_to(root).parts) + offset >= mindepth)
        and (maxdepth is None or len(p.relative_to(root).parts) + offset <= maxdepth)
    )
