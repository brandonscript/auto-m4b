"""Tests for minimalist title stripping and marketing-subtitle detection."""

from __future__ import annotations

import pytest

from src.lib.cleaners import (
    is_author_only_name,
    looks_like_marketing_subtitle,
    minimalist_title,
    strip_leading_author_dash,
)


@pytest.mark.parametrize(
    "raw, author, expected",
    [
        (
            "The Dark Days Club: The Lady Helen Trilogy, Book 1 (Unabridged)",
            None,
            "The Dark Days Club",
        ),
        ("The Dark Days Club", None, "The Dark Days Club"),
        ("Eona: The Last Dragoneye", None, "Eona: The Last Dragoneye"),
        # Without author awareness, keep Author - Title (do not collapse to author).
        (
            "Alison Goodman - The Dark Days Club The Lady Helen Trilogy, Book 1 (Unabridged)",
            None,
            "Alison Goodman - The Dark Days Club",
        ),
        # With author: strip prefix then marketing junk → core title.
        (
            "Alison Goodman - The Dark Days Club The Lady Helen Trilogy, Book 1 (Unabridged)",
            "Alison Goodman",
            "The Dark Days Club",
        ),
        # Short dash series tails still strip.
        ("Some Book - The Foo Trilogy", None, "Some Book"),
    ],
)
def test_minimalist_title(raw: str, author: str | None, expected: str):
    assert minimalist_title(raw, author=author) == expected


def test_strip_leading_author_dash():
    assert (
        strip_leading_author_dash(
            "Alison Goodman - The Dark Days Club", "Alison Goodman"
        )
        == "The Dark Days Club"
    )
    assert strip_leading_author_dash("The Dark Days Club", "Alison Goodman") == (
        "The Dark Days Club"
    )
    # Never collapse to empty
    assert strip_leading_author_dash("Alison Goodman - ", "Alison Goodman") == (
        "Alison Goodman - "
    )


def test_is_author_only_name():
    assert is_author_only_name("Alison Goodman", "Alison Goodman")
    assert is_author_only_name("alison goodman", "Alison Goodman")
    assert not is_author_only_name(
        "Alison Goodman - The Dark Days Club", "Alison Goodman"
    )
    assert not is_author_only_name("The Dark Days Club", "Alison Goodman")


@pytest.mark.parametrize(
    "subtitle, expected",
    [
        ("The Lady Helen Trilogy, Book 1", True),
        ("The Last Dragoneye", False),
    ],
)
def test_looks_like_marketing_subtitle(subtitle: str, expected: bool):
    assert looks_like_marketing_subtitle(subtitle) is expected
