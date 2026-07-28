"""Tests for the MAX_BITRATE env cap."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.lib.audiobook import Audiobook
from src.lib.config import cfg
from src.lib.converter.merge import should_stream_copy


@pytest.fixture(autouse=True)
def _reset_max_bitrate():
    """Ensure MAX_BITRATE does not leak between tests."""
    prev = cfg.MAX_BITRATE
    yield
    cfg.MAX_BITRATE = prev


class TestMaxBitrateConfig:
    def test_unset_means_no_cap(self):
        cfg.MAX_BITRATE = 0
        assert cfg.max_bitrate_bps is None

    def test_max_bitrate_bps_snaps_to_standard(self):
        cfg.MAX_BITRATE = 64
        assert cfg.max_bitrate_bps == 64000

        cfg.MAX_BITRATE = 70  # between 64 and 80 → nearest standard
        assert cfg.max_bitrate_bps in (64000, 80000)


class TestBitrateTargetCap:
    def test_caps_when_source_above_max(self, tiny__flat_mp3: Audiobook):
        cfg.MAX_BITRATE = 48
        with patch(
            "src.lib.audiobook.get_bitrate_py",
            return_value=(128000, 128000),
        ):
            assert tiny__flat_mp3.bitrate_target == 48000
            assert tiny__flat_mp3.bitrate_exceeds_max is True

    def test_unchanged_when_source_at_or_below_max(self, tiny__flat_mp3: Audiobook):
        cfg.MAX_BITRATE = 128
        with patch(
            "src.lib.audiobook.get_bitrate_py",
            return_value=(64000, 64000),
        ):
            assert tiny__flat_mp3.bitrate_target == 64000
            assert tiny__flat_mp3.bitrate_exceeds_max is False

    def test_unchanged_when_max_unset(self, tiny__flat_mp3: Audiobook):
        cfg.MAX_BITRATE = 0
        with patch(
            "src.lib.audiobook.get_bitrate_py",
            return_value=(192000, 192000),
        ):
            assert tiny__flat_mp3.bitrate_target == 192000
            assert tiny__flat_mp3.bitrate_exceeds_max is False


class TestShouldStreamCopy:
    def test_m4b_copies_when_under_max(self, tiny__flat_mp3: Audiobook):
        tiny__flat_mp3._orig_file_type = "m4b"
        cfg.MAX_BITRATE = 128
        with patch(
            "src.lib.audiobook.get_bitrate_py",
            return_value=(64000, 64000),
        ):
            assert should_stream_copy(tiny__flat_mp3) is True

    def test_m4b_reencodes_when_above_max(self, tiny__flat_mp3: Audiobook):
        tiny__flat_mp3._orig_file_type = "m4b"
        cfg.MAX_BITRATE = 64
        with patch(
            "src.lib.audiobook.get_bitrate_py",
            return_value=(128000, 128000),
        ):
            assert should_stream_copy(tiny__flat_mp3) is False

    def test_mp3_never_stream_copies(self, tiny__flat_mp3: Audiobook):
        tiny__flat_mp3._orig_file_type = "mp3"
        cfg.MAX_BITRATE = 0
        assert should_stream_copy(tiny__flat_mp3) is False


class TestPassthroughGateRespectsMaxBitrate:
    def test_high_bitrate_single_m4b_not_already_converted(
        self,
        basic_with_cover__single_m4b: Audiobook,
        capfd: pytest.CaptureFixture[str],
    ):
        """Single m4b above MAX_BITRATE must not take process_already_m4b."""
        from src.auto_m4b import app
        from src.tests.helpers.pytest_utils import testutils

        cfg.MAX_BITRATE = 32
        with patch(
            "src.lib.audiobook.get_bitrate_py",
            return_value=(128000, 128000),
        ), patch(
            "src.lib.ffmpeg_utils.get_bitrate_py",
            return_value=(128000, 128000),
        ):
            app(max_loops=1)

        out = testutils.get_stdout(capfd)
        assert "already been converted" not in out
        # Cap notice and/or a real conversion should appear instead
        assert "Capping bitrate" in out or "Converted" in out or "Starting" in out
