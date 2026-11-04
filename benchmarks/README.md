# Conversion benchmarks

`benchmark_conversion.py` measures the native conversion path against immutable
fixtures in `src/tests/fixtures/`. Each run executes in a fresh subprocess and
temporary directory, which keeps global state and output files from affecting
the next run.

The default workload covers:

- `basic_no_cover__single_mp3`: single-file conversion without cover art
- `basic_with_cover__single_mp3`: single-file conversion with cover art
- `tiny__flat_mp3`: multi-file chapterized conversion

Run the default benchmark with Poetry:

```bash
poetry run python benchmarks/benchmark_conversion.py \
  --output benchmarks/baseline.json
```

Use `--warmups 0` for a quick smoke test, or select cases explicitly:

```bash
poetry run python benchmarks/benchmark_conversion.py \
  --cases tiny__flat_mp3 \
  --warmups 1 \
  --iterations 5
```

The report includes median/minimum/maximum wall time, input/output sizes,
chapter count, verification time, and cumulative timings for conversion,
`ffprobe`, concat, metadata generation, and final embedding. Timings are
diagnostic rather than CI assertions; compare experiments using the same host,
fixture set, and `--cpu-cores` value.

Runtime baselines for cold imports and tree scans are collected separately:

```bash
poetry run python benchmarks/benchmark_runtime.py \
  --output benchmarks/runtime-baseline.json
```

This reports fresh-process import timings and `BooksTree` timings with and
without structure detection for representative nested and multi-file fixtures.
