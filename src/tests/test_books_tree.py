import functools
from pathlib import Path

import pytest

from src.lib.audiobook import Audiobook
from src.lib.books_tree import BooksTree, BookStructure2
from src.lib.misc import flatlist, isorted
from src.tests.helpers.pytest_dumps import MOCKED, TEST_DIRS, TREES

root = None


def inbox_books_tree():
    global root
    if not root:
        root = BooksTree(TEST_DIRS.inbox)
    return root


@pytest.mark.usefixtures("mock_inbox", "setup_teardown", "enable_convert_series")
class test_tree_structures:

    def test_basics(self):
        tree = BooksTree(TEST_DIRS.inbox)
        assert tree.structure
        assert tree.dirs
        assert tree.files
        assert tree.is_root
        assert tree.root is None
        children_sorted = tree.get_children_sorted()
        assert not any((p.is_root for p in children_sorted))
        assert not any((p.root is None for p in children_sorted))

    def test_standalone_files(self):

        tree = BooksTree(TEST_DIRS.inbox, matching_paths=MOCKED.standalone_files)
        assert tree.files
        assert all((f.has_only_structure("standalone_file") for f in tree.files))
        assert all((f.is_book_root for f in tree.files)), f"Expected all standalone files to be book roots"

    def test_flat_dirs(self):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=MOCKED.flat_dirs)
        flat_dir_names = [d.name for d in MOCKED.flat_dirs]
        flat_dirs = [d for name, d in tree.dirs.items() if name in flat_dir_names]
        assert all(
            (d.has_only_structure("flat") for d in flat_dirs)
        ), f"Expected all dirs in {flat_dirs} to have only 'flat' structure, but got {flat_dirs[0].structure}"
        assert all(
            (f.has_only_structure("flat") for d in flat_dirs for f in d.files)
        ), f"Expected all files in 'flat_dirs to have only 'flat' structure, but got {flat_dirs[0].files[0].structure}"
        assert all(
            (d.not_has_structure("nested") for d in flat_dirs)
        ), f"Expected all dirs in {flat_dirs} to not have 'nested' structure, but got {flat_dirs[0].structure}"
        assert all(
            (not f.has_only_structure("standalone_file") for d in flat_dirs for f in d.files)
        ), f"Expected all files in {flat_dirs} to not have 'standalone_file' structure, but got {flat_dirs[0].files[0].structure}"
        assert all((c.is_book_root for c in tree.children)), f"Expected all children to be book roots"

    def test_flat_nested_container_dir(self):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[MOCKED.flat_nested_dir])
        flat_nested_dir = tree.dirs[MOCKED.flat_nested_dir.name]
        assert flat_nested_dir.parent
        assert flat_nested_dir.parent.is_root
        assert flat_nested_dir.is_book_root
        assert flat_nested_dir.has_only_structures(
            "container"
        ), f"Expected ('container'), got {flat_nested_dir.structure}"
        assert all(
            (p.has_only_structures("flat", "nested") for p in flat_nested_dir.children_recursive)
        ), f"Expected all paths to have ('flat', 'nested'), got dirs: {flat_nested_dir.children_recursive[0].structure} / files: {flat_nested_dir.children_recursive[0].structure}"
        assert not any(
            (c.is_book_root for c in flat_nested_dir.children_recursive)
        ), f"Expected all children to not be book roots"

    def test_mixed(self):
        # structure = determine_structure(
        #     TEST_DIRS.inbox, tree, matching_paths=[MOCKED.mixed_dir]
        # )
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[MOCKED.mixed_dir])
        multi_book_mixed = tree.dirs[MOCKED.mixed_dir.name]
        assert multi_book_mixed.has_only_structure("mixed"), f"Expected ('mixed'), got {multi_book_mixed.structure}"
        assert multi_book_mixed.is_book_root
        assert all(
            (c.has_only_structure("mixed") for c in multi_book_mixed.children_recursive)
        ), f"Expected all tree paths to have only 'mixed' structure, got {multi_book_mixed.children_recursive[0].structure}"
        assert not any(
            (c.is_book_root for c in multi_book_mixed.children_recursive)
        ), f"Expected all children to not be book roots"

    def test_multi_disc(self):
        # structure = determine_structure(
        #     TEST_DIRS.inbox,
        #     tree,
        #     matching_paths=[MOCKED.multi_disc_dir, MOCKED.multi_disc_dir_with_extras],
        # )
        tree = BooksTree(
            TEST_DIRS.inbox,
            matching_paths=[MOCKED.multi_disc_dir, MOCKED.multi_disc_dir_with_extras],
        )
        multi_disc_parent = tree.dirs[MOCKED.multi_disc_dir.name]
        multi_disc_extras_parent = tree.dirs[MOCKED.multi_disc_dir_with_extras.name]
        multi_disc_subdirs = [
            *multi_disc_parent.dirs.values(),
            *multi_disc_extras_parent.dirs.values(),
        ]
        multi_disc_files = [
            *multi_disc_parent.get_files_in_dirs(),
            *multi_disc_extras_parent.get_files_in_dirs(),
        ]

        assert multi_disc_parent.has_only_structures(
            "multi_parent", "multi_disc"
        ), f"Expected only ('multi_parent', 'multi_disc'), got {multi_disc_parent.structure}"

        first_not_only_multi_disc_dir = next(
            (d for d in multi_disc_subdirs if not d.has_only_structure("multi_disc")),
            multi_disc_subdirs[0],
        )
        assert all(
            (d.has_only_structure("multi_disc") for d in multi_disc_subdirs)
        ), f"Expected child dirs only ('multi_disc'), got {first_not_only_multi_disc_dir.structure}"

        first_not_only_multi_disc_file = next(
            (f.structure for f in multi_disc_files if not f.has_structure("multi_disc")),
            multi_disc_files[0].structure,
        )
        assert all(
            (f.has_only_structure("multi_disc") for f in multi_disc_files)
        ), f"Expected files only ('multi_disc'), got {first_not_only_multi_disc_file}"

        assert multi_disc_parent.is_book_root
        assert not (
            any((c.is_book_root for c in multi_disc_parent.children_recursive))
        ), f"Expected all children to not be book roots"

    def test_multi_part(self):
        # structure = determine_structure(
        #     TEST_DIRS.inbox,
        #     tree,
        #     matching_paths=[MOCKED.multi_part_dir],
        # )
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[MOCKED.multi_part_dir])
        multi_part_parent = tree.dirs[MOCKED.multi_part_dir.name]
        multi_part_subdirs = list(multi_part_parent.dirs.values())
        multi_part_files = multi_part_parent.get_files_in_dirs()
        assert multi_part_parent.is_book_root

        assert multi_part_parent.has_only_structures(
            "multi_parent", "multi_part"
        ), f"Expected ('multi_parent', 'multi_part'), got {multi_part_parent.structure}"

        first_not_only_multi_part_dir = next(
            (d.structure for d in multi_part_subdirs if not d.has_only_structure("multi_part")),
            multi_part_subdirs[0].structure,
        )
        assert all(
            (d.has_only_structure("multi_part") for d in multi_part_subdirs)
        ), f"Expected all subdirs to have only 'multi_part' structure, got {first_not_only_multi_part_dir}"

        first_not_only_multi_part_file = next(
            (f.structure for f in multi_part_files if not f.has_structure("multi_part")),
            multi_part_files[0].structure,
        )
        assert all(
            (f.has_only_structure("multi_part") for f in multi_part_files)
        ), f"Expected all files to have only 'multi_part' structure, got {first_not_only_multi_part_file}"

        assert not any(
            (c.is_book_root for c in multi_part_parent.children_recursive)
        ), f"Expected all children to not be book roots"

    def test_series(self):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[MOCKED.series_parent_dir])
        series_parent = tree.dirs[MOCKED.series_parent_dir.name]

        assert not series_parent.is_book_root
        assert series_parent.has_only_structure("series_parent")

        assert all((c.has_all_structures("series_book", "flat") for c in series_parent.children_recursive))
        assert not any((c.has_structure("nested") for c in series_parent.children_recursive))
        assert all((c.is_book_root for c in series_parent.dirs.values()))
        assert not any((c.is_book_root for c in flatlist([d.children_recursive for d in series_parent.dirs.values()])))

    def test_series_chanur(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[Chanur_Series[0].path])
        series_parent = tree.dirs[Chanur_Series[0].path.name]

        assert not series_parent.is_book_root
        assert series_parent.has_only_structure("series_parent")

        first_not_flat_series_book = next(
            (c for c in series_parent.children_recursive if not c.has_all_structures("series_book", "flat")),
            series_parent.children_recursive[0],
        )
        assert all(
            (c.has_all_structures("series_book", "flat") for c in series_parent.children_recursive)
        ), f"Expected all paths to have ('series_book', 'flat'), got {first_not_flat_series_book.structure}"
        assert not any(
            (c.has_structure("nested") for c in series_parent.children_recursive)
        ), f"Expected no paths to have 'nested', got {series_parent.children_recursive[0].structure}"
        assert all((c.is_book_root for c in series_parent.dirs.values())), f"Expected all dirs to be book roots"
        assert not any(
            (c.is_book_root for c in flatlist([d.children_recursive for d in series_parent.dirs.values()]))
        ), f"Expected no children to be book roots"

    def test_multi_nested(self):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[MOCKED.multi_nested_dir])
        multi_nested = tree.dirs[MOCKED.multi_nested_dir.name]
        assert multi_nested.is_book_root
        assert multi_nested.has_only_structure("mixed")
        assert all((d.has_only_structure("mixed") for d in multi_nested.dirs.values()))
        assert all((c.has_structure("mixed") for c in multi_nested.children_recursive))
        assert not any((c.is_book_root for c in multi_nested.children_recursive))

    def test_singles(self):
        tree = BooksTree(
            TEST_DIRS.inbox,
            matching_paths=[MOCKED.single_dir_mp3, MOCKED.single_dir_m4b],
        )

        single_mp3 = tree.dirs[MOCKED.single_dir_mp3.name]
        single_m4b = tree.dirs[MOCKED.single_dir_m4b.name]

        assert single_mp3.has_only_structure("single")
        assert single_m4b.has_only_structure("single")
        assert single_mp3.is_book_root
        assert single_m4b.is_book_root

        assert all((f.has_only_structure("single") for f in single_mp3.files))
        assert all((f.has_only_structure("single") for f in single_m4b.files))
        assert not any(
            (c.is_book_root for c in flatlist([single_mp3.children_recursive, single_m4b.children_recursive]))
        )

    def test_single_nested(self):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[MOCKED.single_nested_dir_mp3])
        single_nested = tree.dirs[MOCKED.single_nested_dir_mp3.name]
        single_nested_subdirs = single_nested.dirs.values()
        single_nested_files = single_nested.get_files_in_dirs()
        assert single_nested.is_book_root
        assert single_nested.not_has_structure("flat")

        assert all((d.has_all_structures("single", "nested") for d in single_nested_subdirs))
        assert not any((d.has_structure("flat") for d in single_nested_subdirs))

        assert all((f.has_structure("single") for f in single_nested_files))
        assert not any((f.has_structure("flat") for f in single_nested_files))

        assert not any((c.is_book_root for c in single_nested.children_recursive))


