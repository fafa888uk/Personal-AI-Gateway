import { describe, expect, it } from "vitest";

import { exportSessionToJson, exportSessionToMarkdown } from "../export";
import type { ChatMessage, ChatSession } from "../types";

const session: ChatSession = {
  id: 7,
  title: "测试对话",
  model: "gpt-5.4-mini",
  created_at: "2026-11-14T00:00:00+00:00",
  updated_at: "2026-11-14T01:00:00+00:00",
};

const messages: ChatMessage[] = [
  {
    id: 1,
    session_id: 7,
    role: "user",
    content: "你好",
    model: null,
    tokens_in: null,
    tokens_out: null,
    created_at: "2026-11-14T00:00:00+00:00",
  },
  {
    id: 2,
    session_id: 7,
    role: "assistant",
    content: "你好，有什么可以帮你？",
    model: "gpt-5.4-mini",
    tokens_in: 5,
    tokens_out: 8,
    created_at: "2026-11-14T00:01:00+00:00",
  },
];

describe("exportSessionToMarkdown", () => {
  it("includes title, model, timestamps and role headings", () => {
    const md = exportSessionToMarkdown(session, messages);
    expect(md).toContain("# 测试对话");
    expect(md).toContain("模型: gpt-5.4-mini");
    expect(md).toContain("2026-11-14T00:00:00+00:00");
    expect(md).toContain("## 用户");
    expect(md).toContain("## 助手");
    expect(md).toContain("你好");
    expect(md).toContain("你好，有什么可以帮你？");
  });

  it("falls back to 新对话 for an empty title", () => {
    const md = exportSessionToMarkdown({ ...session, title: "" }, []);
    expect(md).toContain("# 新对话");
  });
});

describe("exportSessionToJson", () => {
  it("round-trips session and messages", () => {
    const parsed = JSON.parse(exportSessionToJson(session, messages));
    expect(parsed.id).toBe(7);
    expect(parsed.title).toBe("测试对话");
    expect(parsed.model).toBe("gpt-5.4-mini");
    expect(parsed.messages).toHaveLength(2);
    expect(parsed.messages[0].role).toBe("user");
    expect(parsed.messages[1].tokens_out).toBe(8);
  });
});
