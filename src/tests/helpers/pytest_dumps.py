from copy import deepcopy
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
_container_dir = TEST_DIRS.inbox / "mock_book_container"
_container_dir_series_parent = _container_dir / "mock_book_container_series"
_container_dir_series_books = [
    _container_dir_series_parent / "01_mock_book_d3_one",
    _container_dir_series_parent / "02_mock_book_d3_two",
    _container_dir_series_parent / "03_mock_book_d3_three",
    _container_dir_series_parent / "04_mock_book_d3_four.m4b",
]
_container_dir_others = [
    _container_dir / "mock_book_d2_this_one.mp3",
    _container_dir / "mock_book_d2_it_takes_two",
    _container_dir / "mock_book_d2_three_is_a_crowd.m4b",
]
_container_dir_files = [
    _container_dir_series_books[0] / "mock_book_d4_one-01.mp3",
    _container_dir_series_books[0] / "mock_book_d4_one-02.mp3",
    _container_dir_series_books[1] / "mock_book_d4_two-01.mp3",
    _container_dir_series_books[1] / "mock_book_d4_two-02.mp3",
    _container_dir_series_books[2] / "mock_book_d4_three-01.mp3",
    _container_dir_series_books[2] / "mock_book_d4_three-02.mp3",
    _container_dir_series_books[3],
    _container_dir_others[0],
    _container_dir_others[1] / "mock_book_d3_it_takes_two-01.mp3",
    _container_dir_others[1] / "mock_book_d3_it_takes_two-02.mp3",
    _container_dir_others[2],
]
_multi_nested_dir = TEST_DIRS.inbox / "mock_book_multi_nested"


@dataclass
class MOCKED:

    flat_dir1 = TEST_DIRS.inbox / "mock_book_1"
    flat_dir2 = TEST_DIRS.inbox / "mock_book_2"
    flat_dir3 = TEST_DIRS.inbox / "mock_book_3"
    flat_dir4 = TEST_DIRS.inbox / "mock_book_4"
    flat_dir5 = TEST_DIRS.inbox / "mock_book_5"
    flat_dirs = [flat_dir1, flat_dir2, flat_dir3, flat_dir4, flat_dir5]

    mixed_dir = TEST_DIRS.inbox / "mock_book_mixed"

    nested_dir = TEST_DIRS.inbox / "mock_book_nested"

    series_books = [
        _series_parent_dir / "Dawn - Book 1",
        _series_parent_dir / "Dusk - Book 3",
        _series_parent_dir / "High Noon - Book 2",
    ]
    series_parent_dir = _series_parent_dir
    multi_disc_dir = TEST_DIRS.inbox / "mock_book_multi_disc"
    multi_disc_dir_with_extras = TEST_DIRS.inbox / "mock_book_multi_disc_dir_with_extras"
    multi_part_dir = TEST_DIRS.inbox / "mock_book_multi_part"
    multi_nested_dir = _multi_nested_dir

    single_dir_mp3 = TEST_DIRS.inbox / "mock_book_single_mp3"
    single_nested_dir_mp3 = TEST_DIRS.inbox / "mock_book_single_nested_mp3"
    single_dir_m4b = TEST_DIRS.inbox / "mock_book_single_m4b"

    multi_dirs = [
        nested_dir,
        series_parent_dir,
        multi_disc_dir,
        multi_disc_dir_with_extras,
        multi_nested_dir,
        multi_part_dir,
    ]
    multi_nested_dirs = [multi_nested_dir / "nested_1", multi_nested_dir / "nested_2"]
    single_dirs = [single_dir_mp3, single_nested_dir_mp3, single_dir_m4b]
    series_dirs = [series_parent_dir, *series_books]
    container_root_dir = _container_dir
    container_dirs = [
        _container_dir,
        _container_dir_series_parent,
        *_container_dir_series_books,
        *_container_dir_others,
        *_container_dir_files,
    ]
    container_dir_d1_standalone_files = [_container_dir_others[0], _container_dir_others[2]]
    container_dir_d2_standalone_files = [_container_dir_series_books[3]]

    all_dirs_no_series = isorted(flat_dirs + [mixed_dir] + multi_dirs + single_dirs)

    all_dirs = isorted(flat_dirs + [mixed_dir] + multi_dirs + series_dirs[1:] + single_dirs + container_dirs)

    all_book_dirs = [d for d in all_dirs if not d == _series_parent_dir and not d == _container_dir]

    standalone_m4b = TEST_DIRS.inbox / "mock_book_standalone_file.m4b"
    standalone_mp3_1 = TEST_DIRS.inbox / "mock_book_standalone_file_a.mp3"
    standalone_mp3_2 = TEST_DIRS.inbox / "mock_book_standalone_file_b.mp3"

    standalone_files = [
        standalone_m4b,
        standalone_mp3_1,
        standalone_mp3_2,
        _container_dir_series_books[3],
    ]
    standalone_files_proper = isorted(
        [
            standalone_m4b,
            standalone_mp3_1,
            standalone_mp3_2,
            _container_dir_series_books[3],
            _container_dir_others[0],
            _container_dir_others[2],
        ]
    )
    standalone_files_d1 = deepcopy(standalone_files[:3])

    empty = TEST_DIRS.inbox / "mock_book_empty"

    all_ = all_dirs + single_dirs + container_dirs + [empty] + standalone_files

    all_books_and_series = isorted(
        list(
            set(
                flat_dirs
                + _container_dir_others
                + _container_dir_series_books
                + series_books
                + single_dirs
                + standalone_files
                + multi_nested_dirs
                + [
                    _container_dir_series_parent,
                    nested_dir,
                    mixed_dir,
                    multi_disc_dir,
                    multi_disc_dir_with_extras,
                    multi_part_dir,
                    series_parent_dir,
                ]
            )
        )
    )


