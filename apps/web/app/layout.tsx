import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Huoke Agent",
  description: "AI 获客线索发现 Agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

