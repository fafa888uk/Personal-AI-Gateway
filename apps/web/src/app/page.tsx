"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { GatewayClient, GatewayError } from "@/lib/api";
import {
  defaultGatewayUrl,
  loadCredentials,
  saveCredentials,
} from "@/lib/credentials";

/**
 * Login screen. The user enters the gateway address + their gateway
 * client key (pag_sk_...). Validation is a real GET /v1/models call —
 * on failure the exact gateway error message is shown; on success the
 * credentials are stored in localStorage and the user goes to /chat.
 */
export default function LoginPage() {
  const router = useRouter();
  const [baseUrl, setBaseUrl] = useState(defaultGatewayUrl());
  const [clientKey, setClientKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (loadCredentials()) {
      router.replace("/chat");
    } else {
      setChecking(false);
    }
  }, [router]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    const url = baseUrl.trim();
    const key = clientKey.trim();
    if (!url || !key) {
      setError("请填写网关地址和客户端密钥");
      return;
    }
    setLoading(true);
    try {
      const client = new GatewayClient({ baseUrl: url, clientKey: key });
      await client.listModels();
      saveCredentials({ baseUrl: url, clientKey: key });
      router.replace("/chat");
    } catch (err) {
      if (err instanceof GatewayError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("登录失败，请重试");
      }
    } finally {
      setLoading(false);
    }
  }

  if (checking) {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <p className="text-sm opacity-60">正在检查登录状态…</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border p-6 shadow-sm"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
        }}
      >
        <h1 className="text-xl font-semibold">Personal AI Gateway</h1>
        <p className="mt-1 text-sm opacity-70">
          输入网关地址与客户端密钥以登录
        </p>

        <label className="mt-6 block text-sm font-medium" htmlFor="base-url">
          网关地址
        </label>
        <input
          id="base-url"
          className="mt-1 w-full rounded-lg border px-3 py-2 text-sm outline-none"
          style={{
            background: "var(--surface-muted)",
            borderColor: "var(--border)",
          }}
          type="url"
          inputMode="url"
          autoComplete="off"
          placeholder="http://localhost:8000"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />

        <label
          className="mt-4 block text-sm font-medium"
          htmlFor="client-key"
        >
          客户端密钥
        </label>
        <input
          id="client-key"
          className="mt-1 w-full rounded-lg border px-3 py-2 font-mono text-sm outline-none"
          style={{
            background: "var(--surface-muted)",
            borderColor: "var(--border)",
          }}
          type="password"
          autoComplete="off"
          placeholder="pag_sk_…"
          value={clientKey}
          onChange={(e) => setClientKey(e.target.value)}
        />

        {error ? (
          <p role="alert" className="mt-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={loading}
          className="mt-6 w-full rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          style={{ background: "var(--accent)" }}
        >
          {loading ? "正在验证…" : "登录"}
        </button>

        <p className="mt-4 text-xs opacity-60">
          密钥只保存在本机浏览器（localStorage），不会上传到任何其他地方。
        </p>
      </form>
    </main>
  );
}
