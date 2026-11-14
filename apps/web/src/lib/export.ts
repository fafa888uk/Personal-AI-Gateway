/**
 * Session export helpers: Markdown and JSON. Pure string builders —
 * no file I/O, no network. The caller decides how to save/download.
 */

import type { ChatMessage, ChatSession } from "./types";

function roleHeading(role: string): string {
  switch (role) {
    case "user":
      return "用户";
    case "assistant":
      return "助手";
    case "system":
      return "系统";
    default:
      return role;
  }
}

function formatTimestamp(value: string | null | undefined): string {
  return value ?? "";
}

export function exportSessionToMarkdown(
  session: ChatSession,
  messages: ChatMessage[],
): string {
  const lines: string[] = [];
  const title = session.title && session.title.trim() !== "" ? session.title : "新对话";
  lines.push(`# ${title}`);
  lines.push("");
  lines.push(`- 模型: ${session.model ?? "未指定"}`);
  lines.push(`- 创建时间: ${formatTimestamp(session.created_at)}`);
  lines.push(`- 更新时间: ${formatTimestamp(session.updated_at)}`);
  lines.push("");
  for (const message of messages) {
    lines.push(`## ${roleHeading(message.role)}`);
    lines.push("");
    lines.push(message.content);
    lines.push("");
  }
  return lines.join("\n");
}

export function exportSessionToJson(
  session: ChatSession,
  messages: ChatMessage[],
): string {
  return JSON.stringify(
    {
      id: session.id,
      title: session.title,
      model: session.model,
      created_at: session.created_at,
      updated_at: session.updated_at,
      messages: messages.map((m) => ({
        id: m.id,
        session_id: m.session_id ?? session.id,
        role: m.role,
        content: m.content,
        model: m.model,
        tokens_in: m.tokens_in,
        tokens_out: m.tokens_out,
        created_at: m.created_at,
      })),
    },
    null,
    2,
  );
}
