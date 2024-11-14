import asyncio
import functools
import os
import re
import subprocess
from collections.abc import Generator, Iterable, Sequence
from pathlib import Path, PosixPath
from typing import Any, cast, overload, TypeVar

from dotenv import dotenv_values

from src.lib.typing import DirName, ENV_DIRS


def get_git_root():
    return Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).strip().decode("utf-8"))


T = TypeVar("T", bound=str | Path)
S = TypeVar("S")


def rm_audio_ext(path: T) -> T:
    # Removes audio file extensions from a string or Path

    if isinstance(path, str):
        return cast(
            T,
            path.replace(".mp3", "").replace(".m4a", "").replace(".m4b", "").replace(".wma", ""),
        )
    else:
        return cast(T, Path(path).with_suffix(""))


def rm_ext(path: str | Path) -> str:
    return Path(path).stem


def get_ext(path: str) -> str:
    return Path(path).suffix


def escape_special_chars(string: str) -> str:
    return re.sub(r"[\[\]\(\)*?|&]", r"\\\g<0>", string)


def get_numbers_in_string(s: str) -> str:
    """Returns a only the numbers found in a string, in order they are found."""
    return "".join(re.findall(r"\d", s))


def get_numbers_contiguous(s: str) -> list[tuple[int, int]]:
    """Returns a list of tuples of contiguous numbers found in a string and their positions, e.g.
    get_numbers_contiguous("123abc456") -> [(123, 0), (456, 6)]
    """
    return [(int(m.group()), m.start()) for m in re.finditer(r"\d+", s)]


def to_bool(v: Any) -> bool:
    """Converts a truthy or falsy value to a boolean. "", None, False, "false", "f",
    "no", "n" (case insensitive) are considered falsy values. All others are considered
    truthy."""
    return v not in [None, False, ""] or str(v).lower() not in ["false", "f", "no", "n"]


def percent_truthy_in_list(l: list[bool], precision: int = 2) -> float:
    """Returns the percentage of truthy values in a list of booleans, or truthy values if the list
    contains non-boolean values. "", None, False, "false", "f", "no", "n" (case insensitive) are
    considered falsy values. All others are considered truthy. Rounds % to precision."""

    if not l:
        return 0.0

    total = len(l)
    truthy = sum([to_bool(v) for v in l])
    return round((truthy / total) * 100, precision)


L = TypeVar(
    "L",
)


@overload
def flatlist(arg: list[L] | list[L | list[L]]) -> list[L]: ...


@overload
def flatlist(arg: Sequence[L] | Sequence[Sequence[L]]) -> Sequence[L]: ...


@overload
def flatlist(*args: L | Sequence[L] | Sequence[Sequence[L]]) -> Sequence[L]: ...


def flatlist(*args: L | Sequence[L] | Sequence[Sequence[L]]) -> Sequence[L]:
    """
    Ensures that any number of arguments are a flat iterable of the same type.

    If a single argument is passed and it's a sequence, it will be flattened.
    If multiple arguments are passed, they are returned as a flat list.
    If a single argument is passed and it's not a sequence, it's returned as a list.
    """

    if not args:
        return []

    def is_sequence(a: Any) -> bool:
        return isinstance(a, Sequence) and not isinstance(a, (str, bytes))

    def is_generator(a: Any) -> bool:
        return isinstance(a, Generator)

    def _flatten(arg: Sequence[L | Sequence[L]]) -> Sequence[L]:
        """Flatten an iterable of nested iterables into a single list."""
        flat_list = []
        for item in arg:
            if is_sequence(item):
                flat_list.extend(_flatten(item))  # Recursively flatten
            elif is_generator(item):
                flat_list.extend(_flatten(list(item)))
            elif isinstance(arg, map):
                return list(item)
            else:
                flat_list.append(item)
        return flat_list

    if len(args) == 1:
        arg = args[0]
        # Always flatten the argument if it's iterable, even if it's a single one
        if is_sequence(arg):
            return _flatten(arg)
        elif is_generator(arg):
            return _flatten(list(arg))
        elif isinstance(arg, map):
            return list(arg)
        else:
            return [arg]
    else:
        # Flatten all arguments into a single list
        return _flatten(args)


