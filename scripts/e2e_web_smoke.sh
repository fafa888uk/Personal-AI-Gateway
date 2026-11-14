#!/usr/bin/env bash
# End-to-end web smoke test for Personal AI Gateway (Stage G).
#
# Starts the REAL FastAPI gateway with the MOCK upstream
# (apps/api/gateway/dev_mock_server.py, MOCK ONLY — never production,
# no real OpenAI key) on 127.0.0.1:$PAG_MOCK_PORT, builds the Next.js
# web app and serves it in production mode on 127.0.0.1:$PAG_WEB_PORT,
# then walks the web client's real call order against the gateway:
#
#   create chat -> post user message -> stream chat completion (SSE)
#   -> post assistant message (web client does this after streaming)
#   -> list messages (verify persistence + tokens)
#   -> usage summary (verify the request was counted)
#
# Also checks the production web server serves / , /chat,
# /manifest.webmanifest (valid JSON) and /sw.js with HTTP 200.
#
# Usage from the repo root:
#
#   scripts/e2e_web_smoke.sh
#
# Environment overrides: PAG_MOCK_PORT (default 8000),
# PAG_WEB_PORT (default 3001). All temp files live under /tmp and are
# removed on exit; both servers are killed on exit (success or
# failure). Exits 0 only if every step passes; on failure it prints
# which step failed and exits non-zero.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOCK_PORT="${PAG_MOCK_PORT:-8000}"
WEB_PORT="${PAG_WEB_PORT:-3001}"
GATEWAY_URL="http://127.0.0.1:${MOCK_PORT}"
WEB_URL="http://127.0.0.1:${WEB_PORT}"
MODEL="gpt-5.4-mini"

TMPDIR="$(mktemp -d /tmp/pag_e2e_XXXXXX)"
KEY_FILE="$TMPDIR/mock_key.json"
SSE_FILE="$TMPDIR/sse.txt"
GATEWAY_LOG="$TMPDIR/gateway.log"
WEB_LOG="$TMPDIR/web.log"
GATEWAY_PID=""
WEB_PID=""

