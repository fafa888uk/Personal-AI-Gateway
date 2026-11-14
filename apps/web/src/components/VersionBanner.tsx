"use client";

import { useEffect, useState } from "react";

import type { GatewayClient } from "@/lib/api";
import { isNewerVersion } from "@/lib/semver";
import { WEB_VERSION } from "@/lib/version";

interface VersionBannerProps {
  client: GatewayClient | null;
}

/**
 * Update prompt for the web client. Calls public GET
 * /api/v1/app/version; when the server is unconfigured
 * (`configured: false`) it renders nothing. When the server reports a
 * `web` platform release newer than this build (WEB_VERSION), it shows
 * the version + release notes and a "刷新获取新版" button that asks
 * the service worker to skip waiting and reloads the page. It never
 * fakes a version and never compares against the gateway version.
 */
export default function VersionBanner({ client }: VersionBannerProps) {
  const [latest, setLatest] = useState<string | null>(null);
  const [notes, setNotes] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    void client
      .getAppVersion()
      .then((info) => {
        if (cancelled) return;
        if (!info.configured) return;
        const web = info.platforms?.web;
        if (web && isNewerVersion(WEB_VERSION, web.version)) {
          setLatest(web.version);
          setNotes(web.release_notes ?? null);
        }
      })
      .catch(() => {
        // Version check is best-effort; a failed check must not block chat.
      });
    return () => {
      cancelled = true;
    };
  }, [client]);

  if (!latest) return null;

  async function refreshForUpdate() {
    setUpdating(true);
    try {
      if ("serviceWorker" in navigator) {
        const reg = await navigator.serviceWorker.getRegistration();
        reg?.waiting?.postMessage({ type: "SKIP_WAITING" });
      }
    } catch {
      // No waiting worker: a plain reload still fetches the new shell.
    }
    window.location.reload();
  }

  return (
    <div
      role="status"
      className="flex flex-col gap-2 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
      style={{
        background: "var(--accent-soft)",
        borderColor: "var(--border)",
      }}
    >
      <div className="text-sm">
        <p className="font-medium">
          有新版本 {latest} 可用（当前 {WEB_VERSION}）
        </p>
        {notes ? <p className="mt-0.5 whitespace-pre-wrap opacity-80">{notes}</p> : null}
      </div>
      <button
        type="button"
        onClick={refreshForUpdate}
        disabled={updating}
        className="shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        style={{ background: "var(--accent)" }}
      >
        {updating ? "正在刷新…" : "刷新获取新版"}
      </button>
    </div>
  );
}