mock_books_flat_full = {
    "mock_book_1": {
        "_files": ["mock_book_1 - part_1.mp3", "mock_book_1 - part_2.mp3", "mock_book_1 - part_3.mp3"],
        "_dirs": {},
    },
    "mock_book_2": {
        "_files": ["mock_book_2 - part_1.mp3", "mock_book_2 - part_2.mp3", "mock_book_2 - part_3.mp3"],
        "_dirs": {},
    },
    "mock_book_3": {
        "_files": ["mock_book_3 - part_1.mp3", "mock_book_3 - part_2.mp3", "mock_book_3 - part_3.mp3"],
        "_dirs": {},
    },
    "mock_book_4": {
        "_files": ["mock_book_4 - part_1.mp3", "mock_book_4 - part_2.mp3", "mock_book_4 - part_3.mp3"],
        "_dirs": {},
    },
    "mock_book_5": {
        "_dirs": {},
        "_files": [
            "01 - mock_book_5.mp3",
            "02 - mock_book_5.mp3",
            "03 - mock_book_5.mp3",
        ],
    },
}

mock_book_container_full = {
    "mock_book_container": {
        "_dirs": {
            "mock_book_container_series": {
                "_dirs": {
                    "01_mock_book_d3_one": {
                        "_dirs": {},
                        "_files": [
                            "mock_book_d4_one-01.mp3",
                            "mock_book_d4_one-02.mp3",
                        ],
                    },
                    "02_mock_book_d3_two": {
                        "_dirs": {},
                        "_files": [
                            "mock_book_d4_two-01.mp3",
                            "mock_book_d4_two-02.mp3",
                        ],
                    },
                    "03_mock_book_d3_three": {
                        "_dirs": {},
                        "_files": [
                            "mock_book_d4_three-01.mp3",
                            "mock_book_d4_three-02.mp3",
                        ],
                    },
                },
                "_files": [
                    "04_mock_book_d3_four.m4b",
                ],
            },
            "mock_book_d2_it_takes_two": {
                "_dirs": {},
                "_files": [
                    "mock_book_d3_it_takes_two-01.mp3",
                    "mock_book_d3_it_takes_two-02.mp3",
                ],
            },
        },
        "_files": [
            "mock_book_d2_this_one.mp3",
            "mock_book_d2_three_is_a_crowd.m4b",
        ],
    }
}

