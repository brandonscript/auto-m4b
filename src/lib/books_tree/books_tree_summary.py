from typing import TYPE_CHECKING

from lib.term import print_debug

if TYPE_CHECKING:
    from src.lib.books_tree import BooksTree
    from src.lib.books_tree.books_tree_node import TreeNode
    from src.lib.books_tree.books_tree_node_list import TreeNodeList


class TreeNodeSummary:

    this: "TreeNode"
    parent: "TreeNode | None"
    children: "TreeNodeList"
    children_recursive: "TreeNodeList"
    files: "TreeNodeList"
    files_recursive: "TreeNodeList"
    dirs: "TreeNodeList"
    this_and_siblings: "TreeNodeList"
    this_and_siblings_recursive: "TreeNodeList"
    siblings_recursive: "TreeNodeList"  # Excludes 'self'

    def __init__(self, tree: "BooksTree"):
        from src.lib.books_tree.books_tree_node import TreeNode
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        self._tree = tree

        if tree.is_root:
            print_debug(f"[TreeNodeSummary]: cannot get summary for root, this will return an empty summary")
            self.this = TreeNode.empty(tree)
            self.parent = None
            self.children = TreeNodeList([], self.this)
            self.children_recursive = TreeNodeList([], self.this)
            self.files = TreeNodeList([], self.this)
            self.files_recursive = TreeNodeList([], self.this)
            self.dirs = TreeNodeList([], self.this)
            self.this_and_siblings = TreeNodeList([], self.this)
            self.this_and_siblings_recursive = TreeNodeList([], self.this)
            self.siblings_recursive = TreeNodeList([], self.this)

        self.this = TreeNode(tree)
        self.parent = TreeNode(tree.parent) if tree.parent and not tree.parent.is_root else None
        self.children = TreeNodeList(tree.children, self.this, default_include_curr=False)
        self.children_recursive = TreeNodeList(tree.children_recursive, self.this, default_include_curr=False)
        self.files = TreeNodeList(tree.files, self.this, default_include_curr=False)
        self.files_recursive = TreeNodeList(tree.files_recursive, self.this, default_include_curr=False)
        self.dirs = TreeNodeList(list(tree.dirs.values()), self.this, default_include_curr=False)
        self.this_and_siblings = TreeNodeList([tree, *(tree.siblings or [])], self.this, default_include_curr=True)
        self.this_and_siblings_recursive = TreeNodeList([tree], self.this, default_include_curr=True)
        self.siblings_recursive = TreeNodeList([], self.this, default_include_curr=False)
        if p := tree.parent:
            children_r = [c for c in p.children_recursive if c != tree]
            self.this_and_siblings_recursive = TreeNodeList(
                [tree, *children_r],
                self.this,
                default_include_curr=True,
            )
            self.siblings_recursive = TreeNodeList(
                children_r,
                self.this,
                default_include_curr=False,
            )

    def __repr__(self):
        return f"{self.this._tree.rel_path}"

    def __str__(self):
        return self.__repr__()
