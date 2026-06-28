"""Native Python audiobook merge — replaces the m4b-tool PHP subprocess call."""

from __future__ import annotations

import subprocess
import tempfile
import time
from concurrent.futures import as_completed, ThreadPoolExecutor
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from src.lib.converter.chapters import (
    build_chapters_from_files,
    dedupe_names,
    parse_chapters_txt,
)
from src.lib.converter.encoder import detect_aac_codec, CODEC_AAC
from src.lib.converter.ffmetadata import write_ffmetadata
from src.lib.converter.naturalsort import natural_sort_files

if TYPE_CHECKING:
    from src.lib.audiobook import Audiobook


def _ffprobe_duration_ms(path: Path) -> int:
    """Return the exact duration of *path* in milliseconds via ffprobe."""
    try:
        import ffmpeg as _ffmpeg

        duration_s = float(_ffmpeg.probe(str(path))["format"]["duration"])
        return round(duration_s * 1000)
    except Exception:
        # fall back to subprocess ffprobe
        result = subprocess.run(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        try:
            return round(float(result.stdout.strip()) * 1000)
        except ValueError:
            return 0


def _ffprobe_title_tag(path: Path) -> Optional[str]:
    """Return the 'title' tag from *path*, or None."""
    try:
        import ffmpeg as _ffmpeg

        tags = _ffmpeg.probe(str(path))["format"].get("tags", {}) or {}
        return tags.get("title") or tags.get("Title")
    except Exception:
        return None


def _convert_file_to_mp4(
    src: Path,
    dst: Path,
    *,
    copy: bool,
    codec: str,
    bitrate: int,
    samplerate: int,
    debug: bool = False,
) -> None:
    """Convert a single source audio file to an MP4 container in *dst*."""
    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error" if not debug else "verbose", "-y"]
    cmd += ["-i", str(src)]

    if copy:
        # Remux in-place — strip video/cover art streams to keep concat clean
        cmd += ["-vn", "-acodec", "copy", "-f", "mp4"]
    else:
        cmd += [
            "-vn",
            "-acodec",
            codec,
            "-b:a",
            f"{bitrate}k",
            "-ar",
            str(samplerate),
            # No faststart for intermediate temp files – faststart requires
            # ffmpeg to re-open the file for a second pass and can fail on
            # temp paths.  The final concat output has faststart applied.
            "-max_muxing_queue_size",
            "9999",
            "-f",
            "mp4",
        ]
        if codec == CODEC_AAC:
            cmd += ["-strict", "experimental"]

    cmd.append(str(dst))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed converting {src.name}:\n{result.stderr}"
        )


def _write_concat_list(tmp_files: list[Path], list_path: Path) -> None:
    """Write an ffmpeg concat demuxer list file.

    ffmpeg concat-demuxer paths use single-quoted strings.  Apostrophes inside
    the path must be escaped as ``'\\''`` (end-quote, literal quote, open-quote).
    """

    def _escape(p: Path) -> str:
        return str(p).replace("'", "'\\''")

    lines = [f"file '{_escape(f)}'\n" for f in tmp_files]
    list_path.write_text("".join(lines), encoding="utf-8")


def _concat_to_m4b(list_path: Path, output: Path, *, debug: bool = False) -> None:
    """Concatenate the temp MP4 files listed in *list_path* into a single MP4."""
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error" if not debug else "verbose",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-vn",
        "-c",
        "copy",
        "-max_muxing_queue_size",
        "9999",
        "-movflags",
        "+faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed:\n{result.stderr}")


