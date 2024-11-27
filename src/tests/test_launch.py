import pytest
from pytest import CaptureFixture

from src.auto_m4b import app
from src.lib.formatters import listify
from src.lib.strings import en
from src.tests.helpers.pytest_utils import testutils


@pytest.fixture(scope="function", autouse=False)
def enable_or_disable_multi(request: pytest.FixtureRequest):

    flatten = request.param

    if flatten:
        testutils.enable_multidisc()
    else:
        testutils.disable_multidisc()


@pytest.mark.skip(reason="No beta features to test at the moment")
@pytest.mark.parametrize(
    "enable_or_disable_multi, features, nots",
    [
        # fmt: off
        ((True, False), [en.FEATURE_FLATTEN_MULTI_DISC_BOOKS], []),
        ((True, True), [en.FEATURE_FLATTEN_MULTI_DISC_BOOKS], []),
        ((False, True), [], [en.FEATURE_FLATTEN_MULTI_DISC_BOOKS]),
        ((False, False), [], [en.FEATURE_FLATTEN_MULTI_DISC_BOOKS]),
        # fmt: on
    ],
    indirect=["enable_or_disable_multi"],
)
def test_display_flatten_and_convert_features(
    # tiny__flat_mp3: Audiobook,
    # enable_multidisc,
    enable_or_disable_multi,
    features,
    nots,
    reset_all,
    capfd: CaptureFixture[str],
):
    testutils.set_match_filter("--none--")
    app(max_loops=1)

    out = testutils.get_stdout(capfd)

    if features:
        assert f"[Beta] features are enabled:\n{listify(features)}" in out
    else:
        assert not "[Beta]" in out
    for n in nots:
        assert not n in out
