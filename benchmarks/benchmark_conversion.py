#!/usr/bin/env python3
"""Benchmark native conversion throughput using immutable repository fixtures.

Run with:
    poetry run python benchmarks/benchmark_conversion.py
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parents[1].resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_CASES = (
    "basic_no_cover__single_mp3",
    "basic_with_cover__single_mp3",
    "tiny__flat_mp3",
)


def _fixture_root() -> Path:
    return REPO_ROOT / "src" / "tests" / "fixtures"


def _probe_output(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_chapters",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _timed(
    timings: dict[str, float],
    name: str,
    function: Callable[..., Any],
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            timings[name] = timings.get(name, 0.0) + time.perf_counter() - started

    return wrapped


def _worker(fixture_name: str, cpu_cores: int) -> None:
    fixture = _fixture_root() / fixture_name
    if not fixture.is_dir():
        raise SystemExit(f"fixture directory not found: {fixture}")

    with tempfile.TemporaryDirectory(prefix="auto-m4b-benchmark-") as temp:
        root = Path(temp)
        inbox = root / "inbox"
        converted = root / "converted"
        archive = root / "archive"
        backup = root / "backup"
        working = root / "working"
        target = inbox / fixture.name
        shutil.copytree(fixture, target)

        os.environ.update(
            {
                "INBOX_FOLDER": str(inbox),
                "CONVERTED_FOLDER": str(converted),
                "ARCHIVE_FOLDER": str(archive),
                "BACKUP_FOLDER": str(backup),
                "WORKING_FOLDER": str(working),
                "BACKUP": "N",
                "CPU_CORES": str(cpu_cores),
                "DEBUG": "N",
                "GOODSCRAPS_USER_AGENT": "",
                "OPEN_LIBRARY_USER_AGENT": "",
                "ON_COMPLETE": "test_do_nothing",
                "SLEEP_TIME": "0",
            }
        )
        timings: dict[str, float] = {}
        started = time.perf_counter()
        with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
            from src.lib.audiobook import Audiobook
            from src.lib.books_tree import BooksTree
            from src.lib.config import cfg
            from src.lib.converter import merge
            from src.lib.converter import convert_book_native
            imports_finished = time.perf_counter()

            for name in (
                "_convert_file_to_mp4",
                "_ffprobe_duration_ms",
                "_ffprobe_title_tag",
                "_concat_to_m4b",
                "_embed_metadata_and_cover",
                "write_ffmetadata",
            ):
                setattr(merge, name, _timed(timings, name, getattr(merge, name)))

            cfg.clear_cached_attrs()
            operation_started = time.perf_counter()
            book = Audiobook(BooksTree(target))
            book_created = time.perf_counter()
            book.extract_path_info()
            path_info_finished = time.perf_counter()
            book.extract_metadata()
            metadata_finished = time.perf_counter()
            book.set_active_dir("merge")
            book.merge_dir.mkdir(parents=True, exist_ok=True)
            for source in target.iterdir():
                destination = book.merge_dir / source.name
                if source.is_dir():
                    shutil.copytree(source, destination)
                else:
                    shutil.copy2(source, destination)
            prepared = time.perf_counter()
            convert_book_native(book)
            conversion_finished = time.perf_counter()
        elapsed = time.perf_counter() - started

        outputs = sorted(book.build_dir.rglob("*.m4b"))
        if len(outputs) != 1:
            raise RuntimeError(f"expected one output m4b, found {len(outputs)}")
        probe_started = time.perf_counter()
        probe = _probe_output(outputs[0])
        verification_seconds = time.perf_counter() - probe_started
        source_files = [
            path
            for path in target.rglob("*")
            if path.is_file() and path.suffix.lower() in {".mp3", ".m4a", ".m4b", ".aac"}
        ]
        result = {
            "fixture": fixture_name,
            "source_files": len(source_files),
            "input_bytes": sum(path.stat().st_size for path in source_files),
            "output_bytes": outputs[0].stat().st_size,
            "duration_seconds": float(probe["format"]["duration"]),
            "chapters": len(probe.get("chapters", [])),
            "wall_seconds": elapsed,
            "import_seconds": imports_finished - started,
            "book_construction_seconds": book_created - operation_started,
            "path_info_seconds": path_info_finished - book_created,
            "metadata_extraction_seconds": metadata_finished - path_info_finished,
            "merge_staging_seconds": prepared - metadata_finished,
            "preparation_seconds": prepared - started,
            "conversion_wall_seconds": conversion_finished - prepared,
            "verification_seconds": verification_seconds,
            "stages": timings,
        }
        print(json.dumps(result, sort_keys=True))


def _run_once(fixture_name: str, cpu_cores: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        fixture_name,
        "--cpu-cores",
        str(cpu_cores),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def _summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    def median(key: str) -> float:
        return statistics.median(float(run[key]) for run in runs)

    stage_names = sorted({name for run in runs for name in run["stages"]})
    return {
        "fixture": runs[0]["fixture"],
        "runs": len(runs),
        "source_files": runs[0]["source_files"],
        "input_bytes": runs[0]["input_bytes"],
        "output_bytes": runs[0]["output_bytes"],
        "duration_seconds": runs[0]["duration_seconds"],
        "chapters": runs[0]["chapters"],
        "wall_seconds": {"median": median("wall_seconds"), "min": min(float(r["wall_seconds"]) for r in runs), "max": max(float(r["wall_seconds"]) for r in runs)},
        "preparation_seconds": median("preparation_seconds"),
        "import_seconds": median("import_seconds"),
        "book_construction_seconds": median("book_construction_seconds"),
        "path_info_seconds": median("path_info_seconds"),
        "metadata_extraction_seconds": median("metadata_extraction_seconds"),
        "merge_staging_seconds": median("merge_staging_seconds"),
        "conversion_wall_seconds": median("conversion_wall_seconds"),
        "verification_seconds": median("verification_seconds"),
        "stages": {name: statistics.median(float(run["stages"].get(name, 0.0)) for run in runs) for name in stage_names},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", metavar="FIXTURE", help=argparse.SUPPRESS)
    parser.add_argument("--cases", nargs="+", default=list(DEFAULT_CASES))
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--cpu-cores", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.worker:
        _worker(args.worker, args.cpu_cores)
        return 0

    for case in args.cases:
        for _ in range(args.warmups):
            _run_once(case, args.cpu_cores)

    summaries = []
    for case in args.cases:
        runs = [_run_once(case, args.cpu_cores) for _ in range(args.iterations)]
        summaries.append(_summarize(runs))

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "cpu_cores": args.cpu_cores,
        "warmups": args.warmups,
        "iterations": args.iterations,
        "cases": summaries,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
