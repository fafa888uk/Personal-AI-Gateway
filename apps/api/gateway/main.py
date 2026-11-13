"""Personal AI Gateway — FastAPI app (Stage B).

Native OpenAI Responses + Chat Completions passthrough.

Verified-by-research endpoints (2026-11-14, official OpenAI API):
- POST /v1/responses/{id}/cancel — cancels a *background* response.
- POST /v1/responses/compact — proprietary server-side compaction Codex
  calls for long sessions; returns an opaque encrypted blob. Passthrough
  only: the gateway never inspects or fabricates the blob.
- DELETE /v1/responses/{id} — deletes a stored response.
All three are plain passthroughs to the fixed upstream base URL.

No other cancel/compress endpoints are implemented: nothing is guessed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import budgets as budget_mod
from .auth import (
    client_may_call_model,
    generate_client_key,
    hash_client_key,
    verify_admin_key,
    verify_client_key,
)
from .config import Settings, load_dotenv
from .db import init_db, list_verified_models, resolve_model
from .models import ApiRequestLog, AuditEvent, ClientKey, ModelRegistry, PricingRule, UsageRecord
from .upstream import (
    PASSTHROUGH_RESPONSE_HEADERS,
    RETRYABLE_STATUSES,
    build_upstream_client,
    extract_usage_from_payload,
    extract_usage_from_sse_line,
    parse_retry_after,
)

logger = logging.getLogger("gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

VERSION = "0.3.0"
MAX_RETRIES = 2  # initial attempt + 2 retries, only before streaming starts


# ---------------------------------------------------------------- errors
def gateway_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": "gateway_error", "code": code}},
    )


def passthrough_headers(upstream: httpx.Headers) -> dict[str, str]:
    out = {}
    for name in PASSTHROUGH_RESPONSE_HEADERS:
        if name in upstream:
            out[name] = upstream[name]
    return out


# ---------------------------------------------------------------- app factory
async def _send_with_timeout(client: httpx.AsyncClient, request: httpx.Request,
                             stream: bool, timeout_s: float) -> httpx.Response:
    """Send with a gateway-enforced timeout.

    httpx transport-level timeouts are not honoured by every transport
    (notably MockTransport in tests, and some proxies); enforcing it here
    with asyncio.wait_for makes timeout behaviour transport-independent.
    """

    async def _send() -> httpx.Response:
        return await client.send(request, stream=stream)

    try:
        return await asyncio.wait_for(_send(), timeout=timeout_s)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise httpx.ReadTimeout("upstream request timed out", request=request) from exc


def create_app(settings: Settings | None = None, transport: httpx.BaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.session_factory = init_db(settings)
        app.state.rate_windows: dict[int, deque] = {}
        app.state.semaphores: dict[int, asyncio.Semaphore] = {}
        yield

    app = FastAPI(title="Personal AI Gateway", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.transport = transport
    app.state.rate_windows = {}
    app.state.semaphores = {}

    @app.exception_handler(_Unauthorized)
    async def _unauthorized_handler(request: Request, exc: _Unauthorized):
        return gateway_error(401, "invalid_client_key", exc.message)

    @app.exception_handler(_Forbidden)
    async def _forbidden_handler(request: Request, exc: _Forbidden):
        return gateway_error(403, exc.code, exc.message)

    @app.exception_handler(_AdminNotConfigured)
    async def _admin_not_configured_handler(request: Request, exc: _AdminNotConfigured):
        return gateway_error(503, "admin_not_configured", "admin key is not configured on this server")

    # ------------------------------------------------------------ dependencies
    def get_db(request: Request):
        session = request.app.state.session_factory()
        try:
            yield session
        finally:
            session.close()

    def bearer_token(request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return None

    def require_admin(request: Request) -> None:
        if not settings.admin_key:
            raise _AdminNotConfigured()
        token = bearer_token(request)
        if not token or not verify_admin_key(token, settings.admin_key):
            raise _Unauthorized("invalid admin key")

    def require_client(request: Request, db: Session = Depends(get_db)) -> ClientKey:
        token = bearer_token(request)
        if not token:
            raise _Unauthorized("missing bearer client key")
        # The admin key must never double as a client key.
        if settings.admin_key and token == settings.admin_key:
            raise _Unauthorized("admin key must not be used as a client key")
        row = db.query(ClientKey).filter(ClientKey.key_hash == hash_client_key(token)).first()
        if row is None:
            raise _Unauthorized("invalid client key")
        if not row.enabled:
            raise _Forbidden("client_disabled", "client key is disabled")
        row.last_used_at = datetime.now(timezone.utc)
        db.commit()
        return row

    # ------------------------------------------------------------ helpers
    def check_rate_limit(client: ClientKey) -> bool:
        now = time.monotonic()
        window = app.state.rate_windows.setdefault(client.id, deque())
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= client.rate_limit_per_min:
            return False
        window.append(now)
        return True

    def get_semaphore(client_id: int, limit: int) -> asyncio.Semaphore:
        sem = app.state.semaphores.get(client_id)
        if sem is None:
            sem = asyncio.Semaphore(limit)
            app.state.semaphores[client_id] = sem
        return sem

    def record(
        trace_id: str,
        client_id: int | None,
        model: str | None,
        endpoint: str,
        status: int | None,
        latency_ms: int | None,
        usage: dict | None,
        error_type: str | None,
        upstream_request_id: str | None,
        reached_upstream: bool,
    ) -> None:
        """Persist request log + usage record. Never stores prompt content."""
        try:
            with app.state.session_factory() as session:
                session.add(
                    ApiRequestLog(
                        trace_id=trace_id,
                        client_key_id=client_id,
                        model=model,
                        endpoint=endpoint,
                        status_code=status,
                        latency_ms=latency_ms,
                        tokens_in=(usage or {}).get("input_tokens") or (usage or {}).get("prompt_tokens"),
                        tokens_out=(usage or {}).get("output_tokens") or (usage or {}).get("completion_tokens"),
                        tokens_cached=((usage or {}).get("input_tokens_details") or {}).get("cached_tokens"),
                        tokens_reasoning=((usage or {}).get("output_tokens_details") or {}).get("reasoning_tokens"),
                        error_type=error_type,
                        upstream_request_id=upstream_request_id,
                    )
                )
                if reached_upstream and model:
                    rule = (
                        session.query(PricingRule)
                        .filter(PricingRule.model == model)
                        .first()
                    )
                    cost, cost_status = budget_mod.compute_cost(usage, rule)
                    session.add(
                        UsageRecord(
                            trace_id=trace_id,
                            client_key_id=client_id,
                            model=model,
                            tokens_in=(usage or {}).get("input_tokens") or (usage or {}).get("prompt_tokens"),
                            tokens_out=(usage or {}).get("output_tokens") or (usage or {}).get("completion_tokens"),
                            tokens_cached=((usage or {}).get("input_tokens_details") or {}).get("cached_tokens"),
                            tokens_reasoning=((usage or {}).get("output_tokens_details") or {}).get("reasoning_tokens"),
                            cost_usd=cost,
                            cost_status=cost_status,
                        )
                    )
                session.commit()
        except Exception:
            logger.exception("failed to record request log trace=%s", trace_id)

    def audit(kind: str, detail: str) -> None:
        try:
            with app.state.session_factory() as session:
                session.add(AuditEvent(kind=kind, detail=detail))
                session.commit()
        except Exception:
            logger.exception("failed to record audit event %s", kind)

    # ------------------------------------------------------------ health
    @app.get("/api/health")
    def health():
        try:
            with app.state.session_factory() as session:
                session.execute(text("SELECT 1"))
            db_status = "ok"
        except Exception:
            db_status = "error"
        return {"status": "ok", "service": "personal-ai-gateway", "version": VERSION, "db": db_status}

    # ------------------------------------------------------------ app version
    @app.get("/api/v1/app/version")
    def app_version():
        """Public release info for clients' update checks.

        Server-side source only (APP_VERSION / APP_RELEASE_INFO_JSON env).
        Clients must never hardcode versions or embed a GitHub PAT.
        Unconfigured => honestly reports configured=false, never fake data.
        """
        info: dict = {}
        if settings.app_release_info_json:
            try:
                parsed = json.loads(settings.app_release_info_json)
                if isinstance(parsed, dict):
                    info = parsed
            except ValueError:
                info = {}
        platforms = info.get("platforms") if isinstance(info.get("platforms"), dict) else {}
        clean: dict[str, dict] = {}
        for name in ("ios", "windows", "macos", "web"):
            entry = platforms.get(name)
            if isinstance(entry, dict) and entry.get("version") and entry.get("download_url"):
                clean[name] = {
                    "version": str(entry["version"]),
                    "release_date": entry.get("release_date"),
                    "download_url": str(entry["download_url"]),
                    "sha256": entry.get("sha256"),
                    "release_notes": entry.get("release_notes"),
                }
        version = info.get("version") or settings.app_version or None
        if not version and not clean:
            return {"configured": False, "version": None, "platforms": {},
                    "note": "no release configured on this server"}
        return {"configured": True, "version": version,
                "gateway_version": VERSION, "platforms": clean}

    # ------------------------------------------------------------ /v1/models
    @app.get("/v1/models")
    def list_models(client: ClientKey = Depends(require_client), db: Session = Depends(get_db)):
        rows = list_verified_models(db)
        return {
            "object": "list",
            "data": [
                {
                    "id": r.canonical_name,
                    "object": "model",
                    "created": int(r.created_at.timestamp()),
                    "owned_by": "gateway",
                }
                for r in rows
            ],
        }

    # ------------------------------------------------------------ forwarding
    async def forward_model_call(
        request: Request,
        endpoint: str,
        upstream_path: str,
        kind: str,  # "responses" | "chat" | "compact"
        client: ClientKey,
        db: Session,
    ):
        trace_id = uuid.uuid4().hex
        started = time.monotonic()
        raw = await request.body()
        if len(raw) > settings.max_request_bytes:
            return gateway_error(413, "request_too_large", "request body exceeds the size limit")
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            return gateway_error(400, "invalid_request", "request body is not valid JSON")
        if not isinstance(body, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")

        model_name = body.get("model")
        canonical: str | None = None
        if kind in ("responses", "chat"):
            if not model_name or not isinstance(model_name, str):
                return gateway_error(400, "invalid_request", "field 'model' is required")
        if model_name:
            row = resolve_model(db, model_name)
            if row is None:
                return gateway_error(404, "model_not_found", f"unknown model: {model_name}")
            if not row.enabled or row.verification_status != "available":
                return gateway_error(
                    403,
                    "model_not_verified",
                    f"model {row.canonical_name} is not verified/enabled "
                    f"(status: {row.verification_status}); it cannot be called",
                )
            if not client_may_call_model(client, row.canonical_name):
                return gateway_error(
                    403, "model_not_allowed", f"client key may not call model {row.canonical_name}"
                )
            cap_field = {"responses": "cap_responses", "chat": "cap_chat", "compact": "cap_responses"}[kind]
            if not getattr(row, cap_field):
                return gateway_error(
                    400,
                    "model_incompatible",
                    f"model {row.canonical_name} does not support {kind}",
                )
            if body.get("stream") is True and not row.cap_streaming:
                return gateway_error(
                    400, "model_incompatible", f"model {row.canonical_name} does not support streaming"
                )
            canonical = row.canonical_name
            body["model"] = canonical

        if not check_rate_limit(client):
            record(trace_id, client.id, canonical, endpoint, 429,
                   int((time.monotonic() - started) * 1000), None, "rate_limited", None, False)
            return gateway_error(429, "rate_limited", "per-minute rate limit exceeded for this client key")

        blocked, reason = budget_mod.check_budgets(
            db, settings, client.id, client.monthly_budget_usd
        )
        if blocked:
            audit("budget_blocked", f"client={client.id} endpoint={endpoint} {reason}")
            record(trace_id, client.id, canonical, endpoint, 429,
                   int((time.monotonic() - started) * 1000), None, "budget_exceeded", None, False)
            return gateway_error(429, "budget_exceeded", reason)

        sem = get_semaphore(client.id, client.concurrency_limit)
        await sem.acquire()
        streaming = body.get("stream") is True
        upstream_client = build_upstream_client(settings, app.state.transport)
        headers = {"X-Gateway-Trace-Id": trace_id}
        if streaming:
            headers["Accept"] = "text/event-stream"

        try:
            resp: httpx.Response | None = None
            attempt = 0
            while True:
                try:
                    req = upstream_client.build_request(
                        "POST", upstream_path, json=body, headers=headers
                    )
                    resp = await _send_with_timeout(
                        upstream_client, req, streaming, settings.upstream_timeout_s
                    )
                except httpx.TimeoutException:
                    record(trace_id, client.id, canonical, endpoint, 504,
                           int((time.monotonic() - started) * 1000), None, "timeout", None, True)
                    return gateway_error(504, "gateway_timeout", "upstream request timed out")
                except httpx.ConnectError:
                    record(trace_id, client.id, canonical, endpoint, 502,
                           int((time.monotonic() - started) * 1000), None, "upstream_unreachable", None, True)
                    return gateway_error(502, "upstream_unreachable", "could not connect to upstream")
                except httpx.HTTPError as exc:
                    logger.warning("upstream transport error: %s", exc)
                    record(trace_id, client.id, canonical, endpoint, 502,
                           int((time.monotonic() - started) * 1000), None, "upstream_error", None, True)
                    return gateway_error(502, "upstream_error", "upstream request failed")
                # Retryable status, only before any byte is streamed to client.
                if resp.status_code in RETRYABLE_STATUSES and attempt < MAX_RETRIES:
                    await resp.aclose()
                    await asyncio.sleep(
                        parse_retry_after(resp.headers, attempt, settings.max_retry_after_s)
                    )
                    attempt += 1
                    continue
                break

            assert resp is not None
            upstream_req_id = resp.headers.get("openai-request-id")
            common_headers = {
                **passthrough_headers(resp.headers),
                "X-Gateway-Trace-Id": trace_id,
            }

            if not streaming:
                payload_bytes = await resp.aread()
                usage = None
                try:
                    payload = json.loads(payload_bytes) if payload_bytes else {}
                    if isinstance(payload, dict):
                        usage = extract_usage_from_payload(payload)
                except ValueError:
                    payload = None
                latency = int((time.monotonic() - started) * 1000)
                err = None
                if resp.status_code >= 400:
                    err = "upstream_error"
                record(trace_id, client.id, canonical, endpoint, resp.status_code,
                       latency, usage, err, upstream_req_id, True)
                await resp.aclose()
                await upstream_client.aclose()
                sem.release()
                media = resp.headers.get("content-type", "application/json")
                return Response(content=payload_bytes, status_code=resp.status_code,
                                media_type=media, headers=common_headers)

            # ---- streaming: yield raw SSE bytes verbatim, in order ----
            async def sse_generator():
                usage_holder: dict | None = None
                buffer = b""
                streamed_any = False
                try:
                    async for chunk in resp.aiter_bytes():
                        if await request.is_disconnected():
                            logger.info("client disconnected, aborting upstream trace=%s", trace_id)
                            break
                        streamed_any = True
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            found = extract_usage_from_sse_line(line)
                            if found:
                                usage_holder = found
                        yield chunk
                    if buffer:
                        found = extract_usage_from_sse_line(buffer)
                        if found:
                            usage_holder = found
                except asyncio.CancelledError:
                    logger.info("streaming cancelled, aborting upstream trace=%s", trace_id)
                    raise
                finally:
                    latency = int((time.monotonic() - started) * 1000)
                    record(trace_id, client.id, canonical, endpoint, resp.status_code,
                           latency, usage_holder, None, upstream_req_id, True)
                    try:
                        await resp.aclose()
                    except Exception:
                        pass
                    try:
                        await upstream_client.aclose()
                    except Exception:
                        pass
                    sem.release()

            return StreamingResponse(
                sse_generator(),
                status_code=resp.status_code,
                media_type="text/event-stream",
                headers={**common_headers, "Cache-Control": "no-cache",
                         "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            )
        except asyncio.CancelledError:
            try:
                await upstream_client.aclose()
            except Exception:
                pass
            sem.release()
            raise

    async def forward_simple(
        request: Request,
        endpoint: str,
        upstream_path: str,
        method: str,
        client: ClientKey,
    ):
        """Passthrough for GET/cancel/delete: no model, no budget, no body rewrite."""
        trace_id = uuid.uuid4().hex
        started = time.monotonic()
        if not check_rate_limit(client):
            return gateway_error(429, "rate_limited", "per-minute rate limit exceeded for this client key")
        upstream_client = build_upstream_client(settings, app.state.transport)
        try:
            body_bytes = await request.body() if method in ("POST",) else None
            req = upstream_client.build_request(
                method, upstream_path,
                content=body_bytes if body_bytes else None,
                headers={"X-Gateway-Trace-Id": trace_id,
                         "Content-Type": request.headers.get("content-type", "application/json")},
            )
            resp = await _send_with_timeout(
                upstream_client, req, False, settings.upstream_timeout_s
            )
            payload = resp.content
        except httpx.TimeoutException:
            return gateway_error(504, "gateway_timeout", "upstream request timed out")
        except httpx.HTTPError:
            return gateway_error(502, "upstream_error", "upstream request failed")
        finally:
            await upstream_client.aclose()
        latency = int((time.monotonic() - started) * 1000)
        record(trace_id, client.id, None, endpoint, resp.status_code, latency,
               None, "upstream_error" if resp.status_code >= 400 else None,
               resp.headers.get("openai-request-id"), True)
        return Response(content=payload, status_code=resp.status_code,
                        media_type=resp.headers.get("content-type", "application/json"),
                        headers={**passthrough_headers(resp.headers), "X-Gateway-Trace-Id": trace_id})

    @app.post("/v1/responses")
    async def create_response(request: Request, client: ClientKey = Depends(require_client),
                             db: Session = Depends(get_db)):
        return await forward_model_call(request, "POST /v1/responses", "/responses", "responses", client, db)

    @app.post("/v1/chat/completions")
    async def create_chat(request: Request, client: ClientKey = Depends(require_client),
                          db: Session = Depends(get_db)):
        return await forward_model_call(request, "POST /v1/chat/completions", "/chat/completions", "chat", client, db)

    @app.post("/v1/responses/compact")
    async def compact_response(request: Request, client: ClientKey = Depends(require_client),
                               db: Session = Depends(get_db)):
        # Codex long-session compaction. Passthrough only; the encrypted
        # blob is never inspected. Model in the body, if present, is resolved.
        return await forward_model_call(request, "POST /v1/responses/compact", "/responses/compact", "compact", client, db)

    @app.get("/v1/responses/{response_id}")
    async def get_response(response_id: str, request: Request,
                           client: ClientKey = Depends(require_client)):
        return await forward_simple(request, "GET /v1/responses/{id}",
                                    f"/responses/{response_id}", "GET", client)

    @app.post("/v1/responses/{response_id}/cancel")
    async def cancel_response(response_id: str, request: Request,
                              client: ClientKey = Depends(require_client)):
        return await forward_simple(request, "POST /v1/responses/{id}/cancel",
                                    f"/responses/{response_id}/cancel", "POST", client)

    @app.delete("/v1/responses/{response_id}")
    async def delete_response(response_id: str, request: Request,
                              client: ClientKey = Depends(require_client)):
        return await forward_simple(request, "DELETE /v1/responses/{id}",
                                    f"/responses/{response_id}", "DELETE", client)

    # ------------------------------------------------------------ admin
    @app.get("/admin/models")
    def admin_list_models(request: Request, db: Session = Depends(get_db)):
        require_admin(request)
        rows = db.query(ModelRegistry).order_by(ModelRegistry.sort_order).all()
        return {"models": [_model_view(r) for r in rows]}

    @app.post("/admin/models/{canonical}/verify")
    async def admin_verify_model(canonical: str, request: Request, db: Session = Depends(get_db)):
        require_admin(request)
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        mode = (payload or {}).get("mode", "real")
        row = db.query(ModelRegistry).filter(ModelRegistry.canonical_name == canonical).first()
        if row is None:
            return gateway_error(404, "model_not_found", f"unknown model: {canonical}")
        if mode == "mock":
            if not settings.allow_mock_verify:
                return gateway_error(
                    403, "mock_not_allowed",
                    "mock verification is a test-only path and is not enabled on this server",
                )
            method = "mock-test-only"
        elif mode == "real":
            if not settings.openai_api_key:
                return gateway_error(503, "no_upstream_key", "no real upstream API key is configured")
            method = "real"
        else:
            return gateway_error(400, "invalid_request", "mode must be 'real' or 'mock'")
        upstream_client = build_upstream_client(settings, app.state.transport)
        try:
            req = upstream_client.build_request(
                "POST", "/responses",
                json={"model": canonical, "input": "ping", "max_output_tokens": 16},
            )
            resp = await _send_with_timeout(
                upstream_client, req, False, settings.upstream_timeout_s
            )
            status = resp.status_code
            await resp.aread()
        except httpx.TimeoutException:
            status = 0
        except httpx.HTTPError:
            status = 0
        finally:
            await upstream_client.aclose()
        mapping = {200: "available", 401: "forbidden", 403: "forbidden",
                   404: "unavailable", 429: "rate_limited"}
        row.verification_status = mapping.get(status, "unavailable")
        row.last_verified_at = datetime.now(timezone.utc)
        row.verification_method = method
        row.last_error = None if status == 200 else f"verification request returned HTTP {status}"
        db.commit()
        audit("model_verified",
              f"model={canonical} status={row.verification_status} method={method} http={status}")
        return {"model": _model_view(row), "verification_http_status": status,
                "note": "Mock verification is NOT real verification." if method == "mock-test-only" else None}

    @app.post("/admin/client-keys")
    async def admin_create_client_key(request: Request, db: Session = Depends(get_db)):
        require_admin(request)
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        payload = payload or {}
        raw = generate_client_key()
        row = ClientKey(
            name=str(payload.get("name", "client")),
            key_hash=hash_client_key(raw),
            allowed_models=payload.get("allowed_models", ["*"]),
            rate_limit_per_min=int(payload.get("rate_limit_per_min", settings.default_rate_limit_per_min)),
            concurrency_limit=int(payload.get("concurrency_limit", settings.default_concurrency_limit)),
            monthly_budget_usd=float(payload.get("monthly_budget_usd", settings.budget_client_monthly_usd)),
            enabled=True,
        )
        db.add(row)
        db.commit()
        audit("client_key_created", f"client_key_id={row.id} name={row.name}")
        # Raw key is returned exactly once, never stored.
        return {"id": row.id, "name": row.name, "key": raw,
                "warning": "Store this key now — it will never be shown again."}

    @app.get("/admin/budgets")
    def admin_budgets(request: Request, db: Session = Depends(get_db)):
        require_admin(request)
        return budget_mod.budget_status(db, settings)

    return app


def _model_view(r: ModelRegistry) -> dict:
    return {
        "canonical_name": r.canonical_name,
        "aliases": r.aliases or [],
        "enabled": r.enabled,
        "is_default": r.is_default,
        "sort_order": r.sort_order,
        "pinned_group": r.pinned_group,
        "capabilities": {
            "responses": r.cap_responses, "chat": r.cap_chat,
            "streaming": r.cap_streaming, "tools": r.cap_tools, "image": r.cap_image,
        },
        "verification_status": r.verification_status,
        "last_verified_at": r.last_verified_at.isoformat() if r.last_verified_at else None,
        "verification_method": r.verification_method,
        "last_error": r.last_error,
    }


class _Unauthorized(Exception):
    def __init__(self, message: str):
        self.message = message


class _Forbidden(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message


class _AdminNotConfigured(Exception):
    pass


def main() -> None:
    import os
    import uvicorn

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    load_dotenv(".env")
    settings = Settings.from_env()
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
