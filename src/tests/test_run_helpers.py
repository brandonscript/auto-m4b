import shutil

from src.lib.audiobook import Audiobook
from src.lib.fs_utils import get_audio_size
from src.lib.run import copy_to_working_dir


def test_copy_to_working_dir(house_on_the_cliff__flat_mp3: Audiobook):

    shutil.rmtree(house_on_the_cliff__flat_mp3.merge_dir, ignore_errors=True)

    copy_to_working_dir(house_on_the_cliff__flat_mp3)

    assert house_on_the_cliff__flat_mp3.merge_dir.exists()
    assert get_audio_size(house_on_the_cliff__flat_mp3.inbox_dir) == get_audio_size(
        house_on_the_cliff__flat_mp3.merge_dir
    )
    merge_cover = house_on_the_cliff__flat_mp3.merge_dir / "houseonthecliff_2307.jpg"
    assert merge_cover.exists()
    assert house_on_the_cliff__flat_mp3._merge_cover_art_file == merge_cover
