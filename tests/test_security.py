"""Stage F security tests — all against the MOCK upstream.

Covers: persisted-settings budgets enforced on /v1/* calls (env is
default/fallback); admin password rotation + session revocation;
failed-login audit rows; log redaction (no raw keys/tokens/passwords
in log output).
"""
from __future__ import annotations

import io
import logging
import logging.handlers

from fastapi.testclient import TestClient

from conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    MODEL,
    add_pricing,
    add_usage,
    auth_headers,
    verify_model,
)
from gateway import budgets as budgets_mod
from gateway.logsafe import RedactingFilter, configure_logging, redact
from gateway.models import AdminSession, AuditEvent, SystemSetting

CHAT_BODY = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
NEW_PASSWORD = "new-admin-pass-1234"


def _login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    return client.post("/api/v1/admin/login",
                       json={"username": username, "password": password})


def _authed(client):
    r = _login(client)
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/admin/csrf")
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _set_budgets(client, headers, daily=None, monthly=None):
    budgets = {}
    if daily is not None:
        budgets["global_daily_usd"] = daily
    if monthly is not None:
        budgets["global_monthly_usd"] = monthly
    r = client.put("/api/v1/admin/settings", json={"budgets": budgets}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _audit_kinds(app, kind):
    with app.state.session_factory() as s:
        return [a.detail for a in
                s.query(AuditEvent).filter(AuditEvent.kind == kind).all()]


# ---------------------------------------------------------------- budgets
def test_settings_daily_budget_enforced_on_v1_calls(client, verified_client, app):
    raw, key_id = verified_client
    add_pricing(app, MODEL, 1.0, 2.0)
    add_usage(app, key_id, MODEL, cost=3.0)  # $3 spent today; env daily is $5
    headers = _authed(client)
    # Persisted daily $2 < spent $3 -> the /v1/* call must hard-stop.
    _set_budgets(client, headers, daily=2.0)
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "budget_exceeded"
    assert "$2.00" in r.json()["error"]["message"]
    # Raise the persisted limit above spend -> the same call passes.
    _set_budgets(client, headers, daily=10.0)
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text


def test_settings_monthly_budget_enforced_on_v1_calls(client, verified_client, app):
    raw, key_id = verified_client
    add_pricing(app, MODEL, 1.0, 2.0)
    add_usage(app, key_id, MODEL, cost=3.0)  # $3 spent this month; env monthly $50
    headers = _authed(client)
    _set_budgets(client, headers, monthly=2.0)
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "budget_exceeded"


def test_env_budget_applies_when_no_setting_persisted(client, verified_client, app):
    raw, key_id = verified_client
    add_pricing(app, MODEL, 1.0, 2.0)
    add_usage(app, key_id, MODEL, cost=3.0)  # under the env daily $5
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 200, r.text
    add_usage(app, key_id, MODEL, cost=3.0)  # now $6 >= env daily $5
    r = client.post("/v1/chat/completions", json=CHAT_BODY, headers=auth_headers(raw))
    assert r.status_code == 429, r.text
    assert "$5.00" in r.json()["error"]["message"]


def test_invalid_persisted_budget_falls_back_to_env(app, settings):
    with app.state.session_factory() as s:
        s.add(SystemSetting(key="budget_global_daily_usd", value="not-a-number"))
        s.add(SystemSetting(key="budget_global_monthly_usd", value=-5))
        s.commit()
    daily, monthly = budgets_mod.resolve_global_budgets(
        app.state.session_factory(), settings)
    assert daily == settings.budget_global_daily_usd == 5.0
    assert monthly == settings.budget_global_monthly_usd == 50.0


def test_resolve_global_budgets_reads_persisted_values(app, settings):
    with app.state.session_factory() as s:
        s.add(SystemSetting(key="budget_global_daily_usd", value=1.5))
        s.add(SystemSetting(key="budget_global_monthly_usd", value=12.0))
        s.commit()
    daily, monthly = budgets_mod.resolve_global_budgets(
        app.state.session_factory(), settings)
    assert (daily, monthly) == (1.5, 12.0)


# ---------------------------------------------------------------- admin password
def test_change_password_wrong_current_rejected(client):
    headers = _authed(client)
    r = client.post("/api/v1/admin/change-password",
                    json={"current_password": "wrong", "new_password": NEW_PASSWORD},
                    headers=headers)
    assert r.status_code == 401
    assert _login(client).status_code == 200  # old password still works


def test_change_password_validates_new_password(client):
    headers = _authed(client)
    r = client.post("/api/v1/admin/change-password",
                    json={"current_password": ADMIN_PASSWORD, "new_password": "short"},
                    headers=headers)
    assert r.status_code == 400
    r = client.post("/api/v1/admin/change-password",
                    json={"current_password": ADMIN_PASSWORD, "new_password": ADMIN_PASSWORD},
                    headers=headers)
    assert r.status_code == 400


def test_change_password_rotates_and_revokes_sessions(client, app):
    headers = _authed(client)
    r = client.post("/api/v1/admin/change-password",
                    json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD},
                    headers=headers)
    assert r.status_code == 200, r.text
    # Every session is revoked, including the caller's.
    assert client.get("/api/v1/admin/me").status_code == 401
    assert _login(client).status_code == 401  # old password dead
    assert _login(client, password=NEW_PASSWORD).status_code == 200
    assert _audit_kinds(app, "admin_password_changed")
    with app.state.session_factory() as s:
        assert s.query(AdminSession).count() == 1  # only the fresh login


