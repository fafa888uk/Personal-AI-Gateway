/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/admin/login",
}));

import AdminLoginPage from "@/app/admin/login/page";

afterEach(() => {
  window.sessionStorage.clear();
});

describe("AdminLoginPage password-changed notice", () => {
  it("shows the re-login notice when the settings page set the flag, then clears it", () => {
    window.sessionStorage.setItem("pag_password_changed", "1");
    render(<AdminLoginPage />);
    expect(
      screen.getByText("密码已修改，请使用新密码重新登录"),
    ).toBeTruthy();
    expect(window.sessionStorage.getItem("pag_password_changed")).toBeNull();
  });

  it("shows no notice without the flag", () => {
    render(<AdminLoginPage />);
    expect(
      screen.queryByText("密码已修改，请使用新密码重新登录"),
    ).toBeNull();
  });
});
