/**
 * Incremental SSE parser for OpenAI-style chat completion streams.
 * Mirrors apps/flutter/lib/sse.dart semantics exactly:
 * - `data: {...}` JSON lines (choices[0].delta.content, usage),
 * - `data: [DONE]` end-of-stream marker,
 * - `data: {"error": ...}` error events (gateway error shape),
 * - partial lines split across chunk boundaries (buffered),
 * - comment lines (`: ...`) and `event:` lines (ignored).
 */

import { GatewayError } from "./api";

export type ChatStreamEvent =
  | { kind: "delta"; delta: string }
  | { kind: "usage"; tokensIn: number | null; tokensOut: number | null }
  | { kind: "done" }
  | { kind: "error"; error: GatewayError };

export class SseParser {
  private buffer = "";

  /** Feed a raw text chunk; returns the events that became complete. */
  feed(chunk: string): ChatStreamEvent[] {
    this.buffer += chunk;
    const events: ChatStreamEvent[] = [];
    let newline = this.buffer.indexOf("\n");
    while (newline >= 0) {
      let line = this.buffer.slice(0, newline);
      this.buffer = this.buffer.slice(newline + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      events.push(...SseParser.handleLine(line));
      newline = this.buffer.indexOf("\n");
    }
    return events;
  }

  /** Flush any trailing partial line at stream end. */
  finish(): ChatStreamEvent[] {
    if (this.buffer.trim() === "") {
      this.buffer = "";
      return [];
    }
    const line = this.buffer;
    this.buffer = "";
    return SseParser.handleLine(line);
  }

  private static handleLine(line: string): ChatStreamEvent[] {
    if (line === "" || line.startsWith(":") || line.startsWith("event:")) {
      return [];
    }
    if (!line.startsWith("data:")) return [];
    const data = line.slice("data:".length).trim();
    if (data === "") return [];
    if (data === "[DONE]") return [{ kind: "done" }];

    let json: unknown;
    try {
      json = JSON.parse(data);
    } catch {
      return [];
    }
    if (typeof json !== "object" || json === null) return [];
    const obj = json as Record<string, unknown>;

    if ("error" in obj) {
      const err = obj.error;
      if (typeof err === "object" && err !== null) {
        const e = err as Record<string, unknown>;
        return [
          {
            kind: "error",
            error: new GatewayError(
              typeof e.message === "string" ? e.message : "上游返回错误",
              typeof e.code === "string" ? e.code : undefined,
            ),
          },
        ];
      }
      return [{ kind: "error", error: new GatewayError("上游返回错误") }];
    }

    const events: ChatStreamEvent[] = [];
    const choices = obj.choices;
    if (Array.isArray(choices)) {
      for (const choice of choices) {
        if (typeof choice === "object" && choice !== null) {
          const delta = (choice as Record<string, unknown>).delta;
          if (typeof delta === "object" && delta !== null) {
            const content = (delta as Record<string, unknown>).content;
            if (typeof content === "string" && content !== "") {
              events.push({ kind: "delta", delta: content });
            }
          }
        }
      }
    }
    const usage = obj.usage;
    if (typeof usage === "object" && usage !== null) {
      const u = usage as Record<string, unknown>;
      events.push({
        kind: "usage",
        tokensIn: typeof u.prompt_tokens === "number" ? u.prompt_tokens : null,
        tokensOut:
          typeof u.completion_tokens === "number" ? u.completion_tokens : null,
      });
    }
    return events;
  }
}

/** Parse a whole SSE body at once (convenience for tests). */
export function parseSseText(text: string): ChatStreamEvent[] {
  const parser = new SseParser();
  const events = parser.feed(text);
  events.push(...parser.finish());
  return events;
}
