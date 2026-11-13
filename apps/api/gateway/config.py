"""Personal AI Gateway — core API gateway (Stage B).

Native OpenAI Responses + Chat Completions passthrough with a model
registry, client-key auth, per-client rate/concurrency limits and hard
budget stops. No real OpenAI key is bundled or required for local tests:
all local tests run against a mock upstream (see tests/).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def load_dotenv(path: str) -> None:
    """Minimal .env loader: only sets variables not already in the env."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    # Production PostgreSQL URL; dev falls back to DATABASE_URL_DEV / SQLite.
    database_url: str = ""
    database_url_dev: str = "sqlite:///./data/dev.db"
    admin_username: str = "admin"
    # Admin API key for /admin/* endpoints. Never doubles as a client key.
    # Empty => admin endpoints return 503 until configured.
    admin_key: str = ""
    budget_global_daily_usd: float = 5.0
    budget_global_monthly_usd: float = 50.0
    budget_client_monthly_usd: float = 20.0
    candidate_models: list[str] = field(default_factory=list)
    upstream_timeout_s: float = 120.0
    max_request_bytes: int = 20 * 1024 * 1024
    default_rate_limit_per_min: int = 60
    default_concurrency_limit: int = 5
    # Test-only: allow /admin/models/{name}/verify with mode=mock.
    # Must stay false outside tests; mock verification is never real.
    allow_mock_verify: bool = False
    # Max seconds to wait for a Retry-After header value.
    max_retry_after_s: float = 30.0
    # Release info served by GET /api/v1/app/version. Server-side only:
    # clients must never hardcode versions or embed a GitHub PAT.
    # Empty => the endpoint honestly reports "no release configured".
    # Shape: {"version": "1.0.0", "platforms": {"ios": {"version": ...,
    #   "release_date": ..., "download_url": ..., "sha256": ...,
    #   "release_notes": ...}, "windows": {...}, "macos": {...}, "web": {...}}}
    app_version: str = ""
    app_release_info_json: str = ""

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return self.database_url_dev or "sqlite:///./data/dev.db"

    @classmethod
    def from_env(cls) -> "Settings":
        candidates = os.environ.get("CANDIDATE_MODELS", "")
        models = [m.strip() for m in candidates.split(",") if m.strip()]
        return cls(
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_base_url=os.environ.get(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/"),
            database_url=os.environ.get("DATABASE_URL", ""),
            database_url_dev=os.environ.get(
                "DATABASE_URL_DEV", "sqlite:///./data/dev.db"
            ),
            admin_username=os.environ.get("ADMIN_USERNAME", "admin"),
            admin_key=os.environ.get("GATEWAY_ADMIN_KEY", ""),
            budget_global_daily_usd=_float("BUDGET_GLOBAL_DAILY_USD", 5.0),
            budget_global_monthly_usd=_float("BUDGET_GLOBAL_MONTHLY_USD", 50.0),
            budget_client_monthly_usd=_float("BUDGET_CLIENT_MONTHLY_USD", 20.0),
            candidate_models=models,
            upstream_timeout_s=_float("UPSTREAM_TIMEOUT_S", 120.0),
            max_request_bytes=_int("MAX_REQUEST_BYTES", 20 * 1024 * 1024),
            default_rate_limit_per_min=_int("DEFAULT_RATE_LIMIT_PER_MIN", 60),
            default_concurrency_limit=_int("DEFAULT_CONCURRENCY_LIMIT", 5),
            allow_mock_verify=os.environ.get(
                "GATEWAY_ALLOW_MOCK_VERIFY", ""
            ).lower()
            in ("1", "true", "yes"),
            max_retry_after_s=_float("MAX_RETRY_AFTER_S", 30.0),
            app_version=os.environ.get("APP_VERSION", ""),
            app_release_info_json=os.environ.get("APP_RELEASE_INFO_JSON", ""),
        )
