"""Stage C (Flutter client) chat-history schema.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14

Portable SQLAlchemy types only — no SQLite-only SQL. Works on
PostgreSQL (production) and SQLite (local dev).

NOTE: chat_messages stores message content by design — that is the
sync store the user asked for, deletable per chat. api_request_logs
still never store prompt content.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_key_id", sa.Integer(), sa.ForeignKey("client_keys.id"), nullable=False),
        sa.Column("title", sa.String(256), nullable=False, server_default=""),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_sessions_client_key_id", "chat_sessions", ["client_key_id"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_sessions.id"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_client_key_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
