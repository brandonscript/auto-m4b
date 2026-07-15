import re
import shutil
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from tinta import Tinta

from src.lib.audiobook import Audiobook
from src.lib.config import AUDIO_EXTS, cfg
from src.lib.formatters import (
    friendly_date,
    human_elapsed_time,
    pluralize,
    pluralize_with_count,
    truncate_middle,
)
from src.lib.converter import convert_book_native
from src.lib.id3_utils import verify_and_update_id3_tags
from src.lib.inbox_state import InboxItem, InboxState
from src.lib.logger import log_global_results

from src.lib.parsers import (
    roman_numerals_affect_file_order,
)
from src.lib.strings import en
from src.lib.term import (
    AMBER_COLOR,
    box,
    CATS_ASCII,
    divider,
    found_banner_in_print_log,
    linebreak_path,
    nl,
    print_dark_grey,
    print_debug,
    print_error,
    print_grey,
    print_list_item,
    print_mint,
    print_notice,
    print_orange,
    smart_print,
    tint_light_grey,
    tint_path,
    tint_warning,
    tinted_file,
    tinted_m4b,
    trim_print_log,
    wrap_brackets,
)

# glasses 1: ⌐◒-◒
# glasses 2: ᒡ◯ᴖ◯ᒢ


def move_standalone_into_dir(book: Audiobook, item: InboxItem):

    from src.lib.formatters import ensure_dot
    from src.lib.fs_utils import find_adjacent_files_with_same_basename, mv_file_into_dir

    if not book.tree.has_any_structure("single", "standalone_file") or not book.tree.is_file():
        return book, item

    ext = ensure_dot(book.orig_file_type)

    folder_name = item.path.stem
    smart_print(f"\nMoving single/standalone {ext} into its own folder → ./{folder_name}/")
    new_folder = item.path.parent / folder_name
    new_folder.mkdir(exist_ok=True)
    mv_file_into_dir(item.path, new_folder, overwrite_mode="overwrite-silent")

    # move any other files with the same basename to the new folder
    for f in find_adjacent_files_with_same_basename(item.path):
        mv_file_into_dir(f, new_folder)

    # update item
    item.update_path(new_folder)
    # Build a fresh tree scoped to the new folder rather than going through
    # InboxState().get(), which can return the parent series item when the
    # newly created folder isn't yet registered under its own key.
    from src.lib.books_tree import BooksTree

    new_book = Audiobook(BooksTree(new_folder))
    return new_book, item


def process_already_m4b(book: Audiobook, item: InboxItem):

    from src.lib.formatters import ensure_dot
    from src.lib.fs_utils import find_adjacent_files_with_same_basename, mv_dir_contents, mv_file_into_dir

    print_book_info(book)
    smart_print(f"\n{en.BOOK_ALREADY_CONVERTED}\n")
    print_moving_to_converted(book)

    if book.tree.has_structure("standalone_file"):
        ext = ensure_dot(book.orig_file_type)
        target_dir = book.converted_dir  # correctly includes series prefix when applicable
        folder_name = target_dir.name

        unique_target = book.converted_file
        target_dir.mkdir(parents=True, exist_ok=True)

        if unique_target.exists():
            smart_print("(A file with the same name already exists, this one will be renamed to prevent data loss)")

            i = 0
            unique_target = (target_dir / f"{folder_name} (copy)").with_suffix(ext)
            while unique_target.exists():
                i += 1
                unique_target = (target_dir / f"{folder_name} (copy {i})").with_suffix(ext)

        mv_file_into_dir(item.path, target_dir, new_filename=unique_target.name)

        for f in find_adjacent_files_with_same_basename(item.path):
            mv_file_into_dir(f, target_dir)

    elif book.tree.has_structure("single"):
        mv_dir_contents(book.inbox_dir, book.converted_dir, overwrite_mode="overwrite-silent")

    book.set_active_dir("converted")
    verify_and_update_id3_tags(book, in_dir="converted")

    item.set_gone()
    return 1


def print_banner(after: Callable[..., Any] | None = None):

    inbox = InboxState()
    _found = found_banner_in_print_log()
    _lc = inbox.loop_counter
    _lbc = inbox._last_banner_lc

    # The decorative header (dashes + timestamp + "Watching for…") only prints
    # once, on the very first loop.  Subsequent loops process books silently —
    # no "Checking for…" or repeated header — so the startup banner remains
    # visible and uncluttered.  after() is still called on every invocation so
    # that callers like inbox_needs_processing can still emit their own message
    # (e.g. "New activity detected") without the decorative wrapper.
    header_skip = _lc > 1 or (_found and _lbc >= _lc)

    current_local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    dash = "-" * 25

    if not header_skip:
        print_mint(f"{dash}  ⌐◒-◒  auto-m4b • {current_local_time}  {dash}")
        print_grey(f"Watching for books in [[{cfg.inbox_dir}]] ꨄ︎")
        if cfg.watch_dir:
            print_grey(f"        and [[{cfg.watch_dir}]]")
        nl()

    time.sleep(0.25 if not cfg.TEST else 0)

    if after:
        after()

    if not header_skip:
        inbox.banner_printed = True
        inbox._last_banner_lc = _lc


def print_book_series_header(book: InboxItem | None, progress: bool = True, done: bool = False):
    if not book:
        return
    if book.is_series_parent:
        parent = book
    elif not ((parent := book.series_parent) and parent.is_series_parent):
        return

    indicator = Tinta()
    if progress:
        for item in parent.series_books:
            if item == book:
                indicator.light_pink("•")
            else:
                indicator.dim().light_pink("•").normal()
    elif done:
        indicator.light_pink("✓")

    box(Tinta().pink(f"Book Series {indicator.to_str(sep='')}\n").grey(parent.basename).to_str(sep=""))


