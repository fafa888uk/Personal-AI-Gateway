"""Stage G integration tests — full chains end to end, mock upstream only.

Every test here drives the public surface the way real clients do
(admin session -> model verify -> client key -> /v1/* calls -> usage /
chats / admin diagnostics), instead of asserting one layer in
isolation. No real OpenAI key is used anywhere; the mock upstream
stands in for api.openai.com and every result labelled mock is mock,
never real verification.

Known mock costs (pricing $1.0 in / $2.0 out per 1M):
- POST /v1/responses (non-streaming): 10 in / 5 out -> $0.00002 exact.
- POST /v1/chat/completions: 12 in / 7 out -> $0.000026 exact.
"""
from __future__ import annotations

import json

from conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    MODEL,
    _make_key,
    add_pricing,
    add_usage,
    auth_headers,
)
from gateway.models import (
    ApiRequestLog,
    ChatMessage,
    SystemSetting,
    UsageRecord,
)

RESP_BODY = {"model": MODEL, "input": "hello mock", "max_output_tokens": 16}
CHAT_BODY = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
RESP_COST = 0.00002
CHAT_COST = 0.000026


def _login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    return client.post("/api/v1/admin/login",
                       json={"username": username, "password": password})


def _authed(client):
    """Log in and return the CSRF header for mutating requests."""
    r = _login(client)
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/admin/csrf")
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _verify_mock_via_admin(client, headers, model=MODEL):
    r = client.post(f"/api/v1/admin/models/{model}/verify",
                    json={"mode": "mock"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"]["verification_status"] == "available"
    assert body["model"]["verification_method"] == "mock-test-only"
    return body


def _create_key_via_admin(client, headers, name, client_type="web"):
    r = client.post("/api/v1/admin/client-keys", json={
        "name": name, "client_type": client_type, "allowed_models": ["*"],
    }, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    raw = body["raw_key"]
    assert raw.startswith("pag_sk_")
    # The raw key is returned exactly once: the list view never shows it.
    r = client.get("/api/v1/admin/client-keys")
    assert r.status_code == 200
    listed = [k for k in r.json()["client_keys"] if k["id"] == body["id"]]
    assert len(listed) == 1
    assert "raw_key" not in listed[0] and "key" not in listed[0]
    assert listed[0]["key_prefix"] == raw[:12]
    return body["id"], raw


def _set_pricing_via_admin(client, headers, inp=1.0, out=2.0):
    r = client.put("/api/v1/admin/settings", json={
        "pricing_rules": [{"model": MODEL, "input_usd_per_1m": inp,
                           "output_usd_per_1m": out}],
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["pricing_rules"][0]["model"] == MODEL
    return r.json()


def _sse_data_lines(response):
    """Return (json_events, saw_done) from a streamed SSE response."""
    events = []
    saw_done = False
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            saw_done = True
        else:
            events.append(json.loads(data))
    return events, saw_done


# ------------------------------------------------------------------ task 1.1
def test_e2e_login_verify_key_call_usage_chats(client, app):
    """Full chain: admin login -> mock verify -> create key -> call both
    /v1 endpoints (one streaming) -> usage lands in the DB and both the
    client usage summary and the admin usage view agree -> chats persist.
    """
    headers = _authed(client)
    _verify_mock_via_admin(client, headers)
    _key_id, raw = _create_key_via_admin(client, headers, "e2e-web")
    _set_pricing_via_admin(client, headers)

    # Non-streaming Responses call.
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    assert r.json()["output"][0]["content"][0]["text"] == "Hello from mock upstream."
    assert r.json()["usage"]["input_tokens"] == 10
    assert r.json()["usage"]["output_tokens"] == 5
    assert r.headers.get("x-gateway-trace-id")

    # Streaming Chat Completions call: event order, [DONE], usage block.
    with client.stream("POST", "/v1/chat/completions",
                       json={**CHAT_BODY, "stream": True},
                       headers=auth_headers(raw)) as r:
        assert r.status_code == 200, r.text
        assert "text/event-stream" in r.headers["content-type"]
        events, saw_done = _sse_data_lines(r)
    assert saw_done, "streaming chat response must end with data: [DONE]"
    assert len(events) == 2
    assert events[0]["choices"][0]["delta"]["content"] == "Hello "
    assert events[0]["choices"][0]["finish_reason"] is None
    assert events[1]["choices"][0]["finish_reason"] == "stop"
    assert events[1]["usage"] == {"prompt_tokens": 12, "completion_tokens": 7,
                                  "total_tokens": 19}
    text = "".join(e["choices"][0]["delta"].get("content") or ""
                   for e in events)
    assert text == "Hello "

    # Usage records landed in the DB: one per call, exact costs.
    with app.state.session_factory() as s:
        rows = (s.query(UsageRecord)
                .filter(UsageRecord.client_key_id == _key_id)
                .order_by(UsageRecord.id).all())
    assert len(rows) == 2
    assert [(r.tokens_in, r.tokens_out) for r in rows] == [(10, 5), (12, 7)]
    assert [r.cost_status for r in rows] == ["exact", "exact"]
    assert abs(rows[0].cost_usd - RESP_COST) < 1e-9
    assert abs(rows[1].cost_usd - CHAT_COST) < 1e-9
    with app.state.session_factory() as s:
        logs = (s.query(ApiRequestLog)
                .filter(ApiRequestLog.client_key_id == _key_id).all())
    assert len(logs) == 2
    assert all(log.status_code == 200 for log in logs)

    # Client usage summary and admin usage see the SAME numbers.
    r = client.get("/api/v1/usage/summary?period=today", headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["requests"] == 2
    assert summary["tokens_in"] == 22 and summary["tokens_out"] == 12
    assert abs(summary["cost_usd"] - (RESP_COST + CHAT_COST)) < 1e-9
    assert summary["cost_status"] == "ok"
    assert summary["by_model"][0]["model"] == MODEL
    assert summary["by_model"][0]["requests"] == 2

    r = client.get("/api/v1/admin/usage?period=today")
    assert r.status_code == 200, r.text
    admin_usage = r.json()
    assert admin_usage["requests"] == 2
    assert admin_usage["success_count"] == 2 and admin_usage["error_count"] == 0
    assert admin_usage["tokens"] == {"in": 22, "out": 12, "total": 34,
                                     "cached": 2, "reasoning": 1}
    assert abs(admin_usage["cost_usd"] - (RESP_COST + CHAT_COST)) < 1e-9
    assert admin_usage["per_model"][0]["model"] == MODEL
    assert admin_usage["per_model"][0]["requests"] == 2

    # Chat history: create a session, add messages, read them back.
    r = client.post("/api/v1/chats", json={"title": "e2e thread", "model": MODEL},
                    headers=auth_headers(raw))
    assert r.status_code == 201, r.text
    session_id = r.json()["id"]
    r = client.post(f"/api/v1/chats/{session_id}/messages",
                    json={"role": "user", "content": "hello gateway", "model": MODEL},
                    headers=auth_headers(raw))
    assert r.status_code == 201, r.text
    r = client.post(f"/api/v1/chats/{session_id}/messages",
                    json={"role": "assistant", "content": "hello back",
                          "model": MODEL, "tokens_in": 12, "tokens_out": 7},
                    headers=auth_headers(raw))
    assert r.status_code == 201, r.text
    r = client.get(f"/api/v1/chats/{session_id}/messages", headers=auth_headers(raw))
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "hello gateway"
    with app.state.session_factory() as s:
        stored = (s.query(ChatMessage)
                  .filter(ChatMessage.session_id == session_id)
                  .order_by(ChatMessage.id).all())
    assert [m.content for m in stored] == ["hello gateway", "hello back"]


# ------------------------------------------------------------------ task 1.2
def test_budget_enforced_end_to_end_then_recovered(client, app):
    """Tiny persisted daily budget via the admin API: real priced calls
    pass while spend is under it, the next call hard-stops with 429
    budget_exceeded (and records no new usage), raising the budget
    restores calls."""
    headers = _authed(client)
    _verify_mock_via_admin(client, headers)
    key_id, raw = _create_key_via_admin(client, headers, "budget-e2e")
    r = client.put("/api/v1/admin/settings", json={
        "budgets": {"global_daily_usd": 0.00003, "global_monthly_usd": 50.0},
        "pricing_rules": [{"model": MODEL, "input_usd_per_1m": 1.0,
                           "output_usd_per_1m": 2.0}],
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["budgets"]["global_daily_usd"] == 0.00003

    # Call 1: spend $0 -> $0.00002 (under the $0.00003 cap). Passes.
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    # Call 2: spend $0.00002 -> $0.00004. Still admitted (checked pre-call).
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    # Call 3: spend $0.00004 >= cap -> hard stop, nothing new recorded.
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "budget_exceeded"
    assert "global daily budget exceeded" in r.json()["error"]["message"]
    with app.state.session_factory() as s:
        assert (s.query(UsageRecord)
                .filter(UsageRecord.client_key_id == key_id).count()) == 2

    # Raise the budget via the admin API -> the same call works again.
    r = client.put("/api/v1/admin/settings",
                   json={"budgets": {"global_daily_usd": 10.0}}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["budgets"]["global_daily_usd"] == 10.0
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    with app.state.session_factory() as s:
        assert (s.query(UsageRecord)
                .filter(UsageRecord.client_key_id == key_id).count()) == 3


def test_env_budget_default_applies_with_no_persisted_setting(client, verified_client, app):
    """Chain level: with no persisted budget setting at all, the env
    defaults (daily $5 / monthly $50 from the fixture) enforce."""
    raw, key_id = verified_client
    add_pricing(app, MODEL, 1.0, 2.0)
    add_usage(app, key_id, MODEL, cost=3.0)  # $3 spent; under env daily $5.
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    add_usage(app, key_id, MODEL, cost=3.0)  # now $6 >= env daily $5.
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "budget_exceeded"
    assert "$5.00" in r.json()["error"]["message"]


def test_invalid_persisted_budget_falls_back_to_env_end_to_end(client, verified_client, app):
    """Chain level: a persisted budget row that is not a number (daily)
    or negative (monthly) is ignored and the env default enforces —
    on /v1/* calls AND on the admin settings/usage pages (which used
    to 500 on such a row; see the _effective_budgets fix in main.py).

    The admin PUT API validates and rejects bad values, so the bad
    rows can only arrive via a direct write to system_settings — that
    is what this test does, exactly as a corrupt/legacy row would.
    """
    raw, key_id = verified_client
    add_pricing(app, MODEL, 1.0, 2.0)
    with app.state.session_factory() as s:
        s.add(SystemSetting(key="budget_global_daily_usd", value="not-a-number"))
        s.add(SystemSetting(key="budget_global_monthly_usd", value=-5))
        s.commit()

    # Admin pages must not crash: they report the env defaults.
    _login(client)
    r = client.get("/api/v1/admin/settings")
    assert r.status_code == 200, r.text
    assert r.json()["budgets"] == {"global_daily_usd": 5.0,
                                   "global_monthly_usd": 50.0}
    r = client.get("/api/v1/admin/usage?period=today")
    assert r.status_code == 200, r.text
    assert r.json()["budget"]["global_daily_usd"] == 5.0

    # And /v1/* enforcement falls back to the env daily $5.
    add_usage(app, key_id, MODEL, cost=3.0)
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    add_usage(app, key_id, MODEL, cost=3.0)  # $6 >= env daily $5.
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "budget_exceeded"
    assert "$5.00" in r.json()["error"]["message"]


# ------------------------------------------------------------------ task 1.3
def test_admin_full_flow_in_one_test(client, app):
    """One admin session, start to finish: login -> mock verify ->
    create key -> call succeeds -> revoke key -> same key is refused
    -> usage + per-trace diagnosis -> change a setting -> the audit
    log shows every one of those management actions."""
    headers = _authed(client)
    _verify_mock_via_admin(client, headers)
    key_id, raw = _create_key_via_admin(client, headers, "admin-flow", "web")
    _set_pricing_via_admin(client, headers)

    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    trace_id = r.headers["x-gateway-trace-id"]

    # Revoke: the same key is refused afterwards. The gateway answers
    # 403 client_disabled for a revoked (disabled) key — NOT 401: the
    # key is recognised but disabled. (The Stage E test
    # test_client_key_patch_revoke_regenerate pins the same 403.)
    r = client.post(f"/api/v1/admin/client-keys/{key_id}/revoke", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "client_disabled"

    # Usage shows the one successful call; the refused call logged nothing.
    r = client.get("/api/v1/admin/usage?period=today")
    assert r.status_code == 200, r.text
    assert r.json()["requests"] == 1
    assert r.json()["success_count"] == 1
    assert r.json()["tokens"]["in"] == 10 and r.json()["tokens"]["out"] == 5
    assert abs(r.json()["cost_usd"] - RESP_COST) < 1e-9

    # Per-trace diagnosis for that call.
    r = client.get(f"/api/v1/admin/requests/{trace_id}")
    assert r.status_code == 200, r.text
    diag = r.json()
    assert diag["status_code"] == 200
    assert diag["endpoint"] == "POST /v1/responses"
    assert diag["client"] == "admin-flow"
    assert diag["usage"]["tokens_in"] == 10
    assert diag["usage"]["tokens_out"] == 5
    assert abs(diag["usage"]["cost_usd"] - RESP_COST) < 1e-9
    assert diag["usage"]["cost_status"] == "exact"
    assert client.get("/api/v1/admin/requests/no-such-trace").status_code == 404

    # Change a setting, then check the audit trail covers the whole flow.
    r = client.put("/api/v1/admin/settings", json={"retention_days": 30},
                   headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["retention_days"] == 30
    r = client.get("/api/v1/admin/audit?limit=100")
    assert r.status_code == 200
    kinds = [e["kind"] for e in r.json()["audit"]]
    for expected in ("admin_login", "model_verified", "client_key_created",
                     "client_key_revoked", "settings_updated"):
        assert expected in kinds, kinds


# ------------------------------------------------------------------ task 1.4
def test_cross_client_consistency_web_and_flutter(client, client_key, app):
    """Same client key, two simulated ends (web, then Flutter): both
    run the same /api/v1/chats + /messages + usage calls and must see
    byte-identical history and usage. Server-side hard delete removes
    the session for both ends; another key sees 404, never the data."""
    raw, _ = client_key
    other_raw, _ = _make_key(app, "other-client", ["*"])

    # "Web end": create the session and post two messages.
    r = client.post("/api/v1/chats", json={"title": "shared thread", "model": MODEL},
                    headers=auth_headers(raw))
    assert r.status_code == 201, r.text
    session_id = r.json()["id"]
    for role, content in (("user", "web: hello"), ("assistant", "web: hello back")):
        r = client.post(f"/api/v1/chats/{session_id}/messages",
                        json={"role": role, "content": content, "model": MODEL},
                        headers=auth_headers(raw))
        assert r.status_code == 201, r.text

    def _web_view():
        sessions = client.get("/api/v1/chats", headers=auth_headers(raw)).json()
        one = client.get(f"/api/v1/chats/{session_id}", headers=auth_headers(raw)).json()
        msgs = client.get(f"/api/v1/chats/{session_id}/messages",
                          headers=auth_headers(raw)).json()
        usage = client.get("/api/v1/usage/summary?period=today",
                           headers=auth_headers(raw)).json()
        return sessions, one, msgs, usage

    web = _web_view()
    flutter = _web_view()  # "Flutter end": same key, same endpoints.
    assert flutter == web
    assert [m["content"] for m in web[2]["messages"]] == ["web: hello", "web: hello back"]
    assert web[1]["title"] == "shared thread"

    # Server-side hard delete: gone for both ends, messages included.
    r = client.delete(f"/api/v1/chats/{session_id}", headers=auth_headers(raw))
    assert r.status_code == 200 and r.json()["deleted"] is True
    for _ in range(2):  # both ends re-check
        assert client.get(f"/api/v1/chats/{session_id}",
                          headers=auth_headers(raw)).status_code == 404
        assert client.get(f"/api/v1/chats/{session_id}/messages",
                          headers=auth_headers(raw)).status_code == 404
    assert client.get("/api/v1/chats", headers=auth_headers(raw)).json()["sessions"] == []

    # Another key never sees the session — even before deletion it was 404.
    r = client.post("/api/v1/chats", json={"title": "mine", "model": MODEL},
                    headers=auth_headers(raw))
    other_session = r.json()["id"]
    assert client.get(f"/api/v1/chats/{other_session}",
                      headers=auth_headers(other_raw)).status_code == 404
    assert client.post(f"/api/v1/chats/{other_session}/messages",
                       json={"role": "user", "content": "intruder"},
                       headers=auth_headers(other_raw)).status_code == 404
    assert client.get("/api/v1/chats",
                      headers=auth_headers(other_raw)).json()["sessions"] == []
    client.delete(f"/api/v1/chats/{other_session}", headers=auth_headers(raw))


# ------------------------------------------------------------------ task 1.5
def test_chat_streaming_order_and_content(client, verified_client, app):
    """Chat streaming: chunks arrive in order, deltas concatenate to
    the full text, the final chunk carries the usage block, and the
    stream ends with data: [DONE]."""
    raw, key_id = verified_client
    with client.stream("POST", "/v1/chat/completions",
                       json={**CHAT_BODY, "stream": True},
                       headers=auth_headers(raw)) as r:
        assert r.status_code == 200, r.text
        events, saw_done = _sse_data_lines(r)
    assert saw_done
    assert [e["choices"][0]["finish_reason"] for e in events] == [None, "stop"]
    assert events[0]["choices"][0]["delta"] == {"content": "Hello "}
    assert events[1]["choices"][0]["delta"] == {}
    assert events[1]["usage"] == {"prompt_tokens": 12, "completion_tokens": 7,
                                  "total_tokens": 19}
    assert "".join(e["choices"][0]["delta"].get("content") or ""
                   for e in events) == "Hello "
    with app.state.session_factory() as s:
        usage = (s.query(UsageRecord)
                 .filter(UsageRecord.client_key_id == key_id).one())
    assert (usage.tokens_in, usage.tokens_out) == (12, 7)


def test_responses_streaming_order_and_content(client, verified_client, app):
    """Responses streaming: created -> delta -> delta -> completed, in
    order; deltas concatenate to the full text; the completed event
    carries usage, which is what lands in the usage record."""
    raw, key_id = verified_client
    with client.stream("POST", "/v1/responses",
                       json={**RESP_BODY, "stream": True},
                       headers=auth_headers(raw)) as r:
        assert r.status_code == 200, r.text
        events, saw_done = _sse_data_lines(r)
    assert not saw_done  # Responses streams end with completed, not [DONE].
    assert [e["type"] for e in events] == [
        "response.created", "response.output_text.delta",
        "response.output_text.delta", "response.completed"]
    assert "".join(e.get("delta", "") for e in events) == "Hello from mock."
    assert events[-1]["response"]["usage"]["input_tokens"] == 10
    assert events[-1]["response"]["usage"]["output_tokens"] == 5
    with app.state.session_factory() as s:
        usage = (s.query(UsageRecord)
                 .filter(UsageRecord.client_key_id == key_id).one())
    assert (usage.tokens_in, usage.tokens_out) == (10, 5)


def test_response_cancel_passthrough(client, verified_client):
    """Cancel: POST /v1/responses/{id}/cancel reaches the mock upstream
    and the cancelled status comes back unchanged."""
    raw, _ = verified_client
    r = client.post("/v1/responses/resp_mock_123/cancel", headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "resp_mock_123"
    assert r.json()["status"] == "cancelled"
