/**
 * Theme helpers. The stored value is "light" | "dark" in localStorage
 * key `pag.theme`; when nothing is stored the OS preference wins.
 * Applied by toggling the `dark` class on <html> (see init.tsx
 * ThemeInit, which applies the same rule on first paint).
 */

export type ThemeChoice = "light" | "dark";

const THEME_KEY = "pag.theme";

export function getStoredTheme(): ThemeChoice | null {
  if (typeof window === "undefined") return null;
  const stored = window.localStorage.getItem(THEME_KEY);
  return stored === "dark" || stored === "light" ? stored : null;
}

export function resolveTheme(): ThemeChoice {
  const stored = getStoredTheme();
  if (stored) return stored;
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function applyTheme(theme: ThemeChoice): void {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", theme === "dark");
  window.localStorage.setItem(THEME_KEY, theme);
}

export function toggleTheme(current: ThemeChoice): ThemeChoice {
  const next: ThemeChoice = current === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}