def print_book_header(book: InboxItem | None):

    if not book or book.is_series_parent:
        return
    print_book_series_header(book)
    box(book.basename, color="mint")


def print_book_done(b: int, book: Audiobook, elapsedtime: int):
    smart_print(
        Tinta("\nConverted")
        .mint(truncate_middle(book.basename, 50))
        .clear(f"in {human_elapsed_time(elapsedtime, relative=False)} 🐾✨🥞")
        .to_str()
    )


def print_footer(b: int):
    divider("\n")
    print_grey(en.DONE_CONVERTING)
    if not cfg.NO_CATS:
        print_dark_grey(CATS_ASCII)


# @cachetools.func.ttl_cache(maxsize=1, ttl=SCAN_TTL)
def audio_files_found():
    from src.lib.fs_utils import only_audio_files, filter_ignored

    inbox_dir = cfg.inbox_dir
    if not inbox_dir.exists():
        return False
    # Check disk directly rather than the filtered tree so that a match_filter
    # of "--none--" (which empties the tree) doesn't make the app think the
    # inbox is empty when audio files are physically present.
    return any(True for _ in only_audio_files(filter_ignored(inbox_dir.rglob("*"))))


def fail_book(book: Audiobook, reason: str = "unknown"):
    """Marks the book as failed, writes a log, and moves it to FAILED_FOLDER if configured."""
    from src.lib.config import cfg
    from src.lib.fs_utils import mv_dir_contents, rm_dir

    inbox = InboxState()
    if not book.key or book.key in inbox.failed_books:
        return
    inbox.set_failed(book.key, reason)

    book.write_log(reason.strip().strip("\n"))
    book.set_active_dir("inbox")
    if (build_log := book.build_dir / book.log_filename) and build_log.exists():
        if book.log_file.exists():
            # update inbox log with build dir log, preceded by a \n
            with open(build_log, "r") as f:
                log = f.read()
            with open(book.log_file, "a") as f:
                f.write(f"\n{log}")
        else:
            # move build dir log to inbox dir
            shutil.move(build_log, book.log_file)

    # Move failed book out of the inbox so it doesn't block the queue.
    if cfg.failed_dir and cfg.ON_COMPLETE != "test_do_nothing" and book.inbox_dir.exists():
        from src.lib.term import print_warning

        failed_dest = book.failed_dir
        try:
            mv_dir_contents(book.inbox_dir, failed_dest, overwrite_mode="overwrite-silent")
            if book.inbox_dir.exists():
                rm_dir(book.inbox_dir, ignore_errors=True, even_if_not_empty=True)
            if not book.inbox_dir.exists():
                inbox.set_gone(book)
                smart_print(f"\nMoved failed book to {tint_path(failed_dest)}")
        except Exception as e:
            print_warning(f"Could not move failed book to failed dir: {e}")


def backup_ok(book: Audiobook):
    # Copy files to backup destination
    from src.lib.formatters import human_size
    from src.lib.fs_utils import (
        compare_dirs_by_files,
        cp_dir_contents,
        cp_file_into_dir,
        dir_is_empty_ignoring_files,
        find_too_small_files,
    )

    if not cfg.BACKUP:
        print_debug("Not backing up (backups are disabled)")
    elif dir_is_empty_ignoring_files(book.inbox_dir):
        print_dark_grey("Skipping backup (folder is empty)")
    else:
        ln = "Making a backup copy → "
        smart_print(f"{ln}{tint_path(linebreak_path(book.backup_dir, indent=len(ln)))}")
        cp_dir_contents(book.inbox_dir, book.backup_dir, overwrite_mode="skip-silent")

        fuzzy = 1000

        # Check that files count and folder size match
        orig_files_count = book.num_files("inbox")
        orig_size_b = book.size("inbox", "bytes")
        orig_size_human = book.size("inbox", "human")
        orig_plural = pluralize(orig_files_count, "file")

        backup_files_count = book.num_files("backup")
        backup_size_b = book.size("backup", "bytes")
        backup_size_human = book.size("backup", "human")
        backup_plural = pluralize(backup_files_count, "file")

        file_count_matches = orig_files_count == backup_files_count
        size_matches = orig_size_b == backup_size_b
        size_fuzzy_matches = abs(orig_size_b - backup_size_b) < fuzzy

        expected = f"{orig_files_count} {orig_plural} ({orig_size_human})"
        found = f"{backup_files_count} {backup_plural} ({backup_size_human})"

        if file_count_matches and size_matches:
            print_grey(f"Backup successful - {backup_files_count} {orig_plural} ({backup_size_human})")
        elif orig_files_count < backup_files_count or orig_size_b < backup_size_b:
            print_grey(f"Backup successful, but extra data found in backup dir - expected {expected}, found {found}")
            print_grey("Assuming this is a previous backup and continuing")
        elif file_count_matches and size_fuzzy_matches:
            print_grey(f"Backup successful, but sizes aren't exactly the same - expected {expected}, found {found}")
            print_grey("Assuming this is a previous backup and continuing")
        elif file_count_matches and backup_size_b < orig_size_b - fuzzy:

            if too_small_files := find_too_small_files(book.inbox_dir, book.backup_dir):
                print_debug(
                    f"Found {len(too_small_files)} files in backup that are smaller than the original, trying to re-copy them"
                )

                # re-copy the files that are too small
                for f in too_small_files:
                    cp_file_into_dir(f, book.backup_dir, overwrite_mode="overwrite-silent")

                # re-check the size of the backup
                if too_small_files := find_too_small_files(book.inbox_dir, book.backup_dir):
                    print_error(
                        f"Backup failed - expected {orig_size_human}, but backup is only {backup_size_human} (found {len(too_small_files)} files that are smaller than the original)"
                    )
                    smart_print("Skipping this book\n")
                    return False
        else:
            # for each audio file in left, find it in right, and compare size of each.
            # if the size is the same, remove it from the list of files to check.
            left_right_files = compare_dirs_by_files(book.inbox_dir, book.backup_dir)
            # if None in the 3rd column of left_right_files, a file is missing from the backup
            missing_files = [f for f in left_right_files if f[2] is None]
            if missing_files:
                print_error(
                    f"Backup failed - {len(missing_files)} {pluralize(len(missing_files), 'file')} missing from backup"
                )
                smart_print("Skipping this book\n")
                return False
            # compare the size of each file in the list of files to check
            for left, l_size, _, r_size in left_right_files:
                if l_size != r_size:
                    l_human_size = human_size(l_size)
                    r_human_size = human_size(r_size)
                    print_error(
                        f"Backup failed - size mismatch for {left} - original is {l_human_size}, but backup is {r_human_size}"
                    )
                    smart_print("Skipping this book\n")
                    return False
            if expected != found:
                print_error(f"Backup failed - expected {expected}, found {found}")
                smart_print("Skipping this book\n")
                return False

    return True


