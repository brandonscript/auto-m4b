#!/usr/bin/env bash
set -euo pipefail
cd "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
poetry install --no-root
cat <<'EOF'

Run otto-m4b: poetry run python -m src
Run metadata repair: poetry run fixm4b
Standalone metadata repair: pip install fixm4b
EOF
