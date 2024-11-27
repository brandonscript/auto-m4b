import functools
import re
from pathlib import Path
from typing import cast

import pytest

from src.lib.audiobook import Audiobook
from src.lib.books_tree import BooksTree
from src.lib.misc import flatlist, isorted
from src.lib.typing import BookStructure2, BookStructureTuple
from src.tests.helpers.pytest_dumps import MOCKED, TEST_DIRS, TREES

root = None


def inbox_books_tree():
    global root
    if not root:
        root = BooksTree(TEST_DIRS.inbox)
    return root


def rel_to_inbox(path: Path):
    return path.relative_to(TEST_DIRS.inbox)


class xt:

    class msg:

        @staticmethod
        def _s(structure: BookStructure2 | BookStructureTuple):
            return f"('{structure}')" if isinstance(structure, str) else str(structure)

        @staticmethod
        def structure_has(t: BooksTree, expected: BookStructureTuple):
            return f"Expected '{rel_to_inbox(t.path)}' to have {xt.msg._s(expected)}, got {t.structure}"

        @staticmethod
        def structure_not_has(t: BooksTree, expected: BookStructureTuple):
            return f"Expected '{rel_to_inbox(t.path)}' to not have {xt.msg._s(expected)}, got {t.structure}"

        @staticmethod
        def structure_is(t: BooksTree, expected: BookStructureTuple):
            return f"Expected '{rel_to_inbox(t.path)}' to be {xt.msg._s(expected)}, got {t.structure}"

        @staticmethod
        def structure_is_not(t: BooksTree, expected: BookStructureTuple):
            return f"Expected '{rel_to_inbox(t.path)}' to not be {xt.msg._s(expected)}, got {t.structure}"

    @staticmethod
    def is_root(t: BooksTree):
        assert t.is_root and t.has_only_structure(
            "_root_"
        ), f"Expected '{rel_to_inbox(t.path)}' to be root, got {t.is_root} with {t.structure}"

    @staticmethod
    def has_root(t: BooksTree):
        assert (
            t.root is not None and t != t.root
        ), f"Expected {t} to have a root and that it shouldn't be equal to itself"

    @staticmethod
    def is_not_root(t: BooksTree):
        assert not t.is_root and not t.has_structure(
            "_root_"
        ), f"Expected '{rel_to_inbox(t.path)}' to not be root, got {t.is_root} with {t.structure}"

    @staticmethod
    def is_book_root(t: BooksTree):
        assert (
            t.is_book_root
        ), f"Expected '{rel_to_inbox(t.path)}' to be a book root, but it is not because it's {t.structure}"

    @staticmethod
    def is_not_book_root(t: BooksTree):
        assert not t.is_book_root, f"Expected '{rel_to_inbox(t.path)}' to not be a book root"

    # @staticmethod
    # def is_container(t: BooksTree):
    #     assert t.has_only_structure("container"), f"Expected {t} to be ('container'), got {t.structure}"

    # @staticmethod
    # def is_standalone_file(t: BooksTree):
    #     assert t.has_only_structure("standalone_file"), f"Expected {t} to be ('standalone_file'), got {t.structure}"

    # @staticmethod
    # def is_nested(t: BooksTree):
    #     assert t.has_only_structure("nested"), f"Expected {t} to be ('nested'), got {t.structure}"

    # @staticmethod
    # def is_single_nested(t: BooksTree):
    #     assert t.has_only_structures("single", "nested"), f"Expected {t} to be ('single', 'nested), got {t.structure}"

    # @staticmethod
    # def is_series_parent(t: BooksTree):
    #     assert t.has_only_structure("series_parent"), f"Expected {t} to be ('series_parent'), got {t.structure}"

    # @staticmethod
    # def is_series_book(t: BooksTree):
    #     assert t.has_only_structure("series_book"), f"Expected {t} to be ('series_book'), got {t.structure}"

    # @staticmethod
    # def is_flat(t: BooksTree):
    #     assert t.has_only_structure("flat"), f"Expected {t} to be ('flat'), got {t.structure}"

    # @staticmethod
    # def is_multi_parent(t: BooksTree):
    #     assert t.has_only_structure("multi_parent"), f"Expected {t} to be ('multi_parent'), got {t.structure}"

    # @staticmethod
    # def is_multi_disc(t: BooksTree):
    #     assert t.has_only_structure("multi_disc"), f"Expected {t} to be ('multi_disc'), got {t.structure}"

    # @staticmethod
    # def is_multi_part(t: BooksTree):
    #     assert t.has_only_structure("multi_part"), f"Expected {t} to be ('multi_part'), got {t.structure}"

    # @staticmethod
    # def is_mixed(t: BooksTree):
    #     assert t.has_only_structure("mixed"), f"Expected {t} to be ('mixed'), got {t.structure}"

    # class does_not_have:

    #     @staticmethod
    #     def root(t: BooksTree):
    #         assert t.root is None, f"Expected {t} to not have a root, got {t.root=}"

    # class is_not:

    #     @staticmethod
    #     def root(t: BooksTree):
    #         assert not t.is_root and not t.has_structure(
    #             "_root_"
    #         ), f"Expected {t} to not be root, got {t.is_root=} and {t.structure}"

    #     @staticmethod
    #     def book_root(t: BooksTree):
    #         assert not t.is_book_root, f"Expected {t} to not be a book root"

    #     @staticmethod
    #     def container(t: BooksTree):
    #         assert not t.has_structure("container"), f"Expected {t} to not have ('container'), got {t.structure}"

    #     @staticmethod
    #     def standalone_file(t: BooksTree):
    #         assert not t.has_structure(
    #             "standalone_file"
    #         ), f"Expected {t} to not have ('standalone_file'), got {t.structure}"

    #     @staticmethod
    #     def nested(t: BooksTree):
    #         assert not t.has_structure("nested"), f"Expected {t} to not have ('nested'), got {t.structure}"

    #     @staticmethod
    #     def single_or_nested(t: BooksTree):
    #         assert not t.has_any_structure(
    #             "single", "nested"
    #         ), f"Expected {t} to not have ('single' or 'nested'), got {t.structure}"

    #     @staticmethod
    #     def series_parent(t: BooksTree):
    #         assert not t.has_structure(
    #             "series_parent"
    #         ), f"Expected {t} to not have ('series_parent'), got {t.structure}"

    #     @staticmethod
    #     def series_book(t: BooksTree):
    #         assert not t.has_structure("series_book"), f"Expected {t} to not have ('series_book'), got {t.structure}"

    #     @staticmethod
    #     def flat(t: BooksTree):
    #         assert not t.has_structure("flat"), f"Expected {t} to not have ('flat'), got {t.structure}"

    #     @staticmethod
    #     def multi_parent(t: BooksTree):
    #         assert not t.has_structure("multi_parent"), f"Expected {t} to not have ('multi_parent'), got {t.structure}"

    #     @staticmethod
    #     def multi_disc(t: BooksTree):
    #         assert not t.has_structure("multi_disc"), f"Expected {t} to not have ('multi_disc'), got {t.structure}"

    #     @staticmethod
    #     def multi_part(t: BooksTree):
    #         assert not t.has_structure("multi_part"), f"Expected {t} to not have ('multi_part'), got {t.structure}"

    #     @staticmethod
    #     def mixed(t: BooksTree):
    #         assert not t.has_structure("mixed"), f"Expected {t} to not have ('mixed'), got {t.structure}"


