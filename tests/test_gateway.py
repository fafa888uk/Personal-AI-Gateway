"""Stage B gateway tests — all against the MOCK upstream.

Coverage required by the Stage B brief: normal request; unauthorized;
unknown model; model without permission; 429; timeout; upstream 5xx;
request cancel; SSE normal end + mid-stream abort; structured tool
calls; Responses streaming + non-streaming; budget hard-stop;
/v1/models hiding unverified models.
"""
from __future__ import annotations

import json
import time

from conftest import (
    ADMIN_KEY,
    MODEL,
    MODEL2,
    add_pricing,
    add_usage,
    auth_headers,
    set_rate_limit,
    verify_model,
)
from gateway.models import ApiRequestLog, UsageRecord

RESP_BODY = {"model": MODEL, "input": "hello mock", "max_output_tokens": 16}
CHAT_BODY = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["db"] == "ok"


def test_models_empty_before_verification(client, client_key):
    raw, _ = client_key
    r = client.get("/v1/models", headers=auth_headers(raw))
    assert r.status_code == 200
    assert r.json()["data"] == []  # correct: nothing verified yet


def test_verify_mock_marks_available_and_models_lists_it(client, client_key):
    raw, _ = client_key
    result = verify_model(client)
    assert result["model"]["verification_status"] == "available"
    assert result["model"]["verification_method"] == "mock-test-only"
    assert "NOT real verification" in (result.get("note") or "")
    r = client.get("/v1/models", headers=auth_headers(raw))
    assert [m["id"] for m in r.json()["data"]] == [MODEL]


