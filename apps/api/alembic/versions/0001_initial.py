"""Stage B initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-11-14

Portable SQLAlchemy types only — no SQLite-only SQL. Works on
PostgreSQL (production) and SQLite (local dev).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_name", sa.String(128), nullable=False, unique=True),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pinned_group", sa.String(128), nullable=True),
        sa.Column("cap_responses", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cap_chat", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cap_streaming", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cap_tools", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cap_image", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_method", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "client_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("allowed_models", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("rate_limit_per_min", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("monthly_budget_usd", sa.Float(), nullable=False, server_default="20"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "api_request_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("client_key_id", sa.Integer(), sa.ForeignKey("client_keys.id"), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("tokens_cached", sa.Integer(), nullable=True),
        sa.Column("tokens_reasoning", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(64), nullable=True),
        sa.Column("upstream_request_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_request_logs_trace_id", "api_request_logs", ["trace_id"])
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("client_key_id", sa.Integer(), sa.ForeignKey("client_keys.id"), nullable=True),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("tokens_cached", sa.Integer(), nullable=True),
        sa.Column("tokens_reasoning", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("cost_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_records_trace_id", "usage_records", ["trace_id"])
    op.create_table(
        "pricing_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model", sa.String(128), nullable=False, unique=True),
        sa.Column("input_usd_per_1m", sa.Float(), nullable=False),
        sa.Column("output_usd_per_1m", sa.Float(), nullable=False),
        sa.Column("cached_input_usd_per_1m", sa.Float(), nullable=True),
        sa.Column("reasoning_usd_per_1m", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("pricing_rules")
    op.drop_index("ix_usage_records_trace_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index("ix_api_request_logs_trace_id", table_name="api_request_logs")
    op.drop_table("api_request_logs")
    op.drop_table("client_keys")
    op.drop_table("model_registry")
