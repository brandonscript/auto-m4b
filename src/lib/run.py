import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from tinta import Tinta

from src.lib.audiobook import Audiobook
from src.lib.config import AUDIO_EXTS, cfg
from src.lib.ffmpeg_utils import build_id3_tags_args
from src.lib.formatters import friendly_date, human_elapsed_time, log_date, pluralize
from src.lib.fs_utils import (
    clean_dir,
    count_audio_files_in_dir,
    cp_dir,
    cp_file_to_dir,
    dir_is_empty,
    find_base_dirs_with_audio_files,
    flatten_files_in_dir,
    is_ok_to_delete,
    mv_dir,
    mv_dir_contents,
    mv_file_to_dir,
    name_matches,
    rm_all_empty_dirs,
    was_recently_modified,
)
from src.lib.id3_utils import verify_and_update_id3_tags
from src.lib.logger import log_global_results
from src.lib.misc import BOOK_ASCII, dockerize_volume, re_group
from src.lib.parsers import count_distinct_roman_numerals, roman_numerals_affect_file_order
from src.lib.term import (
    AMBER_COLOR,
    DARK_GREY_COLOR,
    divider,
    fmt_linebreak_path,
    nl,
    print_aqua,
    print_dark_grey,
    print_debug,
    print_error,
    print_grey,
    print_list,
    print_notice,
    print_orange,
    print_warning,
    smart_print,
    tint_light_grey,
    tint_path,
    tint_warning,
    tinted_file,
    tinted_m4b,
)


def print_launch_and_set_running():
    if cfg.SLEEPTIME and not cfg.TEST:
        time.sleep(min(2, cfg.SLEEPTIME / 2))
    if not cfg.PID_FILE.is_file():
        cfg.PID_FILE.touch()
        current_local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with cfg.PID_FILE.open("a") as f:
            f.write(f"auto-m4b started at {current_local_time}, watching {cfg.inbox_dir}\n")
        print_aqua("\nStarting auto-m4b...")
        print_grey(f"{cfg.info_str}\n")


def process_standalone_files():
    """Move single audio files into their own folders"""

    # get all standalone audio files in inbox - i.e., audio files that are directl in the inbox not a subfolder
    standalone_audio_files = [
        file for ext in AUDIO_EXTS for file in cfg.inbox_dir.glob(f"*{ext}") if len(file.parts) == 1
    ]
    for audio_file in standalone_audio_files:
        # Extract base name without extension
        file_name = audio_file.name
        folder_name = audio_file.stem
        ext = audio_file.suffix

        # If the file is an m4b, we can send it straight to the output folder.
        # if a file of the same name exists, rename the incoming file to prevent data loss using (copy), (copy 1), (copy 2) etc.
        if ext == ".m4b":
            unique_target = cfg.converted_dir / file_name
            print("This book is already an m4b")
            print(f"Moving directly to converted books folder → {unique_target}")

            if unique_target.exists():
                print(
                    "(A file with the same name already exists in the output dir, this one will be renamed to prevent data loss)"
                )

                # using a loop, first try to rename the file to append (copy) to the end of the file name.
                # if that fails, try (copy 1), (copy 2) etc. until it succeeds
                i = 0
                # first try to rename to (copy)
                unique_target = cfg.converted_dir / f"{folder_name} (copy){ext}"
                while unique_target.exists():
                    i += 1
                    unique_target = cfg.converted_dir / f"{folder_name} (copy {i}){ext}"

            shutil.move(str(audio_file), str(unique_target))

            if unique_target.exists():
                print(f"Successfully moved to {unique_target}")
        else:
            print(f"Moving book into its own folder → {folder_name}/")
            new_folder = cfg.inbox_dir / folder_name
            new_folder.mkdir(exist_ok=True)
            shutil.move(str(audio_file), str(new_folder))