def test_change_password_requires_session_and_csrf(client):
    r = client.post("/api/v1/admin/change-password",
                    json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 401
    _login(client)
    r = client.post("/api/v1/admin/change-password",
                    json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 403  # logged in but no CSRF header


# ---------------------------------------------------------------- session revocation
def test_revoke_all_sessions_logs_out_everywhere(app, client):
    headers = _authed(client)
    with TestClient(app) as other:
        assert _login(other).status_code == 200
        assert other.get("/api/v1/admin/me").status_code == 200
        r = client.post("/api/v1/admin/sessions/revoke-all", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["revoked"] == 2
        assert client.get("/api/v1/admin/me").status_code == 401
        assert other.get("/api/v1/admin/me").status_code == 401
    assert _audit_kinds(app, "admin_sessions_revoked")
    with app.state.session_factory() as s:
        assert s.query(AdminSession).count() == 0


# ---------------------------------------------------------------- failed-login audit
def test_failed_login_writes_audit_row_without_password(client, app):
    r = _login(client, password="wrong-password")
    assert r.status_code == 401
    rows = _audit_kinds(app, "admin_login_failed")
    assert len(rows) == 1
    assert ADMIN_USERNAME in rows[0]
    assert "wrong-password" not in rows[0]


def test_rate_limited_attempts_add_no_further_audit_rows(client, app):
    for _ in range(5):
        assert _login(client, password="wrong-password").status_code == 401
    assert _login(client, password="wrong-password").status_code == 429
    assert _login(client, password="wrong-password").status_code == 429
    # Exactly 5 failed-login rows: the 429 path writes none (bounded).
    assert len(_audit_kinds(app, "admin_login_failed")) == 5


# ---------------------------------------------------------------- log redaction
def test_redact_strips_keys_tokens_and_passwords():
    raw_key = "pag_sk_Q7Xn-abc123XYZ_456"
    admin_key = "pag_admin_Zz9_abcdef0123456789"
    upstream = "sk-proj-abcdef0123456789"
    cases = [
        (f"client key {raw_key} leaked", raw_key),
        (f"admin key {admin_key}", admin_key),
        (f"upstream {upstream} failed", upstream),
        ("Authorization: Bearer abcdef0123456789XYZ", "abcdef0123456789XYZ"),
        ("password=hunter2", "hunter2"),
        ('"password": "hunter2"', "hunter2"),
        ("OPENAI_API_KEY=sk-abcdef0123456789", "sk-abcdef0123456789"),
        ("GATEWAY_ADMIN_KEY=pag_admin_Zz9_abcdef0123456789", admin_key),
    ]
    for text, secret in cases:
        out = redact(text)
        assert secret not in out, text
        assert "[REDACTED" in out, text
    # Ordinary text is untouched.
    assert redact("client key created id=1 name=web") == "client key created id=1 name=web"
    assert redact("trace=abc123 upstream_timeout") == "trace=abc123 upstream_timeout"


def test_gateway_logger_filter_redacts_secrets():
    logger = logging.getLogger("gateway")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        logger.warning("auth failed for key %s", "pag_sk_Q7Xn-abc123XYZ_456")
        logger.warning("Bearer %s", "abcdef0123456789XYZ")
        out = stream.getvalue()
    finally:
        logger.removeHandler(handler)
    assert "pag_sk_Q7Xn" not in out
    assert "abcdef0123456789XYZ" not in out
    assert "[REDACTED-CLIENT-KEY]" in out
    assert "Bearer [REDACTED]" in out


def test_configure_logging_adds_rotating_file_handler(tmp_path):
    logger = logging.getLogger("gateway-test-rotate")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    log_file = tmp_path / "gateway.log"
    configure_logging(logger, str(log_file))
    assert any(isinstance(h, logging.handlers.RotatingFileHandler)
               for h in logger.handlers)
    logger.warning("key %s", "pag_sk_Q7Xn-abc123XYZ_456")
    for h in logger.handlers:
        h.flush()
    content = log_file.read_text(encoding="utf-8")
    assert "pag_sk_Q7Xn" not in content
    assert "[REDACTED-CLIENT-KEY]" in content
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()


def test_redacting_filter_is_attached_to_gateway_logger():
    logger = logging.getLogger("gateway")
    assert any(isinstance(f, RedactingFilter) for f in logger.filters)
