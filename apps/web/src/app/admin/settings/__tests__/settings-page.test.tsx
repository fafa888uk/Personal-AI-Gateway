/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const { replaceMock } = vi.hoisted(() => ({ replaceMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  usePathname: () => "/admin/settings",
}));

import AdminSettingsPage from "@/app/admin/settings/page";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const SETTINGS_BODY = {
  budgets: { global_daily_usd: null, global_monthly_usd: null },
  pricing_rules: [],
  retention_days: null,
  version: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  replaceMock.mockClear();
});

/** Stubs fetch for the settings load + CSRF; change-password is injected per test. */
function stubFetch(
  changePassword: (url: string, init?: RequestInit) => Response,
) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.endsWith("/api/v1/admin/settings")) {
        return jsonResponse(200, SETTINGS_BODY);
      }
      if (url.endsWith("/api/v1/admin/csrf")) {
        return jsonResponse(200, { csrf_token: "csrf-1" });
      }
      if (url.endsWith("/api/v1/admin/change-password")) {
        return changePassword(url, init);
      }
      return jsonResponse(404, { error: { message: "not found" } });
    }),
  );
  return calls;
}

function fillChangePassword(current: string, next: string, confirm: string) {
  fireEvent.change(screen.getByLabelText("现密码"), {
    target: { value: current },
  });
  fireEvent.change(screen.getByLabelText("新密码"), {
    target: { value: next },
  });
  fireEvent.change(screen.getByLabelText("确认新密码"), {
    target: { value: confirm },
  });
}

function submitChangePassword() {
  fireEvent.click(screen.getByRole("button", { name: "修改密码" }));
}

describe("AdminSettingsPage change-password form", () => {
  it("shows a validation error and sends no request when the new password is too short", async () => {
    const calls = stubFetch(() => jsonResponse(200, { ok: true }));
    render(<AdminSettingsPage />);
    await screen.findByRole("button", { name: "修改密码" });

    fillChangePassword("old-password-123", "short", "short");
    submitChangePassword();

    expect(await screen.findByText("新密码至少 12 位")).toBeTruthy();
    expect(
      calls.some((c) => c.url.endsWith("/api/v1/admin/change-password")),
    ).toBe(false);
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("shows a validation error and sends no request when the confirmation differs", async () => {
    const calls = stubFetch(() => jsonResponse(200, { ok: true }));
    render(<AdminSettingsPage />);
    await screen.findByRole("button", { name: "修改密码" });

    fillChangePassword("old-password-123", "new-password-456", "different-789012");
    submitChangePassword();

    expect(await screen.findByText("两次输入的新密码不一致")).toBeTruthy();
    expect(
      calls.some((c) => c.url.endsWith("/api/v1/admin/change-password")),
    ).toBe(false);
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("shows a validation error and sends no request when the new password equals the current one", async () => {
    const calls = stubFetch(() => jsonResponse(200, { ok: true }));
    render(<AdminSettingsPage />);
    await screen.findByRole("button", { name: "修改密码" });

    fillChangePassword("same-password-1", "same-password-1", "same-password-1");
    submitChangePassword();

    expect(await screen.findByText("新密码不能与现密码相同")).toBeTruthy();
    expect(
      calls.some((c) => c.url.endsWith("/api/v1/admin/change-password")),
    ).toBe(false);
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("on success posts the passwords, flags the login notice, and redirects to /admin/login", async () => {
    const calls = stubFetch((url, init) => {
      const headers = new Headers(init?.headers);
      expect(init?.method).toBe("POST");
      expect(headers.get("X-CSRF-Token")).toBe("csrf-1");
      expect(JSON.parse(String(init?.body ?? "{}"))).toEqual({
        current_password: "old-password-123",
        new_password: "new-password-456",
      });
      return jsonResponse(200, { ok: true });
    });
    render(<AdminSettingsPage />);
    await screen.findByRole("button", { name: "修改密码" });

    fillChangePassword("old-password-123", "new-password-456", "new-password-456");
    submitChangePassword();

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/admin/login");
    });
    expect(window.sessionStorage.getItem("pag_password_changed")).toBe("1");
    expect(
      calls.some((c) => c.url.endsWith("/api/v1/admin/change-password")),
    ).toBe(true);
  });

  it("shows the backend error and does not redirect when the current password is wrong", async () => {
    stubFetch(() =>
      jsonResponse(401, {
        error: {
          code: "invalid_admin_credentials",
          message: "current password is incorrect",
        },
      }),
    );
    render(<AdminSettingsPage />);
    await screen.findByRole("button", { name: "修改密码" });

    fillChangePassword("wrong-password-1", "new-password-456", "new-password-456");
    submitChangePassword();

    expect(await screen.findByText("现密码不正确，请重试")).toBeTruthy();
    expect(replaceMock).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem("pag_password_changed")).toBeNull();
  });
});
