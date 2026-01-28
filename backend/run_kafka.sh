#!/usr/bin/env bash
set -euo pipefail

KAFKA_START_BIN="${KAFKA_HOME:-}/bin/kafka-server-start.sh"

if [[ -z "${KAFKA_HOME:-}" ]]; then
  if command -v kafka-server-start.sh >/dev/null 2>&1; then
    KAFKA_START_BIN="$(command -v kafka-server-start.sh)"
    KAFKA_HOME="$(dirname "$KAFKA_START_BIN")/.."
  fi
fi

if [[ -z "${KAFKA_START_BIN:-}" || ! -x "$KAFKA_START_BIN" ]]; then
  echo "Kafka start script not found. Set KAFKA_HOME or ensure kafka-server-start.sh is in PATH."
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

export KAFKA_LOG_DIR="${KAFKA_LOG_DIR:-/tmp/kafka-logs-${USER}}"
export LOG_DIR="${LOG_DIR:-$KAFKA_LOG_DIR}"
mkdir -p "$KAFKA_LOG_DIR"

export KAFKA_JVM_PERFORMANCE_OPTS="-Xlog:gc*:file=/tmp/kafka-gc-${USER}.log:time,tags:filecount=10,filesize=100M"

if [[ -z "${KAFKA_LOG4J_OPTS:-}" && -f "/etc/kafka/log4j.properties" ]]; then
  export KAFKA_LOG4J_OPTS="-Dlog4j.configuration=file:/etc/kafka/log4j.properties"
fi

echo "Starting Kafka using: $KAFKA_START_BIN"
echo "Config: $CONFIG_PATH"
echo "Log dir: $KAFKA_LOG_DIR"
exec "$KAFKA_START_BIN" "$CONFIG_PATH"
