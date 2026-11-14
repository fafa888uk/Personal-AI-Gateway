"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { AdminClient, loginErrorMessage } from "@/lib/admin";
import {
  Alert,
  cardStyle,
  inputClass,
  inputStyle,
  primaryButtonClass,
  primaryButtonStyle,
} from "@/components/admin/AdminUI";

/**
 * Admin login. Username/password against POST /api/v1/admin/login;
 * the gateway sets an HttpOnly session cookie on success. 401/429/503
 * are mapped to readable messages (see loginErrorMessage).
 */
export default function AdminLoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError("请填写用户名和密码");
      return;
    }
    setLoading(true);
    try {
      const client = new AdminClient();
      await client.login(username.trim(), password);
      router.replace("/admin");
    } catch (err) {
      setError(loginErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border p-6 shadow-sm"
        style={cardStyle}
      >
        <h1 className="text-xl font-semibold">管理后台</h1>
        <p className="mt-1 text-sm opacity-70">
          使用管理员账号登录 Personal AI Gateway
        </p>

        <label className="mt-6 block text-sm font-medium" htmlFor="admin-username">
          用户名
        </label>
        <input
          id="admin-username"
          className={`${inputClass} mt-1`}
          style={inputStyle}
          type="text"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />

        <label className="mt-4 block text-sm font-medium" htmlFor="admin-password">
          密码
        </label>
        <input
          id="admin-password"
          className={`${inputClass} mt-1`}
          style={inputStyle}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        {error ? <div className="mt-4"><Alert text={error} /></div> : null}

        <button
          type="submit"
          disabled={loading}
          className={`${primaryButtonClass} mt-6 w-full`}
          style={primaryButtonStyle()}
        >
          {loading ? "正在登录…" : "登录"}
        </button>

        <p className="mt-4 text-xs opacity-60">
          登录失败 5 次后将被锁定 15 分钟。会话保存在网关的 HttpOnly
          Cookie 中，不会写入本机存储。
        </p>
      </form>
    </main>
  );
}
