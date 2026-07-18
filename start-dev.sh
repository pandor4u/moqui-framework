#!/bin/bash
# start-dev.sh — Start Moqui in development mode
#
# This script:
# 1. Starts Moqui from the WAR with Java 17 module access flags
# 2. Waits for Moqui to become ready
#
# Usage: ./start-dev.sh [port]
#   port defaults to 8080

set -e
cd "$(dirname "$0")"

PORT="${1:-8080}"

# Kill existing Moqui on target port
if lsof -ti :"$PORT" >/dev/null 2>&1; then
    echo "Killing existing process on port $PORT..."
    lsof -ti :"$PORT" | xargs kill -9 2>/dev/null || true
    sleep 2
fi

# Start Moqui
echo "Starting Moqui on port $PORT..."
nohup java \
  --add-opens java.base/java.lang=ALL-UNNAMED \
  --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
  --add-opens java.base/java.io=ALL-UNNAMED \
  --add-opens java.base/java.net=ALL-UNNAMED \
  --add-opens java.base/sun.nio.ch=ALL-UNNAMED \
  --add-opens java.base/java.util=ALL-UNNAMED \
  -jar moqui-plus-runtime.war conf=conf/MoquiDevConf.xml port="$PORT" \
  > /tmp/moqui_console.log 2>&1 &

MOQUI_PID=$!
echo "Moqui PID: $MOQUI_PID"

# Wait for Moqui to start (check HTTP readiness)
echo "Waiting for Moqui to start..."
for i in $(seq 1 60); do
    if curl -s -o /dev/null http://localhost:"$PORT"/status 2>/dev/null; then
        echo "Moqui is ready on port $PORT"
        echo ""
        echo "Quasar UI:  http://localhost:$PORT/qapps/marble"
        echo "Logs:       /tmp/moqui_console.log"
        exit 0
    fi
    sleep 1
done

echo "WARNING: Moqui did not become ready within 60 seconds"
echo "Check /tmp/moqui_console.log for errors"
exit 1