def isorted(
    *iterable: S | Iterable[S] | Generator[S, None, None],
    reverse: bool = False,
) -> list[S]:

    if not iterable:
        return []

    return cast(list[S], list(sorted(flatlist(*iterable), key=lambda x: str(x).lower(), reverse=reverse)))


def any_in(l1: Iterable[T], l2: Iterable[T]) -> bool:
    """Returns True if any item in l1 is in l2.

    Examples:
    any_in([1, 2, 3], [3, 4, 5]) -> True, because 3 is in both lists.
    any_in([1, 2, 3], [4, 5, 6]) -> False, because no items are in both lists.
    """
    if not l1:
        return False
    return any([i in l2 for i in l1])


def any_matching(l1: Iterable[T], l2: Iterable[T], *, case_insensitive=False) -> bool:
    """Returns True if any item in l1 matches (case-insensitive) any item in l2.

    Examples:
    any_matching(["a", "b", "c"], ["A", "D", "E"]) -> True, because "a" is in both lists.
    any_matching(["a", "b", "c"], ["d", "e", "f"]) -> False, because no items are in both lists.
    any_matching(["apples_bananas", "cherries_oranges"], ["apples"]) -> True, because "apples" is in both lists.
    """
    if not l1:
        return False

    if case_insensitive:
        # if not all elements are strings, can't use case-insensitive comparison
        if not all([isinstance(i, str) for i in l1 + l2]):
            raise ValueError("Can't use case-insensitive comparison on non-string elements.")
        l1 = [i.lower() for i in l1]  # type: ignore
        l2 = [i.lower() for i in l2]  # type: ignore

    return any([i in j for i in l2 for j in l1])


def all_in(l1: Iterable[T], l2: Iterable[T]) -> bool:
    if not l1:
        return False
    return all([i in l2 for i in l1])


def all_in_both(l1: Iterable[T], l2: Iterable[T]) -> bool:
    return all_in(l1, l2) and all_in(l2, l1)


G = TypeVar("G")


def re_group(
    match: re.Match[str] | None,
    group: int | str = 0,
    *,
    default: G = "",
) -> G:
    # returns the first match of pattern in string or default if no match
    found = match.group(group) if match else None
    return cast(G, found) if found is not None else default


def compare_trim(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def try_get_stat_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def is_boolish(v: Any) -> bool:
    return str(v).lower() in ["true", "false", "y", "n", "yes", "no"]


def parse_bool(v: Any) -> bool:
    """Parses a string value to a boolean value."""
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "t", "y", "yes")


def is_floatish(v: Any) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False
    except TypeError:
        return False


def parse_float(v: Any) -> float:
    return float(v) if is_floatish(v) else v


def is_intish(v: Any) -> bool:
    try:
        int(v)
        return True
    except ValueError:
        return False
    except TypeError:
        return False


def parse_int(v: Any) -> int:
    return int(v) if is_intish(v) else v


def is_noneish(v: Any) -> bool:
    return v is None or str(v).lower() in ("none", "null", "nil", "n/a")


def parse_none(v: Any) -> None:
    return None if is_noneish(v) else v


def is_maybe_path(v: Any) -> bool:
    checks = [type(v) in [Path, PosixPath], re.match(r"^\.{0,2}/", str(v))]
    return any(checks)


def pathify(k: str, v: Any) -> Path | None:
    # from src.lib.config import WORKING_DIRS

    if not k.endswith("_FOLDER") or not is_maybe_path(v):
        return None
    p = Path(str(v)).expanduser()
    if not p.is_absolute():
        p = get_git_root() / p
    os.environ[k] = str(p)
    # if p.exists() and k in WORKING_DIRS and clean_working_dirs:
    #     shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def set_typed_env_var(
    k: str,
    v: Any,
    dict_to_update: dict[str, Any] | None = None,
):

    if not dict_to_update:
        dict_to_update = {}

    if not v:
        os.environ.pop(k, None)
        dict_to_update[k] = None
    if is_boolish(v):
        os.environ[k] = "Y" if parse_bool(v) else "N"
        dict_to_update[k] = parse_bool(v)
    elif is_maybe_path(v) and (p := pathify(k, v)):
        os.environ[k] = str(v)
        dict_to_update[k] = p
    else:
        os.environ[k] = str(v)
        dict_to_update[k] = os.environ[k]

    return dict_to_update


