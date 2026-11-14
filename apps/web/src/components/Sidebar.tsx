"use client";

import { useMemo, useState } from "react";

import type { ChatSession } from "@/lib/types";

interface SidebarProps {
  sessions: ChatSession[];
  activeId: number | null;
  onSelect: (sessionId: number) => void;
  onNew: () => void;
  onRename: (sessionId: number, title: string) => void;
  onDelete: (sessionId: number) => void;
  /** Mobile drawer state, controlled by the chat page. */
  open: boolean;
  onClose: () => void;
  creating: boolean;
}

function displayTitle(session: ChatSession): string {
  return session.title && session.title.trim() !== ""
    ? session.title
    : "新对话";
}

/**
 * Conversation list: search filter, new-chat button, per-item inline
 * rename + two-step delete confirm, active state. On mobile (<768px)
 * it is a drawer with an overlay; on desktop it is a fixed column.
 */
export default function Sidebar({
  sessions,
  activeId,
  onSelect,
  onNew,
  onRename,
  onDelete,
  open,
  onClose,
  creating,
}: SidebarProps) {
  const [query, setQuery] = useState("");
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q === "") return sessions;
    return sessions.filter((s) =>
      displayTitle(s).toLowerCase().includes(q),
    );
  }, [sessions, query]);

  function startRename(session: ChatSession) {
    setConfirmDeleteId(null);
    setRenamingId(session.id);
    setRenameValue(displayTitle(session));
  }

  function commitRename(session: ChatSession) {
    const title = renameValue.trim();
    setRenamingId(null);
    if (title !== "" && title !== displayTitle(session)) {
      onRename(session.id, title);
    }
  }

  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="关闭侧边栏"
          onClick={onClose}
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
        />
      ) : null}
      <aside
        aria-label="会话列表"
        className={`fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r transition-transform md:static md:z-auto md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
        }}
      >
        <div className="flex items-center justify-between px-4 pt-4">
          <h2 className="text-base font-semibold">对话</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭侧边栏"
            className="rounded-lg px-2 py-1 text-sm opacity-60 md:hidden"
          >
            ✕
          </button>
        </div>

        <div className="px-4 pt-3">
          <button
            type="button"
            onClick={() => {
              onNew();
              onClose();
            }}
            disabled={creating}
            className="w-full rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            {creating ? "正在创建…" : "＋ 新对话"}
          </button>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索对话…"
            aria-label="搜索对话"
            className="mt-3 w-full rounded-lg border px-3 py-2 text-sm outline-none"
            style={{
              background: "var(--surface-muted)",
              borderColor: "var(--border)",
            }}
          />
        </div>

        <ul className="mt-3 flex-1 overflow-y-auto px-2 pb-4">
          {filtered.length === 0 ? (
            <li className="px-2 py-4 text-sm opacity-60">
              {sessions.length === 0
                ? "还没有对话，点击「新对话」开始。"
                : "没有匹配的对话。"}
            </li>
          ) : (
            filtered.map((session) => {
              const active = session.id === activeId;
              const renaming = renamingId === session.id;
              const confirmingDelete = confirmDeleteId === session.id;
              return (
                <li key={session.id} className="mt-1">
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => {
                      if (!renaming) {
                        onSelect(session.id);
                        onClose();
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !renaming) {
                        onSelect(session.id);
                        onClose();
                      }
                    }}
                    className="group cursor-pointer rounded-xl px-3 py-2"
                    style={
                      active
                        ? {
                            background: "var(--surface-muted)",
                            outline: "2px solid var(--accent-soft)",
                          }
                        : undefined
                    }
                  >
                    {renaming ? (
                      <input
                        autoFocus
                        value={renameValue}
                        maxLength={64}
                        aria-label="重命名对话"
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={() => commitRename(session)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitRename(session);
                          if (e.key === "Escape") setRenamingId(null);
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="w-full rounded-md border px-2 py-1 text-sm outline-none"
                        style={{
                          background: "var(--surface)",
                          borderColor: "var(--accent)",
                        }}
                      />
                    ) : (
                      <p className="truncate text-sm font-medium">
                        {displayTitle(session)}
                      </p>
                    )}
                    <p className="mt-0.5 truncate text-xs opacity-60">
                      {session.model ? `模型：${session.model}` : "模型未指定"}
                    </p>
                    <div className="mt-1 flex gap-1">
                      <button
                        type="button"
                        aria-label={`重命名 ${displayTitle(session)}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          startRename(session);
                        }}
                        className="rounded px-1.5 py-0.5 text-xs opacity-60 hover:opacity-100"
                      >
                        重命名
                      </button>
                      {confirmingDelete ? (
                        <>
                          <button
                            type="button"
                            aria-label={`确认删除 ${displayTitle(session)}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDeleteId(null);
                              onDelete(session.id);
                            }}
                            className="rounded px-1.5 py-0.5 text-xs font-medium text-red-600 dark:text-red-400"
                          >
                            确认删除
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDeleteId(null);
                            }}
                            className="rounded px-1.5 py-0.5 text-xs opacity-60"
                          >
                            取消
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          aria-label={`删除 ${displayTitle(session)}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteId(session.id);
                          }}
                          className="rounded px-1.5 py-0.5 text-xs opacity-60 hover:text-red-600 hover:opacity-100 dark:hover:text-red-400"
                        >
                          删除
                        </button>
                      )}
                    </div>
                  </div>
                </li>
              );
            })
          )}
        </ul>
      </aside>
    </>
  );
}
