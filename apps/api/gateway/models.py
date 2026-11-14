"""SQLAlchemy models for the gateway (Stage B).

Tables: model_registry, client_keys, api_request_logs, usage_records,
pricing_rules, audit_events. All types are portable SQLAlchemy types —
no SQLite-only SQL is used anywhere, so the same models work on
PostgreSQL (production, via Alembic) and SQLite (local dev).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # Aliases that resolve to this canonical name, e.g. ["gpt-5.4-mini"].
    aliases: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Pinned-version grouping, e.g. "gpt-5.4" for gpt-5.4-2026-03-05.
    pinned_group: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cap_responses: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cap_chat: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cap_streaming: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cap_tools: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cap_image: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # pending | available | unavailable | forbidden | rate_limited
    verification_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "real" | "mock-test-only" | None
    verification_method: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class ClientKey(Base):
    __tablename__ = "client_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Irreversible SHA-256 hex digest of the raw key. Raw key is never stored.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # First 12 chars of the raw key at creation (e.g. "pag_sk_aB3..."),
    # for display only; the raw key itself is never stored.
    key_prefix: Mapped[str | None] = mapped_column(String(16))
    # Client kind: "web" | "codex" | "vscode" | "other" (nullable for
    # keys created before Stage E).
    client_type: Mapped[str | None] = mapped_column(String(32))
    # Canonical model names this client may call; ["*"] means any
    # verified-enabled model. Empty list means no models.
    allowed_models: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=20.0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class ApiRequestLog(Base):
    __tablename__ = "api_request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_key_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("client_keys.id"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(128))
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    tokens_cached: Mapped[int | None] = mapped_column(Integer)
    tokens_reasoning: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(64))
    upstream_request_id: Mapped[str | None] = mapped_column(String(128))
    # No prompt / request-body content is stored here by design.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    client_key_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("client_keys.id"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    tokens_cached: Mapped[int | None] = mapped_column(Integer)
    tokens_reasoning: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    # "exact" | "not_obtained" | "price_not_configured"
    cost_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    input_usd_per_1m: Mapped[float] = mapped_column(Float, nullable=False)
    output_usd_per_1m: Mapped[float] = mapped_column(Float, nullable=False)
    cached_input_usd_per_1m: Mapped[float | None] = mapped_column(Float)
    reasoning_usd_per_1m: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class ChatSession(Base):
    """A client-owned chat thread.

    NOTE: chat_messages stores message CONTENT by design — this is the
    sync store the user asked for (history sync across devices), and a
    session is deletable per chat. This is deliberately different from
    api_request_logs, which never store prompt content.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_key_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("client_keys.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class AdminAccount(Base):
    """Stage E: the single admin console account.

    The password is stored ONLY as an Argon2id hash. Plaintext is never
    stored or logged. Seeded once at startup from ADMIN_USERNAME +
    ADMIN_PASSWORD (see db.seed_admin); if the table is non-empty the
    env password is never re-hashed or overwritten.
    """

    __tablename__ = "admin_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class AdminSession(Base):
    """Stage E: an admin console login session.

    Only the SHA-256 digest of the opaque session token is stored; the
    raw token lives only in the HttpOnly pag_admin cookie. The CSRF
    token is stored in plaintext (double-submit pattern: it is not a
    credential on its own — it must match the session).
    """

    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_accounts.id"), nullable=False
    )
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class SystemSetting(Base):
    """Stage E: admin-persisted key/value settings (JSON values).

    Keys: "budget_global_daily_usd", "budget_global_monthly_usd",
    "retention_days". Env vars remain the defaults when no row exists.
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
