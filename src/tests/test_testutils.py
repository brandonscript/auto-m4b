from pathlib import Path

import pytest

from src.lib.term import CATS_ASCII_LINES
from src.tests.helpers.pytest_utils import testutils


@pytest.mark.parametrize(
    "indirect_fixture, expected",
    [
        (
            "test_out_chanur_txt",
            [
                "Chanur Series/01 - Pride Of Chanur",
                "Chanur Series/02 - Chanur's Venture",
                "Chanur Series/03 - Kif Strikes Back",
                "Chanur Series/04 - Chanur's Homecoming",
                "Chanur Series/05 - Chanur's Legacy",
            ],
        ),
        (
            "test_out_tower_txt",
            ["tower_treasure__flat_mp3"],
        ),
    ],
    indirect=["indirect_fixture"],
)
def test_get_all_processed_books(indirect_fixture, expected):
    assert (
        testutils.get_all_processed_books(
            indirect_fixture, root_dir=Path("/auto-m4b/src/tests/tmp/inbox")
        )
        == expected
    )


@pytest.mark.parametrize(
    "test_input, expected",
    [
        (["a", "b", "c"], ("a", "b", "c")),
        (["a", "b", "c", "cat"], ("a", "b", "c", "cat")),
        (("a", "b", "c"), ("a", "b", "c")),
        (("a\nb\ncat",), ("a\nb\ncat",)),
        (tuple(CATS_ASCII_LINES), ()),
        (tuple(["a", "b", *CATS_ASCII_LINES, "x", "y"]), ("a", "b", "x", "y")),
    ],
)
def test_strip_cats_ascii(test_input, expected):
    if isinstance(test_input, tuple):
        assert testutils.strip_cats_ascii(*test_input) == expected
    else:
        assert testutils.strip_cats_ascii(test_input) == expected


@pytest.mark.parametrize(
    "test_input, expected",
    [
        ("------", False),
        (("----", "auto", "[DEBUG]"), False),
        (
            "-------------------------  ⌐◒-◒  auto-m4b • 2024-04-12 18:53:01  -------------------------",
            True,
        ),
        (
            (
                "-------------------------  ⌐◒-◒  auto-m4b • 2024-04-12 18:53:01  -------------------------",
                "Watching for books in /path/to/inbox ꨄ︎",
            ),
            True,
        ),
        (
            """-------------------------  ⌐◒-◒  auto-m4b • 2024-04-12 18:53:01  -------------------------
Watching for books in /path/to/inbox ꨄ︎

[DEBUG] Waiting for inbox updates: 1 (70202c72 → 5ad760a2)
-------------------------  ⌐◒-◒  auto-m4b • 2024-04-12 18:53:01  -------------------------
Watching for books in /path/to/inbox ꨄ︎

 *** New activity detected in the inbox...
[PYTEST] Mocked copy to inbox: 3
[PYTEST] Mocked copy to inbox: 4
[PYTEST] Mocked copy to inbox: 5
[PYTEST] Mocked copy to inbox complete

[DEBUG] Waiting for inbox updates: 2 (70202c72 → 5ad760a2)
[DEBUG] Done waiting for inbox - hash changed (70202c72 → 315637b7)
[DEBUG] 1 book(s) need processing

Found 1 book in the inbox matching tower (ignoring 11))""",
            True,
        ),
        (
            (
                "-------------------------  ⌐◒-◒  auto-m4b • 2024-04-12 18:53:01  -------------------------",
                "Watching for books in /path/to/inbox ꨄ︎",
                "",
                "[DEBUG] Waiting for inbox updates: 1 (70202c72 → 5ad760a2)",
                "-------------------------  ⌐◒-◒  auto-m4b • 2024-04-12 18:53:01  ----------------------------------",
                "Watching for books in /path/to/inbox ꨄ︎",
                "",
                " *** New activity detected in the inbox...",
            ),
            True,
        ),
    ],
)
def test_is_banner(test_input, expected):
    if isinstance(test_input, tuple):
        assert testutils.is_banner(*test_input) == expected
    else:
        assert testutils.is_banner(test_input) == expected
