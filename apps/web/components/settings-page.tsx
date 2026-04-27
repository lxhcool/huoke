"use client";

import React, { useEffect, useState, useMemo } from "react";
import {
  Key, Sparkles, CircleCheck, Circle, Loader2,
  ExternalLink, Shield, Eye, EyeOff, Trash2, Save, Upload,
} from "lucide-react";

import type {
  AIConfig,
  SourceAuthProvider,
  SourceAuthProviderListResponse,
  SourceAuthVerifyResponse,
} from "../lib/types";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

const sourceCredentialStorageKey = "huoke.sourceCredentials.v1";
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

type SourceCredentialStore = Record<string, Record<string, string>>;
type SourceAuthStatusStore = Record<string, { verified: boolean; verified_at?: string; message?: string }>;

export function SettingsPage() {
  const [sourceProviders, setSourceProviders] = useState<SourceAuthProvider[]>([]);
  const [sourceCredentials, setSourceCredentials] = useState<SourceCredentialStore>({});
  const [sourceAuthStatus, setSourceAuthStatus] = useState<SourceAuthStatusStore>({});
  const [sourceVerifying, setSourceVerifying] = useState<Record<string, boolean>>({});
  const [cookieInput, setCookieInput] = useState<Record<string, string>>({});
  const [cookieImporting, setCookieImporting] = useState<Record<string, boolean>>({});
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});
  const [aiConfig, setAiConfig] = useState<AIConfig>({
    api_key: "", base_url: "https://api.siliconflow.cn/v1", model: "Qwen/Qwen3-8B",
  });
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [activeTab, setActiveTab] = useState<"sources" | "ai">("sources");
  const [editingProvider, setEditingProvider] = useState<string | null>(null);

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
    const merged: Record<string, Record<string, string>> = { ...defaultCreds };
    for (const [key, val] of Object.entries(stored)) {
      if (val && typeof val === "object" && Object.keys(val as Record<string, unknown>).length > 0) merged[key] = val as Record<string, string>;
    }
    setSourceCredentials(merged);
    setSourceAuthStatus(parseStorage(localStorage.getItem(sourceAuthStatusStorageKey), {}));
    const storedAiConfig = parseStorage<AIConfig | null>(localStorage.getItem(aiConfigStorageKey), null);
    if (storedAiConfig && storedAiConfig.api_key) setAiConfig(storedAiConfig);
  }, []);

  function showToast(type: "success" | "error", message: string) {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  }

  function updateCredential(sourceName: string, fieldName: string, value: string) {
    setSourceCredentials((prev) => ({ ...prev, [sourceName]: { ...(prev[sourceName] ?? {}), [fieldName]: value } }));
  }

  function saveCredentials(sourceName: string) {
    setSourceCredentials((prev) => {
      const next = { ...prev, [sourceName]: { ...(prev[sourceName] ?? {}) } };
      localStorage.setItem(sourceCredentialStorageKey, JSON.stringify(next));
      return next;
    });
    const provider = sourceProviders.find((p) => p.source_name === sourceName);
    showToast("success", `${provider?.display_name ?? sourceName} 凭证已保存`);
  }

  function clearCredentials(sourceName: string) {
    setSourceCredentials((prev) => {
      const next = { ...prev }; delete next[sourceName];
      localStorage.setItem(sourceCredentialStorageKey, JSON.stringify(next));
      return next;
    });
    setSourceAuthStatus((prev) => {
      const next = { ...prev }; delete next[sourceName];
      localStorage.setItem(sourceAuthStatusStorageKey, JSON.stringify(next));
      return next;
    });
    const provider = sourceProviders.find((p) => p.source_name === sourceName);
    showToast("success", `${provider?.display_name ?? sourceName} 凭证已清除`);
  }

  function saveAiConfig() {
    localStorage.setItem(aiConfigStorageKey, JSON.stringify(aiConfig));
    showToast("success", "AI 配置已保存");
  }

  function clearAiConfig() {
    localStorage.removeItem(aiConfigStorageKey);
    setAiConfig({ api_key: "", base_url: "https://api.siliconflow.cn/v1", model: "Qwen/Qwen3-8B" });
    showToast("success", "AI 配置已清除");
  }

  async function verifySource(sourceName: string) {
    const provider = sourceProviders.find((p) => p.source_name === sourceName);
    if (!provider) return;
    const credentials = sourceCredentials[sourceName] ?? {};
    setSourceVerifying((prev) => ({ ...prev, [sourceName]: true }));
    try {
      const res = await fetch(`${apiBaseUrl}/source-auth/${sourceName}/verify`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ credentials }),
      });
      if (!res.ok) {
        let detail = `${provider.display_name} 登录验证失败`;
        try { const p = await res.json(); if (p.detail) detail = p.detail; } catch { /* */ }
        throw new Error(detail);
      }
      const payload: SourceAuthVerifyResponse = await res.json();
      setSourceAuthStatus((prev) => {
        const next = { ...prev, [sourceName]: { verified: payload.status === "verified", verified_at: payload.verified_at, message: payload.message } };
        localStorage.setItem(sourceAuthStatusStorageKey, JSON.stringify(next));
        return next;
      });
      showToast("success", `${provider.display_name} 验证成功`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "验证失败";
      setSourceAuthStatus((prev) => {
        const next = { ...prev, [sourceName]: { verified: false, message: msg } };
        localStorage.setItem(sourceAuthStatusStorageKey, JSON.stringify(next));
        return next;
      });
      showToast("error", msg);
    } finally {
      setSourceVerifying((prev) => ({ ...prev, [sourceName]: false }));
    }
  }

  async function importCookie(sourceName: string) {
    const cookieStr = cookieInput[sourceName]?.trim();
    if (!cookieStr) { showToast("error", "请先粘贴 Cookie 字符串"); return; }
    const displayName = sourceProviders.find((p) => p.source_name === sourceName)?.display_name ?? sourceName;
    setCookieImporting((prev) => ({ ...prev, [sourceName]: true }));
    try {
      const res = await fetch(`${apiBaseUrl}/source-auth/${sourceName}/import-cookie`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cookie_string: cookieStr }),
      });
      if (!res.ok) {
        let detail = `${displayName} Cookie 导入失败`;
        try { const p = await res.json(); if (p.detail) detail = p.detail; } catch { /* */ }
        throw new Error(detail);
      }
      const payload: SourceAuthVerifyResponse = await res.json();
      setSourceAuthStatus((prev) => {
        const next = { ...prev, [sourceName]: { verified: payload.status === "verified", verified_at: payload.verified_at, message: payload.message } };
        localStorage.setItem(sourceAuthStatusStorageKey, JSON.stringify(next));
        return next;
      });
      setCookieInput((prev) => ({ ...prev, [sourceName]: "" }));
      showToast("success", `${displayName} Cookie 导入成功`);
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Cookie 导入失败");
    } finally {
      setCookieImporting((prev) => ({ ...prev, [sourceName]: false }));
    }
  }

  const hasAnyCreds = (name: string) => {
    const creds = sourceCredentials[name];
    return creds && Object.values(creds).some((v) => v.trim());
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
      {/* Tab Buttons */}
      <div className="flex justify-center gap-3 mb-8">
        <button
          onClick={() => setActiveTab("sources")}
          className={`inline-flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-colors cursor-pointer ${
            activeTab === "sources"
              ? "bg-blue-600 text-white shadow-sm"
              : "bg-white text-slate-600 hover:bg-slate-50 border border-slate-200"
          }`}
        >
          <Key className="h-4 w-4" />
          数据源账号
        </button>
        <button
          onClick={() => setActiveTab("ai")}
          className={`inline-flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium transition-colors cursor-pointer ${
            activeTab === "ai"
              ? "bg-blue-600 text-white shadow-sm"
              : "bg-white text-slate-600 hover:bg-slate-50 border border-slate-200"
          }`}
        >
          <Sparkles className="h-4 w-4" />
          AI 配置
        </button>
      </div>

      {/* Sources Tab */}
        {activeTab === "sources" && (
          <div className="space-y-6">
            {sourceProviders.map((provider) => {
              const status = sourceAuthStatus[provider.source_name];
              const creds = sourceCredentials[provider.source_name] ?? {};
              const isEditing = editingProvider === provider.source_name;
              const isVerified = status?.verified;
              const isVerifying = sourceVerifying[provider.source_name];

              return (
                <div key={provider.source_name} className="card overflow-hidden">
                  {/* Provider Header */}
                  <div
                    className="flex items-center justify-between px-5 py-4 cursor-pointer hover:bg-slate-50/50 transition-colors"
                    onClick={() => setEditingProvider(isEditing ? null : provider.source_name)}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${
                        isVerified ? "bg-emerald-50" : "bg-slate-100"
                      }`}>
                        {isVerified ? (
                          <Shield className="h-5 w-5 text-emerald-600" />
                        ) : (
                          <Key className="h-5 w-5 text-slate-400" />
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900">{provider.display_name}</span>
                          {isVerified ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                              <CircleCheck className="h-3 w-3" /> 已验证
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 ring-1 ring-inset ring-slate-600/20">
                              <Circle className="h-3 w-3" /> 未验证
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-slate-500 mt-0.5">
                          数据源：{provider.task_sources.map((s) => s.includes("business") ? "商业数据" : "海关数据").join("、")}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {status?.verified_at && (
                        <span className="text-[11px] text-slate-400">
                          验证于 {new Date(status.verified_at).toLocaleString("zh-CN")}
                        </span>
                      )}
                      <svg className={`h-4 w-4 text-slate-400 transition-transform ${isEditing ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </div>

                  {/* Expanded Content */}
                  {isEditing && (
                    <div className="border-t border-slate-100 px-5 py-5 bg-slate-50/30">
                      {/* Credential Fields */}
                      <div className="space-y-3">
                        <h4 className="text-xs font-semibold text-slate-700 uppercase tracking-wider">账号凭证</h4>
                        {provider.credential_fields.map((field) => (
                          <div key={field.name}>
                            <label className="mb-1 block text-xs font-medium text-slate-600">{field.label}</label>
                            <div className="relative">
                              <input
                                type={field.input_type === "password" && !showPasswords[provider.source_name] ? "password" : "text"}
                                placeholder={`输入${field.label}`}
                                value={creds[field.name] ?? ""}
                                onChange={(e) => updateCredential(provider.source_name, field.name, e.target.value)}
                                className="input-field text-sm"
                              />
                              {field.input_type === "password" && (
                                <button
                                  onClick={() => setShowPasswords((prev) => ({ ...prev, [provider.source_name]: !prev[provider.source_name] }))}
                                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600 cursor-pointer"
                                >
                                  {showPasswords[provider.source_name] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>

                      {/* Action Buttons */}
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          onClick={() => saveCredentials(provider.source_name)}
                          disabled={!hasAnyCreds(provider.source_name)}
                          className="btn-secondary text-xs !py-2 cursor-pointer"
                        >
                          <Save className="h-3.5 w-3.5 mr-1" /> 保存凭证
                        </button>
                        <button
                          onClick={() => verifySource(provider.source_name)}
                          disabled={isVerifying || !hasAnyCreds(provider.source_name)}
                          className="btn-primary text-xs !py-2 cursor-pointer"
                        >
                          {isVerifying ? (
                            <><Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> 等待浏览器登录中...</>
                          ) : (
                            <><ExternalLink className="h-3.5 w-3.5 mr-1" /> 打开浏览器登录</>
                          )}
                        </button>
                        <button
                          onClick={() => clearCredentials(provider.source_name)}
                          className="btn-danger text-xs !py-2 cursor-pointer"
                        >
                          <Trash2 className="h-3.5 w-3.5 mr-1" /> 清空
                        </button>
                      </div>

                      {/* Cookie Import */}
                      <div className="mt-5 border-t border-slate-200 pt-4">
                        <h4 className="text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2">Cookie 导入</h4>
                        <p className="text-[11px] text-slate-500 mb-2">
                          如果你已有浏览器 Cookie，可直接粘贴导入，无需打开浏览器登录
                        </p>
                        <textarea
                          value={cookieInput[provider.source_name] ?? ""}
                          onChange={(e) => setCookieInput((prev) => ({ ...prev, [provider.source_name]: e.target.value }))}
                          placeholder="粘贴 curl 命令或 Cookie 字符串..."
                          rows={3}
                          className="input-field text-xs !font-mono"
                        />
                        <button
                          onClick={() => importCookie(provider.source_name)}
                          disabled={cookieImporting[provider.source_name] || !cookieInput[provider.source_name]?.trim()}
                          className="btn-secondary text-xs !py-2 mt-2 cursor-pointer"
                        >
                          {cookieImporting[provider.source_name] ? (
                            <><Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> 导入中...</>
                          ) : (
                            <><Upload className="h-3.5 w-3.5 mr-1" /> 导入 Cookie</>
                          )}
                        </button>
                      </div>

                      {/* Status Message */}
                      {status?.message && (
                        <div className={`mt-4 rounded-lg px-3 py-2 text-xs ${
                          isVerified ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"
                        }`}>
                          {status.message}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {sourceProviders.length === 0 && (
              <div className="card p-8 text-center">
                <Key className="mx-auto h-8 w-8 text-slate-300" />
                <p className="mt-2 text-sm text-slate-500">暂无可用数据源</p>
              </div>
            )}
          </div>
        )}

        {/* AI Config Tab */}
        {activeTab === "ai" && (
          <div>
            <div className="card overflow-hidden">
              {/* AI Header */}
              <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-100">
                <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${
                  aiConfig.api_key ? "bg-amber-50" : "bg-slate-100"
                }`}>
                  <Sparkles className={`h-5 w-5 ${aiConfig.api_key ? "text-amber-600" : "text-slate-400"}`} />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900">AI 提取服务</span>
                    {aiConfig.api_key ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-inset ring-emerald-600/20">
                        <CircleCheck className="h-3 w-3" /> 已配置
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 ring-1 ring-inset ring-slate-600/20">
                        未配置
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">兼容 OpenAI API 格式的 AI 服务，用于客户评估和总结生成</p>
                </div>
              </div>

              {/* AI Config Form */}
              <div className="px-5 py-5 space-y-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-700">API Key</label>
                  <input
                    type="password"
                    placeholder="sk-..."
                    value={aiConfig.api_key}
                    onChange={(e) => setAiConfig((prev) => ({ ...prev, api_key: e.target.value }))}
                    className="input-field text-sm"
                  />
                  <p className="mt-1 text-[11px] text-slate-400">AI 服务的 API 密钥，必填</p>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-700">API 地址</label>
                  <input
                    type="text"
                    placeholder="https://api.siliconflow.cn/v1"
                    value={aiConfig.base_url}
                    onChange={(e) => setAiConfig((prev) => ({ ...prev, base_url: e.target.value }))}
                    className="input-field text-sm"
                  />
                  <p className="mt-1 text-[11px] text-slate-400">OpenAI 兼容格式的 API 地址</p>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-700">模型名称</label>
                  <input
                    type="text"
                    placeholder="Qwen/Qwen3-8B"
                    value={aiConfig.model}
                    onChange={(e) => setAiConfig((prev) => ({ ...prev, model: e.target.value }))}
                    className="input-field text-sm"
                  />
                  <p className="mt-1 text-[11px] text-slate-400">模型标识，如 Qwen/Qwen3-8B、gpt-4o-mini 等</p>
                </div>

                {/* AI Actions */}
                <div className="flex gap-2 pt-2">
                  <button
                    onClick={saveAiConfig}
                    disabled={!aiConfig.api_key}
                    className="btn-primary text-xs !py-2 cursor-pointer"
                  >
                    <Save className="h-3.5 w-3.5 mr-1" /> 保存配置
                  </button>
                  {aiConfig.api_key && (
                    <button onClick={clearAiConfig} className="btn-danger text-xs !py-2 cursor-pointer">
                      <Trash2 className="h-3.5 w-3.5 mr-1" /> 清除配置
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* AI Description */}
            <div className="mt-6 card p-5">
              <h3 className="text-sm font-semibold text-slate-900 mb-3">AI 功能说明</h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg bg-blue-50/50 border border-blue-100 px-4 py-3">
                  <div className="flex items-center gap-2 text-xs font-semibold text-blue-700 mb-1">
                    <Sparkles className="h-3.5 w-3.5" /> 客户评估
                  </div>
                  <p className="text-[11px] text-slate-600">根据搜索关键词评估公司匹配度，计算评分和置信度</p>
                </div>
                <div className="rounded-lg bg-emerald-50/50 border border-emerald-100 px-4 py-3">
                  <div className="flex items-center gap-2 text-xs font-semibold text-emerald-700 mb-1">
                    <Sparkles className="h-3.5 w-3.5" /> 智能总结
                  </div>
                  <p className="text-[11px] text-slate-600">为商业数据和海关数据生成简洁的公司/交易总结</p>
                </div>
                <div className="rounded-lg bg-amber-50/50 border border-amber-100 px-4 py-3">
                  <div className="flex items-center gap-2 text-xs font-semibold text-amber-700 mb-1">
                    <Sparkles className="h-3.5 w-3.5" /> 匹配原因
                  </div>
                  <p className="text-[11px] text-slate-600">分析公司业务与搜索关键词的关联原因</p>
                </div>
                <div className="rounded-lg bg-purple-50/50 border border-purple-100 px-4 py-3">
                  <div className="flex items-center gap-2 text-xs font-semibold text-purple-700 mb-1">
                    <Sparkles className="h-3.5 w-3.5" /> 邮箱提取
                  </div>
                  <p className="text-[11px] text-slate-600">从公司网站提取联系人邮箱信息</p>
                </div>
              </div>
            </div>
          </div>
        )}

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-6 right-6 flex items-center gap-2 rounded-lg px-4 py-3 text-sm font-medium shadow-lg transition-all ${
          toast.type === "success" ? "bg-emerald-600 text-white" : "bg-red-600 text-white"
        }`}>
          {toast.type === "success" ? <CircleCheck className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
          {toast.message}
        </div>
      )}
    </div>
  );
}
