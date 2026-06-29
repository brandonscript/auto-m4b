import functools
from typing import cast, TypeVar

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
            # Seal before calling super().__init__() so that any recursive
            # calls to the singleton constructor (e.g. from within __init__)
            # short-circuit instead of triggering a second initialization.
            self._sealed = True
            try:
                super(class_w, self).__init__(*args, **kwargs)
            except Exception:
                self._sealed = False
                raise

        @classmethod
        def destroy(cls):
            cls._instance = None

    return cast(type[C], class_w)