def load_env(env_file: str | Path, clean_working_dirs: bool = False) -> dict[str, Any | None]:

    env_file = Path(env_file)
    env_vars: dict[str, Any] = {}
    for k, v in dotenv_values(env_file).items():
        set_typed_env_var(k, v, env_vars)

    return env_vars


def dockerize_volume(
    path: str | Path,
    rel_to: Path | None = None,
) -> Path:
    """Takes the incoming path and replaces root_dir in path with /mnt if cfg.use_docker is True"""
    from src.lib.config import cfg

    if not rel_to:
        rel_to = cfg.working_dir

    if cfg.USE_DOCKER:
        return Path("/mnt") / Path(path).relative_to(rel_to)
    else:
        return Path(path)


def sanitize(v):
    if isinstance(v, (int, float, bool, str, type(None))):
        return v
    elif isinstance(v, Iterable):
        return [sanitize(_v) for _v in v]
    elif isinstance(v, dict):
        return {k: sanitize(_v) for k, _v in v.items()}
    return str(v)


def to_json(obj: dict[str, Any]) -> str:
    """Converts an object to a JSON string."""
    import json

    return json.dumps({k: sanitize(v) for k, v in obj.items()}, indent=4, sort_keys=True)


def sh(s: str, n: int = 8) -> str:
    return s[-n:]


def get_dir_name_from_path(p: Path) -> DirName | None:

    def get_env(k: str) -> str:
        return os.getenv(k, "")

    known_dirs = zip(map(Path, map(get_env, ENV_DIRS)), ENV_DIRS)
    for k, d in known_dirs:
        if k in p.parents:
            return cast(DirName, d.lower().replace("_folder", ""))


def get_or_create_event_loop():
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError as e:
        if str(e).startswith("There is no current event loop in thread"):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        else:
            raise e
    return loop


C = TypeVar("C")


def singleton(class_: type[C]) -> type[C]:
    class class_w(class_):
        _instance = None

        @functools.wraps(class_.__new__)
        def __new__(cls, *args, **kwargs):
            if class_w._instance is None:
                class_w._instance = super(class_w, cls).__new__(cls, *args, **kwargs)
                class_w._instance._sealed = False
                name = f"{class_.__name__}[singleton]"
                class_w.__name__ = name
                class_w._instance.__name__ = name
                qualname = f"{class_.__qualname__}[singleton]"
                class_w.__qualname__ = qualname
                class_w._instance.__qualname__ = qualname
            return class_w._instance

        @functools.wraps(class_.__init__)
        def __init__(self, *args, **kwargs):
            if self._sealed:
                return
            super(class_w, self).__init__(*args, **kwargs)
            self._sealed = True

        @classmethod
        def destroy(cls):
            cls._instance = None

    return cast(type[C], class_w)


def fix_ffprobe(counter: int = 0):
    from src.lib.term import print_warning

    fix_cmd = "pip uninstall ffmpeg-python python-ffmpeg -y && pip install ffmpeg-python"

    try:
        from ffmpeg import Error, probe

        assert Error
        assert probe

        if counter > 0:
            exit(0)
    except Exception as e:
        if counter == 0:
            print_warning("ffmpeg's ffprobe is not installed or not working. Attempting to fix...\n")

        os.system(fix_cmd)
        if counter < 3:
            counter += 1
            fix_ffprobe(counter)
        else:
            raise ImportError(f"ffmpeg's ffprobe is not installed, please fix it manually:\n\n $ {fix_cmd}\n\n")


def increment(s: str) -> str:
    """if a string ends with a number, increment it and return the new string"""
    if not s:
        return s
    m = re.search(r"\d+$", s)
    if m:
        return s[: m.start()] + str(int(m.group()) + 1)
    return s
