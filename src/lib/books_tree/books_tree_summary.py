import re
from typing import Literal, TYPE_CHECKING

from lazy.lazy import lazy

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
        self.this = TreeNode(tree)
        self.parent = TreeNode(tree.parent) if tree.parent and not tree.parent.is_root else None
        self.children = TreeNodeList(tree.children, self.this)
        self.children_recursive = TreeNodeList(tree.children_recursive, self.this)
        self.files = TreeNodeList(tree.files, self.this)
        self.files_recursive = TreeNodeList(tree.files_recursive, self.this)
        self.dirs = TreeNodeList(list(tree.dirs.values()), self.this)
        self.dirs_recursive = TreeNodeList(tree.dirs_recursive, self.this)
        self.siblings = TreeNodeList(tree.siblings or [], self.this)
        self.this_and_siblings = TreeNodeList([tree, *(tree.siblings or [])], self.this)
        self._best_score = ("unknown", 0)

    def __repr__(self):
        (likely, score) = self._best_score
        if likely != "unknown":
            return f"{self.this._tree}: likely {likely} ({score})"
        return f"{self.this._tree}"

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
            "mixed": self.score_mixed,
            "unknown": 0,
        }
        self._best_score = max(scores.items(), key=lambda x: x[1])
        return self._best_score[0] == likely

    @lazy
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

            path_similarity = -0.5 + (self.children.pathname_similarity(distinct=True, include_curr=True) or 0.5)
            child_sizes = -0.5 + percent_truthy_in_list([is_gt_50mb(p.size) for p in self._tree.children]) / 100
            series_completion = 0
            series_uniqueness = 0
            if self.children.have_series_nums:
                series_completion = -0.5 + float((self.children.series_nums_completion or 1) > 0.95)
                series_uniqueness = float(((self.children.series_nums_uniqueness or 1) > 0.2) / 2)
            start_completion = 0
            if self.children.have_start_nums:
                start_completion = -0.5 + float((self.children.start_nums_completion or 1) > 0.95)
            part_uniqueness = -0.5 + float(
                not self.children.have_part_nums or (self.children.part_nums_uniqueness or 0) < 0.1
            )
            if self._tree.is_match:
                ...

            ok_children = float(
                sum(
                    (
                        path_similarity,
                        child_sizes,
                        series_completion,
                        start_completion,
                        series_uniqueness,
                        part_uniqueness,
                    )
                )
            )

        series_parent_score = ok_children
        if self.children.are_maybe("series"):
            series_parent_score += 0.2
        if bool(re.search(r"(?:\b|_)series(?:\b|_)", self._tree.name.lower(), re.I)):
            series_parent_score += 1
        if self.this.has_series_num or self.this.has_start_num or self.this.has_disc_num:
            # Penalize if the parent candidate has numbers, not very likely to be a series parent
            series_parent_score -= 0.5

        return round(series_parent_score, 3)

    @lazy
    def score_series_book(self):
        if not self._tree.parent or self._tree.parent.is_root or self._tree.is_root:
            return 0.0
        # if self._tree.parent.i.is_likely("series_parent"):
        #     return 1.0

        if self._tree.is_match:
            ...

        curr_and_siblings_are_series = self.this.is_maybe("series") and (
            not self.siblings._trees or self.siblings.are_maybe("series")
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

    @lazy
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

    @lazy
    def score_multi_disc(self):
        if not self._tree.parent or self._tree.is_root:
            return 0.0

        if self._tree.is_file():
            if self.this_and_siblings.are_maybe("multi_disc"):
                return 1.0

            return self.siblings.disc_nums_completion or 0.0
        elif self.this.is_maybe("multi_disc") or self.children.are_maybe("multi_disc"):
            return 1.0

        return self.children.disc_nums_completion or 0.0

    @lazy
    def score_multi_part(self):
        if not self._tree.parent or self._tree.is_root:
            return 0.0

        if self._tree.is_file():
            if self.this_and_siblings.are_maybe("multi_part"):
                return 1.0

            return self.siblings.part_nums_completion or 0.0
        else:
            if self.children.are_maybe("multi_part"):
                return 1.0

            return self.children.part_nums_completion or 0.0

    @lazy
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

    @lazy
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

    @lazy
    def score_mixed(self):
        if not self.children_recursive:
            return 0.0

        if self._tree.is_match:
            ...

        if self._tree.is_file():
            diff = 1 - (self.this_and_siblings.pathname_similarity(distinct=True) or 0)
            missing = len([c for c in self.this_and_siblings.all_path_nums if not c]) / len(
                self.this_and_siblings._trees
            )
            return round(diff + missing, 3)

        seed = max(self.score_container, self.score_series_parent)
        diff = 1 - (self.children.pathname_similarity(distinct=True, include_curr=True) or 0)
        missing = [c for c in self.children_recursive.all_path_nums if not c]
        complexity = self.tree_complexity

        if not missing:
            return round((seed + (diff - 0.5) if seed > 0 else 0.0) + complexity, 3)

        missing_ratio = len(missing) / len(self.children_recursive._trees)

        return round(seed + (diff - 0.5) + missing_ratio * 2 + complexity, 3)

    @lazy
    def tree_complexity(self) -> float:
        """
        Calculates the complexity of the tree structure based on:
        1. Depth of nesting
        2. Mixing of files at different levels
        3. Irregularity in the structure
        4. Number of branches/forks

        Returns a float between 0 and 1, where:
        - 0 means perfectly flat structure (all files in one directory)
        - 1 means highly complex structure with mixed levels and irregular nesting
        """
        if not self._tree.children_recursive:
            return 0.0

        # Get all nodes in the tree
        all_nodes = self._tree.children_recursive
        if not all_nodes:
            return 0.0

        # Calculate base metrics
        max_depth = max(node.depth for node in all_nodes)
        total_files = len([n for n in all_nodes if n.is_file()])
        total_dirs = len([n for n in all_nodes if n.is_dir()])

        if total_files == 0:
            return 0.0

        # Calculate file distribution across depths
        files_by_depth = {}
        for node in all_nodes:
            if node.is_file():
                depth = node.depth
                files_by_depth[depth] = files_by_depth.get(depth, 0) + 1

        # Calculate mixing score (how evenly files are distributed across depths)
        depth_variance = 0
        if len(files_by_depth) > 1:
            mean_files_per_depth = total_files / len(files_by_depth)
            depth_variance = sum((count - mean_files_per_depth) ** 2 for count in files_by_depth.values()) / len(
                files_by_depth
            )
            depth_variance = min(1.0, depth_variance / (total_files**2))  # Normalize to 0-1

        # Calculate branching factor
        avg_children_per_dir = total_files / total_dirs if total_dirs > 0 else 0
        branching_factor = min(1.0, avg_children_per_dir / 10)  # Normalize assuming 10 is max reasonable

        # Calculate depth penalty
        depth_penalty = min(1.0, max_depth / 5)  # Normalize assuming 5 is max reasonable depth

        # Calculate irregularity (how many different depths have files)
        irregularity = min(1.0, len(files_by_depth) / max_depth) if max_depth > 0 else 0

        # Combine all factors with weights
        complexity = (
            depth_penalty * 0.3  # 30% weight to depth
            + depth_variance * 0.3  # 30% weight to file distribution
            + branching_factor * 0.2  # 20% weight to branching
            + irregularity * 0.2  # 20% weight to irregularity
        )

        if self._tree.is_match:
            ...

        return round(complexity, 3)
