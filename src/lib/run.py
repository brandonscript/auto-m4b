import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from tinta import Tinta

from src.lib.audiobook import Audiobook
from src.lib.config import cfg
from src.lib.formatters import (
    human_elapsed_time,
    pluralize,
    pluralize_with_count,
)
from src.lib.fs_utils import *
from src.lib.fs_utils import _mv_or_cp_dir_contents
from src.lib.id3_utils import verify_and_update_id3_tags
from src.lib.inbox_state import InboxItem, InboxState
from src.lib.logger import log_global_results
from src.lib.m4btool import M4bTool
from src.lib.misc import re_group
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
    wrap_brackets,
)

# glasses 1: ⌐◒-◒
# glasses 2: ᒡ◯ᴖ◯ᒢ


def move_standalone_into_dir(book: Audiobook, item: InboxItem):
    if not book.is_not_a("standalone_file", "m4b"):
        return book, item

    ext = ensure_dot(book.orig_file_type)

    folder_name = item.path.stem
    smart_print(f"\nMoving standalone {ext} into its own folder → ./{folder_name}/")
    new_folder = cfg.inbox_dir / folder_name
    new_folder.mkdir(exist_ok=True)
    mv_file_into_dir(item.path, new_folder, overwrite_mode="overwrite-silent")

    # move any other files with the same basename to the new folder
    for f in find_adjacent_files_with_same_basename(item.path):
        mv_file_into_dir(f, new_folder)

    # update item
    item = InboxItem(new_folder / new_folder)
    item.reload()
    return item.to_audiobook(), item


def process_already_m4b(book: Audiobook, item: InboxItem):

    print_book_info(book)
    smart_print(f"\n{en.BOOK_ALREADY_CONVERTED}\n")
    print_moving_to_converted(book)

    if book.tree.has_structure("standalone_file"):
        file_name = item.key
        ext = ensure_dot(book.orig_file_type)
        folder_name = item.path.stem
        target_dir = cfg.converted_dir / folder_name

        unique_target = target_dir / file_name
        (target_dir).mkdir(parents=True, exist_ok=True)

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

    # print_debug(f"Maybe printing banner, loop {InboxState().loop_counter}")
    inbox = InboxState()

    skip = found_banner_in_print_log() and any([inbox.loop_counter > 1 and not inbox.stale, inbox.banner_printed])

    current_local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    dash = "-" * 25

    if not skip:
        print_mint(f"{dash}  ⌐◒-◒  auto-m4b • {current_local_time}  {dash}")

    msg = "Checking for" if inbox.matched_ok_books and inbox.loop_counter > 1 else "Watching for"
    if not skip:
        print_grey(f"{msg} books in [[{cfg.inbox_dir}]] ꨄ︎")

    if not skip and inbox.loop_counter == 1:
        nl()

    time.sleep(0.25 if not cfg.TEST else 0)

    if after:
        # print_debug("Running after function")
        after()

    if not skip:
        inbox.banner_printed = True
        # print_debug("Set banner_printed to True")

    # if skip:
    #     print_debug(f"Skipping banner (loop {inbox.loop_counter})")


def print_book_series_header(book: InboxItem | None, progress: bool = True, done: bool = False):
    if not book:
        return
    if book.is_maybe_series_parent:
        parent = book
    elif not ((parent := book.series_parent) and parent.is_maybe_series_parent):
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

    if not book or book.is_maybe_series_parent:
        return
    print_book_series_header(book)
    box(book.basename, color="mint")


def print_book_done(b: int, book: Audiobook, elapsedtime: int):
    smart_print(
        Tinta("\nConverted")
        .mint(book.basename)
        .clear(f"in {human_elapsed_time(elapsedtime, relative=False)} 🐾✨🥞")
        .to_str()
    )


def print_footer(b: int):
    divider("\n")
    if b:
        print_grey(en.DONE_CONVERTING)
    else:
        print_dark_grey(f"Waiting for books to be added to the inbox...")

    if not cfg.NO_CATS:
        print_dark_grey(CATS_ASCII)


# @cachetools.func.ttl_cache(maxsize=1, ttl=SCAN_TTL)
def audio_files_found():
    return InboxState().num_audio_files_deep > 0


def fail_book(book: Audiobook, reason: str = "unknown"):
    """Adds the book's path to the failed books dict with a value of the last modified date of of the book"""
    inbox = InboxState()
    if book.key in inbox.failed_books:
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


