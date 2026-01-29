#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
DASHBOARD_DIR="$ROOT_DIR/dashboard"
SESSION_NAME="web-market-tracker"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required but not installed."
  exit 1
fi

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo "tmux session '$SESSION_NAME' already exists. Attach with: tmux attach -t $SESSION_NAME"
  exit 1
fi

pane_kafka="$(tmux new-session -d -s "$SESSION_NAME" -c "$ROOT_DIR" -P -F "#{pane_id}")"

# Pane 2: Ingest
pane_ingest="$(tmux split-window -h -t "$pane_kafka" -P -F "#{pane_id}")"

# Pane 3: API
pane_api="$(tmux split-window -v -t "$pane_kafka" -P -F "#{pane_id}")"

# Pane 4: Dash
pane_dash="$(tmux split-window -v -t "$pane_ingest" -P -F "#{pane_id}")"

tmux send-keys -t "$pane_kafka" "cd \"$BACKEND_DIR\" && sudo ./run_kafka.sh" C-m
tmux send-keys -t "$pane_ingest" "cd \"$BACKEND_DIR\" && eval \"\$(micromamba shell hook -s bash)\" && micromamba activate bot && sleep 8 && ./run_ingest.sh" C-m
tmux send-keys -t "$pane_api" "cd \"$BACKEND_DIR\" && eval \"\$(micromamba shell hook -s bash)\" && micromamba activate bot && sleep 8 && ./run_api.sh" C-m
tmux send-keys -t "$pane_dash" "cd \"$DASHBOARD_DIR\" && eval \"\$(micromamba shell hook -s bash)\" && micromamba activate bot && sleep 8 && ./run_dash.sh" C-m

tmux select-layout -t "$SESSION_NAME":0 tiled
tmux attach -t "$SESSION_NAME"
