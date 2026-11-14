/**
 * Shared admin-console UI bits. Same visual language as the chat app:
 * Tailwind + the theme variables in globals.css (light/dark support).
 * No decorative dead controls — every button here is wired by its caller.
 */
import { useState } from "react";

export const cardStyle: React.CSSProperties = {
  background: "var(--surface)",
  borderColor: "var(--border)",
};

export const inputStyle: React.CSSProperties = {
  background: "var(--surface-muted)",
  borderColor: "var(--border)",
};

export const inputClass =
  "w-full rounded-lg border px-3 py-2 text-sm outline-none";

export const primaryButtonClass =
  "rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50";

export function primaryButtonStyle(): React.CSSProperties {
  return { background: "var(--accent)" };
}

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return "操作失败，请重试";
}

export function Card({
  title,
  children,
}: {
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="rounded-2xl border p-4 shadow-sm sm:p-5"
      style={cardStyle}
    >
      {title ? <h2 className="text-base font-semibold">{title}</h2> : null}
      <div className={title ? "mt-3" : ""}>{children}</div>
    </section>
  );
}

export function Alert({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p
      role="alert"
      className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400"
    >
      {text}
    </p>
  );
}

export function Notice({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p
      role="status"
      className="rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300"
    >
      {text}
    </p>
  );
}

export function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-2xl border p-4 shadow-sm" style={cardStyle}>
      <p className="text-xs opacity-60">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {sub ? <p className="mt-1 text-xs opacity-60">{sub}</p> : null}
    </div>
  );
}

/** Copy button with a "已复制" feedback state. */
export function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(text);
      } else {
        throw new Error("no clipboard");
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
      window.prompt("复制以下内容：", text);
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      className="rounded-lg border px-2 py-1 text-xs"
      style={{ borderColor: "var(--border)" }}
    >
      {copied ? "已复制" : label}
    </button>
  );
}
