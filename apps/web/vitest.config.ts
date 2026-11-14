import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  test: {
    // Default environment is node (pure-logic tests). Component tests
    // opt into jsdom with a `/** @vitest-environment jsdom */` header.
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test-setup.ts"],
  },
  esbuild: {
    // Automatic JSX runtime so test files can use JSX without importing React.
    jsx: "automatic",
  },
  resolve: {
    alias: {
      "@": path.resolve(root, "src"),
    },
  },
});
