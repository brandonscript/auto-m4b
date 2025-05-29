import functools
import re
from pathlib import Path
from typing import cast

import pytest

from src.lib.audiobook import Audiobook
from src.lib.books_tree import BooksTree
from src.lib.misc import any_matching, flatlist, isorted
from src.lib.typing import BookStructure2, BookStructureTuple
from src.tests.helpers.pytest_dumps import MOCKED, TEST_DIRS, TREES


def inbox_books_tree(*, match_filter: str | list[Path] | None = None):
    return BooksTree(TEST_DIRS.inbox, match_filter=match_filter)


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
        test_book = tree.dirs[MOCKED.flat_dirs[0].name]
        assert len(test_book.files) == 3
        assert tree.is_root
        assert test_book.root and test_book.root == tree
        assert test_book.root.dirs

    def test_container_root_is_never_root(self, nathan_lowell__nested_series_m4a: Audiobook):
        tree = BooksTree(TEST_DIRS.inbox)
        container = next(iter(tree.dirs.values()))
        assert not container.is_root
        assert container.container_root == container
        for c in container.children_recursive_f:
            assert not c.is_root
            assert c.container_root == container

    def test_parents(self, mock_inbox, setup_teardown):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=MOCKED.all_book_dirs)
        test_book = tree.dirs[MOCKED.flat_dirs[0].name]
        assert test_book.parent == tree
        for c in test_book.children_recursive_f:
            assert not (par := c.parent) or par.is_dir() and not par.is_file()

        for c in test_book.children:
            assert c.parent == test_book

    def test_keys(self, mock_inbox, setup_teardown):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=MOCKED.all_book_dirs)
        test_book = tree.dirs[MOCKED.flat_dirs[0].name]
        assert test_book.key == test_book.name
        for c in test_book.children_recursive:
            if not c.is_book_root:
                assert c.key is None
            else:
                assert c.key != "None"
                assert c.key == c.name

    @pytest.mark.parametrize(
        "indirect_fixtures, matching_paths, expected_fixture_count_sets",
        [
            # fmt: off
            (("Chanur_Series"), "chanur", 
             ((5, 6, 1, 6, 0, 10, 1, 16), (5, 5, 5, 5, 0, 10, 5, 15))),
            (("all_hardy_boys"), "(house|missing|old_mill|tower)", 
             ((4, 4, 4, 9, 0, 14, 4, 23), (0, 0, 0, 0, 2, 2, 2, 2), (0, 0, 2, 2, 2, 5, 4, 7))),
            (("nathan_lowell__nested_series_m4a",), "^(Nathan Lowell)", 
             (
                 (22, 28, 1, 28, 0, 28, 1, 56), 
                 (22, 28, 8, 27, 0, 28, 8, 55), 
                 (3, 3, 3, 3, 0, 3, 3, 6), 
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (6, 6, 6, 6, 0, 6, 6, 12), 
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (2, 2, 2, 2, 0, 2, 2, 4),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (3, 3, 3, 3, 0, 3, 3, 6),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (3, 3, 3, 3, 0, 3, 3, 6),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (3, 3, 2, 2, 1, 9, 3, 11),
                 (0, 0, 0, 0, 7, 7, 7, 7),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
                 (0, 0, 0, 0, 1, 1, 1, 1),
             )),
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

        def _assert_count(t: BooksTree, *expecteds: tuple[int, ...]):
            if not expecteds:
                return

            expected = expecteds[0]
            expected_children = expecteds[1:]
            assert len(t.books_f) == expected[0], f"Expected '{t.key}' to have {expected[0]} books, got {len(t.books)}"
            assert (
                len(t.books_and_series_f) == expected[1]
            ), f"Expected '{t.key}' to have {expected[1]} books_and_series, got {len(t.books_and_series_f)}"
            assert len(t.dirs_f) == expected[2], f"Expected '{t.key}' to have {expected[2]} dirs, got {len(t.dirs_f)}"
            assert (
                len(t.dirs_recursive_f) == expected[3]
            ), f"Expected '{t.key}' to have {expected[3]} dirs_recursive, got {len(t.dirs_recursive_f)}"
            assert (
                len(t.files_f) == expected[4]
            ), f"Expected '{t.key}' to have {expected[4]} files, got {len(t.files_f)}"
            assert (
                len(t.files_recursive_f) == expected[5]
            ), f"Expected '{t.key}' to have {expected[5]} files_recursive, got {len(t.files_recursive_f)}"
            assert (
                len(t.children_f) == expected[6]
            ), f"Expected '{t.key}' to have {expected[6]} children, got {len(t.children_f)}"
            assert (
                len(t.children_recursive_f) == expected[7]
            ), f"Expected '{t.key}' to have {expected[7]} children_recursive, got {len(t.children_recursive_f)}"

            if t.is_root:
                for i, c in enumerate(t.dirs_recursive_f):
                    if len(expected_children) <= i:
                        break

                    _assert_count(c, *expected_children[i:])

        tree = BooksTree(TEST_DIRS.inbox, match_filter=matching_paths)

        def _check():
            if "chanur" in indirect_fixtures[0].key.lower():  # type: ignore
                assert next(
                    (
                        b
                        for b in tree.books_and_series
                        if b.name == "Chanur Series" and b.has_only_structure("series_parent")
                    ),
                    None,
                )
                if chanur_series := tree.get_like("chanur"):
                    assert chanur_series.has_only_structure("series_parent"), xt.msg.structure_is(
                        chanur_series, "series_parent"
                    )
                    xt.is_not_book_root(chanur_series)
                    assert indirect_fixtures[0].key == chanur_series.key
                    for c in indirect_fixtures[1:]:
                        bk = chanur_series.get(c.key)  # type: ignore
                        assert bk
                        assert bk.has_structure("series_book"), xt.msg.structure_has(bk, "series_book")
                        xt.is_book_root(bk)
                else:
                    pytest.fail("Chanur Series not found in tree")

            if re.search(r"(house|missing|old_mill|tower)", indirect_fixtures[0].key):  # type: ignore

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

            if re.search(r"Nathan Lowell", indirect_fixtures[0].key):  # type: ignore

                # assert there is at least one series_parent
                assert next(
                    (b for b in tree.books_and_series if b.has_structure("series_parent")),
                    None,
                )

                assert len(tree.children_recursive_f) == 56
                assert len([c for c in tree.children_recursive_f if c.has_structure("series_parent")]) == 6
                assert len([c for c in tree.children_recursive_f if c.has_structure("series_book")]) == 45

        # tree_counts = expected_fixture_count_sets[0]
        # children_counts = expected_fixture_count_sets[1:]

        _assert_count(tree, *expected_fixture_count_sets)
        _check()

        tree.scan()

        _assert_count(tree, *expected_fixture_count_sets)
        _check()


@pytest.mark.usefixtures("mock_inbox", "setup_teardown")
class test_tree_structures:

    def test_basics(self):
        tree = BooksTree(TEST_DIRS.inbox)
        assert tree.structure
        assert tree.dirs
        assert tree.files
        assert tree.is_root
        assert tree.root is None
        for c in tree.children:
            xt.is_not_root(c)
            xt.has_root(c)

    def test_standalone_files(self):

        tree = inbox_books_tree(match_filter="^(mock_book_(container|standalone))")
        assert tree.files_recursive_f
        for f in [f for f in tree.files_recursive_f if f.path in MOCKED.standalone_files_proper]:
            found = tree.get_path(f.path)
            assert id(f) == id(found), f"Expected both objects to be the same, got {id(f)} and {id(found)}"
            assert f.has_structure("standalone_file"), xt.msg.structure_has(f, "standalone_file")
            xt.is_book_root(f)

    def test_flat_dirs(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=MOCKED.flat_dirs)
        flat_dir_names = [d.name for d in MOCKED.flat_dirs]
        flat_dirs = [d for name, d in tree.dirs.items() if name in flat_dir_names]
        flat_files = flatlist([d.files for d in flat_dirs])
        flat_all = [*flat_dirs, *flat_files]
        for d in flat_all:
            assert d.has_only_structure("flat"), xt.msg.structure_is(d, "flat")
        for c in tree.children_f:
            xt.is_book_root(c)

    def test_flatish_with_tags(self, authors_guide_to_murder__flat_mp3: Audiobook):
        tree = BooksTree(TEST_DIRS.inbox, match_filter="^authors_guide_to_murder")
        book = tree.get(cast(str, authors_guide_to_murder__flat_mp3.key))
        assert book
        assert book.has_structure("flat"), xt.msg.structure_is(book, ("flat"))
        xt.is_book_root(book)

        assert len(book.children_recursive_f) == 39, f"Expected 39 children, got {len(book.children_recursive_f)}"
        assert len(book.files_recursive_f) == 38, f"Expected 38 files, got {len(book.files_recursive_f)}"
        assert len(book.dirs_recursive_f) == 1, f"Expected 1 dir, got {len(book.dirs_recursive_f)}"

        first_file = book.files_recursive_f[0]
        first_dir = book.dirs_recursive_f[0]
        for f in book.files_recursive_f:
            assert f.has_structure_like("flat"), xt.msg.structure_is(f, ("flat"))
            xt.is_not_book_root(f)
        assert first_file.has_structure("flatish"), xt.msg.structure_is(first_file, ("flatish"))
        assert first_dir.has_structure("flatish"), xt.msg.structure_is(first_dir, ("flatish"))

    def test_flatish_without_tags(self, authors_guide_to_murder__flat_mp3: Audiobook):
        tree = BooksTree(TEST_DIRS.inbox, match_filter="^authors_guide_to_murder", scan_id3=False)
        book = tree.get(cast(str, authors_guide_to_murder__flat_mp3.key))
        assert book
        assert book.has_only_structure("container"), xt.msg.structure_is(book, ("container"))
        xt.is_not_book_root(book)

        assert len(book.children_recursive_f) == 39, f"Expected 39 children, got {len(book.children_recursive_f)}"
        assert len(book.files_recursive_f) == 38, f"Expected 38 files, got {len(book.files_recursive_f)}"
        assert len(book.dirs_recursive_f) == 1, f"Expected 1 dir, got {len(book.dirs_recursive_f)}"

        for c in book.children_recursive_f:
            assert c.has_structure_like("unknown"), xt.msg.structure_is(c, ("unknown"))
            xt.is_not_book_root(c)

    def test_container_dir(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.container_dirs[0]])
        container_dir = tree.dirs[MOCKED.container_dirs[0].name]
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
        assert series_parent.children[3].has_only_structures("series_book", "standalone_file"), xt.msg.structure_has(
            series_parent.children[3], ("series_book", "standalone_file")
        )

        flat_unrelated = container_dir.children[1]
        assert flat_unrelated.has_only_structures("flat"), xt.msg.structure_has(flat_unrelated, ("flat"))
        for c in flat_unrelated.children_recursive_f:
            assert c.has_only_structures("flat"), xt.msg.structure_has(c, ("flat"))
        standalone_mp3 = container_dir.children[2]
        assert standalone_mp3.has_only_structure("standalone_file"), xt.msg.structure_is(
            standalone_mp3, "standalone_file"
        )
        standalone_m4b = container_dir.children[3]
        assert standalone_m4b.has_only_structure("standalone_file"), xt.msg.structure_is(
            standalone_m4b, "standalone_file"
        )
        for c in container_dir.children:
            assert c.not_has_structure("container"), xt.msg.structure_not_has(c, "container")

    def test_nested_dir(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.nested_dir])
        nested_dir = tree.dirs[MOCKED.nested_dir.name]
        assert nested_dir.parent
        assert nested_dir.has_only_structures("flat", "nested"), xt.msg.structure_is(nested_dir, ("flat", "nested"))
        xt.is_root(nested_dir.parent)
        xt.is_not_root(nested_dir)
        xt.is_book_root(nested_dir)
        for c in nested_dir.children_recursive_f:
            assert c.container_root == nested_dir
            assert c.has_only_structures("flat", "nested"), xt.msg.structure_is(c, ("flat", "nested"))
            xt.is_not_book_root(c)

    def test_mixed(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.mixed_dir])
        multi_book_mixed = tree.dirs[MOCKED.mixed_dir.name]
        assert multi_book_mixed.has_only_structure("mixed"), xt.msg.structure_is(multi_book_mixed, "mixed")
        xt.is_book_root(multi_book_mixed)

        for sb in multi_book_mixed.children[:5]:
            assert sb.has_only_structures("mixed"), xt.msg.structure_is(sb, ("mixed"))
            xt.is_not_book_root(sb)

        assert (nb := multi_book_mixed.children[5]) and nb.has_only_structures("mixed"), xt.msg.structure_is(
            nb, ("mixed")
        )

    def test_mixed_chums(self, missing_chums__mixed_mp3: Audiobook):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[missing_chums__mixed_mp3.path])
        mixed_chums = tree.dirs[missing_chums__mixed_mp3.path.name]
        assert mixed_chums.has_only_structure("mixed"), xt.msg.structure_is(mixed_chums, "mixed")
        xt.is_book_root(mixed_chums)

        for c in mixed_chums.children_recursive_f[:1]:
            assert c.has_only_structure("mixed"), xt.msg.structure_is(c, "mixed")
            xt.is_not_book_root(c)

    def test_mixed_fails(self, fails__mixed_mp3: Audiobook):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[fails__mixed_mp3.path])
        mixed_fails = tree.dirs[fails__mixed_mp3.path.name]
        assert mixed_fails.has_only_structure("mixed"), xt.msg.structure_is(mixed_fails, "mixed")
        xt.is_book_root(mixed_fails)

        for c in mixed_fails.children_recursive_f[:1]:
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
            any((c.is_book_root for c in multi_disc_parent.children_recursive_f))
        ), f"Expected all children to not be book roots"

    def test_multi_part(self):
        # structure = determine_structure(
        #     TEST_DIRS.inbox,
        #     tree,
        #     matching_paths=[MOCKED.multi_part_dir],
        # )
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.multi_part_dir])
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
            (c.is_book_root for c in multi_part_parent.children_recursive_f)
        ), f"Expected all children to not be book roots"

    def test_series(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.series_parent_dir])
        series_parent = tree.dirs[MOCKED.series_parent_dir.name]

        # assert not series_parent.is_book_root
        xt.is_not_book_root(series_parent)
        assert series_parent.has_only_structure("series_parent")

        assert all((c.has_all_structures("series_book", "flat") for c in series_parent.children_recursive_f))
        assert not any((c.has_structure("nested") for c in series_parent.children_recursive_f))
        assert all((c.is_book_root for c in series_parent.dirs.values()))
        assert not any(
            (c.is_book_root for c in flatlist([d.children_recursive_f for d in series_parent.dirs.values()]))
        )

    def test_series_chanur(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[Chanur_Series[0].path])
        series_parent = tree.dirs[Chanur_Series[0].path.name]

        assert not series_parent.is_book_root
        assert series_parent.has_only_structure("series_parent")

        first_not_flat_series_book = next(
            (c for c in series_parent.children_recursive_f if not c.has_all_structures("series_book", "flat")),
            series_parent.children_recursive_f[0],
        )
        assert all(
            (c.has_all_structures("series_book", "flat") for c in series_parent.children_recursive_f)
        ), f"Expected all paths to have ('series_book', 'flat'), got {first_not_flat_series_book.structure}"
        assert not any(
            (c.has_structure("nested") for c in series_parent.children_recursive_f)
        ), f"Expected no paths to have 'nested', got {series_parent.children_recursive_f[0].structure}"
        assert all((c.is_book_root for c in series_parent.dirs.values())), f"Expected all dirs to be book roots"
        assert not any(
            (c.is_book_root for c in flatlist([d.children_recursive_f for d in series_parent.dirs.values()]))
        ), f"Expected no children to be book roots"

    def test_multi_nested(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.multi_nested_dir])
        multi_nested = tree.dirs[MOCKED.multi_nested_dir.name]
        xt.is_book_root(multi_nested)
        assert multi_nested.has_only_structure("mixed"), xt.msg.structure_is(multi_nested, "mixed")
        for d in multi_nested.children_recursive_f:
            assert d.has_only_structures("mixed"), xt.msg.structure_is(d, ("mixed"))
            xt.is_not_book_root(d)

    def test_multi_nested_series(self, secret_project_series__nested_flat_mixed: Audiobook):
        tree = BooksTree(TEST_DIRS.inbox)
        container = tree.dirs[secret_project_series__nested_flat_mixed.basename]
        xt.is_not_book_root(container)
        assert container.has_only_structure("series_parent"), xt.msg.structure_is(container, "series_parent")
        for d in container.dirs.values():
            if "Yumi" in d.name:
                assert d.has_only_structures("single", "series_book"), xt.msg.structure_is(d, ("single", "series_book"))
            else:
                assert d.has_only_structures("flat", "series_book"), xt.msg.structure_is(d, ("flat", "series_book"))
            xt.is_book_root(d)

    def test_singles(self):
        tree = BooksTree(
            TEST_DIRS.inbox,
            match_filter=[MOCKED.single_dir_mp3, MOCKED.single_dir_m4b],
        )

        single_mp3 = tree.dirs[MOCKED.single_dir_mp3.name]
        single_m4b = tree.dirs[MOCKED.single_dir_m4b.name]

        assert single_mp3.has_only_structures("single"), xt.msg.structure_is(single_mp3, "single")
        assert single_m4b.has_only_structures("single"), xt.msg.structure_is(single_m4b, "single")
        xt.is_book_root(single_mp3)
        xt.is_book_root(single_m4b)

        for f in single_mp3.files:
            assert f.has_only_structures("single"), xt.msg.structure_is(f, "single")
        for f in single_m4b.files:
            assert f.has_only_structure("single"), xt.msg.structure_is(f, "single")
        for c in flatlist([single_mp3.children_recursive_f, single_m4b.children_recursive_f]):
            xt.is_not_book_root(c)

    def test_single_nested(self):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[MOCKED.single_nested_dir_mp3])
        single_nested = tree.dirs[MOCKED.single_nested_dir_mp3.name]
        assert single_nested.has_only_structures("single", "nested"), xt.msg.structure_has(
            single_nested, ("single", "nested")
        )
        xt.is_book_root(single_nested)

        for c in single_nested.children_recursive_f:
            assert c.has_only_structures("single", "nested"), xt.msg.structure_is(c, ("single", "nested"))
            xt.is_not_book_root(c)


