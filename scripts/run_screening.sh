#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
log="logs/screening.log"
echo "[$(date -Is)] screening start" | tee -a "$log"
if ! python3 main.py screen 2>&1 | tee -a "$log"; then
  echo "[$(date -Is)] screening failed" | tee -a "$log" >&2
  exit 1
fi
python3 main.py report 2>&1 | tee -a "$log"
echo "[$(date -Is)] screening complete" | tee -a "$log"
