from dataclasses import dataclass

from src.lib.misc import get_git_root, isorted

GIT_ROOT = get_git_root()
SRC_ROOT = GIT_ROOT / "src"
TESTS_ROOT = SRC_ROOT / "tests"
TESTS_TMP_ROOT = TESTS_ROOT / "tmp"
FIXTURES_ROOT = TESTS_ROOT / "fixtures"


@dataclass
class TEST_DIRS:

    inbox = TESTS_TMP_ROOT / "inbox"
    converted = TESTS_TMP_ROOT / "converted"
    archive = TESTS_TMP_ROOT / "archive"
    fix = TESTS_TMP_ROOT / "fix"
    backup = TESTS_TMP_ROOT / "backup"
    working = TESTS_TMP_ROOT / "working"
    fixtures = FIXTURES_ROOT


_series_parent_dir = TEST_DIRS.inbox / "mock_book_series_parent"


@dataclass
class MOCKED:

    flat_dir1 = TEST_DIRS.inbox / "mock_book_1"
    flat_dir2 = TEST_DIRS.inbox / "mock_book_2"
    flat_dir3 = TEST_DIRS.inbox / "mock_book_3"
    flat_dir4 = TEST_DIRS.inbox / "mock_book_4"
    flat_dirs = [flat_dir1, flat_dir2, flat_dir3, flat_dir4]

    mixed_dir = TEST_DIRS.inbox / "mock_book_mixed"

    flat_nested_dir = TEST_DIRS.inbox / "mock_book_flat_nested"
    series_books = [
        _series_parent_dir / "Dawn - Book 1",
        _series_parent_dir / "Dusk - Book 3",
        _series_parent_dir / "High Noon - Book 2",
    ]
    series_parent_dir = _series_parent_dir
    multi_disc_dir = TEST_DIRS.inbox / "mock_book_multi_disc"
    multi_disc_dir_with_extras = TEST_DIRS.inbox / "mock_book_multi_disc_dir_with_extras"
    multi_part_dir = TEST_DIRS.inbox / "mock_book_multi_part"
    multi_nested_dir = TEST_DIRS.inbox / "mock_book_multi_nested"

    single_dir_mp3 = TEST_DIRS.inbox / "mock_book_single_mp3"
    single_nested_dir_mp3 = TEST_DIRS.inbox / "mock_book_single_nested_mp3"
    single_dir_m4b = TEST_DIRS.inbox / "mock_book_single_m4b"

    multi_dirs = [
        flat_nested_dir,
        series_parent_dir,
        multi_disc_dir,
        multi_disc_dir_with_extras,
        multi_nested_dir,
        multi_part_dir,
    ]
    single_dirs = [single_dir_mp3, single_nested_dir_mp3, single_dir_m4b]
    series_dirs = [series_parent_dir, *series_books]

    all_dirs_no_series = isorted(flat_dirs + [mixed_dir] + multi_dirs + single_dirs)

    all_dirs = isorted(flat_dirs + [mixed_dir] + multi_dirs + series_dirs[1:] + single_dirs)

    all_book_dirs = [d for d in all_dirs if not d == _series_parent_dir]

    standalone_m4b = TEST_DIRS.inbox / "mock_book_standalone_file.m4b"
    standalone_mp3_1 = TEST_DIRS.inbox / "mock_book_standalone_file_a.mp3"
    standalone_mp3_2 = TEST_DIRS.inbox / "mock_book_standalone_file_b.mp3"

    standalone_files = [
        standalone_m4b,
        standalone_mp3_1,
        standalone_mp3_2,
    ]

    empty = TEST_DIRS.inbox / "mock_book_empty"

    all_ = all_dirs + single_dirs


mock_book_mixed_full = {
    "mock_book_mixed": {
        "_files": [
            "mock_book_mixed, a book apart.mp3",
            "mock_book_mixed, a tale of whoa.mp3",
        ],
        "_dirs": {
            "nested": {
                "_files": [
                    "mock_book_mixed - part_42.mp3",
                    "mock_book_mixed, random file no. 7.mp3",
                ],
                "_dirs": {},
            }
        },
    }
}

mock_book_mixed_0_1 = {
    "mock_book_mixed": {
        "_files": mock_book_mixed_full["mock_book_mixed"]["_files"],
        "_dirs": {},
    }
}

