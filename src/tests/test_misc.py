import pytest


# Write a bunch of @pytest.mark.parameterize tests
# to test `flatlist()` which takes an arbitrarily nested list or list of lists and flattens them.
@pytest.mark.parametrize(
    "input, expected",
    [
        ([1, 2, 3], [1, 2, 3]),
        ([1, [2, 3], 4], [1, 2, 3, 4]),
        ([[1, 2], [3, 4], [5, 6]], [1, 2, 3, 4, 5, 6]),
        ([[1, [2, 3]], [4, [5, 6]]], [1, 2, 3, 4, 5, 6]),
        ([[1, [2, 3]], [4, [5, 6], [7, 8]]], [1, 2, 3, 4, 5, 6, 7, 8]),
        ([[1, [2, 3]], [4, [5, 6], [7, 8, [9, 10]]]], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
        ([[1, [2, 3]], [4, [5, 6], [7, 8, [9, 10, [11, 12]]]]], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]),
    ],
)
def test_flatlist(input, expected):
    from src.lib.misc import flatlist

    assert flatlist(input) == expected