step() { echo "== $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

cleanup() {
  # Kill whole process groups: `next start` spawns a `next-server`
  # child that survives killing the npm wrapper alone (found 2026-11-14:
  # a stray next-server kept listening on the web port after exit).
  # Both servers are started under setsid, so their PID is their PGID.
  if [ -n "$WEB_PID" ]; then
    kill -- "-$WEB_PID" 2>/dev/null || true
    wait "$WEB_PID" 2>/dev/null || true
  fi
  if [ -n "$GATEWAY_PID" ]; then
    kill -- "-$GATEWAY_PID" 2>/dev/null || true
    wait "$GATEWAY_PID" 2>/dev/null || true
  fi
  rm -rf "$TMPDIR"
}
trap cleanup EXIT INT TERM

# --- preflight: ports must be free, or a stale server would fake a pass.
# TCP-level check (not an HTTP probe: the gateway answers 404 on /,
# so an HTTP probe would miss a live gateway on the same port).
for port in "$MOCK_PORT" "$WEB_PORT"; do
  if python3 -c "import socket,sys; sys.exit(0 if socket.socket().connect_ex(('127.0.0.1', $port)) == 0 else 1)" 2>/dev/null; then
    fail "preflight: something already listens on 127.0.0.1:${port}; stop it first (or set PAG_MOCK_PORT / PAG_WEB_PORT)"
  fi
done

# --- 1. start the mock-backed gateway and wait for /api/health.
step "1/9 start mock gateway on ${GATEWAY_URL}"
setsid "$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/apps/api/gateway/dev_mock_server.py" \
  --port "$MOCK_PORT" --key-file "$KEY_FILE" >"$GATEWAY_LOG" 2>&1 &
GATEWAY_PID=$!
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "${GATEWAY_URL}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
curl -fsS --max-time 5 "${GATEWAY_URL}/api/health" >/dev/null \
  || fail "step 1: mock gateway did not become healthy (log: $GATEWAY_LOG)"
CLIENT_KEY="$(python3 -c "import json; print(json.load(open('$KEY_FILE'))['client_key'])")"
[ -n "$CLIENT_KEY" ] || fail "step 1: no client key in $KEY_FILE"
echo "gateway healthy; mock client key issued (kept in $TMPDIR, deleted on exit)"

# --- 2. build the web app (production).
step "2/9 build web app (npm run build)"
(cd "$REPO_ROOT/apps/web" && npm run build) \
  || fail "step 2: npm run build failed"

# --- 3. serve the web app in production mode and wait for /.
step "3/9 start web app in production mode on ${WEB_URL}"
# Run the `next` binary directly (not via the npm wrapper) under its own
# process group, so cleanup kills the `next-server` child too.
# `next start` resolves the app from the working directory, so cd first.
setsid bash -c 'cd "$0" && exec "$1" start -p "$2" --hostname 127.0.0.1' \
  "$REPO_ROOT/apps/web" "$REPO_ROOT/apps/web/node_modules/.bin/next" "$WEB_PORT" \
  >"$WEB_LOG" 2>&1 &
WEB_PID=$!
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "${WEB_URL}/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
curl -fsS --max-time 5 "${WEB_URL}/" >/dev/null \
  || fail "step 3: web app did not become healthy (log: $WEB_LOG)"

# --- 4. static production pages / PWA assets.
step "4/9 check production pages and PWA assets"
check_200() { # $1 = url, $2 = label
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$1")"
  [ "$code" = "200" ] || fail "step 4: $2 returned HTTP $code (want 200): $1"
  echo "  $2 -> 200"
}
check_200 "${WEB_URL}/" "/"
check_200 "${WEB_URL}/chat" "/chat"
check_200 "${WEB_URL}/manifest.webmanifest" "/manifest.webmanifest"
curl -fsS --max-time 10 "${WEB_URL}/manifest.webmanifest" \
  | python3 -c "import json,sys; json.load(sys.stdin)" \
  || fail "step 4: /manifest.webmanifest is not valid JSON"
echo "  /manifest.webmanifest is valid JSON"
check_200 "${WEB_URL}/sw.js" "/sw.js"

# --- 5. create a chat session (web client: POST /api/v1/chats).
step "5/9 create chat session (POST /api/v1/chats)"
SESSION_ID="$(curl -fsS --max-time 10 "${GATEWAY_URL}/api/v1/chats" \
  -H "Authorization: Bearer ${CLIENT_KEY}" \
  -H 'Content-Type: application/json' \
  -d "{\"title\": \"e2e smoke\", \"model\": \"${MODEL}\"}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")"
[ -n "$SESSION_ID" ] || fail "step 5: no session id returned"
echo "  session id: $SESSION_ID"

# --- 6. post the user message (web client: POST .../messages).
step "6/9 post user message (POST /api/v1/chats/${SESSION_ID}/messages)"
curl -fsS --max-time 10 "${GATEWAY_URL}/api/v1/chats/${SESSION_ID}/messages" \
  -H "Authorization: Bearer ${CLIENT_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"role": "user", "content": "你好"}' >/dev/null \
  || fail "step 6: posting the user message failed"

# --- 7. stream a chat completion (web client: POST /v1/chat/completions,
# stream:true) and verify SSE deltas, a usage block and [DONE].
step "7/9 stream chat completion (POST /v1/chat/completions stream:true)"
curl -fsS -N --max-time 30 "${GATEWAY_URL}/v1/chat/completions" \
  -H "Authorization: Bearer ${CLIENT_KEY}" \
  -H 'Content-Type: application/json' \
  -d "{\"model\": \"${MODEL}\", \"messages\": [{\"role\": \"user\", \"content\": \"你好\"}], \"stream\": true}" \
  -o "$SSE_FILE" \
  || fail "step 7: streaming chat completion failed (HTTP error)"
grep -q '"content": "Hello "' "$SSE_FILE" \
  || fail "step 7: SSE stream has no 'Hello ' delta (see $SSE_FILE)"
grep -q '"prompt_tokens": 12' "$SSE_FILE" \
  || fail "step 7: SSE stream has no usage block with prompt_tokens 12"
grep -q '^data: \[DONE\]$' "$SSE_FILE" \
  || fail "step 7: SSE stream has no [DONE] terminator"
ASSISTANT_TEXT="$(python3 - "$SSE_FILE" <<'PY'
import json, sys
text = ""
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line.startswith("data: ") and not line.endswith("[DONE]"):
        chunk = json.loads(line[6:])
        for choice in chunk.get("choices", []):
            text += choice.get("delta", {}).get("content", "")
print(text)
PY
)"
[ "$ASSISTANT_TEXT" = "Hello " ] \
  || fail "step 7: assembled SSE text is '$ASSISTANT_TEXT' (want 'Hello ')"
