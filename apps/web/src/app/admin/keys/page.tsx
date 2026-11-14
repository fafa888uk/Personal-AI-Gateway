"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminClient } from "@/lib/admin";
import type { ClientKey, ClientKeyWithRaw } from "@/lib/admin";
import {
  Alert,
  Card,
  CopyButton,
  Notice,
  cardStyle,
  errorMessage,
  inputClass,
  inputStyle,
  primaryButtonClass,
  primaryButtonStyle,
} from "@/components/admin/AdminUI";

const CLIENT_TYPES = [
  { value: "web", label: "网页" },
  { value: "codex", label: "Codex" },
  { value: "vscode", label: "VS Code" },
  { value: "other", label: "其他" },
] as const;

function codexSnippet(baseUrl: string): string {
  return JSON.stringify(
    {
      model_provider: "personal-ai-gateway",
      base_url: `${baseUrl}/v1`,
      api_key_env: "PAG_CLIENT_KEY",
      note: "将客户端密钥保存为环境变量 PAG_CLIENT_KEY，不要把密钥写进配置文件",
    },
    null,
    2,
  );
}

/**
 * Client-key center. The raw key is returned once by the server and is
 * shown once, in memory only — it is never written to localStorage.
 * Dismissing the notice (or leaving the page) drops it for good.
 */
