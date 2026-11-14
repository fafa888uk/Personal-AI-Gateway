"""Stage E admin console tests — cookie-session auth + /api/v1/admin/*.

All against the MOCK upstream. Mock verification is labelled
mock-test-only and is never real verification.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import (
    ADMIN_KEY,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    MODEL,
    MODEL2,
    auth_headers,
)
from gateway.config import Settings
from gateway.db import init_db
from gateway.main import create_app
from gateway.models import ApiRequestLog, ClientKey, ModelRegistry, UsageRecord
from mock_upstream import MockUpstream


def _login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    return client.post("/api/v1/admin/login", json={"username": username, "password": password})


def _authed(client):
    """Log in and return the CSRF header for mutating requests.

    The TestClient keeps the pag_admin / pag_csrf cookies afterwards.
    """
    r = _login(client)
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/admin/csrf")
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _unconfigured_client(tmp_path):
    settings = Settings(
        openai_api_key="mock-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        database_url="",
        database_url_dev=f"sqlite:///{tmp_path}/test.db",
        admin_key=ADMIN_KEY,
        candidate_models=[MODEL],
        upstream_timeout_s=5.0,
    )
    application = create_app(settings, transport=MockUpstream().transport)
    application.state.session_factory = init_db(settings)
    application.state.rate_windows = {}
    application.state.semaphores = {}
    return TestClient(application)


def _seed_usage(app, key_id):
    """3 successful + 1 failed log; usage with mixed cost statuses."""
    with app.state.session_factory() as s:
        for i, latency in enumerate((100, 200, 300)):
            s.add(ApiRequestLog(trace_id=f"trace-ok-{i}", client_key_id=key_id,
                                model=MODEL, endpoint="POST /v1/responses",
                                status_code=200, latency_ms=latency,
                                tokens_in=10, tokens_out=5,
                                upstream_request_id=f"req_ok_{i}"))
        s.add(ApiRequestLog(trace_id="trace-err-0", client_key_id=key_id,
                            model=MODEL2, endpoint="POST /v1/responses",
                            status_code=500, latency_ms=400,
                            tokens_in=None, tokens_out=None,
                            error_type="upstream_error",
                            upstream_request_id="req_err_0"))
        s.add(UsageRecord(trace_id="trace-ok-0", client_key_id=key_id, model=MODEL,
                          tokens_in=1000, tokens_out=500, tokens_cached=100,
                          tokens_reasoning=50, cost_usd=0.01, cost_status="exact"))
        s.add(UsageRecord(trace_id="trace-ok-1", client_key_id=key_id, model=MODEL,
                          tokens_in=0, tokens_out=0,
                          cost_usd=None, cost_status="not_obtained"))
        s.add(UsageRecord(trace_id="trace-ok-2", client_key_id=key_id, model=MODEL,
                          tokens_in=0, tokens_out=0,
                          cost_usd=None, cost_status="price_not_configured"))
        s.add(UsageRecord(trace_id="trace-err-0", client_key_id=key_id, model=MODEL2,
                          tokens_in=200, tokens_out=100,
                          cost_usd=0.02, cost_status="exact"))
        s.commit()


# ---------------------------------------------------------------- auth
def test_login_success_sets_cookie_and_me(client):
    r = _login(client)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "username": ADMIN_USERNAME}
    set_cookie = r.headers.get("set-cookie", "")
    assert "pag_admin=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    me = client.get("/api/v1/admin/me")
    assert me.status_code == 200
    assert me.json() == {"authenticated": True, "username": ADMIN_USERNAME}


def test_login_failure_wrong_password_and_unknown_user(client):
    r = _login(client, password="wrong-password")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_admin_credentials"
    assert client.get("/api/v1/admin/me").status_code == 401
    r = _login(client, username="nosuchuser", password="wrong-password")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_admin_credentials"


def test_login_rate_limit_after_five_failures(client):
    for _ in range(5):
        assert _login(client, password="wrong-password").status_code == 401
    r = _login(client, password="wrong-password")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"


def test_login_not_configured_returns_503(tmp_path):
    with _unconfigured_client(tmp_path) as c:
        r = c.post("/api/v1/admin/login",
                   json={"username": ADMIN_USERNAME, "password": "anything"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "admin_not_configured"


def test_logout_clears_session(client):
    _authed(client)
    assert client.get("/api/v1/admin/me").status_code == 200
    headers = _authed(client)  # refresh CSRF header; session still valid
    r = client.post("/api/v1/admin/logout", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert client.get("/api/v1/admin/me").status_code == 401


def test_csrf_missing_or_wrong_forbidden_on_mutation(client):
    _login(client)
    body = {"name": "x", "client_type": "web"}
    r = client.post("/api/v1/admin/client-keys", json=body)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_invalid"
    r = client.post("/api/v1/admin/client-keys", json=body,
                    headers={"X-CSRF-Token": "bogus"})
    assert r.status_code == 403


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/admin/models"),
    ("GET", "/api/v1/admin/client-keys"),
    ("GET", "/api/v1/admin/usage"),
    ("GET", "/api/v1/admin/requests"),
    ("GET", "/api/v1/admin/requests/trace-abc"),
    ("GET", "/api/v1/admin/settings"),
    ("GET", "/api/v1/admin/audit"),
    ("GET", "/api/v1/admin/me"),
    ("GET", "/api/v1/admin/csrf"),
    ("POST", "/api/v1/admin/models/gpt-5.4-mini/verify"),
    ("POST", "/api/v1/admin/client-keys"),
    ("POST", "/api/v1/admin/client-keys/1/revoke"),
    ("POST", "/api/v1/admin/client-keys/1/regenerate"),
    ("POST", "/api/v1/admin/logout"),
    ("PATCH", "/api/v1/admin/models/gpt-5.4-mini"),
    ("PATCH", "/api/v1/admin/client-keys/1"),
    ("PUT", "/api/v1/admin/settings"),
])
def test_unauthenticated_401_on_every_admin_endpoint(client, method, path):
    r = client.request(method, path, json={})
    assert r.status_code == 401, (method, path, r.text)
    assert r.json()["error"]["code"] == "admin_unauthorized"


def test_bearer_keys_do_not_authenticate_new_admin_api(client, client_key):
    raw, _ = client_key
    r = client.get("/api/v1/admin/me", headers=auth_headers(ADMIN_KEY))
    assert r.status_code == 401
    r = client.get("/api/v1/admin/models", headers=auth_headers(raw))
    assert r.status_code == 401


# ---------------------------------------------------------------- models
def test_admin_models_list_shows_upstream_state(client):
    _login(client)
    r = client.get("/api/v1/admin/models")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["upstream_reachable"] is True
    by_name = {m["canonical_name"]: m for m in body["models"]}
    assert by_name[MODEL]["in_upstream"] is True
    assert by_name[MODEL2]["in_upstream"] is True
    # verification_status comes only from the DB (still pending here).
    assert by_name[MODEL]["verification_status"] == "pending"
    assert {"id": "gpt-upstream-only"} in body["upstream_only"]


def test_admin_patch_model_and_single_default(client, app):
    headers = _authed(client)
    r = client.patch(f"/api/v1/admin/models/{MODEL}", json={
        "enabled": False, "aliases": ["alias-x"], "sort_order": 5,
        "pinned_group": "gpt-5.4", "cap_image": True,
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False
    assert r.json()["aliases"] == ["alias-x"]
    assert r.json()["sort_order"] == 5
    assert r.json()["capabilities"]["image"] is True
    # Setting MODEL2 as default clears MODEL's default.
    r = client.patch(f"/api/v1/admin/models/{MODEL2}", json={"is_default": True},
                     headers=headers)
    assert r.status_code == 200
    assert r.json()["is_default"] is True
    with app.state.session_factory() as s:
        row = s.query(ModelRegistry).filter(ModelRegistry.canonical_name == MODEL).first()
        assert row.is_default is False
    # Bad type -> 400.
    r = client.patch(f"/api/v1/admin/models/{MODEL}", json={"enabled": "yes"},
                     headers=headers)
    assert r.status_code == 400
    # Unknown model -> 404.
    r = client.patch("/api/v1/admin/models/gpt-nope", json={"enabled": True},
                     headers=headers)
    assert r.status_code == 404


def test_admin_verify_model_mock_labelled_and_warns_cost(client):
    headers = _authed(client)
    r = client.post(f"/api/v1/admin/models/{MODEL}/verify", json={"mode": "mock"},
                    headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"]["verification_status"] == "available"
    assert body["model"]["verification_method"] == "mock-test-only"
    assert body["verification_method"] == "mock-test-only"
    assert "may incur API cost" in body["cost_warning"]
    assert "NOT real verification" in (body.get("note") or "")
    r = client.post("/api/v1/admin/models/gpt-nope/verify", json={"mode": "mock"},
                    headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------- client keys
def test_client_key_create_once_list_hides_key(client):
    headers = _authed(client)
    r = client.post("/api/v1/admin/client-keys", json={
        "name": "codex-laptop", "client_type": "codex", "allowed_models": ["*"],
        "rate_limit_per_min": 30, "concurrency_limit": 2, "monthly_budget_usd": 10,
    }, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    raw = body["raw_key"]
    assert raw.startswith("pag_sk_")
    assert body["key_prefix"] == raw[:12]
    assert body["client_type"] == "codex"
    assert body["type"] == "codex"
    # The list view never shows raw key material.
    r = client.get("/api/v1/admin/client-keys")
    assert r.status_code == 200
    keys = r.json()["client_keys"]
    assert len(keys) == 1
    assert "raw_key" not in keys[0] and "key" not in keys[0]
    assert keys[0]["key_prefix"] == raw[:12]
    assert keys[0]["name"] == "codex-laptop"
    assert keys[0]["rate_limit_per_min"] == 30
    # Only the hash is stored.
    assert body["id"] == keys[0]["id"]


def test_client_key_create_invalid_type_400(client):
    headers = _authed(client)
    r = client.post("/api/v1/admin/client-keys",
                    json={"name": "x", "client_type": "bogus"}, headers=headers)
    assert r.status_code == 400


def test_client_key_patch_revoke_regenerate(client, app):
    headers = _authed(client)
    r = client.post("/api/v1/admin/client-keys",
                    json={"name": "web-ui", "client_type": "web"}, headers=headers)
    key_id = r.json()["id"]
    old_raw = r.json()["raw_key"]
    # Patch.
    r = client.patch(f"/api/v1/admin/client-keys/{key_id}",
                     json={"name": "web-ui-renamed", "monthly_budget_usd": 5},
                     headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "web-ui-renamed"
    assert r.json()["monthly_budget_usd"] == 5
    # Regenerate: new raw key once, old key stops working.
    r = client.post(f"/api/v1/admin/client-keys/{key_id}/regenerate", headers=headers)
    assert r.status_code == 200, r.text
    new_raw = r.json()["raw_key"]
    assert new_raw != old_raw
    assert client.get("/v1/models", headers=auth_headers(old_raw)).status_code == 401
    assert client.get("/v1/models", headers=auth_headers(new_raw)).status_code == 200
    # Revoke: row kept, enabled=false.
    r = client.post(f"/api/v1/admin/client-keys/{key_id}/revoke", headers=headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert client.get("/v1/models", headers=auth_headers(new_raw)).status_code == 403
    with app.state.session_factory() as s:
        row = s.query(ClientKey).filter(ClientKey.id == key_id).first()
        assert row is not None and row.enabled is False
    # Unknown key id -> 404.
    assert client.post("/api/v1/admin/client-keys/99999/revoke",
                       headers=headers).status_code == 404


# ---------------------------------------------------------------- usage / traces
def test_usage_aggregation_correctness(client, client_key, app):
    _raw, key_id = client_key
    _login(client)
    _seed_usage(app, key_id)
    r = client.get("/api/v1/admin/usage?period=today")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requests"] == 4
    assert body["success_count"] == 3
    assert body["error_count"] == 1
    assert body["success_rate"] == 0.75
    assert body["error_rate"] == 0.25
    assert body["avg_latency_ms"] == 250.0
    assert body["p95_latency_ms"] == 400
    assert body["tokens"] == {"in": 1200, "out": 600, "total": 1800,
                              "cached": 100, "reasoning": 50}
    # Only exact costs count; not_obtained / price_not_configured never
    # presented as exact.
    assert body["cost_usd"] == 0.03
    assert body["cost_status"] == {"exact": 2, "not_obtained": 1,
                                   "price_not_configured": 1}
    per_model = {m["model"]: m for m in body["per_model"]}
    assert per_model[MODEL]["requests"] == 3
    assert per_model[MODEL]["cost_usd"] == 0.01
    assert per_model[MODEL2]["requests"] == 1
    assert per_model[MODEL2]["cost_usd"] == 0.02
    assert body["per_model"][0]["model"] == MODEL  # ranked by requests
    per_client = {c["client"]: c for c in body["per_client"]}
    assert per_client["test-client"]["requests"] == 4
    assert len(body["daily_trend"]) == 1
    assert body["daily_trend"][0]["requests"] == 4
    assert body["daily_trend"][0]["cost_usd"] == 0.03
    assert body["errors"] == [{"error_type": "upstream_error",
                               "status_code": 500, "count": 1}]
    assert body["budget"]["spent_today"] == 0.03
    assert body["budget"]["spent_month"] == 0.03
    assert body["budget"]["alerts"] == []
    # Yesterday has no data: rates and latencies are null, not zero/fake.
    r = client.get("/api/v1/admin/usage?period=yesterday")
    body = r.json()
    assert body["requests"] == 0
    assert body["success_rate"] is None
    assert body["avg_latency_ms"] is None
    assert body["p95_latency_ms"] is None
    assert body["cost_usd"] == 0
    # Bad period -> 400.
    assert client.get("/api/v1/admin/usage?period=year").status_code == 400


def test_requests_list_trace_and_404(client, client_key, app):
    _raw, key_id = client_key
    _login(client)
    _seed_usage(app, key_id)
    r = client.get("/api/v1/admin/requests")
    assert r.status_code == 200
    rows = r.json()["requests"]
    assert len(rows) == 4
    assert all("trace_id" in row and "client" in row for row in rows)
    assert rows[0]["client"] == "test-client"
    r = client.get("/api/v1/admin/requests?error_only=true")
    assert [row["trace_id"] for row in r.json()["requests"]] == ["trace-err-0"]
    r = client.get("/api/v1/admin/requests/trace-ok-0")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["upstream_request_id"] == "req_ok_0"
    assert body["usage"]["cost_usd"] == 0.01
    assert body["usage"]["cost_status"] == "exact"
    assert body["usage"]["tokens_in"] == 1000
    assert client.get("/api/v1/admin/requests/no-such-trace").status_code == 404


# ---------------------------------------------------------------- settings / audit
def test_settings_get_put_and_validation(client):
    _login(client)
    r = client.get("/api/v1/admin/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["budgets"] == {"global_daily_usd": 5.0, "global_monthly_usd": 50.0}
    assert body["retention_days"] == 90
    assert body["pricing_rules"] == []
    assert body["version"]["configured"] is False
    headers = _authed(client)
    # Invalid inputs -> 400, nothing persisted.
    assert client.put("/api/v1/admin/settings",
                      json={"budgets": {"global_daily_usd": -1}},
                      headers=headers).status_code == 400
    assert client.put("/api/v1/admin/settings", json={"retention_days": 0},
                      headers=headers).status_code == 400
    assert client.put("/api/v1/admin/settings",
                      json={"pricing_rules": [{"model": MODEL}]},
                      headers=headers).status_code == 400
    # Valid update persists and is reflected by GET + usage budget.
    r = client.put("/api/v1/admin/settings", json={
        "budgets": {"global_daily_usd": 10, "global_monthly_usd": 100},
        "retention_days": 30,
        "pricing_rules": [{"model": MODEL, "input_usd_per_1m": 1.5,
                           "output_usd_per_1m": 3.0}],
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["budgets"] == {"global_daily_usd": 10.0, "global_monthly_usd": 100.0}
    assert r.json()["retention_days"] == 30
    assert len(r.json()["pricing_rules"]) == 1
    assert r.json()["pricing_rules"][0]["input_usd_per_1m"] == 1.5
    r = client.get("/api/v1/admin/settings")
    assert r.json()["budgets"]["global_daily_usd"] == 10.0
    r = client.get("/api/v1/admin/usage?period=today")
    assert r.json()["budget"]["global_daily_usd"] == 10.0


def test_audit_log_records_admin_actions(client):
    headers = _authed(client)
    client.patch(f"/api/v1/admin/models/{MODEL}", json={"enabled": False},
                 headers=headers)
    r = client.get("/api/v1/admin/audit")
    assert r.status_code == 200
    kinds = [e["kind"] for e in r.json()["audit"]]
    assert "admin_login" in kinds
    assert "model_updated" in kinds


# ---------------------------------------------------------------- legacy /admin/*
def test_legacy_admin_bearer_endpoints_still_work(client):
    r = client.get("/admin/models", headers={"Authorization": f"Bearer {ADMIN_KEY}"})
    assert r.status_code == 200
    r = client.get("/admin/budgets", headers={"Authorization": f"Bearer {ADMIN_KEY}"})
    assert r.status_code == 200
    assert r.json()["global_daily"]["limit_usd"] == 5.0
    r = client.post("/admin/client-keys", json={"name": "legacy"},
                    headers={"Authorization": f"Bearer {ADMIN_KEY}"})
    assert r.status_code == 200
    assert r.json()["key"].startswith("pag_sk_")
