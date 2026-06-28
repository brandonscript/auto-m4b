import pytest

from src.lib.audiobook import Audiobook
from src.lib.books_tree import BooksTree
from src.lib.fs_utils import hash_path_audio_files
from src.lib.inbox_state import InboxState
from src.lib.misc import isorted
from src.tests.helpers.pytest_utils import testutils


class TestInboxState:

    @pytest.fixture(scope="function", autouse=True)
    def destroy_inbox_state(self):
        InboxState._instance = None  # type: ignore
        yield
        InboxState._instance = None  # type: ignore

    def test_books(
        self,
        Chanur_Series: list[Audiobook],
        reset_inbox_state: InboxState,
    ):
        assert reset_inbox_state.books_and_series
        assert [isinstance(d, BooksTree) for d in reset_inbox_state.books_and_series]

    def test_get_item_by_key(
        self,
        Chanur_Series: list[Audiobook],
        reset_inbox_state: InboxState,
    ):

        assert reset_inbox_state.get("Chanur Series") == Chanur_Series[0]._inbox_item

    def test_get_item_from_audiobook(
        self,
        Chanur_Series: list[Audiobook],
        reset_inbox_state: InboxState,
    ):

        assert reset_inbox_state.get(Chanur_Series[0]) == Chanur_Series[0]._inbox_item

    def test_get_item_from_hash(
        self,
        Chanur_Series: list[Audiobook],
        reset_inbox_state: InboxState,
    ):

        _hash = hash_path_audio_files(Chanur_Series[0].inbox_dir)

        assert reset_inbox_state.get(_hash) == Chanur_Series[0]._inbox_item

    def test_get_series_parent(
        self,
        Chanur_Series: list[Audiobook],
        reset_inbox_state: InboxState,
    ):

        series = Chanur_Series[0]
        # books = Chanur_Series[1:]
        key1 = "Chanur Series/01 - Pride Of Chanur"
        assert (item := reset_inbox_state.get(key1))
        assert item.series_parent == series._inbox_item

    def test_state_with_multiple_books(
        self,
        tower_treasure__flat_mp3: Audiobook,
        missing_chums__mixed_mp3: Audiobook,
        fails__mixed_mp3: Audiobook,
        tiny__flat_mp3: Audiobook,
        capfd: pytest.CaptureFixture[str],
    ):

        testutils.set_match_filter("^(tower|missing|fails|tiny)")

        InboxState().destroy()  # type: ignore
        inbox = InboxState()
        assert isorted(inbox.tree.books_and_series_f) == isorted(
            [
                tower_treasure__flat_mp3.tree,
                missing_chums__mixed_mp3.tree,
                fails__mixed_mp3.tree,
                tiny__flat_mp3.tree,
            ]
        )

        assert len(inbox.matched_ok_books) == 4

        for item in inbox.matched_ok_books.values():
            assert item.status == "new"