class m4btool:
    _cmd: list[Any]

    def __init__(self, book: Audiobook):
        def _(*new_arg: str | tuple[str, Any]):
            if isinstance(new_arg, tuple):
                self._cmd.extend(new_arg)
            else:
                self._cmd.append(new_arg)

        self.book = book
        self._cmd = cfg._m4b_tool + [
            "merge",
            dockerize_volume(book.merge_dir),
            "-n",
        ]

        _("--debug" if cfg.DEBUG == "Y" else "-q")

        if self.should_copy:
            _(("--audio-codec", "copy"))
        else:
            _((f"--audio-codec", "libfdk_aac"))
            _((f"--audio-bitrate", book.bitrate_target))
            _((f"--audio-samplerate", book.samplerate))

        _(("--jobs", cfg.CPU_CORES))
        _(("--output-file", dockerize_volume(book.build_file)))
        _(("--logfile", dockerize_volume(book.log_file)))
        _("--no-chapter-reindexing")

        if cfg.SKIP_COVERS:
            _("--no-cover-image")
        elif not book.has_id3_cover and book.cover_art:
            _(("--cover", dockerize_volume(book.cover_art)))

        if cfg.USE_FILENAMES_AS_CHAPTERS:
            _("--use-filenames-as-chapters")

        if chapters_files := list(dockerize_volume(self.book.merge_dir).glob("*chapters.txt")):
            chapters_file = chapters_files[0]
            _(f'--chapters-file="{chapters_file}"')
            smart_print(
                f"Found {len(chapters_files)} chapters {pluralize(len(chapters_files), 'file')}, setting chapters from {tinted_file(chapters_file.name)}"
            )

        _(*build_id3_tags_args(book.title, book.author, book.year, book.comment))

    def cmd(self, quotify: bool = False) -> list[str]:
        out = []
        for arg in self._cmd:
            if isinstance(arg, tuple):
                k, v = arg
                if quotify and " " in str(v):
                    v = f'"{v}"'
                out.append(f"{k}={v}")
            else:
                out.append(str(arg))
        return out

    def esc_cmd(self) -> str:
        cmd = self.cmd(quotify=True)
        if cfg.USE_DOCKER:
            cmd.insert(2, "-it")
        cmd = [c for c in cmd if c != "-q"]
        return " ".join(cmd)

    @property
    def should_copy(self):
        return self.book.orig_file_type in ["m4a", "m4b"]

    def msg(self):
        starttime_friendly = friendly_date()
        if self.should_copy:
            smart_print(
                f"Starting merge/passthrough → {tinted_m4b()} at {tint_light_grey(starttime_friendly)}..."
            )
        else:
            smart_print(
                f"Starting {tinted_file(self.book.orig_file_type)} → {tinted_m4b()} conversion at {tint_light_grey(starttime_friendly)}..."
            )


# glasses 1: ⌐◒-◒
# glasses 2: ᒡ◯ᴖ◯ᒢ

def banner(verb: str = "Checking"):
    current_local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    dash = "-" * 24

    print_aqua(f"{dash}  ⌐◒-◒  auto-m4b • {current_local_time}  -{dash}")

    print_grey(f"{verb} for new books in {{{{{cfg.inbox_dir}}}}} ꨄ︎")

