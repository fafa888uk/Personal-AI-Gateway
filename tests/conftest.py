"""pytest fixtures: fresh SQLite DB + mock upstream per test.

No real OpenAI key is used anywhere. The mock upstream stands in for
api.openai.com; every result labelled mock is mock, never real.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))
sys.path.insert(0, os.path.dirname(__file__))

from gateway.auth import generate_client_key, hash_client_key  # noqa: E402
from gateway.config import Settings  # noqa: E402
from gateway.main import create_app  # noqa: E402
from gateway.models import ClientKey, ModelRegistry, PricingRule, UsageRecord  # noqa: E402
from mock_upstream import MockUpstream  # noqa: E402

ADMIN_KEY = "test-admin-key-123"
MODEL = "gpt-5.4-mini"
MODEL2 = "gpt-5.4-nano"


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        openai_api_key="mock-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        database_url="",
        database_url_dev=f"sqlite:///{tmp_path}/test.db",
        admin_key=ADMIN_KEY,
        budget_global_daily_usd=5.0,
        budget_global_monthly_usd=50.0,
        budget_client_monthly_usd=20.0,
        candidate_models=[MODEL, MODEL2, "gpt-5.4"],
        upstream_timeout_s=5.0,
        allow_mock_verify=True,
    )


@pytest.fixture()
def mock():
    return MockUpstream()


@pytest.fixture()
def app(settings, mock):
    application = create_app(settings, transport=mock.transport)
    # Initialise the DB eagerly: key/registry fixtures touch
    # app.state.session_factory before the TestClient lifespan runs.
    from gateway.db import init_db

    application.state.session_factory = init_db(settings)
    application.state.rate_windows = {}
    application.state.semaphores = {}
    return application


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def _make_key(app, name, allowed):
    raw = generate_client_key()
    with app.state.session_factory() as session:
        row = ClientKey(
            name=name,
            key_hash=hash_client_key(raw),
            allowed_models=allowed,
            rate_limit_per_min=60,
            concurrency_limit=5,
            monthly_budget_usd=20.0,
            enabled=True,
        )
        session.add(row)
        session.commit()
        key_id = row.id
    return raw, key_id


@pytest.fixture()
def client_key(app):
    """Client key allowed to call any verified-enabled model."""
    raw, key_id = _make_key(app, "test-client", ["*"])
    return raw, key_id


@pytest.fixture()
def restricted_key(app):
    """Client key allowed only gpt-5.4-mini."""
    raw, key_id = _make_key(app, "restricted-client", [MODEL])
    return raw, key_id


def verify_model(client, name=MODEL, admin_key=ADMIN_KEY):
    resp = client.post(f"/admin/models/{name}/verify", json={"mode": "mock"},
                       headers={"Authorization": f"Bearer {admin_key}"})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture()
def verified_client(client, client_key):
    """Client fixture with gpt-5.4-mini verified via the mock path."""
    verify_model(client)
    return client_key


def set_model_available(app, name, status="available"):
    with app.state.session_factory() as session:
        row = session.query(ModelRegistry).filter(ModelRegistry.canonical_name == name).first()
        row.verification_status = status
        session.commit()


def set_rate_limit(app, key_id, per_min):
    with app.state.session_factory() as session:
        row = session.query(ClientKey).filter(ClientKey.id == key_id).first()
        row.rate_limit_per_min = per_min
        session.commit()


def add_pricing(app, model, inp=1.0, out=2.0):
    with app.state.session_factory() as session:
        session.add(PricingRule(model=model, input_usd_per_1m=inp, output_usd_per_1m=out))
        session.commit()


def add_usage(app, key_id, model, cost, tokens_in=1000000, tokens_out=1000000):
    with app.state.session_factory() as session:
        session.add(UsageRecord(trace_id="seed-spend", client_key_id=key_id, model=model,
                                tokens_in=tokens_in, tokens_out=tokens_out,
                                cost_usd=cost, cost_status="exact"))
        session.commit()


def auth_headers(raw):
    return {"Authorization": f"Bearer {raw}"}
