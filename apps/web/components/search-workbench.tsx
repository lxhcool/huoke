"use client";

import React, { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import * as XLSX from "xlsx";
import {
  Search, Download, X, ChevronDown, ChevronRight,
  Building2, Globe2, Phone, Mail, Star, Shield, MapPin, Users,
  FileText, Anchor, ExternalLink, Copy, Bookmark, Ban, Loader2,
  CircleCheck, CircleX, Circle, Clock, AlertTriangle, Sparkles,
  Hash, Weight, Package, DollarSign, Repeat, Info,
  ArrowRight, Key,
} from "lucide-react";

import type {
  AIConfig,
  FeedbackRequest,
  SearchJob,
  SearchJobResult,
  SearchJobResultsResponse,
  SearchRequest,
  SourceAuthProvider,
  SourceAuthProviderListResponse,
} from "../lib/types";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

const sourceOptions = [
  { key: "joinf_business", label: "Joinf 商业数据" },
  { key: "joinf_customs", label: "Joinf 海关数据" },
];

const defaultSources = ["joinf_business", "joinf_customs"];

const sourceCredentialStorageKey = "huoke.sourceCredentials.v1";
const sourceAuthStatusStorageKey = "huoke.sourceAuthStatus.v1";
const aiConfigStorageKey = "huoke.aiConfig.v1";

type SourceCredentialStore = Record<string, Record<string, string>>;
type SourceAuthStatusStore = Record<string, { verified: boolean; verified_at?: string; message?: string }>;

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

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    queued: "等待中", running: "运行中", completed: "已完成", failed: "失败",
    partial: "部分完成", enriching: "补充中", ready: "就绪", completed_with_errors: "部分失败",
  };
  return map[status] || status;
}

function scoreColor(score: number): string {
  if (score >= 80) return "text-emerald-600";
  if (score >= 60) return "text-amber-600";
  return "text-slate-400";
}

function scoreBg(score: number): string {
  if (score >= 80) return "bg-emerald-50 text-emerald-700 ring-emerald-600/20";
  if (score >= 60) return "bg-amber-50 text-amber-700 ring-amber-600/20";
  return "bg-slate-100 text-slate-600 ring-slate-600/20";
}

function socialMediaLabel(type: number): string {
  const map: Record<number, string> = { 1: "Facebook", 2: "Twitter", 3: "LinkedIn", 4: "YouTube", 5: "Instagram", 7: "Instagram", 8: "YouTube" };
  return map[type] || "社交";
}

function sourceDisplayName(sourceName: string): string {
  const map: Record<string, string> = { joinf_business: "Joinf 商业", joinf_customs: "Joinf 海关" };
  return map[sourceName] || sourceName;
}

