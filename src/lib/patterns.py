import re

import regex as rex

# TODO: Add test coverage for narrator with /
# fmt: off
_titlecase_word = r"[A-Z][\p{Ll}\.'-]*"
_author_prefixes = r"[Ww]ritten.?[Bb]y|[Aa]uthor"
_narrator_prefixes = r"(?:[Rr]ead|[Nn]arrated|[Pp]erformed).?[Bb]y|[Nn]arrator"
def _name_substr(ignore_if_trailing: str = '', max_l_of_comma: int = 4, max_r_of_comma: int = 4):
    if ignore_if_trailing:
        ignore_if_trailing = f"(?!{ignore_if_trailing})"
    # (?:[Ww]ritten.?[Bb]y|[Pp]erformed.?[Bb]y|[Rr]ead.?[Bb]y)\W+(?P<name>(?:(?:(?<= )(?: ?[A-Z][a-z\.-]*){1,4})),? ?(?:(?: ?[A-Z][a-z\.-]*){1,4}(?!Performed by)))
    return rf"(?:(?:(?:^|(?<= ))(?: ?{_titlecase_word}){{1,{max_l_of_comma}}})),? ?(?:(?: ?{_titlecase_word}){{1,{max_r_of_comma}}}{ignore_if_trailing})"
_div = r"[-_–—.\s]*?"
_roman_numeral = r"(?:^|(?<=[\W_]))[IVXLCDM]+(?:$|(?=[\W_]))"
wordsplit_pat = re.compile(r"[\s_.]")

author_fs_pattern = re.compile(r"^(?P<author>.*?)[\W\s]*[-_–—\(]", re.I)
author_comment_pattern = rex.compile(rf"(?:{_author_prefixes})\W+(?P<author>{_name_substr(_narrator_prefixes)})", rex.V1)
author_generic_pattern = rex.compile(rf"(?P<author>{_name_substr()})", rex.V1)
narrator_comment_pattern = rex.compile(rf"(?:{_narrator_prefixes})\W+(?P<narrator>{_name_substr(_author_prefixes)})", rex.V1)
narrator_generic_pattern = rex.compile(rf"(?P<narrator>{_name_substr()})", rex.V1)
narrator_slash_pattern = re.compile(r"(?P<author>.+)\/(?P<narrator>.+)", re.I)
narrator_in_artist_pattern = re.compile(rf"(?P<author>.*)\W+{narrator_comment_pattern}", re.I)
graphic_audio_pattern = re.compile(r"graphic\s*audio", re.I)
lastname_firstname_pattern = re.compile(r"^(?P<lastname>.*?), (?P<firstname>.*)$", re.I)
firstname_lastname_pattern = re.compile(r"^(?P<firstname>.*?).*\s(?P<lastname>\S+)$", re.I)

book_title_pattern = re.compile(r"(?<=[-_–—])[\W\s]*(?P<book_title>[\w\s]+?)\s*(?=\d{4}|\(|\[|$)", re.I)
# partno_or_ch_match_pattern = re.compile(rf",?{_div}(?:part|ch(?:\.|apter))?{_div}\W*(?P<num1>\d+)(?:$|{_div}(?:of|-){_div}(?P<num2>\d+)\W*$)", re.I)
roman_numeral_pattern = re.compile(rf"({_roman_numeral})", re.I)
basic_part_or_ch_pattern = re.compile(r"(?:(?<=\W)|^)part|chapter|ch\.|pt\.", re.I)
partno_or_ch_match_pattern2 = re.compile(rf"(?:(?:(?:(?<=\W)|^)p|P)[Aa]?[Rr]?[Tt]|C[Hh]?(?:[\. ]|[Aa][Pp][Tt][Ee][Rr])|[^A-Za-z0-9\n]+?)\W*(?P<num1>(?:\d|{_roman_numeral})+)(?:.?(?:of|-|to).?(?P<num2>(?:\d|{_roman_numeral})+))?[^\n]*$")
part_or_ch_match_words = re.compile(rf"(?:(?<=\W)|^){_div}(?:pa?r?t|ch(?:\.|apter)){_div}(\d|{_roman_numeral})+.*$", re.I)
path_junk_pattern = re.compile(r"^[ \,.\)\}\]_-]*|[ \,.\)\}\]_-]*$", re.I)
path_garbage_pattern = re.compile(r"^[ \,.\)\}\]]*", re.I)
path_strip_l_t_alphanum_pattern = re.compile(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$", re.I)
roman_strip_pattern = re.compile(r"(?<=\w)(?=[\W_.-])|(?<=[\W_.-])(?=\w)|(?<=[a-z])(?=[A-Z])")

year_pattern = re.compile(r"(?P<year>\d{4})", re.I)

common_str_pattern = re.compile(r"(^common_|_c(ommon)?$)")
startswith_num_pattern = re.compile(r"(?P<num>^\d+)")

multi_disc_pattern = re.compile(r"(?:^|(?<=[\W_-]))(dis[ck]|cd)(\b|\s|[_.-])*#?(\b|\s|[_.-])*(?:\b|[\W_-])*(?P<num>\d+)", re.I)
book_series_pattern = re.compile(r"(?:^|(?<=[\W_-]))(bo{0,2}k|vol(?:ume)?|#)(?:\b|[\W_-])*(?P<num>\d+)|(?<=[\W_-])Series.*/.+", re.I)
series_parent_pattern = re.compile(rf"(?:(?<=\W)|^){_div}series{_div}.*$", re.I)
multi_part_pattern = re.compile(r"(?:^|(?<=[\W_-]))(pa?r?t|ch(?:\.|apter))(?:\b|[\W_-])*(\d+)", re.I)

only_non_alphanum_pattern = rex.compile(r"^[^\p{L}]+$")
abbreviated_names_pattern = re.compile(r"^(?:[A-Z]\.?){1,3}$")
uppercase_1_3_letters_pattern = re.compile(r"^(?:[A-Z]){1,3}$")
leading_trailing_non_alphanum_pattern = rex.compile(r"^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$", flags=rex.UNICODE)
open_library_user_agent_pattern = re.compile(r"^(?P<app>[^/]+)/(?P<version>[0-9.]+)? \((?P<email>[^\)]+)\)$") # matches: MyAppName/1.0 (myemail@example.com)
# fmt: on
