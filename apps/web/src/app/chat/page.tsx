"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { GatewayClient, GatewayError } from "@/lib/api";
import {
  buildModelMessages,
  downloadTextFile,
  isNearBottom,
  truncateSessionTitle,
} from "@/lib/chat";
import { clearCredentials, loadCredentials } from "@/lib/credentials";
import {
  exportSessionToJson,
  exportSessionToMarkdown,
} from "@/lib/export";
import { resolveTheme, toggleTheme, type ThemeChoice } from "@/lib/theme";
import type {
  ChatMessage,
  ChatSession,
  GatewayCredentials,
  GatewayModel,
  UsageSummary,
} from "@/lib/types";
import Composer from "@/components/Composer";
import MessageList from "@/components/MessageList";
import ModelPicker from "@/components/ModelPicker";
import SettingsMenu from "@/components/SettingsMenu";
import Sidebar from "@/components/Sidebar";
import UsageBar from "@/components/UsageBar";
import VersionBanner from "@/components/VersionBanner";

/**
 * Full chat page (Stage D 2/3): sidebar + model switcher + message
 * area + composer, streaming replies, history, usage, version prompt.
 *
 * Sync model (v1): full pull on load and after every mutation —
 * GET /api/v1/chats, GET /api/v1/chats/{id}/messages. There is no
 * incremental sync, no tombstones, and the server hard-deletes
 * sessions; local state is replaced by each full pull.
 *
 * Edit / regenerate honesty note: the gateway has NO truncate or
 * message-delete endpoint. Edit-and-resend and regenerate therefore
 * apply locally (the local history is truncated/replaced and the new
 * turn is sent to the model) and only the NEW assistant reply is
 * saved server-side. The superseded user/assistant messages stay in
 * server history, so a fresh full pull (e.g. after reload) may show
 * them again. Nothing here claims server-side truncation.
 */

interface SendError {
  message: string;
}

function newLocalMessage(
  role: "user" | "assistant",
  content: string,
  model: string | null,
): ChatMessage {
  return {
    id: null,
    role,
    content,
    model,
    tokens_in: null,
    tokens_out: null,
    created_at: null,
  };
}

