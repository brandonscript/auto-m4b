import os
import re
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast, overload

from pydantic import BaseModel
from pytest import CaptureFixture
from tinta import Tinta

from src.lib.audiobook import Audiobook
from src.lib.config import cfg, OnComplete
from src.lib.formatters import human_elapsed_time, listify, pluralize_with_count
from src.lib.fs_utils import flatten_files_in_dir, inbox_last_updated_at
from src.lib.inbox_state import InboxState
from src.lib.misc import re_group
from src.lib.strings import en
from src.lib.term import CATS_ASCII_LINES, is_banner
from src.lib.typing import ENV_DIRS
from src.tests.conftest import TEST_DIRS

cfg.PID_FILE.unlink(missing_ok=True)


class testutils:

    @staticmethod
    def pring_out_lines(out_run: str):
        print(out_run.splitlines())

    class check_output(BaseModel):
        already_converted_eq: int | None = None
        already_converted_gt: int | None = None
        found_books_eq: int | None = None
        found_books_gt: int | None = None
        ignored_books_eq: int | None = None
        ignored_books_gt: int | None = None
        retried_books_eq: int | None = None
        retried_books_gt: int | None = None
        skipped_failed_eq: int | None = None
        skipped_failed_gt: int | None = None
        converted_eq: int | None = None
        converted_gt: int | None = None

        empty: bool = False

        def already_converted_result(self):
            return ", ".join(
                [
                    f"to have moved{self.get_comparator(k)} {v} m4b(s)"
                    for k, v in self.model_dump().items()
                    if k.startswith("already_converted") and v is not None
                ]
            )

        def found_books_result(self):
            return ", ".join(
                [
                    f"to have found{self.get_comparator(k)} {v} book(s)"
                    for k, v in self.model_dump().items()
                    if k.startswith("found") and v is not None
                ]
            )

        def failed_books_result(self):
            return ", ".join(
                [
                    f"to have skipped{self.get_comparator(k)} {v} failed book(s)"
                    for k, v in self.model_dump().items()
                    if k.startswith("skipped") and v is not None
                ]
            )

        def ignored_books_result(self):
            return ", ".join(
                [
                    f"to have ignored{self.get_comparator(k)} {v} book(s)"
                    for k, v in self.model_dump().items()
                    if k.startswith("ignored") and v is not None
                ]
            )

        def retried_books_result(self):
            return ", ".join(
                [
                    f"to have retried{self.get_comparator(k)} {v} failed book(s)"
                    for k, v in self.model_dump().items()
                    if k.startswith("retried") and v is not None
                ]
            )

        def converted_books_result(self):
            return ", ".join(
                [
                    f"to have converted{self.get_comparator(k)} {v} book(s)"
                    for k, v in self.model_dump().items()
                    if k.startswith("converted") and v is not None
                ]
            )

        def get_comparator(self, k: str):
            return k.split("_")[-1].replace("eq", "").replace("gt", " >")

    @classmethod
    def print(cls, *s: Any):
        Tinta().tint(213, *["[PYTEST]", *s]).print()

    @classmethod
    def purge_all(cls):
        for folder in ENV_DIRS:
            if folder := os.getenv(folder):
                shutil.rmtree(folder, ignore_errors=True)

    @classmethod
    def flatten_book(cls, book: Audiobook, delay: int = 0):
        time.sleep(delay)
        cls.print(f"About to flatten book {book}")
        cls.print(f"Inbox last updated at {inbox_last_updated_at()}")
        flatten_files_in_dir(book.inbox_dir)
        cls.print(f"Fixed '{book}'")
        cls.print(f"Inbox last updated at {inbox_last_updated_at()}")

    @classmethod
    def fail_book(cls, book: Audiobook | str, delay: int = 0, *, from_now: float = 0):
        time.sleep(delay)
        last_updated_at = time.time() + from_now
        rel_time = human_elapsed_time(-from_now)
        cls.print(
            f"Adding '{book}' to failed list, setting last modified to {rel_time}"
        )
        InboxState().set_failed(book, "Test", last_updated_at)

    @classmethod
    def unfail_book(cls, book: Audiobook | str, delay: int = 0):
        time.sleep(delay)
        cls.print(f"Removing '{book}' from failed list (if present)")
        InboxState().set_ok(book)

    @classmethod
    def set_match_filter(cls, match_filter: str | None, delay: int = 0):
        time.sleep(delay)
        cls.print(f"Setting MATCH_FILTER to {match_filter}")
        InboxState().set_match_filter(match_filter)

    @classmethod
    @contextmanager
    def set_sleep_time(cls, sleep_time: int | float, delay: int = 0):
        time.sleep(delay)
        orig_sleep_time = cfg.SLEEP_TIME
        cls.print(f"Setting SLEEP_TIME to {sleep_time}")
        # os.environ["SLEEP_TIME"] = str(sleep_time)
        cfg.SLEEP_TIME = float(sleep_time)
        yield
        cfg.SLEEP_TIME = orig_sleep_time
        # os.environ["SLEEP_TIME"] = str(orig_sleep_time)

    @classmethod
    @contextmanager
    def set_wait_time(cls, wait_time: int | float, delay: float = 0):
        time.sleep(delay)
        orig_wait_time = cfg.WAIT_TIME
        cls.print(f"Setting WAIT_TIME to {wait_time}")
        # os.environ["WAIT_TIME"] = str(wait_time)
        cfg.WAIT_TIME = float(wait_time)
        yield
        cfg.WAIT_TIME = orig_wait_time
        # os.environ["WAIT_TIME"] = str(orig_wait_time)

    @classmethod
    @contextmanager
    def set_on_complete(cls, on_complete: OnComplete, delay: float = 0):
        time.sleep(delay)
        orig_on_complete = cfg.ON_COMPLETE
        cls.print(f"Setting ON_COMPLETE to '{on_complete}'")
        # os.environ["ON_COMPLETE"] = on_complete
        cfg.ON_COMPLETE = on_complete
        yield
        cfg.ON_COMPLETE = orig_on_complete
        # os.environ["ON_COMPLETE"] = orig_on_complete

    @classmethod
    @contextmanager
    def set_backups(cls, enabled: bool, delay: int = 0):
        time.sleep(delay)
        orig_backups = cfg.BACKUP
        cls.print(f"Setting BACKUP to {enabled}")
        os.environ["BACKUP"] = "Y" if enabled else "N"
        cfg.BACKUP = enabled
        yield
        cfg.BACKUP = orig_backups
        os.environ["BACKUP"] = "Y" if orig_backups else "N"

    @classmethod
    def force_inbox_hash_change(cls, *, delay: int = 0, age: float = 0.5):
        time.sleep(delay)
        cls.print(f"Forcing hash change for inbox")
        str_age = f"-{age}s" if age > 0 else f"+{abs(age)}s"

        new_hash = (
            f"forcing-change {str_age}",
            time.time() - age,
        )
        inbox = InboxState()
        inbox._hashes.insert(0, new_hash)
        inbox._last_run_end = new_hash
        inbox.stale = True
        inbox.banner_printed = False

    @classmethod
    def force_inbox_up_to_date(cls, *, delay: int = 0):
        time.sleep(delay)
        cls.print(f"Forcing inbox to be up to date")
        inbox = InboxState()
        inbox.scan()
        inbox.ready = True
        inbox._last_run_start = inbox._hashes[0]
        inbox._last_run_end = inbox._hashes[0]

    @classmethod
    def rename_files(
        cls,
        book: Audiobook,
        *,
        prepend: str = "",
        append: str = "",
        lstrip: str = "",
        rstrip: str = "",
        delay: float = 0,
        wait_time: float = 0,
    ):
        time.sleep(delay)
        # if prepend:
        #     msg += f", prepending '{prepend}'"
        # if append:
        #     msg += f", appending '{append}'"
        # if lstrip:
        #     msg += f", left stripping '{lstrip}'"
        # if rstrip:
        #     msg += f", right stripping '{rstrip}'"
        cls.print(f"Renaming files for {book}")
        for f in book.inbox_dir.glob("*"):
            if not f.suffix in cfg.AUDIO_EXTS:
                continue
            stripped = re.sub(rf"^{lstrip}|{rstrip}$", "", f.stem)
            new_name = f"{prepend}{stripped}{append}{f.suffix}"
            cls.print(f"Renaming '{f.name}' to '{new_name}'")
            f.rename(f.with_name(new_name))
            time.sleep(wait_time)

    @classmethod
    def enable_multidisc(cls, delay: int = 0):

        time.sleep(delay)
        cls.print("Enabling multidisc")
        cfg.FLATTEN_MULTI_DISC_BOOKS = True

    @classmethod
    def disable_multidisc(cls, delay: int = 0):

        time.sleep(delay)
        cls.print("Disabling multidisc")
        cfg.FLATTEN_MULTI_DISC_BOOKS = False

    @classmethod
    def enable_convert_series(cls, delay: int = 0):

        time.sleep(delay)
        cls.print("Enabling convert series")
        cfg.CONVERT_SERIES = True

    @classmethod
    def disable_convert_series(cls, delay: int = 0):
        time.sleep(delay)
        cls.print("Disabling convert series")
        cfg.CONVERT_SERIES = False

    @classmethod
    def enable_backups(cls, delay: int = 0):

        time.sleep(delay)
        cls.print("Enabling backups")
        cfg.BACKUP = True

    @classmethod
    def disable_backups(cls, delay: int = 0):

        time.sleep(delay)
        cls.print("Disabling backups")
        cfg.BACKUP = False

    @classmethod
    def enable_debug(cls, delay: int = 0):

        time.sleep(delay)
        cls.print("Enabling debug")
        cfg.DEBUG = True

    @classmethod
    def disable_debug(cls, delay: int = 0):

        time.sleep(delay)
        cls.print("Disabling debug")
        cfg.DEBUG = False

    @classmethod
    def enable_archiving(cls, delay: int = 0):

        time.sleep(delay)
        cls.print("Setting ON_COMPLETE to 'archive'")
        cfg.ON_COMPLETE = "archive"

    @classmethod
    def disable_archiving(cls, delay: int = 0):
        time.sleep(delay)
        cls.print("Setting ON_COMPLETE to 'test_do_nothing'")
        cfg.ON_COMPLETE = "test_do_nothing"

    @classmethod
    def make_mock_file(cls, path: Path, size: int = 1024 * 5):
        if not path.is_absolute():
            path = TEST_DIRS.inbox / path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write("a" * size)

    @classmethod
    def rm(cls, p: Path):
        (
            shutil.rmtree(p, ignore_errors=True)
            if p.is_dir()
            else p.unlink(missing_ok=True)
        )

    @classmethod
    def strip_ansi_codes(cls, s: str) -> str:
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", s)

    @classmethod
    def get_stdout(cls, capfd: CaptureFixture[str]) -> str:
        return cls.strip_ansi_codes(capfd.readouterr().out)

    @classmethod
    def is_divider(cls, line: str | None) -> bool:
        return bool(line and line.startswith("-" * 10) and not cls.is_banner(line))

    @classmethod
    def is_empty(cls, line: str | None) -> bool:
        return not line or not line.strip()

    @classmethod
    def is_banner(cls, *lines: str) -> bool:
        return False if not lines else is_banner(*lines)

    @classmethod
    def is_startup(cls, *lines: str | None) -> bool:
        return any(
            bool(line and line.startswith("Starting auto-m4b...")) for line in lines
        )

    @classmethod
    def is_footer(cls, *lines: str | None) -> bool:
        from src.lib.term import CATS_ASCII

        return any((line in CATS_ASCII.splitlines() for line in lines))

    @classmethod
    def strip_test_debug_lines(cls, *lines: str) -> tuple[str, ...]:
        return tuple(
            (
                line
                for line in lines
                if not line.startswith("[DEBUG") and not line.startswith("[PYTEST")
            )
        )

    @classmethod
    def strip_startup_lines(cls, *lines: str):
        startup_idx = next(
            (i for i, line in enumerate(lines) if cls.is_startup(line)), -1
        )
        if startup_idx == -1:
            return lines

        keep = list(lines)
        rm_count = 0
        for i, line in enumerate(list(lines).copy()):
            if i >= startup_idx:
                if cls.is_empty(line) or line.startswith("-" * 3):
                    break
                if any(
                    (
                        *(
                            t in line
                            for t in ["/", "[Beta]", "TEST", "DEBUG", "Loading"]
                        ),
                        cls.is_startup(line),
                        re.match(r"- \w+", line),
                    ),
                ):
                    keep.pop(i - rm_count)
                    rm_count += 1

        return tuple(cls.strip_leading_empty_lines(*keep))

    @overload
    @classmethod
    def strip_cats_ascii(cls, *s: str) -> tuple[str]: ...

    @overload
    @classmethod
    def strip_cats_ascii(cls, *s: list[str]) -> list[str]: ...

    @classmethod
    def strip_cats_ascii(cls, *s: str | tuple[str] | list[str]):
        if s and isinstance(s[0], list):
            return cls.strip_cats_ascii(*s[0])

        r = [l for l in cast(list[str], s[:]) if not l in CATS_ASCII_LINES]
        return cls.strip_outside_empty_lines(*r)

    @classmethod
    def strip_banner_extras(cls, *lines: str) -> tuple[str, ...]:

        first_book_idx = next(
            (i for i, line in enumerate(lines) if line.startswith("╭╌╌╌╌╌╌╌")),
            len(lines),
        )
        _lines = lines[:first_book_idx]

        return cls.strip_outside_empty_lines(
            *(
                l
                for l in cls.strip_startup_lines(*cls.strip_test_debug_lines(*_lines))
                if not any(
                    (
                        l.startswith("Found "),
                        l.startswith(" *** New activity"),
                    )
                )
            )
        )

    @classmethod
    def strip_leading_empty_lines(cls, *lines: str) -> tuple[str, ...]:
        while lines and cls.is_empty(lines[0]):
            lines = lines[1:]
        return tuple(lines)

    @classmethod
    def strip_trailing_empty_lines(cls, *lines: str) -> tuple[str, ...]:
        while lines and cls.is_empty(lines[-1]):
            lines = lines[:-1]
        return tuple(lines)

    @classmethod
    def strip_outside_empty_lines(cls, *lines: str) -> tuple[str, ...]:
        return cls.strip_leading_empty_lines(*cls.strip_trailing_empty_lines(*lines))

    @classmethod
    def get_last_cats_line_idx(cls, *lines: str) -> int:
        return (
            len(lines)
            - next((i for i, line in enumerate(lines[::-1]) if "CATS" in line), 0)
            - 1
        )

    @classmethod
    def get_first_cats_line_idx(cls, *lines: str) -> int:
        return next((i for i, line in enumerate(lines) if "CATS" in line), 0)

    @classmethod
    def get_all_cats_line_idxes(cls, *lines: str) -> list[int]:
        return [i for i, line in enumerate(lines) if "CATS" in line]

    @classmethod
    def get_loops_from_out_lines(cls, *out_lines: str, strip_cats: bool = True):
        cats_idxes = cls.get_all_cats_line_idxes(*out_lines)
        sp = cats_idxes + [len(out_lines)]
        loops = [out_lines[i1:i2] for i1, i2 in zip([0] + sp[:-1], sp)]
        f = cls.strip_cats_ascii if strip_cats else cls.strip_outside_empty_lines
        return [l for l in [f(*l) for l in loops] if l]

    @classmethod
    def make_tmp_files(cls, tmp_path: Path, file_rel_paths: list[str]):
        """Creates a tmp list of files from a tmp_path, and returns the parent directory of the files"""
        d = (tmp_path / file_rel_paths[0]).parent
        d.mkdir(parents=True, exist_ok=True)
        for file in file_rel_paths:
            (tmp_path / file).touch()

        return d

    @classmethod
    def get_all_processed_books(
        cls, s: str, *, root_dir: Path = TEST_DIRS.inbox
    ) -> list[str]:
        lines = s.splitlines()
        books = []
        for i, line in enumerate(lines):
            if line.startswith("- Source: "):
                src = re_group(
                    re.search(rf"- Source: {root_dir}/(?P<book_key>.*$)", line),
                    "book_key",
                )
                if not lines[i + 1].startswith("- Output: "):
                    src = f"{src}{lines[i + 1].strip()}"
                books.append(src)
        return books

    @classmethod
    def assert_header_count(
        cls,
        out: str | CaptureFixture[str],
        *,
        expected_eq: int = -1,
        expected_gte: int = -1,
        expected_lte: int = -1,
    ):
        if isinstance(out, CaptureFixture):
            out = cls.get_stdout(out)

        actual = out.count("auto-m4b •")
        if expected_eq != -1:
            assert (
                actual == expected_eq
            ), f"Expected header to print {expected_eq} time(s), got {actual}"
        if expected_gte != -1:
            assert (
                actual >= expected_gte
            ), f"Expected header to print at least {expected_gte} time(s), got {actual}"
        if expected_lte != -1:
            assert (
                actual <= expected_lte
            ), f"Expected header to print at most {expected_lte} time(s), got {actual}"

        return True

    @classmethod
    def assert_no_double_dividers(cls, out_lines: list[str]):
        _out_lines = cls.strip_test_debug_lines(*out_lines)
        for i, line in enumerate(_out_lines):
            j, next_non_empty_line = next(
                enumerate((l for l in _out_lines[i + 1 :] if not cls.is_empty(l))),
                (0, None),
            )
            if cls.is_divider(line) and cls.is_divider(next_non_empty_line):
                raise AssertionError(
                    f"Found double dividers at lines {i} and {i + 2 + j}"
                )
        return True

    @classmethod
    def assert_banner_starts_each_loop(cls, out_lines: list[str]):
        _out_lines = cls.strip_startup_lines(*cls.strip_test_debug_lines(*out_lines))
        all_runs = cls.get_loops_from_out_lines(*_out_lines)
        for i, run in enumerate(all_runs):
            if run:
                assert cls.is_banner(
                    *run[:4]
                ), f"Expected a banner to print at the start of run {i + 1}"
        return True

    @classmethod
    def assert_no_duplicate_banners(cls, out_lines: list[str]):
        _out_lines = cls.strip_startup_lines(*cls.strip_test_debug_lines(*out_lines))
        all_runs = [
            cls.strip_banner_extras(*run)
            for run in cls.get_loops_from_out_lines(*_out_lines)
        ]
        banners = [[b for b in r if cls.is_banner(b) and b[0] == "-"] for r in all_runs]
        for i, run in enumerate(banners):
            if len(run) > 1:
                raise AssertionError(
                    f"Expected only one banner to print per loop, but got {len(run)} in run {i + 1}"
                )
        return True

    @classmethod
    def assert_not_ends_with_banner(cls, out_lines: list[str]):
        _out_lines = cls.strip_test_debug_lines(*out_lines)
        lines_to_check = cls.strip_cats_ascii(
            *_out_lines[cls.get_last_cats_line_idx(*_out_lines) :]
        )

        assert not cls.is_banner(
            *lines_to_check
        ), "Output should never end with a banner"
        return True

    @classmethod
    def assert_count_inbox_hash_changed(cls, out_lines: list[str], eq: int):
        assert (
            len(list(set([l for l in out_lines if en.DEBUG_INBOX_HASH_UNCHANGED in l])))
            == eq
        )
        return True

    @classmethod
    def assert_count_no_audio_files_found(cls, out_lines: list[str], eq: int):
        assert (
            len(list(set([l for l in out_lines if "No audio files found" in l]))) == eq
        )
        return True

    @classmethod
    def assert_processed_output(
        cls,
        out: str | CaptureFixture[str],
        *exp_books: str | Path | Audiobook,
        loops: list[check_output] | None = None,
    ) -> bool:

        if isinstance(out, CaptureFixture):
            out = cls.get_stdout(out)

        books = [
            Audiobook(Path(b)) if not isinstance(b, Audiobook) else b for b in exp_books
        ]

        processed = cls.get_all_processed_books(out)
        did_process_all = all([book.key in processed for book in books])
        ok = did_process_all and len(processed) == len(books)
        books_list = f"\n{listify([book.key for book in books])}" if books else ""
        processed_list = f"\n{listify(processed)}" if processed else ""
        outs = out.split("CATS")[:-1] if "CATS" in out else [out]
        out_lines = out.splitlines()
        assert (
            ok
        ), f"Expected {len(books)} to be converted: {books_list}\n\nGot {len(processed)}: {processed_list}"

        expect_num_loops = len(loops) if loops else None
        if expect_num_loops is not None:
            assert (
                len(outs) == expect_num_loops
            ), f"Expected {pluralize_with_count(expect_num_loops, 'loop')}, got {len(outs)}"

        def assert_already_converted(
            i: int, ch: testutils.check_output, out_run: str = out
        ):
            if all(
                f is None for f in [ch.already_converted_eq, ch.already_converted_gt]
            ):
                return
            all_already_converted = len(re.findall(r"has already been converted", out))
            this_already_converted = len(
                re.findall(r"has already been converted", out_run)
            )
            try:
                if ch.already_converted_eq is not None:
                    assert this_already_converted == ch.already_converted_eq
                else:
                    if ch.already_converted_gt is not None:
                        assert this_already_converted > ch.already_converted_gt
            except AssertionError:
                expected = ch.already_converted_result()
                raise AssertionError(
                    f"Run {i + 1} - expected {expected} to be already converted, got {this_already_converted} (total already converted: {all_already_converted})"
                )

        def assert_found(i: int, ch: testutils.check_output, out_run: str = out):
            if all(f is None for f in [ch.found_books_eq, ch.found_books_gt]):
                return
            all_founds = re.findall(r"(Found \d+.*? books?.*?)(?=\n)", out)
            all_found_counts = [
                int(
                    re_group(
                        re.search(r"Found (\d+) books?(?!.+but none\b)", x),
                        1,
                        default=0,
                    )
                )
                for x in all_founds
            ]
            this_found = all_found_counts[i] if all_found_counts else 0
            expected = ch.found_books_result()

            if ch.found_books_eq == 0:
                assert (
                    this_found == 0
                ), f"Expected no books to be found, got {this_found}"
            elif this_found == 0:
                assert this_found > 0, f"Expected {expected}, but found none"
            else:
                try:
                    if ch.found_books_eq is not None:
                        assert this_found == ch.found_books_eq
                    else:
                        if ch.found_books_gt is not None:
                            assert this_found > ch.found_books_gt
                except AssertionError:
                    raise AssertionError(f"Expected {expected}, got {this_found}")
            if any((ch.found_books_eq is not None, ch.found_books_gt)):
                err = f"Expected {len(outs)} 'found books' prints in output, got {len(all_founds)}"
                assert len(outs) == len(all_founds), err

        def assert_failed(i: int, ch: testutils.check_output, out_run: str = out):
            if all(c is None for c in [ch.skipped_failed_eq, ch.skipped_failed_gt]):
                return

            all_failed = len(re.findall(r"(\d+) that previously failed", out))
            this_failed = int(
                re_group(
                    re.search(r"(\d+) that previously failed", out_run), 1, default=0
                )
            )
            try:
                if ch.skipped_failed_eq is not None:
                    assert this_failed == ch.skipped_failed_eq
                else:
                    if ch.skipped_failed_gt is not None:
                        assert this_failed > ch.skipped_failed_gt
            except AssertionError:
                expected = ch.failed_books_result()
                raise AssertionError(
                    f"Run {i + 1} - expected {expected}, got {this_failed} (total failed: {all_failed})"
                )

        def assert_ignored(i: int, ch: testutils.check_output, out_run: str = out):
            if all(c is None for c in [ch.ignored_books_eq, ch.ignored_books_gt]):
                return

            all_ignored = len(re.findall(r"ignoring (\d+)", out))
            this_ignored = int(
                re_group(re.search(r"ignoring (\d+)", out_run), 1, default=0)
            )
            try:
                if ch.ignored_books_eq is not None:
                    assert this_ignored == ch.ignored_books_eq
                else:
                    if ch.ignored_books_gt is not None:
                        assert this_ignored > ch.ignored_books_gt
            except AssertionError:
                expected = ch.ignored_books_result()
                raise AssertionError(
                    f"Run {i + 1} - expected {expected} to be ignored, got {this_ignored} (total ignored: {all_ignored})"
                )

        def assert_retried(
            i: int, t: int, ch: testutils.check_output, out_run: str = out
        ):
            if all(c is None for c in [ch.retried_books_eq, ch.retried_books_gt]):
                return

            all_retried = len(re.findall(r"trying again", out))
            this_retried = len(re.findall(r"trying again", out_run))
            try:
                if ch.retried_books_eq is not None:
                    assert this_retried == ch.retried_books_eq
                else:
                    if ch.retried_books_gt is not None:
                        assert this_retried > ch.retried_books_gt
            except AssertionError:
                expected = ch.retried_books_result()
                raise AssertionError(
                    f"Run {i + 1} of {t} - expected {expected} to retry, got {this_retried} (total retried: {all_retried})"
                )

        def assert_converted(
            i: int, t: int, ch: testutils.check_output, loop: str = out
        ):
            if all(c is None for c in [ch.converted_eq, ch.converted_gt]):
                return

            all_converted = len(re.findall(r"Converted .* 🐾✨🥞", out))
            this_converted = len(re.findall(r"Converted .* 🐾✨🥞", loop))
            try:
                if ch.converted_eq is not None:
                    assert this_converted == ch.converted_eq
                else:
                    if ch.converted_gt is not None:
                        assert this_converted > ch.converted_gt
            except AssertionError:
                expected = ch.converted_books_result()
                raise AssertionError(
                    f"Run {i + 1} of {t} - expected {expected} to be converted, got {this_converted} (total converted: {all_converted})"
                )

            loop_lines = loop.splitlines()
            # assert that each converted line is followed by an empty line and a divider
            for i, line in enumerate(loop_lines):
                if "Converted" in line:
                    info = line.split(" 🐾✨🥞")[0]
                    assert cls.is_empty(loop_lines[i + 1]) and cls.is_divider(
                        loop_lines[i + 2]
                    ), f"Expected '{info}' to be followed by an empty line and a divider, got:\n\n {loop.split('\n')[i + 1:i + 3]}"

        if loops is not None:
            for i, (ch, o) in enumerate(zip(loops, outs)):
                if ch.empty:
                    continue
                assert_already_converted(i, ch, o)
                assert_found(i, ch, o)
                assert_failed(i, ch, o)
                assert_ignored(i, ch, o)
                assert_retried(i, len(outs), ch, o)
                assert_converted(i, len(outs), ch, o)

        cls.assert_no_double_dividers(out_lines)
        cls.assert_banner_starts_each_loop(out_lines)
        cls.assert_no_duplicate_banners(out_lines)
        cls.assert_not_ends_with_banner(out_lines)

        return ok

    @classmethod
    def assert_converted_book_and_collateral_exist(cls, book: Audiobook, quality: str):
        assert book.converted_dir.exists()
        m4b = book.converted_dir / f"{book.path.name}.m4b"
        assert m4b.exists()
        assert m4b.stat().st_size > 0
        log = book.converted_dir / f"auto-m4b.{book.path.name}.log"
        assert not log.exists()
        # assert log.stat().st_size > 0
        desc = book.converted_dir / f"{book.path.name} [{quality}].txt"
        assert desc.exists()
        assert desc.stat().st_size > 0
        return True

    blank_audiobook_data = b'ID3\x03\x00\x00\x00\x00\x00mTXXX\x00\x00\x00 \x00\x00\x00Encoded by\x00LAME in FL Studio 20TXXX\x00\x00\x00\x1b\x00\x00\x00BPM (beats per minute)\x00120TYER\x00\x00\x00\x05\x00\x00\x002018\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Xing\x00\x00\x00\x0f\x00\x00\x06J\x00\x0b1V\x00\x03\x05\x07\t\n\x0c\x0e\x10\x12\x13\x16\x18\x1a\x1b\x1d\x1f!#$\'),.1369;=@CEGJMORTWY\\^`cegjlnqsuxz}\x7f\x81\x85\x89\x8c\x8f\x91\x94\x97\x9a\x9d\xa0\xa4\xa7\xaa\xad\xb0\xb3\xb6\xb9\xbb\xbf\xc3\xc5\xc8\xcb\xce\xd0\xd3\xd5\xd8\xdc\xdf\xe2\xe5\xe7\xea\xed\xef\xf2\xf5\xf9\xfc\xfe\x00\x00\x00PLAME3.100\x04\xb9\x00\x00\x00\x00\x00\x00\x00\x005 $\x06(M\x00\x01\xe0\x00\x0b1V\xa5v\x7fh\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xfb\xa0D\x00\x030\x00\x00\x7f\x80\x00\x00\x08\x00\x00\x0f\xf0\x00\x00\x01\x01\x18\x03\x11\x14\x10\x00(#\x00b"\x82\x00\x05DH\x00\x0e\x0f~\x07\xe0!\x11 \x008=\xf8\x1f\x80\x85\x00\x00\x00#\x948b\x85H\xd7\xd8\x1b\x05\x02@\x00\x02\x15f\x1b rc\xce\xfb&\xf6b\xd2`\x86i\xe6\x1dB\xbca\x04\x0b\xc9\x14`\n\x1b\xe6\x02\xa0``\x12\x04\xbb0 \x02`0\x1a\x11\x04\x99\x81p+\xbd\x10X\x88#IcNb%\xe2<:\x02\x00\x10j,`"[\xa6oC\x8f\x04\x84BAe\x15\xe1\x88\x99n\x98\x98 ]\xe3\x87\x0b\xb8[E\xe8\x8a\x89\x10\x8fM,\x10\x1b\x02|w\xcf\xfe\xc0\x8b\xb1\x96H\x19c\xb8\xa01(%\x86\xd6\x8e\xff\xff\xff\xe1\x18\xb1\xc9e\x8e;9L\xc6{3\x19\xff\xff\xff\xfc9\xf8s\xf0\xff\xfa\xb4\xbfV\xcf\xd5\xc7\xcaN"\xe2\xae\r.w\xff\xe8\xb5\x1e\x01\x80\x1aaj\x00\xa0\x0e\x03`\x00\x00\x00\x00\x00\x0e,\x0f p\x02 \t\x06`j\x0f\x8d\xcd\xe1\xf1\xbauK\x86\xb57\x96C\xfc\xeb\x11H\x00\x0b\xf4\x9f\x7f\xac\x00\x000Y\x181\x06\xd9\x87\x90t\x1c2\x10)\x80\xa0\x03\x18"\x03\x19\x81\xd0\x07\x97D.\x01HB`\x02\x00\x00\x90\x00\x1e\x00o\xe7\xeb{k\xb0\xad+6/E:\x8fZ\xc9\x12\x0c\x89G)\x0c\xbcZ\xc7\x07\x96\xf4s`\x03\xe8\x00\x01\xff\x00\x00,\xc0NXL\xd9\xd3Z\xec3<\xdf\xff\x8f4r"`\xa2G\x1f\x14\x10\x83\x04\x95\x00\x05\xbd\xb3_\xf0\x00\x00`\x8cs\x0ea\x02\x0b\x87&$.a\xde\x01A\xc0\xc2D\x02\xca\xd0\x8el\xac\x80\x00\x99\x8c\xd7;N\xef]\t\xda\xbcM\xc2:\x07\xc6j\xf0\x9c}\xdf\x80\x04C\x80\x00\x00\x01\xc0\x00\x00\x85-\t\xd0N\xd4\xa2\x08M\xd6A\xff\xffJ_*\x00\x04\xed\x08\xa8\xfb\xfa\x0c\n\x804\xc0\\\n\x0c\x19\x04$\xde\x01Q\x0e\xf9\x04\xc8\xc2\x0cX\x14\xbaCE#\xa0\x05\xfdX\xcc\xb6\xe7\xd3\xb6\xbc\xb6\x0e\xd5\x19\x90\xd6K\x19\xef69\xd5\xf5\xff\xfb\x80d\xea\x00\x05\xab:\xcc~{$\x80+@\xe9\xff\xcc\x80\x12\t8])\xbd\xe1\x00 \x83\x82\xa57\xb2\x00\x04\x82o\xc0\x03\xc0\x19\xc1\xd8\x12SD>.\x00\x03D\x87\x85{\xf8\x00\x00\x00\x00,`\x10\t\xe6\x07#4h\xf2\xfdg\xcfA\x8c*`Q\x15\x05\x88\x80/\xc5jsZt\xb2\xec\x0fOa\xe9eF\xe4M\'\xcda\x81h\xc5\x87\xe5\xf9\x87\xb1T\xe8\xa6\x06\xd8\xc5`\x00\xe0\xa8\xf3pR\xc4\x92\xb2\x83\xf6Fo<\xfcW\x90\x08\x11\xaaffb\x02\xa0 R\r\x80\xaa\x0e\xcb\x01\x03!\n\x15LF\xd24\xff1\xd8V\x94\xd0\xe4N\xb2_k\xc0Q,\xab\xa5\x08y\xaa\x89\xa9\x91\x18\x1eb\xe2\x8d`\xbf%\xde\x90\x17\x8d\x10Q\xa1\x9b\xb5\xd67,\xaa}E\xde!$#\xd1\xc0@\xee*C\xddl\x9a\x8e\x807\xd5I\xca\x8e\'\x01\x97m\xa3(8\xf3\x16 \xae\x1e\xaa6\x9fhl>\x99\x8d\x1e7\x1b\xce\xa1F\xb2\x1aI\x93\x88\xf3\xd8\xe2\x95Q"Q~\x82\xa7\xc1\xec\xf1\xcb\x85Aq!\xc1\x1d\xe9\\\xea\t\xca\x08\x83\xdfo\xb7\xc5I\xa1\xc0\x84\xe3\xdd"<2\xba\xd9h\x11\x19\xa2t\x06\x06z\x85_V\xf4\xdd\xb3\x07]\x0b$=\xb7K\x01\xc480bP\xa1\x93<u\xc2J\x0c$\xb2M\xeb`Z\xff\xfbPD\xf2\x83\x11\x8c\x10J\xfb\tc\x081\xa1\xe9_c\t\'\x05h?+\xcc1\xea\xa8\xc8\x08\xe5}\x87\xa5\x15\x9fDY\x10\xa1\x97\x86L\x12D\x98\x04(\xb0$\xa0\xec\x91\x00\xa6D\xa1+\x12\xdc\x86\x1c\xef\xad\x1a \x00\x00\x1e\x16\xe6\x15\x80m`&\x11\x98\x19\x96\x99\xa8\xe8\x8e\xb2\xbc\x93\x00\x00\x01q\x07\x08\n\x98\n\xde\xb2\xda@\x0b\x03!\x0b\x07\x81\xacELAME3.100UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUULAME3.100UUUUUUUUUUUUUUUUUUUUUU\xff\xfbPD\xe8\x031]\x0eK{\x0f1\xaa/"\t_a\xecCD\xe89+\xcc=eh\x96\x87%\xf9\x84\xa1\x8dUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU\xff\xfbPd\xea\x031-\x0fG#Xx8\x1e\xa1\xb8\xd4d#c\x04(7"\x8c1&\xa8v\x06\xa3\x91\x97\x8c\x9cUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU\xff\xfb\x10D\xfe\x030\xa6\x07F#\x0f@\x98\x16\xe0\xf8xb\x0c\x01\x01x\r\r\x0c0@ &\x01"\x94\xc4\x80\x06UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU\xff\xfb\x10d\xdd\x8f\xf0\x00\x00\x7f\x80\x00\x00\x08\x00\x00\x0f\xf0\x00\x00\x01\x00\x00\x01\xa4\x00\x00\x00 \x00\x004\x80\x00\x00\x04UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU'
