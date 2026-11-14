/**
 * Gateway API client (fetch-based).
 *
 * - Auth: `Authorization: Bearer <client key>` on every authed call.
 * - Public: GET /api/v1/app/version sends NO auth header.
 * - Errors: the gateway returns `{error:{message, code}}` with an HTTP
 *   status — GatewayError surfaces the real message + status + code.
 * - The client key here is the gateway client key (pag_sk_...), never an
 *   upstream OpenAI key.
 */

import { SseParser, type ChatStreamEvent } from "./sse";
import type {
  AppVersionInfo,
  ChatMessage,
  ChatSession,
  ChatUsage,
  GatewayCredentials,
  GatewayModel,
  UsageSummary,
} from "./types";

export class GatewayError extends Error {
  constructor(
    message: string,
    public readonly code?: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "GatewayError";
  }
}

export interface ChatCompletionResult {
  text: string;
  usage: ChatUsage | null;
}

export interface StreamChatOptions {
  signal?: AbortSignal;
  /** Called for each parsed SSE event as it arrives. */
  onEvent?: (event: ChatStreamEvent) => void;
}

function normalizeBaseUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, "");
}

async function decodeError(response: Response): Promise<GatewayError> {
  const status = response.status;
  let message = `请求失败 (HTTP ${status})`;
  let code: string | undefined;
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const err = (body as Record<string, unknown>).error;
      if (typeof err === "object" && err !== null) {
        const e = err as Record<string, unknown>;
        if (typeof e.message === "string" && e.message !== "") {
          message = e.message;
        }
        if (typeof e.code === "string") code = e.code;
      } else if (typeof (body as Record<string, unknown>).message === "string") {
        message = (body as Record<string, unknown>).message as string;
      }
    }
  } catch {
    // Non-JSON error body: keep the generic message.
  }
  return new GatewayError(message, code, status);
}

export class GatewayClient {
  readonly baseUrl: string;
  private readonly clientKey: string;

  constructor(creds: GatewayCredentials) {
    this.baseUrl = normalizeBaseUrl(creds.baseUrl);
    this.clientKey = creds.clientKey;
  }

