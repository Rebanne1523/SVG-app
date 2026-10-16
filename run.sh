#!/usr/bin/env bash
# Run VectorFlow from source. Creates a private virtualenv the first time.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo ">> First run: creating virtualenv and installing dependencies (one time only)..."
    python -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/python -m vectorflow "$@"
