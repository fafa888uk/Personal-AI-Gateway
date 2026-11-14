import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Base URL of the gateway comes from runtime settings (localStorage /
  // NEXT_PUBLIC_GATEWAY_URL) — never hardcode a gateway origin here and
  // never add rewrites to a fixed gateway.
  reactStrictMode: true,
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
