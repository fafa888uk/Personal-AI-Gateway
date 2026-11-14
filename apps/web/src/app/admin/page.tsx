"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { AdminClient, adminCostStatusLabel, formatUsd } from "@/lib/admin";
import type { UsageStats } from "@/lib/admin";
import { Alert, Card, Notice, StatCard, errorMessage } from "@/components/admin/AdminUI";

/**
 * Admin overview: today's usage + budget alerts + links into each
 * section. Costs are labelled with their cost_status — a partial sum
 * is never shown as an exact total.
 */
export default function AdminOverviewPage() {
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [modelCount, setModelCount] = useState<number | null>(null);
  const [enabledCount, setEnabledCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const client = new AdminClient();
    Promise.all([client.getUsage("today"), client.listModels()])
      .then(([u, m]) => {
        if (cancelled) return;
        setUsage(u);
        setModelCount(m.models.length);
        setEnabledCount(m.models.filter((x) => x.enabled).length);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const alerts = usage?.budgets.alerts ?? [];

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">总览</h1>
      {loading ? <p className="text-sm opacity-60">正在加载…</p> : null}
      <Alert text={error} />
      {alerts.length > 0 ? (
        <div
          role="alert"
          className="rounded-2xl border border-amber-500/50 bg-amber-500/10 p-4"
        >
          <h2 className="text-sm font-semibold text-amber-700 dark:text-amber-300">
            预算提醒
          </h2>
          <ul className="mt-2 list-disc pl-5 text-sm">
            {alerts.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {usage ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="今日请求" value={String(usage.requests)} sub={`成功 ${usage.success_count} · 失败 ${usage.error_count}`} />
          <StatCard label="今日成功率" value={`${(usage.success_rate * 100).toFixed(1)}%`} sub={`错误率 ${(usage.error_rate * 100).toFixed(1)}%`} />
          <StatCard label="今日 Token" value={String(usage.tokens_total)} sub={`输入 ${usage.tokens_in} · 输出 ${usage.tokens_out}`} />
          <StatCard label="今日费用" value={formatUsd(usage.cost_usd)} sub={adminCostStatusLabel(usage.cost_status)} />
        </div>
      ) : null}

      <Card title="快捷入口">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Link href="/admin/models" className="rounded-xl border p-4" style={{ borderColor: "var(--border)" }}>
            <p className="font-medium">模型中心</p>
            <p className="mt-1 text-sm opacity-70">
              {modelCount == null
                ? "查看、启用与验证模型"
                : `共 ${modelCount} 个模型，${enabledCount ?? 0} 个已启用`}
            </p>
          </Link>
          <Link href="/admin/keys" className="rounded-xl border p-4" style={{ borderColor: "var(--border)" }}>
            <p className="font-medium">客户端密钥</p>
            <p className="mt-1 text-sm opacity-70">创建、吊销与重新生成客户端密钥</p>
          </Link>
          <Link href="/admin/usage" className="rounded-xl border p-4" style={{ borderColor: "var(--border)" }}>
            <p className="font-medium">用量统计</p>
            <p className="mt-1 text-sm opacity-70">按天 / 月查看请求、Token 与费用</p>
          </Link>
          <Link href="/admin/diagnostics" className="rounded-xl border p-4" style={{ borderColor: "var(--border)" }}>
            <p className="font-medium">诊断</p>
            <p className="mt-1 text-sm opacity-70">按 Trace ID 查请求，或浏览最近请求</p>
          </Link>
          <Link href="/admin/settings" className="rounded-xl border p-4" style={{ borderColor: "var(--border)" }}>
            <p className="font-medium">设置</p>
            <p className="mt-1 text-sm opacity-70">全局预算、定价规则与保留策略</p>
          </Link>
        </div>
      </Card>

      {usage && usage.budgets.global_daily_usd != null ? (
        <Notice
          text={`今日预算上限 ${formatUsd(usage.budgets.global_daily_usd)}，已用 ${formatUsd(usage.budgets.spent_today)}；本月上限 ${formatUsd(usage.budgets.global_monthly_usd)}，已用 ${formatUsd(usage.budgets.spent_month)}。`}
        />
      ) : null}
    </div>
  );
}
