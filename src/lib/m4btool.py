from typing import Any

from src.lib.audiobook import Audiobook
from src.lib.config import cfg
from src.lib.ffmpeg_utils import build_id3_tags_args
from src.lib.formatters import (
    friendly_date,
    pluralize,
)
from src.lib.fs_utils import *
from src.lib.misc import dockerize_volume
from src.lib.term import (
    smart_print,
    tint_light_grey,
    tinted_file,
    tinted_m4b,
)


class M4bTool:
    _cmd: list[Any]

    def __init__(self, book: Audiobook):
        def _(*new_arg: str | tuple[str, Any]):
            if isinstance(new_arg, tuple):
                self._cmd.extend(new_arg)
            else:
                self._cmd.append(new_arg)

        self.book = book
        self._cmd = cfg._m4b_tool + [
            "merge",
            str(dockerize_volume(book.merge_dir)),
            "-n",
        ]

        _("--debug" if cfg.DEBUG == "Y" else "-q")

        if self.should_copy:
            _(("--audio-codec", "copy"))
        else:
            _((f"--audio-codec", "libfdk_aac"))
            _((f"--audio-bitrate", book.bitrate_target))
            _((f"--audio-samplerate", book.samplerate))

        _(("--jobs", cfg.CPU_CORES))
        _(("--output-file", dockerize_volume(book.build_file)))
        _(("--logfile", dockerize_volume(book.log_file)))
        _("--no-chapter-reindexing")

        if (book.orig_file_type in ["m4a", "m4b"] or not book.has_id3_cover) and book.cover_art_file:
            _(("--cover", dockerize_volume(book.cover_art_file)))

        if cfg.USE_FILENAMES_AS_CHAPTERS:
            _("--use-filenames-as-chapters")

        if chapters_files := list(dockerize_volume(self.book.merge_dir).glob("*chapters.txt")):
            chapters_file = chapters_files[0]
            _(f'--chapters-file="{chapters_file}"')
            smart_print(
                f"Found {len(chapters_files)} chapters {pluralize(len(chapters_files), 'file')}, setting chapters from {tinted_file(chapters_file.name)}"
            )

        _(*build_id3_tags_args(book.title, book.author, book.year, book.comment))

    def build_cmd(self, quotify: bool = False) -> list[str]:
        out = []
        for arg in self._cmd:
            if isinstance(arg, tuple):
                k, v = arg
                if quotify and " " in str(v):
                    v = f'"{v}"'
                out.append(f"{k}={v}")
            else:
                out.append(str(arg))
        return out

    def esc_cmd(self) -> str:
        cmd = self.build_cmd(quotify=True)
        if cfg.USE_DOCKER:
            cmd.insert(2, "-it")
        cmd = [c for c in cmd if c != "-q"]
        return " ".join(cmd)

    @property
    def should_copy(self):
        return self.book.orig_file_type in ["m4a", "m4b"]

    def print_msg(self):
        starttime_friendly = friendly_date()
        if self.should_copy:
            smart_print(f"Starting merge/passthrough → {tinted_m4b()} at {tint_light_grey(starttime_friendly)}...")
        else:
            smart_print(
                f"Starting {tinted_file(self.book.orig_file_type)} → {tinted_m4b()} conversion at {tint_light_grey(starttime_friendly)}..."
            )
