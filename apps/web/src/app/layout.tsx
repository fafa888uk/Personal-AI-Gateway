import type { Metadata, Viewport } from "next";

import "./globals.css";
import { ServiceWorkerRegister, ThemeInit } from "./init";

export const metadata: Metadata = {
  title: "Personal AI Gateway",
  description: "Personal AI Gateway — 私人 AI 聊天与模型中转",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "AI Gateway",
  },
  icons: {
    icon: "/icon.svg",
    apple: "/icon-180.png",
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f7fb" },
    { media: "(prefers-color-scheme: dark)", color: "#1c1c1e" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-dvh antialiased">
        <ThemeInit />
        <ServiceWorkerRegister />
        {children}
      </body>
    </html>
  );
}