class test_tree_scanning:

    def test_tree_root_is_populated(self, mock_inbox, setup_teardown):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=MOCKED.all_book_dirs)
        test_book = tree._dirs[MOCKED.flat_dirs[0].name]
        assert len(test_book.files) == 3
        assert tree.is_root
        assert test_book.root and test_book.root == tree
        assert test_book.root.dirs

    @pytest.mark.parametrize(
        "indirect_fixtures, matching_paths, expected_fixture_count_sets",
        [
            # fmt: off
            (("Chanur_Series"), "chanur", ((5, 6, 1, 6, 0, 10, 1, 16), (5, 5, 5, 5, 0, 10, 5, 15))),
            (("all_hardy_boys"), "(house|missing|old_mill|tower)", ((4, 4, 4, 9, 0, 14, 4, 23), (0, 0, 0, 0, 2, 2, 2, 2), (0, 0, 2, 2, 2, 5, 4, 7))),
            # fmt: on
        ],
        indirect=["indirect_fixtures"],
    )
    def test_tree_scanning_is_idempotent(
        self,
        indirect_fixtures: list[Audiobook],
        matching_paths,
        expected_fixture_count_sets: tuple[tuple[int, ...]],
        capfd: pytest.CaptureFixture[str],
    ):

        def _assert_count(t: BooksTree, expected: tuple[int, ...], expected_children: tuple[tuple[int, ...], ...] = ()):
            assert len(t.books) == expected[0]
            assert len(t.books_and_series) == expected[1]
            assert len(t.dirs) == expected[2]
            assert len(t.dirs_recursive) == expected[3]
            assert len(t.files) == expected[4]
            assert len(t.files_recursive) == expected[5]
            assert len(t.children) == expected[6]
            assert len(t.children_recursive) == expected[7]

            for i, c in enumerate(t.children):
                if len(expected_children) <= i:
                    break
                _assert_count(c, expected_children[i])

        tree = BooksTree(TEST_DIRS.inbox, match_filter=matching_paths)

        if "chanur" in indirect_fixtures[0].key:
            if chanur_series := tree.get_like("chaxnur"):
                assert chanur_series.has_only_structure("series_parent"), xt.msg.structure_is(
                    chanur_series, "series_parent"
                )
                xt.is_book_root(chanur_series)
            else:
                pytest.fail("Chanur Series not found in tree")

        if re.search(r"(house|missing|old_mill|tower)", indirect_fixtures[0].key):

            if cliff := tree.get_like("house"):
                assert cliff.has_only_structure("flat"), xt.msg.structure_is(cliff, "flat")
                xt.is_book_root(cliff)
            else:
                pytest.fail("Cliff House not found in tree")

            if chums := tree.get_like("missing"):
                assert chums.has_only_structure("mixed"), xt.msg.structure_is(chums, "mixed")
                xt.is_book_root(chums)
            else:
                pytest.fail("Missing Chums not found in tree")

            if old_mill := tree.get_like("old_mill"):
                assert old_mill.has_only_structures("multi_parent", "multi_disc"), xt.msg.structure_is(
                    old_mill, ("multi_parent", "multi_disc")
                )
                xt.is_book_root(old_mill)
            else:
                pytest.fail("Old Mill not found in tree")

            if tower := tree.get_like("tower"):
                assert tower.has_only_structure("flat"), xt.msg.structure_is(tower, "flat")
                xt.is_book_root(tower)
            else:
                pytest.fail("Tower not found in tree")

        tree_counts = expected_fixture_count_sets[0]
        children_counts = expected_fixture_count_sets[1:]

        _assert_count(tree, tree_counts, children_counts)

        tree.scan()

        _assert_count(tree, tree_counts, children_counts)


