/**
 * Credential storage — localStorage ONLY.
 *
 * Stores the gateway base URL + the gateway client key (pag_sk_...).
 * Never an upstream OpenAI key: the web client never sees one, and this
 * module must never be given one. Clearing credentials is the logout.
 */

import type { GatewayCredentials } from "./types";

export const DEFAULT_GATEWAY_URL = "http://localhost:8000";

const BASE_URL_KEY = "pag.gateway.baseUrl";
const CLIENT_KEY_KEY = "pag.gateway.clientKey";

export function loadCredentials(): GatewayCredentials | null {
  if (typeof window === "undefined") return null;
  const baseUrl = window.localStorage.getItem(BASE_URL_KEY);
  const clientKey = window.localStorage.getItem(CLIENT_KEY_KEY);
  if (!baseUrl || !clientKey) return null;
  return { baseUrl, clientKey };
}

export function saveCredentials(creds: GatewayCredentials): void {
  window.localStorage.setItem(BASE_URL_KEY, creds.baseUrl);
  window.localStorage.setItem(CLIENT_KEY_KEY, creds.clientKey);
}

/** Logout: remove stored gateway credentials. */
export function clearCredentials(): void {
  window.localStorage.removeItem(BASE_URL_KEY);
  window.localStorage.removeItem(CLIENT_KEY_KEY);
}

/**
 * Default gateway URL.
 *
 * Priority: (1) build-time NEXT_PUBLIC_GATEWAY_URL when set; (2) in the
 * browser, the page's own origin when it is not a loopback host — in
 * production the web app and the gateway are same-origin behind one
 * reverse proxy (ai.fafa888.uk), so the admin console must talk to the
 * page origin, not localhost; (3) localhost:8000 for local dev (page
 * origin localhost:3000) and for SSR (no window).
 */
export function defaultGatewayUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_GATEWAY_URL;
  if (fromEnv && fromEnv.trim() !== "") return fromEnv.trim();
  if (typeof window !== "undefined") {
    const origin = window.location?.origin;
    if (typeof origin === "string" && origin !== "") {
      let host = "";
      try {
        host = new URL(origin).hostname;
      } catch {
        host = "";
      }
      if (host !== "" && host !== "localhost" && host !== "127.0.0.1" && host !== "[::1]") {
        return origin;
      }
    }
  }
  return DEFAULT_GATEWAY_URL;
}
