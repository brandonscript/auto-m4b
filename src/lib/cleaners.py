import re

from lib.misc import re_group

disc_no_strip_pattern = re.compile(r"\W*?-?\W*?[\(\[]*(disc|cd)\W*\d+[\)\]]*", flags=re.I)
part_no_strip_pattern = re.compile(r"(\W*?-?\W*?[\(\[]*(?P<part>[Pp]([Aa][Rr])?[Tt]\W*\d+[\)\]]*|P[Aa][Rr][Tt]$))")
non_alpha_strip_pattern = re.compile(r"^\W+|\W+$")

html_tag_pattern = re.compile(r"</?\w+\s*/?>", flags=re.DOTALL)

leading_articles_pattern = re.compile(r"^((?:a|an|the)[\s_.]+\b)", flags=re.I)


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
    trnsl = str.maketrans("‘’‚‛′′“”„‟″″", "''''''\"\"\"\"\"\"")
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
