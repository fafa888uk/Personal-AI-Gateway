"""Dev mock gateway server for Flutter integration tests ONLY.

Starts the real FastAPI gateway app with the MockUpstream transport on
127.0.0.1:8000 (or --port), with a freshly seeded client key and one
mock-verified model (gpt-5.4-mini). Prints the client key once and
writes {"base_url", "client_key"} to --key-file for the integration
test to read.

MOCK ONLY — never for production, never with a real OpenAI key. The
mock-verified model is labelled mock-test-only in the DB, exactly like
the mock verification path in tests. Nothing served here is real
verification, real usage or a real model call.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gateway.auth import generate_client_key, hash_client_key  # noqa: E402
from gateway.config import Settings  # noqa: E402
from gateway.db import init_db  # noqa: E402
from gateway.main import create_app  # noqa: E402
from gateway.models import ClientKey, ModelRegistry  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "tests"))
from mock_upstream import MockUpstream  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the mock gateway for Flutter integration tests.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--key-file", default="/tmp/pag_mock_key.json")
    parser.add_argument("--model", default="gpt-5.4-mini")
    args = parser.parse_args()

    db_fd, db_path = tempfile.mkstemp(prefix="pag_mock_", suffix=".db")
    os.close(db_fd)
    settings = Settings(
        openai_api_key="mock-key-not-real",
        openai_base_url="https://api.openai.com/v1",
        database_url="",
        database_url_dev=f"sqlite:///{db_path}",
        admin_key="mock-admin-" + secrets.token_hex(8),
        candidate_models=[args.model],
        upstream_timeout_s=10.0,
        allow_mock_verify=True,
    )
    mock = MockUpstream()
    app = create_app(settings, transport=mock.transport)
    factory = init_db(settings)
    app.state.session_factory = factory

    raw = generate_client_key()
    with factory() as session:
        session.add(
            ClientKey(
                name="integration-test",
                key_hash=hash_client_key(raw),
                allowed_models=["*"],
                rate_limit_per_min=600,
                concurrency_limit=5,
                monthly_budget_usd=20.0,
                enabled=True,
            )
        )
        row = session.query(ModelRegistry).filter(
            ModelRegistry.canonical_name == args.model
        ).first()
        row.verification_status = "available"
        row.verification_method = "mock-test-only"
        session.commit()

    base_url = f"http://127.0.0.1:{args.port}"
    with open(args.key_file, "w", encoding="utf-8") as f:
        json.dump({"base_url": base_url, "client_key": raw}, f)
    print(f"MOCK gateway listening on {base_url} (db={db_path})")
    print("Client key written to", args.key_file, "(MOCK ONLY, single use)")

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
