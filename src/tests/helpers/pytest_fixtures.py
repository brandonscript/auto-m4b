import os
import random
import shutil
import sys
import time
from pathlib import Path

import dotenv
import pytest

from src.lib.fs_utils import clean_dirs, find_adjacent_files_with_same_basename
from src.lib.id3_utils import write_id3_tags_mutagen
from src.lib.inbox_state import InboxState
from src.tests.helpers.pytest_dumps import FIXTURES_ROOT, GIT_ROOT, MOCKED, TEST_DIRS
from src.tests.helpers.pytest_utils import testutils

sys.path.append(str(Path(__file__).parent.parent))

from src.lib.audiobook import Audiobook
from src.lib.misc import get_git_root, load_env


@pytest.fixture(autouse=True, scope="session")
def setup_teardown():
    from src.lib.config import cfg

    # remove everything in the inbox that starts with `mock_book_`
    for f in TEST_DIRS.inbox.rglob("mock_book_*"):
        testutils.rm(f)

    cfg.FATAL_FILE.unlink(missing_ok=True)

    for env in get_git_root().glob(".env.local*"):
        dotenv.load_dotenv(env)

    with testutils.set_on_complete("test_do_nothing"):
        load_env(GIT_ROOT / ".env.test", clean_working_dirs=True)

        yield

        cfg.FATAL_FILE.unlink(missing_ok=True)


@pytest.fixture(scope="function", autouse=False)
def reset_failed():
    InboxState().clear_failed()
    os.environ.pop("FAILED_BOOKS", None)
    yield
    InboxState().clear_failed()
    os.environ.pop("FAILED_BOOKS", None)


@pytest.fixture(scope="function", autouse=False)
def reset_match_filter():
    from src.lib.config import cfg

    orig_env_match_filter = os.environ.get("MATCH_FILTER", None)
    orig_cfg_match_filter = cfg.MATCH_FILTER
    yield
    if orig_env_match_filter is not None:
        InboxState().set_match_filter(orig_env_match_filter)
        return
    InboxState().set_match_filter(orig_cfg_match_filter)


@pytest.fixture(scope="function", params=["fixture_name"])
def indirect_fixture(request: pytest.FixtureRequest):
    return request.getfixturevalue(request.param)


@pytest.fixture(scope="function", params=["fixture_names"])
def indirect_fixtures(request: pytest.FixtureRequest):
    if isinstance(request.param, str):
        return request.getfixturevalue(request.param)
    fixtures = (
        request.param if any((isinstance(request.param, list), isinstance(request.param, tuple))) else [request.param]
    )
    return tuple(request.getfixturevalue(f) for f in fixtures)


def rm_from_inbox(*names: str):
    for name in names:
        inbox = TEST_DIRS.inbox / name
        shutil.rmtree(inbox, ignore_errors=True)
        testutils.print(f"Cleaning up {inbox}")


def rm_from_converted(*names: str):
    for name in names:
        converted = TEST_DIRS.converted / name
        if converted.is_dir():
            shutil.rmtree(converted, ignore_errors=True)
        elif converted.is_file():
            converted.unlink(missing_ok=True)
        testutils.print(f"Cleaning up {converted}")


def load_test_fixture(
    name: str,
    *,
    exclusive: bool = False,
    override_name: str | None = None,
    match_filter: str | None = None,
    cleanup_inbox: bool = False,
):
    src_dir = FIXTURES_ROOT / name
    src_mp3 = src_dir.with_suffix(".mp3")
    src_m4b = src_dir.with_suffix(".m4b")

    src = next((f for f in [src_mp3, src_m4b, src_dir] if f.exists()), None)
    if not src or not src.exists():
        raise FileNotFoundError(f"Fixture {name} not found. Does it exist in {FIXTURES_ROOT}?")
    if src.is_dir():
        dst = TEST_DIRS.inbox / (override_name or name)
        dst.mkdir(parents=True, exist_ok=True)

        for f in src.glob("**/*"):
            dst_f = dst / f.relative_to(src)
            if f.is_file() and not dst_f.exists():
                dst_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(f, dst_f)

        # if any files in dst are not in src, delete them
        for f in dst.glob("**/*"):
            src_f = src / f.relative_to(dst)
            if f.is_file() and not src_f.exists():
                f.unlink()
    else:
        dst = TEST_DIRS.inbox / Path(override_name or name).with_suffix(src.suffix)
        shutil.rmtree(dst.with_suffix(""), ignore_errors=True)
        if not dst.exists() or (src.stat().st_size != dst.stat().st_size):
            shutil.copy(src, dst)

        for f in find_adjacent_files_with_same_basename(src):
            dst_f = dst.with_suffix(f.suffix)
            if not dst_f.exists() or (f.stat().st_size != dst_f.stat().st_size):
                shutil.copy(f, dst_f)

    if exclusive or match_filter is not None:
        testutils.set_match_filter(match_filter or name)

    converted = TEST_DIRS.converted / (override_name or name)
    converted_dir = converted.with_suffix("")
    rm_from_converted(override_name or name)
    shutil.rmtree(converted_dir, ignore_errors=True)

    yield Audiobook(dst)

    if cleanup_inbox:
        rm_from_inbox(name)


