from math import floor
from pathlib import Path
from typing import Literal, overload

from pydantic import BaseModel, ConfigDict

from src.lib.books_tree import BooksTree
from src.lib.config import cfg
from src.lib.ffmpeg_utils import (
    DurationFmt,
    get_bitrate_py,
    get_duration,
    get_samplerate_py,
)
from src.lib.formatters import human_bitrate, to_audiobook_fmt
from src.lib.fs_utils import (
    count_audio_files_in_dir,
    cp_file_into_dir,
    find_cover_art_file,
    get_size,
    hash_path_audio_files,
    last_updated_at,
)
from src.lib.misc import get_dir_name_from_path
from src.lib.parsers import count_distinct_romans, extract_path_info, get_year_from_date
from src.lib.typing import AudiobookFmt, DirName, Id3TagDictWithDnumTnum, SizeFmt


class Audiobook(BaseModel):
    path: Path
    tree: BooksTree
    id3_title: str = ""
    id3_artist: str = ""
    id3_albumartist: str = ""
    id3_album: str = ""
    id3_sortalbum: str = ""
    id3_date: str = ""
    id3_year: str = ""
    id3_comment: str = ""
    id3_composer: str = ""
    id3_track_num: tuple[int, int] = (1, 1)
    id3_disc_num: tuple[int, int] = (1, 1)
    has_id3_cover: bool = False
    fs_author: str = ""
    fs_title: str = ""
    fs_year: str = ""
    fs_narrator: str = ""
    dir_extra_junk: str = ""
    file_extra_junk: str = ""
    _orig_file_type: AudiobookFmt = None  # type: ignore
    orig_file_name: str = ""
    title: str = ""
    artist: str = ""
    albumartist: str = ""
    album: str = ""
    sortalbum: str = ""
    date: str = ""
    year: str | None = None
    comment: str = ""
    composer: str = ""
    narrator: str = ""
    title_is_partno: bool = False
    track_num: tuple[int, int] = (1, 1)
    disc_num: tuple[int, int] = (1, 1)
    m4b_num_parts: int = 1
    _active_dir: DirName | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, path_or_tree: Path | BooksTree):

        path: Path = Path(path_or_tree) if isinstance(path_or_tree, (str, Path)) else path_or_tree.path
        if not (tree := (path_or_tree if isinstance(path_or_tree, BooksTree) else None)):
            from src.lib.inbox_state import InboxState

            inbox_state = InboxState()
            if from_state := inbox_state.get(path):
                tree = from_state.tree
            elif inbox_state.ready:
                # from src.lib.inbox_state import InboxStateError
                if inbox_state.is_empty():
                    inbox_state.scan()

                # if not inbox_state.is_empty():
                #     x = inbox_state.get(path)
                # else:
                #     inbox_state.scan()

                # raise InboxStateError(
                #     f"Book not found in inbox state, cannot attach tree to Audiobook instance: {path}"
                # )
        tree = tree or BooksTree(path_or_tree, scan_id3=False)

        super().__init__(path=path, tree=tree)

        self.tree = tree
        self.path = path

        self._active_dir = get_dir_name_from_path(path)
        self.orig_file_type

    def __str__(self):
        return f"{self.key}"

    def __repr__(self):
        return f"{self.key}"

    def extract_path_info(self, console: bool = False):
        return extract_path_info(self, console)

    def extract_metadata(self, console: bool = False):
        from src.lib.id3_utils import extract_metadata

        return extract_metadata(self, console)

    def extract_cover_art(self):
        from src.lib.id3_utils import extract_cover_art

        if self.cover_art_file:
            return self.cover_art_file
        try:
            extract_cover_art(self.sample_audio1, save_to_file=True)
            if art := self._inbox_cover_art_file:
                cp_file_into_dir(art, self.merge_dir)
            return self.cover_art_file
        except Exception:
            # no cover art found, probably
            return None

    def update_from_tags(self):
        from src.lib.id3_tags import Id3Tags

        new_tags = Id3Tags.from_file(self.sample_audio1, throw=False)
        if not new_tags:
            return
        if new_tags.album:
            self.album = new_tags.album
            self.id3_album = new_tags.album
        if new_tags.title:
            self.title = new_tags.title
            self.id3_title = new_tags.title
        if new_tags.artist:
            self.artist = new_tags.artist
            self.id3_artist = new_tags.artist
        if new_tags.albumartist:
            self.albumartist = new_tags.albumartist
            self.id3_albumartist = new_tags.albumartist
        if new_tags.composer:
            self.composer = new_tags.composer
            self.narrator = new_tags.composer
            self.id3_composer = new_tags.composer
        if new_tags.date:
            self.date = new_tags.date
            self.id3_date = new_tags.date
        if new_tags.track_num:
            self.track_num = (new_tags.track_num, new_tags.track_total or new_tags.track_num)
        if new_tags.disc_num:
            self.disc_num = (new_tags.disc_num, new_tags.disc_total or new_tags.disc_num)
        if new_tags.comment:
            self.comment = new_tags.comment
            self.id3_comment = new_tags.comment
        if new_tags.sortalbum:
            self.sortalbum = new_tags.sortalbum
            self.id3_sortalbum = new_tags.sortalbum
        if new_tags.year:
            self.id3_year = new_tags.year
        elif new_tags.date:
            self.id3_year = get_year_from_date(new_tags.date)

        return self

    @property
    def orig_file_type(self):
        from src.lib.fs_utils import find_first_audio_file

        if self._orig_file_type is not None:
            return self._orig_file_type
        if not (
            orig_file_type := (
                to_audiobook_fmt(f.suffix)
                if not self.tree.is_root and (f := find_first_audio_file(self.path, ignore_errors=True))
                else None
            )
        ):
            return "mp3"
        self._orig_file_type = orig_file_type
        return self._orig_file_type

    @property
    def inbox_dir(self):
        return self.path

    @property
    def backup_dir(self) -> Path:
        return cfg.backup_dir.resolve() / (self.key or "")

    @property
    def build_dir(self) -> Path:
        return cfg.build_dir.resolve() / (self.key or "")

    @property
    def build_tmp_dir(self) -> Path:
        return self.build_dir / f"~tmpfiles"

    @property
    def converted_dir(self) -> Path:
        if (p := cfg.converted_dir.resolve() / (self.key or "")).suffix == ".m4b":
            return p.with_suffix("")
        return p

    @property
    def archive_dir(self) -> Path:
        return cfg.archive_dir.resolve() / (self.key or "")

    @property
    def merge_dir(self) -> Path:
        return cfg.merge_dir.resolve() / (self.key or "")

    @property
    def build_file(self) -> Path:
        from src.lib.fs_utils import find_first_audio_file

        if self.build_dir.suffix == ".m4b":
            return self.build_dir
        try:
            return find_first_audio_file(self.build_dir, ext="m4b")
        except FileNotFoundError:
            return self.build_dir / f"{self.basename}.m4b"

    @property
    def converted_file(self) -> Path:
        from src.lib.config import cfg
        from src.lib.fs_utils import find_first_audio_file

        def _build_filename():
            filename = b.with_suffix("") if (b := Path(self.basename)) and b.suffix == ".m4b" else b.with_suffix(".m4b")
            return self.converted_dir / filename

        def _find_m4b_matching_basename():
            for f in self.converted_dir.rglob("*.m4b"):
                if self.basename in f.stem or f.stem in self.basename:
                    return f
            return _build_filename()

        if self.converted_dir == cfg.converted_dir:
            if found := _find_m4b_matching_basename():
                return found
            return _build_filename()
        try:
            if found := _find_m4b_matching_basename():
                return found
            return find_first_audio_file(self.converted_dir, ext="m4b")
        except FileNotFoundError:
            return _build_filename()

    @property
    def sample_audio1(self):
        from src.lib.fs_utils import find_first_audio_file

        return find_first_audio_file(self.path, ignore_errors=False)

    @property
    def sample_audio2(self):

        from src.lib.fs_utils import find_next_audio_file

        return find_next_audio_file(self.path, first=self.sample_audio1, ignore_errors=True)

    def rescan(self):
        self.tree.scan(allow_non_root=True)
        for attr in ["sample_audio1", "sample_audio2"]:
            try:
                delattr(self, attr)
            except AttributeError:
                pass
            getattr(self, attr)

    def last_updated_at(self, for_dir: DirName = "inbox"):
        return last_updated_at(getattr(self, for_dir + "_dir"), only_file_exts=cfg.AUDIO_EXTS)

    def hash(self, for_dir: DirName = "inbox"):
        return hash_path_audio_files(getattr(self, for_dir + "_dir"))

    @property
    def is_flatish(self):
        if not self.tree.has_structure_like("flat") or not self.tree.dirs:
            return False
        has_deep_files = len(self.tree.files_f) < len(self.tree.files_recursive_f)
        same_album = (self.tree.i.files_recursive.similarity("id3_albums", fallback=0.0)) > 0.9
        same_author = (self.tree.i.files_recursive.similarity("id3_authors", fallback=0.0)) > 0.9
        return has_deep_files and same_album and same_author

    @property
    def is_maybe_series_book(self):
        # return self.structure == "multi_book_series"
        return self._inbox_item.is_series_book if self._inbox_item else False

    @property
    def is_maybe_series_parent(self):
        return self._inbox_item.is_series_parent if self._inbox_item else False

    @property
    def is_first_book_in_series(self):
        return self._inbox_item.is_first_book_in_series if self._inbox_item else False

    @property
    def is_last_book_in_series(self):
        return self._inbox_item.is_last_book_in_series if self._inbox_item else False

    @property
    def series_parent(self):
        return self._inbox_item.series_parent if self._inbox_item else None

    @property
    def series_books(self):
        return self._inbox_item.series_books if self._inbox_item else None

    @property
    def series_basename(self):
        return self._inbox_item.series_basename if self._inbox_item else None

    @property
    def num_books_in_series(self):
        return self._inbox_item.num_books_in_series if self._inbox_item else -1

    def num_files(self, for_dir: DirName):
        d = for_dir + "_dir"
        this_dir = getattr(self, d)
        if for_dir == "inbox" and self.active_dir_name == "inbox" and self.tree:
            return self.tree.count_files()
        return count_audio_files_in_dir(this_dir, only_file_exts=cfg.AUDIO_EXTS)

    @property
    def num_roman_numerals(self):
        return count_distinct_romans(self.inbox_dir)

    @overload
    def size(self, for_dir: DirName, fmt: Literal["bytes"]) -> int: ...

    @overload
    def size(self, for_dir: DirName, fmt: Literal["human"]) -> str: ...

    def size(self, for_dir: DirName, fmt: SizeFmt = "bytes"):
        return get_size(getattr(self, for_dir + "_dir"), fmt=fmt)

    @overload
    def duration(self, for_dir: DirName, fmt: Literal["seconds"]) -> float: ...

    @overload
    def duration(self, for_dir: DirName, fmt: Literal["human"]) -> str: ...

    def duration(self, for_dir: DirName, fmt: DurationFmt = "seconds"):
        return get_duration(getattr(self, for_dir + "_dir"), fmt=fmt)

    @property
    def bitrate_actual(self):
        return get_bitrate_py(self.sample_audio1)[1]

    @property
    def bitrate_target(self):
        return get_bitrate_py(self.sample_audio1)[0]

    @property
    def samplerate(self):
        return get_samplerate_py(self.sample_audio1)

    @property
    def log_filename(self):
        return f"auto-m4b.{self.basename}.log"

    @property
    def log_file(self) -> Path:
        return (self.active_dir.parent if self.active_dir.is_file() else self.active_dir) / self.log_filename

    def write_log(self, *s: str):
        self.log_file.touch(exist_ok=True)
        # for each s, replace \n with a space
        lines = [x.replace("\n", " ") for x in s]
        with open(self.log_file, "a+") as f:
            # if file is not empty, and last line is not empty, add a newline
            if f.tell() and (existing := f.readlines()) and existing[-1].strip():
                f.write("\n")
            line = " ".join(lines)
            # ensure newline at end of file
            if not line.endswith("\n"):
                line += "\n"
            f.write(line)

    def set_active_dir(self, new_dir: DirName):
        self._active_dir = new_dir

    @property
    def active_dir(self) -> Path:
        return getattr(self, f"{self._active_dir or 'inbox'}_dir")

    @property
    def active_dir_name(self) -> DirName:
        return self._active_dir or "inbox"

    @property
    def author(self):
        return self.artist or self.albumartist or self.composer

    @property
    def bitrate_friendly(self):
        return human_bitrate(self.sample_audio1)

    @property
    def samplerate_friendly(self):  # round to nearest .1 kHz
        khz = self.samplerate / 1000
        if round(khz % 1, 2) <= 0.05:
            # if sample rate is .05 or less from a 0, round down to the nearest 0
            return f"{int(floor(khz))} kHz"
        return f"{round(khz, 1)} kHz"

    @property
    def _inbox_cover_art_file(self):
        return find_cover_art_file(self.path)

    @property
    def _converted_cover_art_file(self):
        return find_cover_art_file(self.converted_dir)

    @property
    def _merge_cover_art_file(self):
        return find_cover_art_file(self.merge_dir)

    @property
    def cover_art_file(self):

        if inbox_cover := self._inbox_cover_art_file:
            if self.merge_dir.exists():
                cp_file_into_dir(inbox_cover, self.merge_dir, overwrite_mode="skip-silent")
        return next(
            (
                f
                for f in iter((self._inbox_cover_art_file, self._converted_cover_art_file, self._merge_cover_art_file))
                if f
            ),
            None,
        )

    @property
    def id3_cover(self):
        from src.lib.id3_utils import extract_cover_art

        return extract_cover_art(self.sample_audio1, save_to_file=False)

    @property
    def basename(self):
        """The name of the book, including file extension if it is a single file,
        e.g 'The Book.mp3' or 'The Book' if it is a directory. Equivalent to `<book>.path.name`.
        """
        return self.path.name

    @property
    def key(self):
        return self.tree.key
        # return str(self.path.relative_to(cfg.inbox_dir))

    @property
    def _inbox_item(self):
        from src.lib.inbox_state import InboxState

        return InboxState().get(self.key)

    @property
    def merge_desc_file(self):
        return self.merge_dir / "description.txt"

    @property
    def final_desc_file(self):
        quality = f"{self.bitrate_friendly} @ {self.samplerate_friendly}".replace("kb/s", "kbps")
        return self.converted_dir / f"{self.basename} [{quality}].txt"

    def write_description_txt(self, out_path: Path | None = None):

        # Write the description to the file with newlines, ensure utf-8 encoding

        m4b_file = next(
            (f for f in [self.converted_file, self.build_file] if f.exists()),
            None,
        )
        converted_duration = get_duration(m4b_file, "human") if m4b_file else "N/A"
        converted_size = get_size(m4b_file, "human") if m4b_file else "N/A"
        orig_basename = f"{'File' if self.path.is_file() else 'Folder'} name: {self.basename}"

        content = f"""Book title: {self.title}
Author: {self.author}
Date: {self.date}
Narrator: {self.narrator}
Format: m4b
Quality: {self.bitrate_friendly} @ {self.samplerate_friendly}
Duration: {converted_duration}
Size: {converted_size}

(Original)
{orig_basename}
Format: {self.orig_file_type or 'N/A'}
Size: {self.size("inbox", "human")}
"""
        out_path = out_path or self.merge_desc_file
        # write the description to the file, overwriting if it already exists
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

        # check to make sure the file was created
        if not out_path.exists():
            raise ValueError(f"Failed to create {out_path}")

    def metadata(self):
        """Prints all known metadata for the book"""

        for k, v in self.model_dump().items():
            if k.startswith("_") or v is None or v == "":
                continue
            print(f"- {k}: {v}")

    def to_id3_tags(self) -> Id3TagDictWithDnumTnum:
        return {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "albumartist": self.albumartist,
            "composer": self.composer,
            "date": self.date,
            "track_num": self.track_num,
            "disc_num": self.disc_num,
        }
