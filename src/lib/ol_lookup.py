import re
import sys
import urllib.parse
from datetime import timedelta
from math import log10
from typing import Any, Literal, NotRequired, overload, TypedDict

import requests
import requests_cache
from rapidfuzz import fuzz

from lib.misc import max_if, re_group
from lib.term import print_debug
from src.lib.config import cfg

requests_cache.install_cache(
    str(cfg.META_DIR / "ol_cache"), backend="sqlite", expire_after=timedelta(days=1), ignored_parameters=["User-Agent"]
)

OpenLibraryAuthorResult = TypedDict(
    "OpenLibraryAuthorResult",
    {
        "key": str,
        "name": str,
        "type": str,
        "work_count": int,
        "alternate_names": NotRequired[list[str]],
        "birth_date": NotRequired[str],
        "death_date": NotRequired[str],
        "top_subjects": NotRequired[list[str]],
        "top_work": NotRequired[str],
        "ratings_average": NotRequired[float],
        "ratings_sortable": NotRequired[float],
        "ratings_count": NotRequired[int],
        "ratings_count_1": NotRequired[int],
        "ratings_count_2": NotRequired[int],
        "ratings_count_3": NotRequired[int],
        "ratings_count_4": NotRequired[int],
        "ratings_count_5": NotRequired[int],
        "want_to_read_count": NotRequired[int],
        "already_read_count": NotRequired[int],
        "currently_reading_count": NotRequired[int],
        "readinglog_count": NotRequired[int],
        "_version_": NotRequired[int],
    },
)

OpenLibrarySearchResult = TypedDict(
    "OpenLibrarySearchResult",
    {
        "key": str,
        "author_key": list[str],
        "author_name": list[str],
        "type": NotRequired[str],
        "name": str,
        "alternate_names": NotRequired[list[str]],
        "work_count": int,
        "ratings_count": NotRequired[int],
        "currently_reading_count": NotRequired[int],
        "read_count": NotRequired[int],
        "want_to_read_count": NotRequired[int],
        "cover_edition_key": NotRequired[str],
        "cover_i": NotRequired[int],
        "ebook_access": NotRequired[str],
        "edition_count": int,
        "first_publish_year": NotRequired[int],
        "has_fulltext": NotRequired[bool],
        "ia": NotRequired[list[str]],
        "ia_collections": NotRequired[list[str]],
        "language": NotRequired[list[str]],
        "lending_edition_s": NotRequired[str],
        "lending_identifier_s": NotRequired[str],
        "public_scan_b": NotRequired[bool],
        "title": NotRequired[str],
    },
)


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


def _find_best_author(
    author: str, matches: list[OpenLibraryAuthorResult], *, method: Literal["score", "similarity"] = "score"
) -> tuple[OpenLibraryAuthorResult | None, float]:
    if not matches:
        return (None, 0.0)

    score_ordered = sorted(
        matches,
        key=lambda x: (
            x.get("work_count", 0),
            x.get("ratings_count", 0),
            x.get("currently_reading_count", 0),
            x.get("read_count", 0),
            x.get("want_to_read_count", 0),
        ),
        reverse=True,
    )
    sim_ordered = sorted(matches, key=lambda x: fuzz.ratio(author, x["name"]), reverse=True)

    top_scored = score_ordered[0]
    top_sim = sim_ordered[0]

    # closest_match: OpenLibraryAuthorResult | None = None
    # closest_score = 0.0
    # for m in matches:
    #     score = fuzz.ratio(author, m["name"]) / 100
    #     if score > closest_score:
    #         closest_score = score
    #         closest_match = m

    # If closest_match is the same as ordered[0], we found an easy match
    if top_sim and top_sim["key"] == top_scored["key"]:
        return (top_scored, fuzz.ratio(author, top_scored["name"]) / 100)

    # Otherwise, find the highest scored/most similar match
    if method == "score":
        return (top_scored, fuzz.ratio(author, top_scored["name"]) / 100)

    return (top_sim, fuzz.ratio(author, top_sim["name"]) / 100)