class test_tree_structures_series:

    def test_books_and_series(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[Chanur_Series[0].path])
        series_parent = tree.dirs[Chanur_Series[0].path.name]
        found_paths = list(isorted([b.path for b in tree.books_and_series_f]))
        assert not tree.is_book_root
        assert not series_parent.is_book_root
        assert len(tree.books_and_series_f) == len(
            found_paths
        ), f"Expected {len(tree.books_and_series_f)} books and series, found {len(found_paths)}"
        assert len(tree.books_and_series_f) == len(Chanur_Series)
        assert len(tree.books_f) == len(Chanur_Series) - 1
        assert all((f.is_book_root for f in tree.books)), "All books and series should be book roots"
        assert found_paths == [b.path for b in Chanur_Series]

    def test_series_parent_is_not_book_root(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[Chanur_Series[0].path])
        series_parent = tree.dirs[Chanur_Series[0].path.name]

        assert not series_parent.is_book_root
        assert series_parent.has_only_structure("series_parent")

        assert all((c.has_all_structures("series_book", "flat") for c in series_parent.children_recursive_f))
        assert not any((c.has_structure("nested") for c in series_parent.children_recursive_f))
        assert all((c.is_book_root for c in series_parent.dirs.values()))
        assert not any(
            (c.is_book_root for c in flatlist([d.children_recursive_f for d in series_parent.dirs.values()]))
        )

    def test_series_books_are_book_roots(self, Chanur_Series: list[Audiobook]):
        tree = BooksTree(TEST_DIRS.inbox, match_filter=[Chanur_Series[0].path])

        assert [b.path for b in tree.books_f] == [a.path for a in Chanur_Series[1:]]

    def test_complex_container_with_series(
        self, requires_empty_inbox, nathan_lowell__nested_series_m4a: list[Audiobook]
    ):
        tree = BooksTree(TEST_DIRS.inbox, match_filter="^(Nathan Lowell)")
        assert tree.dirs_f == {"Nathan Lowell": BooksTree(TEST_DIRS.inbox / "Nathan Lowell")}
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

        single_dirs = cast(
            list[BooksTree], list(map(container.get_like, ["Dark Knight Station Origins", "Wizard's Butler"]))
        )

        assert (flat := container.get_like("Ravenwood"))
        assert flat.has_only_structures("flat", "series_book"), xt.msg.structure_is(flat, ("flat", "series_book"))

        for p in series_parents:
            assert p.has_only_structure("series_parent"), xt.msg.structure_is(p, "series_parent")

        for f in single_dirs:
            assert f.has_only_structures("single"), xt.msg.structure_is(f, ("single"))

        series_books = [
            "01 In Ashes Born",
            "02 To Fire Called",
            "03 By Darkness Forged",
            "01 Quarter Share",
            "02 Half Share",
            "03 Full Share",
            "04 Double Share",
            "05 Captain's Share",
            "06 Owner's Share",
            "01 School Days",
            "02 Working Class",
            "01 South Coast",
            "02 Cape Grace",
            "03 Finwell Bay",
            "01 Milk Run",
            "02 Suicide Run",
            "03 Home Run",
            "01 Ravenwood",
            "02 Zypheria's Call",
            "03 The Hermit of Lammas Wood",
        ]

        for c in [c for c in container.children_recursive_f if any_matching([c.name], series_books)]:
            assert c.has_structure("series_book"), xt.msg.structure_has(c, "series_book")
            if c.is_file():
                if c.path.suffix == ".m4a" and not "Zypheria" in str(c.path):
                    assert c.has_structure("single"), xt.msg.structure_has(c, "single")
                elif c.path.suffix == ".mp3":
                    assert c.has_structure("flat"), xt.msg.structure_has(c, "flat")

        assert (zypheria := container.get_like("02 Zypheria's Call"))
        assert zypheria.has_structure("standalone_file"), xt.msg.structure_has(zypheria, "standalone_file")
        assert zypheria.not_has_structure("nested"), xt.msg.structure_not_has(zypheria, "nested")

        for c in [
            c
            for c in container.children_recursive_f
            if c.depth > 2
            and not any_matching(
                [c.name],
                [
                    "Dark Knight Station Origins",
                    "Wizard's Butler",
                ],
            )
        ]:
            assert c.has_structure("series_book"), xt.msg.structure_has(c, "series_book")


class test_tree_finding:
    @pytest.mark.parametrize(
        "expected_structure, path",
        [
            *[(("flat"), d) for d in MOCKED.flat_dirs],
            (("flat", "nested"), MOCKED.nested_dir),
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
