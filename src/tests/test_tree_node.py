from src.lib.audiobook import Audiobook
from src.lib.books_tree import BooksTree
from src.tests.helpers.pytest_dumps import TEST_DIRS


class test_tree_node:

    def test_tree_has_id3_info(self, authors_guide_to_murder__flat_mp3: Audiobook, setup_teardown):
        tree = BooksTree(TEST_DIRS.inbox, match_filter="^authors_guide_to_murder")
        test_book = tree.dirs[authors_guide_to_murder__flat_mp3.path.name]
        assert len(test_book.files) == 37
        assert len(test_book.files_recursive) == 38
        assert len(test_book.dirs) == 1
        assert len(test_book.dirs_recursive) == 1

        i = test_book.i
        assert i._tree == test_book

        # Parent
        assert i.parent is None

        # Common
        for x in [i.children, i.files, i.dirs, i.this_and_siblings]:
            assert x.disc_nums == []
            assert x.disc_nums_are_contiguous == None
            assert x.part_nums == []
            assert x.series_nums == []
            assert x.id3_disc_nums == []
            assert x.id3_disc_total == None
            assert x.unique_disc_nums == None
            assert x.unique_part_nums == None
            assert x.unique_series_nums == None
            assert x.similarity("id3_disc_nums", include_curr=True) == None

        # Children
        assert i.children.__repr__() == "{d: —, p: —, s: —, ^: 1-38, ~: 0.872}"
        assert i.children.start_nums == [n for n in range(1, 39)]
        assert i.children.all_path_nums == [[n] for n in range(1, 39)]

        # Files
        assert i.files.__repr__() == "{d: —, p: —, s: —, ^: 2-38, ~: 0.872}"
        assert i.files.start_nums == [n for n in range(2, 39)]
        assert i.files.all_path_nums == [[n] for n in range(2, 39)]

        # Children / Files
        for _name, x in [("children", i.children), ("files", i.files)]:
            assert x.id3_disc_total == None
            assert x.id3_track_nums == [n for n in range(2, 39)]
            assert x.id3_track_total == 38  # 1-based
            assert len(x.id3_titles) == 37
            assert all(len(t) > 2 for t in x.id3_titles)
            assert x.start_nums_uniqueness == 1
            assert x.track_nums_uniqueness == 1
            assert x.unique_start_nums == x.start_nums
            assert x.unique_track_nums == x.id3_track_nums
            assert (x.start_vs_track_nums_similarity or 0) > 0.97

        # Children recursive
        assert i.children_recursive.__repr__() == "{d: —, p: —, s: —, ^: 1-38, ~: 0.883}"
        assert i.children_recursive.start_nums == [1] + [n for n in range(1, 39)]
        assert i.children_recursive.all_path_nums == [[1]] + [[n] for n in range(1, 39)]
        assert i.children_recursive.id3_track_nums == [n for n in range(1, 39)]
        assert i.children_recursive.id3_track_total == 38  # 1-based
        assert len(i.children_recursive.id3_titles) == 38
        assert all(len(t) > 2 for t in i.children_recursive.id3_titles)

        # Files recursive
        assert i.files_recursive.__repr__() == "{d: —, p: —, s: —, ^: 1-38, ~: 0.872}"
        assert i.files_recursive.start_nums == [n for n in range(1, 39)]
        assert i.files_recursive.all_path_nums == [[n] for n in range(1, 39)]
        assert i.files_recursive.id3_track_nums == [n for n in range(1, 39)]
        assert i.files_recursive.id3_track_total == 38  # 1-based
        assert len(i.files_recursive.id3_titles) == 38
        assert all(len(t) > 2 for t in i.files_recursive.id3_titles)

        # Dirs
        assert i.dirs.__repr__() == "{d: —, p: —, s: —, ^: 1, ~: -1}"
        assert i.dirs.start_nums == [1]
        assert i.dirs.all_path_nums == [[1]]
        # There are no id3 tags for dirs

        # This and siblings
        assert i.this_and_siblings.__repr__() == "{d: —, p: —, s: —, ^: —, ~: -1}"
        assert i.this_and_siblings.start_nums == []
        assert i.this_and_siblings.all_path_nums == [[3]]  # Dir has "_mp3" in it

        # Determinations
        assert i.score_multi_part == 1.0
        assert i.score_multi_disc == 0
        assert i.score_series_book < 0.5
        assert i.is_likely("multi_disc") == False
        assert i.is_likely("multi_parent") == False
        assert i.is_likely("multi_part") == True
        assert i.is_likely("series_book") == False
        assert i.is_likely("series_parent") == False
