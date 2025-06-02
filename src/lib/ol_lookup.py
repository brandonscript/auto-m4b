import re
import urllib.parse
from math import log10
from typing import Any

import requests
from rapidfuzz import fuzz

from lib.misc import re_group
from lib.term import print_debug


def _generate_unique_app_name() -> str:
    """Uses nltk corpus to generate a unique app name"""
    from random import choice

    from nltk.corpus import words

    # Keep pulling random words until we have 3 that are <= 6 chars
    result = []
    while len(result) < 3:
        word = re.sub(r"[^a-zA-Z]", "", str(choice(words.words())))
        if len(word) > 3 and len(word) <= 8:
            result.append(word)
    return "-".join(result).lower()


def _get_open_library_user_agent() -> str | None:
    """Get the user agent for the Open Library API from the env var and
    validates that it matches the following format, and includes/generates
    a unique name.

    MyAppName/1.0 (myemail@example.com)
    """
    from src.lib.config import cfg
    from src.lib.patterns import open_library_user_agent_pattern

    if not (agent_string := cfg.OPEN_LIBRARY_USER_AGENT):
        return None

    match = open_library_user_agent_pattern.search(agent_string)

    err_msg = f"Invalid Open Library user agent: {agent_string}, must match: MyAppName/1.0 (myemail@example.com)"

    if not match:
        raise ValueError(err_msg)

    app_name = re_group(match, "app", default="")
    email = re_group(match, "email", default="")
    version = re_group(match, "version", default="0.0.1")

    if not app_name or not email:
        raise ValueError(err_msg)

    if "@pacificaviator." in email.lower():
        raise ValueError("Please use your own email address for the Open Library API user agent")

    if app_name.lower() == "auto-m4b":
        # Check cfg.META_DIR for a file called "app_name"
        app_name_file = cfg.META_DIR / "app_name"
        if app_name_file.exists():
            with open(app_name_file, "r") as f:
                app_name = f.read().strip()
            if app_name and not app_name == "auto-m4b":
                return f"{app_name}/{version} ({email})"
        else:
            app_name = f"auto-m4b-{_generate_unique_app_name()}"
            with open(app_name_file, "w") as f:
                f.write(app_name)

    return f"{app_name}/{version} ({email})"


def _in_alternate_names(name: str, doc: dict[str, Any]) -> bool:
    """Check if name is in the alternate_names list of the doc"""
    if not (alternate_names := doc.get("alternate_names", None)):
        return False
    name = name.lower().strip()
    name_no_periods = name.replace(".", "")
    name_period_spaces = re.sub(r"\s+", " ", name.replace(".", ". "))
    return (
        name in map(str.lower, alternate_names)
        or name_no_periods in map(str.lower, alternate_names)
        or name_period_spaces in map(str.lower, alternate_names)
    )


def open_library_lookup_author(author_name: str) -> float | None:
    """Queries the Open Library API to get the author's score.

    Make sure you follow their rules for identifying your application:
    https://openlibrary.org/developers/api

    Make sure you use your own email address, and a unique
    name other than `auto-m4b`.

    This env var should be in the following format:

    OPEN_LIBRARY_USER_AGENT=MyAppName/1.0 (myemail@example.com)
    """

    agent_string = _get_open_library_user_agent()
    if not agent_string:
        return None

    try:
        author_name_lower = author_name.lower().strip()
        author_name_no_periods = author_name_lower.replace(".", "")
        author_name_period_spaces = re.sub(r"\s+", " ", author_name_lower.replace(".", ". "))
        matches = []
        exact_matches = []
        found = 0
        for name in list(set([author_name_lower, author_name_no_periods, author_name_period_spaces])):
            url = f"https://openlibrary.org/search/authors.json?q={urllib.parse.quote_plus(name)}"
            response = requests.get(url, headers={"User-Agent": agent_string})
            response.raise_for_status()
            data = response.json()
            matches.extend([d for d in data.get("docs", []) if d.get("type", "") == "author"])
            found += data["numFound"]
            exact_matches.extend([d for d in matches if d["name"].lower() == name or _in_alternate_names(name, d)])

        # dedupe matches by key - which are lists of dicts, so we can't use a set()
        matches = list({d["key"]: d for d in matches}.values())
        exact_matches = list({d["key"]: d for d in exact_matches}.values())

        exact_with_works = [d for d in exact_matches if d.get("work_count", 0) > 0]
        exact_with_ratings = [d for d in exact_matches if d.get("ratings_count", 0) > 0]
        max_works = 0 if not exact_matches else max(d.get("work_count", 0) for d in exact_matches)
        max_to_read = 0 if not exact_matches else max(d.get("want_to_read_count", 0) for d in exact_matches)
        max_reading = 0 if not exact_matches else max(d.get("currently_reading_count", 0) for d in exact_matches)
        max_read = 0 if not exact_matches else max(d.get("read_count", 0) for d in exact_matches)

        exact_len = len(exact_matches)
        w_works_len = len(exact_with_works)
        w_ratings_len = len(exact_with_ratings)

        base_score = 0.0
        if found:
            base_score += min(0.25, found / 10)
        if max_works:
            base_score += max(0.5, log10(max_works))

        for m in [max_to_read, max_reading, max_read]:
            if m:
                base_score += min(0.25, m / 10)
            else:
                base_score -= 0.2

        if exact_len:
            base_score += max(1.0, log10(exact_len * 10))
            for m in [w_works_len, w_ratings_len]:
                if m < exact_len:
                    base_score -= (1 - (m / exact_len)) / 2
                else:
                    base_score += min(0.25, m / 10)
        else:
            # If we have no exact matches, find the closest using rapidfuzz.ratio
            closest_match: dict[str, Any] | None = None
            closest_score = 0.0
            for m in matches:
                score = fuzz.ratio(author_name, m["name"]) / 100
                if score > closest_score:
                    closest_score = score
                    closest_match = m
            if closest_match:
                base_score -= 1 - closest_score

        return round(base_score, 3)
    except Exception as e:
        print_debug(f"Error looking up author {author_name} from Open Library: {e}")
        return None