class test_tree_structures_series:

    def test_books_and_series(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[Chanur_Series[0].path])
        series_parent = tree.dirs[Chanur_Series[0].path.name]
        found_paths = list(isorted([b.path for b in tree.books_and_series]))
        assert not tree.is_book_root
        assert not series_parent.is_book_root
        assert len(tree.books_and_series) == len(
            found_paths
        ), f"Expected {len(tree.books_and_series)} books and series, found {len(found_paths)}"
        assert len(tree.books_and_series) == len(Chanur_Series)
        assert len(tree.books) == len(Chanur_Series) - 1
        assert all((f.is_book_root for f in tree.books)), "All books and series should be book roots"
        assert found_paths == [b.path for b in Chanur_Series]

    def test_series_parent_is_not_book_root(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[Chanur_Series[0].path])
        series_parent = tree.dirs[Chanur_Series[0].path.name]

        assert not series_parent.is_book_root
        assert series_parent.has_only_structure("series_parent")

        assert all((c.has_all_structures("series_book", "flat") for c in series_parent.children_recursive))
        assert not any((c.has_structure("nested") for c in series_parent.children_recursive))
        assert all((c.is_book_root for c in series_parent.dirs.values()))
        assert not any((c.is_book_root for c in flatlist([d.children_recursive for d in series_parent.dirs.values()])))

    def test_series_books_are_book_roots(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[Chanur_Series[0].path])

        assert [b.path for b in tree.books] == [a.path for a in Chanur_Series[1:]]