@pytest.mark.usefixtures("mock_inbox", "setup_teardown")
class test_tree_structures:

    def test_basics(self):
        tree = BooksTree(TEST_DIRS.inbox)
        assert tree.structure
        assert tree._dirs
        assert tree._files
        assert tree.is_root
        assert tree.root is None
        for c in tree.children:
            xt.is_not_root(c)
            xt.has_root(c)

    def test_standalone_files(self):

        tree = BooksTree(TEST_DIRS.inbox, match_filter=MOCKED.standalone_files)
        assert tree._files
        for f in tree._files:
            xt.is_book_root(f)
            assert f.has_only_structure("standalone_file"), xt.msg.structure_is(f, "standalone_file")

    def test_flat_dirs(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=MOCKED.flat_dirs)
        flat_dir_names = [d.name for d in MOCKED.flat_dirs]
        flat_dirs = [d for name, d in tree._dirs.items() if name in flat_dir_names]
        flat_files = flatlist([d.files for d in flat_dirs])
        flat_all = [*flat_dirs, *flat_files]
        for d in flat_all:
            assert d.has_only_structure("flat"), xt.msg.structure_is(d, "flat")
        for c in tree.children:
            xt.is_book_root(c)

    def test_container_dir(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.container_dirs[0]])
        container_dir = tree._dirs[MOCKED.container_dirs[0].name]
        assert container_dir.parent
        assert container_dir.parent.is_root
        assert container_dir.has_only_structure("container"), xt.msg.structure_is(container_dir, "container")
        assert container_dir.books
        assert container_dir.books_and_series
        assert not container_dir.is_book_root

        series_parent = container_dir.children[0]
        assert series_parent.has_only_structure("series_parent"), xt.msg.structure_is(series_parent, "series_parent")
        for c in series_parent.children[:3]:
            assert c.has_only_structures("series_book", "flat"), xt.msg.structure_has(c, ("series_book", "flat"))
        assert series_parent.children[3].has_only_structures("series_book", "single", "nested"), xt.msg.structure_has(
            series_parent.children[3], ("series_book", "single", "nested")
        )

        flat_unrelated = container_dir.children[1]
        assert flat_unrelated.has_only_structures("flat", "nested"), xt.msg.structure_has(
            flat_unrelated, ("flat", "nested")
        )
        for c in flat_unrelated.children_recursive:
            assert c.has_only_structures("flat", "nested"), xt.msg.structure_has(c, ("flat", "nested"))
        single_mp3 = container_dir.children[2]
        assert single_mp3.has_only_structure("single"), xt.msg.structure_is(single_mp3, "single")
        single_m4b = container_dir.children[3]
        assert single_m4b.has_only_structure("single"), xt.msg.structure_is(single_m4b, "single")
        for c in container_dir.children:
            assert c.not_has_structure("container"), xt.msg.structure_not_has(c, "container")

    def test_flat_nested_dir(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.flat_nested_dir])
        flat_nested_dir = tree._dirs[MOCKED.flat_nested_dir.name]
        assert flat_nested_dir.parent
        assert flat_nested_dir.has_only_structures("flat", "nested"), xt.msg.structure_is(
            flat_nested_dir, ("flat", "nested")
        )
        xt.is_root(flat_nested_dir.parent)
        xt.is_not_root(flat_nested_dir)
        xt.is_book_root(flat_nested_dir)
        for c in flat_nested_dir.children_recursive:
            assert c.has_only_structures("flat", "nested"), xt.msg.structure_is(c, ("flat", "nested"))
            xt.is_not_book_root(c)

    def test_mixed(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.mixed_dir])
        multi_book_mixed = tree._dirs[MOCKED.mixed_dir.name]
        assert multi_book_mixed.has_only_structure("mixed"), xt.msg.structure_is(multi_book_mixed, "mixed")
        xt.is_book_root(multi_book_mixed)

        for sb in multi_book_mixed.children[:5]:
            assert sb.has_only_structures("mixed"), xt.msg.structure_is(sb, ("mixed"))
            xt.is_not_book_root(sb)

        assert (nb := multi_book_mixed.children[5]) and nb.has_only_structures("mixed"), xt.msg.structure_is(
            nb, ("mixed")
        )

        # for c in multi_book_mixed.children_recursive:
        #     assert c.has_only_structure("mixed"), xt.msg.structure_is(c, "mixed")
        #     xt.is_not_book_root(c)

    def test_mixed_chums(self, missing_chums__mixed_mp3: Audiobook):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[missing_chums__mixed_mp3.path])
        mixed_chums = tree._dirs[missing_chums__mixed_mp3.path.name]
        assert mixed_chums.has_only_structure("mixed"), xt.msg.structure_is(mixed_chums, "mixed")
        xt.is_book_root(mixed_chums)

        for c in mixed_chums.children_recursive[:1]:
            assert c.has_only_structure("mixed"), xt.msg.structure_is(c, "mixed")
            xt.is_not_book_root(c)

    def test_multi_disc(self):
        # structure = determine_structure(
        #     TEST_DIRS.inbox,
        #     tree,
        #     matching_paths=[MOCKED.multi_disc_dir, MOCKED.multi_disc_dir_with_extras],
        # )
        tree = BooksTree(
            TEST_DIRS.inbox,
            match_filter=[MOCKED.multi_disc_dir, MOCKED.multi_disc_dir_with_extras],
        )
        multi_disc_parent = tree._dirs[MOCKED.multi_disc_dir.name]
        multi_disc_extras_parent = tree._dirs[MOCKED.multi_disc_dir_with_extras.name]
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
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.multi_part_dir])
        multi_part_parent = tree._dirs[MOCKED.multi_part_dir.name]
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
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.series_parent_dir])
        series_parent = tree._dirs[MOCKED.series_parent_dir.name]

        # assert not series_parent.is_book_root
        xt.is_not_book_root(series_parent)
        assert series_parent.has_only_structure("series_parent")

        assert all((c.has_all_structures("series_book", "flat") for c in series_parent.children_recursive))
        assert not any((c.has_structure("nested") for c in series_parent.children_recursive))
        assert all((c.is_book_root for c in series_parent.dirs.values()))
        assert not any((c.is_book_root for c in flatlist([d.children_recursive for d in series_parent.dirs.values()])))

    def test_series_chanur(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[Chanur_Series[0].path])
        series_parent = tree._dirs[Chanur_Series[0].path.name]

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
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.multi_nested_dir])
        multi_nested = tree._dirs[MOCKED.multi_nested_dir.name]
        xt.is_not_book_root(multi_nested)
        assert multi_nested.has_only_structure("container"), xt.msg.structure_is(multi_nested, "container")
        for d in multi_nested.dirs.values():
            assert d.has_only_structures("flat", "nested"), xt.msg.structure_is(d, ("flat", "nested"))
            xt.is_book_root(d)

    def test_singles(self):
        tree = BooksTree(
            TEST_DIRS.inbox,
            match_filter=[MOCKED.single_dir_mp3, MOCKED.single_dir_m4b],
        )

        single_mp3 = tree._dirs[MOCKED.single_dir_mp3.name]
        single_m4b = tree._dirs[MOCKED.single_dir_m4b.name]

        assert single_mp3.has_only_structures("single"), xt.msg.structure_is(single_mp3, "single")
        assert single_m4b.has_only_structures("single"), xt.msg.structure_is(single_m4b, "single")
        xt.is_book_root(single_mp3)
        xt.is_book_root(single_m4b)

        for f in single_mp3.files:
            assert f.has_only_structure("single"), xt.msg.structure_is(f, "single")
        for f in single_m4b.files:
            assert f.has_only_structure("single"), xt.msg.structure_is(f, "single")
        for c in flatlist([single_mp3.children_recursive, single_m4b.children_recursive]):
            xt.is_not_book_root(c)

    def test_single_nested(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.single_nested_dir_mp3])
        single_nested = tree._dirs[MOCKED.single_nested_dir_mp3.name]
        assert single_nested.has_only_structure("single"), xt.msg.structure_has(single_nested, "single")
        xt.is_book_root(single_nested)

        for c in single_nested.children_recursive:
            assert c.has_only_structures("single", "nested"), xt.msg.structure_is(c, ("single", "nested"))
            xt.is_not_book_root(c)