def ok_to_overwrite(book: Audiobook):
    from src.lib.term import print_notice, print_warning

    if book.converted_file.is_file():
        if cfg.OVERWRITE_MODE == "skip":
            if book.archive_dir.exists():
                print_notice(
                    f"Found a copy of this book in {tint_path(cfg.archive_dir)}, it has probably already been converted"
                )
                print_notice("Skipping this book because OVERWRITE_EXISTING is not enabled")
                InboxState().set_processed(book)
                return False
            elif book.size("converted", "bytes") > 0:
                print_notice(f"Output file already exists and OVERWRITE_EXISTING is not enabled, skipping this book")
                InboxState().set_processed(book)
                return False
        else:
            print_warning("Warning: Output file already exists, it and any other {{.m4b}} files will be overwritten")

    return True


def check_failed_books():
    inbox = InboxState()
    if not inbox.failed_books:
        return
    # print_debug(f"Found failed books: {[k for k in inbox.failed_books.keys()]}")
    for book_name, item in inbox.failed_books.items():
        # ensure last_modified is a float
        failed_book = Audiobook(cfg.inbox_dir / book_name)
        # was_modified = (
        #     last_updated_at(failed_book.inbox_dir, only_file_exts=cfg.AUDIO_EXTS)
        #     > item.last_updated
        # )
        # if was_modified:
        #     print_debug(
        #         f"{book_name} has been modified since it failed last, checking if hash has changed"
        #     )
        last_book_hash = item._curr_hash
        curr_book_hash = failed_book.hash()
        if last_book_hash is None:
            raise ValueError(
                f"Book {failed_book.inbox_dir} was in failed books but no hash was found for it, this should not happen\ncurr: {curr_book_hash}"
            )
        hash_changed = last_book_hash != curr_book_hash
        if hash_changed:
            # print_debug(
            #     f"{book_name} hash changed since it failed last, removing it from failed books\n        was {last_book_hash}\n        now {curr_book_hash}"
            # )
            inbox.set_needs_retry(book_name)
        # else:
        #     print_debug(f"{book_name} hash is the same, keeping it in failed books")


def copy_to_working_dir(book: Audiobook):
    from src.lib.fs_utils import cp_dir, cp_file_into_dir

    # Move from inbox to merge folder
    smart_print("\nCopying files to working folder...", end="")
    cp_dir(book.inbox_dir, book.merge_dir.parent, overwrite_mode="overwrite-silent")
    # copy book.cover_art to merge folder
    if book.cover_art_file and not book.cover_art_file.exists():
        cp_file_into_dir(book.cover_art_file, book.merge_dir, overwrite_mode="overwrite-silent")
    print_mint(" ✓\n")
    book.set_active_dir("merge")


def books_to_process() -> tuple[int, Callable[[], None]]:

    inbox = InboxState()

    check_failed_books()

    # num_total_ok counts all ok/new/needs_retry books regardless of match_filter.
    # num_ok and num_books both use the filtered view and may be 0 when match_filter
    # excludes everything (e.g. "--none--"), even if books exist on disk.
    total_books = inbox.num_total_ok

    # If all books have failed (no ok books at all), show "waiting" message before
    # the "no books to convert" check - otherwise we'd show the wrong message.
    if inbox.num_failed and not total_books:
        return 0, lambda: smart_print(
            f"Found {pluralize_with_count(inbox.num_failed, 'book')} in the inbox that failed to convert - waiting for {pluralize(inbox.num_failed, 'it', 'them')} to be fixed",
            highlight_color=AMBER_COLOR,
        )

    # If no books at all (unfiltered), print the "nothing here" message.
    if not total_books:
        return 0, lambda: smart_print(f"No books to convert, watching for changes...\n")

    if inbox.match_filter and not inbox.matched_books:
        return 0, lambda: smart_print(
            f"Found {pluralize_with_count(total_books, 'book')} in the inbox, but none match [[{inbox.match_filter}]]",
            highlight_color=AMBER_COLOR,
        )

    if not inbox.ok_books and inbox.num_failed:
        return 0, lambda: smart_print(
            f"Found {pluralize_with_count(inbox.num_failed, 'book')} in the inbox that failed to convert - waiting for {pluralize(inbox.num_failed, 'it', 'them')} to be fixed",
            highlight_color=AMBER_COLOR,
        )

    skipping = f"skipping {inbox.num_failed} that previously failed" if inbox.num_failed else ""

    if inbox.match_filter and (inbox.all_books_failed):
        s = f"all {pluralize_with_count(inbox.num_matched, 'book')}" if inbox.num_matched > 1 else "1 book"
        note = wrap_brackets(f"ignoring {inbox.num_ignored_books}" if inbox.num_ignored_books else "")
        return 0, lambda: smart_print(
            f"Failed to convert {s} in the inbox matching [[{inbox.unescaped_match_filter}]]{note}",
            highlight_color=AMBER_COLOR,
        )

    if inbox.match_filter and inbox.matched_ok_books:
        ignoring = f"ignoring {inbox.num_ignored_books}" if inbox.num_ignored_books else ""
        note = wrap_brackets(ignoring, skipping, sep=", ")
        return inbox.num_matched_ok, lambda: smart_print(
            f"Found {pluralize_with_count(inbox.num_matched, 'book')} in the inbox matching [[{inbox.unescaped_match_filter}]]{note}\n",
            highlight_color=AMBER_COLOR,
        )
    elif inbox.failed_books:
        return inbox.num_ok, lambda: smart_print(
            f"Found {pluralize_with_count(inbox.num_ok, 'book')} to convert ({skipping})\n",
            highlight_color=AMBER_COLOR,
        )
    else:
        return inbox.num_ok, lambda: smart_print(f"Found {pluralize_with_count(inbox.num_ok, 'book')} to convert\n")


