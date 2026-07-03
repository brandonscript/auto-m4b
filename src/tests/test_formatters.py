import pytest

duration_tests = [
    (0, False, "-"),
    (0, True, "-"),
    (1, False, "00m:01s"),
    (1, True, "0h:00m:01s"),
    (59, False, "00m:59s"),
    (59, True, "0h:00m:59s"),
    (60, False, "01m:00s"),
    (60, True, "0h:01m:00s"),
    (61, False, "01m:01s"),
    (61, True, "0h:01m:01s"),
    (3599, False, "59m:59s"),
    (3599, True, "0h:59m:59s"),
    (3600, False, "1h:00m:00s"),
    (3601, False, "1h:00m:01s"),
    (3661, False, "1h:01m:01s"),
    (27733, False, "7h:42m:13s"),
    (27733, True, "7h:42m:13s"),
    (43199, False, "11h:59m:59s"),
    (43200, False, "12h:00m:00s"),
    (43201, False, "12h:00m:01s"),
]


@pytest.mark.parametrize(
    "input, always_hours, units, expected",
    [t for t in [(i, a, u, e) for i, a, e in duration_tests for u in [False, True]]],
)
def test_human_elapsed_time(input: int, always_hours: bool, units: bool, expected: str):
    from src.lib.formatters import format_duration

    expected_no_units = "".join([c for c in expected if c not in "hms"])
    assert format_duration(
        input, "human", always_show_hours=always_hours, show_units=units
    ) == (expected if units else expected_no_units)


@pytest.mark.parametrize(
    "in_bitrate, expected",
    [
        (0, 24),
        (1, 24),
        (12, 24),
        (16, 24),
        (23, 24),
        (24, 24),
        (25, 32),
        (31, 32),
        (33, 40),
        (39, 40),
        (40, 40),
        (41, 48),
        (47, 48),
        (48, 48),
        (49, 56),
        (55, 56),
        (56, 56),
        (57, 64),
        (64, 64),
        (65, 80),
        (79, 80),
        (80, 80),
        (81, 96),
        (95, 96),
        (96, 96),
        (97, 112),
        (111, 112),
        (112, 112),
        (113, 128),
        (127, 128),
        (128, 128),
        (129, 160),
        (159, 160),
        (160, 160),
        (161, 192),
        (191, 192),
        (192, 192),
        (193, 224),
        (223, 224),
        (224, 224),
        (225, 256),
        (255, 256),
        (256, 256),
        (257, 320),
        (319, 320),
        (320, 320),
        (321, 320),
        (383, 320),
        (384, 320),
        (896, 320),
        (897, 320),
    ],
)
def test_get_nearest_standard_bitrate(in_bitrate, expected):
    from src.lib.formatters import get_nearest_standard_bitrate

    assert get_nearest_standard_bitrate(in_bitrate) == expected
    if in_bitrate:
        assert get_nearest_standard_bitrate(in_bitrate * 1000) == expected * 1000


listify_arrs = [
    [],
    ["apple"],
    ["apple", "banana"],
    ["apple", "banana", "carrot"],
    [1, 2, 3],
]

listify_opts = [{}, {"bul": "•"}, {"bul": "→", "indent": 2}]


def listify_expected(indent: int = 1):

    i = " " * indent
    return [
        [
            "",
            f"{i}- apple",
            f"{i}- apple\n{i}- banana",
            f"{i}- apple\n{i}- banana\n{i}- carrot",
            f"{i}- 1\n{i}- 2\n{i}- 3",
        ],
        [
            "",
            f"{i}• apple",
            f"{i}• apple\n{i}• banana",
            f"{i}• apple\n{i}• banana\n{i}• carrot",
            f"{i}• 1\n{i}• 2\n{i}• 3",
        ],
        [
            "",
            f"{i}→ apple",
            f"{i}→ apple\n{i}→ banana",
            f"{i}→ apple\n{i}→ banana\n{i}→ carrot",
            f"{i}→ 1\n{i}→ 2\n{i}→ 3",
        ],
    ]


@pytest.mark.parametrize(
    "test_arr, opts, expected",
    [
        (a, o, listify_expected(o.get("indent", 0))[e][i])
        for e, o in enumerate(listify_opts)
        for i, a in enumerate([a for a in listify_arrs])
    ],
)
def test_listify(test_arr, opts, expected):
    from src.lib.formatters import listify

    assert listify(test_arr, **opts) == expected
