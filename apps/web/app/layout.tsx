import "./globals.css";
import type { Metadata } from "next";
import { AppShell } from "../components/app-shell";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Huoke - 获客线索发现",
  description: "外贸获客线索发现平台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
