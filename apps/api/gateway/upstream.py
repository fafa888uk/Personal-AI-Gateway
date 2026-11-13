"""Upstream (OpenAI) forwarding helpers."""
from __future__ import annotations

import httpx

from .config import Settings

# Headers passed through from upstream responses (allowlist — never forward
# hop-by-hop or gateway-internal headers).
PASSTHROUGH_RESPONSE_HEADERS = {
    "openai-request-id",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
    "retry-after",
    "openai-processing-ms",
}

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def build_upstream_client(
    settings: Settings, transport: httpx.BaseTransport | None = None
) -> httpx.AsyncClient:
    headers = {"Accept": "application/json"}
    if settings.openai_api_key:
        headers["Authorization"] = f"Bearer {settings.openai_api_key}"
    return httpx.AsyncClient(
        base_url=settings.openai_base_url,
        timeout=httpx.Timeout(settings.upstream_timeout_s),
        headers=headers,
        transport=transport,
    )


def parse_retry_after(headers: httpx.Headers, attempt: int, max_s: float) -> float:
    """Retry-After (seconds) honoured, capped; else exponential backoff."""
    raw = headers.get("retry-after")
    if raw:
        try:
            return max(0.0, min(float(raw), max_s))
        except ValueError:
            pass
    return min(0.5 * (2**attempt), max_s)


def extract_usage_from_payload(payload: dict) -> dict | None:
    """Pull a usage dict out of a Responses or Chat Completions payload."""
    usage = payload.get("usage")
    if isinstance(usage, dict):
        return usage
    return None


def extract_usage_from_sse_line(line: bytes) -> dict | None:
    """Best-effort usage extraction from one SSE `data:` line."""
    try:
        text = line.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if not text.startswith("data:"):
        return None
    data = text[5:].strip()
    if not data or data == "[DONE]":
        return None
    import json

    try:
        payload = json.loads(data)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    # Responses: response.completed event carries full response incl. usage.
    if payload.get("type") == "response.completed":
        resp = payload.get("response") or {}
        if isinstance(resp, dict):
            return extract_usage_from_payload(resp)
    # Chat Completions streaming chunk with usage (stream_options.include_usage).
    usage = payload.get("usage")
    if isinstance(usage, dict):
        return usage
    return None
