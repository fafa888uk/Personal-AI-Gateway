/**
 * GatewayClient tests with a mocked global fetch. No network, no server.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { GatewayClient, GatewayError } from "../api";

const creds = { baseUrl: "http://localhost:8000", clientKey: "pag_sk_test" };

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GatewayClient error decoding", () => {
  it("surfaces the gateway error message, code and status on 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(401, {
          error: {
            message: "invalid client key",
            type: "gateway_error",
            code: "invalid_client_key",
          },
        }),
      ),
    );
    const client = new GatewayClient(creds);
    let caught: unknown;
    try {
      await client.listModels();
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(GatewayError);
    if (caught instanceof GatewayError) {
      expect(caught.message).toBe("invalid client key");
      expect(caught.code).toBe("invalid_client_key");
      expect(caught.status).toBe(401);
    }
  });

  it("surfaces a 429 budget error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(429, {
          error: { message: "budget exceeded", code: "budget_exceeded" },
        }),
      ),
    );
    const client = new GatewayClient(creds);
    await expect(client.getUsageSummary("today")).rejects.toMatchObject({
      message: "budget exceeded",
      code: "budget_exceeded",
      status: 429,
    });
  });

  it("falls back to a generic message for a non-JSON error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("gateway down", { status: 502 })),
    );
    const client = new GatewayClient(creds);
    await expect(client.listModels()).rejects.toMatchObject({
      status: 502,
    });
  });
});

describe("GatewayClient requests", () => {
  it("sends Bearer auth on authed calls and parses /v1/models", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("http://localhost:8000/v1/models");
      const headers = new Headers(init?.headers);
      expect(headers.get("Authorization")).toBe("Bearer pag_sk_test");
      return jsonResponse(200, {
        object: "list",
        data: [
          { id: "gpt-5.4-mini", object: "model", created: 1, owned_by: "gateway" },
        ],
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new GatewayClient(creds);
    const models = await client.listModels();
    expect(models).toEqual([
      { id: "gpt-5.4-mini", object: "model", created: 1, owned_by: "gateway" },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("sends NO auth header for the public version endpoint", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe("http://localhost:8000/api/v1/app/version");
      expect(init?.headers).toBeUndefined();
      return jsonResponse(200, { configured: false, version: null, platforms: {} });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new GatewayClient(creds);
    const info = await client.getAppVersion();
    expect(info.configured).toBe(false);
  });

  it("creates a chat session with POST and parses the session view", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(201, {
          id: 3,
          title: "新对话",
          model: null,
          created_at: "2026-11-14T00:00:00+00:00",
          updated_at: "2026-11-14T00:00:00+00:00",
        }),
      ),
    );
    const client = new GatewayClient(creds);
    const session = await client.createChat({ title: "新对话" });
    expect(session.id).toBe(3);
    expect(session.title).toBe("新对话");
  });

  it("parses non-streaming chat completions with usage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(200, {
          choices: [{ message: { role: "assistant", content: "你好" } }],
          usage: { prompt_tokens: 10, completion_tokens: 4 },
        }),
      ),
    );
    const client = new GatewayClient(creds);
    const result = await client.chatCompletion({
      model: "gpt-5.4-mini",
      messages: [{ role: "user", content: "你好" }],
    });
    expect(result.text).toBe("你好");
    expect(result.usage).toEqual({ tokensIn: 10, tokensOut: 4 });
  });

  it("wraps a network failure as a GatewayError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("fetch failed");
      }),
    );
    const client = new GatewayClient(creds);
    await expect(client.listModels()).rejects.toMatchObject({
      message: expect.stringContaining("无法连接网关"),
    });
  });
});