def can_process_multi_dir(book: Audiobook):
    from src.lib.fs_utils import flatten_files_in_dir, flattening_multi_disc_files_in_dir_affects_order

    inbox = InboxState()
    if book.tree.has_structure_like("series") or book.tree.has_structure_like("multi"):
        help_msg = f"Please organize the files in a single folder and rename them so they sort alphabetically\nin the correct order"
        if book.tree.has_structure_like("series"):
            inbox.set_ok(book)
        elif book.tree.has_structure("multi_disc"):
            smart_print(
                "\nThis folder appears to be a multi-disc book, attempting to flatten it...",
                end="",
            )
            if flattening_multi_disc_files_in_dir_affects_order(book.inbox_dir):
                nl(2)
                print_error("Flattening this book would affect the file order, cannot proceed")
                smart_print(f"{help_msg}\n")
                fail_book(
                    book,
                    "This book appears to be a multi-disc book, but flattening it would affect the file order - it will need to be fixed manually by renaming the files so they sort alphabetically in the correct order",
                )
                return False
            else:
                flatten_files_in_dir(book.inbox_dir, prefix_with_parent=True)
                book.rescan()
                # book = Audiobook(book.inbox_dir)
                print_mint(" ✓\n")
                # files = "\n".join([str(f) for f in book.inbox_dir.glob("*")])
                # print_debug(f"New file structure:\n{files}")
                inbox.set_ok(book)
        elif book.tree.has_structure("multi_part"):
            print_error(f"{en.MULTI_ERR}, maybe this is a multi-part book or a series?")
            smart_print(f"{help_msg}\n")
            fail_book(book, f"{en.MULTI_ERR} (multi-part book) - {help_msg}")
            return False
        else:
            print_error(en.MULTI_ERR)
            smart_print(f"{help_msg}\n")
            fail_book(book, f"{en.MULTI_ERR} (structure unknown) - {help_msg}")
            return False

    return True


def can_process_roman_numeral_book(book: Audiobook):
    if book.num_roman_numerals > 1:
        if roman_numerals_affect_file_order(book.inbox_dir):
            print_error(en.ROMAN_ERR)
            help_msg = "Roman numerals do not sort in alphabetical order; please rename them so they sort alphabetically in the correct order"
            smart_print(f"{help_msg}\n")
            fail_book(book, f"{en.ROMAN_ERR} - {help_msg}")
            return False
        else:
            print_debug(
                f"Found {book.num_roman_numerals} roman numeral(s) in {book.basename}, but they don't affect file order"
            )
    return True


def has_audio_files(book: Audiobook):
    if book.inbox_dir.is_file():
        print_debug(f"has_audio_files: '{book.inbox_dir}' is a standalone file, not a folder — skipping")
        return False
    if not book.num_files("inbox"):
        print_notice(f"'{book.inbox_dir}' does not contain any known audio files, skipping")
        fail_book(book, "No audio files found in this folder")
        return False
    return True


def flatten_nested_book(book: Audiobook, series_rerouted: bool = False):
    from src.lib.fs_utils import flatten_files_in_dir

    is_nested = book.tree.has_structure("nested")
    is_messy = book.is_flatish
    if is_nested or is_messy:
        if series_rerouted and is_nested:
            msg = en.BOOK_SERIES_PART_FLATTEN
        elif is_nested:
            msg = en.BOOK_NEEDS_FLATTENING
        else:
            msg = en.BOOK_IS_FLAT_BUT_MESSY
        smart_print(msg, end="")
        flatten_files_in_dir(book.inbox_dir)
        print_mint(" ✓\n")
        book.rescan()


def print_book_info(book: "Audiobook"):
    smart_print("\nFile/folder info:")

    lmt = 120
    src = linebreak_path(book.inbox_dir, indent=10, limit=lmt) if len(str(book.inbox_dir)) > lmt else book.inbox_dir
    dst = (
        linebreak_path(book.converted_dir, indent=10, limit=lmt)
        if len(str(book.converted_dir)) > lmt
        else book.converted_dir
    )
    print_list_item(f"Source: {src}")
    print_list_item(f"Output: {dst}")
    print_list_item(f"Format: {book.orig_file_type}")
    num_files = 1 if book.tree.has_structure("standalone_file") else book.num_files("inbox")
    print_list_item(f"Audio files: {num_files}")
    print_list_item(f"Total size: {book.size('inbox', 'human')}")
    if book.cover_art_file:
        print_list_item(f"Cover art: {book.cover_art_file.name}")

    nl()


