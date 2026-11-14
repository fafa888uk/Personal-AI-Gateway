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

/** Default gateway URL: env override at build time, else localhost:8000. */
export function defaultGatewayUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_GATEWAY_URL;
  return fromEnv && fromEnv.trim() !== "" ? fromEnv.trim() : DEFAULT_GATEWAY_URL;
}
