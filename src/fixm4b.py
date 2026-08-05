"""Interrupt-safe console entrypoint for fix-metadata."""

from __future__ import annotations

import sys


def _meow() -> int:
    print()
    try:
        from src.lib.term import print_pink

        print_pink("Meow.")
    except KeyboardInterrupt:
        # Keep Ctrl+C handling reliable even if formatting is interrupted.
        print("Meow.")
    return 130


def main() -> int:
    try:
        # Import lazily so Ctrl+C during expensive NLP initialization is caught.
        from src.fix_metadata import main as run

        return run()
    except KeyboardInterrupt:
        return _meow()


if __name__ == "__main__":
    sys.exit(main())
