#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON:-/opt/homebrew/bin/python3.11}"

cd "${ROOT_DIR}"
exec "${PYTHON_BIN}" -m pytest tests/smoke -m l5 -q "$@"
