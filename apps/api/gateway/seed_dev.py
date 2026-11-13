"""Dev seed script: create one test client key and print it ONCE.

Usage (from apps/api):
    python -m gateway.seed_dev [--name NAME] [--models gpt-5.4-mini,...]

- Creates tables + seeds the model registry if needed.
- Creates a client key allowed to call the given models (default: all
  verified-enabled models, i.e. ["*"]) and prints the raw key once.
  Only the SHA-256 hash is stored; the raw key is never written to disk
  or committed. Re-run to create another key; old keys are not printed.
- If GATEWAY_ADMIN_KEY is not set in the environment or .env, generates
  one, appends it to the repo-root .env (gitignored) and prints it once.
  The admin key is never usable as a client key.

NEVER run this against production with the intent of sharing the output.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gateway.auth import generate_client_key, hash_client_key  # noqa: E402
from gateway.config import Settings, load_dotenv  # noqa: E402
from gateway.db import init_db  # noqa: E402
from gateway.models import ClientKey  # noqa: E402


def _ensure_admin_key_in_dotenv(repo_root: str) -> str | None:
    dotenv_path = os.path.join(repo_root, ".env")
    existing = ""
    if os.path.exists(dotenv_path):
        with open(dotenv_path, encoding="utf-8") as f:
            existing = f.read()
        for line in existing.splitlines():
            if line.startswith("GATEWAY_ADMIN_KEY=") and line.split("=", 1)[1].strip():
                return None  # already configured; do not print it
    admin_key = "pag_admin_" + secrets.token_urlsafe(32)
    with open(dotenv_path, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(f"GATEWAY_ADMIN_KEY={admin_key}\n")
    return admin_key


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a dev test client key (printed once).")
    parser.add_argument("--name", default="dev-test")
    parser.add_argument("--models", default="*",
                        help="Comma-separated canonical models, or * for all verified-enabled")
    args = parser.parse_args()

    api_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(os.path.dirname(api_dir))
    load_dotenv(os.path.join(repo_root, ".env"))
    load_dotenv(".env")
    settings = Settings.from_env()

    admin_key = None
    if not settings.admin_key:
        admin_key = _ensure_admin_key_in_dotenv(repo_root)
        if admin_key:
            settings.admin_key = admin_key

    factory = init_db(settings)
    allowed = ["*"] if args.models.strip() == "*" else [m.strip() for m in args.models.split(",") if m.strip()]
    raw = generate_client_key()
    with factory() as session:
        row = ClientKey(
            name=args.name,
            key_hash=hash_client_key(raw),
            allowed_models=allowed,
            rate_limit_per_min=settings.default_rate_limit_per_min,
            concurrency_limit=settings.default_concurrency_limit,
            monthly_budget_usd=settings.budget_client_monthly_usd,
            enabled=True,
        )
        session.add(row)
        session.commit()
        print(f"Client key created: id={row.id} name={row.name} allowed_models={allowed}")
    print()
    print("=== SAVE THIS NOW — it is printed once and never stored ===")
    print(f"CLIENT KEY: {raw}")
    if admin_key:
        print(f"ADMIN KEY (written to .env): {admin_key}")
    print("Base URL: http://127.0.0.1:8000/v1  (local dev)")
    print("NOTE: models start unverified; /v1/models is empty until a model")
    print("is verified via POST /admin/models/{name}/verify (real key needed).")


if __name__ == "__main__":
    main()