def load_test_fixtures(
    *names: str,
    exclusive: bool = False,
    override_names: list[str] | None = None,
    match_filter: str | None = None,
    cleanup_inbox: bool = False,
    request: pytest.FixtureRequest | None = None,
):
    if exclusive and not match_filter:
        short_names = [
            n if len(s[:1][0]) < 5 else s[:1][0]
            for n, s in [("_".join(s[:2]), s) for s in [n.split("_") for n in (override_names or names)]]
        ]
        match_filter = rf"^({'|'.join(short_names)})"

    fixtures: list[Audiobook] = []
    for name, override in zip(names, override_names or names):
        fixtures.extend(load_test_fixture(name, match_filter=match_filter, override_name=override))

    if cleanup_inbox:
        if not request:
            raise ValueError("cleanup_inbox requires `request` to be a pytest.FixtureRequest")
        request.addfinalizer(lambda: rm_from_inbox(*names))

    return fixtures


@pytest.fixture(scope="function")
def bitrate_vbr__mp3():
    yield from load_test_fixture("bitrate_vbr__mp3", exclusive=True)


@pytest.fixture(scope="function")
def bitrate_cbr__mp3():
    yield from load_test_fixture("bitrate_cbr__mp3", exclusive=True)


@pytest.fixture(scope="function")
def basic_no_cover__single_mp3():
    yield from load_test_fixture("basic_no_cover__single_mp3", exclusive=True)


@pytest.fixture(scope="function")
def basic_no_cover__single_m4b():
    yield from load_test_fixture("basic_no_cover__single_m4b", exclusive=True)


@pytest.fixture(scope="function")
def basic_with_cover__single_mp3():
    yield from load_test_fixture("basic_with_cover__single_mp3", exclusive=True)


@pytest.fixture(scope="function")
def basic_with_cover__single_m4b():
    yield from load_test_fixture("basic_with_cover__single_m4b", exclusive=True)


@pytest.fixture(scope="function")
def basic_no_cover__standalone_mp3():
    other_cover = FIXTURES_ROOT / "LeviathanWakes.jpg"
    if not (TEST_DIRS.inbox / other_cover.name).exists():
        shutil.copy(other_cover, TEST_DIRS.inbox / other_cover.name)
    yield from load_test_fixture("basic_no_cover__standalone_mp3", exclusive=True)


@pytest.fixture(scope="function")
def basic_no_cover__standalone_m4b():
    yield from load_test_fixture("basic_no_cover__standalone_m4b", exclusive=True)


@pytest.fixture(scope="function")
def basic_with_cover__standalone_mp3():
    yield from load_test_fixture("basic_with_cover__standalone_mp3", exclusive=True)


@pytest.fixture(scope="function")
def basic_with_cover__standalone_m4b():
    yield from load_test_fixture("basic_with_cover__standalone_m4b", exclusive=True)


@pytest.fixture(scope="function")
def bitrate_nonstandard__mp3():
    yield from load_test_fixture("bitrate_nonstandard__mp3", exclusive=True)


@pytest.fixture(scope="function")
def graphic_audio__single_m4b():
    yield from load_test_fixture("graphic_audio__single_m4b", exclusive=True)


@pytest.fixture(scope="function")
def tiny__flat_mp3():
    yield from load_test_fixture("tiny__flat_mp3", exclusive=True)


@pytest.fixture(scope="function")
def tower_treasure__flat_mp3():
    yield from load_test_fixture("tower_treasure__flat_mp3", exclusive=True)


