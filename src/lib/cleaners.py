import re
from typing import Literal

from src.lib.misc import re_group

# Strips "Disc 1", "CD 2", etc., and also orphaned "Disc"/"CD" at the end of a
# string (e.g. after GCS removed the varying number: "Dreadnought Disc " → "Dreadnought").
disc_no_strip_pattern = re.compile(
    r"\W*?-?\W*?[\(\[]*(disc|cd)\W*(?:\d+[\)\]]*|\s*$)", flags=re.I
)

# Strips "Part 1", "Pt. 2", "Ch. 3", "Chapter 4", and also orphaned "Part"/"Pt"
# keywords at the end (e.g. "Dreadnought Part " after GCS). "Chapter" alone is
# intentionally excluded from the no-number case to avoid false-positives on titles
# like "The Last Chapter".
part_no_strip_pattern = re.compile(
    r"(\W*?-?\W*?[\(\[]*(?P<part>(?:p(?:ar)?t|ch(?:apter)?)\W*\d+[\)\]]*|p(?:ar)?t\s*$))",
    re.I,
)
non_alpha_strip_pattern = re.compile(r"^\W+|\W+$")

html_tag_pattern = re.compile(r"</?\w+\s*/?>", flags=re.DOTALL)

leading_articles_pattern = re.compile(r"^((?:a|an|the)[\s_.]+\b)", flags=re.I)

# Pattern to match 1-3 capital letters with optional periods and spaces between them
abbrev_pattern = re.compile(r"^(?:[A-Z](?:\.\s*|\s*\.?|\s*)(?=[A-Z]|\s|$)){1,3}$")

# Pattern to match and capture capital letters with their surrounding punctuation
letter_cap_pattern = re.compile(r"(?:(?P<cap>[A-Z])(?:\.\s*|\s*\.?|\s*)(?=[A-Z]|\s|$))+")


def strip_html_tags(s: str) -> str:
    """Replaces all html tags including <open> and </close> tags, and <autoclose /> tags with an empty string"""
    return html_tag_pattern.sub("", s)


def strip_non_alphanumeric(s: str) -> str:
    """Trims all non-alphanumeric characters from the beginning and end of a string"""
    return non_alpha_strip_pattern.sub("", s)


def strip_disc_number(s: str) -> str:
    """Takes a string and removes any disc/CD number found in the string"""
    if not s:
        return s
    return disc_no_strip_pattern.sub("", s).strip()


def strip_part_number(s: str) -> str:
    # if it matches both the part number and ignore, return original string
    if not s:
        return s
    if (part := re_group(re.search(part_no_strip_pattern, s), "part", default="")) and not part:
        return s
    return part_no_strip_pattern.sub("", s).strip()


def strip_author_narrator(s: str, author: str | None = None, narrator: str | None = None) -> str:
    """Takes a string and removes any author or narrator names found in the string"""
    if not s:
        return s
    if author:
        s = re.sub(re.escape(author), "", s, flags=re.I).strip()
    if narrator:
        s = re.sub(re.escape(narrator), "", s, flags=re.I).strip()
    return s


def strip_leading_author_dash(s: str, author: str | None) -> str:
    """Remove a leading ``Author - `` / ``Author – `` prefix from a title or stem.

    Only strips when a non-empty remainder remains, so we never collapse to
    author-only or empty. Does not remove author names elsewhere in the string.
    """
    original = s or ""
    text = original.strip()
    a = (author or "").strip()
    if not text or not a:
        return text
    m = re.match(r"^" + re.escape(a) + r"\s*[-–—]\s*(.+)$", text, flags=re.I)
    if not m:
        return original
    remainder = m.group(1).strip()
    return remainder if remainder else original


def is_author_only_name(s: str, author: str | None) -> bool:
    """True when *s* is empty/junk or equals *author* (case-insensitive)."""
    text = (s or "").strip()
    if not text or len(text) < 2:
        return True
    a = (author or "").strip()
    return bool(a) and text.casefold() == a.casefold()