def _embed_metadata_and_cover(
    audio: Path,
    meta: Path,
    output: Path,
    cover: Optional[Path] = None,
    *,
    debug: bool = False,
) -> None:
    """Remux *audio* with ffmetadata *meta* (and optional *cover*) into *output*."""
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error" if not debug else "verbose",
        "-y",
        "-i",
        str(audio),
        "-i",
        str(meta),
    ]

    if cover and cover.is_file():
        cmd += ["-i", str(cover)]
        cmd += [
            "-map",
            "0:a",
            "-map",
            "2:v",
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-c",
            "copy",
            "-c:v",
            "mjpeg",
            "-disposition:v",
            "attached_pic",
        ]
    else:
        cmd += [
            "-map",
            "0:a",
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-c",
            "copy",
        ]

    cmd += ["-movflags", "+faststart", str(output)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg metadata embed failed:\n{result.stderr}")


def _find_chapters_txt(directory: Path) -> Optional[Path]:
    matches = sorted(directory.glob("*chapters.txt"))
    return matches[0] if matches else None


def _collect_audio_files(directory: Path) -> list[Path]:
    """Return natural-sorted audio files from *directory* (all depths)."""
    from src.lib.config import AUDIO_EXTS

    files = [
        f for f in directory.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXTS
    ]
    return natural_sort_files(files)


def convert_book_native(book: "Audiobook") -> int:
    """Native Python implementation of ``m4b-tool merge``.

    Converts all audio files in *book.merge_dir* to a single ``.m4b`` file
    written at *book.build_file*, then returns elapsed seconds.

    Raises on any unrecoverable error so the caller can call
    ``fail_book`` and ``write_log``.
    """
    from src.lib.config import cfg

    starttime = time.time()
    debug: bool = bool(cfg.DEBUG)

    merge_dir: Path = book.merge_dir
    build_file: Path = book.build_file
    tmp_dir: Path = book.build_tmp_dir

    tmp_dir.mkdir(parents=True, exist_ok=True)
    build_file.parent.mkdir(parents=True, exist_ok=True)

    # ── 1. Collect + sort source files ────────────────────────────────────────
    src_files = _collect_audio_files(merge_dir)
    if not src_files:
        raise FileNotFoundError(f"No audio files found in {merge_dir}")

    # ── 2. Determine codec strategy ───────────────────────────────────────────
    should_copy = book.orig_file_type in ("m4a", "m4b")
    codec = detect_aac_codec()
    bitrate: int = book.bitrate_target
    samplerate: int = book.samplerate

    # ── 3. Per-file convert to temp MP4 (parallel) ────────────────────────────
    def _convert_one(i: int, src: Path) -> tuple[int, Path]:
        dst = tmp_dir / f"{i:05d}_{src.stem}.mp4"
        _convert_file_to_mp4(
            src,
            dst,
            copy=should_copy,
            codec=codec,
            bitrate=bitrate,
            samplerate=samplerate,
            debug=debug,
        )
        return i, dst

    ordered: dict[int, Path] = {}
    max_workers = max(1, cfg.CPU_CORES)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_convert_one, i, f): i for i, f in enumerate(src_files)}
        for fut in as_completed(futures):
            idx, dst_path = fut.result()  # propagates exceptions
            ordered[idx] = dst_path

    tmp_files = [ordered[i] for i in sorted(ordered)]

    # ── 4. Get exact durations via ffprobe ────────────────────────────────────
    durations_ms = [_ffprobe_duration_ms(f) for f in tmp_files]

    # ── 5. Build chapters ─────────────────────────────────────────────────────
    chapters_txt = _find_chapters_txt(merge_dir)
    total_ms = sum(durations_ms)

    if chapters_txt:
        chapters = parse_chapters_txt(chapters_txt, total_ms)
    else:
        use_filenames = bool(cfg.USE_FILENAMES_AS_CHAPTERS)
        if use_filenames:
            tag_titles = None
        else:
            tag_titles = [_ffprobe_title_tag(f) for f in src_files]

        chapters = build_chapters_from_files(
            src_files, durations_ms, use_filenames=use_filenames, tag_titles=tag_titles
        )
        chapters = dedupe_names(chapters)

    # ── 6. Write ffmetadata ───────────────────────────────────────────────────
    meta_path = tmp_dir / "metadata.txt"
    write_ffmetadata(
        meta_path,
        chapters,
        title=book.title or None,
        artist=book.author or None,
        album=book.title or None,
        album_artist=book.author or None,
        composer=book.composer or None,
        comment=book.comment or None,
        date=book.date or book.year or None,
        genre="Audiobook",
        encoder="PHNTM",
        sort_name=book.title or None,
        sort_artist=book.author or None,
        sort_album=book.sortalbum or book.title or None,
    )

    # ── 7. Concat all temp files ───────────────────────────────────────────────
    concat_output = tmp_dir / "concat.mp4"

    if len(tmp_files) == 1:
        import shutil as _shutil

        _shutil.copy2(tmp_files[0], concat_output)
    else:
        list_path = tmp_dir / "concat_list.txt"
        _write_concat_list(tmp_files, list_path)
        _concat_to_m4b(list_path, concat_output, debug=debug)

    # ── 8. Resolve cover art ──────────────────────────────────────────────────
    cover: Optional[Path] = None
    if book.orig_file_type in ("m4a", "m4b") or not book.has_id3_cover:
        cover = book._merge_cover_art_file or (
            book.inbox_dir / book.cover_art_file.relative_to(book.inbox_dir)
            if book.cover_art_file
            else None
        )
        if cover and not cover.is_file():
            cover = None

    # ── 9. Embed metadata + cover → build_file ────────────────────────────────
    _embed_metadata_and_cover(
        concat_output,
        meta_path,
        build_file,
        cover=cover,
        debug=debug,
    )

    if not build_file.exists():
        raise RuntimeError(f"Conversion appeared to succeed but {build_file} was not created")

    elapsed = int(time.time() - starttime)
    return elapsed
