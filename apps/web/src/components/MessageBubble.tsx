"use client";

import { useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import "highlight.js/styles/github.css";

import { formatTokenLine } from "@/lib/chat";
import type { ChatMessage } from "@/lib/types";

interface MessageBubbleProps {
  message: ChatMessage;
  /** True while this assistant message is still streaming in. */
  streaming?: boolean;
  /** Last assistant message only: show the regenerate button. */
  onRegenerate?: () => void;
  /** User messages only: save an edited resend. */
  onEdit?: (content: string) => void;
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const preRef = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);

  async function copy() {
    const text = preRef.current?.textContent ?? "";
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard API unavailable (non-secure context): fall back to a
      // temporary textarea + execCommand, best effort.
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        // Copy failed; leave the button unchanged.
        ta.remove();
        return;
      }
      ta.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={copy}
        aria-label="复制代码"
        className="absolute right-2 top-2 rounded-md border px-2 py-0.5 text-xs opacity-70 hover:opacity-100"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
        }}
      >
        {copied ? "已复制" : "复制"}
      </button>
      <pre ref={preRef}>{children}</pre>
    </div>
  );
}

/**
 * One chat message. Assistant messages render Markdown (GFM tables,
 * task lists, strikethrough) with syntax-highlighted code blocks that
 * each carry a working copy button; user messages render as plain
 * text. Token counts come from the server only — when unknown the
 * bubble says "未获取", never a guess.
 */
export default function MessageBubble({
  message,
  streaming = false,
  onRegenerate,
  onEdit,
}: MessageBubbleProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(message.content);
  const isUser = message.role === "user";

  const bubbleStyle: React.CSSProperties = isUser
    ? { background: "var(--accent)", color: "#fff" }
    : { background: "var(--surface)", borderColor: "var(--border)" };

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 sm:max-w-[75%] ${
          isUser ? "" : "border"
        }`}
        style={bubbleStyle}
      >
        {editing ? (
          <div>
            <textarea
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              rows={4}
              aria-label="编辑消息"
              className="w-full rounded-lg border px-2 py-1.5 text-sm outline-none"
              style={{
                background: "var(--surface)",
                borderColor: "var(--border)",
                color: "var(--foreground)",
              }}
            />
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                disabled={editValue.trim() === ""}
                onClick={() => {
                  const next = editValue.trim();
                  if (next === "" || next === message.content) {
                    setEditing(false);
                    return;
                  }
                  setEditing(false);
                  onEdit?.(next);
                }}
                className="rounded-lg px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
                style={{ background: "var(--accent)" }}
              >
                保存并重新发送
              </button>
              <button
                type="button"
                onClick={() => {
                  setEditValue(message.content);
                  setEditing(false);
                }}
                className="rounded-lg border px-3 py-1 text-xs"
                style={{ borderColor: "var(--border)" }}
              >
                取消
              </button>
            </div>
          </div>
        ) : isUser ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">
            {message.content}
          </p>
        ) : (
          <div className="markdown text-sm leading-relaxed">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
              components={{
                pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="underline"
                    style={{ color: "var(--accent-text)" }}
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
            {streaming ? (
              <span className="mt-1 inline-block animate-pulse text-xs opacity-60">
                正在生成…
              </span>
            ) : null}
          </div>
        )}

        <div
          className={`mt-2 flex flex-wrap items-center gap-3 text-xs ${
            isUser ? "text-white/70" : "opacity-60"
          }`}
        >
          {!isUser ? (
            <span>
              {formatTokenLine(message.tokens_in, message.tokens_out)}
            </span>
          ) : null}
          {message.model ? <span>{message.model}</span> : null}
          {isUser && onEdit && !streaming ? (
            <button
              type="button"
              onClick={() => {
                setEditValue(message.content);
                setEditing(true);
              }}
              className="underline"
            >
              编辑
            </button>
          ) : null}
          {!isUser && onRegenerate && !streaming ? (
            <button type="button" onClick={onRegenerate} className="underline">
              重新生成
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