def test_verify_mock_rejected_when_disabled(app, client):
    app.state.settings.allow_mock_verify = False
    r = client.post(f"/admin/models/{MODEL}/verify", json={"mode": "mock"},
                    headers={"Authorization": f"Bearer {ADMIN_KEY}"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "mock_not_allowed"


def test_admin_endpoints_require_admin_key(client, client_key):
    raw, _ = client_key
    assert client.get("/admin/models").status_code == 401
    assert client.get("/admin/models", headers=auth_headers(raw)).status_code == 401
    r = client.get("/admin/models", headers={"Authorization": f"Bearer {ADMIN_KEY}"})
    assert r.status_code == 200
    assert all(m["verification_status"] == "pending" for m in r.json()["models"])


def test_responses_nonstreaming_ok(client, verified_client, app):
    raw, key_id = verified_client
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["output"][0]["content"][0]["text"] == "Hello from mock upstream."
    assert payload["usage"]["input_tokens"] == 10
    assert payload["usage"]["output_tokens"] == 5
    assert r.headers.get("openai-request-id") == "req_mock_1"
    assert r.headers.get("x-gateway-trace-id")
    with app.state.session_factory() as s:
        log = s.query(ApiRequestLog).filter(ApiRequestLog.client_key_id == key_id).one()
        assert log.status_code == 200 and log.tokens_in == 10 and log.tokens_out == 5
        assert log.tokens_cached == 2 and log.tokens_reasoning == 1
        usage = s.query(UsageRecord).filter(UsageRecord.client_key_id == key_id).one()
        # No pricing configured -> cost is honestly "price_not_configured".
        assert usage.cost_usd is None and usage.cost_status == "price_not_configured"
        # No prompt content stored anywhere in the log row.
        assert "hello mock" not in json.dumps({c: getattr(log, c) for c in
            ["trace_id", "model", "endpoint", "error_type", "upstream_request_id"]})


def test_responses_streaming_ok(client, verified_client, app, mock):
    raw, key_id = verified_client
    mock.reset_stream_tracker()
    with client.stream("POST", "/v1/responses",
                       json={**RESP_BODY, "stream": True}, headers=auth_headers(raw)) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        events = [json.loads(line[5:]) for line in r.iter_lines() if line.startswith("data:")]
    types = [e["type"] for e in events]
    assert types == ["response.created", "response.output_text.delta",
                     "response.output_text.delta", "response.completed"]
    assert events[-1]["response"]["usage"]["input_tokens"] == 10
    assert mock.stream_tracker["completed"] is True
    with app.state.session_factory() as s:
        usage = s.query(UsageRecord).filter(UsageRecord.client_key_id == key_id).one()
        assert usage.tokens_in == 10 and usage.tokens_out == 5


def test_chat_completions_tool_call(client, verified_client, mock):
    raw, _ = verified_client
    mock.scenario["chat_tool_call"] = True
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    tool = choice["message"]["tool_calls"][0]
    assert tool["function"]["name"] == "get_weather"
    assert json.loads(tool["function"]["arguments"]) == {"location": "Shanghai"}
    assert r.json()["usage"]["prompt_tokens"] == 12


def test_chat_completions_streaming_ok(client, verified_client):
    raw, _ = verified_client
    with client.stream("POST", "/v1/chat/completions",
                       json={**CHAT_BODY, "stream": True}, headers=auth_headers(raw)) as r:
        assert r.status_code == 200
        lines = [line for line in r.iter_lines() if line]
    assert lines[-1] == "data: [DONE]"
    assert any("Hello " in line for line in lines)


def test_unauthorized(client, verified_client):
    raw, _ = verified_client
    assert client.post("/v1/responses", json=RESP_BODY).status_code == 401
    assert client.post("/v1/responses", json=RESP_BODY,
                       headers=auth_headers("pag_sk_bogus")).status_code == 401
    # Admin key must never double as a client key.
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(ADMIN_KEY))
    assert r.status_code == 401


def test_unknown_model(client, verified_client):
    raw, _ = verified_client
    r = client.post("/v1/responses", json={**RESP_BODY, "model": "gpt-nope"},
                    headers=auth_headers(raw))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model_not_found"


def test_unverified_model_call_rejected(client, verified_client):
    raw, _ = verified_client
    # gpt-5.4-nano is still pending in this fixture.
    r = client.post("/v1/responses", json={**RESP_BODY, "model": MODEL2},
                    headers=auth_headers(raw))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "model_not_verified"


def test_model_without_permission(client, restricted_key):
    raw, _ = restricted_key
    verify_model(client, MODEL)
    verify_model(client, MODEL2)
    r = client.post("/v1/responses", json={**RESP_BODY, "model": MODEL2},
                    headers=auth_headers(raw))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "model_not_allowed"


def test_alias_resolution(client, verified_client, app, mock):
    raw, _ = verified_client
    with app.state.session_factory() as s:
        from gateway.models import ModelRegistry
        row = s.query(ModelRegistry).filter(ModelRegistry.canonical_name == MODEL).first()
        row.aliases = ["gpt-mini-alias"]
        s.commit()
    r = client.post("/v1/responses", json={**RESP_BODY, "model": "gpt-mini-alias"},
                    headers=auth_headers(raw))
    assert r.status_code == 200
    assert mock.last_bodies["/responses"]["model"] == MODEL  # canonical sent upstream


def test_upstream_429_passthrough_with_retry(client, verified_client, mock):
    raw, _ = verified_client
    mock.scenario["status_override"] = {"/responses": 429}
    before = len(mock.calls)
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "mock_rate_limit"
    # Limited retry before streaming: initial + 2 retries = 3 upstream calls.
    assert len([c for c in mock.calls[before:] if c["path"] == "/responses"]) == 3


def test_upstream_5xx_passthrough_with_retry(client, verified_client, mock):
    raw, _ = verified_client
    mock.scenario["status_override"] = {"/responses": 500}
    before = len(mock.calls)
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 500
    assert r.json()["error"]["type"] == "mock_error"
    assert len([c for c in mock.calls[before:] if c["path"] == "/responses"]) == 3


def test_timeout(client, verified_client, app, mock):
    raw, _ = verified_client
    app.state.settings.upstream_timeout_s = 0.2
    mock.scenario["sleep_s"] = 2.0
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 504
    assert r.json()["error"]["code"] == "gateway_timeout"


def test_midstream_abort_terminates_upstream(client, verified_client, mock):
    raw, _ = verified_client
    mock.reset_stream_tracker()
    with client.stream("POST", "/v1/responses",
                       json={**RESP_BODY, "stream": True}, headers=auth_headers(raw)) as r:
        assert r.status_code == 200
        lines = r.iter_lines()
        first = next(lines)
        assert first.startswith("data:")
        # Break out early: client disconnects mid-stream.
    deadline = time.time() + 5
    while time.time() < deadline and not mock.stream_tracker["closed"]:
        time.sleep(0.05)
    assert mock.stream_tracker["closed"] is True, "upstream stream was not closed after client abort"
    assert mock.stream_tracker["completed"] is False


def test_get_response_passthrough(client, verified_client):
    raw, _ = verified_client
    r = client.get("/v1/responses/resp_mock_123", headers=auth_headers(raw))
    assert r.status_code == 200
    assert r.json()["id"] == "resp_mock_123"
    assert r.json()["status"] == "completed"


def test_cancel_response_passthrough(client, verified_client):
    raw, _ = verified_client
    r = client.post("/v1/responses/resp_mock_123/cancel", headers=auth_headers(raw))
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_compact_passthrough_preserves_blob(client, verified_client, mock):
    raw, _ = verified_client
    r = client.post("/v1/responses/compact",
                    json={"model": MODEL, "input": [{"type": "message", "role": "user",
                                                    "content": [{"type": "input_text", "text": "long history"}]}]},
                    headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    item = r.json()["output"][0]
    assert item["type"] == "compaction"
    assert item["encrypted_content"] == "MOCK-ENCRYPTED-BLOB-DO-NOT-USE"


def test_budget_hard_stop(client, verified_client, app, mock):
    raw, key_id = verified_client
    add_pricing(app, MODEL, inp=1.0, out=2.0)
    # Seed spend far above the $50 global monthly / $20 client monthly caps.
    add_usage(app, key_id, MODEL, cost=100.0)
    before = len(mock.calls)
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "budget_exceeded"
    assert "budget exceeded" in r.json()["error"]["message"]
    # Nothing new reached the mock upstream.
    assert len(mock.calls) == before


def test_budget_counts_exact_cost_only(client, verified_client, app):
    raw, key_id = verified_client
    add_pricing(app, MODEL, inp=1.0, out=2.0)
    # One real (mock) call: 10 in + 5 out tokens at $1/$2 per 1M = $0.00002.
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 200
    with app.state.session_factory() as s:
        usage = s.query(UsageRecord).filter(UsageRecord.client_key_id == key_id).one()
        assert usage.cost_status == "exact"
        assert abs(usage.cost_usd - 0.00002) < 1e-9


def test_rate_limit(client, verified_client, app):
    raw, key_id = verified_client
    set_rate_limit(app, key_id, 2)
    assert client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw)).status_code == 200
    assert client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw)).status_code == 200
    r = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(raw))
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"


def test_admin_create_client_key_once(client):
    r = client.post("/admin/client-keys", json={"name": "stage-c", "allowed_models": ["*"]},
                    headers={"Authorization": f"Bearer {ADMIN_KEY}"})
    assert r.status_code == 200
    key = r.json()["key"]
    assert key.startswith("pag_sk_")
    # The new key works as a client key.
    verify_model(client)
    r2 = client.post("/v1/responses", json=RESP_BODY, headers=auth_headers(key))
    assert r2.status_code == 200
