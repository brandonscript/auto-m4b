import re
from typing import Literal, TYPE_CHECKING

from lib.misc import is_gt_50mb, is_gt_75mb, percent_truthy_in_list

if TYPE_CHECKING:
    from lib.books_tree import BooksTree
    from lib.books_tree.books_tree_node import TreeNode
    from lib.books_tree.books_tree_node_list import TreeNodeList

Likely = Literal[
    "series_parent",
    "series_book",
    "multi_parent",
    "multi_disc",
    "multi_part",
    "standalone_file",
    "container",
    "unknown",
]


class TreeNodeSummary:

    this: "TreeNode"
    parent: "TreeNode | None"
    children: "TreeNodeList"
    children_recursive: "TreeNodeList"
    files: "TreeNodeList"
    files_recursive: "TreeNodeList"
    dirs: "TreeNodeList"
    dirs_recursive: "TreeNodeList"
    siblings: "TreeNodeList"
    this_and_siblings: "TreeNodeList"

    def __init__(self, tree: "BooksTree"):
        from lib.books_tree.books_tree_node import TreeNode
        from lib.books_tree.books_tree_node_list import TreeNodeList

        self._tree = tree
        self.this = TreeNode(tree.path)
        self.parent = TreeNode(tree.parent.path, self.this) if tree.parent and not tree.parent.is_root else None
        self.children = TreeNodeList([c.path for c in tree.children], self.this)
        self.children_recursive = TreeNodeList([c.path for c in tree.children_recursive], self.this)
        self.files = TreeNodeList([f.path for f in tree.files], self.this)
        self.files_recursive = TreeNodeList([f.path for f in tree.files_recursive], self.this)
        self.dirs = TreeNodeList([d.path for d in tree.dirs.values()], self.this)
        self.dirs_recursive = TreeNodeList([d.path for d in tree.dirs_recursive], self.this)
        self.siblings = TreeNodeList([s.path for s in (tree.siblings or [])], self.this)
        self.this_and_siblings = TreeNodeList([self.this._path, *self.siblings._paths], self.this)
        self._best_score = ("unknown", 0)

    def __repr__(self):
        (likely, score) = self._best_score
        if likely != "unknown":
            return f"{self.this._path}: likely {likely} ({score})"
        return f"{self.this._path}"

    def __str__(self):
        return self.__repr__()

    def is_likely(
        self,
        likely: Likely,
    ):
        scores = {
            "series_parent": self.score_series_parent,
            "series_book": self.score_series_book,
            "multi_parent": self.score_multi_parent,
            "multi_disc": self.score_multi_disc,
            "multi_part": self.score_multi_part,
            "standalone_file": self.score_standalone_file,
            "container": self.score_container,
            "unknown": 0,
        }
        self._best_score = max(scores.items(), key=lambda x: x[1])
        return self._best_score[0] == likely

    @property
    def score_series_parent(self):

        if self._tree.is_match:
            ...

        if self._tree.is_root or self._tree.is_file():
            return 0.0

        ok_children = 0.0
        if self.children.have_albums:
            d = self.children.album_similarity() or 0
            # Strongly penalize if child albums all match
            ok_children -= d if d < 0.95 else 2

        if self.children.have_albumartists:
            ok_children += int((self.children.albumartist_similarity() or 0) > 0.9) / 3

        if self.children.have_artists:
            ok_children += int((self.children.artist_similarity() or 0) > 0.9) / 3

        if (
            not bool(ok_children)
            # and not self.this.has_series_num
            # and not self.this.has_start_num
            and (self.children.have_series_nums or self.children.have_start_nums)
        ):
            child_paths = -0.5 + float((self.children.pathname_similarity(distinct=True) or 0) < 0.85)
            path_sim_to_curr = -0.5 + float(
                (self.children.pathname_similarity(distinct=True, include_curr=True) or 0) < 0.85
            )
            child_sizes = -0.5 + percent_truthy_in_list([is_gt_50mb(p.size) for p in self._tree.children]) / 100
            child_completion = -0.5 + float((self.children.series_nums_completion or 1) > 0.75)
            child_uniqueness = float(((self.children.series_nums_uniqueness or 1) > 0.2) / 2)
            child_part_nums = -0.5 + float(
                not self.children.have_part_nums or (self.children.part_nums_uniqueness or 0) < 0.1
            )

            ok_children = float(
                sum((child_paths, path_sim_to_curr, child_sizes, child_completion, child_uniqueness, child_part_nums))
            )

        series_parent_score = ok_children
        if self.children.are_maybe("series"):
            series_parent_score += 0.2
        if bool(re.search(r"(?:\b|_)series(?:\b|_)", self._tree.name.lower(), re.I)):
            series_parent_score += 0.5
        if self.this.has_series_num or self.this.has_start_num or self.this.has_disc_num:
            # Penalize if the parent candidate has numbers, not very likely to be a series parent
            series_parent_score -= 0.5

        return round(series_parent_score, 3)

    @property
    def score_series_book(self):
        if not self._tree.parent or self._tree.parent.is_root or self._tree.is_root:
            return 0.0
        # if self._tree.parent.i.is_likely("series_parent"):
        #     return 1.0

        if self._tree.is_match:
            ...

        curr_and_siblings_are_series = self.this.is_maybe("series") and (
            not self.siblings._paths or self.siblings.are_maybe("series")
        )
        if _parent_is_series_parent := self._tree.parent and self._tree.parent.has_structure("series_parent"):
            return 1.0

        parent_ok = bool(self.parent and self._tree.parent)
        has_container_root = bool(self._tree.container_root)

        if not parent_ok or not has_container_root:
            return 0.0

        ok_siblings_paths = -0.5 + int((self.siblings.pathname_similarity(distinct=True) or 0) < 0.7)
        ok_siblings_sizes = percent_truthy_in_list([is_gt_50mb(p.size) for p in self._tree.siblings or []]) / 100
        ok_siblings_paths_and_size = -0.5 + int(
            (self.siblings.pathname_similarity(distinct=True) or 0) < 0.85 and ok_siblings_sizes
        )
        ok_siblings = 0.0
        if self.siblings.have_albums:
            ok_siblings += float((self.siblings.album_similarity(distinct=True) or 0) > 0.9)

        if self.siblings.have_albumartists:
            ok_siblings += float((self.siblings.albumartist_similarity(distinct=True) or 0) > 0.9) / 2

        if self.siblings.have_artists:
            ok_siblings += float((self.siblings.artist_similarity(distinct=True) or 0) > 0.9) / 2

        ok_siblings = float(sum((ok_siblings_paths, ok_siblings_sizes, ok_siblings_paths_and_size, ok_siblings)))

        series_book_score = ok_siblings
        if curr_and_siblings_are_series:
            series_book_score += 0.5

        return round(series_book_score, 3)

    @property
    def score_multi_parent(self):
        if not self._tree.parent or not self.parent or self._tree.is_root:
            return 0.0

        if (
            len(self._tree.dirs) < 2
            or self.this.is_maybe("multi_disc")
            or self.this.is_maybe("multi_part")
            or self.parent.is_maybe("multi_disc")
            or self.parent.is_maybe("multi_part")
        ):
            return 0.0

        multi_parent_score = 0.0
        if self.children.are_maybe("multi_disc"):
            multi_parent_score += 0.5
        if self.children.are_maybe("multi_part"):
            multi_parent_score += 0.5

        return round(multi_parent_score, 3)

    @property
    def score_multi_disc(self):
        if not self._tree.parent or self._tree.is_root:
            return 0.0

        if self.this.is_maybe("multi_disc") or self.children.are_maybe("multi_disc"):
            return 1.0

        return 0.0

    @property
    def score_multi_part(self):
        if not self._tree.parent or self._tree.is_root:
            return 0.0

        if self.this_and_siblings.are_maybe("multi_part"):
            return 1.0

        return 0.0

    @property
    def score_standalone_file(self):
        if not self._tree.is_file():
            return 0.0

        if (p := self._tree.parent) and (p.is_root or p.has_structure("container")):
            return 1.0

        if _only_file_in_parent := p and len(p.files) == 1 and not p.dirs:
            return 1.0

        parent_has_files_and_dirs = bool(p and (p.files or p.dirs))
        parent_has_multiple_dirs = bool(p and len(p.dirs) > 1)
        parent_has_mixed_content = parent_has_files_and_dirs or parent_has_multiple_dirs

        dissimilar_files = (self.siblings.pathname_similarity(distinct=True) or 0) < 0.8
        has_mixed_file_types = len(set([f.path.suffix for f in p.files])) > 1 if p else False
        all_sizes_gt_75mb = all(is_gt_75mb(f.size) for f in p.files) if p else False
        has_m4b_files = any(f.path.suffix == ".m4b" for f in p.files) if p else False

        standalone_score = (
            percent_truthy_in_list(
                [dissimilar_files, has_mixed_file_types, all_sizes_gt_75mb, has_m4b_files, parent_has_mixed_content]
            )
            / 100
        )

        if self.siblings.have_albums and (
            (siblings_album_similarity := self.siblings.album_similarity(distinct=True) or 0) < 0.9
        ):
            standalone_score += 1 - siblings_album_similarity

        if self.siblings.have_albumartists and (
            (siblings_albumartist_similarity := self.siblings.albumartist_similarity(distinct=True) or 0) < 0.7
        ):
            standalone_score += 1 - siblings_albumartist_similarity

        if self.siblings.have_artists and (
            (siblings_artist_similarity := self.siblings.artist_similarity(distinct=True) or 0) < 0.7
        ):
            standalone_score += 1 - siblings_artist_similarity

        # if it has a track number/total other than None, 1, or 1/1, subtract 1.5
        if self.this.has_track_num and (self.this.id3_track_num > 1 or not self.this.id3_track_total > 1):
            standalone_score -= 1.5

        # if it has a disc number/total other than None, 1, or 1/1, subtract 1.5
        if self.this.has_disc_num and (self.this.id3_disc_num > 1 or not self.this.id3_disc_total > 1):
            standalone_score -= 1.5

        return round(standalone_score, 3)

    @property
    def score_container(self):
        dissimilar_files = (self.files.pathname_similarity(distinct=True) or 0) < 0.8
        has_multiple_files = len(self._tree.files) > 1
        has_files_and_dirs = bool(self._tree.parent and (self._tree.parent.files or self._tree.parent.dirs))
        standalones = (
            len([f for f in self._tree.files if f.i.score_standalone_file > 0.4]) / len(self._tree.files)
            if self._tree.files
            else 0.0
        )
        pathnames_similarity = (self.files.pathname_similarity(distinct=True) or 0) < 0.8

        container_score = (
            percent_truthy_in_list(
                [dissimilar_files, has_multiple_files, has_files_and_dirs, pathnames_similarity, standalones > 0]
            )
            / 100
        )

        return round(container_score, 3)
