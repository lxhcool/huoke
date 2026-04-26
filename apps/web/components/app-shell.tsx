"use client";

import React, { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  Search, Settings, CircleCheck, Circle, AlertTriangle,
} from "lucide-react";

import type {
  SourceAuthProvider,
  SourceAuthProviderListResponse,
} from "../lib/types";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

const sourceAuthStatusStorageKey = "huoke.sourceAuthStatus.v1";
const aiConfigStorageKey = "huoke.aiConfig.v1";

const fallbackSourceProviders: SourceAuthProvider[] = [
  {
    source_name: "joinf",
    display_name: "Joinf",
    task_sources: ["joinf_business", "joinf_customs"],
    credential_fields: [
      { name: "username", label: "账号", input_type: "text", required: true },
      { name: "password", label: "密码", input_type: "password", required: true },
    ],
  },
];

function parseStorage<T>(value: string | null, fallback: T): T {
  if (!value) return fallback;
  try { return JSON.parse(value) as T; } catch { return fallback; }
}

type SourceAuthStatusStore = Record<string, { verified: boolean; verified_at?: string; message?: string }>;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [sourceProviders, setSourceProviders] = useState<SourceAuthProvider[]>([]);
  const [authStatus, setAuthStatus] = useState<SourceAuthStatusStore>({});
  const [aiConfigured, setAiConfigured] = useState(false);

  useEffect(() => {
    fetch(`${apiBaseUrl}/source-auth/providers`)
      .then((r) => r.ok ? r.json() : null)
      .then((data: SourceAuthProviderListResponse | null) => {
        if (data?.items) setSourceProviders(data.items);
      })
      .catch(() => setSourceProviders(fallbackSourceProviders));

    setAuthStatus(parseStorage(localStorage.getItem(sourceAuthStatusStorageKey), {}));
    const ai = parseStorage<{ api_key?: string }>(localStorage.getItem(aiConfigStorageKey), {});
    setAiConfigured(!!ai?.api_key);
  }, []);

  useEffect(() => {
    const handler = () => {
      setAuthStatus(parseStorage(localStorage.getItem(sourceAuthStatusStorageKey), {}));
      const ai = parseStorage<{ api_key?: string }>(localStorage.getItem(aiConfigStorageKey), {});
      setAiConfigured(!!ai?.api_key);
    };
    window.addEventListener("storage", handler);
    const timer = setInterval(handler, 2000);
    return () => { window.removeEventListener("storage", handler); clearInterval(timer); };
  }, []);

  const anySourceVerified = Object.values(authStatus).some((s) => s.verified);
  const needsSetup = !anySourceVerified || !aiConfigured;

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Top Navigation */}
      <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/90 backdrop-blur-md">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-14 items-center justify-between">
            {/* Logo + Source Status */}
            <div className="flex items-center gap-4">
              <Link href="/" className="flex items-center gap-2.5 no-underline">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600">
                  <Search className="h-4 w-4 text-white" />
                </div>
                <div>
                  <h1 className="text-sm font-bold text-slate-900 leading-tight">Huoke</h1>
                  <p className="text-[10px] text-slate-400 leading-tight">获客线索发现</p>
                </div>
              </Link>
              {/* Source Status Indicators */}
              {sourceProviders.length > 0 && (
                <div className="hidden sm:flex items-center gap-3 border-l border-slate-200 pl-4">
                  {sourceProviders.map((p) => {
                    const status = authStatus[p.source_name];
                    return (
                      <div key={p.source_name} className="flex items-center gap-1.5 text-xs">
                        {status?.verified ? (
                          <CircleCheck className="h-3.5 w-3.5 text-emerald-500" />
                        ) : (
                          <Circle className="h-3.5 w-3.5 text-slate-300" />
                        )}
                        <span className={status?.verified ? "text-slate-600" : "text-slate-400"}>
                          {p.display_name}
                        </span>
                      </div>
                    );
                  })}
                  <div className="flex items-center gap-1.5 text-xs">
                    {aiConfigured ? (
                      <CircleCheck className="h-3.5 w-3.5 text-emerald-500" />
                    ) : (
                      <Circle className="h-3.5 w-3.5 text-slate-300" />
                    )}
                    <span className={aiConfigured ? "text-slate-600" : "text-slate-400"}>AI</span>
                  </div>
                </div>
              )}
            </div>

            {/* Settings - rightmost */}
            <div className="flex items-center gap-2">
              {needsSetup && pathname === "/" && (
                <Link
                  href="/settings"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-amber-50 border border-amber-200 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100 transition-colors"
                >
                  <AlertTriangle className="h-3.5 w-3.5" />
                  完成配置
                </Link>
              )}
              <Link
                href="/settings"
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  pathname === "/settings"
                    ? "bg-slate-100 text-slate-900"
                    : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
                }`}
              >
                <Settings className={`h-4 w-4 ${pathname === "/settings" ? "text-slate-700" : "text-slate-400"}`} />
                设置
              </Link>
            </div>
          </div>
        </div>
      </header>

      {/* Page Content */}
      <main>
        {children}
      </main>
    </div>
  );
}
