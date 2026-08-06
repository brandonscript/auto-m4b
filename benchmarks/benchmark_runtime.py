#!/usr/bin/env python3
"""Benchmark cold imports and BooksTree scanning.

Run with:
    poetry run python benchmarks/benchmark_runtime.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parents[1].resolve()
FIXTURE_ROOT = REPO_ROOT / "src" / "tests" / "fixtures"

DEFAULT_IMPORTS = ("src", "src.auto_m4b", "src.fixm4b", "src.fix_metadata", "src.lib.nlp")
DEFAULT_SCANS = ("tiny__flat_mp3", "nathan_lowell__nested_series_m4a", "secret_project_series__nested_flat_mixed")


def _run_subprocess(code: str) -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    payload["wall_seconds"] = elapsed
    return payload


def _benchmark_import(module: str) -> dict[str, Any]:
    return _run_subprocess(
        "import json, sys; "
        f"__import__({module!r}); "
        "print(json.dumps({'module': sys.modules.get("
        f"{module!r}).__name__ if {module!r} in sys.modules else {module!r}, "
        "'loaded_nlp': any(name.startswith('spacy') or name.startswith('nltk') "
        "for name in sys.modules)}))"
    )


def _benchmark_scan(fixture: str, determine_structure: bool) -> dict[str, Any]:
    path = FIXTURE_ROOT / fixture
    if not path.is_dir():
        raise SystemExit(f"fixture directory not found: {path}")
    return _run_subprocess(
        "import json, time; "
        "from pathlib import Path; "
        "from src.lib.books_tree import BooksTree; "
        f"path = Path({str(path)!r}); "
        "started = time.perf_counter(); "
        f"tree = BooksTree(path, determine_structure={determine_structure!r}); "
        "elapsed = time.perf_counter() - started; "
        "print(json.dumps({'fixture': path.name, "
        f"'determine_structure': {determine_structure!r}, "
        "'directories': len(tree.dirs_recursive), "
        "'files': len(tree.files_recursive), "
        "'books': len(tree.books), "
        "'seconds': elapsed}))"
    )


def _summarize(values: list[dict[str, Any]], key: str) -> dict[str, float]:
    numbers = [float(value[key]) for value in values]
    return {"median": statistics.median(numbers), "min": min(numbers), "max": max(numbers)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imports", nargs="+", default=list(DEFAULT_IMPORTS))
    parser.add_argument("--scans", nargs="+", default=list(DEFAULT_SCANS))
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    imports = {
        module: [_benchmark_import(module) for _ in range(args.iterations)]
        for module in args.imports
    }
    scans = {
        fixture: {
            str(determine_structure).lower(): [
                _benchmark_scan(fixture, determine_structure) for _ in range(args.iterations)
            ]
            for determine_structure in (False, True)
        }
        for fixture in args.scans
    }
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "iterations": args.iterations,
        "imports": {
            module: {
                "wall_seconds": _summarize(runs, "wall_seconds"),
                "nlp_loaded": any(run["loaded_nlp"] for run in runs),
            }
            for module, runs in imports.items()
        },
        "scans": {
            fixture: {
                mode: {
                    "wall_seconds": _summarize(runs, "seconds"),
                    "directories": runs[0]["directories"],
                    "files": runs[0]["files"],
                    "books": runs[0]["books"],
                }
                for mode, runs in modes.items()
            }
            for fixture, modes in scans.items()
        },
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