def fix_smart_quotes(s: str) -> str:
    """Takes a string and replaces smart quotes with regular quotes"""
    if not s:
        return s
    # Map smart quotes to regular quotes using a dictionary
    # This handles various Unicode smart quote characters
    smart_quote_map = {
        # Single quotes/apostrophes
        "\u2018": "'",  # U+2018 LEFT SINGLE QUOTATION MARK
        "\u2019": "'",  # U+2019 RIGHT SINGLE QUOTATION MARK
        "\u201a": "'",  # U+201A SINGLE LOW-9 QUOTATION MARK
        "\u201b": "'",  # U+201B SINGLE HIGH-REVERSED-9 QUOTATION MARK
        "\u2032": "'",  # U+2032 PRIME
        # Double quotes
        "\u201c": '"',  # U+201C LEFT DOUBLE QUOTATION MARK
        "\u201d": '"',  # U+201D RIGHT DOUBLE QUOTATION MARK
        "\u201e": '"',  # U+201E DOUBLE LOW-9 QUOTATION MARK
        "\u201f": '"',  # U+201F DOUBLE HIGH-REVERSED-9 QUOTATION MARK
        "\u2033": '"',  # U+2033 DOUBLE PRIME (sometimes used as double quote)
    }
    trnsl = str.maketrans(smart_quote_map)
    return s.translate(trnsl)


urlencode_map = {
    "%20": " ",
    "%2C": ",",
    "%2F": "/",
    "%3A": ":",
    "%40": "@",
    "%3D": "=",
    "%26": "&",
    "%3F": "?",
    "&amp;": "&",
    "&quot;": '"',
    "&apos;": "'",
    "&eacute;": "é",
    "&egrave;": "è",
    "&ntilde;": "ñ",
    "&ccedil;": "ç",
    "&atilde;": "ã",
    "&lt;": "<",
    "&gt;": ">",
    "&nbsp;": " ",
    "&mdash;": "—",
    "&ndash;": "–",
    "&copy;": "©",
}


def un_urlencode(s: str) -> str:
    """Looks for common url-encoded characters and replaces them with their ascii equivalent (case insensitive)"""
    for k, v in urlencode_map.items():
        if k.lower() in s.lower():
            # replace all instances of the key with the value
            s = re.sub(re.escape(k), v, s, flags=re.I)
    return s


def clean_string(s: str, strip_disc_no: bool = True, strip_part_no: bool = True) -> str:
    """Cleans a string by stripping html tags, smart quotes, and url-encoded characters"""
    s = strip_html_tags(s)
    s = fix_smart_quotes(s)
    s = un_urlencode(s)
    if strip_disc_no:
        s = strip_disc_number(s)
    if strip_part_no:
        s = strip_part_number(s)
    return s


def strip_leading_articles(s: str) -> str:
    """Strips leading articles from a string"""
    return leading_articles_pattern.sub("", s).strip()


def title_case_ol_title(s: str) -> str:
    """Apply Chicago-style Title Case to an Open Library title.

    OL frequently returns titles in sentence case (e.g. ``The sunne in splendour``).
    Use this only for OL-sourced titles — do not apply to user/ID3 titles when OL
    is not involved.

    Small words (a, an, the, of, in, …) stay lowercase except at the start (or
    after a colon), apostrophes are preserved (``Devil's Brood``), and an already
    title-cased string is left intact.
    """
    if not s:
        return s
    from titlecase import titlecase

    return titlecase(s)