mock_book_mixed_1_1 = {**mock_book_mixed_0_1}

mock_book_mixed_1_2 = {
    "mock_book_mixed": {
        "_files": mock_book_mixed_full["mock_book_mixed"]["_files"],
        "_dirs": {
            **mock_book_mixed_full["mock_book_mixed"]["_dirs"],
        },
    }
}
mock_book_mixed_2_2 = {
    "mock_book_mixed": {
        "_files": [],
        "_dirs": {
            **mock_book_mixed_full["mock_book_mixed"]["_dirs"],
        },
    }
}


# fmt: off
TREES = {
    "None, None": 
        {"_files": [f.name for f in MOCKED.standalone_files], "_dirs": {"mock_book_1": {"_files": ["mock_book_1 - part_1.mp3", "mock_book_1 - part_2.mp3", "mock_book_1 - part_3.mp3"], "_dirs": {}}, "mock_book_2": {"_files": ["mock_book_2 - part_1.mp3", "mock_book_2 - part_2.mp3", "mock_book_2 - part_3.mp3"], "_dirs": {}}, "mock_book_3": {"_files": ["mock_book_3 - part_1.mp3", "mock_book_3 - part_2.mp3", "mock_book_3 - part_3.mp3"], "_dirs": {}}, "mock_book_4": {"_files": ["mock_book_4 - part_1.mp3", "mock_book_4 - part_2.mp3", "mock_book_4 - part_3.mp3"], "_dirs": {}}, "mock_book_flat_nested": {"_files": [], "_dirs": {"inner_dir": {"_files": ["mock_book_flat_nested - part_1.mp3", "mock_book_flat_nested - part_2.mp3", "mock_book_flat_nested - part_3.mp3"], "_dirs": {}}}}, **mock_book_mixed_full, "mock_book_series_parent": {"_files": [], "_dirs": {"Dawn - Book 1": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3"], "_dirs": {}}, "Dusk - Book 3": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3", "mock_book_series - ch. 4.mp3"], "_dirs": {}}, "High Noon - Book 2": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3"], "_dirs": {}}}}, "mock_book_multi_disc": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc1 - ch_1.mp3", "mock_book_multi_disc1 - ch_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc2 - ch_3.mp3", "mock_book_multi_disc2 - ch_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc3 - ch_5.mp3", "mock_book_multi_disc3 - ch_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc4 - ch_7.mp3", "mock_book_multi_disc4 - ch_8.mp3"], "_dirs": {}}}}, "mock_book_multi_disc_dir_with_extras": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_1.mp3", "mock_book_multi_disc_dir_with_extras - part_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_3.mp3", "mock_book_multi_disc_dir_with_extras - part_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_5.mp3", "mock_book_multi_disc_dir_with_extras - part_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_7.mp3", "mock_book_multi_disc_dir_with_extras - part_8.mp3"], "_dirs": {}}}}, "mock_book_multi_nested": {"_files": [], "_dirs": {"nested_1": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}, "nested_2": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}}}, "mock_book_multi_part": {"_files": [], "_dirs": {"Part 01 - I": {"_files": ["mock_book_multi_part - pt.01 - I - ch_1.mp3", "mock_book_multi_part - pt.01 - I - ch_2.mp3"], "_dirs": {}}, "Part 02 - II": {"_files": ["mock_book_multi_part - pt.02 - II - ch_1.mp3", "mock_book_multi_part - pt.02 - II - ch_2.mp3"], "_dirs": {}}, "Part 03 - III": {"_files": ["mock_book_multi_part - pt.03 - III - ch_1.mp3", "mock_book_multi_part - pt.03 - III - ch_2.mp3"], "_dirs": {}}, "Part 04 - IV": {"_files": ["mock_book_multi_part - pt.04 - IV - ch_1.mp3", "mock_book_multi_part - pt.04 - IV - ch_2.mp3"], "_dirs": {}}}}, "mock_book_single_m4b": {"_files": ["mock_book_single_m4b.m4b"], "_dirs": {}}, "mock_book_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}, "mock_book_single_nested_mp3": {"_files": [], "_dirs": {"nested_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}}}},   
    "None, 0": 
        {"_files": ["mock_book_standalone_file.m4b", "mock_book_standalone_file_a.mp3", "mock_book_standalone_file_b.mp3"], "_dirs": {}},
    "0, 1": 
        {"_files": ["mock_book_standalone_file.m4b", "mock_book_standalone_file_a.mp3", "mock_book_standalone_file_b.mp3"], "_dirs": {"mock_book_1": {"_files": ["mock_book_1 - part_1.mp3", "mock_book_1 - part_2.mp3", "mock_book_1 - part_3.mp3"], "_dirs": {}}, "mock_book_2": {"_files": ["mock_book_2 - part_1.mp3", "mock_book_2 - part_2.mp3", "mock_book_2 - part_3.mp3"], "_dirs": {}}, "mock_book_3": {"_files": ["mock_book_3 - part_1.mp3", "mock_book_3 - part_2.mp3", "mock_book_3 - part_3.mp3"], "_dirs": {}}, "mock_book_4": {"_files": ["mock_book_4 - part_1.mp3", "mock_book_4 - part_2.mp3", "mock_book_4 - part_3.mp3"], "_dirs": {}}, **mock_book_mixed_0_1, "mock_book_single_m4b": {"_files": ["mock_book_single_m4b.m4b"], "_dirs": {}}, "mock_book_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}},
    "1, 1": 
        {"_files": [], "_dirs": {"mock_book_1": {"_files": ["mock_book_1 - part_1.mp3", "mock_book_1 - part_2.mp3", "mock_book_1 - part_3.mp3"], "_dirs": {}}, "mock_book_2": {"_files": ["mock_book_2 - part_1.mp3", "mock_book_2 - part_2.mp3", "mock_book_2 - part_3.mp3"], "_dirs": {}}, "mock_book_3": {"_files": ["mock_book_3 - part_1.mp3", "mock_book_3 - part_2.mp3", "mock_book_3 - part_3.mp3"], "_dirs": {}}, "mock_book_4": {"_files": ["mock_book_4 - part_1.mp3", "mock_book_4 - part_2.mp3", "mock_book_4 - part_3.mp3"], "_dirs": {}}, **mock_book_mixed_1_1, "mock_book_single_m4b": {"_files": ["mock_book_single_m4b.m4b"], "_dirs": {}}, "mock_book_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}},
    "1, 2": 
        {"_files": [], "_dirs": {"mock_book_1": {"_files": ["mock_book_1 - part_1.mp3", "mock_book_1 - part_2.mp3", "mock_book_1 - part_3.mp3"], "_dirs": {}}, "mock_book_2": {"_files": ["mock_book_2 - part_1.mp3", "mock_book_2 - part_2.mp3", "mock_book_2 - part_3.mp3"], "_dirs": {}}, "mock_book_3": {"_files": ["mock_book_3 - part_1.mp3", "mock_book_3 - part_2.mp3", "mock_book_3 - part_3.mp3"], "_dirs": {}}, "mock_book_4": {"_files": ["mock_book_4 - part_1.mp3", "mock_book_4 - part_2.mp3", "mock_book_4 - part_3.mp3"], "_dirs": {}}, "mock_book_flat_nested": {"_files": [], "_dirs": {"inner_dir": {"_files": ["mock_book_flat_nested - part_1.mp3", "mock_book_flat_nested - part_2.mp3", "mock_book_flat_nested - part_3.mp3"], "_dirs": {}}}}, **mock_book_mixed_1_2, "mock_book_series_parent": {"_files": [], "_dirs": {"Dawn - Book 1": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3"], "_dirs": {}}, "Dusk - Book 3": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3", "mock_book_series - ch. 4.mp3"], "_dirs": {}}, "High Noon - Book 2": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3"], "_dirs": {}}}}, "mock_book_multi_disc": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc1 - ch_1.mp3", "mock_book_multi_disc1 - ch_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc2 - ch_3.mp3", "mock_book_multi_disc2 - ch_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc3 - ch_5.mp3", "mock_book_multi_disc3 - ch_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc4 - ch_7.mp3", "mock_book_multi_disc4 - ch_8.mp3"], "_dirs": {}}}}, "mock_book_multi_disc_dir_with_extras": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_1.mp3", "mock_book_multi_disc_dir_with_extras - part_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_3.mp3", "mock_book_multi_disc_dir_with_extras - part_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_5.mp3", "mock_book_multi_disc_dir_with_extras - part_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_7.mp3", "mock_book_multi_disc_dir_with_extras - part_8.mp3"], "_dirs": {}}}}, "mock_book_multi_nested": {"_files": [], "_dirs": {"nested_1": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}, "nested_2": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}}}, "mock_book_multi_part": {"_files": [], "_dirs": {"Part 01 - I": {"_files": ["mock_book_multi_part - pt.01 - I - ch_1.mp3", "mock_book_multi_part - pt.01 - I - ch_2.mp3"], "_dirs": {}}, "Part 02 - II": {"_files": ["mock_book_multi_part - pt.02 - II - ch_1.mp3", "mock_book_multi_part - pt.02 - II - ch_2.mp3"], "_dirs": {}}, "Part 03 - III": {"_files": ["mock_book_multi_part - pt.03 - III - ch_1.mp3", "mock_book_multi_part - pt.03 - III - ch_2.mp3"], "_dirs": {}}, "Part 04 - IV": {"_files": ["mock_book_multi_part - pt.04 - IV - ch_1.mp3", "mock_book_multi_part - pt.04 - IV - ch_2.mp3"], "_dirs": {}}}}, "mock_book_single_m4b": {"_files": ["mock_book_single_m4b.m4b"], "_dirs": {}}, "mock_book_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}, "mock_book_single_nested_mp3": {"_files": [], "_dirs": {"nested_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}}}},
    "2, 2": 
        {"_files": [], "_dirs": {"mock_book_flat_nested": {"_files": [], "_dirs": {"inner_dir": {"_files": ["mock_book_flat_nested - part_1.mp3", "mock_book_flat_nested - part_2.mp3", "mock_book_flat_nested - part_3.mp3"], "_dirs": {}}}}, **mock_book_mixed_2_2, "mock_book_series_parent": {"_files": [], "_dirs": {"Dawn - Book 1": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3"], "_dirs": {}}, "Dusk - Book 3": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3", "mock_book_series - ch. 4.mp3"], "_dirs": {}}, "High Noon - Book 2": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3"], "_dirs": {}}}}, "mock_book_multi_disc": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc1 - ch_1.mp3", "mock_book_multi_disc1 - ch_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc2 - ch_3.mp3", "mock_book_multi_disc2 - ch_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc3 - ch_5.mp3", "mock_book_multi_disc3 - ch_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc4 - ch_7.mp3", "mock_book_multi_disc4 - ch_8.mp3"], "_dirs": {}}}}, "mock_book_multi_disc_dir_with_extras": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_1.mp3", "mock_book_multi_disc_dir_with_extras - part_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_3.mp3", "mock_book_multi_disc_dir_with_extras - part_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_5.mp3", "mock_book_multi_disc_dir_with_extras - part_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_7.mp3", "mock_book_multi_disc_dir_with_extras - part_8.mp3"], "_dirs": {}}}}, "mock_book_multi_nested": {"_files": [], "_dirs": {"nested_1": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}, "nested_2": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}}}, "mock_book_multi_part": {"_files": [], "_dirs": {"Part 01 - I": {"_files": ["mock_book_multi_part - pt.01 - I - ch_1.mp3", "mock_book_multi_part - pt.01 - I - ch_2.mp3"], "_dirs": {}}, "Part 02 - II": {"_files": ["mock_book_multi_part - pt.02 - II - ch_1.mp3", "mock_book_multi_part - pt.02 - II - ch_2.mp3"], "_dirs": {}}, "Part 03 - III": {"_files": ["mock_book_multi_part - pt.03 - III - ch_1.mp3", "mock_book_multi_part - pt.03 - III - ch_2.mp3"], "_dirs": {}}, "Part 04 - IV": {"_files": ["mock_book_multi_part - pt.04 - IV - ch_1.mp3", "mock_book_multi_part - pt.04 - IV - ch_2.mp3"], "_dirs": {}}}}, "mock_book_single_nested_mp3": {"_files": [], "_dirs": {"nested_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}}}}
}
# fmt: on
