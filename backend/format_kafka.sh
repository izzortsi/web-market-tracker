#!/usr/bin/env bash
set -euo pipefail

KAFKA_STORAGE_BIN="${KAFKA_HOME:-}/bin/kafka-storage.sh"

if [[ -z "${KAFKA_HOME:-}" ]]; then
  if command -v kafka-storage.sh >/dev/null 2>&1; then
    KAFKA_STORAGE_BIN="$(command -v kafka-storage.sh)"
    KAFKA_HOME="$(dirname "$KAFKA_STORAGE_BIN")/.."
  fi
fi

if [[ -z "${KAFKA_STORAGE_BIN:-}" || ! -x "$KAFKA_STORAGE_BIN" ]]; then
  echo "kafka-storage.sh not found. Set KAFKA_HOME or ensure kafka-storage.sh is in PATH."
  exit 1
fi

KRAFT_CONFIG="/etc/kafka/kraft/server.properties"
CLASSIC_CONFIG="/etc/kafka/server.properties"
FALLBACK_KRAFT="$KAFKA_HOME/config/kraft/server.properties"
FALLBACK_CLASSIC="$KAFKA_HOME/config/server.properties"

if [[ -n "${KAFKA_CONFIG:-}" ]]; then
  CONFIG_PATH="$KAFKA_CONFIG"
elif [[ -f "$KRAFT_CONFIG" ]]; then
  CONFIG_PATH="$KRAFT_CONFIG"
elif [[ -f "$CLASSIC_CONFIG" ]]; then
  CONFIG_PATH="$CLASSIC_CONFIG"
elif [[ -f "$FALLBACK_KRAFT" ]]; then
  CONFIG_PATH="$FALLBACK_KRAFT"
elif [[ -f "$FALLBACK_CLASSIC" ]]; then
  CONFIG_PATH="$FALLBACK_CLASSIC"
else
  echo "No Kafka config found. Set KAFKA_CONFIG or ensure a server.properties exists under /etc/kafka or \$KAFKA_HOME/config."
  exit 1
fi

CLUSTER_ID="${KAFKA_CLUSTER_ID:-}"

if [[ -z "$CLUSTER_ID" ]]; then
  CLUSTER_ID="$("$KAFKA_STORAGE_BIN" random-uuid)"
fi

MODE_FLAG=""
if grep -q "process.roles" "$CONFIG_PATH"; then
  if ! grep -q "controller.quorum.voters" "$CONFIG_PATH"; then
    MODE_FLAG="--standalone"
  fi
fi

echo "Formatting Kafka storage..."
echo "Config: $CONFIG_PATH"
echo "Cluster ID: $CLUSTER_ID"
exec "$KAFKA_STORAGE_BIN" format $MODE_FLAG -t "$CLUSTER_ID" -c "$CONFIG_PATH"