export default function ChatPage() {
  const router = useRouter();
  const [creds, setCreds] = useState<GatewayCredentials | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [models, setModels] = useState<GatewayModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sendError, setSendError] = useState<SendError | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [streamingTokens, setStreamingTokens] = useState<{
    in: number | null;
    out: number | null;
  }>({ in: null, out: null });
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [usageOpen, setUsageOpen] = useState(false);
  const [usageToday, setUsageToday] = useState<UsageSummary | null>(null);
  const [usageMonth, setUsageMonth] = useState<UsageSummary | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [theme, setTheme] = useState<ThemeChoice>("light");
  const [showScrollPill, setShowScrollPill] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  /** History of the last failed turn, for the retry button. */
  const lastTurnRef = useRef<{
    sessionId: number;
    history: ChatMessage[];
    model: string;
  } | null>(null);

  const client = useMemo(
    () => (creds ? new GatewayClient(creds) : null),
    [creds],
  );

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeId) ?? null,
    [sessions, activeId],
  );

  useEffect(() => {
    setTheme(resolveTheme());
  }, []);

  const handleAuthFailure = useCallback(
    (err: unknown) => {
      if (err instanceof GatewayError && err.status === 401) {
        clearCredentials();
        router.replace("/");
        return true;
      }
      return false;
    },
    [router],
  );

  const loadSessions = useCallback(async () => {
    if (!client) return;
    setSessionsLoading(true);
    try {
      setSessions(await client.listChats());
    } catch (err) {
      if (!handleAuthFailure(err)) {
        setError(
          err instanceof Error ? err.message : "加载会话失败",
        );
      }
    } finally {
      setSessionsLoading(false);
    }
  }, [client, handleAuthFailure]);

  const loadModels = useCallback(async () => {
    if (!client) return;
    setModelsLoading(true);
    try {
      const list = await client.listModels();
      setModels(list);
      setSelectedModel((prev) => prev ?? list[0]?.id ?? null);
    } catch (err) {
      if (!handleAuthFailure(err)) {
        setError(err instanceof Error ? err.message : "加载模型失败");
      }
    } finally {
      setModelsLoading(false);
    }
  }, [client, handleAuthFailure]);

  // Initial load: credentials, then models + sessions (full pull).
  useEffect(() => {
    const stored = loadCredentials();
    if (!stored) {
      router.replace("/");
      return;
    }
    setCreds(stored);
  }, [router]);

  useEffect(() => {
    if (!client) return;
    void loadModels();
    void loadSessions();
  }, [client, loadModels, loadSessions]);

  const openSession = useCallback(
    async (sessionId: number) => {
      if (!client) return;
      setActiveId(sessionId);
      setMessages([]);
      setSendError(null);
      setMessagesLoading(true);
      try {
        const loaded = await client.listMessages(sessionId);
        setMessages(loaded);
        const session = sessions.find((s) => s.id === sessionId);
        if (session?.model) setSelectedModel(session.model);
      } catch (err) {
        if (!handleAuthFailure(err)) {
          setError(err instanceof Error ? err.message : "加载消息失败");
        }
      } finally {
        setMessagesLoading(false);
      }
    },
    [client, handleAuthFailure, sessions],
  );

  // ---- auto-scroll: only while the user is at the bottom ----
  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const near = isNearBottom(el.scrollHeight, el.scrollTop, el.clientHeight);
    nearBottomRef.current = near;
    setShowScrollPill(!near && messages.length > 0);
  }

  useEffect(() => {
    const el = scrollRef.current;
    if (el && nearBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, streamingText]);

  function scrollToBottom() {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    nearBottomRef.current = true;
    setShowScrollPill(false);
  }

  // ---- streaming turn ----
  /**
   * Streams one assistant reply for `history` (which must end with a
   * user message) and saves the finished (or stopped-partial) reply
   * server-side. When `replaceLastAssistant` is set (regenerate), the
   * saved reply replaces the last local assistant message instead of
   * being appended. Returns false when the turn failed (error card
   * shown, retry available via lastTurnRef).
   */
  const streamReply = useCallback(
    async (opts: {
      sessionId: number;
      history: ChatMessage[];
      model: string;
      replaceLastAssistant: boolean;
    }): Promise<boolean> => {
      if (!client) return false;
      const { sessionId, history, model, replaceLastAssistant } = opts;
      const controller = new AbortController();
      abortRef.current = controller;
      setStreaming(true);
      setStreamingText("");
      setStreamingTokens({ in: null, out: null });
      setSendError(null);
      let acc = "";
      let usage: { in: number | null; out: number | null } = {
        in: null,
        out: null,
      };
      try {
        const result = await client.streamChatCompletion(
          { model, messages: buildModelMessages(history) },
          {
            signal: controller.signal,
            onEvent: (event) => {
              if (event.kind === "delta") {
                acc += event.delta;
                setStreamingText(acc);
              } else if (event.kind === "usage") {
                usage = { in: event.tokensIn, out: event.tokensOut };
                setStreamingTokens(usage);
              }
            },
          },
        );
        if (result.usage) {
          usage = {
            in: result.usage.tokensIn,
            out: result.usage.tokensOut,
          };
        }
        const text = result.text || acc;
        if (text.trim() === "") {
          setSendError({ message: "网关返回了空回复，请重试" });
          lastTurnRef.current = { sessionId, history, model };
          return false;
        }
        const saved = await client.addMessage(sessionId, {
          role: "assistant",
          content: text,
          model,
          tokens_in: usage.in ?? undefined,
          tokens_out: usage.out ?? undefined,
        });
        setMessages((prev) => {
          if (replaceLastAssistant) {
            const idx = (() => {
              for (let i = prev.length - 1; i >= 0; i--) {
                if (prev[i].role === "assistant") return i;
              }
              return -1;
            })();
            if (idx >= 0) {
              const next = [...prev];
              next[idx] = saved;
              return next;
            }
          }
          return [...prev, saved];
        });
        lastTurnRef.current = null;
        void loadSessions();
        return true;
      } catch (err) {
        // Stop button: save the partial reply as a message, if any.
        if (err instanceof GatewayError && err.message === "已停止") {
          if (acc.trim() !== "") {
            try {
              const saved = await client.addMessage(sessionId, {
                role: "assistant",
                content: acc,
                model,
                tokens_in: usage.in ?? undefined,
                tokens_out: usage.out ?? undefined,
              });
              setMessages((prev) => {
                if (replaceLastAssistant) {
                  const idx = (() => {
                    for (let i = prev.length - 1; i >= 0; i--) {
                      if (prev[i].role === "assistant") return i;
                    }
                    return -1;
                  })();
                  if (idx >= 0) {
                    const next = [...prev];
                    next[idx] = saved;
                    return next;
                  }
                }
                return [...prev, saved];
              });
              void loadSessions();
            } catch {
              // Saving the partial reply failed; the partial text was
              // already shown while streaming. Surface nothing extra.
            }
          }
          lastTurnRef.current = null;
          return true;
        }
        if (!handleAuthFailure(err)) {
          setSendError({
            message:
              err instanceof Error ? err.message : "发送失败，请重试",
          });
          lastTurnRef.current = { sessionId, history, model };
        }
        return false;
      } finally {
        abortRef.current = null;
        setStreaming(false);
        setStreamingText(null);
        setStreamingTokens({ in: null, out: null });
      }
    },
    [client, handleAuthFailure, loadSessions],
  );

  async function handleSend(text: string) {
    if (!client || streaming) return;
    const model = selectedModel ?? models[0]?.id ?? null;
    if (!model) {
      setSendError({ message: "暂无可用模型，无法发送消息" });
      return;
    }
    setSendError(null);
    let sessionId = activeId;
    try {
      if (sessionId == null) {
        setCreating(true);
        const session = await client.createChat({
          title: truncateSessionTitle(text),
          model,
        });
        sessionId = session.id;
        setSessions((prev) => [session, ...prev]);
        setActiveId(session.id);
      }
      const userMsg = newLocalMessage("user", text, model);
      const history = [...messages, userMsg];
      setMessages(history);
      const savedUser = await client.addMessage(sessionId, {
        role: "user",
        content: text,
        model,
      });
      setMessages((prev) =>
        prev.map((m) => (m === userMsg ? savedUser : m)),
      );
      await streamReply({
        sessionId,
        history: [...messages, savedUser],
        model,
        replaceLastAssistant: false,
      });
    } catch (err) {
      if (!handleAuthFailure(err)) {
        setSendError({
          message: err instanceof Error ? err.message : "发送失败，请重试",
        });
      }
    } finally {
      setCreating(false);
    }
  }

  async function handleRetry() {
    const turn = lastTurnRef.current;
    if (!turn || streaming) return;
    await streamReply({
      sessionId: turn.sessionId,
      history: turn.history,
      model: turn.model,
      replaceLastAssistant: false,
    });
  }

  async function handleRegenerate() {
    if (!client || streaming || activeId == null) return;
    const model = selectedModel ?? models[0]?.id ?? null;
    if (!model) return;
    let lastUserIdx = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        lastUserIdx = i;
        break;
      }
    }
    if (lastUserIdx < 0) return;
    const history = messages.slice(0, lastUserIdx + 1);
    await streamReply({
      sessionId: activeId,
      history,
      model,
      replaceLastAssistant: true,
    });
  }

  /**
   * Edit-and-resend. The gateway has no truncate endpoint, so the
   * edited message is NOT posted as a new server message and the
   * superseded messages are NOT deleted server-side — the local
   * history is truncated at the edited message and the edited text +
   * all earlier messages are sent to the model; only the new assistant
   * reply is saved. See the header comment.
   */
  async function handleEdit(message: ChatMessage, content: string) {
    if (!client || streaming || activeId == null) return;
    const model = selectedModel ?? models[0]?.id ?? null;
    if (!model) return;
    const idx = messages.indexOf(message);
    if (idx < 0) return;
    const edited = newLocalMessage("user", content, model);
    const history = [...messages.slice(0, idx), edited];
    setMessages(history);
    await streamReply({
      sessionId: activeId,
      history,
      model,
      replaceLastAssistant: false,
    });
  }

  function handleStop() {
    abortRef.current?.abort();
  }

  async function handleNewChat() {
    if (!client) return;
    setActiveId(null);
    setMessages([]);
    setSendError(null);
    setSidebarOpen(false);
    // No server session is created until the first message is sent.
  }

  async function handleRename(sessionId: number, title: string) {
    if (!client) return;
    try {
      await client.updateChat(sessionId, { title });
      await loadSessions();
    } catch (err) {
      if (!handleAuthFailure(err)) {
        setError(err instanceof Error ? err.message : "重命名失败");
      }
    }
  }

  async function handleDelete(sessionId: number) {
    if (!client) return;
    try {
      await client.deleteChat(sessionId);
      if (sessionId === activeId) {
        setActiveId(null);
        setMessages([]);
        setSendError(null);
      }
      await loadSessions();
    } catch (err) {
      if (!handleAuthFailure(err)) {
        setError(err instanceof Error ? err.message : "删除失败");
      }
    }
  }

  async function handleModelChange(modelId: string) {
    setSelectedModel(modelId);
    if (!client || activeId == null) return;
    try {
      await client.updateChat(activeId, { model: modelId });
      await loadSessions();
    } catch (err) {
      if (!handleAuthFailure(err)) {
        setError(err instanceof Error ? err.message : "切换模型失败");
      }
    }
  }

  const loadUsage = useCallback(async () => {
    if (!client) return;
    setUsageLoading(true);
    setUsageError(null);
    try {
      const [today, month] = await Promise.all([
        client.getUsageSummary("today"),
        client.getUsageSummary("month"),
      ]);
      setUsageToday(today);
      setUsageMonth(month);
    } catch (err) {
      if (!handleAuthFailure(err)) {
        setUsageError(err instanceof Error ? err.message : "加载用量失败");
      }
    } finally {
      setUsageLoading(false);
    }
  }, [client, handleAuthFailure]);

  function toggleUsage() {
    const next = !usageOpen;
    setUsageOpen(next);
    if (next) void loadUsage();
  }

  function handleLogout() {
    clearCredentials();
    router.replace("/");
  }

  function handleExport(format: "md" | "json") {
    if (!activeSession) return;
    const title =
      activeSession.title && activeSession.title.trim() !== ""
        ? activeSession.title.trim()
        : "新对话";
    const safe = title.replace(/[\\/:*?"<>|]/g, "_").slice(0, 64);
    if (format === "md") {
      downloadTextFile(
        `${safe}.md`,
        exportSessionToMarkdown(activeSession, messages),
        "text/markdown;charset=utf-8",
      );
    } else {
      downloadTextFile(
        `${safe}.json`,
        exportSessionToJson(activeSession, messages),
        "application/json;charset=utf-8",
      );
    }
  }

  if (!creds) {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <p className="text-sm opacity-60">正在检查登录状态…</p>
      </main>
    );
  }

  return (
    <main className="flex h-dvh w-full overflow-hidden">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={(id) => void openSession(id)}
        onNew={handleNewChat}
        onRename={(id, title) => void handleRename(id, title)}
        onDelete={(id) => void handleDelete(id)}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        creating={creating}
      />

      <section className="flex min-w-0 flex-1 flex-col">
        <VersionBanner client={client} />
        <header
          className="flex items-center gap-2 border-b px-3 py-2.5"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border)",
          }}
        >
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label="打开会话列表"
            className="rounded-lg border px-2.5 py-1.5 text-sm md:hidden"
            style={{ borderColor: "var(--border)" }}
          >
            ☰
          </button>
          <ModelPicker
            models={models}
            currentModel={selectedModel}
            loading={modelsLoading}
            onChange={(id) => void handleModelChange(id)}
          />
          <div className="flex-1" />
          {activeSession && messages.length > 0 ? (
            <div className="hidden items-center gap-1 sm:flex">
              <button
                type="button"
                onClick={() => handleExport("md")}
                className="rounded-lg border px-2 py-1.5 text-xs"
                style={{ borderColor: "var(--border)" }}
              >
                导出 Markdown
              </button>
              <button
                type="button"
                onClick={() => handleExport("json")}
                className="rounded-lg border px-2 py-1.5 text-xs"
                style={{ borderColor: "var(--border)" }}
              >
                导出 JSON
              </button>
            </div>
          ) : null}
          <button
            type="button"
            onClick={() => setTheme(toggleTheme(theme))}
            aria-label={theme === "dark" ? "切换到浅色" : "切换到深色"}
            className="rounded-lg border px-2.5 py-1.5 text-sm"
            style={{
              background: "var(--surface)",
              borderColor: "var(--border)",
            }}
          >
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
          <SettingsMenu
            baseUrl={creds.baseUrl}
            usageOpen={usageOpen}
            onToggleUsage={toggleUsage}
            onLogout={handleLogout}
          />
        </header>

        {usageOpen ? (
          <UsageBar
            today={usageToday}
            month={usageMonth}
            loading={usageLoading}
            error={usageError}
          />
        ) : null}

        {error ? (
          <p
            role="alert"
            className="mx-4 mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400"
          >
            {error}
          </p>
        ) : null}

        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="relative flex-1 overflow-y-auto"
        >
          <div className="mx-auto w-full max-w-3xl">
            {sessionsLoading || messagesLoading ? (
              <p className="px-4 py-6 text-sm opacity-60">正在加载…</p>
            ) : (
              <MessageList
                messages={messages}
                streamingText={streamingText}
                streamingTokensIn={streamingTokens.in}
                streamingTokensOut={streamingTokens.out}
                streaming={streaming}
                onRegenerate={() => void handleRegenerate()}
                onEdit={(msg, content) => void handleEdit(msg, content)}
              />
            )}
            {sendError ? (
              <div
                role="alert"
                className="mx-4 mb-6 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3"
              >
                <p className="text-sm font-medium text-red-600 dark:text-red-400">
                  发送失败
                </p>
                <p className="mt-1 text-sm">{sendError.message}</p>
                <button
                  type="button"
                  onClick={() => void handleRetry()}
                  disabled={streaming}
                  className="mt-2 rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                  style={{ background: "var(--accent)" }}
                >
                  重试
                </button>
              </div>
            ) : null}
          </div>
          {showScrollPill ? (
            <button
              type="button"
              onClick={scrollToBottom}
              className="fixed bottom-28 left-1/2 z-20 -translate-x-1/2 rounded-full border px-3 py-1.5 text-xs shadow-md"
              style={{
                background: "var(--surface)",
                borderColor: "var(--border)",
              }}
            >
              ↓ 回到底部
            </button>
          ) : null}
        </div>

        <Composer
          onSend={(text) => void handleSend(text)}
          onStop={handleStop}
          streaming={streaming}
          noModel={models.length === 0}
        />
      </section>
    </main>
  );
}
