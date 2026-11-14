import { describe, expect, it } from "vitest";

import { parseSseText, SseParser } from "../sse";

const delta = (content: string) =>
  `data: {"choices":[{"delta":{"content":${JSON.stringify(content)}}}]}\n\n`;

describe("SseParser", () => {
  it("parses delta chunks into text", () => {
    const events = parseSseText(`${delta("你好")}${delta("世界")}`);
    expect(events).toEqual([
      { kind: "delta", delta: "你好" },
      { kind: "delta", delta: "世界" },
    ]);
  });

  it("handles data: [DONE]", () => {
    const events = parseSseText(`${delta("hi")}\ndata: [DONE]\n\n`);
    expect(events).toContainEqual({ kind: "done" });
  });

  it("surfaces gateway error events with message and code", () => {
    const events = parseSseText(
      'data: {"error":{"message":"model_not_verified","code":"model_not_verified"}}\n\n',
    );
    expect(events).toHaveLength(1);
    const event = events[0];
    expect(event.kind).toBe("error");
    if (event.kind === "error") {
      expect(event.error.message).toBe("model_not_verified");
      expect(event.error.code).toBe("model_not_verified");
    }
  });

  it("handles a line split across chunks (buffered partial line)", () => {
    const parser = new SseParser();
    const first = parser.feed('data: {"choices":[{"delta":{"con');
    expect(first).toEqual([]);
    const second = parser.feed('tent":"hello"}}]}\n\n');
    expect(second).toEqual([{ kind: "delta", delta: "hello" }]);
  });

  it("ignores comment lines and event: lines", () => {
    const events = parseSseText(
      `: keep-alive\n\nevent: message\n${delta("ok")}`,
    );
    expect(events).toEqual([{ kind: "delta", delta: "ok" }]);
  });

  it("parses usage from a chunk", () => {
    const events = parseSseText(
      'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":4}}\n\n',
    );
    expect(events).toEqual([
      { kind: "usage", tokensIn: 10, tokensOut: 4 },
    ]);
  });

  it("ignores malformed JSON lines instead of throwing", () => {
    const events = parseSseText(`data: {not json\n\n${delta("ok")}`);
    expect(events).toEqual([{ kind: "delta", delta: "ok" }]);
  });

  it("flushes a trailing partial line on finish()", () => {
    const parser = new SseParser();
    parser.feed(delta("a"));
    const rest = parser.finish();
    expect(rest).toEqual([]);
    const parser2 = new SseParser();
    parser2.feed(`data: {"choices":[{"delta":{"content":"tail"}}]}`);
    expect(parser2.finish()).toEqual([{ kind: "delta", delta: "tail" }]);
  });
});