mock_book_mixed_full = {
    "mock_book_mixed": {
        "_files": [
            "01 - mixed drinks.mp3",
            "02 - mixed drinks.mp3",
            "03 - mixed drinks.mp3",
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

mock_book_container_0_1 = {
    "mock_book_container": {
        "_dirs": {},
        "_files": mock_book_container_full["mock_book_container"]["_files"],
    }
}

mock_book_mixed_0_1 = {
    "mock_book_mixed": {
        "_files": mock_book_mixed_full["mock_book_mixed"]["_files"],
        "_dirs": {},
    }
}

mock_book_mixed_1_1 = {**mock_book_mixed_0_1}

mock_book_container_1_2 = {
    "mock_book_container": {
        "_dirs": {
            "mock_book_container_series": {
                "_files": mock_book_container_full["mock_book_container"]["_dirs"]["mock_book_container_series"][
                    "_files"
                ],
                "_dirs": {},
            },
            "mock_book_d2_it_takes_two": mock_book_container_full["mock_book_container"]["_dirs"][
                "mock_book_d2_it_takes_two"
            ],
        },
        "_files": mock_book_container_full["mock_book_container"]["_files"],
    }
}

mock_book_mixed_1_2 = {
    "mock_book_mixed": {
        "_files": mock_book_mixed_full["mock_book_mixed"]["_files"],
        "_dirs": {
            **mock_book_mixed_full["mock_book_mixed"]["_dirs"],
        },
    }
}

mock_book_container_2_2 = {
    "mock_book_container": {
        "_dirs": deepcopy(mock_book_container_full["mock_book_container"]["_dirs"]),
        "_files": mock_book_container_full["mock_book_container"]["_files"],
    }
}
mock_book_container_2_2["mock_book_container"]["_dirs"]["mock_book_container_series"]["_dirs"] = {}
mock_book_container_2_2["mock_book_container"]["_files"] = []

mock_book_mixed_2_2 = {
    "mock_book_mixed": {
        "_files": [],
        "_dirs": {
            **mock_book_mixed_full["mock_book_mixed"]["_dirs"],
        },
    }
}

mock_book_container_2_3 = deepcopy(mock_book_container_2_2)
mock_book_container_2_3["mock_book_container"]["_dirs"]["mock_book_container_series"]["_dirs"] = deepcopy(
    mock_book_container_full["mock_book_container"]["_dirs"]["mock_book_container_series"]["_dirs"]
)

# fmt: off
TREES = {
    "None, None": 
        {"_files": [f.name for f in MOCKED.standalone_files_d1], "_dirs": {
            **mock_books_flat_full, 
            **mock_book_container_full, "mock_book_nested": {"_files": [], "_dirs": {"inner_dir": {"_files": ["mock_book_nested - part_1.mp3", "mock_book_nested - part_2.mp3", "mock_book_nested - part_3.mp3"], "_dirs": {}}}}, **mock_book_mixed_full, "mock_book_series_parent": {"_files": [], "_dirs": {"Dawn - Book 1": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3"], "_dirs": {}}, "Dusk - Book 3": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3", "mock_book_series - ch. 4.mp3"], "_dirs": {}}, "High Noon - Book 2": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3"], "_dirs": {}}}}, "mock_book_multi_disc": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc1 - ch_1.mp3", "mock_book_multi_disc1 - ch_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc2 - ch_3.mp3", "mock_book_multi_disc2 - ch_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc3 - ch_5.mp3", "mock_book_multi_disc3 - ch_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc4 - ch_7.mp3", "mock_book_multi_disc4 - ch_8.mp3"], "_dirs": {}}}}, "mock_book_multi_disc_dir_with_extras": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_1.mp3", "mock_book_multi_disc_dir_with_extras - part_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_3.mp3", "mock_book_multi_disc_dir_with_extras - part_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_5.mp3", "mock_book_multi_disc_dir_with_extras - part_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_7.mp3", "mock_book_multi_disc_dir_with_extras - part_8.mp3"], "_dirs": {}}}}, "mock_book_multi_nested": {"_files": [], "_dirs": {"nested_1": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}, "nested_2": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}}}, "mock_book_multi_part": {"_files": [], "_dirs": {"Part 01 - I": {"_files": ["mock_book_multi_part - pt.01 - I - ch_1.mp3", "mock_book_multi_part - pt.01 - I - ch_2.mp3"], "_dirs": {}}, "Part 02 - II": {"_files": ["mock_book_multi_part - pt.02 - II - ch_1.mp3", "mock_book_multi_part - pt.02 - II - ch_2.mp3"], "_dirs": {}}, "Part 03 - III": {"_files": ["mock_book_multi_part - pt.03 - III - ch_1.mp3", "mock_book_multi_part - pt.03 - III - ch_2.mp3"], "_dirs": {}}, "Part 04 - IV": {"_files": ["mock_book_multi_part - pt.04 - IV - ch_1.mp3", "mock_book_multi_part - pt.04 - IV - ch_2.mp3"], "_dirs": {}}}}, "mock_book_single_m4b": {"_files": ["mock_book_single_m4b.m4b"], "_dirs": {}}, "mock_book_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}, "mock_book_single_nested_mp3": {"_files": [], "_dirs": {"nested_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}}}},   
    "None, 0": 
        {"_files": [f.name for f in MOCKED.standalone_files_d1], "_dirs": {}},
    "0, 1": 
        {"_files": [f.name for f in MOCKED.standalone_files_d1], "_dirs": {
            **mock_books_flat_full,
            **mock_book_container_0_1,
            **mock_book_mixed_0_1, "mock_book_single_m4b": {"_files": ["mock_book_single_m4b.m4b"], "_dirs": {}}, "mock_book_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}},
    "1, 1": 
        {"_files": [], "_dirs": {
            **mock_books_flat_full, **mock_book_container_0_1, **mock_book_mixed_1_1, "mock_book_single_m4b": {"_files": ["mock_book_single_m4b.m4b"], "_dirs": {}}, "mock_book_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}},
    "1, 2": 
        {"_files": [], "_dirs": {
            **mock_books_flat_full, "mock_book_nested": {"_files": [], "_dirs": {"inner_dir": {"_files": ["mock_book_nested - part_1.mp3", "mock_book_nested - part_2.mp3", "mock_book_nested - part_3.mp3"], "_dirs": {}}}}, **mock_book_container_1_2, **mock_book_mixed_1_2, "mock_book_series_parent": {"_files": [], "_dirs": {"Dawn - Book 1": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3"], "_dirs": {}}, "Dusk - Book 3": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3", "mock_book_series - ch. 4.mp3"], "_dirs": {}}, "High Noon - Book 2": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3"], "_dirs": {}}}}, "mock_book_multi_disc": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc1 - ch_1.mp3", "mock_book_multi_disc1 - ch_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc2 - ch_3.mp3", "mock_book_multi_disc2 - ch_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc3 - ch_5.mp3", "mock_book_multi_disc3 - ch_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc4 - ch_7.mp3", "mock_book_multi_disc4 - ch_8.mp3"], "_dirs": {}}}}, "mock_book_multi_disc_dir_with_extras": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_1.mp3", "mock_book_multi_disc_dir_with_extras - part_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_3.mp3", "mock_book_multi_disc_dir_with_extras - part_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_5.mp3", "mock_book_multi_disc_dir_with_extras - part_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_7.mp3", "mock_book_multi_disc_dir_with_extras - part_8.mp3"], "_dirs": {}}}}, "mock_book_multi_nested": {"_files": [], "_dirs": {"nested_1": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}, "nested_2": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}}}, "mock_book_multi_part": {"_files": [], "_dirs": {"Part 01 - I": {"_files": ["mock_book_multi_part - pt.01 - I - ch_1.mp3", "mock_book_multi_part - pt.01 - I - ch_2.mp3"], "_dirs": {}}, "Part 02 - II": {"_files": ["mock_book_multi_part - pt.02 - II - ch_1.mp3", "mock_book_multi_part - pt.02 - II - ch_2.mp3"], "_dirs": {}}, "Part 03 - III": {"_files": ["mock_book_multi_part - pt.03 - III - ch_1.mp3", "mock_book_multi_part - pt.03 - III - ch_2.mp3"], "_dirs": {}}, "Part 04 - IV": {"_files": ["mock_book_multi_part - pt.04 - IV - ch_1.mp3", "mock_book_multi_part - pt.04 - IV - ch_2.mp3"], "_dirs": {}}}}, "mock_book_single_m4b": {"_files": ["mock_book_single_m4b.m4b"], "_dirs": {}}, "mock_book_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}, "mock_book_single_nested_mp3": {"_files": [], "_dirs": {"nested_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}}}},
    "2, 2": 
        {"_files": [], "_dirs": {"mock_book_nested": {"_files": [], "_dirs": {"inner_dir": {"_files": ["mock_book_nested - part_1.mp3", "mock_book_nested - part_2.mp3", "mock_book_nested - part_3.mp3"], "_dirs": {}}}}, **mock_book_container_2_2, **mock_book_mixed_2_2, "mock_book_series_parent": {"_files": [], "_dirs": {"Dawn - Book 1": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3"], "_dirs": {}}, "Dusk - Book 3": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3", "mock_book_series - ch. 4.mp3"], "_dirs": {}}, "High Noon - Book 2": {"_files": ["mock_book_series - ch. 1.mp3", "mock_book_series - ch. 2.mp3", "mock_book_series - ch. 3.mp3"], "_dirs": {}}}}, "mock_book_multi_disc": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc1 - ch_1.mp3", "mock_book_multi_disc1 - ch_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc2 - ch_3.mp3", "mock_book_multi_disc2 - ch_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc3 - ch_5.mp3", "mock_book_multi_disc3 - ch_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc4 - ch_7.mp3", "mock_book_multi_disc4 - ch_8.mp3"], "_dirs": {}}}}, "mock_book_multi_disc_dir_with_extras": {"_files": [], "_dirs": {"Disc 1 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_1.mp3", "mock_book_multi_disc_dir_with_extras - part_2.mp3"], "_dirs": {}}, "Disc 2 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_3.mp3", "mock_book_multi_disc_dir_with_extras - part_4.mp3"], "_dirs": {}}, "Disc 3 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_5.mp3", "mock_book_multi_disc_dir_with_extras - part_6.mp3"], "_dirs": {}}, "Disc 4 of 4": {"_files": ["mock_book_multi_disc_dir_with_extras - part_7.mp3", "mock_book_multi_disc_dir_with_extras - part_8.mp3"], "_dirs": {}}}}, "mock_book_multi_nested": {"_files": [], "_dirs": {"nested_1": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}, "nested_2": {"_files": ["mock_book_multi_nested - 01.mp3", "mock_book_multi_nested - 02.mp3"], "_dirs": {}}}}, "mock_book_multi_part": {"_files": [], "_dirs": {"Part 01 - I": {"_files": ["mock_book_multi_part - pt.01 - I - ch_1.mp3", "mock_book_multi_part - pt.01 - I - ch_2.mp3"], "_dirs": {}}, "Part 02 - II": {"_files": ["mock_book_multi_part - pt.02 - II - ch_1.mp3", "mock_book_multi_part - pt.02 - II - ch_2.mp3"], "_dirs": {}}, "Part 03 - III": {"_files": ["mock_book_multi_part - pt.03 - III - ch_1.mp3", "mock_book_multi_part - pt.03 - III - ch_2.mp3"], "_dirs": {}}, "Part 04 - IV": {"_files": ["mock_book_multi_part - pt.04 - IV - ch_1.mp3", "mock_book_multi_part - pt.04 - IV - ch_2.mp3"], "_dirs": {}}}}, "mock_book_single_nested_mp3": {"_files": [], "_dirs": {"nested_single_mp3": {"_files": ["mock_book_single_mp3.mp3"], "_dirs": {}}}}}},
    "2, 3": {}
}
TREES["2, 3"] = deepcopy(TREES["2, 2"])
TREES["2, 3"]["_dirs"] = {**deepcopy(TREES["2, 2"]["_dirs"]), **deepcopy(mock_book_container_2_3)}
# fmt: on
