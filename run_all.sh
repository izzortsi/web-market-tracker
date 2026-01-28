#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
DASHBOARD_DIR="$ROOT_DIR/dashboard"

find_terminal() {
  if command -v gnome-terminal >/dev/null 2>&1; then
    echo "gnome-terminal"
  elif command -v konsole >/dev/null 2>&1; then
    echo "konsole"
  elif command -v xfce4-terminal >/dev/null 2>&1; then
    echo "xfce4-terminal"
  elif command -v xterm >/dev/null 2>&1; then
    echo "xterm"
  else
    echo ""
  fi
}

TERMINAL_BIN="$(find_terminal)"
if [[ -z "$TERMINAL_BIN" ]]; then
  echo "No supported terminal emulator found (gnome-terminal/konsole/xfce4-terminal/xterm)."
  exit 1
fi

run_term() {
  local title="$1"
  local cmd="$2"

  case "$TERMINAL_BIN" in
    gnome-terminal)
      gnome-terminal --window --title="$title" -- bash -lc "$cmd; exec bash" &
      ;;
    konsole)
      konsole --title="$title" -e bash -lc "$cmd; exec bash" &
      ;;
    xfce4-terminal)
      xfce4-terminal --disable-server --title="$title" --command "bash -lc \"$cmd; exec bash\"" &
      ;;
    xterm)
      xterm -T "$title" -e bash -lc "$cmd; exec bash" &
      ;;
    *)
      echo "Unsupported terminal: $TERMINAL_BIN"
      exit 1
      ;;
  esac
}

run_term "Kafka" "cd \"$BACKEND_DIR\" && sudo ./run_kafka.sh"
sleep 7.5
run_term "Ingest" "cd \"$BACKEND_DIR\" && eval \"\$(micromamba shell hook -s bash)\" && micromamba activate bot && ./run_ingest.sh"
sleep 2.5
run_term "API" "cd \"$BACKEND_DIR\" && eval \"\$(micromamba shell hook -s bash)\" && micromamba activate bot && ./run_api.sh"
sleep 2.5
run_term "Dash" "cd \"$DASHBOARD_DIR\" && eval \"\$(micromamba shell hook -s bash)\" && micromamba activate bot && ./run_dash.sh"

echo "Started Kafka, ingest, API, and Dash in separate terminals."
