from __future__ import annotations


def main() -> int:
    """Load and run the converter application on demand."""
    from src.otto_m4b import app

    return app()