def process_inbox(first_run: bool = False, failed_books: list[Path] = [], last_touched: float = 0):
    audiobooks_count = count_audio_files_in_dir(cfg.inbox_dir, only_file_exts=AUDIO_EXTS)

    if audiobooks_count == 0:
        if first_run:
            banner("Watching")
            nl()
        return

    # compare last_touched to inbox dir's mtime - if inbox dir has not been modified since last run, skip
    if last_touched and last_touched == cfg.inbox_dir.stat().st_mtime:
        return

    banner()

    if was_recently_modified(cfg.inbox_dir):  # replace 'unfinished_dirs' with your variable
        smart_print(
            "The inbox folder was recently modified, waiting in case files are being copied...\n"
        )
        return

    standalone_count = count_audio_files_in_dir(cfg.inbox_dir, maxdepth=0)
    if standalone_count:
        process_standalone_files()

    # Find directories containing audio files, handling single quote if present
    audio_dirs = find_base_dirs_with_audio_files(cfg.inbox_dir, mindepth=1)
    real_books_count = len(audio_dirs)
    books_count = real_books_count

    if cfg.MATCH_NAME:
        audio_dirs = [d for d in audio_dirs if name_matches(d, cfg.MATCH_NAME)]
        books_count = len(audio_dirs)

    if failed_books:
        audio_dirs = [d for d in audio_dirs if d not in failed_books]
        books_count = len(audio_dirs)

    # If no books to convert, print, sleep, and exit
    if real_books_count == 0:  # replace 'books_count' with your variable
        smart_print(f"No books to convert, next check in {cfg.sleeptime_friendly}\n")
        return
    elif books_count == 0:
        filtered_count = real_books_count - books_count
        if cfg.MATCH_NAME:
            print_notice(
                f"Found {filtered_count} {pluralize(filtered_count, 'book')}, but none match '{cfg.MATCH_NAME}' – next check in {cfg.sleeptime_friendly}"
            )
        return

    elif books_count != real_books_count:
        smart_print(
            f"Found {books_count} of {real_books_count} {pluralize(real_books_count, 'book')} in inbox matching [[{cfg.MATCH_NAME}]]\n",
            highlight_color=AMBER_COLOR,
        )
    else:
        smart_print(f"Found {books_count} {pluralize(books_count, 'book')} to convert\n")

    for b, book_full_path in enumerate(audio_dirs):
        book = Audiobook(book_full_path)
        book.log_file.unlink(missing_ok=True)

        m4b_count = count_audio_files_in_dir(book.inbox_dir, only_file_exts=["m4b"])
        root_only_audio_files_count = count_audio_files_in_dir(
            book.inbox_dir, only_file_exts=AUDIO_EXTS, maxdepth=1
        )

        vline = "|"
        hline = "-"
        tl = "•"
        tr = "•"
        bl = "•"
        br = "•"

        border = lambda l, r: smart_print(
            l + hline * (len(book.basename) + 2) + r, color=DARK_GREY_COLOR
        )

        border(tl, tr)
        smart_print(Tinta().dark_grey(vline).aqua(book.basename).dark_grey(vline).to_str())
        border(bl, br)

        nested_audio_dirs = find_base_dirs_with_audio_files(book.inbox_dir, mindepth=1)
        nested_audio_dirs_count = len(nested_audio_dirs)
        roman_numerals_count = count_distinct_roman_numerals(book.inbox_dir)

        # check if the current dir was modified in the last 1m and skip if so
        if was_recently_modified(book.inbox_dir):
            print_notice("Skipping this book, it was recently updated and may still be copying")
            continue

        if not book.num_files("inbox"):
            print_error(f"Error: {book.inbox_dir} does not contain any known audio files, skipping")
            book.write_log("No audio files found in this folder")
            failed_books.append(book.inbox_dir)
            continue

        if m4b_count == 1:
            smart_print("This book is already an m4b")
            smart_print(f"Moving directly to converted books folder → {book.converted_dir}")
            mv_dir_contents(book.inbox_dir, book.converted_dir)
            continue

        # Check if a copy of this book is in fix_dir and bail
        if (cfg.fix_dir / book.basename).exists():
            print_error(
                "Error: A copy of this book is in the fix folder, please fix it and try again"
            )
            failed_books.append(book.inbox_dir)
            continue

        def mv_to_fix_dir():
            failed_books.append(book.inbox_dir)
            if cfg.NO_FIX:
                # cp_file_to_dir(book.log_file, book.inbox_dir, new_filename=f"m4b-tool.{book}.log", overwrite_mode="overwrite-silent")
                # book.set_active_dir("inbox")
                book.write_log("(This book would have been moved to fix folder, but NO_FIX is enabled)")
                return
            smart_print(f"Moving to fix folder → {tint_path(book.fix_dir)}")
            mv_dir(book.inbox_dir, cfg.fix_dir)
            cp_file_to_dir(book.log_file, book.fix_dir, new_filename=f"m4b-tool.{book}.log")
            book.set_active_dir("fix")

        needs_fixing = False
        if nested_audio_dirs_count > 1 or (
            nested_audio_dirs_count == 1 and root_only_audio_files_count > 0
        ):
            needs_fixing = True
            print_error("Error: This book contains multiple folders with audio files")
            smart_print("Maybe this is a multi-disc book, or maybe it is multiple books?")
            smart_print(
                "All files must be in a single folder, named alphabetically in the correct order\n"
            )
            book.write_log("This book contains multiple folders with audio files - maybe it is a multi-disc book,", "or maybe it is multiple books? All files must be in a single folder,", "named alphabetically in the correct order.")

        if roman_numerals_count > 1:
            if roman_numerals_affect_file_order(book.inbox_dir):
                print_error("Error: Some of this book's files appear to be named with roman numerals")
                smart_print(
                    "Roman numerals do not sort in alphabetical order; please make sure files are named alphabetically in the correct order.\n"
                )
                book.write_log("Some of this book's files appear to be named with roman numerals. Roman numerals do not sort in alphabetical order; please make sure files are named alphabetically in the correct order.")
                needs_fixing = True
            else:
                print_debug(
                    f"Found {roman_numerals_count} roman numerals in {book.basename}, but they don't affect file order"
                )

        if needs_fixing:
            mv_to_fix_dir()
            continue

        if nested_audio_dirs_count == 1:
            smart_print(
                f"Audio files for this book are a subfolder: {tint_path(f"./{nested_audio_dirs[0]}")}"
            )
            smart_print(f"Moving them to book's root → {tint_path(book.inbox_dir)}")
            flatten_files_in_dir(book.inbox_dir)

        smart_print("\nFile/folder info:")

        print_list(f"Output folder: {book.converted_dir}")
        print_list(f"File type: {book.orig_file_type}")
        print_list(f"Audio files: {book.num_files("inbox")}")
        print_list(f"Total size: {book.size("inbox", "human")}")
        if book.cover_art:
            print_list(f"Cover art: {book.cover_art.name}")

        nl()

        # Copy files to backup destination
        if not cfg.MAKE_BACKUP:
            print_dark_grey("Not backing up (backups are disabled)")
        elif dir_is_empty(book.inbox_dir):
            print_dark_grey("Skipping backup (folder is empty)")
        else:
            smart_print(f"Making a backup copy → {tint_path(book.backup_dir)}")
            cp_dir(book.inbox_dir, cfg.backup_dir, overwrite_mode="skip-silent")

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
            size_fuzzy_matches = abs(orig_size_b - backup_size_b) < 1000

            expected = f"{orig_files_count} {orig_plural} ({orig_size_human})"
            found = f"{backup_files_count} {backup_plural} ({backup_size_human})"

            if file_count_matches and size_matches:
                print_grey(
                    f"Backup successful - {backup_files_count} {orig_plural} ({backup_size_human})"
                )
            elif orig_files_count < backup_files_count or orig_size_b < backup_size_b:
                print_grey(
                    f"Backup successful, but extra data found in backup dir - expected {expected}, found {found}"
                )
                print_grey("Assuming this is a previous backup and continuing")
            elif file_count_matches and size_fuzzy_matches:
                print_grey(
                    f"Backup successful, but sizes aren't exactly the same - expected {expected}, found {found}"
                )
                print_grey("Assuming this is a previous backup and continuing")
            else:
                print_error(
                    f"Backup failed - expected {expected}, found {found}"
                )
                smart_print("Skipping this book\n")
                continue

        if book.converted_file.is_file():
            if cfg.OVERWRITE_MODE == "skip":
                if book.archive_dir.exists():
                    print_notice(
                        f"Found a copy of this book in {tint_path(cfg.archive_dir)}, it has probably already been converted"
                    )
                    print_notice("Skipping this book because OVERWRITE_EXISTING is not enabled")
                    continue
                elif book.size("converted", "bytes") > 0:
                    print_notice(
                        f"Output file already exists and OVERWRITE_EXISTING is not enabled, skipping this book"
                    )
                    continue
            else:
                print_warning(
                    "Warning: Output file already exists, it and any other {{.m4b}} files will be overwritten"
                )

        # Move from inbox to merge folder
        smart_print("\nCopying files to working folder...", end="")
        cp_dir(book.inbox_dir, cfg.merge_dir, overwrite_mode="overwrite-silent")
        print_aqua(f" ✓\n")

        book.extract_path_info()
        book.extract_metadata()

        # Pre-create tempdir for m4b-tool in "$buildfolder$book-tmpfiles" and ensure writable
        clean_dir(book.build_dir)
        clean_dir(book.build_tmp_dir)
        rm_all_empty_dirs(cfg.merge_dir)

        book.set_active_dir("build")

        starttime = time.time()

        m4b_tool = m4btool(book)

        nl()

        book.write_description_txt()

        err: Literal[False] | str = False

        cmd = m4b_tool.cmd()

        m4b_tool.msg()

        if cfg.DEBUG:
            print_dark_grey(m4b_tool.esc_cmd())

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.stderr:
            nl()
            raise RuntimeError(proc.stderr.decode())
        else:
            stdout = proc.stdout.decode()

        if cfg.DEBUG:
            smart_print(stdout)
        # if proc.returncode != 0 or proc.stderr:
        # print_error(f"m4b-tool failed to convert {book}")
        # raise RuntimeError(
        #     f"{proc.stderr.decode()}"
        #     if proc.stderr
        #     else f"m4b-tool failed to convert {book}"
        # )

        # print_error "Error: [TEST] m4b-tool failed to convert \"$book\""
        # print "     Moving \"$book\" to fix folder..."
        # mv_dir "$mergefolder$book" "$fix_dir"
        # cp "$logfile" "$fix_dir$book/m4b-tool.$book.log"
        # log_results "$book_full_path" "FAILED" ""
        # break

        endtime_log = log_date()
        # endtime_friendly = friendly_date()
        elapsedtime = int(time.time() - starttime)
        elapsedtime_friendly = human_elapsed_time(elapsedtime)

        # with open(book.log_file, "r") as f:
        #     logfile = f.read()

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

            # ignorable errors:
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
            smart_print(f"See log file in {tint_light_grey(book.fix_dir)} for details\n")
        elif not book.build_file.exists():
            print_error(
                f"Error: m4b-tool failed to convert {{{{{book}}}}}, no output .m4b file was found"
            )
            err = "No output file found, conversion or copying probably failed, but no error was reported"

        if err:
            mv_to_fix_dir()
            stderr = proc.stderr.decode() if proc.stderr else ""
            book.write_log(f"{err}\n{stderr}")
            log_global_results(book, "FAILED", "-")
            continue
        else:
            book.write_log(f"{endtime_log}  {book}  Converted in {elapsedtime_friendly}\n")

        # create converted dir
        book.converted_dir.mkdir(parents=True, exist_ok=True)

        # m4b_num_parts=1 # hardcode for now, until we know if we need to split parts

        # Remove old description files from current dir, $buildfolder$book and $mergefolder$book
        did_remove_old_desc = False
        for d in [book.build_dir, book.merge_dir, book.converted_dir]:
            desc_files = list(Path(d).rglob(f"{book} [*kHz*].txt"))
            for f in desc_files:
                f.unlink()
                did_remove_old_desc = True

        if did_remove_old_desc:
            print_notice(f"Removed old description {pluralize(len(desc_files), "file")}")

        mv_file_to_dir(
            book.merge_desc_file,
            book.final_desc_file.parent,
            new_filename=book.final_desc_file.name,
            overwrite_mode="overwrite-silent",
        )

        log_global_results(book, "SUCCESS", elapsedtime)

        # TODO: Only handles single m4b output file, not multiple files.
        verify_and_update_id3_tags(book, "build")

        nl()

        smart_print(
            f"Moving to converted books folder → {tint_path(fmt_linebreak_path(book.converted_file, 80, 35))}"
        )

        # Copy other jpg, png, and txt files from mergefolder to output folder
        mv_dir_contents(
            book.merge_dir,
            book.converted_dir,
            only_file_exts=cfg.OTHER_EXTS,
            overwrite_mode="overwrite-silent",
        )

        # Copy log file to output folder as $buildfolder$book/m4b-tool.$book.log
        mv_file_to_dir(
            book.log_file,
            book.converted_dir,
            new_filename=f"m4b-tool.{book}.log",
            overwrite_mode="overwrite-silent",
        )
        book.set_active_dir("converted")

        rm_all_empty_dirs(book.build_dir)

        # Move all built audio files to output folder
        mv_dir_contents(
            book.build_dir,
            book.converted_dir,
            only_file_exts=AUDIO_EXTS,
            silent_files=[book.build_file.name],
        )

        if not book.converted_file.is_file():
            print_error(
                f"Error: The output file does not exist, something went wrong during the conversion\n     Expected it to be at {book.converted_file}"
            )
            mv_to_fix_dir()
            continue

        # Remove description.txt from output folder if "$book [$desc_quality].txt" exists
        if book.final_desc_file.is_file():
            (book.converted_dir / "description.txt").unlink(missing_ok=True)
        else:
            print_notice(
                "The description.txt is missing (reason unknown), trying to save a new one"
            )
            book.write_description_txt(book.final_desc_file)

        # Remove temp copies in build and merge if it's still there
        shutil.rmtree(book.build_dir, ignore_errors=True)
        shutil.rmtree(book.merge_dir, ignore_errors=True)

        if cfg.on_complete == "move":
            smart_print("Archiving original from inbox...")
            mv_dir_contents(book.inbox_dir, book.archive_dir, overwrite_mode="overwrite-silent")

            if book.inbox_dir.exists():
                print_warning(
                    f"Warning: {tint_warning(book)} is still in the inbox folder, it should have been archived"
                )
                print_orange(
                    "     To prevent this book from being converted again, move it out of the inbox folder"
                )

        elif cfg.on_complete == "delete":
            smart_print("Deleting original from inbox...")
            if is_ok_to_delete(book.inbox_dir):
                shutil.rmtree(book.inbox_dir, ignore_errors=True)
            else:
                print_notice("Notice: The original folder is not empty, it will not be deleted")
        elif cfg.on_complete == "test_do_nothing":
            print_notice("Test mode: The original folder will not be moved or deleted")

        smart_print(
            Tinta("\nConverted")
            .aqua(book.basename)
            .clear(f"in {elapsedtime_friendly} 🐾✨🥞")
            .to_str()
        )

        divider("\n")
        if b < books_count - 1:
            nl()

    # clear the folders
    clean_dir(cfg.merge_dir)
    clean_dir(cfg.build_dir)
    clean_dir(cfg.trash_dir)

    # Delete all *-tmpfiles dirs inside $outputfolder
    # Shouldn't be required if the clean_dir methods work
    # for d in list(book.build_dir.rglob("*-tmpfiles")) + list(
    #     book.converted_dir.rglob("*-tmpfiles")
    # ):
    #     if d.is_dir() and len(list(d.parents)) <= 2:
    #         shutil.rmtree(d, ignore_errors=True)

    if books_count >= 1:
        print_grey(
            f"Finished converting all available books, next check in {cfg.sleeptime_friendly}"
        )
        if not cfg.NO_ASCII:
            print_dark_grey(BOOK_ASCII)
    else:
        print_dark_grey(f"Next check in {cfg.sleeptime_friendly}")

    divider()
    nl()


