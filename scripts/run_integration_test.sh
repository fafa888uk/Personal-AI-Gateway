#!/usr/bin/env bash
# Run the Flutter integration test against a real (mock-backed) gateway.
#
# Starts apps/api/gateway/dev_mock_server.py (MOCK ONLY — never for
# production, no real OpenAI key) on 127.0.0.1:8000, waits for
# /api/health, runs `flutter test integration_test`, then stops the
# server. Usage from the repo root:
#
#   scripts/run_integration_test.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/flutter/bin:$PATH"
export FLUTTER_SUPPRESS_ANALYTICS=true

KEY_FILE="$(mktemp /tmp/pag_mock_key_XXXXXX.json)"
PORT="${PAG_MOCK_PORT:-8000}"

cleanup() {
  if [ -n "${SERVER_PID:-}" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$KEY_FILE"
}
trap cleanup EXIT

"$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/apps/api/gateway/dev_mock_server.py" \
  --port "$PORT" --key-file "$KEY_FILE" &
SERVER_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$PORT/api/health" || {
  echo "mock gateway did not become healthy on port $PORT" >&2
  exit 1
}

cd "$REPO_ROOT/apps/flutter"
PAG_MOCK_KEY_FILE="$KEY_FILE" \
  flutter test integration_test --concurrency=1
