import time
from functools import cached_property
from pathlib import Path
from typing import cast, Literal

from cachetools.func import ttl_cache

from src.lib.audiobook import Audiobook
from src.lib.books_tree import BooksTree
from src.lib.formatters import human_elapsed_time, human_size
from src.lib.fs_utils import (
    get_audio_size,
    hash_path_audio_files,
    last_updated_audio_files_at,
    name_matches,
)
from src.lib.typing import DirName

InboxItemStatus = Literal["new", "ok", "needs_retry", "failed", "gone"]


def get_key(path_or_book: "str | Path | BooksTree | Audiobook | InboxItem") -> str:
    if isinstance(path_or_book, BooksTree):
        return path_or_book.key or ""
    if isinstance(path_or_book, str):
        return path_or_book
    if isinstance(path_or_book, Path):
        return path_or_book.name
    return path_or_book.key


def get_books_tree(
    key_path_or_book: "str | Path | BooksTree | Audiobook | InboxItem",
) -> BooksTree:
    from src.lib.config import cfg

    instancetype = type(key_path_or_book).__name__

    match instancetype:
        case "BooksTree":
            return cast(BooksTree, key_path_or_book)
        case "Audiobook":
            return cast(Audiobook, key_path_or_book).tree
        case "str":
            str_path = cast(str, key_path_or_book)
            path = Path(str_path)
            if not path.is_absolute():
                path = cfg.inbox_dir / str_path
            return BooksTree(path)
        case "Path":
            return BooksTree(cast(Path, key_path_or_book))
        case "InboxItem":
            return cast(InboxItem, key_path_or_book).tree
        case _:
            raise ValueError(f"Invalid type: {instancetype}")


def get_item(key_path_or_book: "str | Path | Audiobook | InboxItem") -> "InboxItem":
    from src.lib.config import cfg

    if isinstance(key_path_or_book, str):
        return InboxItem(cfg.inbox_dir / key_path_or_book)
    if isinstance(key_path_or_book, Path):
        return InboxItem(key_path_or_book)
    if isinstance(key_path_or_book, Audiobook):
        return InboxItem(key_path_or_book)
    return key_path_or_book


