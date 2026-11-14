/**
 * AdminClient tests with a mocked global fetch. No network, no server.
 * Covers: credentials + CSRF header on mutations, login error mapping
 * (401/429/503), cost-status labelling, and the verified-model rule.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AdminClient,
  AdminError,
  adminCostIsExact,
  adminCostStatusLabel,
  isModelVerified,
  loginErrorMessage,
  verificationBadgeLabel,
} from "../admin";
import type { AdminModel } from "../admin";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function model(overrides: Partial<AdminModel> = {}): AdminModel {
  return {
    canonical_name: "gpt-5.4-mini",
    aliases: [],
    enabled: true,
    is_default: false,
    sort_order: 0,
    pinned_group: null,
    cap_responses: true,
    cap_chat: true,
    cap_streaming: true,
    cap_tools: false,
    cap_image: false,
    verification_status: "pending",
    last_verified_at: null,
    verification_method: null,
    last_error: null,
    in_upstream: true,
    ...overrides,
  };
}

describe("AdminClient auth + CSRF", () => {
  it("sends credentials:'include' on every call and X-CSRF-Token on mutations", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        if (url.endsWith("/api/v1/admin/csrf")) {
          return jsonResponse(200, { csrf_token: "csrf-123" });
        }
        if (url.endsWith("/api/v1/admin/models/gpt-5.4-mini")) {
          const headers = new Headers(init?.headers);
          expect(headers.get("X-CSRF-Token")).toBe("csrf-123");
          expect(init?.credentials).toBe("include");
          return jsonResponse(200, model({ enabled: false }));
        }
        return jsonResponse(404, { error: { message: "not found" } });
      }),
    );
    const client = new AdminClient("http://localhost:8000");
    const updated = await client.updateModel("gpt-5.4-mini", { enabled: false });
    expect(updated.enabled).toBe(false);
    // CSRF fetched once, then the mutation.
    expect(calls).toHaveLength(2);
    expect(calls[0].url).toBe("http://localhost:8000/api/v1/admin/csrf");
    expect(calls[0].init?.credentials).toBe("include");
    expect(calls[1].init?.credentials).toBe("include");
  });

  it("does not send X-CSRF-Token on read-only calls", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        expect(url).toBe("http://localhost:8000/api/v1/admin/me");
        expect(init?.credentials).toBe("include");
        const headers = new Headers(init?.headers);
        expect(headers.get("X-CSRF-Token")).toBeNull();
        return jsonResponse(200, { authenticated: true, username: "admin" });
      }),
    );
    const client = new AdminClient("http://localhost:8000");
    const me = await client.me();
    expect(me).toEqual({ authenticated: true, username: "admin" });
  });

  it("parses the models list and the upstream_only array", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(200, {
          models: [model()],
          upstream_only: ["gpt-5.4"],
        }),
      ),
    );
    const client = new AdminClient("http://localhost:8000");
    const res = await client.listModels();
    expect(res.models).toHaveLength(1);
    expect(res.upstream_only).toEqual(["gpt-5.4"]);
  });
});

describe("loginErrorMessage", () => {
  it("maps 401 to wrong credentials", () => {
    expect(loginErrorMessage(new AdminError("bad", undefined, 401))).toBe(
      "用户名或密码错误，请重试",
    );
  });

  it("maps 429 to the 15-minute lockout", () => {
    expect(loginErrorMessage(new AdminError("locked", undefined, 429))).toBe(
      "登录失败次数过多，请 15 分钟后再试",
    );
  });

  it("maps 503 to admin-not-configured", () => {
    expect(loginErrorMessage(new AdminError("no admin", undefined, 503))).toBe(
      "管理员账号尚未配置，请先在服务器上配置管理员账号",
    );
  });

  it("surfaces the server message for other statuses", () => {
    expect(loginErrorMessage(new AdminError("boom", undefined, 500))).toBe("boom");
  });

  it("login rejects with the mapped AdminError status on 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/api/v1/admin/csrf")) {
          return jsonResponse(200, { csrf_token: "csrf-1" });
        }
        return jsonResponse(401, { error: { message: "bad creds", code: "bad_credentials" } });
      }),
    );
    const client = new AdminClient("http://localhost:8000");
    let caught: unknown;
    try {
      await client.login("admin", "wrong");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(AdminError);
    expect(loginErrorMessage(caught)).toBe("用户名或密码错误，请重试");
  });
});

describe("cost-status labelling (admin usage)", () => {
  it("only 'exact' is exact", () => {
    expect(adminCostIsExact("exact")).toBe(true);
    expect(adminCostIsExact("price_not_configured")).toBe(false);
    expect(adminCostIsExact("not_obtained")).toBe(false);
  });

  it("labels a missing price as an incomplete sum, never exact", () => {
    expect(adminCostStatusLabel("price_not_configured")).toContain("不完整合计");
    expect(adminCostStatusLabel("price_not_configured")).toContain("价格未配置");
    expect(adminCostStatusLabel("not_obtained")).toContain("不完整合计");
    expect(adminCostStatusLabel("exact")).toContain("精确合计");
  });
});

describe("verified-model rule", () => {
  it("only available + real counts as verified", () => {
    expect(isModelVerified(model({ verification_status: "available", verification_method: "real" }))).toBe(true);
    expect(isModelVerified(model({ verification_status: "available", verification_method: "mock" }))).toBe(false);
    expect(isModelVerified(model({ verification_status: "pending", verification_method: "real" }))).toBe(false);
    expect(isModelVerified(model())).toBe(false);
  });

  it("labels mock verification as test-only, never verified", () => {
    expect(
      verificationBadgeLabel(model({ verification_status: "available", verification_method: "mock" })),
    ).toBe("测试验证（非真实请求）");
    expect(
      verificationBadgeLabel(model({ verification_status: "available", verification_method: "real" })),
    ).toBe("已验证（真实请求）");
    expect(verificationBadgeLabel(model())).toBe("未验证");
  });
});

describe("backend response normalization (real gateway shapes)", () => {
  // Fixtures copied from the live gateway (mock upstream) — the backend
  // envelopes differ from the flat UI types, and the adapter must bridge
  // them. If the backend changes shape, these tests fail first.
  const backendModelRow = {
    canonical_name: "gpt-5.4-mini",
    aliases: ["gpt-5.4-mini-2026-03-17"],
    enabled: true,
    is_default: true,
    sort_order: 1,
    pinned_group: null,
    capabilities: { responses: true, chat: true, streaming: true, tools: false, image: false },
    verification_status: "pending",
    last_verified_at: null,
    verification_method: null,
    last_error: null,
    in_upstream: true,
  };

  it("listModels flattens nested capabilities and unwraps upstream_only objects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/api/v1/admin/models")
          ? jsonResponse(200, {
              models: [backendModelRow],
              upstream_only: [{ id: "gpt-5.6-sol" }],
              upstream_reachable: true,
            })
          : jsonResponse(404, { error: "not found" }),
      ),
    );
    const res = await new AdminClient("http://gw").listModels();
    expect(res.models).toHaveLength(1);
    expect(res.models[0].cap_responses).toBe(true);
    expect(res.models[0].cap_tools).toBe(false);
    expect(res.models[0].cap_image).toBe(false);
    expect(res.models[0].is_default).toBe(true);
    expect(res.upstream_only).toEqual(["gpt-5.6-sol"]);
  });

  it("verifyModel unwraps {model, cost_warning}", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/api/v1/admin/csrf")) return jsonResponse(200, { csrf_token: "c" });
        return jsonResponse(200, {
          model: { ...backendModelRow, verification_status: "available", verification_method: "mock-test-only" },
          verification_http_status: 200,
          verification_method: "mock-test-only",
          cost_warning: "this sends a real request and may incur API cost",
        });
      }),
    );
    const res = await new AdminClient("http://gw").verifyModel("gpt-5.4-mini");
    expect(res.canonical_name).toBe("gpt-5.4-mini");
    expect(res.verification_status).toBe("available");
    expect(res.cap_chat).toBe(true);
    expect(res.cost_warning).toContain("real request");
    expect(isModelVerified(res)).toBe(false); // mock verification is never "verified"
  });

  it("listClientKeys accepts the {client_keys} envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(200, {
          client_keys: [
            {
              id: 1, name: "web", key_prefix: "pag_sk_abc", client_type: "web",
              allowed_models: ["*"], rate_limit_per_min: 60, concurrency_limit: 5,
              monthly_budget_usd: 20, enabled: true, last_used_at: null,
              last_error: null, created_at: "2026-11-14T00:00:00Z",
            },
          ],
        }),
      ),
    );
    const keys = await new AdminClient("http://gw").listClientKeys();
    expect(keys).toHaveLength(1);
    expect(keys[0].name).toBe("web");
  });

  it("getUsage maps nested tokens, per_* rankings, errors and cost breakdown", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(200, {
          period: "today",
          requests: 2, success_count: 1, error_count: 1,
          success_rate: 0.5, error_rate: 0.5, avg_latency_ms: 120, p95_latency_ms: 200,
          tokens: { in: 100, out: 50, total: 150, cached: 10, reasoning: 5 },
          cost_usd: 0.001,
          cost_status: { exact: 1, not_obtained: 1, price_not_configured: 0 },
          per_model: [{ model: "gpt-5.4-mini", requests: 2, tokens_in: 100, tokens_out: 50, cost_usd: 0.001 }],
          per_client: [{ client: "web", requests: 2, tokens_in: 100, tokens_out: 50, cost_usd: 0.001 }],
          daily_trend: [{ date: "2026-11-14", requests: 2, tokens_in: 100, tokens_out: 50, cost_usd: 0.001 }],
          errors: [{ error_type: "upstream_500", status_code: 500, count: 1 }],
          budget: { global_daily_usd: 5, global_monthly_usd: 50, spent_today: 0.001, spent_month: 0.001, alerts: [] },
        }),
      ),
    );
    const u = await new AdminClient("http://gw").getUsage("today");
    expect(u.tokens_in).toBe(100);
    expect(u.tokens_total).toBe(150);
    expect(u.tokens_cached).toBe(10);
    expect(u.model_ranking[0]).toEqual({ model: "gpt-5.4-mini", requests: 2, tokens: 150, cost_usd: 0.001 });
    expect(u.client_ranking[0].client_name).toBe("web");
    expect(u.daily_trend[0].tokens).toBe(150);
    expect(u.error_distribution[0]).toEqual({ error_type: "upstream_500", count: 1 });
    expect(u.cost_status).toBe("partial");
    expect(adminCostIsExact(u.cost_status)).toBe(false);
    expect(u.budgets.global_daily_usd).toBe(5);
  });

  it("getSettings maps pricing_rules and global_* budgets; updateSettings translates back", async () => {
    const seen: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        seen.push({ url, init });
        if (url.endsWith("/api/v1/admin/csrf")) return jsonResponse(200, { csrf_token: "c" });
        if (url.endsWith("/api/v1/admin/settings") && init?.method === "GET") {
          return jsonResponse(200, {
            budgets: { global_daily_usd: 5, global_monthly_usd: 50 },
            pricing_rules: [
              { model: "gpt-5.4-mini", input_usd_per_1m: 0.25, output_usd_per_1m: 2, cached_input_usd_per_1m: null, reasoning_usd_per_1m: null, updated_at: "2026-11-14T00:00:00Z" },
            ],
            retention_days: 90,
            version: { version: "0.3.0" },
          });
        }
        return jsonResponse(200, {
          budgets: { global_daily_usd: 10, global_monthly_usd: 50 },
          pricing_rules: [],
          retention_days: 90,
          version: { version: "0.3.0" },
        });
      }),
    );
    const client = new AdminClient("http://gw");
    const s = await client.getSettings();
    expect(s.budgets.daily_usd).toBe(5);
    expect(s.pricing).toHaveLength(1);
    expect(s.pricing[0].model).toBe("gpt-5.4-mini");
    await client.updateSettings({ budgets: { daily_usd: 10, monthly_usd: 50 }, retention_days: 90 });
    const put = seen.find((c) => c.init?.method === "PUT");
    const body = JSON.parse(String(put?.init?.body ?? "{}"));
    expect(body.budgets).toEqual({ global_daily_usd: 10, global_monthly_usd: 50 });
    expect(body.pricing).toBeUndefined();
  });

  it("listRequests maps client/error_type to the page's field names", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(200, {
          requests: [
            {
              id: 7, trace_id: "t-1", client: "codex", model: "gpt-5.4-mini",
              endpoint: "/v1/responses", status_code: 500, latency_ms: 42,
              tokens_in: 10, tokens_out: 5, error_type: "upstream_500",
              created_at: "2026-11-14T00:00:00Z",
            },
          ],
        }),
      ),
    );
    const rows = await new AdminClient("http://gw").listRequests();
    expect(rows).toHaveLength(1);
    expect(rows[0].client_name).toBe("codex");
    expect(rows[0].error).toBe("upstream_500");
    expect(rows[0].status).toBe("500");
  });
});
