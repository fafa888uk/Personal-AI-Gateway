/**
 * Data models for the Personal AI Gateway web client.
 *
 * Field names mirror the real gateway API — see apps/api/gateway/main.py
 * (list_models, _session_view, _message_view, usage_summary, app_version)
 * and apps/flutter/lib/models.dart. Nothing here invents a model status,
 * a version, a cost or a token count: values come from the server, and
 * missing values stay missing (null/undefined), never guessed.
 */

/** One model from GET /v1/models — `{object:"list", data:[{id, object, created, owned_by}]}`. */
export interface GatewayModel {
  id: string;
  object?: string;
  created?: number;
  owned_by?: string;
}

/** One chat session from GET /api/v1/chats. */
export interface ChatSession {
  id: number;
  title: string;
  model: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** One message from GET /api/v1/chats/{id}/messages. */
export interface ChatMessage {
  id: number | null;
  session_id?: number;
  role: "user" | "assistant" | "system" | string;
  content: string;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  created_at: string | null;
}

/** Per-model usage row from GET /api/v1/usage/summary. */
export interface UsageByModel {
  model: string;
  requests: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
}

/**
 * Usage summary from GET /api/v1/usage/summary.
 * cost_status is exactly what the gateway computes:
 * - "ok": every counted cost is exact.
 * - "price_not_configured": at least one record has no price — the cost
 *   shown is a partial sum, never a complete total.
 * - "not_obtained": at least one record has no upstream usage — the cost
 *   shown is a partial sum, never a complete total.
 */
export interface UsageSummary {
  period: "today" | "month" | string;
  requests: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  cost_status: "ok" | "price_not_configured" | "not_obtained" | string;
  by_model: UsageByModel[];
}

/** One platform entry from GET /api/v1/app/version. */
export interface PlatformRelease {
  version: string;
  release_date?: string | null;
  download_url: string;
  sha256?: string | null;
  release_notes?: string | null;
}

/**
 * Release info from GET /api/v1/app/version. When `configured` is false
 * the server has no release info and the UI must say so — never fake a
 * version.
 */
export interface AppVersionInfo {
  configured: boolean;
  version: string | null;
  gateway_version?: string | null;
  platforms: Partial<Record<"ios" | "windows" | "macos" | "web", PlatformRelease>>;
  note?: string;
}

/** Credentials the user enters on the login screen. Client key only — never an upstream OpenAI key. */
export interface GatewayCredentials {
  baseUrl: string;
  clientKey: string;
}

/** Token usage reported by the server for one completed reply. */
export interface ChatUsage {
  tokensIn: number | null;
  tokensOut: number | null;
}
