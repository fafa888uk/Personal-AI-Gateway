"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { AdminClient } from "@/lib/admin";

const NAV = [
  { href: "/admin", label: "总览" },
  { href: "/admin/models", label: "模型" },
  { href: "/admin/keys", label: "客户端密钥" },
  { href: "/admin/usage", label: "用量" },
  { href: "/admin/diagnostics", label: "诊断" },
  { href: "/admin/settings", label: "设置" },
];

/**
 * Admin shell. The login page (same /admin tree) renders without the
 * shell or the auth check; every other admin page requires a live
 * session — GET /api/v1/admin/me returning 401 sends the user to
 * /admin/login. The session lives in the gateway HttpOnly cookie, so
 * the check must run in the browser.
 */
export default function AdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const router = useRouter();
  const pathname = usePathname();
  const isLogin = pathname === "/admin/login";
  const [username, setUsername] = useState<string | null>(null);
  const [checking, setChecking] = useState(!isLogin);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (isLogin) {
      setChecking(false);
      return;
    }
    let cancelled = false;
    const client = new AdminClient();
    client
      .me()
      .then((me) => {
        if (cancelled) return;
        if (!me.authenticated) {
          router.replace("/admin/login");
          return;
        }
        setUsername(me.username);
        setChecking(false);
      })
      .catch(() => {
        if (!cancelled) router.replace("/admin/login");
      });
    return () => {
      cancelled = true;
    };
  }, [isLogin, router]);

  const handleLogout = useCallback(async () => {
    try {
      await new AdminClient().logout();
    } catch {
      // Even if the server call fails, drop the local session view.
    }
    router.replace("/admin/login");
  }, [router]);

  if (isLogin) return <>{children}</>;

  if (checking) {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <p className="text-sm opacity-60">正在检查管理员登录状态…</p>
      </main>
    );
  }

  return (
    <div className="flex min-h-dvh">
      <aside
        aria-label="管理后台导航"
        className="hidden w-56 shrink-0 flex-col border-r p-4 md:flex"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <h1 className="px-2 text-base font-semibold">管理后台</h1>
        {username ? (
          <p className="mt-1 px-2 text-xs opacity-60">已登录：{username}</p>
        ) : null}
        <nav className="mt-4 flex flex-col gap-1">
          {NAV.map((item) => {
            const active =
              item.href === "/admin"
                ? pathname === "/admin"
                : pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                className="rounded-lg px-3 py-2 text-sm"
                style={
                  active
                    ? {
                        background: "var(--surface-muted)",
                        outline: "2px solid var(--accent-soft)",
                        fontWeight: 600,
                      }
                    : undefined
                }
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto flex flex-col gap-2 pt-4">
          <Link
            href="/chat"
            className="rounded-lg border px-3 py-2 text-center text-sm"
            style={{ borderColor: "var(--border)" }}
          >
            返回聊天
          </Link>
          <button
            type="button"
            onClick={handleLogout}
            className="rounded-lg border px-3 py-2 text-sm text-red-600 dark:text-red-400"
            style={{ borderColor: "var(--border)" }}
          >
            退出登录
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex items-center justify-between border-b px-4 py-3 md:hidden"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <span className="text-base font-semibold">管理后台</span>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            aria-expanded={menuOpen}
            aria-label="管理后台菜单"
            className="rounded-lg border px-2.5 py-1.5 text-sm"
            style={{ borderColor: "var(--border)" }}
          >
            ☰
          </button>
        </header>
        {menuOpen ? (
          <nav
            className="border-b px-4 py-2 md:hidden"
            style={{ background: "var(--surface)", borderColor: "var(--border)" }}
          >
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMenuOpen(false)}
                className="block rounded-lg px-3 py-2 text-sm"
              >
                {item.label}
              </Link>
            ))}
            <Link
              href="/chat"
              className="block rounded-lg px-3 py-2 text-sm"
              onClick={() => setMenuOpen(false)}
            >
              返回聊天
            </Link>
            <button
              type="button"
              onClick={handleLogout}
              className="block w-full rounded-lg px-3 py-2 text-left text-sm text-red-600 dark:text-red-400"
            >
              退出登录
            </button>
          </nav>
        ) : null}
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
          {children}
        </main>
      </div>
    </div>
  );
}
