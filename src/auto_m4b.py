import sys
import time
import traceback
from contextlib import contextmanager

from src.lib import run
from src.lib.config import AutoM4bArgs, cfg
from src.lib.inbox_state import InboxState
from src.lib.term import nl, print_error, print_red, was_prev_line_empty
from src.lib.term import print_debug as _print_debug
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
        cfg.startup(args)
        inbox = InboxState()

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
        # Delay starting the observer until the initial background scan
        # completes — both compete for SMB bandwidth and running them
        # concurrently roughly doubles I/O time.
        observer_started = False
        try:
            while True:
                # Use a timeout so the loop wakes periodically and re-checks
                # inbox.ready — important when the initial scan runs in the
                # background (large SMB inbox, slow first-time structure scan).
                dirty.wait(timeout=cfg.SLEEP_TIME)
                dirty.clear()
                _print_debug(
                    f"[watchdog] woke — ready={inbox.ready}, loop={inbox.loop_counter}"
                )
                if not inbox.ready:
                    # Background initial scan still in progress; wait longer.
                    _print_debug("[watchdog] inbox not ready yet, sleeping...")
                    continue
                if not observer_started:
                    observer.start()
                    observer_started = True
                inbox.loop_counter += 1
                with use_error_handler():
                    run.process_inbox()
        finally:
            if observer_started:
                observer.stop()
                observer.join()


if __name__ == "__main__":
    app()
