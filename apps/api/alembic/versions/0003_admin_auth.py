"""Stage E admin console schema: admin accounts/sessions + system settings.

Revision ID: 0003_admin_auth
Revises: 0002
Create Date: 2026-11-14

Portable SQLAlchemy types only — no SQLite-only SQL. Works on
PostgreSQL (production) and SQLite (local dev).

- admin_accounts: single admin console account; password stored ONLY as
  an Argon2id hash (seeded at startup from ADMIN_USERNAME/ADMIN_PASSWORD).
- admin_sessions: opaque session tokens stored ONLY as SHA-256 digests,
  plus the double-submit CSRF token.
- system_settings: admin-persisted key/value (JSON) settings.
- client_keys gains client_type ("web" | "codex" | "vscode" | "other")
  and key_prefix (display-only first chars of the raw key at creation).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_admin_auth"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("admin_accounts.id"), nullable=False),
        sa.Column("session_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_sessions_account_id", "admin_sessions", ["account_id"])
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("client_keys", sa.Column("client_type", sa.String(32), nullable=True))
    op.add_column("client_keys", sa.Column("key_prefix", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("client_keys", "key_prefix")
    op.drop_column("client_keys", "client_type")
    op.drop_table("system_settings")
    op.drop_index("ix_admin_sessions_account_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_table("admin_accounts")