def convert_book(book: Audiobook):
    if not book.merge_dir.exists():
        raise FileNotFoundError(
            f"Fatal: Merge folder '{book.merge_dir}' does not exist – ensure that auto_m4b has permissions to write to this path. If this error persists, please open an issue on GitHub."
        )

    if not book.num_files("merge"):
        raise FileNotFoundError(
            f"Fatal: No audio files found in merge folder '{book.merge_dir}' – ensure that auto_m4b has permissions to write to this path. If this error persists, please open an issue on GitHub."
        )

    # Pre-extract cover art for m4a/m4b inputs
    if book.orig_file_type in ["m4a", "m4b"]:
        book.extract_cover_art()

    starttime_friendly = friendly_date()
    if book.orig_file_type in ["m4a", "m4b"]:
        smart_print(f"Starting merge/passthrough → {tinted_m4b()} at {tint_light_grey(starttime_friendly)}...")
    else:
        smart_print(f"Starting {tinted_file(book.orig_file_type)} → {tinted_m4b()} conversion at {tint_light_grey(starttime_friendly)}...")

    try:
        elapsed = convert_book_native(book)
    except Exception as exc:
        err_msg = str(exc)
        book.write_log(err_msg)
        nl()
        print_error(f"Native converter error: {err_msg}")
        smart_print(f"See log file in {tint_light_grey(book.inbox_dir)} for details\n")
        # Log before moving: log_global_results accesses book.num_files/size/duration
        # for the inbox dir. fail_book() may move that dir to FAILED_FOLDER, making
        # the inbox dir disappear and causing a FileNotFoundError in log_global_results.
        log_global_results(book, "FAILED", 0)
        fail_book(book, reason=err_msg)
        return False

    if not book.build_file.exists():
        err_msg = f"Native converter failed to produce output .m4b for {book}"
        book.write_log(err_msg)
        print_error(f"Error: {err_msg}")
        log_global_results(book, "FAILED", 0)
        fail_book(book, reason=err_msg)
        return False

    verify_and_update_id3_tags(book, in_dir="build")

    return elapsed

def move_desc_file(book: Audiobook):
    from src.lib.fs_utils import mv_file_into_dir

    desc_files = []
    did_remove_old_desc = False
    for d in [book.build_dir, book.merge_dir, book.converted_dir]:
        _desc_files = list(Path(d).rglob(f"{book} [*kHz*].txt"))
        for f in _desc_files:
            f.unlink()
            did_remove_old_desc = True
        desc_files.extend(_desc_files)

    if did_remove_old_desc:
        print_notice(f"Removed old description {pluralize(len(desc_files), 'file')}")

    mv_file_into_dir(
        book.merge_desc_file,
        book.final_desc_file.parent,
        new_filename=book.final_desc_file.name,
        overwrite_mode="overwrite-silent",
    )


def print_moving_to_converted(book):
    ln = "Moving to converted books folder → "

    smart_print(f"{ln}{tint_path(linebreak_path(book.converted_file, indent=len(ln)))}")


def move_converted_book_and_extras(book: Audiobook):
    from src.lib.fs_utils import mv_dir_contents, mv_file_into_dir, rm_all_empty_dirs, rm_dirs, safe_filename

    print_moving_to_converted(book)

    # Move jpg, png, txt, etc. from merge folder to output folder, sanitizing
    # filenames so that characters illegal on SMB/NTFS (e.g. ":") don't slip
    # through from old inbox artifacts copied into the merge dir.
    book.converted_dir.mkdir(parents=True, exist_ok=True)
    for src_file in book.merge_dir.iterdir():
        if not src_file.is_file():
            continue
        if src_file.suffix.lower() not in cfg.OTHER_EXTS:
            continue
        safe_name = safe_filename(src_file.name)
        mv_file_into_dir(
            src_file,
            book.converted_dir,
            new_filename=safe_name,
            overwrite_mode="overwrite-silent",
        )

    # Also delete any stale [quality].txt files in the converted dir whose names
    # still contain unsafe chars (e.g. from a pre-fix conversion run).
    for f in book.converted_dir.glob("*.txt"):
        if safe_filename(f.name) != f.name:
            f.unlink(missing_ok=True)

    if book.log_file.is_file():
        # Delete it if it's empty, otherwise move it
        if not book.log_file.read_text().strip():
            book.log_file.unlink()
        else:
            mv_file_into_dir(
                book.log_file,
                book.converted_dir,
                new_filename=book.log_filename,
                overwrite_mode="overwrite-silent",
            )

    # Remove intermediate temp files before moving — prevents ~tmpfiles from being
    # carried into the converted output directory by mv_dir_contents' recursive descent.
    rm_dirs([book.build_tmp_dir], ignore_errors=True, even_if_not_empty=True)
    rm_all_empty_dirs(book.build_dir)

    # Move all built audio files to output folder
    mv_dir_contents(
        book.build_dir,
        book.converted_dir,
        only_file_exts=AUDIO_EXTS,
        silent_files=[book.build_file.name],
    )

    book.set_active_dir("converted")

    if not book.converted_file.is_file():
        print_error(
            f"Error: The output file does not exist, something went wrong during the conversion\n     Expected it to be at {book.converted_file}"
        )
        fail_book(book)
        return False

    return True
    # Remove description.txt from output folder if "$book [$desc_quality].txt" exists
    # if book.final_desc_file.is_file():
    #     (book.converted_dir / "description.txt").unlink(missing_ok=True)
    # else:
    #     print_notice(
    #         "The description.txt is missing (reason unknown), trying to save a new one"
    #     )
    #     book.write_description_txt(book.final_desc_file)


