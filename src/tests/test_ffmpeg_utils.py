from src.lib.audiobook import Audiobook


class test_ffprobe:
    def test_get_duration(self, basic_with_cover__single_mp3: Audiobook):
        from src.lib.ffmpeg_utils import get_duration

        # Fixtures are stream-copy trimmed for suite speed; duration is short but valid.
        assert get_duration(basic_with_cover__single_mp3.path) == "0h:00m:12s"
