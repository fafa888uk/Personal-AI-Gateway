"use client";

import MessageBubble from "./MessageBubble";
import type { ChatMessage } from "@/lib/types";

interface MessageListProps {
  messages: ChatMessage[];
  /** Live-streaming assistant text; rendered as a trailing bubble. */
  streamingText: string | null;
  streamingTokensIn: number | null;
  streamingTokensOut: number | null;
  streaming: boolean;
  onRegenerate: () => void;
  onEdit: (message: ChatMessage, content: string) => void;
}

/**
 * The central message column. The last assistant message gets the
 * regenerate button; every user message gets edit-and-resend. The
 * streaming reply is shown as a trailing assistant bubble until the
 * page saves it and replaces it with the stored message.
 */
export default function MessageList({
  messages,
  streamingText,
  streamingTokensIn,
  streamingTokensOut,
  streaming,
  onRegenerate,
  onEdit,
}: MessageListProps) {
  if (messages.length === 0 && streamingText == null) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 py-12">
        <p className="text-center text-sm opacity-60">
          还没有消息，在下方输入框发送第一条消息开始对话。
        </p>
      </div>
    );
  }

  const lastAssistantIndex = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return i;
    }
    return -1;
  })();

  return (
    <div className="flex flex-col gap-4 px-4 py-6">
      {messages.map((message, index) => (
        <MessageBubble
          key={message.id ?? `local-${index}`}
          message={message}
          onRegenerate={
            index === lastAssistantIndex && !streaming
              ? onRegenerate
              : undefined
          }
          onEdit={
            message.role === "user" && !streaming
              ? (content) => onEdit(message, content)
              : undefined
          }
        />
      ))}
      {streamingText != null ? (
        <MessageBubble
          message={{
            id: null,
            role: "assistant",
            content: streamingText,
            model: null,
            tokens_in: streamingTokensIn,
            tokens_out: streamingTokensOut,
            created_at: null,
          }}
          streaming={streaming}
        />
      ) : null}
    </div>
  );
}
