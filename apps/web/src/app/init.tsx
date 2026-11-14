"use client";

import { useEffect } from "react";

/** Apply the `dark` class on <html> from localStorage, else the OS preference. */
export function ThemeInit() {
  useEffect(() => {
    const stored = window.localStorage.getItem("pag.theme");
    const prefersDark = window.matchMedia(
      "(prefers-color-scheme: dark)",
    ).matches;
    const dark = stored ? stored === "dark" : prefersDark;
    document.documentElement.classList.toggle("dark", dark);
  }, []);
  return null;
}

/** Register the service worker in production only. */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (
      process.env.NODE_ENV !== "production" ||
      typeof window === "undefined" ||
      !("serviceWorker" in navigator)
    ) {
      return;
    }
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Offline shell is best-effort; a failed registration must not
      // break the app.
    });
  }, []);
  return null;
}
