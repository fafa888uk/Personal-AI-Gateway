/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/admin/keys",
}));

import AdminKeysPage from "@/app/admin/keys/page";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("AdminKeysPage key-once display", () => {
  it("shows the raw key once with a never-again notice, then drops it on dismiss and never stores it", async () => {
    const rawKey = "pag_sk_new_123456";
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/api/v1/admin/client-keys") && init?.method === "POST") {
        return jsonResponse(201, {
          id: 1,
          name: "我的 iPhone",
          key_prefix: "pag_sk_new",
          client_type: "web",
          allowed_models: [],
          rate_limit_per_min: null,
          concurrency_limit: null,
          monthly_budget_usd: null,
          enabled: true,
          last_used_at: null,
          last_error: null,
          created_at: "2026-11-14T00:00:00Z",
          raw_key: rawKey,
        });
      }
      if (url.endsWith("/api/v1/admin/csrf")) {
        return jsonResponse(200, { csrf_token: "csrf-1" });
      }
      if (url.endsWith("/api/v1/admin/client-keys")) {
        return jsonResponse(200, []);
      }
      if (url.endsWith("/api/v1/admin/models")) {
        return jsonResponse(200, { models: [], upstream_only: [] });
      }
      return jsonResponse(404, { error: { message: "not found" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminKeysPage />);
    expect(await screen.findByText("创建新密钥")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("例如：我的 iPhone"), {
      target: { value: "我的 iPhone" },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建密钥" }));

    await waitFor(() => {
      expect(screen.getByText(rawKey)).toBeTruthy();
    });
    expect(screen.getByText(/仅显示一次/)).toBeTruthy();
    expect(
      screen.getByText(/关闭此提示后，密钥将再也不会显示/),
    ).toBeTruthy();

    // Never persisted to localStorage.
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i);
      if (k) expect(window.localStorage.getItem(k)).not.toContain(rawKey);
    }

    fireEvent.click(screen.getByRole("button", { name: "我已保存，关闭" }));
    await waitFor(() => {
      expect(screen.queryByText(rawKey)).toBeNull();
    });
  });
});
