from types import SimpleNamespace

import pytest

from src.lib import term
from src.tests.helpers.pytest_utils import testutils


@pytest.mark.parametrize("logged", ["A book failed", "\x1b[32mA book failed\x1b[0m"])
def test_stdout_does_not_duplicate_colored_output(monkeypatch, logged):
    monkeypatch.setattr(term, "PRINT_LOG", [(logged, "\n")])
    monkeypatch.setattr(testutils, "_print_log_cursor", 0)
    capture = SimpleNamespace(readouterr=lambda: SimpleNamespace(out="\x1b[31mA book failed\x1b[0m\n"))

    assert testutils.get_stdout(capture) == "A book failed\n"


def test_stdout_falls_back_to_print_log_and_advances_cursor(monkeypatch):
    monkeypatch.setattr(term, "PRINT_LOG", [("A book failed", "\n")])
    monkeypatch.setattr(testutils, "_print_log_cursor", 0)
    capture = SimpleNamespace(readouterr=lambda: SimpleNamespace(out=""))

    assert testutils.get_stdout(capture) == "A book failed\n"
    assert testutils.get_stdout(capture) == ""
