import pytest

from lib.compare import get_size_similarity

kb = 1000
kb_10 = 10 * kb
kb_100 = 100 * kb
kb_1000 = 1000 * kb

mb = 1000 * kb
mb_10 = 10 * mb
mb_100 = 100 * mb

gb = 1000 * mb


@pytest.mark.parametrize(
    "name, b, m, expected",
    [
        # Identical sizes
        ("= 0b", [0, 0], 1, 1.0),
        ("= 0b (10x)", [0, 0], 10, 1.0),
        ("= 0b (100x)", [0, 0], 100, 1.0),
        ("= 0b (1000x)", [0, 0], 1000, 1.0),
        ("= 1b", [1, 1], 1, 1.0),
        ("= 10b (10x)", [1, 1], 10, 1.0),
        ("= 100b", [100, 100], 1, 1.0),
        ("= 100b (100x)", [1, 1], 100, 1.0),
        ("= 1kb", [kb, kb], 1, 1.0),
        ("= 1kb (10x)", [100, 100], 10, 1.0),
        ("= 1kb (1000x)", [1, 1], 1000, 1.0),
        ("= 10kb (10x)", [kb, kb], 10, 1.0),
        ("= 10kb (100x)", [100, 100], 100, 1.0),
        ("= 100kb (100x)", [kb, kb], 100, 1.0),
        ("= 100kb (1000x)", [100, 100], 1000, 1.0),
        ("= 1mb", [mb, mb], 1, 1.0),
        ("= 1mb (1000x)", [kb, kb], 1000, 1.0),
        ("= 10mb", [mb_10, mb_10], 1, 1.0),
        ("= 10mb (10x)", [kb_100, kb_100], 10, 1.0),
        ("= 100mb", [mb_100, mb_100], 1, 1.0),
        ("= 100mb (10x)", [mb_10, mb_10], 10, 1.0),
        ("= 100mb (100x)", [mb, mb], 100, 1.0),
        # Different sizes
        ("diff 1b", [0, 1, 2], 1, 0.999),
        ("diff 1b", [10, 11, 12], 1, 0.999),
        ("diff 10b", [0, 10, 20], 1, 0.998),
        ("diff 10b", [10, 20, 30], 1, 0.998),
        ("diff 10b (10x)", [0, 1, 2], 10, 0.998),
        ("diff 10b (10x)", [10, 11, 12], 10, 0.998),
        ("diff 100b (10x)", [0, 10, 20], 10, 0.979),
        ("diff 100b (10x)", [10, 20, 30], 10, 0.979),
        ("diff 100b (100x)", [0, 1, 2], 100, 0.979),
        ("diff 100b (100x)", [10, 11, 12], 100, 0.979),
        ("diff 1kb (100x)", [0, 10, 20], 100, 0.911),
        ("diff 1kb (1000x)", [0, 1, 2], 1000, 0.911),
        ("diff 1kb (1000x)", [10, 11, 12], 1000, 0.911),
        ("diff 1kb (100x)", [10, 20, 30], 100, 0.911),
        ("diff 10kb (1000x)", [0, 10, 20], 1000, 0.745),
        ("diff 110b", [10, 110, 220], 1, 0.978),
        ("diff 1.1kb", [100, 1.1 * kb, 2.2 * kb], 1, 0.909),
        ("diff 1.1kb (10x)", [10, 110, 220], 10, 0.909),
        ("diff 11kb (10x)", [100, 1.1 * kb, 2.2 * kb], 10, 0.74),
        ("diff 11kb (100x)", [10, 110, 220], 100, 0.74),
        ("diff 110kb", [10 * kb, 110 * kb, 220 * kb], 1, 0.401),
        ("diff 110kb (100x)", [100, 1.1 * kb, 2.2 * kb], 100, 0.401),
        ("diff 110kb (1000x)", [10, 110, 220], 1000, 0.401),
        ("diff 1.1mb", [100 * kb, 1.1 * mb, 2.2 * mb], 1, 0.0),
        ("diff 1.1mb (1000x)", [100, 1.1 * kb, 2.2 * kb], 1000, 0.0),
        ("diff 1.1mb (10000x)", [10, 110, 220], 10**4, 0.0),
        ("diff 11mb (100x)", [1000, 11 * kb, 22 * kb], 100, 0.0),
        ("diff 11mb", [1 * mb, 11 * mb, 22 * mb], 1, 0),
        ("diff 11mb (10x)", [100 * kb, 1.1 * mb, 2.2 * mb], 10, 0),
        ("diff 11mb (100x)", [10 * kb, 110 * kb, 220 * kb], 100, 0),
        ("diff 11mb (0.1x)", [10 * mb, 110 * mb, 220 * mb], 0.1, 0),
        ("diff 110mb", [10 * mb, 110 * mb, 220 * mb], 1, 0),
    ],
)
def test_get_size_similarity(name, b, m, expected):
    assert get_size_similarity(b, byte_multiplier=m, zero_point=6.05, curve_strength=4) == expected


