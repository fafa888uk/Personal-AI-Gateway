"""Tests for the chat-history API + usage summary (Stage C).

Auth scoping: a key sees ONLY its own sessions; another key's session
returns 404 (never 403 — no existence leak).
"""
from __future__ import annotations

from conftest import ADMIN_KEY, MODEL, add_pricing, add_usage, auth_headers, verify_model


def _create(client, key, title="hello", model=None):
    body = {"title": title}
    if model:
        body["model"] = model
    r = client.post("/api/v1/chats", json=body, headers=auth_headers(key))
    assert r.status_code == 201, r.text
    return r.json()


def test_chat_crud_and_ordering(client, client_key):
    raw, _ = client_key
    s1 = _create(client, raw, "first")
    s2 = _create(client, raw, "second")
    assert s1["id"] != s2["id"]
    assert s1["title"] == "first"

    r = client.get("/api/v1/chats", headers=auth_headers(raw))
    assert r.status_code == 200
    titles = [s["title"] for s in r.json()["sessions"]]
    assert titles == ["second", "first"]  # updated_at desc

    r = client.get(f"/api/v1/chats/{s1['id']}", headers=auth_headers(raw))
    assert r.status_code == 200 and r.json()["title"] == "first"

    r = client.patch(f"/api/v1/chats/{s1['id']}", json={"title": "renamed"},
                     headers=auth_headers(raw))
    assert r.status_code == 200 and r.json()["title"] == "renamed"

    # Renaming bumps updated_at, so it sorts first now.
    r = client.get("/api/v1/chats", headers=auth_headers(raw))
    assert [s["title"] for s in r.json()["sessions"]] == ["renamed", "second"]

    r = client.delete(f"/api/v1/chats/{s2['id']}", headers=auth_headers(raw))
    assert r.status_code == 200 and r.json()["deleted"] is True
    r = client.get(f"/api/v1/chats/{s2['id']}", headers=auth_headers(raw))
    assert r.status_code == 404


def test_chat_requires_auth(client, client_key):
    raw, _ = client_key
    r = client.get("/api/v1/chats")
    assert r.status_code == 401
    # Admin key must not double as a client key.
    r = client.get("/api/v1/chats", headers=auth_headers(ADMIN_KEY))
    assert r.status_code == 401


def test_chat_scoping_other_key_gets_404(client, client_key, app):
    from conftest import _make_key

    raw, _ = client_key
    other_raw, _ = _make_key(app, "other-client", ["*"])
    s = _create(client, raw, "mine")
    for method in ("get", "patch", "delete"):
        kwargs = {"headers": auth_headers(other_raw)}
        if method == "patch":
            kwargs["json"] = {"title": "x"}
        r = getattr(client, method)(f"/api/v1/chats/{s['id']}", **kwargs)
        assert r.status_code == 404, (method, r.text)
    r = client.get(f"/api/v1/chats/{s['id']}/messages", headers=auth_headers(other_raw))
    assert r.status_code == 404
    r = client.post(f"/api/v1/chats/{s['id']}/messages",
                    json={"role": "user", "content": "hi"},
                    headers=auth_headers(other_raw))
    assert r.status_code == 404
    # Other key's list is empty, not leaked.
    r = client.get("/api/v1/chats", headers=auth_headers(other_raw))
    assert r.json()["sessions"] == []