def cleanup_series_dir(parent: InboxItem | None):
    from src.lib.fs_utils import _mv_or_cp_dir_contents, is_ok_to_delete, rm_dir

    if not parent or not parent.is_series_parent:
        print_debug(f"{parent} is not a series parent, can't move series extras or clean up")
        return

    print_book_series_header(parent, progress=False, done=True)

    parent_book = parent.to_audiobook()
    verb = "copy" if cfg.ON_COMPLETE == "test_do_nothing" else "move"
    # Move (or copy) series collateral to converted folder.
    # Guard: the inbox dir may already be gone if individual series books were
    # archived/moved by the OS or another process before we reach cleanup.
    if parent_book.inbox_dir.exists():
        _mv_or_cp_dir_contents(
            verb,
            parent_book.inbox_dir,
            parent_book.converted_dir,
            only_file_exts=cfg.OTHER_EXTS,
            overwrite_mode="overwrite-silent",
        )
    else:
        print_debug(
            f"cleanup_series_dir: inbox dir '{parent_book.inbox_dir}' no longer exists, skipping collateral move"
        )

    parent_book.set_active_dir("converted")

    if cfg.ON_COMPLETE == "test_do_nothing":
        print_notice("Test mode: The original series folder will not be moved or deleted")
    else:
        smart_print("\nCleaning up series folder...", end="")

        if parent_book.inbox_dir.exists():
            if cfg.ON_COMPLETE == "archive":
                _mv_or_cp_dir_contents(
                    verb,
                    parent_book.inbox_dir,
                    parent_book.archive_dir,
                    overwrite_mode="skip-silent",
                )

                if parent_book.inbox_dir.exists():
                    # Cross-partition: fell back to copy, leaving source intact.
                    # Remove it now so the series folder isn't reprocessed.
                    rm_dir(parent_book.inbox_dir, ignore_errors=True, even_if_not_empty=True)

            elif cfg.ON_COMPLETE == "delete":
                can_del = is_ok_to_delete(parent_book.inbox_dir)
                if can_del or cfg.BACKUP:
                    rm_dir(
                        parent_book.inbox_dir,
                        ignore_errors=True,
                        even_if_not_empty=True,
                    )
                elif not can_del and not cfg.BACKUP:
                    print_notice(
                        f"Notice: The book series folder [[{parent_book.inbox_dir}]] is not empty, it will not be deleted because backups are disabled"
                    )
                    return
            InboxState().set_gone(parent_book)
        print_mint(" ✓")


def archive_inbox_book(book: Audiobook):
    from src.lib.fs_utils import is_ok_to_delete, mv_dir_contents, rm_dir
    from src.lib.term import print_notice, print_warning

    if cfg.ON_COMPLETE == "test_do_nothing":
        print_notice("Test mode: The original folder will not be moved or deleted")
        InboxState().set_processed(book)
    else:
        if not book.inbox_dir.exists():
            print_notice(en.BOOK_INBOX_MOVED_AFTER_CONVERSION)
            InboxState().set_gone(book)
            return

        if cfg.ON_COMPLETE == "archive":
            smart_print("\nArchiving original from inbox...", end="")
            mv_dir_contents(
                book.inbox_dir,
                book.archive_dir,
                overwrite_mode="overwrite-silent",
            )

            if book.inbox_dir.exists():
                # Cross-partition: mv_dir_contents fell back to copy, leaving source
                # intact. Remove it now so the book isn't reprocessed on the next loop.
                rm_dir(book.inbox_dir, ignore_errors=True, even_if_not_empty=True)

            if book.inbox_dir.exists():
                print_warning(
                    f"Warning: {tint_warning(book)} is still in the inbox folder, it should have been archived"
                )
                print_orange("     To prevent this book from being converted again, move it out of the inbox folder")
                return

        elif cfg.ON_COMPLETE == "delete":
            smart_print("\nDeleting original from inbox...", end="")
            can_del = is_ok_to_delete(book.inbox_dir)
            if can_del or cfg.BACKUP:
                rm_dir(book.inbox_dir, ignore_errors=True, even_if_not_empty=True)
            elif not can_del and not cfg.BACKUP:
                print_notice(
                    "Notice: The original folder is not empty, it will not be deleted because backups are disabled"
                )
                return

        InboxState().set_gone(book)
        print_mint(" ✓")


_SERIES_NUM_RE = re.compile(r"\s+0*\d+\s*[-–\s]")


def _series_prefix(name: str) -> str:
    """Return the series prefix from a folder name, or '' if none detected.

    E.g. 'SIGMA Force 02 - Map of Bones (2006)' → 'SIGMA Force'
         'Jake Ransom 02 - The Howling Sphinx'   → 'Jake Ransom'
         'Map of Bones (2006)'                   → '' (no series number)
    """
    m = _SERIES_NUM_RE.search(name)
    return name[: m.start()].strip() if m else ""


def _name_matches_author_tag(search_root: "Path", dir_name: str, threshold: float = 0.75) -> bool:
    """Return True if dir_name fuzzy-matches the artist/author ID3 tag found on
    the first audio file discovered under search_root (any depth).  Used as a
    fallback when the directory name is not in "Last, First" comma format.
    """
    from difflib import SequenceMatcher

    _AUDIO_EXTS = {".mp3", ".m4a", ".m4b", ".flac", ".ogg", ".aac", ".wav"}
    first_audio = next(
        (f for f in search_root.rglob("*") if f.is_file() and f.suffix.lower() in _AUDIO_EXTS),
        None,
    )
    if not first_audio:
        return False
    try:
        import mutagen
        tags = mutagen.File(first_audio, easy=True)
        if not tags:
            return False
        author = (tags.get("artist") or tags.get("albumartist") or [""])[0]
        if not author:
            return False
        ratio = SequenceMatcher(None, dir_name.lower(), author.lower()).ratio()
        return ratio >= threshold
    except Exception:
        return False


