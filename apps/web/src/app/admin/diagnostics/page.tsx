"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminClient } from "@/lib/admin";
import type { AdminRequest } from "@/lib/admin";
import {
  Alert,
  Card,
  Notice,
  cardStyle,
  errorMessage,
  inputClass,
  inputStyle,
  primaryButtonClass,
  primaryButtonStyle,
} from "@/components/admin/AdminUI";

/**
 * Diagnostics: look up one request by trace ID, and browse recent
 * requests with an error-only filter. Detail is rendered as the real
 * server record — nothing is guessed or filled in.
 */
export default function AdminDiagnosticsPage() {
  const [requests, setRequests] = useState<AdminRequest[]>([]);
  const [errorOnly, setErrorOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [traceId, setTraceId] = useState("");
  const [detail, setDetail] = useState<AdminRequest | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async (onlyErrors: boolean) => {
    setLoading(true);
    try {
      const list = await new AdminClient().listRequests(50, onlyErrors);
      setRequests(list);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(errorOnly);
  }, [errorOnly, load]);

  async function handleLookup(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setDetail(null);
    const id = traceId.trim();
    if (!id) {
      setError("请填写 Trace ID");
      return;
    }
    setDetailLoading(true);
    try {
      const record = await new AdminClient().getRequest(id);
      setDetail(record);
      setNotice(`已找到 Trace ${record.trace_id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">诊断</h1>
      <Alert text={error} />
      <Notice text={notice} />

      <Card title="按 Trace ID 查询">
        <form onSubmit={handleLookup} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex-1 text-sm font-medium">
            Trace ID
            <input
              className={`${inputClass} mt-1 font-mono`}
              style={inputStyle}
              value={traceId}
              onChange={(e) => setTraceId(e.target.value)}
              placeholder="例如：trace_…"
            />
          </label>
          <button
            type="submit"
            disabled={detailLoading}
            className={primaryButtonClass}
            style={primaryButtonStyle()}
          >
            {detailLoading ? "查询中…" : "查询"}
          </button>
        </form>
        {detail ? (
          <div className="mt-4">
            <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
              <div><dt className="opacity-60">Trace ID</dt><dd className="font-mono">{detail.trace_id}</dd></div>
              <div><dt className="opacity-60">模型</dt><dd className="font-mono">{detail.model ?? "—"}</dd></div>
              <div><dt className="opacity-60">客户端</dt><dd>{detail.client_name ?? "—"}</dd></div>
              <div><dt className="opacity-60">状态</dt><dd>{detail.status ?? detail.status_code ?? "—"}</dd></div>
              <div><dt className="opacity-60">延迟</dt><dd>{detail.latency_ms != null ? `${detail.latency_ms} ms` : "—"}</dd></div>
              <div><dt className="opacity-60">Token</dt><dd>{detail.tokens_in != null || detail.tokens_out != null ? `输入 ${detail.tokens_in ?? "—"} · 输出 ${detail.tokens_out ?? "—"}` : "未获取"}</dd></div>
              <div><dt className="opacity-60">费用</dt><dd>{detail.cost_usd != null ? `$${detail.cost_usd}` : "—"}</dd></div>
              <div><dt className="opacity-60">时间</dt><dd>{detail.created_at ?? "—"}</dd></div>
            </dl>
            {detail.error ? (
              <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
                错误：{detail.error}
              </p>
            ) : null}
            <details className="mt-3">
              <summary className="cursor-pointer text-sm font-medium">原始记录（JSON）</summary>
              <pre className="mt-2 overflow-x-auto rounded-lg p-3 font-mono text-xs" style={{ background: "var(--surface-muted)" }}>
                {JSON.stringify(detail, null, 2)}
              </pre>
            </details>
          </div>
        ) : null}
      </Card>

      <div className="rounded-2xl border p-4 shadow-sm sm:p-5" style={cardStyle}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold">最近请求</h2>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={errorOnly}
              onChange={(e) => setErrorOnly(e.target.checked)}
            />
            仅显示错误
          </label>
        </div>
        {loading ? <p className="mt-3 text-sm opacity-60">正在加载…</p> : null}
        {requests.length === 0 && !loading ? (
          <p className="mt-3 text-sm opacity-60">暂无请求记录。</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="text-xs opacity-60">
                  <th className="px-3 py-2 font-medium">Trace ID</th>
                  <th className="px-3 py-2 font-medium">模型</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">延迟</th>
                  <th className="px-3 py-2 font-medium">Token</th>
                  <th className="px-3 py-2 font-medium">时间</th>
                  <th className="px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((r) => (
                  <tr key={r.trace_id} className="border-t" style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-2 font-mono text-xs">{r.trace_id}</td>
                    <td className="px-3 py-2 font-mono">{r.model ?? "—"}</td>
                    <td className="px-3 py-2">{r.status ?? r.status_code ?? "—"}</td>
                    <td className="px-3 py-2">{r.latency_ms != null ? `${r.latency_ms} ms` : "—"}</td>
                    <td className="px-3 py-2">
                      {r.tokens_in != null || r.tokens_out != null
                        ? `${r.tokens_in ?? "—"} / ${r.tokens_out ?? "—"}`
                        : "未获取"}
                    </td>
                    <td className="px-3 py-2 text-xs">{r.created_at ?? "—"}</td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => {
                          setTraceId(r.trace_id);
                          setDetail(r);
                          setNotice(`已载入 Trace ${r.trace_id}`);
                        }}
                        className="rounded-lg border px-2 py-1 text-xs"
                        style={{ borderColor: "var(--border)" }}
                      >
                        查看详情
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
