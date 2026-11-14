"""Budget accounting — hard stops, never soft warnings.

Costs come only from real upstream usage + configured pricing rules.
If upstream returns no usage, cost is "not_obtained"; if no price is
configured for the model, cost is "price_not_configured". Neither is
ever presented as an exact cost, and unknown cost never counts toward
a budget (it cannot — there is no number to count). Once pricing is
configured, spend is exact and budgets enforce as hard stops.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import Settings
from .models import PricingRule, SystemSetting, UsageRecord


def resolve_global_budgets(
    session: Session, settings: Settings
) -> tuple[float, float]:
    """Effective global budget limits: persisted SystemSetting wins,
    env Settings are the default/fallback.

    A stored value that is missing, not a number, or negative is ignored
    and the env default is used — a bad row can never disable the hard
    stop or turn the limit negative.
    """
    daily = settings.budget_global_daily_usd
    monthly = settings.budget_global_monthly_usd
    try:
        rows = (
            session.query(SystemSetting)
            .filter(
                SystemSetting.key.in_(
                    ["budget_global_daily_usd", "budget_global_monthly_usd"]
                )
            )
            .all()
        )
    except Exception:
        return daily, monthly
    for row in rows:
        try:
            value = float(row.value)
        except (TypeError, ValueError):
            continue
        if value < 0:
            continue
        if row.key == "budget_global_daily_usd":
            daily = value
        elif row.key == "budget_global_monthly_usd":
            monthly = value
    return daily, monthly


def compute_cost(
    usage: dict | None, rule: PricingRule | None
) -> tuple[float | None, str]:
    """Return (cost_usd, cost_status)."""
    if not usage:
        return None, "not_obtained"
    if rule is None:
        return None, "price_not_configured"
    tokens_in = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    tokens_out = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    cached = 0
    reasoning = 0
    details = usage.get("input_tokens_details") or {}
    if isinstance(details, dict):
        cached = details.get("cached_tokens") or 0
    out_details = usage.get("output_tokens_details") or {}
    if isinstance(out_details, dict):
        reasoning = out_details.get("reasoning_tokens") or 0
    # Cached input is billed at the cached rate when configured, else input rate.
    cached_rate = (
        rule.cached_input_usd_per_1m
        if rule.cached_input_usd_per_1m is not None
        else rule.input_usd_per_1m
    )
    reasoning_rate = (
        rule.reasoning_usd_per_1m
        if rule.reasoning_usd_per_1m is not None
        else rule.output_usd_per_1m
    )
    cost = (
        Decimal(str(max(tokens_in - cached, 0))) * Decimal(str(rule.input_usd_per_1m))
        + Decimal(str(cached)) * Decimal(str(cached_rate))
        + Decimal(str(max(tokens_out - reasoning, 0)))
        * Decimal(str(rule.output_usd_per_1m))
        + Decimal(str(reasoning)) * Decimal(str(reasoning_rate))
    ) / Decimal(1_000_000)
    return float(cost), "exact"


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def spend_since(
    session: Session,
    start: datetime,
    client_key_id: int | None = None,
) -> float:
    """Exact-cost spend (cost_status='exact') since `start`."""
    q = session.query(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).filter(
        UsageRecord.created_at >= start,
        UsageRecord.cost_status == "exact",
    )
    if client_key_id is not None:
        q = q.filter(UsageRecord.client_key_id == client_key_id)
    return float(q.scalar() or 0.0)


def check_budgets(
    session: Session, settings: Settings, client_key_id: int, client_monthly_usd: float
) -> tuple[bool, str]:
    """Return (blocked, reason). Blocked means reject the new request.

    Global limits come from resolve_global_budgets: the admin-persisted
    SystemSetting values when present, env Settings as default/fallback.
    Per-client monthly limit stays on the client key row.
    """
    now = datetime.now(timezone.utc)
    daily_limit, monthly_limit = resolve_global_budgets(session, settings)
    daily = spend_since(session, _day_start(now))
    if daily >= daily_limit:
        return True, (
            f"global daily budget exceeded: spent ${daily:.4f} of "
            f"${daily_limit:.2f}"
        )
    monthly = spend_since(session, _month_start(now))
    if monthly >= monthly_limit:
        return True, (
            f"global monthly budget exceeded: spent ${monthly:.4f} of "
            f"${monthly_limit:.2f}"
        )
    client_monthly = spend_since(session, _month_start(now), client_key_id)
    if client_monthly >= client_monthly_usd:
        return True, (
            f"client monthly budget exceeded: spent ${client_monthly:.4f} of "
            f"${client_monthly_usd:.2f}"
        )
    return False, ""


def budget_status(session: Session, settings: Settings) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "global_daily": {
            "limit_usd": settings.budget_global_daily_usd,
            "spent_usd": spend_since(session, _day_start(now)),
        },
        "global_monthly": {
            "limit_usd": settings.budget_global_monthly_usd,
            "spent_usd": spend_since(session, _month_start(now)),
        },
        "note": (
            "Spend counts only exact costs (real upstream usage + configured "
            "pricing). Usage without a price, or calls without usage, are "
            "recorded as price_not_configured / not_obtained and do not "
            "count toward budgets."
        ),
    }
