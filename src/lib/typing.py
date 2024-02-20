import functools
import inspect
from collections.abc import Callable
from typing import Any, cast, Literal, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

AudiobookFmt = Literal["m4b", "mp3", "m4a", "wma"]


# Source: https://stackoverflow.com/a/71968448/1214800
def copy_kwargs(func: Callable[P, R]) -> Callable[..., Callable[P, R]]:
    """Decorator does nothing but casts the original function to match the given function signature"""

    @functools.wraps(func, updated=())
    def _cast_func(_func: Callable[..., Any]) -> Callable[P, R]:
        return cast(Callable[P, R], _func)

    if inspect.isfunction(func):
        return _cast_func

    raise RuntimeError("You must pass a function to this decorator.")