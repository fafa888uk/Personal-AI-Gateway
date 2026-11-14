// Minimal flat ESLint config (Stage D gap #2 fix): the old `next lint`
// script no longer exists in Next 15, so `npm run lint` runs ESLint
// directly. TypeScript + React rules only; no stylistic nitpicking.
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["node_modules", ".next", "out", "public/sw.js", "next-env.d.ts"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.ts", "**/*.tsx"],
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_" },
      ],
    },
  },
);
