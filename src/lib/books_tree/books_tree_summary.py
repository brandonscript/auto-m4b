from functools import cached_property
from typing import TYPE_CHECKING

from src.lib.term import print_debug

if TYPE_CHECKING:
    from src.lib.books_tree import BooksTree
    from src.lib.books_tree.books_tree_node import TreeNode
    from src.lib.books_tree.books_tree_node_list import TreeNodeList


class TreeNodeSummary:
    """Per-node sibling/child views used heavily by structure scorers.

    List slots are built lazily so scorers only pay for the views they touch.
    Recursive sibling lists share one filtered ``children_recursive`` walk.
    """

    def __init__(self, tree: "BooksTree"):
        from src.lib.books_tree.books_tree_node import TreeNode

        self._tree = tree
        if tree.is_root:
            print_debug(
                "[TreeNodeSummary]: cannot get summary for root, this will return an empty summary"
            )

        self._this = TreeNode(tree)
        self._parent = TreeNode(tree.parent) if tree.parent and not tree.parent.is_root else None
        # Shared filtered walk for siblings_recursive / this_and_siblings_recursive.
        self._children_r_excluding_self: list["BooksTree"] | None = None

    @property
    def this(self) -> "TreeNode":
        return self._this

    @property
    def parent(self) -> "TreeNode | None":
        return self._parent

    def _sibling_parent(self) -> "BooksTree | None":
        tree = self._tree
        p = tree.parent
        if not p or p.is_root:
            return None
        # If this is a file at depth >= 3, look at grandparent's children so
        # multi-disc / nested layouts compare across sibling book folders.
        if tree.is_file() and p.parent and tree.depth >= 3:
            return p.parent
        return p

    def _get_children_r_excluding_self(self) -> list["BooksTree"]:
        if self._children_r_excluding_self is not None:
            return self._children_r_excluding_self

        p = self._sibling_parent()
        if not p:
            self._children_r_excluding_self = []
        else:
            tree = self._tree
            # Identity comparison avoids pathlib.Path.__eq__ — nodes are
            # uniqued by _path_index so identity matches path equality.
            self._children_r_excluding_self = [c for c in p.children_recursive if c is not tree]
        return self._children_r_excluding_self

    @cached_property
    def children(self) -> "TreeNodeList":
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        return TreeNodeList(self._tree.children, self.this, default_include_curr=False)

    @cached_property
    def children_recursive(self) -> "TreeNodeList":
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        return TreeNodeList(self._tree.children_recursive, self.this, default_include_curr=False)

    @cached_property
    def files(self) -> "TreeNodeList":
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        return TreeNodeList(self._tree.files, self.this, default_include_curr=False)

    @cached_property
    def files_recursive(self) -> "TreeNodeList":
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        return TreeNodeList(self._tree.files_recursive, self.this, default_include_curr=False)

    @cached_property
    def dirs(self) -> "TreeNodeList":
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        return TreeNodeList(list(self._tree.dirs.values()), self.this, default_include_curr=False)

    @cached_property
    def this_and_siblings(self) -> "TreeNodeList":
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        tree = self._tree
        return TreeNodeList([tree, *(tree.siblings or [])], self.this, default_include_curr=True)

    @cached_property
    def this_and_siblings_recursive(self) -> "TreeNodeList":
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        tree = self._tree
        children_r = self._get_children_r_excluding_self()
        return TreeNodeList([tree, *children_r], self.this, default_include_curr=True)

    @cached_property
    def siblings_recursive(self) -> "TreeNodeList":
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        return TreeNodeList(
            self._get_children_r_excluding_self(),
            self.this,
            default_include_curr=False,
        )

    def __repr__(self):
        return f"{self.this._tree.rel_path}"

    def __str__(self):
        return self.__repr__()
