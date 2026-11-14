"use client";

import { useCallback, useEffect, useState } from "react";

import {
  AdminClient,
  adminCostIsExact,
  adminCostStatusLabel,
  formatUsd,
} from "@/lib/admin";
import type { UsageStats } from "@/lib/admin";
import { Alert, Card, Notice, StatCard, errorMessage } from "@/components/admin/AdminUI";

type Period = "today" | "yesterday" | "month";

const PERIODS: { value: Period; label: string }[] = [
  { value: "today", label: "今天" },
  { value: "yesterday", label: "昨天" },
  { value: "month", label: "本月" },
];

/**
 * Usage dashboard. Cost is shown with its cost_status label; when the
 * status is not "exact" the figure is a partial sum and is labelled
 * as such — never presented as an exact total.
 */
export default function AdminUsagePage() {
  const [period, setPeriod] = useState<Period>("today");
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (p: Period) => {
    setLoading(true);
    try {
      const u = await new AdminClient().getUsage(p);
      setUsage(u);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(period);
  }, [period, load]);

  const maxTrend = usage
    ? Math.max(1, ...usage.daily_trend.map((d) => d.requests))
    : 1;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">用量统计</h1>
        <div className="flex gap-2" role="group" aria-label="统计周期">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              type="button"
              aria-pressed={period === p.value}
              onClick={() => setPeriod(p.value)}
              className="rounded-lg border px-3 py-1.5 text-sm"
              style={
                period === p.value
                  ? { background: "var(--accent)", color: "#fff", borderColor: "var(--accent)" }
                  : { borderColor: "var(--border)" }
              }
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {loading ? <p className="text-sm opacity-60">正在加载…</p> : null}
      <Alert text={error} />

      {usage ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="请求数" value={String(usage.requests)} sub={`成功 ${usage.success_count} · 失败 ${usage.error_count}`} />
            <StatCard label="成功率" value={`${(usage.success_rate * 100).toFixed(1)}%`} sub={`错误率 ${(usage.error_rate * 100).toFixed(1)}%`} />
            <StatCard
              label="平均延迟 / P95"
              value={usage.avg_latency_ms != null ? `${Math.round(usage.avg_latency_ms)} ms` : "—"}
              sub={usage.p95_latency_ms != null ? `P95 ${Math.round(usage.p95_latency_ms)} ms` : "无延迟数据"}
            />
            <StatCard
              label="费用"
              value={formatUsd(usage.cost_usd)}
              sub={adminCostIsExact(usage.cost_status) ? "精确合计" : "不完整合计（见下方说明）"}
            />
          </div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Token 总计" value={String(usage.tokens_total)} sub={`输入 ${usage.tokens_in} · 输出 ${usage.tokens_out}`} />
            <StatCard label="缓存 Token" value={String(usage.tokens_cached)} sub="命中缓存的输入 Token" />
            <StatCard label="推理 Token" value={String(usage.tokens_reasoning)} sub="推理模型输出的推理 Token" />
            <StatCard
              label="预算"
              value={usage.budgets.global_daily_usd != null ? formatUsd(usage.budgets.global_daily_usd) : "未设置"}
              sub={`今日已用 ${formatUsd(usage.budgets.spent_today)} · 本月已用 ${formatUsd(usage.budgets.spent_month)}`}
            />
          </div>

          <Notice text={adminCostStatusLabel(usage.cost_status)} />

          {usage.budgets.alerts.length > 0 ? (
            <div role="alert" className="rounded-2xl border border-amber-500/50 bg-amber-500/10 p-4">
              <h2 className="text-sm font-semibold text-amber-700 dark:text-amber-300">预算提醒</h2>
              <ul className="mt-2 list-disc pl-5 text-sm">
                {usage.budgets.alerts.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <Card title="按模型排行">
            {usage.model_ranking.length === 0 ? (
              <p className="text-sm opacity-60">暂无数据。</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="text-xs opacity-60">
                      <th className="px-3 py-2 font-medium">模型</th>
                      <th className="px-3 py-2 font-medium">请求</th>
                      <th className="px-3 py-2 font-medium">Token</th>
                      <th className="px-3 py-2 font-medium">费用</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.model_ranking.map((r) => (
                      <tr key={r.model} className="border-t" style={{ borderColor: "var(--border)" }}>
                        <td className="px-3 py-2 font-mono">{r.model}</td>
                        <td className="px-3 py-2">{r.requests}</td>
                        <td className="px-3 py-2">{r.tokens}</td>
                        <td className="px-3 py-2">{formatUsd(r.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="按客户端排行">
            {usage.client_ranking.length === 0 ? (
              <p className="text-sm opacity-60">暂无数据。</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="text-xs opacity-60">
                      <th className="px-3 py-2 font-medium">客户端</th>
                      <th className="px-3 py-2 font-medium">请求</th>
                      <th className="px-3 py-2 font-medium">Token</th>
                      <th className="px-3 py-2 font-medium">费用</th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.client_ranking.map((r) => (
                      <tr key={r.client_name} className="border-t" style={{ borderColor: "var(--border)" }}>
                        <td className="px-3 py-2">{r.client_name}</td>
                        <td className="px-3 py-2">{r.requests}</td>
                        <td className="px-3 py-2">{r.tokens}</td>
                        <td className="px-3 py-2">{formatUsd(r.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="每日趋势">
            {usage.daily_trend.length === 0 ? (
              <p className="text-sm opacity-60">暂无数据。</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {usage.daily_trend.map((d) => (
                  <li key={d.date} className="flex items-center gap-3 text-sm">
                    <span className="w-24 shrink-0 font-mono text-xs">{d.date}</span>
                    <div
                      className="h-4 min-w-1 rounded"
                      style={{
                        width: `${Math.max(1, (d.requests / maxTrend) * 100)}%`,
                        background: "var(--accent)",
                      }}
                      aria-label={`${d.date} 请求 ${d.requests} 次`}
                    />
                    <span className="shrink-0 text-xs opacity-70">
                      {d.requests} 次 · {d.tokens} tokens · {formatUsd(d.cost_usd)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="错误分布">
            {usage.error_distribution.length === 0 ? (
              <p className="text-sm opacity-60">暂无错误。</p>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {usage.error_distribution.map((e) => (
                  <li key={e.error_type} className="flex justify-between gap-3">
                    <span className="font-mono">{e.error_type}</span>
                    <span>{e.count} 次</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
