"use client";

import { useEffect, useRef, useState } from "react";

import type { GatewayModel } from "@/lib/types";

interface ModelPickerProps {
  models: GatewayModel[];
  currentModel: string | null;
  loading: boolean;
  /** Called when the user picks a model; the page persists it per session. */
  onChange: (modelId: string) => void;
}

/**
 * Top-bar model switcher, fed by GET /v1/models. When the gateway
 * reports no verified models the picker shows "暂无可用模型" honestly
 * and disables sending — it never invents a model.
 */
export default function ModelPicker({
  models,
  currentModel,
  loading,
  onChange,
}: ModelPickerProps) {
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

  const label = loading
    ? "正在加载模型…"
    : models.length === 0
      ? "暂无可用模型"
      : (currentModel ?? models[0]?.id ?? "选择模型");

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={loading || models.length === 0}
        className="max-w-56 truncate rounded-lg border px-3 py-1.5 text-sm font-medium disabled:opacity-60 sm:max-w-xs"
        style={{
          background: "var(--surface)",
          borderColor: "var(--border)",
        }}
      >
        {label} ▾
      </button>
      {open && models.length > 0 ? (
        <ul
          role="listbox"
          aria-label="选择模型"
          className="absolute left-0 z-50 mt-1 max-h-72 w-64 overflow-y-auto rounded-xl border p-1 shadow-lg"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border)",
          }}
        >
          {models.map((model) => (
            <li key={model.id}>
              <button
                type="button"
                role="option"
                aria-selected={model.id === currentModel}
                onClick={() => {
                  onChange(model.id);
                  setOpen(false);
                }}
                className="w-full truncate rounded-lg px-3 py-2 text-left text-sm hover:opacity-80"
                style={
                  model.id === currentModel
                    ? { background: "var(--surface-muted)" }
                    : undefined
                }
              >
                {model.id}
                {model.id === currentModel ? " ✓" : ""}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
