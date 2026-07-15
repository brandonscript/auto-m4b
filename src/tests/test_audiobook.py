import pytest

from src.lib.audiobook import Audiobook
from src.lib.inbox_state import InboxState
from src.tests.helpers.pytest_dumps import TEST_DIRS


def test_orig_file_type(house_on_the_cliff__flat_mp3: Audiobook):
    assert house_on_the_cliff__flat_mp3.orig_file_type == "mp3"


@pytest.mark.parametrize(
    "indirect_fixture, expected_num_files",
    [
        ("house_on_the_cliff__flat_mp3", 2),
        ("corrupt_audiobook", 1),
        ("nathan_lowell__nested_series_m4a", 28),
    ],
    indirect=["indirect_fixture"],
)
def test_num_files(indirect_fixture: Audiobook, expected_num_files: int):
    assert indirect_fixture.num_files("inbox") == expected_num_files


def test_series_parent(Chanur_Series):
    # Force an InboxState rescan now that the Chanur fixtures are loaded so
    # series-parent relationships are populated before we read them.
    InboxState().scan(force=True)
    for book in Chanur_Series[1:]:
        assert book.series_parent.tree == Chanur_Series[0].tree


class test_safe_filename_in_audiobook_paths:
    """Verify that a colon (or other SMB-unsafe char) in self.title is stripped
    out of every path-building property so the OS never sees an illegal name."""

    @pytest.fixture
    def book_with_colon_title(self, house_on_the_cliff__flat_mp3: Audiobook) -> Audiobook:
        """Inject a colon-bearing title onto an otherwise normal Audiobook."""
        house_on_the_cliff__flat_mp3.title = (
            "Into the Fire: A LitRPG Fantasy Cooking Adventure (Morcster Chef, Book 2)"
        )
        return house_on_the_cliff__flat_mp3

    def test_build_file_has_no_colon(self, book_with_colon_title: Audiobook):
        name = book_with_colon_title.build_file.name
        assert ":" not in name
        assert name == "Into the Fire - A LitRPG Fantasy Cooking Adventure (Morcster Chef, Book 2).m4b"

    def test_converted_file_stem_has_no_colon(self, book_with_colon_title: Audiobook):
        # converted_file._build_filename() uses self.basename (the inbox folder
        # name), which won't have a colon on SMB.  The important thing is that
        # safe_filename() doesn't break a clean name.
        name = book_with_colon_title.converted_file.name
        assert ":" not in name

    def test_final_desc_file_has_no_colon(self, book_with_colon_title: Audiobook):
        name = book_with_colon_title.final_desc_file.name
        assert ":" not in name
        assert name.startswith("Into the Fire - A LitRPG Fantasy Cooking Adventure (Morcster Chef, Book 2) [")
