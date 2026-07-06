import json
import os
import re
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, cast, TypeVar

from src.lib.singleton import singleton
from src.lib.audiobook import Audiobook
from src.lib.books_tree import BooksTree
from src.lib.formatters import friendly_short_date
from src.lib.fs_utils import find_root_from_path, try_relative_to
from src.lib.hasher import Hasher
from src.lib.inbox_item import get_item, get_key, InboxItem, InboxItemStatus
from src.lib.misc import any_in
from src.lib.strings import en
from src.lib.term import print_debug, print_notice

SCAN_CALLS = 0


def filter_series_parents(d: dict[str, "InboxItem"]):
    return {k: v for k, v in d.items() if not v.is_series_parent}


def scanner(func: Callable[..., Any]):
    """A decorator that scans the path of a Hasher object after calling the decorated function."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        from src.lib.config import cfg

        hasher = cast(Hasher, args[0])
        result = func(*args, **kwargs)
        if hasher.hash_age > cfg.SLEEP_TIME:
            hasher.scan()
        return result

    return wrapper


R = TypeVar("R")


def requires_scan(func: Callable[..., R]):
    """A decorator that ensures the path of a Hasher object has been scanned before calling the decorated function."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        inbox = cast(InboxState, args[0])
        if not inbox._hashes or inbox._last_scan == 0:
            inbox.scan(skip_failed_sync=True)
        return cast(R, func(*args, **kwargs))

    return wrapper


class InboxStateError(Exception):
    pass


