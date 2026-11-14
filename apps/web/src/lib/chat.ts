/**
 * Pure chat helpers — no network, no DOM. Covered by src/lib/__tests__/chat.test.ts.
 */

import type { ChatMessage, UsageSummary } from "./types";

/** Session title for a brand-new session: the first 24 chars of the first message. */
export function truncateSessionTitle(text: string): string {
  return text.trim().slice(0, 24);
}

/**
 * True when the scroll container is at (or near) the bottom, so
 * auto-scroll on new deltas will not yank the user away from messages
 * they scrolled up to read. `thresholdPx` is the slack in pixels.
 */
export function isNearBottom(
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
  thresholdPx = 48,
): boolean {
  return scrollHeight - scrollTop - clientHeight <= thresholdPx;
}

/** Per-message token line. Unknown usage stays "未获取" — never guessed. */
export function formatTokenLine(
  tokensIn: number | null | undefined,
  tokensOut: number | null | undefined,
): string {
  if (tokensIn == null && tokensOut == null) return "Token：未获取";
  const inPart = tokensIn == null ? "未获取" : String(tokensIn);
  const outPart = tokensOut == null ? "未获取" : String(tokensOut);
  return `输入 ${inPart} · 输出 ${outPart} tokens`;
}

/**
 * Cost-status label — exact semantics copied from the Flutter
 * UsageSummary model (apps/flutter/lib/models.dart):
 * - "ok": every counted cost is exact.
 * - "price_not_configured": at least one record has no price — the cost
 *   shown is a partial sum, never a complete total.
 * - "not_obtained": at least one record has no upstream usage — the cost
 *   shown is a partial sum, never a complete total.
 */
export function costStatusLabel(costStatus: string): string {
  switch (costStatus) {
    case "ok":
      return "费用已按真实用量与定价计算";
    case "price_not_configured":
      return "部分模型未配置价格，费用为不完整合计";
    case "not_obtained":
      return "部分请求未返回用量，费用为不完整合计";
    default:
      return `费用状态未知：${costStatus}`;
  }
}

/** True only when the cost is a complete exact total (Flutter: costIsExact). */
export function costIsExact(summary: UsageSummary): boolean {
  return summary.cost_status === "ok";
}

/**
 * History to send to the model for a turn: every message up to and
 * including the last user message, in {role, content} shape.
 * System messages are passed through unchanged.
 */
export function buildModelMessages(
  messages: ChatMessage[],
): { role: string; content: string }[] {
  return messages.map((m) => ({ role: m.role, content: m.content }));
}

/** Trigger a browser download of a text blob. Caller supplies the filename. */
export function downloadTextFile(
  filename: string,
  content: string,
  mimeType: string,
): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
