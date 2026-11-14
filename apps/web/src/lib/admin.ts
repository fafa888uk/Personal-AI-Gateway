/**
 * Admin API client for the Personal AI Gateway admin console.
 *
 * Auth is a session cookie set by the gateway (POST /api/v1/admin/login),
 * so every call uses `credentials: "include"` and sends NO Authorization
 * header and NO upstream OpenAI key — the web app never sees one.
 *
 * Mutating calls send `X-CSRF-Token`, fetched once per admin session
 * from GET /api/v1/admin/csrf. Field names mirror the backend contract
 * exactly; nothing here invents a model status, a cost or a token count.
 */

import { defaultGatewayUrl } from "./credentials";

export class AdminError extends Error {
  constructor(
    message: string,
    public readonly code?: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "AdminError";
  }
}

export type VerificationStatus =
  | "pending"
  | "available"
  | "unavailable"
  | "forbidden"
  | "rate_limited"
  | string;

export interface AdminModel {
  canonical_name: string;
  aliases: string[];
  enabled: boolean;
  is_default: boolean;
  sort_order: number;
  pinned_group: string | null;
  cap_responses: boolean;
  cap_chat: boolean;
  cap_streaming: boolean;
  cap_tools: boolean;
  cap_image: boolean;
  verification_status: VerificationStatus;
  last_verified_at: string | null;
  verification_method: string | null;
  last_error: string | null;
  in_upstream: boolean;
}

export interface AdminModelsResponse {
  models: AdminModel[];
  upstream_only: string[];
}

export type ClientType = "web" | "codex" | "vscode" | "other" | string;

export interface ClientKey {
  id: number | string;
  name: string;
  key_prefix: string;
  client_type: ClientType;
  allowed_models: string[];
  rate_limit_per_min: number | null;
  concurrency_limit: number | null;
  monthly_budget_usd: number | null;
  enabled: boolean;
  last_used_at: string | null;
  last_error: string | null;
  created_at: string | null;
}

export interface ClientKeyWithRaw extends ClientKey {
  raw_key: string;
}

export interface CreateClientKeyInput {
  name: string;
  client_type: ClientType;
  allowed_models: string[];
  rate_limit_per_min?: number | null;
  concurrency_limit?: number | null;
  monthly_budget_usd?: number | null;
}

export type UsageCostStatus = "exact" | "not_obtained" | "price_not_configured" | string;

export interface UsageStats {
  requests: number;
  success_count: number;
  error_count: number;
  success_rate: number;
  error_rate: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  tokens_in: number;
  tokens_out: number;
  tokens_total: number;
  tokens_cached: number;
  tokens_reasoning: number;
  cost_usd: number;
  cost_status: UsageCostStatus;
  model_ranking: { model: string; requests: number; tokens: number; cost_usd: number }[];
  client_ranking: { client_name: string; requests: number; tokens: number; cost_usd: number }[];
  daily_trend: { date: string; requests: number; tokens: number; cost_usd: number }[];
  error_distribution: { error_type: string; count: number }[];
  budgets: {
    global_daily_usd: number | null;
    global_monthly_usd: number | null;
    spent_today: number;
    spent_month: number;
    alerts: string[];
  };
}

export interface AdminRequest {
  trace_id: string;
  model?: string | null;
  client_name?: string | null;
  status?: string | null;
  status_code?: number | null;
  latency_ms?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  cost_usd?: number | null;
  error?: string | null;
  created_at?: string | null;
  [key: string]: unknown;
}

export interface PricingRule {
  model: string;
  input_usd_per_1m: number | null;
  output_usd_per_1m: number | null;
  cached_input_usd_per_1m: number | null;
  reasoning_usd_per_1m: number | null;
  updated_at: string | null;
}

export interface AdminSettings {
  budgets: { daily_usd: number | null; monthly_usd: number | null };
  pricing: PricingRule[];
  retention_days: number | null;
  version: Record<string, unknown> | null;
}

