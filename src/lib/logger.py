import re
import traceback
from pathlib import Path
from typing import Any

from columnar import columnar

from src.lib.audiobook import Audiobook
from src.lib.books_tree import BooksTree
from src.lib.config import cfg
from src.lib.formatters import log_date, log_format_elapsed_time, pluralize
from src.lib.misc import re_group
from src.lib.term import multiline_is_empty

LOG_HEADERS = [
    "Date",
    "Result",
    "Original Folder",
    "Bitrate",
    "Sample Rate",
    "Type",
    "Files",
    "Size",
    "Duration",
    "Time",
]
LOG_JUSTIFY = ["l", "l", "l", "r", "r", "r", "r", "r", "r", "r"]
log_pattern = re.compile(
    r"(?P<date>^\d.*?)\s*(?P<result>SUCCESS|FAILED|UNKNOWN)\s*(?P<book_name>.+?(?=\d{1,3} kb/s|\d{2}\.\d kHz))\s*(?P<bitrate>~?\d+ kb/s)?\s*(?P<samplerate>[\d.]+ kHz)?\s*(?P<file_type>\.\w+)?\s*(?P<num_files>\d+ files?)?\s*(?P<size>[\d.]+\s*[bBkKMGi]+)?\s*(?P<duration>[\dhms:-]*)?\s*(?P<elapsed>\S+)?"
)
# TEST:
# 2023-10-22 18:37:58-0700   FAILED    The Law of Attraction by Esther and Jerry Hicks    129 kb/s      44.1 kHz   .wma    85 files   336M         -


def log_global_results(
    book: Audiobook,
    result: str,
    elapsed_s: int | float,
    log_file: Path | None = None,
) -> None:
    # note: requires `column` version 2.39 or higher, available in util-linux 2.39 or higher

    # takes the original book's path and the result of the book and logs to outputfolder/auto-m4b.log
    # format: [date] [time] [original book relative path] [info] ["result"=success|failed] [failure-message]
    # pad the relative path with spaces to 70 characters and truncate to 70 characters
    # sanitize book_src to remove multiple spaces and replace | with _

    # get current log data and load it into columns - split by tabs or spaces >= 2

    human_elapsed = log_format_elapsed_time(elapsed_s)

    if not log_file:
        log_file = cfg.GLOBAL_LOG_FILE

    log_data: list[list[str]] = []
    log_file.touch(exist_ok=True)
    with open(log_file, "r") as f:
        for line in f:
            if line.startswith("Date ") or multiline_is_empty(line):
                continue
            cells = re.sub(r"\s{2,}", "\t", line).strip().split("\t")

            if len(cells) == 10:
                if not cells[1].lower() in ["success", "failed"]:
                    cells[1] = "UNKNOWN"
                log_data.append(cells)
            else:
                # book name probably got goofed, we need to regex it out
                parsed = log_pattern.search(line.strip())
                if parsed:
                    log_data.append(
                        [
                            re_group(parsed, "date", default=""),
                            re_group(parsed, "result", default=""),
                            re_group(parsed, "book_name", default="").strip(),
                            re_group(parsed, "bitrate", default=""),
                            re_group(parsed, "samplerate", default=""),
                            re_group(parsed, "file_type", default=""),
                            re_group(parsed, "num_files", default=""),
                            re_group(parsed, "size", default=""),
                            re_group(parsed, "duration", default="-"),
                            re_group(parsed, "elapsed", default="-"),
                        ]
                    )
                else:
                    raise ValueError(f"Couldn't parse log row: '{line}'\nin file: {log_file}")

    num_cols = len(LOG_HEADERS)

    # ensure all rows in log_data have 10 columns
    for row in log_data:
        if len(row) < num_cols:
            row.extend([""] * (num_cols - len(row)))
        elif len(row) > num_cols:
            raise ValueError(f"Row has too many columns for log: {row}")

    # remove 2+ spaces from book_name
    book_name = " ".join(book.basename.split())

    # pad result with spaces to 9 characters
    # result = f"{result:<10}"

    # # strip all chars from elapsed that are not number or :
    # human_elapsed = "".join(c for c in str(human_elapsed) if c.isdigit() or c == ":")

    # Read the current auto-m4b.log file and replace all double spaces with |
    # with open(log_file, "r") as f:
    #     log = f.read().replace("  ", "\t")

    # Remove each line from log if it starts with ^Date\s+
    # log = "\n".join(line for line in log.splitlines() if not line.startswith("Date "))

    # Remove blank lines from end of log file
    # log = log.rstrip("\n")

    log_data.append(
        [
            log_date(),
            result.upper(),
            book_name,
            book.bitrate_friendly,
            book.samplerate_friendly,
            f".{(book.orig_file_type or "N/A").replace('.', '')}",
            f"{book.num_files('inbox')} {pluralize(book.num_files('inbox'), "file")}",
            book.size("inbox", "human"),
            book.duration("inbox", "human") or "-",
            human_elapsed or "",
        ]
    )

    table = columnar(
        log_data,
        headers=LOG_HEADERS,
        terminal_width=1000,
        preformatted_headers=True,
        no_borders=True,
        max_column_width=70,
        justify=LOG_JUSTIFY,
        wrap_max=0,  # don't wrap
    )

    table_cleaned = []

    for line in table.splitlines()[1:]:
        table_cleaned.append(line.strip())

    # remove empty first line of table, and edge whitespace
    table = "\n".join(table_cleaned)

    # replace the log file
    with open(log_file, "w") as f:
        # ensure newline at end of file
        f.write(table)


def get_log_entry(book_src: Path, log_file: Path | None = None) -> str:
    # looks in the log file to see if this book has been converted before and returns the log entry or ""
    if not log_file:
        log_file = cfg.GLOBAL_LOG_FILE
    book_name = book_src.name
    with open(log_file, "r") as f:
        log_entry = next((line for line in f if book_name in line), "")
    return log_entry


def write_err_file(file: "BooksTree | Path", e: Any, component: str, stderr: str | None = None) -> None:
    path = file.path if isinstance(file, BooksTree) else file
    err_file = path.with_suffix(f".{component}-error.txt")
    err_file.touch(exist_ok=True)
    with open(err_file, "a") as f:
        full_stack = traceback.format_exc()
        stderr = f"\n\n{stderr}" if stderr else ""
        f.write(f"{full_stack}\n{str(e)}{stderr}")
