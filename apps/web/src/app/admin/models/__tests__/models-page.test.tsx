/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/admin/models",
}));

import AdminModelsPage from "@/app/admin/models/page";

const MODEL = {
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
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AdminModelsPage verify gating", () => {
  it("shows the cost warning first and sends no verify request before confirm", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/api/v1/admin/models")) {
        return jsonResponse(200, { models: [MODEL], upstream_only: [] });
      }
      return jsonResponse(404, { error: { message: "not found" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AdminModelsPage />);
    expect(await screen.findByText("gpt-5.4-mini")).toBeTruthy();
    expect(screen.getByText("未验证")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "验证" }));
    expect(
      screen.getByText("验证将发送一次真实请求，可能产生 API 费用。"),
    ).toBeTruthy();
    // No verify request has been sent yet.
    expect(
      fetchMock.mock.calls.some(([u]) => String(u).includes("/verify")),
    ).toBe(false);

    // Confirm: now the CSRF fetch + the verify POST go out.
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith("/api/v1/admin/csrf")) {
        return jsonResponse(200, { csrf_token: "csrf-1" });
      }
      if (url.endsWith("/verify")) {
        return jsonResponse(200, {
          ...MODEL,
          verification_status: "available",
          verification_method: "real",
          last_verified_at: "2026-11-14T00:00:00Z",
          cost_warning: "this sends a real request and may incur API cost",
        });
      }
      if (url.endsWith("/api/v1/admin/models")) {
        return jsonResponse(200, { models: [MODEL], upstream_only: [] });
      }
      return jsonResponse(404, { error: { message: "not found" } });
    });
    fireEvent.click(screen.getByRole("button", { name: "确认验证" }));
    await waitFor(() => {
      expect(screen.getByText("已验证（真实请求）")).toBeTruthy();
    });
    expect(
      fetchMock.mock.calls.some(([u]) => String(u).includes("/verify")),
    ).toBe(true);
  });
});
