#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
eval "$(micromamba shell hook -s bash)"
micromamba activate bot
uvicorn app.main:app --host 0.0.0.0 --port 8000
