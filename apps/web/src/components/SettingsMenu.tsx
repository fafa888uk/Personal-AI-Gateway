"use client";

import { useEffect, useRef, useState } from "react";

interface SettingsMenuProps {
  baseUrl: string;
  usageOpen: boolean;
  onToggleUsage: () => void;
  onLogout: () => void;
}

/**
 * Small settings popover in the top bar: shows the configured gateway
 * address, a usage-view toggle, and "退出登录" (clears credentials and
 * returns to /). No admin features live here.
 */
export default function SettingsMenu({
  baseUrl,
  usageOpen,
  onToggleUsage,
  onLogout,
}: SettingsMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (
        rootRef.current &&
        !rootRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open ]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="设置"
        className="rounded-lg border px-2.5 py-1.5 text-sm"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
        }}
      >
        ⚙️
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-1 w-72 rounded-xl border p-3 shadow-lg"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border)",
          }}
        >
          <p className="text-xs opacity-60">网关地址</p>
          <p className="mt-0.5 break-all font-mono text-sm">{baseUrl}</p>
          <button
            type="button"
            onClick={() => {
              onToggleUsage();
              setOpen(false);
            }}
            className="mt-3 w-full rounded-lg border px-3 py-2 text-left text-sm"
            style={{ borderColor: "var(--border)" }}
          >
            {usageOpen ? "隐藏用量" : "查看用量"}
          </button>
          <button
            type="button"
            onClick={onLogout}
            className="mt-2 w-full rounded-lg border px-3 py-2 text-left text-sm text-red-600 dark:text-red-400"
            style={{ borderColor: "var(--border)" }}
          >
            退出登录
          </button>
        </div>
      ) : null}
    </div>
  );
}