def _find_best_title(
    title: str,
    matches: list[OpenLibrarySearchResult],
    *,
    author: str | None = None,
    narrator: str | None = None,
    method: Literal["score", "similarity"] = "score",
) -> tuple[OpenLibrarySearchResult | None, float, float | None, Literal["author", "narrator"] | None]:
    """
    Returns:
        tuple[OpenLibrarySearchResult | None, float, float]
        - The best match
        - The score of the best match
        - The score of the author candidate
        - Which of author or narrator is the likely author
    """
    if not matches:
        return (None, 0.0, 0.0, None)

    score_ordered = sorted(
        matches,
        key=lambda x: (
            x.get("work_count", 0),
            x.get("ratings_count", 0),
            x.get("currently_reading_count", 0),
            x.get("read_count", 0),
            x.get("want_to_read_count", 0),
        ),
        reverse=True,
    )
    sim_ordered = sorted(matches, key=lambda x: fuzz.ratio(title, x.get("title", "")), reverse=True)

    author_sim_ordered = sorted(
        matches, key=lambda x: max(fuzz.ratio(author, name) for name in x["author_name"]) if author else 0, reverse=True
    )
    narrator_sim_ordered = sorted(
        matches,
        key=lambda x: max(fuzz.ratio(narrator, name) for name in x["author_name"]) if narrator else 0,
        reverse=True,
    )

    top_scored = score_ordered[0]
    top_sim = sim_ordered[0]
    top_author_sim = author_sim_ordered[0] if author else None
    top_narrator_sim = narrator_sim_ordered[0] if narrator else None

    # If both author and narrator, figure out which one is most similar to the top_scored and top_sim books by doing fuzz.ratio on the author_name and narrator_name for both top_scored and top_sim
    # Even though we pass author and narrator in, there are no narrators in the OL search results - this is only used to determine which of the two names is more likely to be the author (in the case the id3 tags were swapped)
    author_candidate = None
    if author or narrator:
        author_candidates = list(filter(lambda a: a is not None, [top_author_sim, top_narrator_sim]))
        scores = list(
            map(
                lambda c: (
                    c,
                    max(
                        fuzz.ratio(ta, a)
                        for t in [top_scored, top_sim]
                        for ta in t.get("author_name", [])
                        for a in (c or {}).get("author_name", [])
                    ),
                ),
                author_candidates,
            )
        )
        author_candidate = max(scores, key=lambda c: c[1])[0]

    def _get_author_sim(
        title_res: OpenLibrarySearchResult,
    ) -> tuple[float | None, Literal["author", "narrator"] | None]:
        _author_sim = (
            None
            if not author
            else 0.0 if not author_candidate else fuzz.ratio(author, title_res.get("author_name", "")) / 100
        )
        _narrator_sim = (
            None
            if not narrator
            else 0.0 if not author_candidate else fuzz.ratio(narrator, title_res.get("author_name", "")) / 100
        )
        # Author sim is now the max of the author and narrator scores
        if _author_sim and _narrator_sim:
            return max(_author_sim, _narrator_sim), "author" if _author_sim > _narrator_sim else "narrator"
        elif _author_sim:
            return _author_sim, "author"
        elif _narrator_sim:
            return _narrator_sim, "narrator"
        return None, None

    # If top_scored and top_sim are the same, we found an easy match
    if top_scored["key"] == top_sim["key"]:
        title_sim = fuzz.ratio(title, top_scored.get("title", "")) / 100
        author_sim = _get_author_sim(top_scored)
        return (top_scored, title_sim, *author_sim)

    # Otherwise, find the title with the best score / highest similarity
    if method == "score":
        return (top_scored, fuzz.ratio(title, top_scored.get("title", "")) / 100, *_get_author_sim(top_scored))

    return (top_sim, fuzz.ratio(title, top_sim.get("title", "")) / 100, *_get_author_sim(top_sim))


class OpenLibraryAuthor:
    def __init__(self, author_res: OpenLibraryAuthorResult | None, score: float | None):
        if not author_res is None:
            self.author_res = author_res
        else:
            self.author_res = OpenLibraryAuthorResult(
                key="",
                name="",
                type="",
                work_count=0,
                alternate_names=[],
            )

        self._score = score

    def __repr__(self) -> str:
        return f"OpenLibraryAuthor(name={self.name}, score={self.score()})"

    @property
    def has_match(self) -> bool:
        return bool(self.author_res.get("key", ""))

    @property
    def name(self) -> str:
        return self.author_res.get("name", "")

    @overload
    def score(self, *, fallback: float) -> float: ...

    @overload
    def score(self, *, fallback: float | None = None) -> float | None: ...

    def score(self, *, fallback: float | None = None) -> float | None:
        return float(self._score) if self.has_match and isinstance(self._score, (float, int)) else fallback


