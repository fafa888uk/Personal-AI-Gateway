/**
 * defaultGatewayUrl fallback tests. No network, no server.
 * Covers: build-time env override wins; in the browser a non-loopback
 * page origin wins over localhost:8000 (production, same-origin behind
 * one reverse proxy); localhost / 127.0.0.1 origins and SSR (no window)
 * fall back to localhost:8000; AdminClient with no baseUrl argument
 * talks to the page origin (the admin-login "Failed to fetch" bug).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminClient } from "../admin";
import { DEFAULT_GATEWAY_URL, defaultGatewayUrl } from "../credentials";

const ENV_KEY = "NEXT_PUBLIC_GATEWAY_URL";
let savedEnv: string | undefined;

function stubOrigin(origin: string): void {
  vi.stubGlobal("window", { location: { origin } });
}

beforeEach(() => {
  savedEnv = process.env[ENV_KEY];
  delete process.env[ENV_KEY];
});

afterEach(() => {
  vi.unstubAllGlobals();
  if (savedEnv === undefined) delete process.env[ENV_KEY];
  else process.env[ENV_KEY] = savedEnv;
});

describe("defaultGatewayUrl", () => {
  it("prefers the build-time env override, trimmed", () => {
    process.env[ENV_KEY] = "  https://ai.fafa888.uk  ";
    stubOrigin("https://other.example.com");
    expect(defaultGatewayUrl()).toBe("https://ai.fafa888.uk");
  });

  it("returns the page origin when it is not a loopback host", () => {
    stubOrigin("https://ai.fafa888.uk");
    expect(defaultGatewayUrl()).toBe("https://ai.fafa888.uk");
  });

  it("falls back to localhost:8000 for a localhost page origin (local dev)", () => {
    stubOrigin("http://localhost:3000");
    expect(defaultGatewayUrl()).toBe(DEFAULT_GATEWAY_URL);
    expect(defaultGatewayUrl()).toBe("http://localhost:8000");
  });

  it("falls back to localhost:8000 for a 127.0.0.1 page origin", () => {
    stubOrigin("http://127.0.0.1:3000");
    expect(defaultGatewayUrl()).toBe("http://localhost:8000");
  });

  it("falls back to localhost:8000 for a [::1] page origin", () => {
    stubOrigin("http://[::1]:3000");
    expect(defaultGatewayUrl()).toBe("http://localhost:8000");
  });

  it("falls back to localhost:8000 with no window (SSR)", () => {
    // No window stubbed: node environment, typeof window === "undefined".
    expect(typeof window).toBe("undefined");
    expect(defaultGatewayUrl()).toBe("http://localhost:8000");
  });

  it("treats a blank env value as unset and uses the page origin", () => {
    process.env[ENV_KEY] = "   ";
    stubOrigin("https://ai.fafa888.uk");
    expect(defaultGatewayUrl()).toBe("https://ai.fafa888.uk");
  });
});

describe("AdminClient default baseUrl", () => {
  it("with no argument, talks to the production page origin, not localhost", async () => {
    stubOrigin("https://ai.fafa888.uk");
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        seen.push(url);
        return new Response(JSON.stringify({ csrf_token: "c" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    const client = new AdminClient();
    await client.ensureCsrf();
    expect(seen).toHaveLength(1);
    expect(seen[0]).toBe("https://ai.fafa888.uk/api/v1/admin/csrf");
  });
});