@pytest.fixture(scope="function")
def house_on_the_cliff__flat_mp3():
    yield from load_test_fixture("house_on_the_cliff__flat_mp3", exclusive=True)


@pytest.fixture(scope="function")
def old_mill__multidisc_mp3():
    yield from load_test_fixture("old_mill__multidisc_mp3", exclusive=True)


@pytest.fixture(scope="function")
def missing_chums__mixed_mp3():
    shutil.rmtree(TEST_DIRS.inbox / "missing_chums__mixed_mp3", ignore_errors=True)
    yield from load_test_fixture("missing_chums__mixed_mp3", exclusive=True)


@pytest.fixture(scope="function")
def tower_treasure__nested_mp3():
    yield from load_test_fixture("tower_treasure__nested_mp3", exclusive=True)


@pytest.fixture(scope="function")
def hardy_boys__flat_mp3(request: pytest.FixtureRequest):
    yield load_test_fixtures(
        "tower_treasure__flat_mp3",
        "house_on_the_cliff__flat_mp3",
        exclusive=True,
        request=request,
    )


@pytest.fixture(scope="function")
def all_hardy_boys(request: pytest.FixtureRequest):
    yield load_test_fixtures(
        "tower_treasure__flat_mp3",
        "house_on_the_cliff__flat_mp3",
        "old_mill__multidisc_mp3",
        "missing_chums__mixed_mp3",
        exclusive=True,
        request=request,
    )


@pytest.fixture(scope="function")
def the_crusades_through_arab_eyes__flat_mp3():
    yield from load_test_fixture("the_crusades_through_arab_eyes__flat_mp3", exclusive=True)


@pytest.fixture(scope="function")
def the_sunlit_man__flat_mp3():
    yield from load_test_fixture("the_sunlit_man__flat_mp3", exclusive=True)


@pytest.fixture(scope="function")
def touch_of_frost__flat_mp3():
    yield from load_test_fixture(
        "touch_of_frost__flat_mp3",
        exclusive=True,
        override_name="01 - Touch of Frost (2011)",
    )


@pytest.fixture(scope="function")
def count_of_monte_cristo__flat_mp3():
    yield from load_test_fixture(
        "count_of_monte_cristo__flat_mp3",
        exclusive=True,
        override_name="Alexandre Dumas   The Count of Monte Cristo",
    )


@pytest.fixture(scope="function")
def conspiracy_theories__flat_mp3():
    yield from load_test_fixture(
        "conspiracy_theories__flat_mp3",
        exclusive=True,
        override_name="The Great Courses - Conspiracies & Conspiracy Theories What We Should and Shouldn't Believe - and Why",
        cleanup_inbox=True,
    )


@pytest.fixture(scope="function")
def blackmail_bibingka__flat_m4b():

    yield from load_test_fixture(
        "blackmail_bibingka__flat_m4b",
        exclusive=True,
        override_name="Blackmail and Bibingka A Tita Rosie's Kitchen Mystery, Book 3",
        match_filter="^(Blackmail and Bibingka)",
        cleanup_inbox=True,
    )


@pytest.fixture(scope="function")
def authors_guide_to_murder__flat_mp3():

    yield from load_test_fixture(
        "authors_guide_to_murder__flat_mp3",
        exclusive=True,
        match_filter="^authors_guide_to_murder",
        cleanup_inbox=True,
    )


@pytest.fixture(scope="function")
def Chanur_Series(reset_inbox_state):
    series = "chanur_series__series_mp3"
    override_series = "Chanur Series"

    files = lambda s: [
        s,
        f"{s}/01 - Pride Of Chanur",
        f"{s}/02 - Chanur's Venture",
        f"{s}/03 - Kif Strikes Back",
        f"{s}/04 - Chanur's Homecoming",
        f"{s}/05 - Chanur's Legacy",
    ]

    yield load_test_fixtures(
        *files(series),
        override_names=files(override_series),
        exclusive=True,
        match_filter=("^(chanur)"),
    )


