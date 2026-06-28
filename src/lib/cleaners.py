import re
from typing import Literal

from lib.misc import re_group

disc_no_strip_pattern = re.compile(r"\W*?-?\W*?[\(\[]*(disc|cd)\W*\d+[\)\]]*", flags=re.I)
part_no_strip_pattern = re.compile(r"(\W*?-?\W*?[\(\[]*(?P<part>[Pp]([Aa][Rr])?[Tt]\W*\d+[\)\]]*|P[Aa][Rr][Tt]$))")
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


def fix_smart_quotes(s: str) -> str:
    """Takes a string and replaces smart quotes with regular quotes"""
    if not s:
        return s
    # Map smart quotes to regular quotes using a dictionary
    # This handles various Unicode smart quote characters
    smart_quote_map = {
        # Single quotes/apostrophes
        "'": "'",  # U+2018 LEFT SINGLE QUOTATION MARK
        "'": "'",  # U+2019 RIGHT SINGLE QUOTATION MARK
        "‚": "'",  # U+201A SINGLE LOW-9 QUOTATION MARK
        "‛": "'",  # U+201B SINGLE HIGH-REVERSED-9 QUOTATION MARK
        "′": "'",  # U+2032 PRIME
        "″": "'",  # U+2033 DOUBLE PRIME (sometimes used as quote)
        # Double quotes
        '"': '"',  # U+201C LEFT DOUBLE QUOTATION MARK
        '"': '"',  # U+201D RIGHT DOUBLE QUOTATION MARK
        "„": '"',  # U+201E DOUBLE LOW-9 QUOTATION MARK
        "‟": '"',  # U+201F DOUBLE HIGH-REVERSED-9 QUOTATION MARK
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