def open_library_lookup_author(
    author: str, *, method: Literal["score", "similarity"] = "score"
) -> OpenLibraryAuthor | None:
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
        author_lower = author.lower().strip()
        author_no_periods = author_lower.replace(".", "")
        author_period_spaces = re.sub(r"\s+", " ", author_lower.replace(".", ". "))
        matches = []
        exact_matches = []
        found = 0
        for name in list(set([author_lower, author_no_periods, author_period_spaces])):
            url = f"https://openlibrary.org/search/authors.json?q={urllib.parse.quote_plus(name)}"
            response = requests.get(url, headers={"User-Agent": agent_string})
            response.raise_for_status()
            data = response.json()
            matches.extend(
                [OpenLibraryAuthorResult(**d) for d in data.get("docs", []) if d.get("type", "") == "author"]
            )
            found += data["numFound"]
            exact_matches.extend(
                [
                    OpenLibraryAuthorResult(**d)
                    for d in matches
                    if d["name"].lower() == name or _in_alternate_names(name, d)
                ]
            )

        # dedupe matches by key - which are lists of dicts, so we can't use a set()
        matches = list({d["key"]: d for d in matches}.values())
        exact_matches = list({d["key"]: d for d in exact_matches}.values())

        exact_with_works = [d for d in exact_matches if d.get("work_count", 0) > 0]
        exact_with_ratings = [d for d in exact_matches if d.get("ratings_count", 0) > 0]
        max_works = max_if((d.get("work_count", 0) for d in exact_matches), 0)
        max_to_read = max_if((d.get("want_to_read_count", 0) for d in exact_matches), 0)
        max_reading = max_if((d.get("currently_reading_count", 0) for d in exact_matches), 0)
        max_read = max_if((d.get("read_count", 0) for d in exact_matches), 0)

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

        best_author = None

        if exact_len:
            base_score += max(1.0, log10(exact_len * 10))
            best_author, _best_score = _find_best_author(author, exact_matches, method=method)

            for m in [w_works_len, w_ratings_len]:
                if m < exact_len:
                    base_score -= (1 - (m / exact_len)) / 2
                else:
                    base_score += min(0.25, m / 10)
        else:
            best_author, best_score = _find_best_author(author, matches, method="similarity")
            base_score -= 1 - best_score

        # If best_author has a negative score, return an empty author
        if base_score < 0:
            return OpenLibraryAuthor(None, None)

        return OpenLibraryAuthor(best_author, round(base_score, 3))
    except Exception as e:
        print_debug(f"Error looking up author {author} from Open Library: {e}")
        if "pytest" in sys.modules:
            raise e
        return None