# Audible / retailer marketing suffixes (series, book index, abridgement).
_MIN_ABRIDGEMENT = re.compile(
    r"\s*[\(\[]\s*(?:un)?abridged\s*[\)\]]|\s*[\(\[]\s*ab\s*[\)\]]",
    re.I,
)
_MIN_BOOK_VOL = re.compile(
    r"\s*[,:\-–—]?\s*(?:book|bk\.?|vol(?:ume)?\.?)\s*\d+\b.*$",
    re.I,
)
_MIN_SERIES_SUBTITLE = re.compile(
    # Colon form: "Title: The Foo Trilogy…" (Audible-style)
    r"\s*:\s*the\s+.+?\s+(?:trilogy|series|saga|cycle|chronicles)\b.*$"
    # Dash form: only short series tails (e.g. "Some Book - The Foo Trilogy")
    r"|"
    r"\s+[-–—]\s*the\s+(?:\w+\s+){0,4}(?:trilogy|series|saga|cycle|chronicles)\b.*$"
    # Space form: "Title The Foo Bar Trilogy…" without colon/dash before series
    # (keeps "Author - Title" when dash form must not swallow the book title)
    r"|"
    r"\s+the\s+(?:\w+\s+){0,5}(?:trilogy|series|saga|cycle|chronicles)\b.*$",
    re.I,
)
_MIN_SERIES_COMMA = re.compile(
    r"\s*,\s*the\s+.+?\s+(?:trilogy|series|saga|cycle|chronicles)\b.*$",
    re.I,
)


def looks_like_marketing_subtitle(subtitle: str) -> bool:
    """True for trilogy/series/Book N/unabridged-style subtitle noise."""
    s = (subtitle or "").strip()
    if not s:
        return False
    if _MIN_ABRIDGEMENT.search(s):
        return True
    if re.search(r"\b(?:trilogy|series|saga|cycle|chronicles)\b", s, re.I):
        return True
    if re.search(r"\b(?:book|bk\.?|vol(?:ume)?\.?)\s*\d+\b", s, re.I):
        return True
    return False


def minimalist_title(s: str, author: str | None = None) -> str:
    """Strip series / Book N / (Unabridged) marketing suffixes from a title.

    When *author* is provided, a leading ``Author - `` prefix is removed first so
    author dashes cannot bait series-subtitle stripping into deleting the real title.

    Example::

        The Dark Days Club: The Lady Helen Trilogy, Book 1 (Unabridged)
        → The Dark Days Club

        Alison Goodman - The Dark Days Club The Lady Helen Trilogy, Book 1 (Unabridged)
        → The Dark Days Club   (with author=Alison Goodman)
    """
    if not s:
        return s
    original = s.strip()
    out = strip_leading_author_dash(original, author) if author else original
    # Order: abridgement markers can trail Book N; strip Book/series after.
    prev = None
    while prev != out:
        prev = out
        out = _MIN_ABRIDGEMENT.sub("", out).strip()
        out = _MIN_BOOK_VOL.sub("", out).strip()
        out = _MIN_SERIES_SUBTITLE.sub("", out).strip()
        out = _MIN_SERIES_COMMA.sub("", out).strip()
        out = out.rstrip(" ,;:.-–—").strip()
    out = clean_string(out)
    out = out.strip(" -_,.")
    # Never return author-only after stripping marketing junk.
    if is_author_only_name(out, author):
        return original
    return out or original


def clean_name_abbreviations(s: str, mode: Literal["periods", "periods_spaces", "strip"] = "periods") -> str:
    """Cleans up name abbreviations, e.g. J.R.R. Tolkien -> J. R. R. Tolkien
    or J. R. R. Tolkien -> J.R.R. Tolkien, and applies periods to standalone capital letters
    e.g. JRR Tolkien -> J.R.R. Tolkien, and Franklin W Dixon -> Franklin W. Dixon"""

    split_s = s.split(" ")
    out = ""
    for w in split_s:
        if not abbrev_pattern.search(w):
            out += f" {w} "
            continue

        match mode:
            case "strip":
                # Strip all periods and spaces between capital letters
                out += letter_cap_pattern.sub(r"\1", w)
            case "periods":
                # Apply periods (no spaces) to standalone capital letters
                out += letter_cap_pattern.sub(r"\1.", w)
            case "periods_spaces":
                # Apply periods (with spaces) to standalone capital letters
                out += letter_cap_pattern.sub(r"\1. ", w)
            case _:
                raise ValueError(f"[clean_name_abbreviations]: invalid mode: {mode}")

    # strip 2+ spaces to 1
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip()
