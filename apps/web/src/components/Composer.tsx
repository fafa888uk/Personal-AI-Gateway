"use client";

import { useRef, useState } from "react";

interface ComposerProps {
  /** Called with the trimmed text when the user sends. */
  onSend: (text: string) => void;
  /** Abort the in-flight stream. */
  onStop: () => void;
  streaming: boolean;
  /** True when no verified model is available — sending is disabled. */
  noModel: boolean;
}

/**
 * Bottom composer: auto-growing textarea, Enter sends, Shift+Enter
 * inserts a newline. The send button is disabled while the input is
 * empty, while streaming, or when no model is available; while
 * streaming a Stop button aborts the stream via AbortController.
 */
export default function Composer({
  onSend,
  onStop,
  streaming,
  noModel,
}: ComposerProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function autoGrow() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  function send() {
    const text = value.trim();
    if (text === "" || streaming || noModel) return;
    onSend(text);
    setValue("");
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (el) el.style.height = "auto";
    });
  }

  return (
    <div
      className="border-t px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3"
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
      }}
    >
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2">
        <textarea
          ref={textareaRef}
          value={value}
          rows={1}
          aria-label="输入消息"
          placeholder={
            noModel
              ? "暂无可用模型，无法发送消息"
              : "输入消息…（Enter 发送，Shift+Enter 换行）"
          }
          disabled={streaming}
          onChange={(e) => {
            setValue(e.target.value);
            autoGrow();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          className="max-h-50 flex-1 resize-none rounded-xl border px-3 py-2.5 text-sm outline-none disabled:opacity-60"
          style={{
            background: "var(--surface-muted)",
            borderColor: "var(--border)",
          }}
        />
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="停止生成"
            className="shrink-0 rounded-xl border px-4 py-2.5 text-sm font-medium text-red-600 dark:text-red-400"
            style={{ borderColor: "var(--border)" }}
          >
            停止
          </button>
        ) : (
          <button
            type="button"
            onClick={send}
            disabled={value.trim() === "" || noModel}
            aria-label="发送消息"
            className="shrink-0 rounded-xl px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            发送
          </button>
        )}
      </div>
      <p className="mx-auto mt-2 w-full max-w-3xl text-center text-xs opacity-50">
        文件/图片输入暂未提供（待真实模型能力支持后加入）。
      </p>
    </div>
  );
}