export function SearchWorkbench() {
  const [query, setQuery] = useState("ledlighting");
  const [country, setCountry] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>(defaultSources);
  const [maxPages, setMaxPages] = useState(5);
  const [minScore, setMinScore] = useState(0);

  const [job, setJob] = useState<SearchJob | null>(null);
  const [results, setResults] = useState<SearchJobResultsResponse | null>(null);
  const [resultsTab, setResultsTab] = useState<"business" | "customs">("business");
  const [sourceProviders, setSourceProviders] = useState<SourceAuthProvider[]>([]);
  const [sourceCredentials, setSourceCredentials] = useState<SourceCredentialStore>({});
  const [sourceAuthStatus, setSourceAuthStatus] = useState<SourceAuthStatusStore>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);
  const [contactModalItem, setContactModalItem] = useState<SearchJobResult | null>(null);

  const [aiConfig, setAiConfig] = useState<AIConfig>({
    api_key: "", base_url: "https://api.siliconflow.cn/v1", model: "Qwen/Qwen3-8B",
  });

  const providerDisplayMap = useMemo(
    () => Object.fromEntries(sourceProviders.map((p) => [p.source_name, p.display_name])),
    [sourceProviders]
  );

  const taskSourceToProviderMap = useMemo(() => {
    const m: Record<string, string> = {};
    sourceProviders.forEach((p) => p.task_sources.forEach((s) => (m[s] = p.source_name)));
    return m;
  }, [sourceProviders]);

  const selectedProviderNames = useMemo(() => {
    const s = new Set<string>();
    selectedSources.forEach((src) => {
      const p = taskSourceToProviderMap[src] ?? src.split("_")[0];
      if (p) s.add(p);
    });
    return Array.from(s);
  }, [selectedSources, taskSourceToProviderMap]);

  const verifiedSources = useMemo(
    () => selectedSources.filter((src) => {
      const p = taskSourceToProviderMap[src] ?? src.split("_")[0];
      return p && sourceAuthStatus[p]?.verified;
    }),
    [selectedSources, taskSourceToProviderMap, sourceAuthStatus]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiBaseUrl}/source-auth/providers`);
        if (!res.ok) throw new Error();
        const data: SourceAuthProviderListResponse = await res.json();
        if (!cancelled) setSourceProviders(data.items);
      } catch {
        if (!cancelled) setSourceProviders(fallbackSourceProviders);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const stored = parseStorage(localStorage.getItem(sourceCredentialStorageKey), {});
    const defaultCreds = { joinf: { username: "hcct010", password: "hcct86069640" } };
    const merged = { ...defaultCreds };
    for (const [key, val] of Object.entries(stored)) {
      if (val && Object.keys(val).length > 0) merged[key] = val;
    }
    setSourceCredentials(merged);
    setSourceAuthStatus(parseStorage(localStorage.getItem(sourceAuthStatusStorageKey), {}));
    const storedAiConfig = parseStorage<AIConfig>(localStorage.getItem(aiConfigStorageKey), null);
    if (storedAiConfig && storedAiConfig.api_key) setAiConfig(storedAiConfig);
  }, []);

  // Poll for settings changes (when user updates in /settings page)
  useEffect(() => {
    const timer = setInterval(() => {
      setSourceAuthStatus(parseStorage(localStorage.getItem(sourceAuthStatusStorageKey), {}));
      const storedAiConfig = parseStorage<AIConfig>(localStorage.getItem(aiConfigStorageKey), null);
      if (storedAiConfig && storedAiConfig.api_key) setAiConfig(storedAiConfig);
    }, 3000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!job) return;
    const terminalStatuses = ["completed", "completed_with_errors", "cancelled", "failed"];
    if (terminalStatuses.includes(job.status)) {
      fetch(`${apiBaseUrl}/search-jobs/${job.id}/results`)
        .then((r) => r.ok ? r.json() : null)
        .then((data) => { if (data && data.items) setResults(data); })
        .catch(() => {});
      return;
    }
    const timer = setInterval(async () => {
      try {
        const [jr, rr] = await Promise.all([
          fetch(`${apiBaseUrl}/search-jobs/${job.id}`),
          fetch(`${apiBaseUrl}/search-jobs/${job.id}/results`),
        ]);
        if (jr.ok) setJob(await jr.json());
        if (rr.ok) {
          const data = await rr.json();
          if (data && data.items) setResults(data);
        }
      } catch { /* ignore */ }
    }, 3000);
    return () => clearInterval(timer);
  }, [job]);

  const exportToExcel = useCallback(() => {
    if (!results || results.items.length === 0) return;
    const rows = results.items.map((item) => {
      const contactEmails = item.contacts.filter((c) => c.email).map((c) => c.email).join("; ");
      const contactPhones = item.contacts.filter((c) => c.phone).map((c) => c.phone).join("; ");
      const contactNames = item.contacts.map((c) => [c.name, c.title].filter(Boolean).join(" - ")).join("; ");
      const socialLinks = (item.social_media || [])
        .map((s) => { const url = s.snsUrl || s.url || ""; return url ? `${socialMediaLabel(s.type)}: ${url}` : ""; })
        .filter(Boolean).join("; ");
      return {
        "公司名称": item.company_name, "国家": item.country || "", "城市": item.city || "",
        "行业": item.industry || "", "主营业务": item.main_business || "", "网站": item.website || "",
        "公司电话": item.phone || "", "地址": item.address || "", "邮箱数量": item.email_count ?? "",
        "员工规模": item.employee_size || "", "信用评级": item.grade || "", "星级": item.star ?? "",
        "公司简介": item.description || "", "AI总结": item.ai_summary || "",
        "联系人": contactNames, "联系人邮箱": contactEmails, "联系人电话": contactPhones,
        "社交媒体": socialLinks, "匹配分数": item.score, "置信度": item.confidence,
        "匹配原因": item.match_reasons.join("; "),
      };
    });
    const ws = XLSX.utils.json_to_sheet(rows);
    ws["!cols"] = [
      { wch: 30 }, { wch: 12 }, { wch: 12 }, { wch: 15 }, { wch: 30 },
      { wch: 25 }, { wch: 18 }, { wch: 30 }, { wch: 8 }, { wch: 10 },
      { wch: 8 }, { wch: 5 }, { wch: 40 }, { wch: 30 }, { wch: 30 },
      { wch: 35 }, { wch: 20 }, { wch: 30 }, { wch: 8 }, { wch: 6 }, { wch: 40 },
    ];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "搜索结果");
    const keyword = job?.query || "search";
    XLSX.writeFile(wb, `huoke_${keyword}_${new Date().toISOString().slice(0, 10)}.xlsx`);
    setFeedbackMsg("Excel 已导出");
    setTimeout(() => setFeedbackMsg(null), 3000);
  }, [results, job]);

  async function submitFeedback(companyId: number, action: string) {
    try {
      await fetch(`${apiBaseUrl}/feedback`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company_id: companyId, action, query_text: job?.query } as FeedbackRequest),
      });
      setFeedbackMsg(`已${action === "favorite" ? "收藏" : "标记无效"}`);
      setTimeout(() => setFeedbackMsg(null), 2000);
    } catch { /* */ }
  }

  function toggleSource(key: string) {
    setSelectedSources((prev) => prev.includes(key) ? prev.filter((s) => s !== key) : [...prev, key]);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) { setError("请输入产品关键词"); return; }
    if (verifiedSources.length === 0) { setError("请先在「设置」页面验证数据源登录"); return; }
    setLoading(true); setError(null); setResults(null);
    try {
      const payload: SearchRequest = {
        query: query.trim(), sources: verifiedSources, country: country.trim() || undefined,
        customer_profile_mode: "general", customs_required: false,
        limit: maxPages * 20, min_score: minScore,
        ai_config: aiConfig.api_key ? aiConfig : undefined,
      };
      const res = await fetch(`${apiBaseUrl}/search-jobs`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("搜索请求失败，请检查 API 服务");
      const jobData: SearchJob = await res.json();
      setJob(jobData);
      const rr = await fetch(`${apiBaseUrl}/search-jobs/${jobData.id}/results`);
      if (rr.ok) setResults(await rr.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "未知错误");
    } finally { setLoading(false); }
  }

  // ─── derived data ───
  const businessItems = results?.items.filter((item) => !item.source_names.includes("joinf_customs") || item.source_names.some((s) => s !== "joinf_customs")) ?? [];
  const customsOnlyItems = results?.items.filter((item) => item.source_names.includes("joinf_customs") && item.source_names.every((s) => s === "joinf_customs")) ?? [];
  const hasCustoms = customsOnlyItems.length > 0;
  const filteredItems = resultsTab === "business" ? (hasCustoms ? businessItems : (results?.items ?? [])) : customsOnlyItems;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {/* Setup Guide - show when not configured */}
      {(() => {
        const anySourceVerified = verifiedSources.length > 0;
        const needsSourceSetup = !anySourceVerified;
        const needsAiSetup = !aiConfig.api_key;

        if (needsSourceSetup || needsAiSetup) {
          return (
            <div className="mt-16">
              <div className="mx-auto max-w-lg text-center mb-8">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50">
                  <Search className="h-6 w-6 text-blue-500" />
                </div>
                <h2 className="mt-4 text-lg font-semibold text-slate-900">开始使用 Huoke</h2>
                <p className="mt-1 text-sm text-slate-500">完成以下配置后即可搜索外贸客户线索</p>
              </div>
              <div className="mx-auto max-w-md space-y-4">
                {/* Source Setup */}
                <div className={`card p-5 ${needsSourceSetup ? "ring-2 ring-amber-400/60" : ""}`}>
                  <div className="flex items-start gap-3">
                    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                      anySourceVerified ? "bg-emerald-50" : "bg-amber-50"
                    }`}>
                      {anySourceVerified ? (
                        <CircleCheck className="h-5 w-5 text-emerald-600" />
                      ) : (
                        <Key className="h-5 w-5 text-amber-600" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold text-slate-900">数据源账号</h3>
                        {anySourceVerified ? (
                          <span className="text-[11px] font-medium text-emerald-600">已完成</span>
                        ) : (
                          <span className="text-[11px] font-medium text-amber-600">必填</span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {anySourceVerified
                          ? "数据源已验证，可以正常搜索"
                          : "登录数据源账号后才能抓取商业和海关数据"}
                      </p>
                      {!anySourceVerified && (
                        <a href="/settings" className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-800 transition-colors">
                          前往配置 <ArrowRight className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                  </div>
                </div>

                {/* AI Setup */}
                <div className={`card p-5 ${!needsSourceSetup && needsAiSetup ? "ring-2 ring-amber-400/60" : ""}`}>
                  <div className="flex items-start gap-3">
                    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                      aiConfig.api_key ? "bg-emerald-50" : "bg-slate-100"
                    }`}>
                      {aiConfig.api_key ? (
                        <CircleCheck className="h-5 w-5 text-emerald-600" />
                      ) : (
                        <Sparkles className="h-5 w-5 text-slate-400" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold text-slate-900">AI 配置</h3>
                        {aiConfig.api_key ? (
                          <span className="text-[11px] font-medium text-emerald-600">已完成</span>
                        ) : (
                          <span className="text-[11px] font-medium text-slate-400">可选</span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {aiConfig.api_key
                          ? "AI 已配置，支持客户评估和智能总结"
                          : "配置后可启用客户匹配评分、智能总结等功能"}
                      </p>
                      {!aiConfig.api_key && (
                        <a href="/settings" className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-800 transition-colors">
                          前往配置 <ArrowRight className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          );
        }

        return null;
      })()}

      {/* Main content - only show when configured */}
      {(() => {
        const anySourceVerified = verifiedSources.length > 0;
        const needsAiSetup = !aiConfig.api_key;
        const configured = anySourceVerified && !needsAiSetup;
        if (!configured) return null;
        return (
          <>
        {/* Search Form */}
        <form onSubmit={handleSubmit} className="card p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end">
            {/* Keyword */}
            <div className="flex-1 min-w-0">
              <label className="mb-1.5 block text-xs font-medium text-slate-600">产品关键词</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
                  placeholder="例如：ledlighting、激光切割设备、数控机床..."
                  className="input-field !pl-9" />
              </div>
            </div>
            {/* Country */}
            <div className="w-full lg:w-40">
              <label className="mb-1.5 block text-xs font-medium text-slate-600">
                国家/地区 <span className="text-slate-400 font-normal">(可选)</span>
              </label>
              <div className="relative">
                <MapPin className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input type="text" value={country} onChange={(e) => setCountry(e.target.value)}
                  placeholder="德国、USA" className="input-field !pl-9" />
              </div>
            </div>
            {/* Pages */}
            <div className="w-full lg:w-28">
              <label className="mb-1.5 block text-xs font-medium text-slate-600">抓取页数</label>
              <input type="number" min={1} max={50} value={maxPages}
                onChange={(e) => setMaxPages(Number(e.target.value) || 5)} className="input-field text-center" />
            </div>
            {/* Min Score */}
            <div className="w-full lg:w-28">
              <label className="mb-1.5 block text-xs font-medium text-slate-600">
                最低评分 <span className="text-slate-400 font-normal">(0=全部)</span>
              </label>
              <input type="number" min={0} max={100} step={10} value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value) || 0)} className="input-field text-center" placeholder="0" />
            </div>
            {/* Source + Submit */}
            <div className="flex items-end gap-3 w-full lg:w-auto">
              <div className="flex-1 lg:flex-initial">
                <label className="mb-1.5 block text-xs font-medium text-slate-600">数据源</label>
                <div className="flex gap-1.5">
                  {sourceOptions.map((opt) => {
                    const providerName = taskSourceToProviderMap[opt.key] ?? opt.key.split("_")[0];
                    const isVerified = sourceAuthStatus[providerName]?.verified;
                    const isSelected = selectedSources.includes(opt.key);
                    return (
                      <button key={opt.key} type="button" onClick={() => toggleSource(opt.key)}
                        className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-2 text-xs font-medium transition-colors cursor-pointer ${
                          isSelected
                            ? isVerified ? "border-blue-600 bg-blue-50 text-blue-700" : "border-amber-500 bg-amber-50 text-amber-700"
                            : "border-slate-200 bg-white text-slate-400 hover:bg-slate-50"
                        }`}>
                        {opt.key === "joinf_business" ? <Building2 className="h-3.5 w-3.5" /> : <Anchor className="h-3.5 w-3.5" />}
                        <span className="hidden sm:inline">{opt.label.replace("Joinf ", "")}</span>
                        {!isVerified && isSelected && <AlertTriangle className="h-3 w-3 text-amber-500" />}
                      </button>
                    );
                  })}
                </div>
              </div>
              <button type="submit" disabled={loading}
                className="btn-primary min-w-[110px] cursor-pointer shrink-0">
                {loading ? (
                  <span className="flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> 搜索中</span>
                ) : (
                  <span className="flex items-center gap-2"><Search className="h-4 w-4" /> 搜索</span>
                )}
              </button>
            </div>
          </div>
          {loading && job && (
            <div className="mt-3 flex items-center gap-3">
              <button type="button" onClick={async () => {
                try { await fetch(`${apiBaseUrl}/search-jobs/${job.id}/cancel`, { method: "POST" }); setFeedbackMsg("已发送取消请求"); }
                catch { setError("取消请求发送失败"); }
              }} className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 cursor-pointer transition-colors">
                <Ban className="h-3 w-3" /> 取消搜索
              </button>
              {verifiedSources.length < selectedSources.length && (
                <span className="text-[11px] text-amber-600">
                  <AlertTriangle className="inline h-3 w-3 mr-0.5" />
                  {selectedSources.length - verifiedSources.length} 个数据源未验证，将被跳过
                </span>
              )}
            </div>
          )}
        </form>

        {/* Toast Messages */}
        {error && (
          <div className="mt-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertTriangle className="h-4 w-4 shrink-0" /> {error}
            <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600 cursor-pointer"><X className="h-4 w-4" /></button>
          </div>
        )}
        {feedbackMsg && (
          <div className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
            <CircleCheck className="h-4 w-4 shrink-0" /> {feedbackMsg}
          </div>
        )}

        {/* Task Progress */}
        {job && (
          <div className="mt-5 card p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-slate-900">任务进度</h3>
              <div className="flex items-center gap-3">
                {results && results.items.length > 0 && !["completed", "completed_with_errors", "cancelled", "failed"].includes(job.status) && (
                  <span className="text-xs text-blue-600 flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" /> 已找到 {results.items.length} 条...
                  </span>
                )}
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${
                  ["completed", "ready"].includes(job.status) ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" :
                  ["running", "enriching"].includes(job.status) ? "bg-blue-50 text-blue-700 ring-blue-700/10" :
                  ["failed"].includes(job.status) ? "bg-red-50 text-red-700 ring-red-600/10" :
                  "bg-slate-100 text-slate-600 ring-slate-600/20"
                }`}>
                  {["running", "enriching"].includes(job.status) && <Loader2 className="h-3 w-3 animate-spin" />}
                  {["completed", "ready"].includes(job.status) && <CircleCheck className="h-3 w-3" />}
                  {["failed"].includes(job.status) && <CircleX className="h-3 w-3" />}
                  {statusLabel(job.status)}
                </span>
              </div>
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {job.source_tasks.map((task) => (
                <div key={task.id} className="flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-2">
                  {task.status === "running" ? <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin" /> :
                   task.status === "completed" ? <CircleCheck className="h-3.5 w-3.5 text-emerald-500" /> :
                   task.status === "failed" ? <CircleX className="h-3.5 w-3.5 text-red-500" /> :
                   <Clock className="h-3.5 w-3.5 text-slate-300" />}
                  <span className="text-xs text-slate-700">{sourceDisplayName(task.source_name)}</span>
                  <span className="ml-auto text-[11px] text-slate-500">{statusLabel(task.status)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Results */}
        {results && results.items.length > 0 && (
          <div className="mt-5">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-3">
                {hasCustoms ? (
                  <div className="flex rounded-lg border border-slate-200 overflow-hidden">
                    <button onClick={() => setResultsTab("business")}
                      className={`inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                        resultsTab === "business" ? "bg-blue-600 text-white" : "bg-white text-slate-600 hover:bg-slate-50"
                      }`}>
                      <Building2 className="h-3.5 w-3.5" /> 商业数据 ({businessItems.length})
                    </button>
                    <button onClick={() => setResultsTab("customs")}
                      className={`inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                        resultsTab === "customs" ? "bg-amber-600 text-white" : "bg-white text-slate-600 hover:bg-slate-50"
                      }`}>
                      <Anchor className="h-3.5 w-3.5" /> 海关数据 ({customsOnlyItems.length})
                    </button>
                  </div>
                ) : (
                  <h2 className="text-sm font-semibold text-slate-900">
                    搜索结果 <span className="ml-1 text-xs font-normal text-slate-500">共 {results.total} 条</span>
                  </h2>
                )}
              </div>
              <button onClick={exportToExcel}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 cursor-pointer transition-colors">
                <Download className="h-3.5 w-3.5" /> 导出 Excel
              </button>
            </div>

            <div className="overflow-hidden card">
              <div className="overflow-x-auto">
                {resultsTab === "customs" ? (
                  <CustomsTable items={customsOnlyItems} expandedRow={expandedRow} onToggle={(id) => setExpandedRow(expandedRow === id ? null : id)} />
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 bg-slate-50/80">
                        <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500">公司</th>
                        <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500">行业/主营</th>
                        <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500">网站</th>
                        <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500">联系方式</th>
                        <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500">地区</th>
                        <th className="px-4 py-2.5 text-center text-xs font-medium text-slate-500">匹配度</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {filteredItems.map((item) => (
                        <ResultRow key={item.id} item={item} expanded={expandedRow === item.id}
                          onToggle={() => setExpandedRow(expandedRow === item.id ? null : item.id)}
                          onFeedback={submitFeedback} onShowContacts={setContactModalItem} />
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Empty State - no search yet */}
        {!job && !error && (
          <div className="mt-20 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100">
              <Search className="h-6 w-6 text-slate-400" />
            </div>
            <h3 className="mt-4 text-sm font-medium text-slate-900">输入关键词开始搜索</h3>
            <p className="mt-1 text-xs text-slate-500">搜索外贸客户公司及联系人信息</p>
          </div>
        )}
        {job && results && results.items.length === 0 && ["completed", "completed_with_errors", "cancelled", "failed"].includes(job.status) && (
          <div className="mt-20 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100">
              <FileText className="h-6 w-6 text-slate-400" />
            </div>
            <h3 className="mt-4 text-sm font-medium text-slate-900">
              {job.status === "cancelled" ? "搜索已取消" : job.status === "failed" ? "搜索失败" : "未找到结果"}
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              {job.status === "cancelled" ? "搜索任务已被取消" :
               job.source_tasks.some((t) => t.status === "failed" && t.error_message) ?
               `失败原因：${job.source_tasks.find((t) => t.status === "failed")?.error_message?.slice(0, 120)}` :
               "尝试更换关键词或调整筛选条件"}
            </p>
          </div>
        )}
          </>
        );
      })()}

      {/* Contact Modal */}
      {contactModalItem && <ContactModal item={contactModalItem} onClose={() => setContactModalItem(null)} />}
    </div>
  );
}


/* ─── Customs Data Table ─── */

function CustomsTable({ items, expandedRow, onToggle }: { items: SearchJobResult[]; expandedRow: number | null; onToggle: (id: number) => void }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-amber-100 bg-amber-50/60">
          <th className="px-4 py-2.5 text-left text-xs font-medium text-amber-800">交易日期</th>
          <th className="px-4 py-2.5 text-left text-xs font-medium text-amber-800">HS编码</th>
          <th className="px-4 py-2.5 text-left text-xs font-medium text-amber-800">采购商</th>
          <th className="px-4 py-2.5 text-left text-xs font-medium text-amber-800">供应商</th>
          <th className="px-4 py-2.5 text-left text-xs font-medium text-amber-800">产品描述</th>
          <th className="px-4 py-2.5 text-center text-xs font-medium text-amber-800">重量</th>
          <th className="px-4 py-2.5 text-center text-xs font-medium text-amber-800">数量</th>
          <th className="px-4 py-2.5 text-center text-xs font-medium text-amber-800">金额</th>
          <th className="px-4 py-2.5 text-center text-xs font-medium text-amber-800">频次</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {items.map((item) => {
          const cs = item.customs_summary;
          const isExpanded = expandedRow === item.id;
          return (
            <React.Fragment key={item.id}>
              <tr className="cursor-pointer hover:bg-amber-50/30 transition-colors" onClick={() => onToggle(item.id)}>
                <td className="px-4 py-2.5 text-slate-600 text-xs whitespace-nowrap">{cs?.trade_date || cs?.last_trade_at || "-"}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-slate-700">{cs?.hs_code || "-"}</td>
                <td className="px-4 py-2.5">
                  <div className="font-medium text-slate-900 max-w-[180px] truncate" title={cs?.buyer || item.company_name}>{cs?.buyer || item.company_name}</div>
                </td>
                <td className="px-4 py-2.5 text-slate-600 max-w-[150px] truncate" title={cs?.supplier || "-"}>{cs?.supplier || "-"}</td>
                <td className="px-4 py-2.5 text-slate-600 max-w-[200px] truncate" title={cs?.product_description || "-"}>{cs?.product_description || "-"}</td>
                <td className="px-4 py-2.5 text-center text-slate-600 text-xs">{cs?.weight || "-"}</td>
                <td className="px-4 py-2.5 text-center text-slate-600 text-xs">{cs?.quantity || "-"}</td>
                <td className="px-4 py-2.5 text-center text-slate-600 text-xs">{cs?.amount || "-"}</td>
                <td className="px-4 py-2.5 text-center">
                  <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                    {cs?.frequency || 0}
                  </span>
                </td>
              </tr>
              {cs?.ai_summary && !isExpanded && (
                <tr className="bg-blue-50/30">
                  <td colSpan={9} className="px-4 py-2">
                    <div className="flex items-start gap-2 text-xs">
                      <span className="shrink-0 inline-flex items-center gap-1 rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">
                        <Sparkles className="h-2.5 w-2.5" /> 总结
                      </span>
                      <span className="text-slate-700">{cs.ai_summary}</span>
                    </div>
                  </td>
                </tr>
              )}
              {isExpanded && (
                <tr>
                  <td colSpan={9} className="bg-amber-50/20 px-6 py-4">
                    {cs?.ai_summary && (
                      <div className="mb-4 rounded-lg bg-blue-50 border border-blue-100 px-4 py-3">
                        <div className="flex items-start gap-2">
                          <span className="shrink-0 inline-flex items-center gap-1 rounded bg-blue-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                            <Sparkles className="h-2.5 w-2.5" /> 总结
                          </span>
                          <span className="text-sm text-slate-800">{cs.ai_summary}</span>
                        </div>
                      </div>
                    )}
                    <div className="grid gap-4 sm:grid-cols-3">
                      <div className="space-y-2">
                        <h4 className="text-xs font-semibold text-slate-900 flex items-center gap-1.5"><FileText className="h-3.5 w-3.5 text-slate-400" /> 交易详情</h4>
                        {cs?.trade_date && <div className="text-xs"><span className="text-slate-500">交易日期：</span>{cs.trade_date}</div>}
                        {cs?.hs_code && <div className="text-xs"><span className="text-slate-500">HS编码：</span><span className="font-mono">{cs.hs_code}</span></div>}
                        {cs?.buyer && <div className="text-xs"><span className="text-slate-500">采购商：</span><span className="font-semibold">{cs.buyer}</span></div>}
                        {cs?.supplier && <div className="text-xs"><span className="text-slate-500">供应商：</span>{cs.supplier}</div>}
                        {cs?.origin && <div className="text-xs"><span className="text-slate-500">原产国：</span>{cs.origin}</div>}
                      </div>
                      <div className="space-y-2">
                        <h4 className="text-xs font-semibold text-slate-900 flex items-center gap-1.5"><Package className="h-3.5 w-3.5 text-slate-400" /> 货物信息</h4>
                        {cs?.product_description && <div className="text-xs"><span className="text-slate-500">产品描述：</span>{cs.product_description}</div>}
                        {cs?.weight && <div className="text-xs"><span className="text-slate-500">重量：</span>{cs.weight}</div>}
                        {cs?.quantity && <div className="text-xs"><span className="text-slate-500">数量：</span>{cs.quantity}</div>}
                        {cs?.amount && <div className="text-xs"><span className="text-slate-500">金额：</span>{cs.amount}</div>}
                        {cs?.frequency != null && <div className="text-xs"><span className="text-slate-500">交易频次：</span><span className="font-semibold text-amber-700">{cs.frequency} 次</span></div>}
                      </div>
                      <div className="space-y-2">
                        <h4 className="text-xs font-semibold text-slate-900 flex items-center gap-1.5"><Info className="h-3.5 w-3.5 text-slate-400" /> 匹配原因</h4>
                        {item.match_reasons.map((r, i) => (
                          <div key={i} className="flex items-start gap-1.5 text-[11px] text-slate-600">
                            <span className="mt-1 h-1 w-1 flex-shrink-0 rounded-full bg-amber-400" /> {r}
                          </div>
                        ))}
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </React.Fragment>
          );
        })}
      </tbody>
    </table>
  );
}


/* ─── Result Row ─── */

function ResultRow({ item, expanded, onToggle, onFeedback, onShowContacts }: {
  item: SearchJobResult; expanded: boolean; onToggle: () => void;
  onFeedback: (companyId: number, action: string) => void; onShowContacts: (item: SearchJobResult) => void;
}) {
  return (
    <>
      <tr onClick={onToggle} className="cursor-pointer hover:bg-slate-50/80 transition-colors">
        <td className="px-4 py-2.5">
          <div className="flex items-center gap-2.5">
            {item.website_logo ? (
              <img src={item.website_logo} alt="" className="h-8 w-8 rounded-lg object-contain border border-slate-100"
                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
            ) : (
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-xs font-bold text-slate-400">
                {(item.company_name || "?")[0]}
              </div>
            )}
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="font-medium text-slate-900 truncate">{item.company_name}</span>
                {expanded ? <ChevronDown className="h-3.5 w-3.5 text-slate-400 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-300 shrink-0" />}
              </div>
              {item.ai_summary && !expanded && (
                <p className="text-[11px] text-slate-500 truncate max-w-[280px]">{item.ai_summary}</p>
              )}
            </div>
          </div>
        </td>
        <td className="px-4 py-2.5">
          <div className="max-w-[140px]">
            {item.industry && <div className="text-xs text-slate-700 truncate">{item.industry}</div>}
            {!item.industry && item.main_business && <div className="text-xs text-slate-500 truncate">{item.main_business.slice(0, 40)}</div>}
            {item.industry && item.main_business && <div className="text-[10px] text-slate-400 truncate">{item.main_business.slice(0, 30)}</div>}
          </div>
        </td>
        <td className="px-4 py-2.5">
          {item.website ? (
            <a href={item.website} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline" onClick={(e) => e.stopPropagation()}>
              <Globe2 className="h-3 w-3" />
              {item.website.replace(/^https?:\/\//, "").replace(/\/$/, "").slice(0, 25)}
            </a>
          ) : <span className="text-slate-300">-</span>}
        </td>
        <td className="px-4 py-2.5">
          <ContactInfoCell item={item} />
        </td>
        <td className="px-4 py-2.5 text-xs text-slate-600 whitespace-nowrap">
          <MapPin className="inline h-3 w-3 text-slate-400 mr-0.5" />
          {item.country}{item.city && <span className="text-slate-400"> / {item.city}</span>}
        </td>
        <td className="px-4 py-2.5 text-center">
          <span className={`inline-flex items-center justify-center rounded-full px-2 py-0.5 text-xs font-bold ring-1 ring-inset ${scoreBg(item.score)}`}>
            {item.score}
          </span>
        </td>
      </tr>

      {/* Expanded Detail */}
      {expanded && (
        <tr>
          <td colSpan={6} className="bg-slate-50/50 px-6 py-5">
            <div className="grid gap-6 lg:grid-cols-3">
              {/* Left: Main info */}
              <div className="lg:col-span-2 space-y-5">
                {/* AI Summary */}
                {item.ai_summary && (
                  <div className="rounded-lg bg-blue-50 border border-blue-100 px-4 py-3">
                    <div className="flex items-start gap-2">
                      <span className="shrink-0 inline-flex items-center gap-1 rounded bg-blue-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                        <Sparkles className="h-2.5 w-2.5" /> 总结
                      </span>
                      <span className="text-sm text-slate-800">{item.ai_summary}</span>
                    </div>
                  </div>
                )}

                {/* Company Info */}
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-900 mb-3">
                    <Building2 className="h-3.5 w-3.5 text-blue-500" /> 公司信息
                  </h4>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {item.phone && <DetailField icon={<Phone className="h-3.5 w-3.5" />} label="电话" value={item.phone} />}
                    {item.address && <DetailField icon={<MapPin className="h-3.5 w-3.5" />} label="地址" value={item.address} />}
                    {item.employee_size && <DetailField icon={<Users className="h-3.5 w-3.5" />} label="员工规模" value={item.employee_size} />}
                    {item.email_count != null && <DetailField icon={<Mail className="h-3.5 w-3.5" />} label="邮箱数量" value={String(item.email_count)} />}
                    {item.grade && <DetailField icon={<Shield className="h-3.5 w-3.5" />} label="信用评级" value={item.grade} />}
                    {item.star != null && <DetailField icon={<Star className="h-3.5 w-3.5" />} label="星级" value={"★".repeat(Math.min(Math.floor(item.star), 5)) + (item.star % 1 >= 0.5 ? "½" : "")} />}
                    {item.linkedin_url && (
                      <div className="flex items-center gap-1.5 text-xs">
                        <span className="text-slate-400 font-bold text-[10px]">in</span>
                        <a href={item.linkedin_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">LinkedIn 主页</a>
                      </div>
                    )}
                  </div>
                  {item.main_business && (
                    <div className="mt-3 rounded-lg bg-white border border-slate-200 px-3 py-2">
                      <span className="text-[11px] font-medium text-slate-500">主营业务</span>
                      <p className="mt-1 text-xs text-slate-800">{item.main_business}</p>
                    </div>
                  )}
                  {item.description && (
                    <div className="mt-2">
                      <span className="text-[11px] font-medium text-slate-500">公司简介</span>
                      <p className="mt-1 text-xs text-slate-600 line-clamp-5">{item.description}</p>
                    </div>
                  )}
                </div>

                {/* Social Media */}
                {item.social_media && item.social_media.length > 0 && (() => {
                  const validSocial = item.social_media!.filter((s) => s.snsUrl || s.url);
                  if (validSocial.length === 0) return null;
                  return (
                    <div>
                      <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-900 mb-2">
                        <Globe2 className="h-3.5 w-3.5 text-purple-500" /> 社交媒体 ({validSocial.length})
                      </h4>
                      <div className="flex flex-wrap gap-1.5">
                        {validSocial.map((s, i) => {
                          const url = s.snsUrl || s.url || "";
                          return (
                            <a key={i} href={url} target="_blank" rel="noreferrer"
                              className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-blue-600 hover:bg-blue-50 cursor-pointer transition-colors">
                              <ExternalLink className="h-3 w-3" /> {socialMediaLabel(s.type)}
                            </a>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}

                {/* Contacts */}
                <div>
                  <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-900 mb-3">
                    <Users className="h-3.5 w-3.5 text-emerald-500" /> 联系人 ({item.contacts.length})
                    {item.contacts.length > 0 && (
                      <div className="ml-auto flex items-center gap-2">
                        <button onClick={(e) => { e.stopPropagation(); onShowContacts(item); }}
                          className="text-[11px] text-blue-600 hover:text-blue-800 font-medium cursor-pointer transition-colors">
                          查看全部
                        </button>
                        <button onClick={(e) => {
                          e.stopPropagation();
                          const lines = item.contacts.map((c) => {
                            const parts = [c.name, c.title].filter(Boolean);
                            if (c.email) parts.push(c.email); if (c.phone) parts.push(c.phone);
                            return parts.join(" | ");
                          });
                          navigator.clipboard.writeText(lines.join("\n"));
                        }} className="text-[11px] text-slate-400 hover:text-blue-600 cursor-pointer transition-colors flex items-center gap-0.5">
                          <Copy className="h-3 w-3" /> 复制
                        </button>
                      </div>
                    )}
                  </h4>
                  {item.contacts.length > 0 ? (
                    <div className="space-y-2">
                      {item.contacts.slice(0, 3).map((c, i) => (
                        <div key={i} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-semibold text-slate-900 text-xs">{c.name || "未知"}</span>
                                {c.title && c.title !== "-1" && c.title !== "0" && (
                                  <span className="inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{c.title}</span>
                                )}
                              </div>
                              <div className="mt-1 flex flex-col gap-0.5">
                                {c.email && (
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <Mail className="h-3 w-3 text-slate-400" />
                                    <a href={`mailto:${c.email}`} className="text-blue-600 hover:underline break-all" onClick={(e) => e.stopPropagation()}>{c.email}</a>
                                    {c.email_type && <span className="text-[10px] text-slate-400">({c.email_type})</span>}
                                  </div>
                                )}
                                {c.phone && (
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <Phone className="h-3 w-3 text-slate-400" />
                                    <span className="text-slate-700">{c.phone}</span>
                                  </div>
                                )}
                                {c.linkedin_url && (
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <span className="text-slate-400 font-bold text-[10px]">in</span>
                                    <a href={c.linkedin_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline" onClick={(e) => e.stopPropagation()}>LinkedIn</a>
                                  </div>
                                )}
                              </div>
                            </div>
                            <span className={`shrink-0 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                              c.confidence === "A" ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20" :
                              c.confidence === "B" ? "bg-amber-50 text-amber-700 ring-1 ring-amber-600/20" :
                              "bg-slate-100 text-slate-600 ring-1 ring-slate-600/20"
                            }`}>
                              {c.confidence === "A" ? "高" : c.confidence === "B" ? "中" : (c.confidence || "低")}
                            </span>
                          </div>
                        </div>
                      ))}
                      {item.contacts.length > 3 && (
                        <button onClick={(e) => { e.stopPropagation(); onShowContacts(item); }}
                          className="w-full rounded-lg border border-dashed border-blue-300 bg-blue-50/50 px-4 py-2 text-[11px] text-blue-600 hover:bg-blue-100/50 cursor-pointer transition-colors">
                          还有 {item.contacts.length - 3} 位联系人，点击查看全部
                        </button>
                      )}
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-6 text-center">
                      <p className="text-xs text-slate-400">暂无联系人信息</p>
                    </div>
                  )}
                </div>

                {/* Customs in business detail */}
                {item.customs_summary && (
                  <div>
                    <h4 className="flex items-center gap-1.5 text-xs font-semibold text-slate-900 mb-2">
                      <Anchor className="h-3.5 w-3.5 text-amber-500" /> 海关记录
                    </h4>
                    <div className="flex flex-wrap gap-1.5">
                      {item.customs_summary.trade_date && <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 ring-1 ring-inset ring-amber-600/20"><Clock className="h-3 w-3" /> {item.customs_summary.trade_date}</span>}
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 ring-1 ring-inset ring-amber-600/20"><Repeat className="h-3 w-3" /> {item.customs_summary.frequency} 次</span>
                      {item.customs_summary.hs_code && <span className="inline-flex items-center gap-1 rounded-full bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-inset ring-slate-600/20"><Hash className="h-3 w-3" /> {item.customs_summary.hs_code}</span>}
                      {item.customs_summary.supplier && <span className="inline-flex items-center gap-1 rounded-full bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-inset ring-slate-600/20"><Building2 className="h-3 w-3" /> {item.customs_summary.supplier}</span>}
                      {item.customs_summary.weight && <span className="inline-flex items-center gap-1 rounded-full bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-inset ring-slate-600/20"><Weight className="h-3 w-3" /> {item.customs_summary.weight}</span>}
                      {item.customs_summary.amount && <span className="inline-flex items-center gap-1 rounded-full bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600 ring-1 ring-inset ring-slate-600/20"><DollarSign className="h-3 w-3" /> {item.customs_summary.amount}</span>}
                    </div>
                  </div>
                )}

                {/* Actions */}
                <div className="flex gap-2 pt-1">
                  <button onClick={() => onFeedback(item.company_id, "favorite")}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 cursor-pointer transition-colors">
                    <Bookmark className="h-3.5 w-3.5" /> 收藏
                  </button>
                  <button onClick={() => onFeedback(item.company_id, "invalid")}
                    className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 cursor-pointer transition-colors">
                    <Ban className="h-3.5 w-3.5" /> 标记无效
                  </button>
                  {item.contacts.some((c) => c.email) && (
                    <button onClick={() => {
                      const emails = item.contacts.filter((c) => c.email).map((c) => c.email).join("; ");
                      navigator.clipboard.writeText(emails);
                    }} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 cursor-pointer transition-colors">
                      <Copy className="h-3.5 w-3.5" /> 复制全部邮箱
                    </button>
                  )}
                </div>
              </div>

              {/* Right: Score & Match */}
              <div className="space-y-4">
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-medium text-slate-500">匹配度评分</span>
                    <span className="group relative cursor-help">
                      <Info className="h-3.5 w-3.5 text-slate-400" />
                      <div className="pointer-events-none absolute bottom-full right-0 mb-2 w-52 rounded-lg bg-slate-800 px-3 py-2 text-[10px] leading-relaxed text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100 z-50">
                        <p className="font-semibold mb-1">评分规则 (AI 评估)</p>
                        <p>80-100：经销商/分销商</p>
                        <p>70-79：业务场景需大量采购</p>
                        <p>40-69：经营互补产品</p>
                        <p>10-39：竞争对手</p>
                        <p>0：不相关</p>
                      </div>
                    </span>
                  </div>
                  <div className="flex items-baseline gap-1">
                    <span className={`text-3xl font-bold ${scoreColor(item.score)}`}>{item.score}</span>
                    <span className="text-xs text-slate-400">/100</span>
                  </div>
                  <div className="mt-2 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                    <div className={`h-full rounded-full transition-all ${
                      item.score >= 80 ? "bg-emerald-500" : item.score >= 60 ? "bg-amber-500" : "bg-slate-300"
                    }`} style={{ width: `${item.score}%` }} />
                  </div>
                  <div className="mt-2 flex items-center gap-1.5">
                    <span className="text-[11px] text-slate-500">置信度</span>
                    <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${
                      item.confidence === "A" ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" :
                      item.confidence === "B" ? "bg-amber-50 text-amber-700 ring-amber-600/20" :
                      "bg-slate-100 text-slate-600 ring-slate-600/20"
                    }`}>
                      {item.confidence === "A" ? "高" : item.confidence === "B" ? "中" : "低"}
                    </span>
                  </div>
                </div>

                <div>
                  <h4 className="text-xs font-medium text-slate-500 mb-2">匹配原因</h4>
                  <div className="space-y-1.5">
                    {item.match_reasons.map((r, i) => (
                      <div key={i} className="flex items-start gap-1.5 text-[11px] text-slate-600">
                        <span className="mt-1 h-1 w-1 flex-shrink-0 rounded-full bg-blue-400" /> {r}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}


/* ─── Detail Field ─── */

function DetailField({ icon, label, value }: { icon?: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {icon && <span className="text-slate-400">{icon}</span>}
      <span className="text-slate-500">{label}：</span>
      <span className="text-slate-900">{value}</span>
    </div>
  );
}


/* ─── Contact Info Cell (table inline) ─── */

function ContactInfoCell({ item }: { item: SearchJobResult }) {
  const emails = item.contacts.filter((c) => c.email).map((c) => c.email!);
  const phones = item.contacts.filter((c) => c.phone).map((c) => c.phone!);
  if (emails.length === 0 && phones.length === 0 && !item.phone) {
    return <span className="text-slate-300">-</span>;
  }
  return (
    <div className="text-[11px] text-slate-700 space-y-0.5 max-w-[200px]">
      {item.phone && (
        <div className="flex items-center gap-1"><Phone className="h-3 w-3 text-slate-400" /><span className="truncate">{item.phone}</span></div>
      )}
      {emails.slice(0, 2).map((e, i) => (
        <div key={i} className="flex items-center gap-1"><Mail className="h-3 w-3 text-slate-400" /><span className="truncate text-blue-600">{e}</span></div>
      ))}
      {phones.filter((p) => p !== item.phone).slice(0, 1).map((p, i) => (
        <div key={i} className="flex items-center gap-1"><Phone className="h-3 w-3 text-slate-400" /><span className="truncate">{p}</span></div>
      ))}
      {emails.length > 2 && <div className="text-slate-400 pl-4">+{emails.length - 2} 个邮箱</div>}
    </div>
  );
}


/* ─── Contact Modal ─── */

function ContactModal({ item, onClose }: { item: SearchJobResult; onClose: () => void }) {
  const [searchText, setSearchText] = useState("");
  const [filterType, setFilterType] = useState<"all" | "email" | "phone">("all");

  const filteredContacts = useMemo(() => {
    let list = item.contacts;
    if (searchText.trim()) {
      const q = searchText.toLowerCase();
      list = list.filter((c) =>
        (c.name || "").toLowerCase().includes(q) || (c.title || "").toLowerCase().includes(q) ||
        (c.email || "").toLowerCase().includes(q) || (c.phone || "").toLowerCase().includes(q)
      );
    }
    if (filterType === "email") list = list.filter((c) => c.email);
    if (filterType === "phone") list = list.filter((c) => c.phone);
    return list;
  }, [item.contacts, searchText, filterType]);

  const emailCount = item.contacts.filter((c) => c.email).length;
  const phoneCount = item.contacts.filter((c) => c.phone).length;

  function exportCompanyContacts() {
    const rows = item.contacts.map((c) => ({
      "姓名": c.name || "", "职位": c.title || "", "邮箱": c.email || "",
      "邮箱类型": c.email_type || "", "电话": c.phone || "", "LinkedIn": c.linkedin_url || "", "置信度": c.confidence,
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    ws["!cols"] = [{ wch: 20 }, { wch: 20 }, { wch: 30 }, { wch: 10 }, { wch: 20 }, { wch: 35 }, { wch: 6 }];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "联系人");
    XLSX.writeFile(wb, `${item.company_name}_联系人_${new Date().toISOString().slice(0, 10)}.xlsx`);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
      <div className="relative z-10 mx-4 w-full max-w-3xl max-h-[85vh] flex flex-col rounded-2xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900">{item.company_name}</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              <MapPin className="inline h-3 w-3 mr-0.5" />
              {item.country}{item.city ? ` / ${item.city}` : ""}
              {item.website && <span className="ml-2">· <a href={item.website} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{item.website.replace(/^https?:\/\//, "").replace(/\/$/, "").slice(0, 30)}</a></span>}
            </p>
            <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-600">
              <span className="flex items-center gap-1"><Users className="h-3 w-3" /> {item.contacts.length} 位联系人</span>
              {emailCount > 0 && <span className="flex items-center gap-1 text-blue-600"><Mail className="h-3 w-3" /> {emailCount} 个邮箱</span>}
              {phoneCount > 0 && <span className="flex items-center gap-1 text-emerald-600"><Phone className="h-3 w-3" /> {phoneCount} 个电话</span>}
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 cursor-pointer transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Search & Filter */}
        <div className="flex items-center gap-3 border-b border-slate-100 px-6 py-2.5">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
            <input type="text" placeholder="搜索姓名、职位、邮箱..." value={searchText}
              onChange={(e) => setSearchText(e.target.value)} className="input-field text-xs !py-1.5 !pl-8" />
          </div>
          <div className="flex rounded-lg border border-slate-200 overflow-hidden">
            {([["all", "全部"], ["email", "有邮箱"], ["phone", "有电话"]] as const).map(([key, label]) => (
              <button key={key} onClick={() => setFilterType(key)}
                className={`px-3 py-1.5 text-[11px] font-medium transition-colors cursor-pointer ${
                  filterType === key ? "bg-blue-600 text-white" : "bg-white text-slate-600 hover:bg-slate-50"
                }`}>
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {filteredContacts.length > 0 ? (
            <div className="space-y-2.5">
              {filteredContacts.map((c, i) => (
                <div key={i} className="rounded-xl border border-slate-200 bg-slate-50/50 px-5 py-3.5 hover:bg-slate-50 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-semibold text-blue-700">
                      {(c.name || "?")[0].toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-slate-900 text-sm">{c.name || "未知"}</span>
                        {c.title && c.title !== "-1" && c.title !== "0" && (
                          <span className="inline-flex items-center rounded-md bg-white px-2 py-0.5 text-[11px] text-slate-600 border border-slate-200">{c.title}</span>
                        )}
                        <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset ${
                          c.confidence === "A" ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" :
                          c.confidence === "B" ? "bg-amber-50 text-amber-700 ring-amber-600/20" :
                          "bg-slate-100 text-slate-600 ring-slate-600/20"
                        }`}>
                          {c.confidence === "A" ? "高可信" : c.confidence === "B" ? "中可信" : (c.confidence || "低可信")}
                        </span>
                      </div>
                      <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                        {c.email && (
                          <div className="flex items-center gap-2 rounded-lg bg-white border border-slate-200 px-3 py-1.5">
                            <Mail className="h-3 w-3 text-slate-400" />
                            <a href={`mailto:${c.email}`} className="text-xs text-blue-600 hover:underline break-all">{c.email}</a>
                            {c.email_type && <span className="text-[10px] text-slate-400 ml-auto shrink-0">{c.email_type}</span>}
                          </div>
                        )}
                        {c.phone && (
                          <div className="flex items-center gap-2 rounded-lg bg-white border border-slate-200 px-3 py-1.5">
                            <Phone className="h-3 w-3 text-slate-400" />
                            <span className="text-xs text-slate-700">{c.phone}</span>
                          </div>
                        )}
                        {c.linkedin_url && (
                          <div className="flex items-center gap-2 rounded-lg bg-white border border-slate-200 px-3 py-1.5 sm:col-span-2">
                            <span className="text-[10px] font-bold text-slate-400">in</span>
                            <a href={c.linkedin_url} target="_blank" rel="noreferrer" className="text-xs text-blue-600 hover:underline break-all">{c.linkedin_url}</a>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-12 text-center"><p className="text-xs text-slate-400">没有匹配的联系人</p></div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-200 px-6 py-3 bg-slate-50/50 rounded-b-2xl">
          <span className="text-[11px] text-slate-500">显示 {filteredContacts.length} / {item.contacts.length} 位联系人</span>
          <div className="flex gap-2">
            <button onClick={() => {
              const all = filteredContacts.filter((c) => c.email).map((c) => c.email!).join("\n");
              navigator.clipboard.writeText(all);
            }} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 cursor-pointer transition-colors">
              <Copy className="h-3.5 w-3.5" /> 复制邮箱
            </button>
            <button onClick={exportCompanyContacts}
              className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 cursor-pointer transition-colors">
              <Download className="h-3.5 w-3.5" /> 导出 Excel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