class test_tree_structures_series:

    def test_books_and_series(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[Chanur_Series[0].path])
        series_parent = tree._dirs[Chanur_Series[0].path.name]
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
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[Chanur_Series[0].path])
        series_parent = tree._dirs[Chanur_Series[0].path.name]

        assert not series_parent.is_book_root
        assert series_parent.has_only_structure("series_parent")

        assert all((c.has_all_structures("series_book", "flat") for c in series_parent.children_recursive))
        assert not any((c.has_structure("nested") for c in series_parent.children_recursive))
        assert all((c.is_book_root for c in series_parent.dirs.values()))
        assert not any((c.is_book_root for c in flatlist([d.children_recursive for d in series_parent.dirs.values()])))

    def test_series_books_are_book_roots(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[Chanur_Series[0].path])

        assert [b.path for b in tree.books] == [a.path for a in Chanur_Series[1:]]

    def test_nested_series_with_standalone_m4as(self, nathan_lowell__nested_series_m4a: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, match_filter="^(Nathan Lowell)")
        assert tree.dirs == {"Nathan Lowell": BooksTree(TEST_DIRS.inbox / "Nathan Lowell")}
        container = tree.dirs["Nathan Lowell"]
        assert container.has_only_structure("container"), f"Expected ('container'), got {container.structure}"

        series_parents = cast(
            list[BooksTree],
            list(
                map(
                    container.get_like,
                    [
                        "A Seeker's Tale",
                        "A Trader's Tale",
                        "SC Marva Collins",
                        "Shaman's Tales",
                        "Smuggler's Tales",
                        "Tanyth Fairport Adventures",
                    ],
                )
            ),
        )

        single_nested = cast(
            list[BooksTree], list(map(container.get_like, ["Dark Knight Station Origins", "Wizard's Butler"]))
        )

        for p in series_parents:
            assert p.has_only_structure("series_parent"), xt.msg.structure_is(p, "series_parent")

        for f in single_nested:
            assert f.has_only_structures("single", "nested"), xt.msg.structure_is(f, ("single", "nested"))