@pytest.fixture(scope="function", autouse=False)
def benedict_society__mp3():

    dir_name = TEST_DIRS.inbox / "01 - The Mysterious Benedict Society"

    def _path(i: int) -> Path:
        return dir_name / f"Trenton_Lee_Stewart_-_MBS1_-_The_Mysterious_Benedict_Society_({i:02}of11).mp3"

    for i in range(1, 12):
        testutils.make_mock_file(_path(i))

    testutils.set_match_filter("Benedict")

    yield Audiobook(dir_name)

    testutils.set_match_filter(None)

    shutil.rmtree(dir_name, ignore_errors=True)


@pytest.fixture(scope="function", autouse=False)
def nathan_lowell__nested_series_m4a():
    # dir_name = TEST_DIRS.inbox / "nathan_lowell__nested_series_m4a"
    yield from load_test_fixture(
        "nathan_lowell__nested_series_m4a",
        exclusive=True,
        override_name="Nathan Lowell",
        match_filter="^(Nathan Lowell)",
    )


@pytest.fixture(scope="function", autouse=False)
def secret_project_series__nested_flat_mixed():
    yield from load_test_fixture(
        "secret_project_series__nested_flat_mixed",
        exclusive=True,
        override_name="Sanderson - Secret Project Series",
        match_filter="^(Sanderson.*Secret Project Series)",
    )


@pytest.fixture(scope="function", autouse=False)
def the_hobbit__multidisc_mp3():

    dirname = TEST_DIRS.inbox / "the_hobbit__multidisc_mp3"

    # remove any mp3 files in the root of this dir
    if dirname.exists():
        for f in dirname.iterdir():
            if f.is_file() and f.suffix == ".mp3":
                f.unlink(missing_ok=True)
    yield from load_test_fixture("the_hobbit__multidisc_mp3", exclusive=True)


@pytest.fixture(scope="function", autouse=False)
def the_shining__flat_mp3():
    # Contains out of order roman numerals
    yield from load_test_fixture("the_shining__flat_mp3", exclusive=True)


