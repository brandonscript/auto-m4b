#!/usr/bin/env bash
set -euo pipefail

cat <<'EOF'
fixm4b has moved to a standalone package.

Install options:
  pip install fixm4b
  brew install brandonscript/tap/fixm4b

Or from the sibling checkout:
  cd ../fixm4b && ./install.sh

Inside this auto-m4b repo, `poetry install` already provides the
`fixm4b` console script via the path dependency on ../fixm4b.
EOF