def test_chat_messages_roundtrip(client, client_key):
    raw, _ = client_key
    s = _create(client, raw, "thread", model=MODEL)
    r = client.post(f"/api/v1/chats/{s['id']}/messages",
                    json={"role": "user", "content": "你好", "model": MODEL},
                    headers=auth_headers(raw))
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "user" and r.json()["content"] == "你好"
    r = client.post(f"/api/v1/chats/{s['id']}/messages",
                    json={"role": "assistant", "content": "你好，我在。",
                          "model": MODEL, "tokens_in": 12, "tokens_out": 7},
                    headers=auth_headers(raw))
    assert r.status_code == 201
    assert r.json()["tokens_in"] == 12 and r.json()["tokens_out"] == 7
    r = client.get(f"/api/v1/chats/{s['id']}/messages", headers=auth_headers(raw))
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "你好"

    # Validation.
    r = client.post(f"/api/v1/chats/{s['id']}/messages",
                    json={"role": "robot", "content": "x"}, headers=auth_headers(raw))
    assert r.status_code == 400
    r = client.post(f"/api/v1/chats/{s['id']}/messages",
                    json={"role": "user", "content": ""}, headers=auth_headers(raw))
    assert r.status_code == 400
    r = client.post("/api/v1/chats/999999/messages",
                    json={"role": "user", "content": "x"}, headers=auth_headers(raw))
    assert r.status_code == 404

    # Deleting the session deletes its messages.
    r = client.delete(f"/api/v1/chats/{s['id']}", headers=auth_headers(raw))
    assert r.status_code == 200
    r = client.get(f"/api/v1/chats/{s['id']}/messages", headers=auth_headers(raw))
    assert r.status_code == 404


def test_usage_summary_empty_and_priced(client, app, client_key, verified_client):
    raw, key_id = client_key
    r = client.get("/api/v1/usage/summary?period=today", headers=auth_headers(raw))
    assert r.status_code == 200
    body = r.json()
    assert body["period"] == "today"
    assert body["requests"] == 0 and body["tokens_in"] == 0
    assert body["cost_usd"] == 0 and body["cost_status"] == "ok"
    assert body["by_model"] == []

    r = client.get("/api/v1/usage/summary?period=banana", headers=auth_headers(raw))
    assert r.status_code == 400

    # Real gateway call (mock upstream) + pricing -> exact cost.
    add_pricing(app, MODEL, inp=1.0, out=2.0)
    r = client.post("/v1/chat/completions",
                    json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}]},
                    headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/usage/summary?period=today", headers=auth_headers(raw))
    body = r.json()
    assert body["requests"] == 1
    assert body["tokens_in"] == 12 and body["tokens_out"] == 7
    # 12 * $1/1M + 7 * $2/1M = $0.000026
    assert abs(body["cost_usd"] - 0.000026) < 1e-9, body
    assert body["cost_status"] == "ok"
    assert body["by_model"][0]["model"] == MODEL
    assert body["by_model"][0]["requests"] == 1
    r = client.get("/api/v1/usage/summary?period=month", headers=auth_headers(raw))
    assert r.json()["requests"] == 1


def test_usage_summary_unpriced_status(client, app, client_key):
    raw, key_id = client_key
    # Usage without a pricing rule -> price_not_configured, never a fake cost.
    add_usage(app, key_id, MODEL, cost=None, tokens_in=100, tokens_out=50)
    # add_usage above writes cost_status exact with cost None; rewrite to the
    # honest status the gateway computes when no price exists.
    from gateway.models import UsageRecord

    with app.state.session_factory() as session:
        row = session.query(UsageRecord).filter(UsageRecord.client_key_id == key_id).first()
        row.cost_status = "price_not_configured"
        row.cost_usd = None
        session.commit()
    r = client.get("/api/v1/usage/summary?period=today", headers=auth_headers(raw))
    body = r.json()
    assert body["cost_status"] == "price_not_configured"
    assert body["cost_usd"] == 0
    assert body["tokens_in"] == 100 and body["tokens_out"] == 50


def test_usage_summary_scoped_to_calling_key(client, app, client_key):
    from conftest import _make_key

    raw, key_id = client_key
    other_raw, other_id = _make_key(app, "other-client", ["*"])
    add_usage(app, other_id, MODEL, cost=5.0, tokens_in=1000, tokens_out=1000)
    r = client.get("/api/v1/usage/summary?period=today", headers=auth_headers(raw))
    assert r.json()["requests"] == 0 and r.json()["tokens_in"] == 0
    r = client.get("/api/v1/usage/summary?period=today", headers=auth_headers(other_raw))
    assert r.json()["tokens_in"] == 1000 and r.json()["cost_usd"] == 5.0
