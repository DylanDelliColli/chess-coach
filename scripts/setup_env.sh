#!/usr/bin/env bash
# Create this worktree's own virtualenv and install chessleak into it.
#
# Every worktree gets its own .venv (the design record's host plan): the release
# runs several workers on one host, and only pip's download cache is shared.
# Re-running this script is safe; it reuses an existing .venv and an already
# installed engine.
#
#   bash scripts/setup_env.sh
#
# Afterwards:
#   .venv/bin/python -m pytest          # unit + integration suites
#   .venv/bin/ruff check .              # lint
#   .venv/bin/ruff format --check .     # format check
#   .venv/bin/chessleak analyze --username <account>   # once the cli unit lands
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
log() { echo "setup_env: $*" >&2; }

"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' ||
  die "python 3.11+ is required, $PYTHON is $("$PYTHON" -V 2>&1)"

if [ ! -x .venv/bin/python ]; then
  log "creating .venv with $("$PYTHON" -V 2>&1)"
  "$PYTHON" -m venv .venv
else
  log "reusing .venv"
fi

log "installing chessleak (editable, with dev extras)"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e ".[dev]"

log "checking the shared Stockfish binary"
ENGINE="$(bash scripts/get_stockfish.sh)"

cat >&2 <<EOF

ready:
  engine   $ENGINE
  python   $PWD/.venv/bin/python
  pytest   $PWD/.venv/bin/python -m pytest
  lint     $PWD/.venv/bin/ruff check .
EOF