echo "  SSE: delta 'Hello ' arrived, usage prompt 12 / completion 7, [DONE] seen"

# --- 8. post the assistant message with tokens, then verify both
# messages persisted server-side (web client: addMessage, listMessages).
step "8/9 save assistant reply and verify persistence (GET .../messages)"
curl -fsS --max-time 10 "${GATEWAY_URL}/api/v1/chats/${SESSION_ID}/messages" \
  -H "Authorization: Bearer ${CLIENT_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"role": "assistant", "content": "Hello ", "model": "gpt-5.4-mini", "tokens_in": 12, "tokens_out": 7}' >/dev/null \
  || fail "step 8: posting the assistant message failed"
python3 - "$GATEWAY_URL" "$SESSION_ID" "$CLIENT_KEY" <<'PY' || fail "step 8: persisted messages do not match (want user '你好' + assistant 'Hello ' with tokens 12/7)"
import json, sys, urllib.request
base, sid, key = sys.argv[1], sys.argv[2], sys.argv[3]
req = urllib.request.Request(
    f"{base}/api/v1/chats/{sid}/messages",
    headers={"Authorization": f"Bearer {key}"})
msgs = json.load(urllib.request.urlopen(req, timeout=10))["messages"]
assert len(msgs) == 2, f"want 2 messages, got {len(msgs)}: {msgs}"
assert msgs[0]["role"] == "user" and msgs[0]["content"] == "你好", msgs[0]
assert msgs[1]["role"] == "assistant" and msgs[1]["content"] == "Hello ", msgs[1]
assert msgs[1].get("tokens_in") == 12 and msgs[1].get("tokens_out") == 7, msgs[1]
print(f"  persisted: 2 messages, assistant tokens_in=12 tokens_out=7")
PY

# --- 9. usage summary must count the streamed request.
step "9/9 usage summary counts the request (GET /api/v1/usage/summary)"
python3 - "$GATEWAY_URL" "$CLIENT_KEY" <<'PY' || fail "step 9: usage summary does not show the streamed request"
import json, sys, urllib.request
base, key = sys.argv[1], sys.argv[2]
for period in ("today", "month"):
    req = urllib.request.Request(
        f"{base}/api/v1/usage/summary?period={period}",
        headers={"Authorization": f"Bearer {key}"})
    body = json.load(urllib.request.urlopen(req, timeout=10))
    reqs = body.get("requests", body.get("total_requests", 0))
    assert reqs >= 1, f"period={period}: requests={reqs} (want >= 1): {body}"
    print(f"  usage {period}: requests={reqs}, cost_status={body.get('cost_status')}")
PY

echo
echo "E2E WEB SMOKE: ALL 9 STEPS PASSED (mock upstream only, no real OpenAI key)"
