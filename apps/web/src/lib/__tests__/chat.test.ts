import { describe, expect, it } from "vitest";

import {
  buildModelMessages,
  costIsExact,
  costStatusLabel,
  formatTokenLine,
  isNearBottom,
  truncateSessionTitle,
} from "../chat";
import { exportSessionToJson, exportSessionToMarkdown } from "../export";
import type { ChatMessage, ChatSession, UsageSummary } from "../types";

describe("truncateSessionTitle", () => {
  it("takes the first 24 chars of the first message", () => {
    expect(truncateSessionTitle("你好，请介绍一下你自己好吗？谢谢")).toBe(
      "你好，请介绍一下你自己好吗？谢谢".slice(0, 24),
    );
    expect(
      truncateSessionTitle("abcdefghijklmnopqrstuvwxyz0123456789"),
    ).toBe("abcdefghijklmnopqrstuvwx");
    expect(truncateSessionTitle("短")).toBe("短");
  });

  it("trims surrounding whitespace first", () => {
    expect(truncateSessionTitle("  hello world  ")).toBe("hello world");
  });
});

describe("isNearBottom", () => {
  it("is true exactly at the bottom and within the threshold", () => {
    expect(isNearBottom(1000, 500, 500)).toBe(true);
    expect(isNearBottom(1000, 460, 500)).toBe(true); // 40px away < 48
  });

  it("is false when scrolled well up", () => {
    expect(isNearBottom(1000, 100, 500)).toBe(false);
  });
});

describe("formatTokenLine", () => {
  it("says 未获取 when both counts are unknown", () => {
    expect(formatTokenLine(null, null)).toBe("Token：未获取");
    expect(formatTokenLine(undefined, undefined)).toBe("Token：未获取");
  });

  it("shows known counts and 未获取 for the missing side", () => {
    expect(formatTokenLine(5, 8)).toBe("输入 5 · 输出 8 tokens");
    expect(formatTokenLine(5, null)).toBe("输入 5 · 输出 未获取 tokens");
  });
});

describe("costStatusLabel / costIsExact (Flutter semantics)", () => {
  const base: UsageSummary = {
    period: "today",
    requests: 1,
    tokens_in: 10,
    tokens_out: 5,
    cost_usd: 0.001,
    cost_status: "ok",
    by_model: [],
  };

  it("only ok is exact", () => {
    expect(costIsExact(base)).toBe(true);
    expect(costIsExact({ ...base, cost_status: "price_not_configured" })).toBe(
      false,
    );
    expect(costIsExact({ ...base, cost_status: "not_obtained" })).toBe(false);
  });

  it("labels partial sums as incomplete, never as exact totals", () => {
    expect(costStatusLabel("ok")).toBe("费用已按真实用量与定价计算");
    expect(costStatusLabel("price_not_configured")).toBe(
      "部分模型未配置价格，费用为不完整合计",
    );
    expect(costStatusLabel("not_obtained")).toBe(
      "部分请求未返回用量，费用为不完整合计",
    );
  });
});

describe("buildModelMessages", () => {
  it("maps messages to {role, content} in order", () => {
    const messages: ChatMessage[] = [
      {
        id: 1,
        role: "user",
        content: "hi",
        model: null,
        tokens_in: null,
        tokens_out: null,
        created_at: null,
      },
      {
        id: 2,
        role: "assistant",
        content: "hello",
        model: "gpt-5.4-mini",
        tokens_in: 3,
        tokens_out: 2,
        created_at: null,
      },
    ];
    expect(buildModelMessages(messages)).toEqual([
      { role: "user", content: "hi" },
      { role: "assistant", content: "hello" },
    ]);
  });
});

describe("export with tokens", () => {
  const session: ChatSession = {
    id: 3,
    title: "token 对话",
    model: "gpt-5.4-mini",
    created_at: null,
    updated_at: null,
  };
  const messages: ChatMessage[] = [
    {
      id: 9,
      session_id: 3,
      role: "assistant",
      content: "答复",
      model: "gpt-5.4-mini",
      tokens_in: 12,
      tokens_out: 34,
      created_at: null,
    },
  ];

  it("JSON export keeps tokens_in/tokens_out per message", () => {
    const parsed = JSON.parse(exportSessionToJson(session, messages));
    expect(parsed.messages[0].tokens_in).toBe(12);
    expect(parsed.messages[0].tokens_out).toBe(34);
  });

  it("Markdown export includes the assistant content", () => {
    expect(exportSessionToMarkdown(session, messages)).toContain("答复");
  });
});
