from src.lib.audiobook import Audiobook


class test_audiobook_class:

    def test_orig_file_type(self, house_on_the_cliff__flat_mp3: Audiobook):
        assert house_on_the_cliff__flat_mp3.orig_file_type == "mp3"