def test_get_size_similarity_real_world():
    files = [
        ("01 - Opening credits.mp3", 568918),
        ("02 - Dedication.mp3", 156067),
        ("03 - Prologue.mp3", 5277215),
        ("04 - Part I.mp3", 103397),
        ("05 - Chapter One - Cassie.mp3", 19411574),
        ("06 - Chapter Two - Emma.mp3", 18417873),
        ("07 - Chapter Three - Kat.mp3", 18387155),
        ("08 - Chapter Four - Cassie.mp3", 17435779),
        ("09 - Chapter Five - Emma.mp3", 20147912),
        ("10 - Chapter Six - Kat.mp3", 20742873),
        ("11 - Chapter Seven - Cassie.mp3", 22744072),
        ("12 - Chapter Eight - Emma.mp3", 34265948),
        ("13 - Chapter Nine - Kat.mp3", 17353017),
        ("14 - Chapter Ten - Cassie.mp3", 24684443),
        ("15 - Part II.mp3", 103399),
        ("16 - Chapter Eleven - Emma.mp3", 12708034),
        ("17 - Chapter Twelve - Kat.mp3", 19854193),
        ("18 - Chapter Thirteen - Cassie.mp3", 18779944),
        ("19 - Chapter Fourteen - Emma.mp3", 17559917),
        ("20 - Chapter Fifteen - Kat.mp3", 16231743),
        ("21 - Chapter Sixteen - Cassie.mp3", 11566697),
        ("22 - Chapter Seventeen - Emma.mp3", 16893483),
        ("23 - Chapter Eighteen - Kat.mp3", 11516537),
        ("24 - Chapter Nineteen - Cassie.mp3", 13785436),
        ("25 - Chapter Twenty - Emma.mp3", 13558790),
        ("26 - Chapter Twenty-One - Kat.mp3", 13412405),
        ("27 - Chapter Twenty-Two - Cassie.mp3", 12046938),
        ("28 - Chapter Twenty-Three - Emma.mp3", 12357273),
        ("29 - Chapter Twenty-Four - Kat.mp3", 19589635),
        ("30 - Chapter Twenty-Five - Cassie.mp3", 8070580),
        ("31 - Chapter Twenty-Six - Emma.mp3", 7547394),
        ("32 - Chapter Twenty-Seven - Kat.mp3", 12150695),
        ("33 - Chapter Twenty-Eight - Cassie.mp3", 11634416),
        ("34 - Chapter Twenty-Nine - Emma.mp3", 12238466),
        ("35 - Chapter Thirty - Kat.mp3", 17007891),
        ("36 - Epilogue.mp3", 8828509),
        ("38 - Credits.mp3", 882998),
        ("37 - Authors' Note.mp3", 2012128),
    ]
    assert get_size_similarity([f[1] for f in files], ignore_smaller_than=10 * mb) == 0.306