class OpenLibraryTitle:
    def __init__(
        self,
        title_res: OpenLibrarySearchResult | None,
        score: float | None,
        author_score: float | None,
        author_prop: Literal["author", "narrator"] | None,
        *,
        original_author: str | None,
        original_narrator: str | None,
    ):
        if not title_res is None:
            self.title_res = title_res
        else:
            self.title_res = OpenLibrarySearchResult(
                key="",
                author_key=[],
                author_name=[],
                type="",
                name="",
                alternate_names=[],
                work_count=0,
                ratings_count=0,
                currently_reading_count=0,
                read_count=0,
                want_to_read_count=0,
                cover_edition_key="",
                cover_i=0,
                ebook_access="",
                edition_count=0,
                first_publish_year=0,
                has_fulltext=False,
            )
        self._score = score

        self._author_score = author_score
        self.author_prop = author_prop
        self.original_author = original_author
        self.original_narrator = original_narrator

    def __repr__(self) -> str:
        return f"OpenLibraryTitle(title={self.title}, score={self.score()}, author_score={self.author_score()}, author_prop={self.author_prop})"

    @property
    def has_match(self) -> bool:
        return bool(self.title_res.get("key", ""))

    @property
    def title(self) -> str:
        return self.title_res.get("title", "") if self.has_match else ""

    @overload
    def score(self, *, fallback: float) -> float: ...

    @overload
    def score(self, *, fallback: float | None = None) -> float | None: ...

    def score(self, *, fallback: float | None = None) -> float | None:
        return float(self._score) if self.has_match and isinstance(self._score, (float, int)) else fallback

    @overload
    def author_score(self, *, fallback: float) -> float: ...

    @overload
    def author_score(self, *, fallback: float | None = None) -> float | None: ...

    def author_score(self, *, fallback: float | None = None) -> float | None:
        return (
            float(self._author_score) if self.has_match and isinstance(self._author_score, (float, int)) else fallback
        )

    def _get_author_or_narrator(self, prop: Literal["author", "narrator"]) -> str:
        original = self.original_author if prop == "author" else self.original_narrator
        if authors := self.title_res.get("author_name", [""]):
            # return the first if there is no original author, otherwise the one wiht the highest fuzz.ratio
            if not original:
                return authors[0]
            else:
                return max(authors, key=lambda x: fuzz.ratio(original or "", x))
        return ""

    @property
    def author(self) -> str:
        if self.author_and_narrator_swapped:
            return self.narrator
        return self._get_author_or_narrator("author")

    @property
    def author_and_narrator_swapped(self) -> bool:
        return self.author_prop == "narrator"

    @property
    def narrator(self) -> str:
        if not self.original_narrator or not self.has_match:
            return ""
        if self.author_and_narrator_swapped and self.original_author != self.original_narrator:
            # If they're swapped, we can return what we thought was the author as the narrator
            return self._get_author_or_narrator("author")
        return self._get_author_or_narrator("narrator")

    @property
    def date(self) -> str:
        return str(self.title_res.get("first_publish_year", "")) if self.has_match else ""


def open_library_lookup_title(
    title: str,
    *,
    author: str | None = None,
    narrator: str | None = None,
    method: Literal["score", "similarity"] = "score",
) -> OpenLibraryTitle | None:
    """Queries the Open Library API to get the title's score.

    Make sure you follow their rules for identifying your application:
    https://openlibrary.org/developers/api

    Make sure you use your own email address, and a unique
    name other than `auto-m4b`.

    This env var should be in the following format:

    OPEN_LIBRARY_USER_AGENT=MyAppName/1.0 (myemail@example.com)
    """

    from src.lib.patterns import junk_chars_title_pattern, title_chunk_pattern

    agent_string = _get_open_library_user_agent()
    if not agent_string:
        return None

    author_result = (None, 0.0)
    narrator_result = (None, 0.0)
    authors = []

    if author and (author_result := open_library_lookup_author(author, method="similarity")):
        if (a_name := author_result.name) and a_name:
            authors.append(a_name)
    if narrator and (narrator_result := open_library_lookup_author(narrator, method="similarity")):
        if (n_name := narrator_result.name) and n_name:
            authors.append(n_name)

    try:
        title_lower = title.lower().strip()
        title_no_periods = title_lower.replace(".", "")
        title_no_punctuation = junk_chars_title_pattern.sub("", title_lower)
        title_unchunked = title_chunk_pattern.sub("", title_lower)

        matches = []
        found = 0
        for t in list(set([title_lower, title_no_periods, title_no_punctuation, title_unchunked])):
            urls = (
                [
                    f"https://openlibrary.org/search.json?title={urllib.parse.quote_plus(t)}&author={urllib.parse.quote_plus(a)}"
                    for a in authors
                ]
                if authors
                else [f"https://openlibrary.org/search.json?title={urllib.parse.quote_plus(t)}"]
            )
            for url in urls:
                response = requests.get(url, headers={"User-Agent": agent_string})
                response.raise_for_status()
                data = response.json()
                matches.extend([OpenLibrarySearchResult(**d) for d in data.get("docs", [])])
                found += data["numFound"]

        return OpenLibraryTitle(
            *_find_best_title(title, matches, author=author, narrator=narrator, method=method),
            original_author=author,
            original_narrator=narrator,
        )
    except Exception as e:
        print_debug(f"Error looking up title {title} from Open Library: {e}")
        if "pytest" in sys.modules:
            raise e
        return None
