"use client";

import { costIsExact, costStatusLabel } from "@/lib/chat";
import type { UsageSummary } from "@/lib/types";

interface UsageBarProps {
  today: UsageSummary | null;
  month: UsageSummary | null;
  loading: boolean;
  error: string | null;
}

function SummaryBlock({
  label,
  summary,
}: {
  label: string;
  summary: UsageSummary | null;
}) {
  if (!summary) {
    return (
      <div className="rounded-xl border px-3 py-2" style={{ borderColor: "var(--border)" }}>
        <p className="text-xs font-medium">{label}</p>
        <p className="mt-1 text-sm opacity-60">未获取</p>
      </div>
    );
  }
  return (
    <div className="rounded-xl border px-3 py-2" style={{ borderColor: "var(--border)" }}>
      <p className="text-xs font-medium">{label}</p>
      <p className="mt-1 text-sm">
        {summary.requests} 次请求 · 输入 {summary.tokens_in} · 输出{" "}
        {summary.tokens_out} tokens
      </p>
      {costIsExact(summary) ? (
        <p className="mt-1 text-sm">${summary.cost_usd.toFixed(4)}</p>
      ) : (
        <p className="mt-1 text-xs opacity-70">
          费用：{costStatusLabel(summary.cost_status)}
        </p>
      )}
    </div>
  );
}

/**
 * Today + month token/request summary from GET /api/v1/usage/summary.
 * Cost semantics copy the Flutter UsageSummary model exactly: a dollar
 * figure is shown ONLY when cost_status is "ok" (costIsExact). When
 * the status is "price_not_configured" or "not_obtained" the cost is a
 * partial sum, so the UI shows the status label instead of a number —
 * it never presents a partial sum as an exact total.
 */
export default function UsageBar({ today, month, loading, error }: UsageBarProps) {
  return (
    <section
      aria-label="用量统计"
      className="border-b px-4 py-3"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
      }}
    >
      <h3 className="text-sm font-medium">用量</h3>
      {loading ? (
        <p className="mt-2 text-sm opacity-60">正在加载用量…</p>
      ) : error ? (
        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
          用量加载失败：{error}
        </p>
      ) : (
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <SummaryBlock label="今天" summary={today} />
          <SummaryBlock label="本月" summary={month} />
        </div>
      )}
    </section>
  );
}
