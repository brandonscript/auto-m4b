import re
from pathlib import Path

import pytest

from src.auto_m4b import app
from src.lib.audiobook import Audiobook
from src.lib.logger import log_global_results
from src.tests.conftest import TEST_DIRS

FIRST_LINE = (
    r"2023-10-21 22:37:37-0700\s{2,}"
    r"SUCCESS\s{2,}"
    r"Stephen Hawking - A Brief History of Time\s{2,}"
    r"67 kb/s\s{2,}"
    r"44.1 kHz\s{2,}"
    r"\.mp3\s{2,}"
    r"\d+ files?\s{2,}"
    r"80M\s{2,}"
    r"-\s{2,}"
    r"0:35"
)

LAST_LINE_MATCH_TOWER = (
    r"^.*?-\d{4}\s{2,}"
    r"SUCCESS\s{2,}"
    r"tower_treasure__flat_mp3\s{2,}"
    r"64 kb/s\s{2,}"
    r"22 kHz\s{2,}"
    r"\.mp3\s{2,}"
    r"\d+ files?\s{2,}"
    r"\d+ MB\s{2,}"
    r"0h:\d+m:\d+s\s{2,}"
    r"02:43"
)

LAST_LINE_MATCH_CONSPIRACY = (
    r"^.*?-\d{4}\s{2,}"
    r"SUCCESS\s{2,}"
    r"The Great Courses - Conspiracies & Conspiracy Theories What We Should\s{2,}"
    r"128 kb/s\s{2,}"
    r"44.1 kHz\s{2,}"
    r"\.mp3\s{2,}"
    r"\d+ files?\s{2,}"
    r"\d+ MB\s{2,}"
    r"0h:\d+m:\d+s\s{2,}"
    r"02:43"
)


def check(test_log: Path, expect_last_lines: list[str]):
    global FIRST_LINE
    with open(test_log, "r") as f:
        lines = f.readlines()
        header_line = lines[0]
        blank_line = True if lines[1].strip() == "" else False
        first_line = lines[2] if blank_line else lines[1]
        last_lines = lines[-len(expect_last_lines) :]

        assert list(map(str.strip, header_line.split())) == [
            "Date",
            "Result",
            "Original",
            "Folder",
            "Bitrate",
            "Sample",
            "Rate",
            "Type",
            "Files",
            "Size",
            "Duration",
            "Time",
        ]

        assert re.match(FIRST_LINE, first_line)

        # check that the last line of the log is the expected result
        for last_line, expect_last_line in zip(last_lines, expect_last_lines):
            assert last_line.startswith("20")
            assert (
                True
                if re.match(expect_last_line, last_line)
                else pytest.fail(f"\nExpected: {expect_last_line}\nGot: {last_line}")
            )


def check_ground_truth(test_log: Path):
    check(
        test_log,
        [
            r"2023-11-09 22:49:46-0800\s{2,}SUCCESS\s{2,}Say What You Mean A Mindful Approach to Nonviolent Communication by Or\s{2,}64 kb/s      44.1 kHz\s{2,}\.mp3\s{2,}\d+ files?\s{2,}\d+M\s{2,}11h:00m:11s\s{2,}01:40"
        ],
    )


def test_load_existing_log(tower_treasure__flat_mp3: Audiobook, global_test_log: Path):
    check_ground_truth(global_test_log)

    log_global_results(tower_treasure__flat_mp3, "success", 163, global_test_log)
    assert global_test_log.exists()
    check(
        global_test_log,
        [LAST_LINE_MATCH_TOWER],
    )


def test_repeat_success_writes_to_log(tower_treasure__flat_mp3: Audiobook, global_test_log: Path):
    check_ground_truth(global_test_log)

    log_global_results(tower_treasure__flat_mp3, "success", 163, global_test_log)
    assert global_test_log.exists()
    check(
        global_test_log,
        [LAST_LINE_MATCH_TOWER],
    )

    log_global_results(tower_treasure__flat_mp3, "success", 163, global_test_log)
    assert global_test_log.exists()
    check(
        global_test_log,
        [LAST_LINE_MATCH_TOWER, LAST_LINE_MATCH_TOWER],  # line should be repeated
    )


def test_repeat_failed_writes_to_log(tower_treasure__flat_mp3: Audiobook, global_test_log: Path):
    check_ground_truth(global_test_log)

    orig_duration = tower_treasure__flat_mp3.duration
    orig_size = tower_treasure__flat_mp3.size
    tower_treasure__flat_mp3.__dict__["duration"] = lambda *args, **kwargs: ""
    tower_treasure__flat_mp3.__dict__["size"] = lambda *args, **kwargs: "1.25 GB"
    log_global_results(tower_treasure__flat_mp3, "failed", 0, global_test_log)
    assert global_test_log.exists()
    check(
        global_test_log,
        [
            r"^.*?-\d{4}\s{2,}FAILED\s{2,}tower_treasure__flat_mp3\s{2,}64 kb/s\s{2,}22 kHz\s{2,}\.mp3\s{2,}\d+ files?\s{2,}[\d.]+ GB\s{2,}-"
        ],
    )

    tower_treasure__flat_mp3.__dict__["duration"] = orig_duration
    tower_treasure__flat_mp3.__dict__["size"] = orig_size
    log_global_results(tower_treasure__flat_mp3, "success", 163, global_test_log)
    assert global_test_log.exists()
    check(
        global_test_log,
        [
            r"^.*?-\d{4}\s{2,}FAILED\s{2,}tower_treasure__flat_mp3\s{2,}64 kb/s\s{2,}22 kHz\s{2,}\.mp3\s{2,}\d+ files?\s{2,}[\d.]+ GB\s{2,}-\s{2,}-",
            LAST_LINE_MATCH_TOWER,
        ],
    )


def test_write_long_title_to_log(conspiracy_theories__flat_mp3: Audiobook, global_test_log: Path):
    check_ground_truth(global_test_log)

    log_global_results(conspiracy_theories__flat_mp3, "success", 163, global_test_log)
    assert global_test_log.exists()
    check(
        global_test_log,
        [LAST_LINE_MATCH_CONSPIRACY],
    )

    log_global_results(conspiracy_theories__flat_mp3, "success", 163, global_test_log)
    assert global_test_log.exists()
    check(
        global_test_log,
        [
            LAST_LINE_MATCH_CONSPIRACY,
            LAST_LINE_MATCH_CONSPIRACY,
        ],  # line should be repeated
    )


def test_log_supports_vbr_mp3s(bitrate_vbr__mp3: Audiobook, global_test_log: Path):
    check_ground_truth(global_test_log)

    log_global_results(bitrate_vbr__mp3, "success", 163, global_test_log)
    assert global_test_log.exists()
    check(
        global_test_log,
        [
            r"^.*?-\d{4}  SUCCESS  bitrate_vbr__mp3 \s* ~46 kb/s       22 kHz   .mp3 \s* \d+ files?  11 MB \s* 0h:33m:07s  02:43",
        ],
    )


def test_logs_m4b_tool_failures(corrupt_audiobook: Audiobook, global_test_log: Path):

    log_file = TEST_DIRS.inbox / "corrupt_audiobook" / corrupt_audiobook.log_filename
    log_file.unlink(missing_ok=True)
    app(max_loops=1, test=True)
    assert global_test_log.exists()
    assert log_file.exists()
    sample_audio = corrupt_audiobook.sample_audio1
    assert sample_audio.exists()
    ffprobe_log = corrupt_audiobook.sample_audio1.with_suffix(".ffprobe-error.txt")
    assert ffprobe_log.exists()
