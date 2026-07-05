import sys
import time
import traceback
from contextlib import contextmanager

from src.lib import run
from src.lib.config import AutoM4bArgs, cfg
from src.lib.inbox_state import InboxState
from src.lib.term import nl, print_error, print_red, was_prev_line_empty
from src.lib.typing import copy_kwargs_omit_first_arg


def handle_err(e: Exception):

    from src.lib.config import cfg

    if cfg.CRASH_PROTECTION:
        with open(cfg.FATAL_FILE, "a") as f:
            f.write(str(e))

    if cfg.DEBUG:
        print_red(f"\n{traceback.format_exc()}")
    else:
        print_error(f"Error: {e}")

    if cfg.CRASH_PROTECTION:
        err = f"auto-m4b fatally crashed - delete the error lock file before restarting:\n\n {cfg.FATAL_FILE}"
        print_error(err)

    if "pytest" in sys.modules:
        raise e

    time.sleep(cfg.SLEEP_TIME)


@contextmanager
def use_error_handler():
    try:
        yield
    except Exception as e:
        handle_err(e)


@copy_kwargs_omit_first_arg(AutoM4bArgs.__init__)
def app(**kwargs):
    with use_error_handler():
        import threading

        args = AutoM4bArgs(**kwargs)
        inbox = InboxState()
        cfg.startup(args)

        # ── Test / finite-loop path ────────────────────────────────────────────
        # Keep the original while/sleep loop so all existing tests continue to
        # work without modification.
        if args.max_loops != -1:
            while inbox.loop_counter < args.max_loops:
                inbox.loop_counter += 1
                run.process_inbox()
                if inbox.loop_counter < args.max_loops:
                    time.sleep(cfg.SLEEP_TIME)

            if not was_prev_line_empty():
                nl()
            return

        # ── Production path: event-driven ─────────────────────────────────────
        # PollingObserver is used (not inotify) because the inbox lives on an
        # SMB/CIFS mount where kernel inotify events are not delivered.
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers.polling import PollingObserver

        dirty = threading.Event()

        class _InboxHandler(FileSystemEventHandler):
            def on_any_event(self, event):
                if not event.is_directory:
                    dirty.set()

        # Initial scan
        inbox.loop_counter += 1
        run.process_inbox()

        observer = PollingObserver(timeout=cfg.SLEEP_TIME)
        observer.schedule(_InboxHandler(), str(cfg.inbox_dir), recursive=True)
        observer.start()
        try:
            while True:
                dirty.wait()
                dirty.clear()
                inbox.loop_counter += 1
                with use_error_handler():
                    run.process_inbox()
        finally:
            observer.stop()
            observer.join()


if __name__ == "__main__":
    app()
