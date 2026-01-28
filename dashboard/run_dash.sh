#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
eval "$(micromamba shell hook -s bash)"
micromamba activate bot
python app.py
