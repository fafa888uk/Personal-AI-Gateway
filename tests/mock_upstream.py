"""Mock upstream for local tests ONLY.

Returns realistic OpenAI Responses + Chat Completions payloads, including
SSE streams, tool calls, usage and error cases. Nothing here is a real
OpenAI response and no test result from this mock is real verification.
"""
from __future__ import annotations

import asyncio
import json

import httpx


class AbortableStream(httpx.AsyncByteStream):
    """SSE byte stream that records whether it was fully consumed or closed early."""

    def __init__(self, chunks: list[bytes], tracker: dict, delay_s: float = 0.02):
        self._chunks = chunks
        self._tracker = tracker
        self._delay_s = delay_s

    async def __aiter__(self):
        for chunk in self._chunks:
            await asyncio.sleep(self._delay_s)
            yield chunk
        self._tracker["completed"] = True

    async def aclose(self) -> None:
        self._tracker["closed"] = True


def responses_json(model: str, response_id: str = "resp_mock_123") -> dict:
    return {
        "id": response_id,
        "object": "response",
        "created_at": 1763000000,
        "status": "completed",
        "model": model,
        "output": [
            {
                "type": "message",
                "id": "msg_mock_1",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Hello from mock upstream."}],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 2},
            "output_tokens_details": {"reasoning_tokens": 1},
        },
    }


def chat_json(model: str, tool_call: bool = False) -> dict:
    message: dict = {"role": "assistant", "content": "Hello from mock upstream."}
    if tool_call:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_mock_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"location": "Shanghai"}',
                    },
                }
            ],
        }
    return {
        "id": "chatcmpl-mock-123",
        "object": "chat.completion",
        "created": 1763000000,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_call else "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
    }


def responses_sse_chunks(response_id: str = "resp_mock_123") -> list[bytes]:
    events = [
        {"type": "response.created", "response": {"id": response_id, "status": "in_progress"}},
        {"type": "response.output_text.delta", "delta": "Hello "},
        {"type": "response.output_text.delta", "delta": "from mock."},
        {"type": "response.completed", "response": responses_json("gpt-5.4-mini", response_id)},
    ]
    return [f"data: {json.dumps(e)}\n\n".encode() for e in events]


def chat_sse_chunks() -> list[bytes]:
    events = [
        {"id": "chatcmpl-mock-123", "object": "chat.completion.chunk", "created": 1763000000,
         "model": "gpt-5.4-mini", "choices": [{"index": 0, "delta": {"content": "Hello "}, "finish_reason": None}]},
        {"id": "chatcmpl-mock-123", "object": "chat.completion.chunk", "created": 1763000000,
         "model": "gpt-5.4-mini", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}},
    ]
    return [f"data: {json.dumps(e)}\n\n".encode() for e in events] + [b"data: [DONE]\n\n"]


class MockUpstream:
    """Stateful mock: tests set `scenario` to drive error/timeout behaviour."""

    def __init__(self):
        self.scenario: dict = {}
        self.calls: list[dict] = []
        self.last_bodies: dict[str, dict] = {}
        self.stream_tracker: dict = {"completed": False, "closed": False}
        self.transport = httpx.MockTransport(self._handler)

    def reset_stream_tracker(self):
        self.stream_tracker = {"completed": False, "closed": False}

    async def _handler(self, request: httpx.Request) -> httpx.Response:
        sleep_s = float(self.scenario.get("sleep_s", 0))
        if sleep_s:
            await asyncio.sleep(sleep_s)
        path = request.url.path
        if path.startswith("/v1"):
            path = path[3:]  # upstream base URL is .../v1; handler matches from there
        body: dict = {}
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = {}
        self.calls.append({"method": request.method, "path": path, "body": body})
        self.last_bodies[path] = body

        def error_response(status: int) -> httpx.Response:
            return httpx.Response(
                status,
                json={"error": {"message": f"mock upstream error {status}",
                                "type": "mock_error", "code": "mock_rate_limit" if status == 429 else "mock_error"}},
                headers={"retry-after": "0", "openai-request-id": "req_mock_err"},
            )

        status_override = self.scenario.get("status_override", {})
        if path in status_override:
            return error_response(int(status_override[path]))

        if request.method == "POST" and path == "/responses":
            model = body.get("model", "gpt-5.4-mini")
            if body.get("stream") is True:
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream", "openai-request-id": "req_mock_stream"},
                    stream=AbortableStream(responses_sse_chunks(), self.stream_tracker),
                )
            return httpx.Response(200, json=responses_json(model),
                                  headers={"openai-request-id": "req_mock_1"})
        if request.method == "POST" and path == "/chat/completions":
            model = body.get("model", "gpt-5.4-mini")
            if body.get("stream") is True:
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream", "openai-request-id": "req_mock_stream"},
                    stream=AbortableStream(chat_sse_chunks(), self.stream_tracker),
                )
            return httpx.Response(200, json=chat_json(model, tool_call=bool(self.scenario.get("chat_tool_call"))),
                                  headers={"openai-request-id": "req_mock_2"})
        if request.method == "POST" and path == "/responses/compact":
            return httpx.Response(200, json={
                "id": "resp_mock_compact", "object": "response", "status": "completed",
                "model": body.get("model", "gpt-5.4-mini"),
                "output": [{"type": "compaction", "encrypted_content": "MOCK-ENCRYPTED-BLOB-DO-NOT-USE"}],
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            })
        if request.method == "GET" and path.startswith("/responses/"):
            rid = path.split("/")[-1]
            return httpx.Response(200, json=responses_json("gpt-5.4-mini", rid))
        if request.method == "POST" and path.endswith("/cancel"):
            rid = path.split("/")[-2]
            payload = responses_json("gpt-5.4-mini", rid)
            payload["status"] = "cancelled"
            return httpx.Response(200, json=payload)
        if request.method == "DELETE" and path.startswith("/responses/"):
            rid = path.split("/")[-1]
            return httpx.Response(200, json={"id": rid, "object": "response", "deleted": True})
        return httpx.Response(404, json={"error": {"message": "mock: not found", "type": "mock_error", "code": "not_found"}})