export default function AdminKeysPage() {
  const [keys, setKeys] = useState<ClientKey[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [rawKey, setRawKey] = useState<{ name: string; key: string } | null>(null);
  const [guideKeyId, setGuideKeyId] = useState<number | string | null>(null);

  // Create form state.
  const [name, setName] = useState("");
  const [clientType, setClientType] = useState<string>("web");
  const [allowedModels, setAllowedModels] = useState<string[]>([]);
  const [rateLimit, setRateLimit] = useState("");
  const [concurrency, setConcurrency] = useState("");
  const [monthlyBudget, setMonthlyBudget] = useState("");
  const [confirmId, setConfirmId] = useState<number | string | null>(null);
  const [confirmAction, setConfirmAction] = useState<"revoke" | "regenerate" | null>(null);
  const [busyId, setBusyId] = useState<number | string | null>(null);

  const baseUrl = new AdminClient().baseUrl;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, modelRes] = await Promise.all([
        new AdminClient().listClientKeys(),
        new AdminClient().listModels(),
      ]);
      setKeys(list);
      setModels(modelRes.models.map((m) => m.canonical_name));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function parseOptionalNumber(value: string): number | null {
    const v = value.trim();
    if (v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("请填写密钥名称");
      return;
    }
    setCreating(true);
    try {
      const created: ClientKeyWithRaw = await new AdminClient().createClientKey({
        name: name.trim(),
        client_type: clientType,
        allowed_models: allowedModels,
        rate_limit_per_min: parseOptionalNumber(rateLimit),
        concurrency_limit: parseOptionalNumber(concurrency),
        monthly_budget_usd: parseOptionalNumber(monthlyBudget),
      });
      setKeys((prev) => [created, ...prev]);
      setRawKey({ name: created.name, key: created.raw_key });
      setNotice(`已创建密钥「${created.name}」`);
      setName("");
      setAllowedModels([]);
      setRateLimit("");
      setConcurrency("");
      setMonthlyBudget("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function runConfirmedAction(key: ClientKey) {
    setBusyId(key.id);
    try {
      if (confirmAction === "revoke") {
        const updated = await new AdminClient().revokeClientKey(key.id);
        setKeys((prev) => prev.map((k) => (k.id === key.id ? updated : k)));
        setNotice(`已吊销密钥「${key.name}」`);
      } else if (confirmAction === "regenerate") {
        const updated = await new AdminClient().regenerateClientKey(key.id);
        setKeys((prev) =>
          prev.map((k) => (k.id === key.id ? { ...updated, raw_key: undefined } as unknown as ClientKey : k)),
        );
        setRawKey({ name: key.name, key: updated.raw_key });
        setNotice(`已重新生成密钥「${key.name}」，旧密钥立即失效`);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
      setConfirmId(null);
      setConfirmAction(null);
    }
  }

  async function toggleEnabled(key: ClientKey) {
    setBusyId(key.id);
    try {
      const updated = await new AdminClient().updateClientKey(key.id, {
        enabled: !key.enabled,
      });
      setKeys((prev) => prev.map((k) => (k.id === key.id ? updated : k)));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">客户端密钥</h1>
      {loading ? <p className="text-sm opacity-60">正在加载…</p> : null}
      <Alert text={error} />
      <Notice text={notice} />

      {rawKey ? (
        <div
          role="alert"
          className="rounded-2xl border border-amber-500/50 bg-amber-500/10 p-4"
        >
          <h2 className="text-sm font-semibold text-amber-700 dark:text-amber-300">
            密钥「{rawKey.name}」仅显示一次
          </h2>
          <p className="mt-1 text-sm">
            请立即复制并妥善保存。关闭此提示后，密钥将再也不会显示，丢失只能重新生成。
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <code className="break-all rounded-lg border px-3 py-2 font-mono text-sm" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
              {rawKey.key}
            </code>
            <CopyButton text={rawKey.key} label="复制密钥" />
            <button
              type="button"
              onClick={() => setRawKey(null)}
              className="rounded-lg border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)" }}
            >
              我已保存，关闭
            </button>
          </div>
        </div>
      ) : null}

      <Card title="创建新密钥">
        <form onSubmit={handleCreate} className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="text-sm font-medium">
              名称
              <input
                className={`${inputClass} mt-1`}
                style={inputStyle}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：我的 iPhone"
              />
            </label>
            <label className="text-sm font-medium">
              客户端类型
              <select
                className={`${inputClass} mt-1`}
                style={inputStyle}
                value={clientType}
                onChange={(e) => setClientType(e.target.value)}
              >
                {CLIENT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm font-medium">
              每分钟限速（留空不限）
              <input
                className={`${inputClass} mt-1`}
                style={inputStyle}
                inputMode="numeric"
                value={rateLimit}
                onChange={(e) => setRateLimit(e.target.value)}
                placeholder="例如 60"
              />
            </label>
            <label className="text-sm font-medium">
              并发上限（留空不限）
              <input
                className={`${inputClass} mt-1`}
                style={inputStyle}
                inputMode="numeric"
                value={concurrency}
                onChange={(e) => setConcurrency(e.target.value)}
                placeholder="例如 2"
              />
            </label>
            <label className="text-sm font-medium">
              每月预算（美元，留空不限）
              <input
                className={`${inputClass} mt-1`}
                style={inputStyle}
                inputMode="decimal"
                value={monthlyBudget}
                onChange={(e) => setMonthlyBudget(e.target.value)}
                placeholder="例如 20"
              />
            </label>
          </div>
          <fieldset>
            <legend className="text-sm font-medium">允许的模型（不选表示全部）</legend>
            {models.length === 0 ? (
              <p className="mt-1 text-sm opacity-60">暂无模型可供选择。</p>
            ) : (
              <div className="mt-2 flex flex-wrap gap-3">
                {models.map((m) => (
                  <label key={m} className="flex items-center gap-1 text-sm">
                    <input
                      type="checkbox"
                      checked={allowedModels.includes(m)}
                      onChange={(e) =>
                        setAllowedModels((prev) =>
                          e.target.checked
                            ? [...prev, m]
                            : prev.filter((x) => x !== m),
                        )
                      }
                    />
                    <span className="font-mono">{m}</span>
                  </label>
                ))}
              </div>
            )}
          </fieldset>
          <div>
            <button
              type="submit"
              disabled={creating}
              className={primaryButtonClass}
              style={primaryButtonStyle()}
            >
              {creating ? "创建中…" : "创建密钥"}
            </button>
          </div>
        </form>
      </Card>

      <div className="rounded-2xl border p-4 shadow-sm sm:p-5" style={cardStyle}>
        <h2 className="text-base font-semibold">已有密钥</h2>
        {keys.length === 0 && !loading ? (
          <p className="mt-3 text-sm opacity-60">暂无客户端密钥。</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="text-xs opacity-60">
                  <th className="px-3 py-2 font-medium">名称 / 前缀</th>
                  <th className="px-3 py-2 font-medium">类型</th>
                  <th className="px-3 py-2 font-medium">允许模型 / 限额</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => {
                  const busy = busyId === key.id;
                  const confirming = confirmId === key.id;
                  return (
                    <tr key={key.id} className="border-t align-top" style={{ borderColor: "var(--border)" }}>
                      <td className="px-3 py-3">
                        <p className="font-medium">{key.name}</p>
                        <p className="mt-0.5 font-mono text-xs opacity-70">{key.key_prefix}…</p>
                        <p className="mt-0.5 text-xs opacity-60">
                          创建于 {key.created_at ?? "未知"}
                          {key.last_used_at ? ` · 最近使用 ${key.last_used_at}` : " · 从未使用"}
                        </p>
                        {key.last_error ? (
                          <p className="mt-0.5 text-xs text-red-600 dark:text-red-400">
                            最近错误：{key.last_error}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-3 py-3">{key.client_type}</td>
                      <td className="px-3 py-3 text-xs">
                        <p>{key.allowed_models.length > 0 ? key.allowed_models.join(", ") : "全部模型"}</p>
                        <p className="mt-0.5 opacity-60">
                          限速 {key.rate_limit_per_min ?? "不限"}/分钟 · 并发 {key.concurrency_limit ?? "不限"} · 月预算{" "}
                          {key.monthly_budget_usd != null ? `$${key.monthly_budget_usd}` : "不限"}
                        </p>
                      </td>
                      <td className="px-3 py-3">
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={key.enabled}
                            disabled={busy}
                            onChange={() => void toggleEnabled(key)}
                            aria-label={`启用密钥 ${key.name}`}
                          />
                          {key.enabled ? "已启用" : "已停用"}
                        </label>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => setGuideKeyId(guideKeyId === key.id ? null : key.id)}
                            className="rounded-lg border px-2 py-1 text-xs"
                            style={{ borderColor: "var(--border)" }}
                          >
                            {guideKeyId === key.id ? "收起接入指南" : "接入指南"}
                          </button>
                          {confirming ? (
                            <>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => void runConfirmedAction(key)}
                                className="rounded-lg px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
                                style={{ background: "var(--accent)" }}
                              >
                                {confirmAction === "revoke" ? "确认吊销" : "确认重新生成"}
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setConfirmId(null);
                                  setConfirmAction(null);
                                }}
                                className="rounded-lg border px-2 py-1 text-xs"
                                style={{ borderColor: "var(--border)" }}
                              >
                                取消
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => {
                                  setConfirmId(key.id);
                                  setConfirmAction("regenerate");
                                }}
                                className="rounded-lg border px-2 py-1 text-xs disabled:opacity-50"
                                style={{ borderColor: "var(--border)" }}
                              >
                                重新生成
                              </button>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => {
                                  setConfirmId(key.id);
                                  setConfirmAction("revoke");
                                }}
                                className="rounded-lg border px-2 py-1 text-xs text-red-600 disabled:opacity-50 dark:text-red-400"
                                style={{ borderColor: "var(--border)" }}
                              >
                                吊销
                              </button>
                            </>
                          )}
                        </div>
                        {confirming && confirmAction === "regenerate" ? (
                          <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
                            重新生成后旧密钥立即失效，新密钥仅显示一次。
                          </p>
                        ) : null}
                        {confirming && confirmAction === "revoke" ? (
                          <p className="mt-2 text-xs text-red-600 dark:text-red-400">
                            吊销后该密钥立即失效，不可恢复。
                          </p>
                        ) : null}
                        {guideKeyId === key.id ? (
                          <div className="mt-3 rounded-xl border p-3 text-xs" style={{ borderColor: "var(--border)", background: "var(--surface-muted)" }}>
                            <p className="font-medium">接入指南（{key.name}）</p>
                            <p className="mt-2 opacity-70">网关地址</p>
                            <div className="mt-1 flex items-center gap-2">
                              <code className="break-all font-mono">{baseUrl}</code>
                              <CopyButton text={baseUrl} label="复制" />
                            </div>
                            <p className="mt-2 opacity-70">环境变量（将密钥保存为 PAG_CLIENT_KEY）</p>
                            <div className="mt-1 flex items-center gap-2">
                              <code className="break-all font-mono">export PAG_CLIENT_KEY=&lt;你的密钥&gt;</code>
                              <CopyButton text="export PAG_CLIENT_KEY=" label="复制" />
                            </div>
                            <p className="mt-2 opacity-70">Codex 配置片段（API 地址为 /v1，密钥用环境变量引用，不写进文件）</p>
                            <pre className="mt-1 overflow-x-auto rounded-lg p-2 font-mono" style={{ background: "var(--surface)" }}>
                              {codexSnippet(baseUrl)}
                            </pre>
                            <div className="mt-2">
                              <CopyButton text={codexSnippet(baseUrl)} label="复制 Codex 配置" />
                            </div>
                            <p className="mt-2 opacity-70">
                              注意：完整密钥只在创建或重新生成时显示一次，本页不再保存它；请用创建时复制的密钥设置
                              PAG_CLIENT_KEY。
                            </p>
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
