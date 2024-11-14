import pytest

from src.auto_m4b import app
from src.tests.helpers.pytest_utils import testutils


class test_series:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, reset_all):
        yield

    def test_multi_series_m4bs_are_passed_through(
        self,
        nathan_lowell__nested_series_m4b,
        capfd: pytest.CaptureFixture[str],
    ):
        testutils.set_match_filter("^(Nathan Lowell)")
        app(max_loops=1)
        assert testutils.assert_processed_output(
            capfd,
            nathan_lowell__nested_series_m4b,
            loops=[testutils.check_output(already_converted_eq=1)],
        )
