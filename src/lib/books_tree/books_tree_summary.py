from typing import TYPE_CHECKING

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
    # dirs_recursive: "TreeNodeList"
    # siblings: "TreeNodeList"
    this_and_siblings: "TreeNodeList"

    def __init__(self, tree: "BooksTree"):
        from src.lib.books_tree.books_tree_node import TreeNode
        from src.lib.books_tree.books_tree_node_list import TreeNodeList

        self._tree = tree
        self.this = TreeNode(tree)
        self.parent = TreeNode(tree.parent) if tree.parent and not tree.parent.is_root else None
        self.children = TreeNodeList(tree.children, self.this)
        self.children_recursive = TreeNodeList(tree.children_recursive, self.this)
        self.files = TreeNodeList(tree.files, self.this)
        self.files_recursive = TreeNodeList(tree.files_recursive, self.this)
        self.dirs = TreeNodeList(list(tree.dirs.values()), self.this)
        # self.dirs_recursive = TreeNodeList(tree.dirs_recursive, self.this)
        # self.siblings = TreeNodeList(tree.siblings or [], self.this)
        self.this_and_siblings = TreeNodeList([tree, *(tree.siblings or [])], self.this)

    def __repr__(self):
        return f"{self.this._tree.rel_path}"

    def __str__(self):
        return self.__repr__()
