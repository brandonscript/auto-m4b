import threading
import time
from pathlib import Path

from src.lib.formatters import human_elapsed_time
from src.lib.fs_utils import hash_path_audio_files, last_updated_audio_files_at


class Hasher:
    """Stores the current, and previous 5 hashes of a given path as a tuple. When a new hash is added, the oldest one is removed, and the rest are shifted down by one. If a hash is the same as the previous one, it is not added - only the timestamp on the current hash is updated. This is used to determine if a file has changed in the last 5 seconds."""

    def __init__(self, path: Path, max_hashes: int = 10):
        self.path = path
        self.max_hashes = max_hashes
        self._hashes = []
        self._last_run_start = None
        self._last_run_end = None
        self.stale = True
        self.flush()

    def __repr__(self):
        return f"{self.path} -- {self._hashes} -- {human_elapsed_time(time.time() - self.last_updated)}"

    def __eq__(self, other):
        return self.path == other.path

    @property
    def last_updated(self):
        return last_updated_audio_files_at(self.path)

    def scan(self):
        with threading.Lock():
            new_hash = self.next_hash
            if new_hash != self.curr_hash:
                self._hashes.insert(0, (new_hash, time.time()))
                if len(self._hashes) > self.max_hashes:
                    self._hashes.pop()

    @property
    def hashes(self):
        # returns self._hashes, but calculates time since on each hash
        return [(h, time.time() - t) for h, t in self._hashes]

    @property
    def time_since_last_change(self):
        return time.time() - self.last_updated

    @property
    def hash_age(self):
        return time.time() - self.last_hash_change

    @property
    def last_hash_change(self):
        return self._hashes[0][1] if self._hashes else 0

    @property
    def dir_was_recently_modified(self):
        from src.lib.config import cfg

        mod = self.time_since_last_change < cfg.WAIT_TIME
        if mod:
            self.stale = True
        return mod

    @property
    def hash_was_recently_changed(self):
        from src.lib.config import cfg

        return self.hash_age < cfg.WAIT_TIME + cfg.SLEEP_TIME

    @property
    def curr_hash(self):
        return self._hashes[0][0]

    @property
    def prev_hash(self):
        return self._hashes[1][0] if len(self._hashes) > 1 else ""

    @property
    def next_hash(self):
        return hash_path_audio_files(self.path)

    @property
    def last_run_start_hash(self):
        return self._last_run_start[0] if self._last_run_start else ""

    @property
    def last_run_end_hash(self):
        return self._last_run_end[0] if self._last_run_end else ""

    def to_dict(self):
        return {
            "path": str(self.path),
            "hashes": self._hashes,
            "last_updated": self.last_updated,
        }

    def flush(self):
        self._hashes = [(self.next_hash, self.last_updated)]

    def __hash__(self):
        return hash(self.path)

    def __str__(self):
        return self.__repr__()
