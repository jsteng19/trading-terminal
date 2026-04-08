#!/bin/bash
# Start the trading terminal.
#
# Usage:
#   ./start.sh           # Live mode, subaccount 1
#   ./start.sh --demo    # Demo mode
#   ./start.sh --dev     # Dev mode: frontend hot-reloads on code changes (port 5173)
#   ./start.sh --build   # Rebuild frontend only, don't start server

set -e
cd "$(dirname "$0")"

export PATH="/opt/homebrew/bin:/opt/homebrew/Cellar/node/25.2.1/bin:$PATH"

PORT=8766
MODE=""
DEV=false
BUILD_ONLY=false
SUBACCOUNT="${TERMINAL_SUBACCOUNT:-1}"

for arg in "$@"; do
  case "$arg" in
    --demo) MODE="--demo" ;;
    --dev)  DEV=true ;;
    --build) BUILD_ONLY=true ;;
    --sub=*) SUBACCOUNT="${arg#--sub=}" ;;
  esac
done

# Kill existing processes
lsof -ti:$PORT 2>/dev/null | xargs kill -9 2>/dev/null || true
if $DEV; then
  lsof -ti:5173 2>/dev/null | xargs kill -9 2>/dev/null || true
fi
sleep 0.5

# Rebuild frontend (unless --dev, which uses HMR)
if ! $DEV; then
  echo "Building frontend..."
  (cd frontend && npm run build 2>&1 | tail -3)
  echo ""
fi

if $BUILD_ONLY; then
  echo "Frontend built. Done."
  exit 0
fi

# Start backend
echo "Starting backend (port $PORT, sub=$SUBACCOUNT, ${MODE:-live})..."
TERMINAL_SUBACCOUNT=$SUBACCOUNT .venv/bin/python run.py --no-browser --port $PORT $MODE &
BACKEND_PID=$!
sleep 2

if $DEV; then
  # Start frontend dev server with HMR (proxies API to backend)
  echo "Starting frontend dev server (port 5173, HMR enabled)..."
  echo "Open http://localhost:5173"
  (cd frontend && npx vite dev --port 5173)
else
  echo "Open http://localhost:$PORT"
  echo "Backend PID: $BACKEND_PID (hot-reloads on backend/ changes)"
  echo "Run ./start.sh --build to rebuild frontend after changes."
  wait $BACKEND_PID
fi