  private authedHeaders(extra: Record<string, string> = {}): Headers {
    return new Headers({
      Authorization: `Bearer ${this.clientKey}`,
      ...extra,
    });
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    authed = true,
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: authed
          ? this.authedHeaders(
              (init.headers as Record<string, string> | undefined) ?? {},
            )
          : (init.headers as HeadersInit | undefined),
      });
    } catch (err) {
      throw new GatewayError(
        err instanceof Error
          ? `无法连接网关: ${err.message}`
          : "无法连接网关",
      );
    }
    if (!response.ok) throw await decodeError(response);
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  private async jsonRequest<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    return this.request<T>(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  // ------------------------------------------------------------ public

  /** GET /api/v1/app/version — PUBLIC, no auth header. */
  async getAppVersion(): Promise<AppVersionInfo> {
    const response = await fetch(`${this.baseUrl}/api/v1/app/version`);
    if (!response.ok) throw await decodeError(response);
    return (await response.json()) as AppVersionInfo;
  }

  // ------------------------------------------------------------ models

  async listModels(): Promise<GatewayModel[]> {
    const body = await this.request<{ data: GatewayModel[] }>("/v1/models");
    return Array.isArray(body.data) ? body.data : [];
  }

  // ------------------------------------------------------------ chats

  async listChats(): Promise<ChatSession[]> {
    const body = await this.request<{ sessions: ChatSession[] }>(
      "/api/v1/chats",
    );
    return Array.isArray(body.sessions) ? body.sessions : [];
  }

  async createChat(input: { title?: string; model?: string }): Promise<ChatSession> {
    return this.jsonRequest<ChatSession>("POST", "/api/v1/chats", input);
  }

  async getChat(sessionId: number): Promise<ChatSession> {
    return this.request<ChatSession>(`/api/v1/chats/${sessionId}`);
  }

  async updateChat(
    sessionId: number,
    input: { title?: string; model?: string | null },
  ): Promise<ChatSession> {
    return this.jsonRequest<ChatSession>(
      "PATCH",
      `/api/v1/chats/${sessionId}`,
      input,
    );
  }

  async deleteChat(sessionId: number): Promise<void> {
    await this.request(`/api/v1/chats/${sessionId}`, { method: "DELETE" });
  }

  async listMessages(sessionId: number): Promise<ChatMessage[]> {
    const body = await this.request<{ messages: ChatMessage[] }>(
      `/api/v1/chats/${sessionId}/messages`,
    );
    return Array.isArray(body.messages) ? body.messages : [];
  }

  async addMessage(
    sessionId: number,
    input: {
      role: "user" | "assistant" | "system";
      content: string;
      model?: string;
      tokens_in?: number;
      tokens_out?: number;
    },
  ): Promise<ChatMessage> {
    return this.jsonRequest<ChatMessage>(
      "POST",
      `/api/v1/chats/${sessionId}/messages`,
      input,
    );
  }

  // ------------------------------------------------------------ usage

  async getUsageSummary(
    period: "today" | "month",
  ): Promise<UsageSummary> {
    return this.request<UsageSummary>(
      `/api/v1/usage/summary?period=${period}`,
    );
  }

  // ------------------------------------------------------------ chat completions

  /**
   * Non-streaming POST /v1/chat/completions. Returns the assistant text
   * plus upstream usage (prompt_tokens / completion_tokens) when present.
   */
  async chatCompletion(input: {
    model: string;
    messages: { role: string; content: string }[];
    extra?: Record<string, unknown>;
  }): Promise<ChatCompletionResult> {
    const body = await this.jsonRequest<{
      choices?: { message?: { content?: string } }[];
      usage?: { prompt_tokens?: number; completion_tokens?: number };
    }>("POST", "/v1/chat/completions", {
      model: input.model,
      messages: input.messages,
      stream: false,
      ...(input.extra ?? {}),
    });
    const text =
      body.choices?.[0]?.message?.content ?? "";
    return {
      text,
      usage: body.usage
        ? {
            tokensIn: body.usage.prompt_tokens ?? null,
            tokensOut: body.usage.completion_tokens ?? null,
          }
        : null,
    };
  }

  /**
   * Streaming POST /v1/chat/completions via fetch + ReadableStream.
   * Returns the full assembled text plus usage when the server sent it.
   * Pass an AbortSignal (from AbortController) to stop the stream —
   * aborting is the stop button.
   */
  async streamChatCompletion(
    input: {
      model: string;
      messages: { role: string; content: string }[];
      extra?: Record<string, unknown>;
    },
    options: StreamChatOptions = {},
  ): Promise<ChatCompletionResult> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/v1/chat/completions`, {
        method: "POST",
        headers: this.authedHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          model: input.model,
          messages: input.messages,
          stream: true,
          ...(input.extra ?? {}),
        }),
        signal: options.signal,
      });
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        throw new GatewayError("已停止");
      }
      throw new GatewayError(
        err instanceof Error ? `无法连接网关: ${err.message}` : "无法连接网关",
      );
    }
    if (!response.ok) throw await decodeError(response);
    if (!response.body) {
      throw new GatewayError("网关未返回流式响应");
    }

    const parser = new SseParser();
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let text = "";
    let usage: ChatUsage | null = null;

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        const events = parser.feed(decoder.decode(value, { stream: true }));
        for (const event of events) {
          options.onEvent?.(event);
          if (event.kind === "delta") text += event.delta;
          else if (event.kind === "usage") {
            usage = { tokensIn: event.tokensIn, tokensOut: event.tokensOut };
          } else if (event.kind === "error") {
            throw event.error;
          } else if (event.kind === "done") {
            // End marker: keep reading until the body closes.
          }
        }
      }
      for (const event of parser.finish()) {
        options.onEvent?.(event);
        if (event.kind === "delta") text += event.delta;
        else if (event.kind === "usage") {
          usage = { tokensIn: event.tokensIn, tokensOut: event.tokensOut };
        } else if (event.kind === "error") {
          throw event.error;
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        throw new GatewayError("已停止");
      }
      throw err;
    } finally {
      reader.releaseLock();
    }
    return { text, usage };
  }
}
