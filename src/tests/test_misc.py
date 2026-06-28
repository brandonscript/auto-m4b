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


basic_in_tests = [
    ([1], [1, 2, 3], True),
    ([1, 2], [1, 2, 3], True),
    ([1, 2, 3], [1, 2, 3], True),
    ([1, 2, 3], [1], True),
    ([1, 2, 3], [1, 2], True),
    ([3, 2, 1], [1, 2, 3], True),
    ([1, 2, 3], [4], False),
    ([4], [1, 2, 3], False),
    ([1, 2, 3], [4, 5, 6], False),
    ([4, 5, 6], [1, 2, 3], False),
    (["a"], ["a", "b", "c"], True),
    (["a", "b"], ["a", "b", "c"], True),
    (["a", "b", "c"], ["a", "b", "c"], True),
    (["a", "b", "c"], ["a"], True),
    (["a", "b", "c"], ["a", "b"], True),
    (["a", "b", "c"], ["d", "e", "f"], False),
    (["d", "e", "f"], ["a", "b", "c"], False),
    ([1, 2, 3], [1, "a", 2, "b", 3, "c"], True),
    ([1, "a", 2, "b", 3, "c"], [1, 2, 3], True),
    ([1, 2, 3], [1, 2, "a", 3, 4, "b", 5, 6, "c"], True),
    ([1, 2, "a", 3, 4, "b", 5, 6, "c"], [1, 2, 3], True),
]


@pytest.mark.parametrize(
    "l1, l2, expected",
    basic_in_tests,
)
def test_any_in(l1, l2, expected):
    from src.lib.misc import any_in

    assert any_in(l1, l2) == expected


@pytest.mark.parametrize(
    "l1, l2, insensitive, expected",
    [
        *[(t[0], t[1], False, t[2]) for t in basic_in_tests],
        (["apple"], ["apple pie", "crabapple", "pineapple", "pears"], False, True),
        (["apple pie", "crabapple", "pineapple", "pears"], ["apple"], False, True),
        (["Apple"], ["apple pie", "crabapple", "pineapple", "pears"], True, True),
        (["APPLE pie", "crabapple", "pineapple", "pears"], ["apple"], True, True),
        (["bananas"], ["apple pie", "crabapple", "pineapple", "pears"], True, False),
        (["pearnanas", "crabapple", "pineapple", "pears"], ["bananas"], True, False),
        (["Apple"], ["apple pie", "crabapple", "pineapple", "pears"], False, False),
        (["APPLE pie", "crabApple", "pineApple", "pears"], ["apple"], False, False),
        ([123, 456, 789], [123, 456, 789], False, True),
        ([123, 456, 789], [123, 456, 789], True, True),
        ([123, 456, 789], [123456789], False, True),
        ([123, 456, 789], [123456789], True, True),
        (
            ["Dark Knight Station Origins.m4a"],
            [
                "Dark Knight Station Origins",
                "Wizard's Butler",
            ],
            False,
            True,
        ),
        (
            ["Wizard's Butler - [Wizard's Butler 01.0] The Wizard's Butler"],
            [
                "Dark Knight Station Origins",
                "Wizard's Butler",
            ],
            False,
            True,
        ),
    ],
)
def test_any_matching(l1, l2, insensitive, expected):
    from src.lib.misc import any_matching

    assert any_matching(l1, l2, case_insensitive=insensitive) == expected
