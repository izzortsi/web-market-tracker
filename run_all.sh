#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
DASHBOARD_DIR="$ROOT_DIR/dashboard"
SESSION_NAME="web-market-tracker"

START_KAFKA="${START_KAFKA:-1}"
START_INGEST="${START_INGEST:-0}"
START_API="${START_API:-1}"
START_DASH="${START_DASH:-0}"
STARTUP_DELAY="${STARTUP_DELAY:-8}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required but not installed."
  exit 1
fi

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo "tmux session '$SESSION_NAME' already exists. Attach with: tmux attach -t $SESSION_NAME"
  exit 1
fi

tmux new-session -d -s "$SESSION_NAME" -c "$ROOT_DIR" -n "main"

tmux split-window -t "$SESSION_NAME:0" -h -c "$ROOT_DIR"
tmux split-window -t "$SESSION_NAME:0.0" -v -c "$ROOT_DIR"
tmux split-window -t "$SESSION_NAME:0.1" -v -c "$ROOT_DIR"
tmux select-layout -t "$SESSION_NAME:0" tiled

tmux select-pane -t "$SESSION_NAME:0.0" -T "kafka"
tmux select-pane -t "$SESSION_NAME:0.1" -T "ingest"
tmux select-pane -t "$SESSION_NAME:0.2" -T "api"
tmux select-pane -t "$SESSION_NAME:0.3" -T "dash"

if [[ "$START_KAFKA" == "1" ]]; then
  tmux send-keys -t "$SESSION_NAME:0.0" "cd \"$BACKEND_DIR\" && sudo ./run_kafka.sh" C-m
fi

if [[ "$START_INGEST" == "1" ]]; then
  tmux send-keys -t "$SESSION_NAME:0.1" "cd \"$BACKEND_DIR\" && eval \"\$(micromamba shell hook -s bash)\" && micromamba activate bot && sleep $STARTUP_DELAY && ./run_ingest.sh" C-m
fi

if [[ "$START_API" == "1" ]]; then
  tmux send-keys -t "$SESSION_NAME:0.2" "cd \"$BACKEND_DIR\" && eval \"\$(micromamba shell hook -s bash)\" && micromamba activate bot && sleep $STARTUP_DELAY && ./run_api.sh" C-m
fi

if [[ "$START_DASH" == "1" ]]; then
  tmux send-keys -t "$SESSION_NAME:0.3" "cd \"$DASHBOARD_DIR\" && eval \"\$(micromamba shell hook -s bash)\" && micromamba activate bot && sleep $STARTUP_DELAY && ./run_dash.sh" C-m
fi

tmux attach -t "$SESSION_NAME"
