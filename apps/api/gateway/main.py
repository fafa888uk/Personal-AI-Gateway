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
import hmac
import json
import logging
import math
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from . import backup as backup_mod
from . import budgets as budget_mod
from .auth import (
    client_may_call_model,
    generate_client_key,
    generate_csrf_token,
    generate_session_token,
    hash_admin_password,
    hash_client_key,
    hash_session_token,
    verify_admin_key,
    verify_admin_password,
    verify_client_key,
)
from .config import Settings, load_dotenv
from .db import init_db, list_verified_models, resolve_model
from .logsafe import configure_logging, log_file_from_env
from .models import (
    AdminAccount,
    AdminSession,
    ApiRequestLog,
    AuditEvent,
    ChatMessage,
    ChatSession,
    ClientKey,
    ModelRegistry,
    PricingRule,
    SystemSetting,
    UsageRecord,
)
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
# Stage F: every record the gateway logger emits passes the redacting
# filter; when GATEWAY_LOG_FILE is set, a rotating file handler is
# added (stdout behaviour is unchanged otherwise).
configure_logging(logger, log_file_from_env())

# Release version, unified at v0.1.2 (see ARCHITECTURE.md §14: the release
# tag is the single version source). Returned by /api/health ("version")
# and by GET /api/v1/app/version ("gateway_version").
VERSION = "0.1.2"
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
        app.state.login_attempts: dict[tuple[str, str], deque] = {}
        yield

    app = FastAPI(title="Personal AI Gateway", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.transport = transport
    app.state.rate_windows = {}
    app.state.semaphores = {}
    app.state.login_attempts = {}

    @app.exception_handler(_Unauthorized)
    async def _unauthorized_handler(request: Request, exc: _Unauthorized):
        return gateway_error(401, "invalid_client_key", exc.message)

    @app.exception_handler(_AdminUnauthorized)
    async def _admin_unauthorized_handler(request: Request, exc: _AdminUnauthorized):
        return gateway_error(401, "admin_unauthorized", exc.message)

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
    def _version_payload() -> dict:
        """Release info for clients' update checks (shared by the public
        version endpoint and the admin settings endpoint).

        Server-side source only (APP_VERSION / APP_RELEASE_INFO_JSON env).
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

    @app.get("/api/v1/app/version")
    def app_version():
        """Public release info for clients' update checks.

        Server-side source only (APP_VERSION / APP_RELEASE_INFO_JSON env).
        Clients must never hardcode versions or embed a GitHub PAT.
        Unconfigured => honestly reports configured=false, never fake data.
        """
        return _version_payload()

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

    # ------------------------------------------------------------ chat history
    # Server-side sync store: a client key sees ONLY its own sessions.
    # A session owned by another key returns 404, never 403 (no existence leak).
    # Message content is stored here by design (see models.ChatSession);
    # api_request_logs still never store prompt content.
    def _session_view(s: ChatSession) -> dict:
        return {
            "id": s.id,
            "title": s.title,
            "model": s.model,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }

    def _message_view(m: ChatMessage) -> dict:
        return {
            "id": m.id,
            "session_id": m.session_id,
            "role": m.role,
            "content": m.content,
            "model": m.model,
            "tokens_in": m.tokens_in,
            "tokens_out": m.tokens_out,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }

    def _own_session(db: Session, client: ClientKey, session_id: int) -> ChatSession | None:
        return (
            db.query(ChatSession)
            .filter(ChatSession.id == session_id, ChatSession.client_key_id == client.id)
            .first()
        )

    @app.post("/api/v1/chats", status_code=201)
    async def create_chat_session(request: Request, client: ClientKey = Depends(require_client),
                                  db: Session = Depends(get_db)):
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")
        title = payload.get("title")
        model = payload.get("model")
        if title is not None and not isinstance(title, str):
            return gateway_error(400, "invalid_request", "field 'title' must be a string")
        if model is not None and not isinstance(model, str):
            return gateway_error(400, "invalid_request", "field 'model' must be a string")
        row = ChatSession(client_key_id=client.id, title=(title or "")[:256],
                          model=model)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _session_view(row)

    @app.get("/api/v1/chats")
    def list_chat_sessions(client: ClientKey = Depends(require_client),
                           db: Session = Depends(get_db)):
        rows = (
            db.query(ChatSession)
            .filter(ChatSession.client_key_id == client.id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            .all()
        )
        return {"sessions": [_session_view(r) for r in rows]}

    @app.get("/api/v1/chats/{session_id}")
    def get_chat_session(session_id: int, client: ClientKey = Depends(require_client),
                         db: Session = Depends(get_db)):
        row = _own_session(db, client, session_id)
        if row is None:
            return gateway_error(404, "chat_not_found", "chat session not found")
        return _session_view(row)

    @app.patch("/api/v1/chats/{session_id}")
    async def update_chat_session(session_id: int, request: Request,
                                  client: ClientKey = Depends(require_client),
                                  db: Session = Depends(get_db)):
        row = _own_session(db, client, session_id)
        if row is None:
            return gateway_error(404, "chat_not_found", "chat session not found")
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")
        if "title" in payload:
            if not isinstance(payload["title"], str):
                return gateway_error(400, "invalid_request", "field 'title' must be a string")
            row.title = payload["title"][:256]
        if "model" in payload:
            if payload["model"] is not None and not isinstance(payload["model"], str):
                return gateway_error(400, "invalid_request", "field 'model' must be a string")
            row.model = payload["model"]
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return _session_view(row)

    @app.delete("/api/v1/chats/{session_id}")
    def delete_chat_session(session_id: int, client: ClientKey = Depends(require_client),
                            db: Session = Depends(get_db)):
        row = _own_session(db, client, session_id)
        if row is None:
            return gateway_error(404, "chat_not_found", "chat session not found")
        db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
        db.delete(row)
        db.commit()
        return {"deleted": True, "id": session_id}

    @app.get("/api/v1/chats/{session_id}/messages")
    def list_chat_messages(session_id: int, client: ClientKey = Depends(require_client),
                           db: Session = Depends(get_db)):
        row = _own_session(db, client, session_id)
        if row is None:
            return gateway_error(404, "chat_not_found", "chat session not found")
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .all()
        )
        return {"messages": [_message_view(m) for m in rows]}

    @app.post("/api/v1/chats/{session_id}/messages", status_code=201)
    async def add_chat_message(session_id: int, request: Request,
                               client: ClientKey = Depends(require_client),
                               db: Session = Depends(get_db)):
        row = _own_session(db, client, session_id)
        if row is None:
            return gateway_error(404, "chat_not_found", "chat session not found")
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")
        role = payload.get("role")
        content = payload.get("content")
        if role not in ("user", "assistant", "system"):
            return gateway_error(400, "invalid_request", "field 'role' must be user, assistant or system")
        if not isinstance(content, str) or not content:
            return gateway_error(400, "invalid_request", "field 'content' must be a non-empty string")
        model = payload.get("model")
        tokens_in = payload.get("tokens_in")
        tokens_out = payload.get("tokens_out")
        if model is not None and not isinstance(model, str):
            return gateway_error(400, "invalid_request", "field 'model' must be a string")
        for name, val in (("tokens_in", tokens_in), ("tokens_out", tokens_out)):
            if val is not None and (not isinstance(val, int) or val < 0):
                return gateway_error(400, "invalid_request", f"field '{name}' must be a non-negative integer")
        msg = ChatMessage(session_id=session_id, role=role, content=content,
                          model=model, tokens_in=tokens_in, tokens_out=tokens_out)
        db.add(msg)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(msg)
        return _message_view(msg)

    # ------------------------------------------------------------ usage summary
    @app.get("/api/v1/usage/summary")
    def usage_summary(period: str = "today", client: ClientKey = Depends(require_client),
                      db: Session = Depends(get_db)):
        if period not in ("today", "month"):
            return gateway_error(400, "invalid_request", "period must be 'today' or 'month'")
        now = datetime.now(timezone.utc)
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        requests = (
            db.query(func.count(ApiRequestLog.id))
            .filter(ApiRequestLog.client_key_id == client.id,
                    ApiRequestLog.created_at >= start)
            .scalar() or 0
        )
        usage_rows = (
            db.query(UsageRecord)
            .filter(UsageRecord.client_key_id == client.id,
                    UsageRecord.created_at >= start)
            .all()
        )
        tokens_in = sum(r.tokens_in or 0 for r in usage_rows)
        tokens_out = sum(r.tokens_out or 0 for r in usage_rows)
        cost = sum(r.cost_usd or 0.0 for r in usage_rows if r.cost_status == "exact")
        statuses = {r.cost_status for r in usage_rows}
        if "price_not_configured" in statuses:
            cost_status = "price_not_configured"
        elif "not_obtained" in statuses:
            cost_status = "not_obtained"
        else:
            cost_status = "ok"
        by_model: dict[str, dict] = {}
        for r in usage_rows:
            entry = by_model.setdefault(r.model, {"model": r.model, "requests": 0,
                                                  "tokens_in": 0, "tokens_out": 0,
                                                  "cost_usd": 0.0})
            entry["requests"] += 1
            entry["tokens_in"] += r.tokens_in or 0
            entry["tokens_out"] += r.tokens_out or 0
            if r.cost_status == "exact":
                entry["cost_usd"] += r.cost_usd or 0.0
        return {
            "period": period,
            "requests": int(requests),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost, 6),
            "cost_status": cost_status,
            "by_model": sorted(by_model.values(), key=lambda e: e["model"]),
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

    # Shared model verification (used by legacy /admin/* and new
    # /api/v1/admin/*). Returns (error_response, row, http_status, method);
    # exactly one of error_response / row is set. verification_method is
    # "real" only for a real upstream call, "mock-test-only" for the mock
    # path. This sends a real request and may incur API cost in real mode.
    async def _verify_model(canonical: str, db: Session, mode: str):
        row = db.query(ModelRegistry).filter(ModelRegistry.canonical_name == canonical).first()
        if row is None:
            return gateway_error(404, "model_not_found", f"unknown model: {canonical}"), None, None, None
        if mode == "mock":
            if not settings.allow_mock_verify:
                return gateway_error(
                    403, "mock_not_allowed",
                    "mock verification is a test-only path and is not enabled on this server",
                ), None, None, None
            method = "mock-test-only"
        elif mode == "real":
            if not settings.openai_api_key:
                return gateway_error(503, "no_upstream_key", "no real upstream API key is configured"), None, None, None
            method = "real"
        else:
            return gateway_error(400, "invalid_request", "mode must be 'real' or 'mock'"), None, None, None
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
        return None, row, status, method

    @app.post("/admin/models/{canonical}/verify")
    async def admin_verify_model(canonical: str, request: Request, db: Session = Depends(get_db)):
        require_admin(request)
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        mode = (payload or {}).get("mode", "real")
        err, row, status, method = await _verify_model(canonical, db, mode)
        if err is not None:
            return err
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
            key_prefix=raw[:12],
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

    # ================================================================
    # Stage E — admin console API (/api/v1/admin/*)
    #
    # Cookie-session auth (AdminAccount/AdminSession), NOT the bearer
    # admin key: the bearer key keeps working only on legacy /admin/*.
    # Mutating endpoints additionally require double-submit CSRF.
    # Nothing here ever logs or returns passwords, raw keys or tokens.
    # ================================================================
    ADMIN_SESSION_COOKIE = "pag_admin"
    ADMIN_CSRF_COOKIE = "pag_csrf"
    LOGIN_MAX_FAILURES = 5
    LOGIN_WINDOW_S = 15 * 60  # 15 minutes
    VALID_CLIENT_TYPES = {"web", "codex", "vscode", "other"}
    DEFAULT_RETENTION_DAYS = 90

    def _now_aware() -> datetime:
        return datetime.now(timezone.utc)

    def _as_aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def _iso(value: datetime | None) -> str | None:
        value = _as_aware(value)
        return value.isoformat() if value else None

    def _session_max_age_s() -> int:
        return max(60, int(settings.admin_session_hours * 3600))

    def _set_session_cookie(resp: JSONResponse, raw_token: str) -> None:
        resp.set_cookie(
            ADMIN_SESSION_COOKIE, raw_token, max_age=_session_max_age_s(),
            path="/", httponly=True, samesite="lax",
            secure=settings.session_cookie_secure,
        )

    def _set_csrf_cookie(resp: JSONResponse, csrf_token: str, max_age: int | None = None) -> None:
        resp.set_cookie(
            ADMIN_CSRF_COOKIE, csrf_token,
            max_age=max_age if max_age is not None else _session_max_age_s(),
            path="/", httponly=False, samesite="lax",
            secure=settings.session_cookie_secure,
        )

    def _admin_session(request: Request, db: Session):
        """Return (account, session_row) for a valid pag_admin cookie, else (None, None)."""
        raw = request.cookies.get(ADMIN_SESSION_COOKIE)
        if not raw:
            return None, None
        row = (
            db.query(AdminSession)
            .filter(AdminSession.session_token_hash == hash_session_token(raw))
            .first()
        )
        if row is None:
            return None, None
        expires = _as_aware(row.expires_at)
        if expires is None or expires <= _now_aware():
            db.delete(row)
            db.commit()
            return None, None
        account = db.query(AdminAccount).filter(AdminAccount.id == row.account_id).first()
        if account is None:
            return None, None
        row.last_seen_at = _now_aware()
        db.commit()
        return account, row

    def require_admin_session(request: Request, db: Session):
        account, session_row = _admin_session(request, db)
        if account is None or session_row is None:
            raise _AdminUnauthorized("admin session required")
        return account, session_row

    def require_csrf(request: Request, session_row: AdminSession) -> None:
        header = request.headers.get("x-csrf-token", "")
        cookie = request.cookies.get(ADMIN_CSRF_COOKIE, "")
        if (
            not header
            or not hmac.compare_digest(header, session_row.csrf_token)
            or not hmac.compare_digest(cookie, session_row.csrf_token)
        ):
            raise _Forbidden("csrf_invalid", "missing or invalid CSRF token")

    # ---- login rate limiting (in-memory, per client IP + username) ----
    def _login_key(request: Request, username: str) -> tuple[str, str]:
        ip = request.client.host if request.client else "unknown"
        return (ip, username)

    def _prune_login_attempts(key: tuple[str, str]) -> deque:
        window = app.state.login_attempts.setdefault(key, deque())
        cutoff = time.monotonic() - LOGIN_WINDOW_S
        while window and window[0] <= cutoff:
            window.popleft()
        return window

    def _login_blocked(key: tuple[str, str]) -> bool:
        return len(_prune_login_attempts(key)) >= LOGIN_MAX_FAILURES

    def _record_login_failure(key: tuple[str, str]) -> None:
        _prune_login_attempts(key).append(time.monotonic())

    def _clear_login_failures(key: tuple[str, str]) -> None:
        app.state.login_attempts.pop(key, None)

    # ---- persisted settings (SystemSetting overrides env defaults) ----
    def _get_setting(db: Session, key: str, default):
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        return row.value if row is not None else default

    def _set_setting(db: Session, key: str, value) -> None:
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row is None:
            db.add(SystemSetting(key=key, value=value))
        else:
            row.value = value

    def _effective_budgets(db: Session) -> tuple[float, float]:
        """Effective budgets for the admin API: persisted SystemSetting
        wins, env Settings are the default/fallback.

        Mirrors budgets.resolve_global_budgets: a stored value that is
        not a number or is negative is ignored and the env default is
        used. A bad row must never crash the admin API — before this
        fix an unguarded float() here turned GET /api/v1/admin/settings
        (and /usage, and backup creation) into a 500 while the /v1/*
        enforcement path already fell back correctly.
        """
        daily = settings.budget_global_daily_usd
        monthly = settings.budget_global_monthly_usd
        for key in ("budget_global_daily_usd", "budget_global_monthly_usd"):
            default = daily if key == "budget_global_daily_usd" else monthly
            try:
                value = float(_get_setting(db, key, default))
            except (TypeError, ValueError):
                continue
            if value < 0:
                continue
            if key == "budget_global_daily_usd":
                daily = value
            else:
                monthly = value
        return daily, monthly

    def _effective_retention_days(db: Session) -> int:
        try:
            value = int(_get_setting(db, "retention_days", DEFAULT_RETENTION_DAYS))
        except (TypeError, ValueError):
            return DEFAULT_RETENTION_DAYS
        return value if value >= 1 else DEFAULT_RETENTION_DAYS

    def _client_key_view(r: ClientKey) -> dict:
        prefix = r.key_prefix or (r.key_hash[:8] if r.key_hash else None)
        return {
            "id": r.id,
            "name": r.name,
            "key_prefix": prefix,
            "type": r.client_type,
            "client_type": r.client_type,
            "allowed_models": r.allowed_models or [],
            "rate_limit_per_min": r.rate_limit_per_min,
            "concurrency_limit": r.concurrency_limit,
            "monthly_budget_usd": r.monthly_budget_usd,
            "enabled": r.enabled,
            "last_used_at": _iso(r.last_used_at),
            "last_error": r.last_error,
            "created_at": _iso(r.created_at),
        }

    def _pricing_view(r: PricingRule) -> dict:
        return {
            "model": r.model,
            "input_usd_per_1m": r.input_usd_per_1m,
            "output_usd_per_1m": r.output_usd_per_1m,
            "cached_input_usd_per_1m": r.cached_input_usd_per_1m,
            "reasoning_usd_per_1m": r.reasoning_usd_per_1m,
            "updated_at": _iso(r.updated_at),
        }

    def _settings_payload(db: Session) -> dict:
        daily, monthly = _effective_budgets(db)
        rules = db.query(PricingRule).order_by(PricingRule.model).all()
        return {
            "budgets": {
                "global_daily_usd": daily,
                "global_monthly_usd": monthly,
            },
            "pricing_rules": [_pricing_view(r) for r in rules],
            "retention_days": _effective_retention_days(db),
            "version": _version_payload(),
        }

    def _percentile(sorted_vals: list[int], pct: float) -> int | None:
        if not sorted_vals:
            return None
        idx = max(0, math.ceil(pct / 100.0 * len(sorted_vals)) - 1)
        return sorted_vals[idx]

    def _is_number(value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _is_int(value) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    # ---- admin auth ----
    @app.post("/api/v1/admin/login")
    async def admin_login(request: Request, db: Session = Depends(get_db)):
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")
        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
            return gateway_error(400, "invalid_request", "username and password are required")
        if db.query(AdminAccount).count() == 0:
            # No admin account seeded (ADMIN_PASSWORD was absent at startup).
            return gateway_error(503, "admin_not_configured", "admin login is not configured on this server")
        key = _login_key(request, username)
        if _login_blocked(key):
            return gateway_error(429, "rate_limited", "too many failed login attempts; try again later")
        account = db.query(AdminAccount).filter(AdminAccount.username == username).first()
        if account is None or not verify_admin_password(password, account.password_hash):
            _record_login_failure(key)
            # Audit the failure (username + client IP only — never the
            # password). At most 5 such rows per (IP, username) per
            # 15-minute window: further attempts hit the 429 path, which
            # deliberately writes no audit row (unbounded by design).
            audit("admin_login_failed", f"username={username} ip={key[0]}")
            # Generic message: never reveal whether the username exists.
            return gateway_error(401, "invalid_admin_credentials", "invalid username or password")
        _clear_login_failures(key)
        raw_token = generate_session_token()
        csrf_token = generate_csrf_token()
        now = _now_aware()
        db.add(AdminSession(
            account_id=account.id,
            session_token_hash=hash_session_token(raw_token),
            csrf_token=csrf_token,
            expires_at=now + timedelta(hours=settings.admin_session_hours),
            created_at=now,
            last_seen_at=now,
        ))
        db.commit()
        audit("admin_login", f"username={account.username}")
        resp = JSONResponse(content={"ok": True, "username": account.username})
        _set_session_cookie(resp, raw_token)
        _set_csrf_cookie(resp, csrf_token)
        return resp

    @app.post("/api/v1/admin/logout")
    def admin_logout(request: Request, db: Session = Depends(get_db)):
        account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        db.delete(session_row)
        db.commit()
        audit("admin_logout", f"username={account.username}")
        resp = JSONResponse(content={"ok": True})
        resp.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
        resp.delete_cookie(ADMIN_CSRF_COOKIE, path="/")
        return resp

    # ---- Stage F: admin credential rotation ----
    @app.post("/api/v1/admin/change-password")
    async def admin_change_password(request: Request, db: Session = Depends(get_db)):
        """Rotate the single admin password (session + CSRF required).

        Verifies the current password, stores only the new Argon2id
        hash, and revokes EVERY session including the caller's — the
        admin must log in again with the new password. This is the
        rotation path for the admin credential; the env ADMIN_PASSWORD
        is only a first-boot seed and never overwrites an existing
        account (see db.seed_admin).
        """
        account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")
        current = payload.get("current_password")
        new = payload.get("new_password")
        if not isinstance(current, str) or not current or not isinstance(new, str) or not new:
            return gateway_error(400, "invalid_request", "current_password and new_password are required")
        if not verify_admin_password(current, account.password_hash):
            return gateway_error(401, "invalid_admin_credentials", "current password is incorrect")
        if len(new) < 12:
            return gateway_error(400, "invalid_request", "new password must be at least 12 characters")
        if new == current:
            return gateway_error(400, "invalid_request", "new password must differ from the current password")
        account.password_hash = hash_admin_password(new)
        db.query(AdminSession).filter(AdminSession.account_id == account.id).delete()
        db.commit()
        audit("admin_password_changed", f"username={account.username} sessions_revoked=all")
        resp = JSONResponse(content={"ok": True})
        resp.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
        resp.delete_cookie(ADMIN_CSRF_COOKIE, path="/")
        return resp

    @app.post("/api/v1/admin/sessions/revoke-all")
    def admin_revoke_all_sessions(request: Request, db: Session = Depends(get_db)):
        """Revoke every admin session (session + CSRF required).

        The caller's session is revoked too: after this call the admin
        must log in again. Use after a suspected session leak, or
        together with a password change (change-password already does
        this on its own).
        """
        account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        count = (
            db.query(AdminSession)
            .filter(AdminSession.account_id == account.id)
            .count()
        )
        db.query(AdminSession).filter(AdminSession.account_id == account.id).delete()
        db.commit()
        audit("admin_sessions_revoked", f"username={account.username} revoked={count}")
        resp = JSONResponse(content={"ok": True, "revoked": count})
        resp.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
        resp.delete_cookie(ADMIN_CSRF_COOKIE, path="/")
        return resp

    @app.get("/api/v1/admin/me")
    def admin_me(request: Request, db: Session = Depends(get_db)):
        account, _session_row = require_admin_session(request, db)
        return {"authenticated": True, "username": account.username}

    @app.get("/api/v1/admin/csrf")
    def admin_csrf(request: Request, db: Session = Depends(get_db)):
        _account, session_row = require_admin_session(request, db)
        remaining = int((_as_aware(session_row.expires_at) - _now_aware()).total_seconds())
        resp = JSONResponse(content={"csrf_token": session_row.csrf_token})
        _set_csrf_cookie(resp, session_row.csrf_token, max_age=max(0, remaining))
        return resp

    # ---- admin models ----
    @app.get("/api/v1/admin/models")
    async def admin_v1_list_models(request: Request, db: Session = Depends(get_db)):
        require_admin_session(request, db)
        rows = db.query(ModelRegistry).order_by(ModelRegistry.sort_order).all()
        registry_names = {r.canonical_name for r in rows}
        upstream_names: set[str] = set()
        upstream_reachable = False
        try:
            upstream_client = build_upstream_client(settings, app.state.transport)
            try:
                req = upstream_client.build_request("GET", "/models")
                resp = await _send_with_timeout(
                    upstream_client, req, False, settings.upstream_timeout_s
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data") if isinstance(data, dict) else None
                    if isinstance(items, list):
                        upstream_names = {
                            str(item.get("id")) for item in items
                            if isinstance(item, dict) and item.get("id")
                        }
                        upstream_reachable = True
                await resp.aread()
            finally:
                await upstream_client.aclose()
        except Exception:
            logger.warning("admin model list: live upstream /v1/models fetch failed")
        models = []
        for r in rows:
            view = _model_view(r)
            view["in_upstream"] = r.canonical_name in upstream_names
            models.append(view)
        upstream_only = [
            {"id": name} for name in sorted(upstream_names - registry_names)
        ]
        return {"models": models, "upstream_only": upstream_only,
                "upstream_reachable": upstream_reachable}

    @app.patch("/api/v1/admin/models/{canonical}")
    async def admin_v1_patch_model(canonical: str, request: Request, db: Session = Depends(get_db)):
        _account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        row = db.query(ModelRegistry).filter(ModelRegistry.canonical_name == canonical).first()
        if row is None:
            return gateway_error(404, "model_not_found", f"unknown model: {canonical}")
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")
        bool_fields = ("enabled", "is_default", "cap_responses", "cap_chat",
                       "cap_streaming", "cap_tools", "cap_image")
        changed: list[str] = []
        for field in bool_fields:
            if field in payload:
                if not isinstance(payload[field], bool):
                    return gateway_error(400, "invalid_request", f"field '{field}' must be a boolean")
                setattr(row, field, payload[field])
                changed.append(field)
        if "aliases" in payload:
            if not isinstance(payload["aliases"], list) or not all(isinstance(a, str) for a in payload["aliases"]):
                return gateway_error(400, "invalid_request", "field 'aliases' must be a list of strings")
            row.aliases = payload["aliases"]
            changed.append("aliases")
        if "sort_order" in payload:
            if not _is_int(payload["sort_order"]):
                return gateway_error(400, "invalid_request", "field 'sort_order' must be an integer")
            row.sort_order = payload["sort_order"]
            changed.append("sort_order")
        if "pinned_group" in payload:
            if payload["pinned_group"] is not None and not isinstance(payload["pinned_group"], str):
                return gateway_error(400, "invalid_request", "field 'pinned_group' must be a string or null")
            row.pinned_group = payload["pinned_group"]
            changed.append("pinned_group")
        if row.is_default:
            # Exactly one default: setting one clears the others.
            db.query(ModelRegistry).filter(
                ModelRegistry.id != row.id, ModelRegistry.is_default.is_(True)
            ).update({"is_default": False})
        db.commit()
        db.refresh(row)
        audit("model_updated", f"model={canonical} fields={','.join(changed) or 'none'}")
        return _model_view(row)

    @app.post("/api/v1/admin/models/{canonical}/verify")
    async def admin_v1_verify_model(canonical: str, request: Request, db: Session = Depends(get_db)):
        _account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        mode = (payload or {}).get("mode", "real")
        err, row, status, method = await _verify_model(canonical, db, mode)
        if err is not None:
            return err
        return {
            "model": _model_view(row),
            "verification_http_status": status,
            "verification_method": method,
            "cost_warning": "this sends a real request and may incur API cost",
            "note": "Mock verification is NOT real verification." if method == "mock-test-only" else None,
        }

    # ---- admin client keys ----
    @app.get("/api/v1/admin/client-keys")
    def admin_v1_list_client_keys(request: Request, db: Session = Depends(get_db)):
        require_admin_session(request, db)
        rows = db.query(ClientKey).order_by(ClientKey.id).all()
        return {"client_keys": [_client_key_view(r) for r in rows]}

    @app.post("/api/v1/admin/client-keys")
    async def admin_v1_create_client_key(request: Request, db: Session = Depends(get_db)):
        _account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")
        name = payload.get("name", "client")
        if not isinstance(name, str) or not name:
            return gateway_error(400, "invalid_request", "field 'name' must be a non-empty string")
        client_type = payload.get("client_type")
        if client_type is not None and client_type not in VALID_CLIENT_TYPES:
            return gateway_error(400, "invalid_request",
                                 "field 'client_type' must be one of web, codex, vscode, other")
        allowed = payload.get("allowed_models", ["*"])
        if not isinstance(allowed, list) or not all(isinstance(m, str) for m in allowed):
            return gateway_error(400, "invalid_request", "field 'allowed_models' must be a list of strings")
        rate = payload.get("rate_limit_per_min", settings.default_rate_limit_per_min)
        concurrency = payload.get("concurrency_limit", settings.default_concurrency_limit)
        budget = payload.get("monthly_budget_usd", settings.budget_client_monthly_usd)
        if not _is_int(rate) or rate < 0:
            return gateway_error(400, "invalid_request", "field 'rate_limit_per_min' must be a non-negative integer")
        if not _is_int(concurrency) or concurrency < 0:
            return gateway_error(400, "invalid_request", "field 'concurrency_limit' must be a non-negative integer")
        if not _is_number(budget) or budget < 0:
            return gateway_error(400, "invalid_request", "field 'monthly_budget_usd' must be a non-negative number")
        raw = generate_client_key()
        row = ClientKey(
            name=name,
            key_hash=hash_client_key(raw),
            key_prefix=raw[:12],
            client_type=client_type,
            allowed_models=allowed,
            rate_limit_per_min=rate,
            concurrency_limit=concurrency,
            monthly_budget_usd=float(budget),
            enabled=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        audit("client_key_created", f"client_key_id={row.id} name={row.name} type={client_type}")
        view = _client_key_view(row)
        view["raw_key"] = raw
        view["warning"] = "Store this key now — it will never be shown again."
        return view

    @app.patch("/api/v1/admin/client-keys/{key_id}")
    async def admin_v1_patch_client_key(key_id: int, request: Request, db: Session = Depends(get_db)):
        _account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        row = db.query(ClientKey).filter(ClientKey.id == key_id).first()
        if row is None:
            return gateway_error(404, "client_key_not_found", f"unknown client key: {key_id}")
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")
        changed: list[str] = []
        if "name" in payload:
            if not isinstance(payload["name"], str) or not payload["name"]:
                return gateway_error(400, "invalid_request", "field 'name' must be a non-empty string")
            row.name = payload["name"]
            changed.append("name")
        if "client_type" in payload:
            if payload["client_type"] is not None and payload["client_type"] not in VALID_CLIENT_TYPES:
                return gateway_error(400, "invalid_request",
                                     "field 'client_type' must be one of web, codex, vscode, other")
            row.client_type = payload["client_type"]
            changed.append("client_type")
        if "allowed_models" in payload:
            if not isinstance(payload["allowed_models"], list) or not all(isinstance(m, str) for m in payload["allowed_models"]):
                return gateway_error(400, "invalid_request", "field 'allowed_models' must be a list of strings")
            row.allowed_models = payload["allowed_models"]
            changed.append("allowed_models")
        if "rate_limit_per_min" in payload:
            if not _is_int(payload["rate_limit_per_min"]) or payload["rate_limit_per_min"] < 0:
                return gateway_error(400, "invalid_request", "field 'rate_limit_per_min' must be a non-negative integer")
            row.rate_limit_per_min = payload["rate_limit_per_min"]
            changed.append("rate_limit_per_min")
        if "concurrency_limit" in payload:
            if not _is_int(payload["concurrency_limit"]) or payload["concurrency_limit"] < 0:
                return gateway_error(400, "invalid_request", "field 'concurrency_limit' must be a non-negative integer")
            row.concurrency_limit = payload["concurrency_limit"]
            changed.append("concurrency_limit")
        if "monthly_budget_usd" in payload:
            if not _is_number(payload["monthly_budget_usd"]) or payload["monthly_budget_usd"] < 0:
                return gateway_error(400, "invalid_request", "field 'monthly_budget_usd' must be a non-negative number")
            row.monthly_budget_usd = float(payload["monthly_budget_usd"])
            changed.append("monthly_budget_usd")
        if "enabled" in payload:
            if not isinstance(payload["enabled"], bool):
                return gateway_error(400, "invalid_request", "field 'enabled' must be a boolean")
            row.enabled = payload["enabled"]
            changed.append("enabled")
        db.commit()
        db.refresh(row)
        audit("client_key_updated", f"client_key_id={key_id} fields={','.join(changed) or 'none'}")
        return _client_key_view(row)

    @app.post("/api/v1/admin/client-keys/{key_id}/revoke")
    def admin_v1_revoke_client_key(key_id: int, request: Request, db: Session = Depends(get_db)):
        _account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        row = db.query(ClientKey).filter(ClientKey.id == key_id).first()
        if row is None:
            return gateway_error(404, "client_key_not_found", f"unknown client key: {key_id}")
        row.enabled = False
        db.commit()
        db.refresh(row)
        audit("client_key_revoked", f"client_key_id={key_id} name={row.name}")
        return _client_key_view(row)

    @app.post("/api/v1/admin/client-keys/{key_id}/regenerate")
    def admin_v1_regenerate_client_key(key_id: int, request: Request, db: Session = Depends(get_db)):
        _account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        row = db.query(ClientKey).filter(ClientKey.id == key_id).first()
        if row is None:
            return gateway_error(404, "client_key_not_found", f"unknown client key: {key_id}")
        raw = generate_client_key()
        row.key_hash = hash_client_key(raw)
        row.key_prefix = raw[:12]
        db.commit()
        db.refresh(row)
        audit("client_key_regenerated", f"client_key_id={key_id} name={row.name}")
        view = _client_key_view(row)
        view["raw_key"] = raw
        view["warning"] = "Store this key now — it will never be shown again."
        return view

    # ---- admin usage ----
    @app.get("/api/v1/admin/usage")
    def admin_v1_usage(request: Request, period: str = "today", db: Session = Depends(get_db)):
        require_admin_session(request, db)
        if period not in ("today", "yesterday", "month"):
            return gateway_error(400, "invalid_request", "period must be 'today', 'yesterday' or 'month'")
        now = _now_aware()
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif period == "yesterday":
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
        logs = (
            db.query(ApiRequestLog)
            .filter(ApiRequestLog.created_at >= start, ApiRequestLog.created_at < end)
            .all()
        )
        usage_rows = (
            db.query(UsageRecord)
            .filter(UsageRecord.created_at >= start, UsageRecord.created_at < end)
            .all()
        )
        total = len(logs)
        success = sum(1 for l in logs if l.status_code is not None and 200 <= l.status_code < 300)
        errors = sum(1 for l in logs if l.status_code is not None and l.status_code >= 400)
        latencies = sorted(l.latency_ms for l in logs if l.latency_ms is not None)
        tokens_in = sum(r.tokens_in or 0 for r in usage_rows)
        tokens_out = sum(r.tokens_out or 0 for r in usage_rows)
        tokens_cached = sum(r.tokens_cached or 0 for r in usage_rows)
        tokens_reasoning = sum(r.tokens_reasoning or 0 for r in usage_rows)
        cost_exact = sum(r.cost_usd or 0.0 for r in usage_rows if r.cost_status == "exact")
        cost_breakdown = {"exact": 0, "not_obtained": 0, "price_not_configured": 0}
        for r in usage_rows:
            if r.cost_status in cost_breakdown:
                cost_breakdown[r.cost_status] += 1
            else:
                cost_breakdown[r.cost_status] = cost_breakdown.get(r.cost_status, 0) + 1
        # Per-model ranking (requests from logs, tokens/cost from usage).
        by_model: dict[str, dict] = {}
        for l in logs:
            name = l.model or "unknown"
            entry = by_model.setdefault(name, {"model": name, "requests": 0, "success_count": 0,
                                               "error_count": 0, "tokens_in": 0, "tokens_out": 0,
                                               "cost_usd": 0.0})
            entry["requests"] += 1
            if l.status_code is not None and 200 <= l.status_code < 300:
                entry["success_count"] += 1
            if l.status_code is not None and l.status_code >= 400:
                entry["error_count"] += 1
        for r in usage_rows:
            entry = by_model.setdefault(r.model or "unknown", {"model": r.model or "unknown", "requests": 0,
                                                               "success_count": 0, "error_count": 0,
                                                               "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0})
            entry["tokens_in"] += r.tokens_in or 0
            entry["tokens_out"] += r.tokens_out or 0
            if r.cost_status == "exact":
                entry["cost_usd"] += r.cost_usd or 0.0
        for entry in by_model.values():
            entry["cost_usd"] = round(entry["cost_usd"], 6)
        # Per-client ranking, by client name — never raw key material.
        key_names = {k.id: k.name for k in db.query(ClientKey).all()}
        by_client: dict[str, dict] = {}
        for l in logs:
            name = key_names.get(l.client_key_id, "unknown") if l.client_key_id is not None else "unknown"
            entry = by_client.setdefault(name, {"client": name, "requests": 0, "success_count": 0,
                                                "error_count": 0, "tokens_in": 0, "tokens_out": 0,
                                                "cost_usd": 0.0})
            entry["requests"] += 1
            if l.status_code is not None and 200 <= l.status_code < 300:
                entry["success_count"] += 1
            if l.status_code is not None and l.status_code >= 400:
                entry["error_count"] += 1
        for r in usage_rows:
            name = key_names.get(r.client_key_id, "unknown") if r.client_key_id is not None else "unknown"
            entry = by_client.setdefault(name, {"client": name, "requests": 0, "success_count": 0,
                                                "error_count": 0, "tokens_in": 0, "tokens_out": 0,
                                                "cost_usd": 0.0})
            entry["tokens_in"] += r.tokens_in or 0
            entry["tokens_out"] += r.tokens_out or 0
            if r.cost_status == "exact":
                entry["cost_usd"] += r.cost_usd or 0.0
        for entry in by_client.values():
            entry["cost_usd"] = round(entry["cost_usd"], 6)
        # Daily trend: one bucket per day in the period.
        first_day = start.date()
        last_day = (end - timedelta(seconds=1)).date()
        trend: dict = {}
        day = first_day
        while day <= last_day:
            trend[day] = {"date": day.isoformat(), "requests": 0,
                          "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
            day += timedelta(days=1)
        for l in logs:
            bucket = trend.get(_as_aware(l.created_at).date())
            if bucket is not None:
                bucket["requests"] += 1
        for r in usage_rows:
            bucket = trend.get(_as_aware(r.created_at).date())
            if bucket is not None:
                bucket["tokens_in"] += r.tokens_in or 0
                bucket["tokens_out"] += r.tokens_out or 0
                if r.cost_status == "exact":
                    bucket["cost_usd"] += r.cost_usd or 0.0
        for bucket in trend.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 6)
        # Error distribution by error_type / status.
        err_groups: dict[tuple[str | None, int | None], int] = {}
        for l in logs:
            if l.status_code is not None and l.status_code >= 400:
                key = (l.error_type, l.status_code)
                err_groups[key] = err_groups.get(key, 0) + 1
        error_dist = [
            {"error_type": et, "status_code": sc, "count": n}
            for (et, sc), n in sorted(err_groups.items(), key=lambda kv: -kv[1])
        ]
        daily_limit, monthly_limit = _effective_budgets(db)
        spent_today = budget_mod.spend_since(db, now.replace(hour=0, minute=0, second=0, microsecond=0))
        spent_month = budget_mod.spend_since(db, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        alerts: list[str] = []
        if spent_today >= daily_limit:
            alerts.append("global_daily_budget_exceeded")
        if spent_month >= monthly_limit:
            alerts.append("global_monthly_budget_exceeded")
        return {
            "period": period,
            "requests": total,
            "success_count": success,
            "error_count": errors,
            "success_rate": round(success / total, 4) if total else None,
            "error_rate": round(errors / total, 4) if total else None,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "p95_latency_ms": _percentile(latencies, 95),
            "tokens": {
                "in": tokens_in, "out": tokens_out,
                "total": tokens_in + tokens_out,
                "cached": tokens_cached, "reasoning": tokens_reasoning,
            },
            "cost_usd": round(cost_exact, 6),
            "cost_status": cost_breakdown,
            "per_model": sorted(by_model.values(), key=lambda e: (-e["requests"], e["model"])),
            "per_client": sorted(by_client.values(), key=lambda e: (-e["requests"], e["client"])),
            "daily_trend": [trend[d] for d in sorted(trend)],
            "errors": error_dist,
            "budget": {
                "global_daily_usd": daily_limit,
                "global_monthly_usd": monthly_limit,
                "spent_today": round(spent_today, 6),
                "spent_month": round(spent_month, 6),
                "alerts": alerts,
            },
        }

    # ---- admin request traces ----
    def _log_view(l: ApiRequestLog, db: Session) -> dict:
        name = "unknown"
        if l.client_key_id is not None:
            key = db.query(ClientKey).filter(ClientKey.id == l.client_key_id).first()
            name = key.name if key is not None else "unknown"
        return {
            "id": l.id,
            "trace_id": l.trace_id,
            "client": name,
            "client_key_id": l.client_key_id,
            "model": l.model,
            "endpoint": l.endpoint,
            "status_code": l.status_code,
            "latency_ms": l.latency_ms,
            "tokens_in": l.tokens_in,
            "tokens_out": l.tokens_out,
            "tokens_cached": l.tokens_cached,
            "tokens_reasoning": l.tokens_reasoning,
            "error_type": l.error_type,
            "created_at": _iso(l.created_at),
        }

    @app.get("/api/v1/admin/requests")
    def admin_v1_list_requests(request: Request, limit: str = "50", error_only: str = "false",
                               db: Session = Depends(get_db)):
        require_admin_session(request, db)
        try:
            limit_n = int(limit)
        except ValueError:
            return gateway_error(400, "invalid_request", "limit must be an integer")
        limit_n = max(1, min(200, limit_n))
        only_errors = error_only.lower() in ("1", "true", "yes")
        q = db.query(ApiRequestLog)
        if only_errors:
            q = q.filter(
                (ApiRequestLog.status_code >= 400) | (ApiRequestLog.error_type.isnot(None))
            )
        rows = q.order_by(ApiRequestLog.created_at.desc(), ApiRequestLog.id.desc()).limit(limit_n).all()
        return {"requests": [_log_view(r, db) for r in rows]}

    @app.get("/api/v1/admin/requests/{trace_id}")
    def admin_v1_get_request(trace_id: str, request: Request, db: Session = Depends(get_db)):
        require_admin_session(request, db)
        row = (
            db.query(ApiRequestLog)
            .filter(ApiRequestLog.trace_id == trace_id)
            .order_by(ApiRequestLog.created_at.asc(), ApiRequestLog.id.asc())
            .first()
        )
        if row is None:
            return gateway_error(404, "trace_not_found", f"unknown trace id: {trace_id}")
        view = _log_view(row, db)
        view["upstream_request_id"] = row.upstream_request_id
        usage = (
            db.query(UsageRecord)
            .filter(UsageRecord.trace_id == trace_id)
            .first()
        )
        view["usage"] = None
        if usage is not None:
            view["usage"] = {
                "trace_id": usage.trace_id,
                "model": usage.model,
                "tokens_in": usage.tokens_in,
                "tokens_out": usage.tokens_out,
                "tokens_cached": usage.tokens_cached,
                "tokens_reasoning": usage.tokens_reasoning,
                "cost_usd": usage.cost_usd,
                "cost_status": usage.cost_status,
                "created_at": _iso(usage.created_at),
            }
        return view

    # ---- admin settings ----
    @app.get("/api/v1/admin/settings")
    def admin_v1_get_settings(request: Request, db: Session = Depends(get_db)):
        require_admin_session(request, db)
        return _settings_payload(db)

    @app.put("/api/v1/admin/settings")
    async def admin_v1_put_settings(request: Request, db: Session = Depends(get_db)):
        _account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            return gateway_error(400, "invalid_request", "request body must be a JSON object")
        changed: list[str] = []
        budgets = payload.get("budgets")
        if budgets is not None:
            if not isinstance(budgets, dict):
                return gateway_error(400, "invalid_request", "field 'budgets' must be an object")
            for field, key in (("global_daily_usd", "budget_global_daily_usd"),
                               ("global_monthly_usd", "budget_global_monthly_usd")):
                if field in budgets:
                    if not _is_number(budgets[field]) or budgets[field] < 0:
                        return gateway_error(400, "invalid_request",
                                             f"budgets.{field} must be a non-negative number")
                    _set_setting(db, key, float(budgets[field]))
                    changed.append(key)
        # Top-level budget fields are also accepted for convenience.
        for field, key in (("global_daily_usd", "budget_global_daily_usd"),
                           ("global_monthly_usd", "budget_global_monthly_usd")):
            if field in payload:
                if not _is_number(payload[field]) or payload[field] < 0:
                    return gateway_error(400, "invalid_request",
                                         f"field '{field}' must be a non-negative number")
                _set_setting(db, key, float(payload[field]))
                changed.append(key)
        if "retention_days" in payload:
            if not _is_int(payload["retention_days"]) or payload["retention_days"] < 1:
                return gateway_error(400, "invalid_request", "field 'retention_days' must be an integer >= 1")
            _set_setting(db, "retention_days", payload["retention_days"])
            changed.append("retention_days")
        rules = payload.get("pricing_rules")
        if rules is not None:
            if not isinstance(rules, list):
                return gateway_error(400, "invalid_request", "field 'pricing_rules' must be a list")
            for entry in rules:
                if not isinstance(entry, dict) or not entry.get("model") or not isinstance(entry["model"], str):
                    return gateway_error(400, "invalid_request", "each pricing rule needs a 'model' string")
                for rate_field in ("input_usd_per_1m", "output_usd_per_1m"):
                    if rate_field not in entry or not _is_number(entry[rate_field]) or entry[rate_field] < 0:
                        return gateway_error(400, "invalid_request",
                                             f"pricing rule '{entry['model']}' needs non-negative '{rate_field}'")
                for opt_field in ("cached_input_usd_per_1m", "reasoning_usd_per_1m"):
                    if entry.get(opt_field) is not None and (not _is_number(entry[opt_field]) or entry[opt_field] < 0):
                        return gateway_error(400, "invalid_request",
                                             f"pricing rule '{entry['model']}' field '{opt_field}' must be a non-negative number or null")
                existing = db.query(PricingRule).filter(PricingRule.model == entry["model"]).first()
                if existing is None:
                    db.add(PricingRule(
                        model=entry["model"],
                        input_usd_per_1m=float(entry["input_usd_per_1m"]),
                        output_usd_per_1m=float(entry["output_usd_per_1m"]),
                        cached_input_usd_per_1m=entry.get("cached_input_usd_per_1m"),
                        reasoning_usd_per_1m=entry.get("reasoning_usd_per_1m"),
                    ))
                else:
                    existing.input_usd_per_1m = float(entry["input_usd_per_1m"])
                    existing.output_usd_per_1m = float(entry["output_usd_per_1m"])
                    existing.cached_input_usd_per_1m = entry.get("cached_input_usd_per_1m")
                    existing.reasoning_usd_per_1m = entry.get("reasoning_usd_per_1m")
                changed.append(f"pricing:{entry['model']}")
        db.commit()
        audit("settings_updated", f"fields={','.join(changed) or 'none'}")
        return _settings_payload(db)

    # ---- admin audit log ----
    @app.get("/api/v1/admin/audit")
    def admin_v1_audit(request: Request, limit: str = "50", db: Session = Depends(get_db)):
        require_admin_session(request, db)
        try:
            limit_n = int(limit)
        except ValueError:
            return gateway_error(400, "invalid_request", "limit must be an integer")
        limit_n = max(1, min(200, limit_n))
        rows = (
            db.query(AuditEvent)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit_n)
            .all()
        )
        return {"audit": [
            {"id": r.id, "kind": r.kind, "detail": r.detail, "created_at": _iso(r.created_at)}
            for r in rows
        ]}

    # ---- Stage F: backups ----
    @app.get("/api/v1/admin/backups")
    def admin_v1_list_backups(request: Request, db: Session = Depends(get_db)):
        """List known backups from the manifest (admin session required).

        The manifest records filenames, sizes and SHA-256 hashes only —
        never key material. A missing manifest degrades to a directory
        scan (entries without a hash cannot be verified on restore).
        """
        require_admin_session(request, db)
        url = settings.effective_database_url
        kind = "postgres" if url.startswith("postgres") else "sqlite"
        backup_dir = backup_mod.resolve_backup_dir(settings.backup_dir or None, url)
        backups = backup_mod.read_manifest(backup_dir) if backup_dir.exists() else []
        return {"db_kind": kind, "backup_dir": str(backup_dir), "backups": backups}

    @app.post("/api/v1/admin/backups")
    def admin_v1_create_backup(request: Request, db: Session = Depends(get_db)):
        """Create a backup now (admin session + CSRF required).

        SQLite: online backup via the sqlite3 backup API, file chmod
        0600, manifest updated, retention pruned from the persisted
        `retention_days` setting. PostgreSQL: the API cannot run
        pg_dump — it returns 501 with the exact command to run on the
        server (database URL redacted; it comes from server env, never
        from this response). Restore is CLI-only by design
        (scripts/backup_db.py): restoring over a live database from an
        HTTP call would be unsafe.
        """
        _account, session_row = require_admin_session(request, db)
        require_csrf(request, session_row)
        url = settings.effective_database_url
        backup_dir = backup_mod.resolve_backup_dir(settings.backup_dir or None, url)
        if url.startswith("postgres"):
            return JSONResponse(
                status_code=501,
                content={
                    "error": {
                        "message": (
                            "PostgreSQL backup is not run from this API; "
                            "run pg_dump on the server (see docs/BACKUP_RESTORE.md)"
                        ),
                        "type": "gateway_error",
                        "code": "backup_postgres_manual",
                    },
                    # Deliberately a template: the real DATABASE_URL
                    # (which may contain a password) is never echoed.
                    "pg_dump_command": [
                        "pg_dump", "--format=custom", "--no-owner",
                        "--file", "<output.dump>", "<DATABASE_URL from server env>",
                    ],
                },
            )
        if not url.startswith("sqlite:///"):
            return gateway_error(400, "backup_unsupported", f"unsupported database URL scheme: {url.split(':')[0]}")
        db_path = url[len("sqlite:///"):]
        if db_path == ":memory:":
            return gateway_error(400, "backup_unsupported", "in-memory database cannot be backed up")
        entry = backup_mod.create_sqlite_backup(
            db_path,
            backup_dir,
            retention_days=_effective_retention_days(db),
            retention_count=settings.backup_retention_count,
            source="admin-api",
        )
        audit("backup_created", f"file={entry['filename']} size={entry['size_bytes']}")
        return {"ok": True, "backup": entry}

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


class _AdminUnauthorized(Exception):
    """Admin console session auth failure (cookie session, Stage E)."""

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