class test_tree_finding:
    @pytest.mark.parametrize(
        "expected_structure, path",
        [
            *[("flat", d) for d in MOCKED.flat_dirs],
            ("container", MOCKED.flat_nested_dir),
            ("series_parent", MOCKED.series_parent_dir),
            ("multi_disc", MOCKED.multi_disc_dir),
            ("multi_part", MOCKED.multi_part_dir),
            ("mixed", MOCKED.multi_nested_dir),
            ("mixed", MOCKED.mixed_dir),
            ("standalone_file", MOCKED.standalone_mp3_1),
            ("standalone_file", MOCKED.standalone_m4b),
            ("single", MOCKED.single_dir_mp3),
        ],
    )
    def test_find_book_audio_files(
        self,
        expected_structure: BookStructure2,
        path: Path,
        mock_inbox,
        setup_teardown,
    ):
        root = inbox_books_tree()
        assert (branch := root.get(path)), f"Expected {path} to be found in TreePath({root.path})"
        assert branch.has_structure(expected_structure), f"Expected ('{expected_structure},'), got {branch.structure}"

    @pytest.mark.parametrize(
        "path, mindepth, maxdepth, expected",
        [
            # fmt: off
            (TEST_DIRS.inbox, None, None, MOCKED.all_dirs + MOCKED.standalone_files),
            (TEST_DIRS.inbox, 0, None, MOCKED.all_dirs + MOCKED.standalone_files),
            (TEST_DIRS.inbox, None, 0, MOCKED.standalone_files),
            (TEST_DIRS.inbox, 0, 0, MOCKED.standalone_files),
            (TEST_DIRS.inbox, 0, 1, flatlist(MOCKED.flat_dirs + [MOCKED.mixed_dir] + [MOCKED.single_dir_m4b, MOCKED.single_dir_mp3] + MOCKED.standalone_files)),
            (TEST_DIRS.inbox, 1, 1, flatlist(MOCKED.flat_dirs + [MOCKED.mixed_dir] + [MOCKED.single_dir_mp3, MOCKED.single_dir_m4b])),
            (TEST_DIRS.inbox, 1, 2, MOCKED.all_dirs),
            (TEST_DIRS.inbox, 2, 2, flatlist([MOCKED.mixed_dir] + MOCKED.multi_dirs + [MOCKED.single_nested_dir_mp3] + MOCKED.series_books)),
            # fmt: on
        ],
    )
    def test_find_books_in_inbox(
        self,
        path: Path,
        mindepth: int,
        maxdepth: int,
        expected: list[Path],
        mock_inbox,
        setup_teardown,
        enable_convert_series,
    ):

        tree = BooksTree(path, mindepth=mindepth, maxdepth=maxdepth)
        assert isorted(tree.books_and_series) == isorted(
            map(functools.partial(BooksTree, allow_file_root=True), expected)
        )

    def test_find_books_in_inbox_series_off(self, mock_inbox, setup_teardown, disable_convert_series):
        tree = BooksTree(TEST_DIRS.inbox, matching_paths=[MOCKED.series_parent_dir])

        assert list(sorted(tree.books_and_series)) == []

    def test_find_standalone_books_in_inbox(self, mock_inbox, setup_teardown, enable_convert_series):
        tree = BooksTree(TEST_DIRS.inbox)

        expected_sorted = list(sorted([BooksTree(p, allow_file_root=True) for p in MOCKED.standalone_files]))

        assert list(sorted(tree.files)) == expected_sorted
        assert (
            list(sorted(filter(lambda b: b.has_only_structure("standalone_file"), tree.books_and_series)))
            == expected_sorted
        )

    @pytest.mark.parametrize(
        "path, mindepth, maxdepth, expected",
        [
            # fmt: off
            (TEST_DIRS.inbox, None, None, TREES['None, None']),
            (TEST_DIRS.inbox, 0, None, TREES['None, None']), # Same as above
            (TEST_DIRS.inbox, None, 0, TREES['None, 0']),
            (TEST_DIRS.inbox, 0, 0, TREES["None, 0"]), # Same as above
            (TEST_DIRS.inbox, 0, 1, TREES["0, 1"]),
            (TEST_DIRS.inbox, 1, 1, TREES["1, 1"]),
            (TEST_DIRS.inbox, 1, 2, TREES["1, 2"]),
            (TEST_DIRS.inbox, 2, 2, TREES["2, 2"]),
            (TEST_DIRS.inbox, 2, 3, TREES["2, 2"])
            # Only 2 levels deep, so same as above
            # fmt: on
        ],
    )
    def test_find_tree_of_audio_files_in_dir(
        self,
        path: Path,
        mindepth: int,
        maxdepth: int,
        expected: list[Path],
        mock_inbox,
        setup_teardown,
        enable_convert_series,
    ):

        tree = BooksTree(path, mindepth=mindepth, maxdepth=maxdepth)

        assert tree.to_dict(fs_only=True) == expected
        assert tree.is_root and tree.root is None
        children_sorted = tree.get_children_sorted()
        assert not any((p.is_root for p in children_sorted))
        assert not any((p.root is None for p in children_sorted))

    def test_find_first_audio_file(self, tower_treasure__flat_mp3: Audiobook):
        tree = BooksTree(tower_treasure__flat_mp3.path)
        assert tree.first_audio_file().path == tower_treasure__flat_mp3.path / "towertreasure4_01_dixon_64kb.mp3"

    def test_find_next_audio_file(self, tower_treasure__flat_mp3: Audiobook):
        tree = BooksTree(tower_treasure__flat_mp3.path)
        assert (
            tree.next_audio_file(tree.first_audio_file()).path
            == tower_treasure__flat_mp3.path / "towertreasure4_02_dixon_64kb.mp3"
        )
