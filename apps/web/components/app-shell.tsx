"use client";

import React from "react";
import Link from "next/link";
import { Search } from "lucide-react";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Top Navigation */}
      <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/90 backdrop-blur-md">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-14 items-center justify-between">
            {/* Logo */}
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
