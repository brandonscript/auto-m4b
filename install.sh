#!/usr/bin/env bash
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [[ -h "$SOURCE" ]]; do
    SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$SCRIPT_DIR/$SOURCE"
done

SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR" >/dev/null 2>&1 && pwd)"
BIN_DIR="${BIN_DIR:-${HOME}/.local/bin}"

if ! command -v poetry >/dev/null 2>&1; then
    printf 'Poetry is required. Install it from https://python-poetry.org/docs/#installation\n' >&2
    exit 1
fi

printf 'Installing fixm4b from %s\n' "$REPO_ROOT"
poetry -C "$REPO_ROOT" install

if ! poetry -C "$REPO_ROOT" run python -c "import spacy; spacy.load('en_core_web_sm')" >/dev/null 2>&1; then
    printf 'Installing the spaCy English model\n'
    poetry -C "$REPO_ROOT" run python -m spacy download en_core_web_sm
fi

mkdir -p "$BIN_DIR"
ln -sfn "$REPO_ROOT/bin/fixm4b" "$BIN_DIR/fixm4b"

printf 'Installed fixm4b → %s/fixm4b\n' "$BIN_DIR"
if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
    printf 'Add %s to PATH to run fixm4b from any directory.\n' "$BIN_DIR"
fi