def backup_ok(book: Audiobook):
    # Copy files to backup destination
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
    if book.converted_file.is_file():
        if cfg.OVERWRITE_MODE == "skip":
            if book.archive_dir.exists():
                print_notice(
                    f"Found a copy of this book in {tint_path(cfg.archive_dir)}, it has probably already been converted"
                )
                print_notice("Skipping this book because OVERWRITE_EXISTING is not enabled")
                return False
            elif book.size("converted", "bytes") > 0:
                print_notice(f"Output file already exists and OVERWRITE_EXISTING is not enabled, skipping this book")
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

    # If no books to convert, print, sleep, and exit
    if not inbox.num_books:  # replace 'books_count' with your variable
        return 0, lambda: smart_print(f"No books to convert, next check in {cfg.sleeptime_friendly}\n")

    if inbox.match_filter and not inbox.matched_books:
        return 0, lambda: smart_print(
            f"Found {pluralize_with_count(inbox.num_books, 'book')} in the inbox, but none match [[{inbox.match_filter}]]",
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
        note = wrap_brackets(f"ignoring {inbox.num_filtered}" if inbox.num_filtered else "")
        return 0, lambda: smart_print(
            f"Failed to convert {s} in the inbox matching [[{inbox.match_filter}]]{note}",
            highlight_color=AMBER_COLOR,
        )

    if inbox.match_filter and inbox.matched_ok_books:
        ignoring = f"ignoring {inbox.num_filtered}" if inbox.num_filtered else ""
        note = wrap_brackets(ignoring, skipping, sep=", ")
        unescaped_match_filter = re.sub(r"\\ ", " ", str(inbox.match_filter))
        return inbox.num_matched_ok, lambda: smart_print(
            f"Found {pluralize_with_count(inbox.num_matched, 'book')} in the inbox matching [[{unescaped_match_filter}]]{note}\n",
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
    inbox = InboxState()
    if book.tree.has_structure_like("series") or book.tree.has_structure_like("multi"):
        help_msg = f"Please organize the files in a single folder and rename them so they sort alphabetically\nin the correct order"
        if book.tree.has_structure_like("series"):
            inbox.set_ok(book)
        elif book.tree.has_structure("multi_disc"):
            if cfg.FLATTEN_MULTI_DISC_BOOKS:
                smart_print(
                    "\nThis folder appears to be a multi-disc book, attempting to flatten it...",
                    end="",
                )
                if flattening_files_in_dir_affects_order(book.inbox_dir):
                    nl(2)
                    print_error("Flattening this book would affect the file order, cannot proceed")
                    smart_print(f"{help_msg}\n")
                    fail_book(
                        book,
                        "This book appears to be a multi-disc book, but flattening it would affect the file order - it will need to be fixed manually by renaming the files so they sort alphabetically in the correct order",
                    )
                    return False
                else:
                    flatten_files_in_dir(book.inbox_dir)
                    book.rescan()
                    # book = Audiobook(book.inbox_dir)
                    print_mint(" ✓\n")
                    # files = "\n".join([str(f) for f in book.inbox_dir.glob("*")])
                    # print_debug(f"New file structure:\n{files}")
                    inbox.set_ok(book)
            else:
                print_error(f"{en.MULTI_ERR}, maybe this is a multi-disc book?")
                smart_print(
                    f"{help_msg}, or set FLATTEN_MULTI_DISC_BOOKS=Y to have auto-m4b flatten\nmulti-disc books automatically\n"
                )
                fail_book(book, f"{en.MULTI_ERR} (multi-disc book) - {help_msg}")
                return False
        elif book.tree.has_structure("multi_part"):
            print_error(f"{en.MULTI_ERR}, maybe this is a multi-part book or a series?")
            smart_print(f"{help_msg}\n")
            fail_book(book, f"{en.MULTI_ERR} (multi-part book) - {help_msg}")
            return False
        else:
            print_error(f"{en.MULTI_ERR}, cannot determine book structure")
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
    if not book.num_files("inbox"):
        print_notice(f"{book.inbox_dir} does not contain any known audio files, skipping")
        fail_book(book, "No audio files found in this folder")
        return False
    return True


def flatten_nested_book(book: Audiobook):
    if book.tree.has_structure("nested"):
        smart_print(
            f"Audio files for this book are a subfolder, moving them to the book's root folder...",
            end="",
        )
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

    starttime = time.time()
    m4btool = M4bTool(book)

    err: Literal[False] | str = False

    # if book is m4a or m4b, need to pre-extract cover art
    if book.orig_file_type in ["m4a", "m4b"]:
        book.extract_cover_art()

    cmd = m4btool.build_cmd()

    m4btool.print_msg()

    if cfg.DEBUG:
        print_dark_grey(m4btool.esc_cmd())

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.stderr:
        book.write_log(proc.stderr.decode())
        nl()
        raise RuntimeError(proc.stderr.decode())
    else:
        stdout = proc.stdout.decode()

    if cfg.DEBUG:
        smart_print(stdout)

    if re.search(r"error", stdout, re.I):
        # ignorable errors:
        ###################
        # an error occured, that has not been caught:
        # Array
        # (
        #     [type] => 8192
        #     [message] => Implicit conversion from float 9082109.64 to int loses precision
        #     [file] => phar:///usr/local/bin/m4b-tool/src/library/M4bTool/Parser/SilenceParser.php
        #     [line] => 61
        # )
        ###################
        # regex: an error occured[\s\S]*?Array[\s\S]*?Implicit conversion from float[\s\S]*?\)
        ###################

        err_blocks = [r"an error occured[\s\S]*?Array[\s\S]*?\)"]

        ignorable_errors = [
            r"failed to save key",
            r"implicit conversion from float",
            r"ffmpeg version .* or higher is .* likely to cause errors",
        ]

        # if any of the err_blocks do not match any of the ignorable errors, then it's a valid error
        err = (
            re_group(
                re.search(
                    rf"PHP (?:Warning|Fatal error):  ([\s\S]*?)Stack trace",
                    stdout,
                    re.I | re.M,
                ),
                1,
            )
            .replace("\n", "\n     ")
            .strip()
        )
        if not err:
            for block in [re_group(re.search(err, stdout, re.I)) for err in err_blocks]:
                if block and not any(re.search(err, block) for err in ignorable_errors):
                    err = re_group(re.search(rf"\[message\] => (.*$)", block, re.I | re.M), 1)
        print_error(f"m4b-tool Error: {err}")
        smart_print(f"See log file in {tint_light_grey(book.inbox_dir)} for details\n")
    elif not book.build_file.exists():
        print_error(f"Error: m4b-tool failed to convert [[{book}]], no output .m4b file was found")
        err = f"m4b-tool failed to convert {book}, no output .m4b file was found"

    if err:
        stderr = proc.stderr.decode() if proc.stderr else ""
        fail_book(book, reason=f"{err}\n{stderr}")
        log_global_results(book, "FAILED", 0)
        return False

    # TODO: No longer need to write successful logs
    # else:
    #     book.write_log(
    #         f"{endtime_log}  {book}  Converted in {log_format_elapsed_time(elapsedtime)}\n"
    #     )

    verify_and_update_id3_tags(book, in_dir="build")

    return int(time.time() - starttime)


def move_desc_file(book: Audiobook):
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
    print_moving_to_converted(book)

    # Copy other jpg, png, and txt files from mergefolder to output folder
    mv_dir_contents(
        book.merge_dir,
        book.converted_dir,
        only_file_exts=cfg.OTHER_EXTS,
        overwrite_mode="overwrite-silent",
    )

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
    if not parent or not parent.is_maybe_series_parent:
        print_debug(f"{parent} is not a series parent, can't move series extras or clean up")
        return

    print_book_series_header(parent, progress=False, done=True)

    parent_book = parent.to_audiobook()
    verb = "copy" if cfg.ON_COMPLETE == "test_do_nothing" else "move"
    # Move (or copy) series collateral to converted folder
    _mv_or_cp_dir_contents(
        verb,
        parent_book.inbox_dir,
        parent_book.converted_dir,
        only_file_exts=cfg.OTHER_EXTS,
        overwrite_mode="overwrite-silent",
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
    if cfg.ON_COMPLETE == "test_do_nothing":
        print_notice("Test mode: The original folder will not be moved or deleted")
    else:
        if cfg.ON_COMPLETE == "archive":
            smart_print("\nArchiving original from inbox...", end="")
            mv_dir_contents(
                book.inbox_dir,
                book.archive_dir,
                overwrite_mode="overwrite-silent",
            )

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


def process_book(b: int, item: InboxItem):

    inbox = InboxState()
    book = item.to_audiobook()
    print_book_header(item)

    if not item.path.exists():
        print_notice(f"This book was removed from the inbox or cannot be accessed, skipping")
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

    if book.is_a(("single", "standalone_file"), "m4b"):
        b += process_already_m4b(book, item)
        if item.is_gone:
            return b
    elif book.is_a("standalone_file", but_not="m4b"):
        book, item = move_standalone_into_dir(book, item)

    if not has_audio_files(book):
        return b

    if not can_process_multi_dir(book):
        return b

    if book.tree.has_structure("series_parent"):
        return b

    if not can_process_roman_numeral_book(book):
        return b

    flatten_nested_book(book)
    print_book_info(book)

    if not backup_ok(book):
        return b

    if not ok_to_overwrite(book):
        return b

    inbox.set_ok(book)

    copy_to_working_dir(book)

    book.extract_path_info()
    book.extract_metadata()

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
    inbox = InboxState()

    if inbox.loop_counter == 1:
        print_debug("First run, scanning inbox...")
        print_banner()
        inbox.scan(set_ready=True)

    if not audio_files_found():
        print_banner()
        print_debug(
            f"No audio files found in {cfg.inbox_dir}\n        Last updated at {inbox_last_updated_at(friendly=True)}, next check in {cfg.sleeptime_friendly}",
            only_once=True,
        )
        return
    if (
        # not inbox.inbox_needs_processing(on_will_scan=process_standalone_files)
        not inbox.inbox_needs_processing()
        and inbox.loop_counter > 1
    ):
        return
    elif info := books_to_process():
        _expected, msg = info
        # print_debug(f"Processing {expected} book(s)")
        print_banner(after=lambda: [x() for x in (nl, msg)])

    # process_standalone_files()

    inbox.start()

    b = 0
    for item in inbox.matched_ok_books.values():
        b = process_book(b, item)
        divider("\n", "\n")

        if item.is_maybe_series_book and item.is_last_book_in_series:
            cleanup_series_dir(item.series_parent)

    print_footer(b)
    clean_dirs([cfg.merge_dir, cfg.build_dir, cfg.trash_dir])
    inbox.done()