@pytest.fixture(scope="function", autouse=False)
def roman_numeral__mp3():
    dir_name = TEST_DIRS.inbox / "Roman Numeral Book"

    def _path(i: int, n: str) -> Path:
        return dir_name / f"Roman_Numeral_Book_{n} - Part_{i}.mp3"

    for i, n in enumerate(["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]):
        testutils.make_mock_file(_path(i, n))

    testutils.set_match_filter("Roman Numeral Book")

    yield Audiobook(dir_name)

    testutils.set_match_filter(None)

    shutil.rmtree(dir_name, ignore_errors=True)


@pytest.fixture(scope="function", autouse=False)
def fails__mixed_mp3():
    """A mixed book that fails to convert because its structure can't be determined."""
    name = "fails__mixed_mp3"
    book = TEST_DIRS.inbox / name
    book.mkdir(parents=True, exist_ok=True)

    for i in range(1, 6):
        testutils.make_mock_file(book / f"fails__mixed_mp3_{i}.mp3")
    d1 = book / "subdir_5_1"
    d1.mkdir(parents=True, exist_ok=True)
    d1f1 = d1 / "balloon_baboon_falls_book3__mp3.mp3"
    d1f2 = d1 / "supermoons_are_orange_and_sometimes_red_wow!__mp3.mp3"

    d2 = book / "yet_another_subdir_42_19"
    d2.mkdir(parents=True, exist_ok=True)
    d2f1 = d2 / "book2_the_constant_noise_that_keeps_humming_in_my_kitchen__mp3.mp3"
    d2f2 = d2 / "everest_is_a_very_tall_mountain__mp3.mp3"
    for f in [d1f1, d1f2, d2f1, d2f2]:
        testutils.make_mock_file(f)

    testutils.set_match_filter(name)
    yield Audiobook(book)
    testutils.set_match_filter(None)
    shutil.rmtree(book, ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "build" / name, ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "fix" / name, ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "merge" / name, ignore_errors=True)


@pytest.fixture(scope="function", autouse=False)
def blank_audiobook():
    """Create a fake mp3 audiobook with one completely valid audiofile that plays a tone A4 for 2 seconds."""
    book = TEST_DIRS.inbox / "blank_audiobook"
    book.mkdir(parents=True, exist_ok=True)

    # write a completely valid audiofile that plays a tone A4 for 2 seconds
    with open(book / f"blank_audiobook_01.mp3", "wb") as f:
        f.write(testutils.blank_audiobook_data)
    with open(book / f"blank_audiobook_02.mp3", "wb") as f:
        f.write(testutils.blank_audiobook_data)

    testutils.set_match_filter("blank_audiobook")
    yield Audiobook(book)
    testutils.set_match_filter(None)
    shutil.rmtree(book, ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "build" / "blank_audiobook", ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "fix" / "blank_audiobook", ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "merge" / "blank_audiobook", ignore_errors=True)


@pytest.fixture(scope="function", autouse=False)
def mock_id3_tags():
    def write_tags(*files_and_tags: tuple[Path, dict[str, str]]):
        from src.lib.id3_tags import Id3Tags

        for f, tags in files_and_tags:
            write_id3_tags_mutagen(f, tags)

        return [(t := Id3Tags.from_file(f)) and t.to_dict() for f, _ in files_and_tags]

    return write_tags


@pytest.fixture(scope="function", autouse=False)
def corrupt_audiobook():
    """Create a fake mp3 audiobook with a corrupt file."""
    book = TEST_DIRS.inbox / "corrupt_audiobook"
    book.mkdir(parents=True, exist_ok=True)
    with open(book / f"corrupt_audiobook.mp3", "wb") as f:
        f.write(b"\xff\xfb\xd6\x04")
        # write 20kb of random data, but the first 4 bytes are corrupt
        f.write(os.urandom(1024 * 20))
    testutils.set_match_filter("corrupt_audiobook")
    yield Audiobook(book)
    testutils.set_match_filter(None)
    shutil.rmtree(book, ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "build" / "corrupt_audiobook", ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "fix" / "corrupt_audiobook", ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "merge" / "corrupt_audiobook", ignore_errors=True)


@pytest.fixture(scope="function", autouse=False)
def test_out_chanur_txt():
    """Loads 'test_out_chanur.txt' from the fixtures directory."""
    with open(FIXTURES_ROOT / "test_out_chanur.txt", "r") as f:
        yield f.read()


@pytest.fixture(scope="function", autouse=False)
def test_out_tower_txt():
    """Loads 'test_out_tower.txt' from the fixtures directory."""
    with open(FIXTURES_ROOT / "test_out_tower.txt", "r") as f:
        yield f.read()


@pytest.fixture(scope="function", autouse=False)
def not_an_audio_file():
    """Create a fake mp3 audiobook with a corrupt file."""
    book = TEST_DIRS.inbox / "not_an_audio_file"
    book.mkdir(parents=True, exist_ok=True)
    with open(book / f"not_an_audio_file.mp3", "w") as f:
        f.write("This is not an audio file")
        f.write("a" * 1024 * 5)
    yield Audiobook(book)
    shutil.rmtree(book, ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "build" / "not_an_audio_file", ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "fix" / "not_an_audio_file", ignore_errors=True)
    shutil.rmtree(TEST_DIRS.working / "merge" / "not_an_audio_file", ignore_errors=True)


@pytest.fixture(scope="function", autouse=False)
def mock_inbox(setup_teardown, requires_empty_inbox):
    """Populate INBOX_FOLDER with mocked sample audiobooks."""

    # make 4 sample audiobooks using nealy empty txt files (~5kb) as pretend mp3 files.
    for i, f in enumerate(MOCKED.flat_dirs[:4]):
        f.mkdir(parents=True, exist_ok=True)
        for j in range(1, 4):
            testutils.make_mock_file(f / f"mock_book_{i + 1} - part_{j}.mp3")

    for f in ["01", "02", "03"]:
        testutils.make_mock_file(MOCKED.flat_dirs[-1] / f"{f} - mock_book_5.mp3")

    # make a book with a single flat nested folder
    for i in range(1, 4):
        testutils.make_mock_file(MOCKED.nested_dir / "inner_dir" / f"mock_book_nested - part_{i}.mp3")

    STANDALONE_FILES = MOCKED.standalone_files

    # make a deeply nested container dir
    list(map(testutils.make_mock_file, [f for f in MOCKED.container_dirs if "." in f.name]))
    for f in [*MOCKED.container_dir_d1_standalone_files, *MOCKED.container_dir_d2_standalone_files]:
        STANDALONE_FILES.append(f)

    # make a multi-series directory
    names = ["Dawn", "High Noon", "Dusk"]
    for s in ["1", "2", "3"]:
        name = names[int(s) - 1]
        series = MOCKED.series_parent_dir / f"{name} - Book {s}"
        series.mkdir(parents=True, exist_ok=True)
        for i in range(1, 2 + int(s)):
            testutils.make_mock_file(series / f"mock_book_series - ch. {i}.mp3")

    # make a multi-disc book
    for d in range(1, 5):
        disc = MOCKED.multi_disc_dir / f"Disc {d} of 4"
        disc.mkdir(parents=True, exist_ok=True)
        for i in range(1, 3):
            testutils.make_mock_file(disc / f"mock_book_multi_disc{d} - ch_{d+(d-i+1)}.mp3")

    # make a mutli-part book
    romans = ["I", "II", "III", "IV"]
    for i in range(1, 5):
        for j in range(1, 3):
            testutils.make_mock_file(
                MOCKED.multi_part_dir
                / f"Part {i:02} - {romans[i-1]}"
                / f"mock_book_multi_part - pt.{i:02} - {romans[i-1]} - ch_{j}.mp3"
            )

    # make a multi-disc book with extras
    words = ["science", "principles", "observation", "acceleration"]
    for d in range(1, 5):
        disc = MOCKED.multi_disc_dir_with_extras / f"Disc {d} of 4"
        disc.mkdir(parents=True, exist_ok=True)
        for i in range(1, 3):
            testutils.make_mock_file(disc / f"mock_book_multi_disc_dir_with_extras - part_{d+(d-i+1)}.mp3")
        testutils.make_mock_file(disc / f"{words[d-1]}.pdf")
        testutils.make_mock_file(disc / f"notes-{d}.txt")
        testutils.make_mock_file(disc / f"cover-{d}.jpg")

    # make a multi-folder nested dir (not specifically multi-disc or book)
    for i in range(1, 3):
        for j in range(1, 3):
            testutils.make_mock_file(MOCKED.multi_nested_dir / f"nested_{i}" / f"mock_book_multi_nested - {j:02}.mp3")

    # PRAGMA – old, makes multi-part mixed, which isn't a thing right now
    # make a mixed dir with some files in the root, and some in nested dirs
    # for i in range(1, 3):
    #     testutils.make_mock_file(MOCKED.mixed_dir / f"mock_book_mixed - part_{i}.mp3")
    # for i in range(3, 5):
    #     testutils.make_mock_file(
    #         MOCKED.mixed_dir / "nested" / f"mock_book_mixed - part_{i}.mp3"
    #     )
    testutils.make_mock_file(MOCKED.mixed_dir / "mock_book_mixed, a tale of whoa.mp3")
    testutils.make_mock_file(MOCKED.mixed_dir / "mock_book_mixed, a book apart.mp3")
    testutils.make_mock_file(MOCKED.mixed_dir / "nested" / "mock_book_mixed - part_42.mp3")
    testutils.make_mock_file(MOCKED.mixed_dir / "nested" / "mock_book_mixed, random file no. 7.mp3")
    testutils.make_mock_file(MOCKED.mixed_dir / "01 - mixed drinks.mp3")
    testutils.make_mock_file(MOCKED.mixed_dir / "02 - mixed drinks.mp3")
    testutils.make_mock_file(MOCKED.mixed_dir / "03 - mixed drinks.mp3")

    # make standalone files
    for f in STANDALONE_FILES:
        rand_between_51_and_100 = random.randint(51 * 1024, 100 * 1024)
        testutils.make_mock_file(f, size=rand_between_51_and_100)

    # make a single files
    testutils.make_mock_file(MOCKED.single_dir_m4b / "mock_book_single_m4b.m4b")
    testutils.make_mock_file(MOCKED.single_dir_mp3 / "mock_book_single_mp3.mp3")
    testutils.make_mock_file(MOCKED.single_nested_dir_mp3 / "nested_single_mp3" / "mock_book_single_mp3.mp3")

    # make an empty dir
    MOCKED.empty.mkdir(parents=True, exist_ok=True)

    yield TEST_DIRS.inbox

    # remove everything in the inbox that starts with `mock_book_`
    for f in TEST_DIRS.inbox.rglob("mock_book_*"):
        testutils.rm(f)


@pytest.fixture(scope="function", autouse=False)
def mock_inbox_being_copied_to():
    """Runs an async function that updates the inbox every second for `seconds` seconds by creating and deleting a test file."""

    # def wrapper(seconds: int = 5):
    def update_inbox(files: int = 5, delay: float = 0):
        time.sleep(delay)
        testutils.print("Mocking inbox being copied to...")
        for i in range(1, files + 1):
            testutils.make_mock_file(TEST_DIRS.inbox / f"mock_book_{i}.mp3")
            testutils.print(f"Mocked copy to inbox: {i}")
            time.sleep(0.2)
            # testutils.rm(TEST_DIRS.inbox / f"mock_book_{i}.mp3")
        testutils.print("Mocked copy to inbox complete")

        # loop = asyncio.get_event_loop()
        # loop.run_until_complete(update_inbox())

    yield update_inbox

    # cleanup
    for f in TEST_DIRS.inbox.glob("mock_book_*"):
        testutils.rm(f)


@pytest.fixture(scope="function", autouse=False)
def global_test_log():
    orig_log = FIXTURES_ROOT / "sample-auto-m4b.log"
    test_log = TEST_DIRS.converted / "auto-m4b.log"
    test_log.unlink(missing_ok=True)
    shutil.copy2(orig_log, test_log)
    yield test_log
    test_log.unlink(missing_ok=True)


@pytest.fixture(scope="function", autouse=False)
def reset_all(reset_match_filter, reset_failed):

    from src.lib.config import cfg

    InboxState().destroy()  # type: ignore
    inbox = InboxState()
    clean_dirs([TEST_DIRS.archive, TEST_DIRS.converted, TEST_DIRS.working])
    cfg.SLEEP_TIME = 0.1
    cfg.WAIT_TIME = 0.5
    cfg.TEST = True
    cfg.ON_COMPLETE = "test_do_nothing"

    yield

    inbox.reset_inbox()
    cfg.MATCH_FILTER = None  # type: ignore
    cfg.SLEEP_TIME = 0.1
    cfg.WAIT_TIME = 0.5
    cfg.TEST = True
    cfg.ON_COMPLETE = "test_do_nothing"

    clean_dirs([TEST_DIRS.archive, TEST_DIRS.converted, TEST_DIRS.working])
    inbox.destroy()  # type: ignore
    cfg.PID_FILE.unlink(missing_ok=True)
    inbox = InboxState()


@pytest.fixture(scope="function", autouse=False)
def enable_backups():
    testutils.enable_backups()
    yield
    testutils.disable_backups()


@pytest.fixture(scope="function", autouse=False)
def disable_backups():
    testutils.disable_backups()
    yield
    testutils.enable_backups()


@pytest.fixture(scope="function", autouse=False)
def enable_debug():
    testutils.enable_debug()
    yield
    testutils.disable_debug()


@pytest.fixture(scope="function", autouse=False)
def disable_debug():
    testutils.disable_debug()
    yield
    testutils.enable_debug()


@pytest.fixture(scope="function", autouse=False)
def enable_archiving():
    testutils.enable_archiving()
    yield
    testutils.disable_archiving()


@pytest.fixture(scope="function", autouse=False)
def disable_archiving():
    testutils.disable_archiving()
    yield
    testutils.enable_archiving()


@pytest.fixture(scope="function", autouse=False)
def reset_inbox_state():
    InboxState().destroy()  # type: ignore
    inbox = InboxState()
    inbox.scan()
    yield inbox
    inbox.destroy()  # type: ignore
    inbox = InboxState()


@pytest.fixture(scope="function", autouse=False)
def requires_empty_inbox():
    """Fixture that moves the inbox to a tmp folder, and restores it after the test."""

    backup_inbox = Path(f"{TEST_DIRS.inbox}_backup")
    # if inbox exists, move it to a backup folder
    if TEST_DIRS.inbox.exists():
        shutil.rmtree(backup_inbox, ignore_errors=True)
        shutil.move(TEST_DIRS.inbox, backup_inbox)

    TEST_DIRS.inbox.mkdir(parents=True, exist_ok=True)

    InboxState().destroy()  # type: ignore

    yield TEST_DIRS.inbox

    # restore contents of inbox if it was moved to a backup folder
    if backup_inbox.exists():
        for f in backup_inbox.glob("*"):
            # if dst exists, remove src instead
            if (TEST_DIRS.inbox / f.name).exists():
                testutils.rm(f)
            else:
                shutil.move(f, TEST_DIRS.inbox)
        shutil.rmtree(backup_inbox, ignore_errors=True)
