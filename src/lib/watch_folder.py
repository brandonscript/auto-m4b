import shutil
import time
from pathlib import Path

from src.lib.fs_utils import is_audio_file
from src.lib.term import print_debug, print_warning, smart_print, tint_path


_IGNORE_DIR_NAMES: frozenset[str] = frozenset({"@eaDir", "@tmp", ".DS_Store"})

# Written into the SOURCE directory after a successful copy to inbox.
# Prevents re-copying if the user later moves/deletes the converted m4b
# or the archive, which would otherwise fool _is_already_handled.
_MARKER_NAME = ".auto-m4b"


class WatchFolder:
    """
    Scans a secondary source folder (WATCH_FOLDER) for audiobooks that need
    conversion and copies qualifying directories to the inbox.

    A directory qualifies when it contains more than one file whose extension
    is in AUDIO_EXTS (.mp3, .m4a, .m4b, .aac, .wma).  Video files (.mkv, .mp4,
    .mov, .m4v, .avi, …) are intentionally excluded from the count — this
    prevents music albums or video-with-commentary folders from being
    incorrectly treated as audiobooks.

    Stability check: no file in the tree may have been modified within
    cfg.WAIT_TIME seconds and no Deluge in-progress (.part) file may be
    present before a directory is eligible for copying.
    """

    @staticmethod
    def _audio_file_count(path: Path) -> int:
        """Count audio files (AUDIO_EXTS only) recursively inside *path*."""
        return sum(1 for f in path.rglob("*") if f.is_file() and is_audio_file(f))

    @staticmethod
    def is_stable(path: Path) -> bool:
        """
        Return True if *path* is safe to copy.

        A directory is stable when:
        - No file inside it has been modified within cfg.WAIT_TIME seconds.
        - No ``.part`` file is present (Deluge's in-progress download marker).
        """
        from src.lib.config import cfg

        cutoff = time.time() - cfg.WAIT_TIME
        try:
            for f in path.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() == ".part":
                    print_debug(f"[watch_folder] .part file present, not stable: {f.name!r}")
                    return False
                try:
                    if f.stat().st_mtime > cutoff:
                        return False
                except OSError:
                    pass
        except OSError:
            return False
        return True

    @staticmethod
    def _is_already_handled(source: Path) -> bool:
        """
        Return True if *source* has already been queued or processed.

        Checks in order:
        1. Our own marker file inside the source directory (written after a
           successful copy).  This survives the user moving/deleting the
           converted m4b or the archive entry.
        2. The directory name exists in the inbox, converted, or archive folder.
        """
        from src.lib.config import cfg

        if (source / _MARKER_NAME).exists():
            return True

        name = source.name
        for root in (cfg.inbox_dir, cfg.converted_dir, cfg.archive_dir):
            if (root / name).exists():
                return True
        return False

    @staticmethod
    def _should_ignore(path: Path) -> bool:
        """Return True if this directory should be silently skipped."""
        name = path.name
        return name.startswith(".") or name.startswith("#") or name in _IGNORE_DIR_NAMES

    @staticmethod
    def find_convertible_books() -> list[Path]:
        """
        Return directories in watch_dir that contain more than one audio file
        and are not already present in the inbox, converted, or archive folder.

        Only the top level of watch_dir is scanned (mindepth/maxdepth=1) to
        avoid treating individual disc or chapter subdirectories as separate
        books.
        """
        from src.lib.config import cfg

        if not cfg.watch_dir or not cfg.watch_dir.exists():
            return []

        results: list[Path] = []
        try:
            candidates = sorted(cfg.watch_dir.iterdir())
        except OSError as exc:
            print_warning(f"[watch_folder] cannot read watch dir: {exc}")
            return []

        for candidate in candidates:
            if not candidate.is_dir():
                continue
            if WatchFolder._should_ignore(candidate):
                print_debug(f"[watch_folder] ignoring: {candidate.name!r}")
                continue
            if WatchFolder._is_already_handled(candidate):
                print_debug(f"[watch_folder] already handled: {candidate.name!r}")
                continue
            count = WatchFolder._audio_file_count(candidate)
            if count > 1:
                print_debug(f"[watch_folder] queued: {candidate.name!r} ({count} audio files)")
                results.append(candidate)
            else:
                print_debug(f"[watch_folder] skipping (≤1 audio file): {candidate.name!r}")

        return results

    @staticmethod
    def scan_and_copy() -> list[Path]:
        """
        Find all convertible books in watch_dir, check stability, and copy
        them to the inbox.  Returns the list of inbox paths that were created.

        Is a no-op when cfg.watch_dir is None (WATCH_FOLDER not set).
        """
        from src.lib.config import cfg

        if not cfg.watch_dir:
            return []

        copied: list[Path] = []
        for book in WatchFolder.find_convertible_books():
            if not WatchFolder.is_stable(book):
                print_debug(f"[watch_folder] not yet stable, skipping: {book.name!r}")
                continue
            dest = cfg.inbox_dir / book.name
            if dest.exists():
                # Guard against a race where the book was just copied in the
                # same scan pass (find_convertible_books already checks this on
                # the next call via _is_already_handled, so this only fires in
                # the edge case of two books with the same name in one pass).
                print_debug(f"[watch_folder] destination already exists: {book.name!r}")
                continue
            ln = "Copying book to inbox → "
            smart_print(f"{ln}{tint_path(str(book))}")
            try:
                shutil.copytree(book, dest, dirs_exist_ok=True)
                copied.append(dest)
                # Drop a marker so this source dir is recognised as already
                # handled on the next scan, even if the user later removes
                # the converted m4b or archive entry.
                try:
                    (book / _MARKER_NAME).write_text("")
                except OSError:
                    pass  # read-only share or permission denied — silent fallback
            except OSError as exc:
                print_warning(f"[watch_folder] copy failed for {book.name!r}: {exc}")

        return copied
