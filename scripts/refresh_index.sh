#!/usr/bin/env bash
# Fetch the allowlist, rebuild chunks, and replace the Chroma index when the text changed.
#
# Install with crontab -e. Example, 02:30 every day:
# 30 2 * * * /absolute/path/to/Buildhour1Nov/scripts/refresh_index.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "missing ${PY}; create the virtualenv and pip install -r requirements.txt" >&2
  exit 1
fi

mkdir -p "${ROOT}/logs"
LOG="${ROOT}/logs/refresh.log"

{
  echo "---- $(date -u +%Y-%m-%dT%H:%M:%SZ) start ----"
  echo "scrape"
  "$PY" -m src.scrape
  echo "load"
  "$PY" -m src.load
  echo "chunk"
  "$PY" -m src.chunk
  echo "embed"
  "$PY" -m src.embed
  echo "---- $(date -u +%Y-%m-%dT%H:%M:%SZ) done ----"
} >>"$LOG" 2>&1
