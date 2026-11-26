#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 path/to/transactions.csv" >&2
  exit 64
fi
mkdir -p logs
log="logs/ingest.log"
echo "[$(date -Is)] ingest start: $1" | tee -a "$log"
if ! python3 main.py ingest "$1" 2>&1 | tee -a "$log"; then
  echo "[$(date -Is)] ingest failed" | tee -a "$log" >&2
  exit 1
fi
echo "[$(date -Is)] ingest complete" | tee -a "$log"