export interface AuditEntry {
  id?: number | string;
  actor?: string | null;
  action?: string | null;
  target?: string | null;
  detail?: string | null;
  created_at?: string | null;
  [key: string]: unknown;
}

function normalizeBaseUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, "");
}

async function decodeError(response: Response): Promise<AdminError> {
  const status = response.status;
  let message = `请求失败 (HTTP ${status})`;
  let code: string | undefined;
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const err = (body as Record<string, unknown>).error;
      if (typeof err === "object" && err !== null) {
        const e = err as Record<string, unknown>;
        if (typeof e.message === "string" && e.message !== "") message = e.message;
        if (typeof e.code === "string") code = e.code;
      } else if (typeof (body as Record<string, unknown>).message === "string") {
        message = (body as Record<string, unknown>).message as string;
      } else if (typeof (body as Record<string, unknown>).detail === "string") {
        message = (body as Record<string, unknown>).detail as string;
      }
    }
  } catch {
    // Non-JSON error body: keep the generic message.
  }
  return new AdminError(message, code, status);
}

/**
 * Human-readable login failure. 401 = wrong credentials, 429 = too many
 * failed attempts (5 per 15 min), 503 = admin not configured on the server.
 */
export function loginErrorMessage(err: unknown): string {
  if (err instanceof AdminError) {
    if (err.status === 401) return "用户名或密码错误，请重试";
    if (err.status === 429) return "登录失败次数过多，请 15 分钟后再试";
    if (err.status === 503) return "管理员账号尚未配置，请先在服务器上配置管理员账号";
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "登录失败，请重试";
}

/** Minimum new-password length, mirroring the backend rule. */
export const MIN_ADMIN_PASSWORD_LENGTH = 12;

/**
 * Client-side validation for the change-password form. Returns the
 * first problem as a readable message, or null when the input is
 * acceptable. Mirrors the backend rules (new password >= 12 chars,
 * different from the current one) so the user gets feedback without
 * a round trip; the backend still enforces them.
 */
export function validatePasswordChange(
  currentPassword: string,
  newPassword: string,
  confirmPassword: string,
): string | null {
  if (!currentPassword) return "请填写现密码";
  if (!newPassword) return "请填写新密码";
  if (newPassword.length < MIN_ADMIN_PASSWORD_LENGTH)
    return `新密码至少 ${MIN_ADMIN_PASSWORD_LENGTH} 位`;
  if (newPassword === currentPassword) return "新密码不能与现密码相同";
  if (newPassword !== confirmPassword) return "两次输入的新密码不一致";
  return null;
}

/**
 * Change-password failure message. 401 means the current password is
 * wrong; anything else is shown exactly as the backend reported it.
 */
export function changePasswordErrorMessage(err: unknown): string {
  if (err instanceof AdminError) {
    if (err.status === 401) return "现密码不正确，请重试";
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "修改密码失败，请重试";
}

/**
 * Cost-status label for the admin usage dashboard. Only "exact" is a
 * complete total; anything else is a partial sum and must be labelled
 * as such — never presented as exact.
 */
export function adminCostStatusLabel(costStatus: string): string {
  switch (costStatus) {
    case "exact":
      return "费用为精确合计（已按真实用量与定价计算）";
    case "price_not_configured":
      return "价格未配置：费用为不完整合计，请勿视为精确总额";
    case "not_obtained":
      return "部分用量未获取：费用为不完整合计，请勿视为精确总额";
    case "partial":
      return "部分费用未计入（有用量未获取或价格未配置）：费用为不完整合计，请勿视为精确总额";
    default:
      return `费用状态未知（${costStatus}）：费用可能不完整，请勿视为精确总额`;
  }
}

/** True only when the cost is a complete exact total. */
export function adminCostIsExact(costStatus: string): boolean {
  return costStatus === "exact";
}

/**
 * A model counts as verified ONLY when the backend verified it with a
 * real request (verification_status "available" + method "real").
 * Anything else — pending, mock/test verification, unavailable — is
 * never rendered as verified.
 */
export function isModelVerified(model: AdminModel): boolean {
  return (
    model.verification_status === "available" &&
    model.verification_method === "real"
  );
}

export function verificationBadgeLabel(model: AdminModel): string {
  switch (model.verification_status) {
    case "available":
      return model.verification_method === "real"
        ? "已验证（真实请求）"
        : "测试验证（非真实请求）";
    case "pending":
      return "未验证";
    case "unavailable":
      return "不可用";
    case "forbidden":
      return "无权限";
    case "rate_limited":
      return "限流";
    default:
      return `未知状态：${model.verification_status}`;
  }
}

export function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `$${value.toFixed(4)}`;
}

// ---------------------------------------------------------------------------
// Backend response normalization.
//
// The gateway's /api/v1/admin/* responses use their own envelope shapes
// (nested `capabilities`, `tokens: {in,out,...}`, `per_model` / `per_client`
// / `errors` / `budget`, `pricing_rules`, `{id}` upstream entries, and a
// `cost_status` breakdown object). The pages consume the flat shapes in the
// types above, so every admin fetch normalizes here — in one place — instead
// of trusting either side's field names. All mappings are defensive:
// unknown/missing fields fall back to empty values, never to invented data.
// ---------------------------------------------------------------------------

function asRecord(v: unknown): Record<string, unknown> {
  return typeof v === "object" && v !== null ? (v as Record<string, unknown>) : {};
}

function asNum(v: unknown, fallback = 0): number {
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
}

function asStr(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function asArr(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

/** Backend model rows nest capabilities; the UI reads flat cap_* fields. */
export function normalizeAdminModel(raw: unknown): AdminModel {
  const b = asRecord(raw);
  const caps = asRecord(b.capabilities);
  const cap = (flat: unknown, nested: unknown, fallback: boolean): boolean =>
    nested !== undefined ? nested === true : flat !== undefined ? flat === true : fallback;
  return {
    canonical_name: asStr(b.canonical_name) ?? "",
    aliases: asArr(b.aliases).filter((a): a is string => typeof a === "string"),
    enabled: b.enabled === true,
    is_default: b.is_default === true,
    sort_order: asNum(b.sort_order),
    pinned_group: asStr(b.pinned_group),
    cap_responses: cap(b.cap_responses, caps.responses, true),
    cap_chat: cap(b.cap_chat, caps.chat, true),
    cap_streaming: cap(b.cap_streaming, caps.streaming, true),
    cap_tools: cap(b.cap_tools, caps.tools, true),
    cap_image: cap(b.cap_image, caps.image, false),
    verification_status: (asStr(b.verification_status) ?? "pending") as AdminModel["verification_status"],
    last_verified_at: asStr(b.last_verified_at),
    verification_method: asStr(b.verification_method),
    last_error: asStr(b.last_error),
    in_upstream: b.in_upstream === true,
  };
}

/** Backend request rows use `client` / `error_type`; pages read `client_name` / `error` / `status`. */
export function normalizeAdminRequest(raw: unknown): AdminRequest {
  const b = asRecord(raw);
  const statusCode = typeof b.status_code === "number" ? b.status_code : null;
  return {
    ...b,
    trace_id: asStr(b.trace_id) ?? "",
    client_name: asStr(b.client_name) ?? asStr(b.client) ?? "unknown",
    status: asStr(b.status) ?? (statusCode !== null ? String(statusCode) : null),
    status_code: statusCode,
    model: asStr(b.model),
    latency_ms: typeof b.latency_ms === "number" ? b.latency_ms : null,
    tokens_in: typeof b.tokens_in === "number" ? b.tokens_in : null,
    tokens_out: typeof b.tokens_out === "number" ? b.tokens_out : null,
    cost_usd: typeof b.cost_usd === "number" ? b.cost_usd : null,
    error: asStr(b.error) ?? asStr(b.error_type),
    created_at: asStr(b.created_at),
  };
}

/**
 * Summarize the backend's per-record cost breakdown
 * {exact, not_obtained, price_not_configured} (counts) into one status
 * string. A mixed result is "partial" — never "exact".
 */
export function summarizeCostStatus(raw: unknown): string {
  if (typeof raw === "string") return raw;
  const b = asRecord(raw);
  const exact = asNum(b.exact);
  const notObtained = asNum(b.not_obtained);
  const noPrice = asNum(b.price_not_configured);
  if (exact === 0 && notObtained === 0 && noPrice === 0) return "exact";
  if (exact > 0 && notObtained === 0 && noPrice === 0) return "exact";
  if (noPrice > 0 && exact === 0 && notObtained === 0) return "price_not_configured";
  if (notObtained > 0 && exact === 0 && noPrice === 0) return "not_obtained";
  return "partial";
}

export function normalizeUsageStats(raw: unknown): UsageStats {
  const b = asRecord(raw);
  const tokens = asRecord(b.tokens);
  const tokensIn = asNum(b.tokens_in ?? tokens.in);
  const tokensOut = asNum(b.tokens_out ?? tokens.out);
  const rank = (v: unknown): UsageStats["model_ranking"] =>
    asArr(v).map((e) => {
      const r = asRecord(e);
      return {
        model: asStr(r.model) ?? "unknown",
        requests: asNum(r.requests),
        tokens: asNum(
          r.tokens ?? (asNum(r.tokens_in) + asNum(r.tokens_out)),
        ),
        cost_usd: asNum(r.cost_usd),
      };
    });
  const modelRanking = rank(b.per_model ?? b.model_ranking);
  const clientRanking = asArr(b.per_client ?? b.client_ranking).map((e) => {
    const r = asRecord(e);
    return {
      client_name: asStr(r.client_name) ?? asStr(r.client) ?? "unknown",
      requests: asNum(r.requests),
      tokens: asNum(r.tokens ?? (asNum(r.tokens_in) + asNum(r.tokens_out))),
      cost_usd: asNum(r.cost_usd),
    };
  });
  const errorDistribution = asArr(b.errors ?? b.error_distribution).map((e) => {
    const r = asRecord(e);
    const statusCode = typeof r.status_code === "number" ? r.status_code : null;
    return {
      error_type:
        asStr(r.error_type) ??
        (statusCode !== null ? `HTTP ${statusCode}` : "unknown"),
      count: asNum(r.count),
    };
  });
  const dailyTrend = asArr(b.daily_trend).map((e) => {
    const r = asRecord(e);
    return {
      date: asStr(r.date) ?? "",
      requests: asNum(r.requests),
      tokens: asNum(r.tokens ?? (asNum(r.tokens_in) + asNum(r.tokens_out))),
      cost_usd: asNum(r.cost_usd),
    };
  });
  const budget = asRecord(b.budget ?? b.budgets);
  const alerts = asArr(budget.alerts).filter(
    (a): a is string => typeof a === "string",
  );
  return {
    requests: asNum(b.requests),
    success_count: asNum(b.success_count),
    error_count: asNum(b.error_count),
    success_rate: asNum(b.success_rate),
    error_rate: asNum(b.error_rate),
    avg_latency_ms: typeof b.avg_latency_ms === "number" ? b.avg_latency_ms : null,
    p95_latency_ms: typeof b.p95_latency_ms === "number" ? b.p95_latency_ms : null,
    tokens_in: tokensIn,
    tokens_out: tokensOut,
    tokens_total: asNum(b.tokens_total ?? tokens.total ?? tokensIn + tokensOut),
    tokens_cached: asNum(b.tokens_cached ?? tokens.cached),
    tokens_reasoning: asNum(b.tokens_reasoning ?? tokens.reasoning),
    cost_usd: asNum(b.cost_usd),
    cost_status: summarizeCostStatus(b.cost_status),
    model_ranking: modelRanking,
    client_ranking: clientRanking,
    daily_trend: dailyTrend,
    error_distribution: errorDistribution,
    budgets: {
      global_daily_usd:
        typeof budget.global_daily_usd === "number" ? budget.global_daily_usd : null,
      global_monthly_usd:
        typeof budget.global_monthly_usd === "number" ? budget.global_monthly_usd : null,
      spent_today: asNum(budget.spent_today),
      spent_month: asNum(budget.spent_month),
      alerts,
    },
  };
}

export function normalizeAdminSettings(raw: unknown): AdminSettings {
  const b = asRecord(raw);
  const budgets = asRecord(b.budgets);
  const rules = asArr(b.pricing_rules ?? b.pricing).map((e) => {
    const r = asRecord(e);
    return {
      model: asStr(r.model) ?? "",
      input_usd_per_1m: typeof r.input_usd_per_1m === "number" ? r.input_usd_per_1m : null,
      output_usd_per_1m: typeof r.output_usd_per_1m === "number" ? r.output_usd_per_1m : null,
      cached_input_usd_per_1m:
        typeof r.cached_input_usd_per_1m === "number" ? r.cached_input_usd_per_1m : null,
      reasoning_usd_per_1m:
        typeof r.reasoning_usd_per_1m === "number" ? r.reasoning_usd_per_1m : null,
      updated_at: asStr(r.updated_at),
    };
  });
  return {
    budgets: {
      daily_usd:
        typeof budgets.daily_usd === "number"
          ? budgets.daily_usd
          : typeof budgets.global_daily_usd === "number"
            ? budgets.global_daily_usd
            : null,
      monthly_usd:
        typeof budgets.monthly_usd === "number"
          ? budgets.monthly_usd
          : typeof budgets.global_monthly_usd === "number"
            ? budgets.global_monthly_usd
            : null,
    },
    pricing: rules,
    retention_days: typeof b.retention_days === "number" ? b.retention_days : null,
    version: asRecord(b.version),
  };
}

/** Translate the UI's AdminSettings patch into the backend's field names. */
export function toBackendSettings(
  patch: Partial<Pick<AdminSettings, "budgets" | "pricing" | "retention_days">>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (patch.budgets !== undefined) {
    out.budgets = {
      global_daily_usd: patch.budgets.daily_usd,
      global_monthly_usd: patch.budgets.monthly_usd,
    };
  }
  if (patch.pricing !== undefined) out.pricing_rules = patch.pricing;
  if (patch.retention_days !== undefined) out.retention_days = patch.retention_days;
  return out;
}

export class AdminClient {
  readonly baseUrl: string;
  private csrfToken: string | null = null;
  private csrfPromise: Promise<string> | null = null;

  constructor(baseUrl?: string) {
    this.baseUrl = normalizeBaseUrl(baseUrl ?? defaultGatewayUrl());
  }

  /** Fetch the CSRF token once per session (sets the pag_csrf cookie). */
  async ensureCsrf(): Promise<string> {
    if (this.csrfToken) return this.csrfToken;
    if (!this.csrfPromise) {
      this.csrfPromise = (async () => {
        const body = await this.request<{ csrf_token: string }>(
          "/api/v1/admin/csrf",
          { method: "GET" },
          false,
        );
        if (!body.csrf_token) throw new AdminError("网关未返回 CSRF 令牌");
        this.csrfToken = body.csrf_token;
        return body.csrf_token;
      })().catch((err) => {
        this.csrfPromise = null;
        throw err;
      });
    }
    return this.csrfPromise;
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    mutating = false,
  ): Promise<T> {
    const headers = new Headers(init.headers as HeadersInit | undefined);
    if (mutating) {
      const token = await this.ensureCsrf();
      headers.set("X-CSRF-Token", token);
    }
    if (init.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers,
        credentials: "include",
      });
    } catch (err) {
      throw new AdminError(
        err instanceof Error ? `无法连接网关: ${err.message}` : "无法连接网关",
      );
    }
    if (!response.ok) throw await decodeError(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  private jsonRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
    return this.request<T>(
      path,
      {
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
      },
      true,
    );
  }

  // ------------------------------------------------------------ auth

  async login(username: string, password: string): Promise<{ ok: boolean; username: string }> {
    // Best-effort CSRF fetch first (the login endpoint may itself be
    // CSRF-protected); a failure here must not block the login attempt.
    try {
      await this.ensureCsrf();
    } catch {
      // Fall through and attempt login without a token.
    }
    return this.request<{ ok: boolean; username: string }>(
      "/api/v1/admin/login",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      },
      false,
    );
  }

  async logout(): Promise<void> {
    await this.jsonRequest("POST", "/api/v1/admin/logout");
    this.csrfToken = null;
    this.csrfPromise = null;
  }

  /**
   * Rotate the admin password. The backend revokes EVERY session
   * (including this one) and clears the session cookies, so the
   * caller must send the user back to /admin/login afterwards.
   */
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await this.jsonRequest("POST", "/api/v1/admin/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    });
    this.csrfToken = null;
    this.csrfPromise = null;
  }

  async me(): Promise<{ authenticated: boolean; username: string | null }> {
    return this.request("/api/v1/admin/me", { method: "GET" }, false);
  }

  // ------------------------------------------------------------ models

  async listModels(): Promise<AdminModelsResponse> {
    const body = await this.request<unknown>("/api/v1/admin/models", { method: "GET" }, false);
    if (Array.isArray(body)) return { models: body.map(normalizeAdminModel), upstream_only: [] };
    if (typeof body === "object" && body !== null) {
      const b = body as Record<string, unknown>;
      const rawModels = Array.isArray(b.models)
        ? b.models
        : Array.isArray(b.data)
          ? b.data
          : [];
      // Backend sends upstream_only as [{id: name}] objects; the UI needs strings.
      const upstreamOnly = asArr(b.upstream_only).map((e) => {
        if (typeof e === "string") return e;
        return asStr(asRecord(e).id) ?? "";
      }).filter(Boolean);
      return { models: rawModels.map(normalizeAdminModel), upstream_only: upstreamOnly };
    }
    return { models: [], upstream_only: [] };
  }

  async updateModel(
    canonical: string,
    patch: Partial<
      Pick<
        AdminModel,
        | "enabled"
        | "is_default"
        | "aliases"
        | "sort_order"
        | "pinned_group"
        | "cap_responses"
        | "cap_chat"
        | "cap_streaming"
        | "cap_tools"
        | "cap_image"
      >
    >,
  ): Promise<AdminModel> {
    const body = await this.jsonRequest<unknown>(
      "PATCH",
      `/api/v1/admin/models/${encodeURIComponent(canonical)}`,
      patch,
    );
    return normalizeAdminModel(body);
  }

  async verifyModel(canonical: string): Promise<AdminModel & { cost_warning?: string }> {
    const body = await this.jsonRequest<unknown>(
      "POST",
      `/api/v1/admin/models/${encodeURIComponent(canonical)}/verify`,
    );
    // Backend wraps the updated row: {model, verification_http_status,
    // verification_method, cost_warning, note}. Unwrap it for the table.
    const b = asRecord(body);
    const model = normalizeAdminModel(b.model ?? body);
    return { ...model, cost_warning: asStr(b.cost_warning) ?? undefined };
  }

  // ------------------------------------------------------------ client keys

  async listClientKeys(): Promise<ClientKey[]> {
    const body = await this.request<unknown>("/api/v1/admin/client-keys", { method: "GET" }, false);
    if (Array.isArray(body)) return body as ClientKey[];
    if (typeof body === "object" && body !== null) {
      const b = body as Record<string, unknown>;
      if (Array.isArray(b.client_keys)) return b.client_keys as ClientKey[];
      if (Array.isArray(b.keys)) return b.keys as ClientKey[];
      if (Array.isArray(b.data)) return b.data as ClientKey[];
    }
    return [];
  }

  async createClientKey(input: CreateClientKeyInput): Promise<ClientKeyWithRaw> {
    return this.jsonRequest<ClientKeyWithRaw>("POST", "/api/v1/admin/client-keys", input);
  }

  async updateClientKey(
    id: number | string,
    patch: Partial<
      Pick<
        ClientKey,
        | "name"
        | "client_type"
        | "allowed_models"
        | "rate_limit_per_min"
        | "concurrency_limit"
        | "monthly_budget_usd"
        | "enabled"
      >
    >,
  ): Promise<ClientKey> {
    return this.jsonRequest<ClientKey>(
      "PATCH",
      `/api/v1/admin/client-keys/${encodeURIComponent(String(id))}`,
      patch,
    );
  }

  async revokeClientKey(id: number | string): Promise<ClientKey> {
    return this.jsonRequest<ClientKey>(
      "POST",
      `/api/v1/admin/client-keys/${encodeURIComponent(String(id))}/revoke`,
    );
  }

  async regenerateClientKey(id: number | string): Promise<ClientKeyWithRaw> {
    return this.jsonRequest<ClientKeyWithRaw>(
      "POST",
      `/api/v1/admin/client-keys/${encodeURIComponent(String(id))}/regenerate`,
    );
  }

  // ------------------------------------------------------------ usage

  async getUsage(period: "today" | "yesterday" | "month"): Promise<UsageStats> {
    const body = await this.request<unknown>(
      `/api/v1/admin/usage?period=${period}`,
      { method: "GET" },
      false,
    );
    return normalizeUsageStats(body);
  }

  // ------------------------------------------------------------ requests / diagnostics

  async listRequests(limit = 50, errorOnly = false): Promise<AdminRequest[]> {
    const body = await this.request<unknown>(
      `/api/v1/admin/requests?limit=${limit}&error_only=${errorOnly}`,
      { method: "GET" },
      false,
    );
    if (Array.isArray(body)) return body.map(normalizeAdminRequest);
    if (typeof body === "object" && body !== null) {
      const b = body as Record<string, unknown>;
      if (Array.isArray(b.requests)) return b.requests.map(normalizeAdminRequest);
      if (Array.isArray(b.data)) return b.data.map(normalizeAdminRequest);
    }
    return [];
  }

  async getRequest(traceId: string): Promise<AdminRequest> {
    const body = await this.request<unknown>(
      `/api/v1/admin/requests/${encodeURIComponent(traceId)}`,
      { method: "GET" },
      false,
    );
    return normalizeAdminRequest(body);
  }

  // ------------------------------------------------------------ settings / audit

  async getSettings(): Promise<AdminSettings> {
    const body = await this.request<unknown>("/api/v1/admin/settings", { method: "GET" }, false);
    return normalizeAdminSettings(body);
  }

  async updateSettings(
    patch: Partial<Pick<AdminSettings, "budgets" | "pricing" | "retention_days">>,
  ): Promise<AdminSettings> {
    const body = await this.jsonRequest<unknown>(
      "PUT",
      "/api/v1/admin/settings",
      toBackendSettings(patch),
    );
    return normalizeAdminSettings(body);
  }

  async listAudit(limit = 50): Promise<AuditEntry[]> {
    const body = await this.request<unknown>(
      `/api/v1/admin/audit?limit=${limit}`,
      { method: "GET" },
      false,
    );
    if (Array.isArray(body)) return body as AuditEntry[];
    if (typeof body === "object" && body !== null) {
      const b = body as Record<string, unknown>;
      if (Array.isArray(b.entries)) return b.entries as AuditEntry[];
      if (Array.isArray(b.audit)) return b.audit as AuditEntry[];
      if (Array.isArray(b.data)) return b.data as AuditEntry[];
    }
    return [];
  }
}
