import asyncio
import functools
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Generator, Iterable, Sequence
from pathlib import Path, PosixPath
from typing import Any, cast, Generic, overload, TypeVar

from dotenv import dotenv_values

from src.lib.typing import DirName, ENV_DIRS


def is_gt_100mb(size: int) -> bool:
    if "pytest" in sys.modules:
        return size > 100 * 1024
    return size > 100 * 1024 * 1024


def is_gt_75mb(size: int) -> bool:
    if "pytest" in sys.modules:
        return size > 75 * 1024
    return size > 75 * 1024 * 1024


def is_gt_50mb(size: int) -> bool:
    if "pytest" in sys.modules:
        return size > 50 * 1024
    return size > 50 * 1024 * 1024


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


def flatlist(*args: L | Sequence[L] | Sequence[Sequence[L]]) -> Sequence[L]:  # type: ignore
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
            item = cast(Sequence[L | Sequence[L]], item)
            if is_sequence(item):
                flat_list.extend(_flatten(item))  # Recursively flatten
            elif is_generator(item):
                flat_list.extend(_flatten(list(item)))
            elif isinstance(arg, map):
                return list(cast(Sequence[L], item))
            else:
                flat_list.append(item)
        return flat_list

    if len(args) == 1:
        arg = args[0]
        # Always flatten the argument if it's iterable, even if it's a single one
        if is_sequence(arg):
            return _flatten(cast(Sequence[L | Sequence[L]], arg))
        elif is_generator(arg):
            arg = list(cast(Generator[L | Sequence[L], None, None], arg))
            if not arg:
                return []
            return _flatten(cast(Sequence[L | Sequence[L]], arg))
        elif isinstance(arg, map):
            return list(cast(Sequence[L], arg))
        else:
            return [cast(L, arg)]
    else:
        # Flatten all arguments into a single list
        return _flatten(cast(Sequence[L | Sequence[L]], args))


def isorted(
    *iterable: S | Iterable[S] | Generator[S, None, None],
    reverse: bool = False,
) -> list[S]:

    if not iterable:
        return []

    return cast(list[S], list(sorted(flatlist(*iterable), key=lambda x: str(x).lower(), reverse=reverse)))  # type: ignore


def any_in(l1: Iterable[T], l2: Iterable[T]) -> bool:
    """Returns True if any item in l1 is in l2 or vice versa.

    Examples:
    any_in([1, 2, 3], [3, 4, 5]) -> True, because 3 is in both lists.
    any_in([1, 2, 3], [4, 5, 6]) -> False, because no items are in both lists.
    """
    if not l1:
        return False
    if any(i in l1 for i in l2):
        return True
    return any(j in l2 for j in l1)


def any_matching(l1: Iterable[T], l2: Iterable[T], *, case_insensitive=False) -> bool:
    """Returns True if any item in l1 matches (case-insensitive) a part of an item in l2.

    Examples:
    any_matching(["a", "b", "c"], ["A", "D", "E"]) -> True, because "a" is in both lists.
    any_matching(["a", "b", "c"], ["d", "e", "f"]) -> False, because no items are in both lists.
    any_matching(["apples_bananas", "cherries_oranges"], ["apples"]) -> True, because "apples" is in both lists.
    """
    if not l1:
        return False

    l1_zip = lambda: zip([str(i).lower() for i in l1] if case_insensitive else [str(i) for i in l1], l1)
    l2_zip = lambda: zip([str(i).lower() for i in l2] if case_insensitive else [str(i) for i in l2], l2)

    if any_in(l1, l2):
        return True

    if any((any((str_i in str_j, str_j in str_i, i == j)) for (str_i, i) in l2_zip() for (str_j, j) in l1_zip())):
        return True
    return any((any((str_i in str_j, str_j in str_i, i == j)) for (str_i, i) in l1_zip() for (str_j, j) in l2_zip()))


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


def ffprobe_paths():
    paths_to_add = ["/opt/homebrew/bin", "/usr/local/bin/"]
    for path in paths_to_add:
        if Path(path) not in sys.path and Path(path).exists():
            sys.path.append(path)

    return os.pathsep.join(paths_to_add)


def fix_ffprobe(counter: int = 0):

    def check_ffprobe():
        import ffmpeg
        from ffmpeg import Error, probe  # type: ignore

        assert ffmpeg.probe  # type: ignore
        assert Error
        assert probe
        subprocess.check_output(["which", "ffprobe"]).decode().strip()
        assert (
            subprocess.run(
                "ffprobe -version",
                capture_output=True,
                shell=True,
                env={
                    "PATH": ffprobe_paths(),
                },
            ).returncode
            == 0
        )

    # Get the path to the .venv
    src_root = Path(__file__).parent.parent.parent
    venv_path = src_root / ".venv"
    binary = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = venv_path / f"lib/{binary}/site-packages"
    bin_root = venv_path / "bin" / binary
    if not site_packages.exists():
        raise RuntimeError(f"auto_m4b's site_packages not found at '{site_packages}', cannot fix ffprobe")

    fix_cmd = f"{bin_root} -m pip uninstall ffmpeg-python python-ffmpeg -y && {bin_root} -m pip install ffmpeg-python --target {site_packages} --force-reinstall --upgrade"

    try:
        check_ffprobe()
    except Exception as _e:
        # if counter == 0:
        #     print_warning("ffmpeg's ffprobe is not installed or not working — attempting to fix...\n")

        # Look for ffprobe in PATH and known locations
        known_locations = ["/opt/homebrew/bin", "/usr/local/bin"]
        for location in known_locations:
            if Path(location).exists():
                os.environ["PATH"] = f"{location}:{os.environ['PATH']}"

        ffprobe_path = subprocess.check_output(["which", "ffprobe"]).decode().strip()
        if ffprobe_path and not (d := os.path.dirname(ffprobe_path)) in os.environ["PATH"]:
            os.environ["PATH"] = f"{d}:{os.environ['PATH']}"

        code = subprocess.run(
            fix_cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        if code == 0:
            return
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


def clamp[T: (
    float,
    int,
), Min: (float, int), Max: (float, int)](value: T, min_value: Min, max_value: Max) -> T | Min | Max:
    """Clamps a value between a minimum and maximum value.

    Args:
        value: The value to clamp
        min_value: The minimum allowed value
        max_value: The maximum allowed value

    Returns:
        The clamped value, of the same type as the input value
    """
    return cast(T, max(min_value, min(value, max_value)))


T_co = TypeVar("T_co", covariant=True)


def cached_property_max_age(ttl: int = 300):
    def decorator(func: Callable[..., T_co]):
        return cast(T_co, _cached_property_max_age(func, ttl))

    return decorator


class _cached_property_max_age(property, Generic[T_co]):
    def __init__(self, func: Callable[..., T_co], ttl: int = 300):
        self.ttl = ttl
        self.cache: dict[Any, T_co] = {}
        self.time_cache: dict[Any, float] = {}
        super().__init__(func)

    def __get__(self, instance: Any, owner: Any) -> T_co:
        if instance is None:
            return cast(T_co, self)
        now = time.time()
        if instance not in self.cache or (now - self.time_cache.get(instance, 0)) > self.ttl:
            if not self.fget:
                raise ValueError(
                    "func is not set for cached_property_max_age, did you use @cached_property_max_age(...)?"
                )
            self.cache[instance] = self.fget(instance)
            self.time_cache[instance] = now
        return self.cache[instance]