def _find_author_subfolder(book: "Audiobook") -> "Path | None":
    """If book.inbox_dir sits directly under cfg.inbox_dir, looks like an
    author name, and contains exactly one sub-directory with audio, return
    that sub-directory.

    This prevents flattening structures like:
      inbox/Weir, Alison/A dangerous inheritance/audio.mp3
    where the outer folder is an author dir, not a book title.  Without this
    check the audio would be flattened up to the author root and the book
    subfolder would be lost.

    Author-name detection uses two heuristics (either is sufficient):
      1. The directory name contains a comma  ("Weir, Alison" / "King, S.J.")
      2. The directory name fuzzy-matches the artist ID3 tag on the first
         audio file found inside it (handles "First Last" or slight typos).
    """
    from src.lib.config import cfg

    if not book.tree.has_structure("nested"):
        return None

    # Must be a top-level inbox entry (direct child of inbox_dir)
    if book.inbox_dir.parent != cfg.inbox_dir:
        return None

    dir_name = book.inbox_dir.name

    # Heuristic 1: "Last, First" or "Last, First M." comma format
    is_author = "," in dir_name
    # Heuristic 2: fuzzy-match against the ID3 author tag (handles "First Last")
    if not is_author:
        is_author = _name_matches_author_tag(book.inbox_dir, dir_name)

    if not is_author:
        return None

    try:
        subdirs = [
            d for d in book.inbox_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
    except OSError:
        return None

    # Only reroute when there is exactly one book subfolder; if there are
    # multiple, the inbox scanner already picked them up as individual books.
    if len(subdirs) != 1:
        return None

    return subdirs[0]


def _find_series_subfolder(book: "Audiobook") -> "Path | None":
    """If book.inbox_dir contains exactly one sub-directory whose name shares
    a series prefix with an existing converted sibling, return that sub-dir.

    This is used to reroute processing for cases like:
      inbox/Rollins, James/SIGMA Force 02 - Map of Bones (2006)/…
    where  converted/Rollins, James/SIGMA Force 01 - Sandstorm (2004)/
    already exists — the book belongs in the series tree, not the author root.
    """
    if not book.tree.has_structure("nested"):
        return None

    try:
        subdirs = [
            d
            for d in book.inbox_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
    except OSError:
        return None

    if len(subdirs) != 1:
        return None

    candidate = subdirs[0]
    prefix = _series_prefix(candidate.name)
    if not prefix:
        return None

    converted_parent = book.converted_dir
    if not converted_parent.exists():
        return None

    for sibling in converted_parent.iterdir():
        if (
            sibling.is_dir()
            and sibling.name != candidate.name
            and sibling.name.lower().startswith(prefix.lower())
        ):
            return candidate

    return None


def process_book(b: int, item: InboxItem, _series_rerouted: bool = False):
    from src.lib.fs_utils import clean_dirs, rm_all_empty_dirs, rm_dirs, was_recently_modified
    from src.lib.term import print_notice

    inbox = InboxState()
    book = item.to_audiobook()

    # Before printing anything: if this is a single nested entry whose series
    # is already present in the converted dir, silently reroute to the
    # sub-folder so the output lands in the correct series location rather
    # than the author root (e.g. Author/Series 02 - Title/ not Author/).
    if series_subdir := _find_series_subfolder(book):
        from src.lib.books_tree.books_tree import BooksTree
        from src.lib.inbox_item import InboxItem as _InboxItem

        sub_tree = BooksTree(series_subdir)
        sub_tree.scan()
        return process_book(b, _InboxItem(sub_tree), _series_rerouted=True)

    # Similarly, if the book root looks like an author-name directory
    # (e.g. "Weir, Alison") containing a single book subfolder, reroute to
    # the subfolder so we don't flatten away the book's own directory.
    if author_subdir := _find_author_subfolder(book):
        from src.lib.books_tree.books_tree import BooksTree
        from src.lib.inbox_item import InboxItem as _InboxItem

        sub_tree = BooksTree(author_subdir)
        sub_tree.scan()
        return process_book(b, _InboxItem(sub_tree))

    print_book_header(item)

    if not item.path.exists():
        print_notice(f"This book was removed from the inbox or cannot be accessed, skipping")
        inbox.set_gone(item.path)
        return b

    # check if the current dir was modified in the last 1m and skip if so
    if was_recently_modified(book.inbox_dir):
        print_notice(en.BOOK_RECENTLY_MODIFIED)
        return b

    if inbox.should_retry(book):
        nl()
        smart_print(en.BOOK_SHOULD_RETRY)

    # can't modify the inbox dir until we check whether it was modified recently
    book.log_file.unlink(missing_ok=True)

    if book.tree.has_any_structure("single", "standalone_file"):
        if book.orig_file_type == "m4b":
            b += process_already_m4b(book, item)
            if item.is_gone:
                return b
        elif book.tree.is_file():
            book, item = move_standalone_into_dir(book, item)

    if not has_audio_files(book):
        return b

    # "mixed" is only used internally by the scorer; the book tree gets "unknown"
    # when the scorer cannot determine a valid structure. A book with unknown
    # structure that still has subdirectories cannot be safely processed.
    if book.tree.has_structure("unknown") and book.tree.dirs:
        print_error(en.MULTI_ERR)
        fail_book(book, en.MULTI_ERR)
        return b

    if not can_process_multi_dir(book):
        return b

    if book.tree.has_structure("series_parent"):
        return b

    if not can_process_roman_numeral_book(book):
        return b

    print_book_info(book)

    if not backup_ok(book):
        return b

    if not ok_to_overwrite(book):
        return b

    flatten_nested_book(book, series_rerouted=_series_rerouted)

    inbox.set_ok(book)

    try:
        copy_to_working_dir(book)
    except (FileNotFoundError, OSError) as e:
        if not book.inbox_dir.exists():
            print_notice(en.BOOK_INBOX_MOVED_BEFORE_PROCESSING)
            inbox.set_gone(book)
            return b
        raise

    book.extract_path_info(console=True)
    book.extract_metadata(console=True)

    clean_dirs([book.build_dir, book.build_tmp_dir])
    rm_all_empty_dirs(cfg.merge_dir)

    book.set_active_dir("build")

    nl()

    # TODO: Only handles single m4b output file, not multiple files.

    if (elapsedtime := convert_book(book)) is False:
        return b

    book.converted_dir.mkdir(parents=True, exist_ok=True)

    # m4b_num_parts=1 # hardcode for now, until we know if we need to split parts

    # move_desc_file(book)

    log_global_results(book, "SUCCESS", elapsedtime)

    book.write_description_txt(book.final_desc_file)
    if not move_converted_book_and_extras(book):
        return b

    archive_inbox_book(book)

    print_book_done(b, book, elapsedtime)
    rm_dirs([book.build_dir, book.merge_dir], ignore_errors=True, even_if_not_empty=True)
    b += 1
    return b


def process_inbox():
    from src.lib.fs_utils import clean_dirs, inbox_last_updated_at
    from src.lib.run import audio_files_found, print_banner
    from src.lib.term import print_debug

    inbox = InboxState()

    if inbox.loop_counter == 1:
        if "pytest" not in sys.modules:
            # Production startup: print banner immediately so the user sees the app
            # is alive, then do the (potentially slow) full scan in the background.
            # The watchdog loop in auto_m4b.py uses dirty.wait(timeout) so it wakes
            # up and begins processing once inbox.ready is set.
            print_banner()
            import threading

            def _bg_scan():
                import traceback
                t0 = time.monotonic()
                print_debug("[bg-scan] Starting background inbox scan...")
                try:
                    inbox.scan(set_ready=True, force=True, scan_id3=False)
                    # Record the post-scan hash as both the run-start and run-end
                    # checkpoints so the first inbox_needs_processing() call can skip
                    # the otherwise redundant re-scan (nothing changed since we just
                    # finished scanning).
                    inbox.start()
                    inbox.done()
                    elapsed = time.monotonic() - t0
                    print_debug(
                        f"[bg-scan] Done in {elapsed:.1f}s — ready={inbox.ready}, "
                        f"items={len(inbox._items)}, ok={inbox.num_matched_ok}"
                    )
                except Exception as e:
                    print_debug(f"[bg-scan] ERROR: {e}\n{traceback.format_exc()}")

            threading.Thread(target=_bg_scan, daemon=True).start()
            return
        inbox.scan(set_ready=True, force=True)
        print_banner()

    def _sweep_empty_inbox_dirs():
        """Remove empty leftover dirs from the inbox (e.g. series parent dirs whose
        children were all archived in a previous run). Safe because:
        - first prunes any empty sub-directories recursively (shell folders left
          behind after individual books were archived)
        - only then removes the top-level dir if it is now also empty
        - skips dirs modified within WAIT_TIME seconds (actively receiving files)
        - skips dirs that are currently tracked as books in _items"""
        from src.lib.fs_utils import rm_all_empty_dirs, rm_dir, was_recently_modified

        for subdir in sorted(cfg.inbox_dir.iterdir()):
            if not subdir.is_dir() or was_recently_modified(subdir) or inbox.get(subdir):
                continue
            # First remove any nested empty dirs (e.g. individual book folders
            # whose audio was already archived, leaving an empty shell).
            rm_all_empty_dirs(subdir)
            # Now remove the top-level dir if it is itself empty.
            if not any(subdir.iterdir()):
                print_debug(f"Removing empty leftover inbox dir: {subdir.name}")
                rm_dir(subdir, ignore_errors=True)

    print_debug(f"[process_inbox] loop={inbox.loop_counter}, checking audio_files_found...")
    if not audio_files_found():
        print_debug(
            f"No audio files found in {cfg.inbox_dir}\n        Last updated at {inbox_last_updated_at(friendly=True)}, watching for changes...",
            only_once=True,
        )
        # Still sweep for empty leftover dirs (e.g. series parents from a previous run).
        _sweep_empty_inbox_dirs()
        return
    print_debug(f"[process_inbox] audio files found, checking inbox_needs_processing...")
    if (
        # not inbox.inbox_needs_processing(on_will_scan=process_standalone_files)
        not inbox.inbox_needs_processing()
        and inbox.loop_counter > 1
    ):
        # Nothing changed since the last run — skip this idle loop entirely.
        # Do NOT print a banner here; a banner without a matching CATS footer
        # would violate assert_not_ends_with_banner in tests and looks wrong in
        # production when the app is just polling for new books.
        return
    # Only print the banner when something actually changed in the inbox (new
    # books added/removed) or on the very first processing loop. Re-processing
    # the same set of pending books (e.g. retrying after a transient failure)
    # should not flood the log with headers every SLEEP_TIME seconds.
    _should_banner = inbox.loop_counter <= 1
    if info := books_to_process():
        _expected, msg = info
        if _should_banner:
            print_banner(after=lambda: [x() for x in (nl, msg)])
        else:
            nl()
            msg()
    elif _should_banner:
        print_banner()

    # process_standalone_files()

    inbox.start()

    b = 0
    for item in inbox.matched_ok_books.values():
        b = process_book(b, item)
        divider("\n", "\n")

        if item.is_series_book and item.is_last_book_in_series:
            cleanup_series_dir(item.series_parent)

    # Sweep 1: series parents still in _items whose inbox dir became empty during this
    # run. Catches cases where is_last_book_in_series didn't fire (e.g. dict ordering
    # placed the "last" child first and it converted before the others).
    for parent_item in list(inbox._items.values()):
        if (
            parent_item.is_series_parent
            and parent_item.status not in ("gone", "processed")
            and parent_item.path.is_dir()
            and not any(parent_item.path.iterdir())
        ):
            cleanup_series_dir(parent_item)

    # Sweep 2: empty inbox subdirs not in _items — container-restart scenario.
    _sweep_empty_inbox_dirs()

    if b:
        print_footer(b)
    clean_dirs([cfg.merge_dir, cfg.build_dir, cfg.trash_dir])
    inbox.done()
    inbox.prune_gone()
    return b
    trim_print_log()