@singleton
class InboxState(Hasher):

    def __init__(self):
        from src.lib.config import cfg

        super().__init__(cfg.inbox_dir)
        self._items: dict[str, InboxItem] = {}
        self.ready = False
        self.loop_counter = 0
        self.banner_printed = False
        # Tracks the loop_counter value when the banner was last printed.
        # Used by print_banner to avoid reprinting the header in the same loop
        # or the immediately following loop of the same app() run. Reset to -1
        # when InboxState is created or force_inbox_hash_change signals a new
        # outer iteration so that the next loop prints a fresh header.
        self._last_banner_lc: int = -1
        self._last_scan = 0
        self.tree: BooksTree = None  # type: ignore
        self.scan(scan_id3=False)

    def set(
        self,
        key_path_or_book: str | Path | Audiobook | InboxItem,
        *,
        status: InboxItemStatus | None = None,
        last_updated: float | None = None,
    ):
        item = get_item(key_path_or_book)
        self._items[item.key] = item
        if last_updated:
            self._items[item.key]._last_updated = last_updated
        if status:
            self._items[item.key].status = status

    @requires_scan
    def get(self, key_path_or_book: str | Path | Audiobook | None) -> InboxItem | None:
        return self._get(key_path_or_book)

    @requires_scan
    def get_like(self, key_or_expr: str | Path | BooksTree | Audiobook):
        return [v for k, v in self._items.items() if re.search(str(key_or_expr), k, re.I)]

    @requires_scan
    def get_many(self, keys_paths_or_books: list[str | Path | Audiobook]):
        if not isinstance(keys_paths_or_books, list):
            raise ValueError("You must pass a list of keys to .get_many()")
        return [(k, self._get(k)) for k in keys_paths_or_books]

    def _get(self, key_path_hash_or_book: str | Path | BooksTree | Audiobook | None) -> InboxItem | None:
        if not key_path_hash_or_book:
            return None

        if not self._items:
            return None
        hsh = str(key_path_hash_or_book)
        path = (
            Path(key_path_hash_or_book)
            if isinstance(key_path_hash_or_book, (str, Path))
            else key_path_hash_or_book.path
        )
        root = find_root_from_path(path)
        rel_from_root = None if not root or not (rel := try_relative_to(path, root)) else rel
        key: Path = (rel_from_root.path if isinstance(rel_from_root, BooksTree) else rel_from_root) or path
        while len(key.parts) >= 1:
            simple = self._items.get(str(key), None)
            if simple:
                return simple
            key = key.parent
        return next(
            (item for item in self._items.values() if any_in([key, path, hsh], [item.key, item.hash, item.path])),
            None,
        )

    def rm(self, key_path_book_or_hash: str | Path | Audiobook):
        key = get_key(key_path_book_or_hash)
        if key or (item := self.get(str(key_path_book_or_hash))) and (key := item.key):
            return self._items.pop(key, None)

    def is_empty(self):
        return not bool(self._items)

    def scan(
        self,
        recheck_failed: bool = False,
        skip_failed_sync: bool = False,
        set_ready: bool = False,
        *,
        scan_id3: bool | None = None,
        force: bool = False,
        determine_structure: bool = True,
    ):
        from src.lib.config import cfg

        if self._last_scan > 0 and self.ready:
            if not force and time.time() - self._last_scan < cfg.WAIT_TIME:
                return

        if self.stale:
            recheck_failed = True

        global SCAN_CALLS
        SCAN_CALLS += 1

        super().scan()

        if not self.tree:
            # Create without auto-scan so the explicit scan() call below
            # controls whether ID3 tags are read (avoids a redundant full scan).
            self.tree = BooksTree(cfg.inbox_dir, scan=False)
        self.tree.scan(scan_id3=False if scan_id3 is False else True, determine_structure=determine_structure)
        # self._tree.scan()

        found_items = {str(t.key): InboxItem(t) for t in self.tree.books_and_series}

        gone_keys = set(self._items.keys()) - set(found_items.keys())
        for k, v in found_items.items():
            if k not in self._items:
                self._items[k] = v
            else:
                existing = self._items[k]
                # Always update the tree with the freshly scanned version so that
                # stub trees (created by _sync_failed_from_env without a scan) get
                # replaced with properly scanned nodes, preventing requires_scan errors.
                existing.tree = v.tree
                if existing.status == "processed":
                    # Item was processed but left on disk (e.g. ON_COMPLETE=test_do_nothing).
                    # Keep the "processed" status so it won't be re-converted.
                    pass
                elif existing.status == "gone":
                    # Item reappeared (e.g. renamed away then back) — treat as new.
                    existing.status = "new"
                elif recheck_failed and existing.status == "failed" and existing.did_change:
                    existing.set_needs_retry()

        # Remove items that are no longer in the inbox. An item may appear absent from
        # found_items simply because match_filter filtered it out during the tree scan
        # (BooksTree._scan applies match_filter when building _dirs/_files). Only mark
        # an item gone if its path is actually missing from disk; filtered-but-present
        # items remain in _items so they can be re-discovered when the filter changes.
        # They will be excluded from num_ok via ok_books (which checks is_filtered).
        for k in gone_keys:
            if (item := self._items.get(k)) and not item.path.exists():
                item.set_gone()

        if not skip_failed_sync and not self.failed_books and os.getenv("FAILED_BOOKS"):
            _sync_failed_from_env()

        if set_ready:
            self.ready = True

        self._last_scan = time.time()
        self.stale = False

    def flush(self):
        super().flush()
        self._items = {}

    def prune_gone(self, failed_ttl_days: float = 30):
        """Remove stale items from _items to release BooksTree and ID3 memory.

        Two cases are handled:

        Gone items — paths no longer exist and status is 'gone'. They serve no
        purpose; the next scan will re-add them as 'new' if they reappear.

        Stale failed items — status is 'failed' and the failure is older than
        ``failed_ttl_days`` (default 30). If the path is still on disk the item
        is reset to 'new' so it gets a fresh conversion attempt; if the path is
        gone the item is dropped entirely. Either way the FAILED_BOOKS env var
        is refreshed so the persisted state stays consistent.
        """
        gone = [k for k, v in self._items.items() if v.status == "gone"]
        for k in gone:
            del self._items[k]

        stale_threshold = time.time() - failed_ttl_days * 86400
        stale_failed = [
            k
            for k, v in self._items.items()
            if v.status == "failed" and v.failed_at is not None and v.failed_at < stale_threshold
        ]
        if stale_failed:
            for k in stale_failed:
                item = self._items[k]
                if item.path.exists():
                    # Still on disk — reset so it gets a fresh conversion attempt.
                    item.failed_at = None
                    item.failed_reason = ""
                    item.status = "new"
                else:
                    del self._items[k]
            _sync_failed_to_env()

    @property
    def match_filter(self):
        return self.tree.match_filter

    @property
    def unescaped_match_filter(self):
        unescaped = str(self.match_filter)
        while unescaped != (unescaped := re.sub(r"\\(.)", r"\1", unescaped)):
            ...
        return unescaped

    def set_match_filter(self, match_filter: str | None):
        from src.lib.config import cfg

        if match_filter is None:
            os.environ.pop("MATCH_FILTER", None)
            # update all items where filtered was set to ok
            # for item in [i for _, i in self.get_many(self.filtered_books.keys()) if i]:
            #     item.set_ok()
            cfg.MATCH_FILTER = ""
        else:
            os.environ["MATCH_FILTER"] = match_filter
            cfg.MATCH_FILTER = match_filter

        if self.tree is not None:
            self.tree._match_filter = match_filter
        # self.tree.scan()

    def reset_inbox(self, new_match_filter: str | None = None):

        self.set_match_filter(new_match_filter)
        self.flush()
        self.ready = False
        _sync_failed_from_env()
        self.reset_loop_counter()
        return self

    def clear_failed(self):
        for item in self.failed_books.values():
            item.set_ok()
        _sync_failed_to_env()

    def reset_loop_counter(self, start_at: int = 0):
        self.loop_counter = start_at
        self._last_banner_lc = -1
        # Reset any "processed" items back to "ok" so they can be re-converted
        # on the fresh loop.  "processed" is a within-session guard (prevents
        # double-conversion in the same run), not a permanent state.
        for item in self._items.values():
            if item.status == "processed":
                item.status = "ok"

    @requires_scan
    def did_fail(self, key_path_or_book: str | Path | Audiobook):
        if item := self.get(key_path_or_book):
            return item.status == "failed"
        return False

    @requires_scan
    def should_retry(self, key_path_or_book: str | Path | Audiobook):
        if item := self.get(key_path_or_book):
            return item.status == "needs_retry"
        return False

    @requires_scan
    def is_filtered(self, key_or_path: str | Path | Audiobook):
        if item := self.get(key_or_path):
            return item.is_filtered
        return False

    @requires_scan
    def is_ok(self, key_path_or_book: str | Path | Audiobook):
        if item := self.get(key_path_or_book):
            return item.status in ["ok", "new"]
        return False

    @property
    def items(self):
        return self._items

    @property
    def num_audio_files_deep(self):
        return len(self.tree.files_recursive)

    @property
    def standalone_files(self):
        return self.tree.standalone_files

    @property
    def standalone_books(self):
        return {
            k: v
            for k, v in self._items.items()
            if v.tree.has_structure("standalone_file") and v.status in ("ok", "new", "needs_retry")
        }

    @property
    def num_standalone_books(self):
        return len(self.standalone_books)

    @property
    def books_and_series(self):
        return self.tree.books_and_series

    @property
    def series_parents(self):
        return self.tree.series_parents

    def series_items_for_key(self, key: str):
        return [
            v
            for _k, v in self._items.items()
            if v.series_key == key or (v.key and Path(v.key).parts[0] == key and v.is_series_book)
        ]

    @property
    def num_books(self):
        return len(self.tree.books)

    @property
    def num_series(self):
        return len(self.series_parents)

    @property
    def ignored_books(self):
        return {k: v for k, v in self._items.items() if v.is_filtered}

    @property
    def num_ignored_books(self):
        return len(self.tree.books) - self.num_matched

    @property
    def matched_books(self):
        return {
            k: v
            for k, v in self._items.items()
            if v.tree.is_book_root and not v.is_filtered and v.status not in ["gone", "processed"]
        }

    @property
    def num_matched(self):
        return len(self.tree.books_f)

    @property
    def ok_books(self):
        return {
            k: v
            for k, v in self._items.items()
            if v.tree.is_book_root and v.status in ["ok", "new", "needs_retry"] and not v.is_filtered
        }

    @property
    def num_ok(self):
        return len(self.ok_books)

    @property
    def total_ok_books(self):
        """Unfiltered count of books with an ok status (ignores match_filter).
        Excludes "processed" books since they should not be re-converted."""
        return {
            k: v
            for k, v in self._items.items()
            if v.tree.is_book_root and v.status in ["ok", "new", "needs_retry"]
        }

    @property
    def num_total_ok(self):
        return len(self.total_ok_books)

    @property
    def matched_ok_books(self):
        return {k: v for k, v in self.matched_books.items() if v.status in ["ok", "new", "needs_retry"]}

    @property
    def num_matched_ok(self):
        return len(self.matched_ok_books)

    @property
    def has_failed_books(self):
        return any(v.status in ["failed", "needs_retry"] for v in self._items.values())

    @property
    def failed_books(self):
        return {k: v for k, v in self._items.items() if v.status == "failed"}

    @property
    def num_failed(self):
        return len(self.failed_books)

    @property
    def all_books_failed(self):
        haystack = self._items.values() if not self.match_filter else self.matched_books.values()
        return all(v.status == "failed" for v in haystack)

    @requires_scan
    def start(self):
        if len(self._hashes):
            self._last_run_start = self._hashes[0]

    @scanner
    def done(self):
        if len(self._hashes):
            self._last_run_end = self._hashes[0]
        self.banner_printed = False
        # print_debug("Set banner_printed to False")

    @property
    @scanner
    def changed_since_last_run_started(self):
        changed = self.next_hash != self.last_run_start_hash
        if changed:
            self.stale = True
        return changed

    @property
    @scanner
    def changed_since_last_run_ended(self):
        changed = self.next_hash != self.last_run_end_hash
        if changed:
            self.stale = True
        return changed

    def inbox_needs_processing(self, *, on_will_scan: Callable[[], None] | None = None):

        from src.lib.config import cfg
        from src.lib.run import print_banner

        self.changed_after_waiting = False
        waited_count = 0
        before_modified_hash = self.prev_hash if self.hash_age < cfg.SLEEP_TIME else self.curr_hash
        _banner_printed = False
        items_before_wait = set(self._items.keys())
        # rec_mod = self.dir_was_recently_modified
        while self.dir_was_recently_modified:
            print_debug(f"{en.DEBUG_WAITING_FOR_INBOX} {waited_count + 1} ({before_modified_hash} → {self.curr_hash})")
            self.scan()
            if not self.changed_after_waiting:
                self.changed_after_waiting = self.next_hash != before_modified_hash

            # Print banner whenever inbox changed while we waited (not just when new
            # items match the filter — the activity itself is worth notifying about).
            if self.changed_after_waiting and not _banner_printed:
                self.stale = True
                print_banner(after=lambda: print_notice(f"{en.INBOX_RECENTLY_MODIFIED}\n"))
                _banner_printed = True

            waited_count += 1
            time.sleep(min(0.5, cfg.WAIT_TIME / 2))

        needs_scan = self.changed_since_last_run_ended or self.changed_since_last_run_started
        hash_changed = False

        # print_debug(
        #     f"----------------------------\n"
        #     f"        Recently modified: {rec_mod}\n"
        #     f"        Last run hash: {self.last_run_hash}\n"
        #     f"        Prev hash: {self.previous_hash}\n"
        #     f"        Curr hash: {self.current_hash}\n"
        #     f"        Next hash: {self.next_hash}\n"
        #     f"        Changed after waiting: {changed_after_waiting}\n"
        #     f"        Changed since last run: {self.changed_since_last_run}\n"
        #     f"        Needs processing: {needs_processing}\n"
        #     f"        Waited count: {waited_count}\n"
        #     f"        Ready: {self.ready}\n"
        # )

        if needs_scan or waited_count > 0:

            msg = ""
            if waited_count:
                msg = f"Done waiting for inbox"

            # Fix standalone files
            if on_will_scan:
                on_will_scan()

            # When the hash actually changed (needs_scan), force the scan to
            # bypass the WAIT_TIME throttle — we know new files are present and
            # must populate _items regardless of how recently the last scan ran.
            self.scan(recheck_failed=True, set_ready=True, force=needs_scan)

            # Compute hash_changed AFTER the scan so we compare the freshly
            # computed curr_hash against the pre-scan snapshot.  Computing it
            # before the scan produces a false-negative when force_inbox_hash_change
            # inserts a fake hash that also matches _last_run_end — both sides would
            # be the fake value and hash_changed would always be False.
            hash_changed = self.curr_hash != before_modified_hash

            if hash_changed:
                h = f"({before_modified_hash} → {self.curr_hash})"
                msg = f"{msg} - hash changed {h}" if msg else f"Hash changed {h}"

            elif msg:
                msg = f"{msg}, no changes ({self.curr_hash})"

            if msg:
                print_debug(f"{msg}", only_once=True)

        if self.matched_ok_books or hash_changed or (waited_count > 0 and self.changed_after_waiting):
                # matched_ok_books: there are books ready to process.
                # hash_changed: the inbox actually changed while we waited.
                # waited_count > 0 and changed_after_waiting: we waited for the dir to
                #   settle and the hash actually changed during that wait (e.g. because a
                #   test injected a forced hash change via force_inbox_hash_change); run a
                #   full processing cycle so the footer/CATS always prints. We do NOT
                #   return True if we waited but the hash stayed the same — that would
                #   cause a spurious extra processing loop when the inbox was merely
                #   "recently modified" (e.g. fresh test fixture files) without any
                #   actual changes.
                return True

        print_debug(
            f"{en.DEBUG_INBOX_HASH_UNCHANGED} {friendly_short_date(self.last_hash_change)} ({self.curr_hash})",
            only_once=True,
        )

        return False

    def to_dict(self, refresh_hashes=False):
        return {path: item.to_dict(refresh_hashes) for path, item in self._items.items()}

    @property
    def fixed_books(self):
        return {k: v for k, v in self._items.items() if v.status == "needs_retry" and v.failed_reason}

    def set_failed(
        self,
        key_path_or_book: str | Path | Audiobook,
        reason: str,
        last_updated: float | None = None,
    ):
        if not self.get(key_path_or_book):
            self.set(key_path_or_book)

        if item := self.get(key_path_or_book):
            item.set_failed(reason)
            if last_updated is not None:
                item._last_updated = last_updated
            _sync_failed_to_env()
        else:
            print_debug(f"Item {key_path_or_book} not found in inbox")

    def set_needs_retry(self, key_path_or_book: str | Path | Audiobook):
        if not self.get(key_path_or_book):
            self.set(key_path_or_book)

        if item := self.get(key_path_or_book):
            item.set_needs_retry()
            _sync_failed_to_env()
        else:
            print_debug(f"Item {key_path_or_book} not found in inbox")

    def set_ok(self, key_path_or_book: str | Path | Audiobook):
        if not self.get(key_path_or_book):
            self.set(key_path_or_book)

        if item := self.get(key_path_or_book):
            item.set_ok()
            _sync_failed_to_env()
        else:
            print_debug(f"Item {key_path_or_book} not found in inbox")

    def set_gone(self, key_path_or_book: str | Path | Audiobook):
        if not self.get(key_path_or_book):
            self.set(key_path_or_book)

        if item := self.get(key_path_or_book):
            item.set_gone()
            _sync_failed_to_env()
        else:
            print_debug(f"Item {key_path_or_book} not found in inbox")

    def set_processed(self, key_path_or_book: str | Path | Audiobook):
        if not self.get(key_path_or_book):
            self.set(key_path_or_book)

        if item := self.get(key_path_or_book):
            item.set_processed()
        else:
            print_debug(f"Item {key_path_or_book} not found in inbox")

    def __iter__(self):
        return iter(self._items.values())

    def __len__(self):
        return len(self._items)

    def __contains__(self, path: Path):
        return path in self._items

    def __repr__(self):
        return f"Inbox state:\n{self.__str__()}"

    def __str__(self):
        return json.dumps(self.to_dict(), indent=4)


def _sync_failed_to_env():
    os.environ["FAILED_BOOKS"] = json.dumps({k: v.last_updated for k, v in InboxState().failed_books.items()})


def _sync_failed_from_env():
    failed_books = {k: float(v) for k, v in json.loads(os.getenv("FAILED_BOOKS", "{}")).items()}
    for k, lu in failed_books.items():
        InboxState().set_failed(k, "From ENV", lu)