class InboxItem:

    def __init__(self, book: str | Path | BooksTree | Audiobook):
        self.tree = get_books_tree(book)

        self.is_dir = self.tree.path.is_dir()
        self.is_file = self.tree.path.is_file()

        self._prev_hash = None
        self._last_updated: float | None = None
        self._curr_hash = hash_path_audio_files(self.tree.path)
        self._hash_changed: float = time.time()
        self.key = str(self.tree.key)
        self.size = get_audio_size(self.tree.path) if self.tree.path.exists() else 0
        self.status: InboxItemStatus = "new"
        self.failed_reason: str = ""

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        since = human_elapsed_time(time.time() - self.last_updated)
        status = f"filtered ({self.status})" if self.is_filtered else self.status
        return f"{status} -- ({human_size(self.size)}) -- {self.key} -- {since} -- {self.hash}"

    def __eq__(self, other):
        if not isinstance(other, InboxItem):
            return False
        return self.key == other.key

    def __hash__(self):
        return self.key.__hash__()

    def reload(self):
        self = InboxItem(self.path)

    @cached_property
    def path(self) -> Path:
        from src.lib.config import cfg

        return cfg.inbox_dir / self.key

    @cached_property
    def basename(self):
        return self.path.name

    @property
    def hash(self):
        if self.is_gone:
            self._hash_changed = time.time()
            return ""
        new_hash = hash_path_audio_files(self.path)
        if new_hash != self._curr_hash:
            self._prev_hash = self._curr_hash
            self._curr_hash = new_hash
            self._hash_changed = time.time()
        return self._curr_hash

    @property
    def prev_hash(self):
        return self._prev_hash

    @property
    def last_updated(self):
        if self._last_updated is not None:
            return self._last_updated
        return last_updated_audio_files_at(self.path)

    @property
    def hash_changed(self):
        if not self._hash_changed:
            self.hash
        return self._hash_changed

    @property
    def hash_age(self):
        return time.time() - self.hash_changed

    def _set(
        self,
        status: InboxItemStatus,
        reason: str | None = None,
        last_updated: float | None = None,
    ):
        if self.is_gone:
            return
        self.status = status
        if reason:
            self.failed_reason = reason
        if last_updated:
            self._last_updated = last_updated
        self.hash

    def set_failed(self, reason: str, last_updated: float | None = None):
        from src.lib.inbox_state import _sync_failed_to_env

        self._set("failed", reason, last_updated)
        _sync_failed_to_env()

    def set_needs_retry(self):
        from src.lib.inbox_state import _sync_failed_to_env

        self._set("needs_retry")
        _sync_failed_to_env()

    def set_ok(self):
        self._set("ok")

    def set_gone(self):
        self._set("gone")

    @property
    def is_gone(self):
        if self.path.exists():
            return False
        self.status = "gone"
        return True

    @property
    def is_filtered(self):
        from src.lib.config import cfg

        return not name_matches(self.path.relative_to(cfg.inbox_dir), cfg.MATCH_FILTER)

    @property
    def is_maybe_series_book(self):
        return self.tree.has_structure("series_book")
        # return len(Path(self.key).parts) > 1

    @cached_property
    def is_maybe_series_parent(self):
        return self.tree.has_structure("series_parent")
        # return any(
        #     [
        #         is_maybe_multiple_books_or_series(d.name)
        #         for d in find_base_dirs_with_audio_files(self.path, ignore_errors=True)
        #     ]
        # )

    @cached_property
    def is_first_book_in_series(self):
        return (
            self.is_maybe_series_book
            and (parent := self.series_parent)
            and (series_books := parent.series_books)
            and series_books[0] == self
        )

    @cached_property
    def is_last_book_in_series(self):
        return (
            self.is_maybe_series_book
            and (parent := self.series_parent)
            and (series_books := parent.series_books)
            and series_books[-1] == self
        )

    @cached_property
    def series_parent(self):
        from src.lib.inbox_state import InboxState

        inbox = InboxState()
        if not self.is_maybe_series_book:
            return None
        return inbox.get(self.series_key)

    @property
    def series_books(self) -> list["InboxItem"]:
        from src.lib.inbox_state import InboxState

        inbox = InboxState()
        if not self.is_maybe_series_parent:
            return []

        return inbox.series_items_for_key(self.key)

    @cached_property
    def series_key(self):
        from src.lib.config import cfg

        return str(self.path.relative_to(cfg.inbox_dir).parent) if self.is_maybe_series_book else None

    @cached_property
    def series_basename(self):
        from src.lib.config import cfg

        d = self.path.relative_to(cfg.inbox_dir)
        return str(d.parent) if len(d.parts) > 1 and d.parts[-1] == self.basename else str(d)

    @property
    @ttl_cache(maxsize=6, ttl=10)
    def num_books_in_series(self):
        if not self.is_maybe_series_parent:
            return -1
        return len(self.series_books)

    @property
    def did_change(self) -> bool:
        return True if self.is_gone else hash_path_audio_files(self.path) != self._curr_hash

    @property
    def type(self) -> Literal["dir", "file", "gone"]:
        return "dir" if self.path.is_dir() else "file" if self.path.is_file() else "gone"

    def to_dict(self, refresh_hash=False):
        h = self.hash if (refresh_hash or not self._curr_hash) else self._curr_hash
        status = "gone" if self.is_gone else self.status
        if self.is_filtered:
            status = f"filtered ({status})"
        return {
            "key": self.key,
            "hash": h,
            "prev_hash": self.prev_hash,
            "path": str(self.path),
            "size": self.size,
            "last_updated": self.last_updated,
            "hash_age": self.hash_age,
            "status": status,
            "failed_reason": self.failed_reason,
        }

    def to_audiobook(self, active_dir: DirName = "inbox") -> Audiobook:
        book = Audiobook(self.path)
        book._active_dir = active_dir
        return book