class test_tree_finding:
    @pytest.mark.parametrize(
        "expected_structure, path",
        [
            *[(("flat"), d) for d in MOCKED.flat_dirs],
            (("flat", "nested"), MOCKED.flat_nested_dir),
            ("series_parent", MOCKED.series_parent_dir),
            (("multi_parent", "multi_disc"), MOCKED.multi_disc_dir),
            (("multi_parent", "multi_part"), MOCKED.multi_part_dir),
            ("container", MOCKED.multi_nested_dir),
            ("mixed", MOCKED.mixed_dir),
            ("standalone_file", MOCKED.standalone_mp3_1),
            ("standalone_file", MOCKED.standalone_m4b),
            ("single", MOCKED.single_dir_mp3),
        ],
    )
    def test_find_book_audio_files(
        self,
        expected_structure: BookStructure2 | BookStructureTuple,
        path: Path,
        mock_inbox,
        setup_teardown,
    ):
        root = inbox_books_tree()
        assert (branch := root.get(path)), f"Expected {path} to be found in TreePath({root.path})"
        _expected_structure = expected_structure if isinstance(expected_structure, tuple) else (expected_structure,)
        assert branch.has_only_structures(*_expected_structure), xt.msg.structure_is(branch, _expected_structure)

    @pytest.mark.parametrize(
        "path, mindepth, maxdepth, expected",
        [
            # fmt: off
            (TEST_DIRS.inbox, None, None, MOCKED.all_books_and_series),
            (TEST_DIRS.inbox, 0, None, MOCKED.all_books_and_series),
            (TEST_DIRS.inbox, None, 0, MOCKED.standalone_files_d1),
            (TEST_DIRS.inbox, 0, 0, MOCKED.standalone_files_d1),
            (TEST_DIRS.inbox, 0, 1, flatlist(MOCKED.flat_dirs + [MOCKED.container_root_dir, MOCKED.mixed_dir] + [MOCKED.single_dir_m4b, MOCKED.single_dir_mp3] + MOCKED.standalone_files_d1)),
            (TEST_DIRS.inbox, 1, 1, flatlist(MOCKED.flat_dirs + [MOCKED.container_root_dir, MOCKED.mixed_dir] + [MOCKED.single_dir_mp3, MOCKED.single_dir_m4b])),
            (TEST_DIRS.inbox, 1, 2, MOCKED.all_books_and_series[:6] + MOCKED.all_books_and_series[10:-3]),
            (TEST_DIRS.inbox, 2, 2, [MOCKED.all_books_and_series[5], MOCKED.all_books_and_series[10], MOCKED.all_books_and_series[-4]] + MOCKED.all_books_and_series[13:-6]),
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
    ):

        tree = BooksTree(path, mindepth=mindepth, maxdepth=maxdepth)
        assert isorted(tree.books_and_series) == isorted(
            list(set(map(functools.partial(BooksTree, allow_file_root=True), expected)))
        )

    def test_find_standalone_books_in_inbox(self, mock_inbox, setup_teardown):
        tree = BooksTree(TEST_DIRS.inbox)

        expected_sorted = list(sorted([BooksTree(p, allow_file_root=True) for p in MOCKED.standalone_files_d1]))

        assert list(sorted(tree._files)) == expected_sorted
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
            (TEST_DIRS.inbox, 2, 3, TREES["2, 3"])
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
    ):

        tree = BooksTree(path, mindepth=mindepth, maxdepth=maxdepth)

        assert tree.to_dict(fs_only=True) == expected
        assert tree.is_root and tree.root is None
        children_sorted = tree.children
        assert not any((p.is_root for p in children_sorted))
        assert not any((p.root is None for p in children_sorted))

    def test_find_first_audio_file(self, tower_treasure__flat_mp3: Audiobook):
        tree = tower_treasure__flat_mp3.tree
        assert tree.first_audio_file().path == tower_treasure__flat_mp3.path / "towertreasure4_01_dixon_64kb.mp3"

    def test_find_next_audio_file(self, tower_treasure__flat_mp3: Audiobook):
        tree = tower_treasure__flat_mp3.tree
        assert (
            tree.next_audio_file(tree.first_audio_file()).path
            == tower_treasure__flat_mp3.path / "towertreasure4_02_dixon_64kb.mp3"
        )
