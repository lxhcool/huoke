"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import type {
  FeedbackRequest,
  SearchJob,
  SearchJobResultsResponse,
  SearchRequest,
  SourceAuthProvider,
  SourceAuthProviderListResponse,
  SourceAuthVerifyResponse,
} from "../lib/types";

const defaultSourceInput = "joinf, linkedin";

const initialForm: SearchRequest = {
  query: "帮我找德国做激光切割设备、最近一年有进口记录的公司",
  sources: ["joinf_business", "joinf_customs", "linkedin_company", "linkedin_contact"],
  country: "Germany",
  hs_code: "845611",
  customer_profile_mode: "small_wholesale",
  customs_required: true,
  limit: 10,
};

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

const sourceAliasMap: Record<string, string[]> = {
  joinf: ["joinf_business", "joinf_customs"],
  joinf_business: ["joinf_business"],
  joinf_customs: ["joinf_customs"],
  "cloud.joinf.com": ["joinf_business", "joinf_customs"],
  linkedin: ["linkedin_company", "linkedin_contact"],
  "领英": ["linkedin_company", "linkedin_contact"],
  linkedin_company: ["linkedin_company"],
  linkedin_contact: ["linkedin_contact"],
};

const sourceCredentialStorageKey = "huoke.sourceCredentials.v1";
const sourceAuthStatusStorageKey = "huoke.sourceAuthStatus.v1";

type SourceCredentialStore = Record<string, Record<string, string>>;

type SourceAuthStatusStore = Record<
  string,
  {
    verified: boolean;
    verified_at?: string;
    message?: string;
  }
>;

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
  {
    source_name: "linkedin",
    display_name: "LinkedIn",
    task_sources: ["linkedin_company", "linkedin_contact"],
    credential_fields: [
      { name: "username", label: "账号", input_type: "text", required: true },
      { name: "password", label: "密码", input_type: "password", required: true },
    ],
  },
];

function parseStorage<T>(value: string | null, fallback: T): T {
  if (!value) {
    return fallback;
  }

  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

function normalizeSources(input: string) {
  const rawItems = input
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  const recognized = new Set<string>();
  const unsupported: string[] = [];

  rawItems.forEach((item) => {
    const normalizedKey = item.toLowerCase();
    const mapped = sourceAliasMap[item] ?? sourceAliasMap[normalizedKey];

    if (!mapped) {
      unsupported.push(item);
      return;
    }

    mapped.forEach((source) => recognized.add(source));
  });

  return {
    recognized: Array.from(recognized),
    unsupported,
  };
}

export function SearchWorkbench() {
  const [form, setForm] = useState<SearchRequest>(initialForm);
  const [sourceInput, setSourceInput] = useState(defaultSourceInput);
  const [job, setJob] = useState<SearchJob | null>(null);
  const [results, setResults] = useState<SearchJobResultsResponse | null>(null);
  const [sourceProviders, setSourceProviders] = useState<SourceAuthProvider[]>([]);
  const [sourceCredentials, setSourceCredentials] = useState<SourceCredentialStore>({});
  const [sourceAuthStatus, setSourceAuthStatus] = useState<SourceAuthStatusStore>({});
  const [sourceVerifying, setSourceVerifying] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);

  const normalizedSources = useMemo(() => normalizeSources(sourceInput), [sourceInput]);

  const providerDisplayMap = useMemo(
    () => Object.fromEntries(sourceProviders.map((provider) => [provider.source_name, provider.display_name])),
    [sourceProviders]
  );

  const taskSourceToProviderMap = useMemo(() => {
    const entries: Record<string, string> = {};
    sourceProviders.forEach((provider) => {
      provider.task_sources.forEach((taskSource) => {
        entries[taskSource] = provider.source_name;
      });
    });
    return entries;
  }, [sourceProviders]);

  const selectedProviderNames = useMemo(() => {
    const providers = new Set<string>();
    normalizedSources.recognized.forEach((taskSource) => {
      const providerName = taskSourceToProviderMap[taskSource] ?? taskSource.split("_")[0];
      if (providerName) {
        providers.add(providerName);
      }
    });
    return Array.from(providers);
  }, [normalizedSources.recognized, taskSourceToProviderMap]);

  const selectedUnverifiedProviders = useMemo(
    () => selectedProviderNames.filter((providerName) => !sourceAuthStatus[providerName]?.verified),
    [selectedProviderNames, sourceAuthStatus]
  );

  const selectedVerifiedSources = useMemo(
    () =>
      normalizedSources.recognized.filter((taskSource) => {
        const providerName = taskSourceToProviderMap[taskSource] ?? taskSource.split("_")[0];
        return Boolean(providerName && sourceAuthStatus[providerName]?.verified);
      }),
    [normalizedSources.recognized, taskSourceToProviderMap, sourceAuthStatus]
  );

  useEffect(() => {
    let cancelled = false;

    async function loadSourceProviders() {
      try {
        const response = await fetch(`${apiBaseUrl}/source-auth/providers`);
        if (!response.ok) {
          throw new Error("load source auth providers failed");
        }

        const data: SourceAuthProviderListResponse = await response.json();
        if (!cancelled) {
          setSourceProviders(data.items);
        }
      } catch {
        if (!cancelled) {
          setSourceProviders(fallbackSourceProviders);
        }
      }
    }

    loadSourceProviders();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const storedCredentials = parseStorage<SourceCredentialStore>(
      window.localStorage.getItem(sourceCredentialStorageKey),
      {}
    );
    setSourceCredentials(storedCredentials);

    const storedAuthStatus = parseStorage<SourceAuthStatusStore>(
      window.localStorage.getItem(sourceAuthStatusStorageKey),
      {}
    );
    setSourceAuthStatus(storedAuthStatus);
  }, []);

  useEffect(() => {
    if (!job || ["completed", "completed_with_errors"].includes(job.status)) {
      return;
    }

    const timer = window.setInterval(async () => {
      try {
        const [jobResponse, resultsResponse] = await Promise.all([
          fetch(`${apiBaseUrl}/search-jobs/${job.id}`),
          fetch(`${apiBaseUrl}/search-jobs/${job.id}/results`),
        ]);

        if (jobResponse.ok) {
          const jobData: SearchJob = await jobResponse.json();
          setJob(jobData);
        }

        if (resultsResponse.ok) {
          const resultsData: SearchJobResultsResponse = await resultsResponse.json();
          setResults(resultsData);
        }
      } catch {
        // ignore polling transient errors in demo phase
      }
    }, 3000);

    return () => window.clearInterval(timer);
  }, [job]);

  function updateSourceCredential(sourceName: string, fieldName: string, value: string) {
    setSourceCredentials((previous) => ({
      ...previous,
      [sourceName]: {
        ...(previous[sourceName] ?? {}),
        [fieldName]: value,
      },
    }));
  }

  function saveSourceCredentials(sourceName: string) {
    setSourceCredentials((previous) => {
      const next = {
        ...previous,
        [sourceName]: {
          ...(previous[sourceName] ?? {}),
        },
      };
      window.localStorage.setItem(sourceCredentialStorageKey, JSON.stringify(next));
      return next;
    });
    const sourceDisplayName = providerDisplayMap[sourceName] ?? sourceName;
    setFeedbackMessage(`${sourceDisplayName} 凭证已保存到当前浏览器。`);
  }

  function clearSourceCredentials(sourceName: string) {
    setSourceCredentials((previous) => {
      const next = { ...previous };
      delete next[sourceName];
      window.localStorage.setItem(sourceCredentialStorageKey, JSON.stringify(next));
      return next;
    });

    setSourceAuthStatus((previous) => {
      const next = { ...previous };
      delete next[sourceName];
      window.localStorage.setItem(sourceAuthStatusStorageKey, JSON.stringify(next));
      return next;
    });

    const sourceDisplayName = providerDisplayMap[sourceName] ?? sourceName;
    setFeedbackMessage(`${sourceDisplayName} 本地凭证与验证状态已清空。`);
  }

  async function verifySourceCredentials(sourceName: string) {
    const provider = sourceProviders.find((item) => item.source_name === sourceName);
    if (!provider) {
      setError(`未找到数据源配置：${sourceName}`);
      return;
    }

    const credentials = sourceCredentials[sourceName] ?? {};
    const hasAnyCredential = provider.credential_fields.some((field) => (credentials[field.name] || "").trim().length > 0);
    if (hasAnyCredential) {
      const missingFields = provider.credential_fields
        .filter((field) => field.required)
        .filter((field) => !(credentials[field.name] || "").trim());

      if (missingFields.length > 0) {
        const labels = missingFields.map((field) => field.label).join("、");
        setError(`${provider.display_name} 缺少必填项：${labels}`);
        return;
      }
    }

    setSourceVerifying((previous) => ({ ...previous, [sourceName]: true }));
    setError(null);

    try {
      const response = await fetch(`${apiBaseUrl}/source-auth/${sourceName}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credentials }),
      });

      if (!response.ok) {
        let detail = `${provider.display_name} 登录验证失败`;
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload.detail) {
            detail = payload.detail;
          }
        } catch {
          // ignore parse errors
        }
        throw new Error(detail);
      }

      const payload: SourceAuthVerifyResponse = await response.json();
      setSourceAuthStatus((previous) => {
        const next = {
          ...previous,
          [sourceName]: {
            verified: payload.status === "verified",
            verified_at: payload.verified_at,
            message: payload.message,
          },
        };
        window.localStorage.setItem(sourceAuthStatusStorageKey, JSON.stringify(next));
        return next;
      });

      setFeedbackMessage(`${provider.display_name} 登录态验证成功。`);
    } catch (verifyError) {
      const message = verifyError instanceof Error ? verifyError.message : "登录验证失败";
      setSourceAuthStatus((previous) => {
        const next = {
          ...previous,
          [sourceName]: {
            verified: false,
            message,
          },
        };
        window.localStorage.setItem(sourceAuthStatusStorageKey, JSON.stringify(next));
        return next;
      });
      setError(message);
    } finally {
      setSourceVerifying((previous) => ({ ...previous, [sourceName]: false }));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);

    try {
      if (normalizedSources.recognized.length === 0) {
        throw new Error("没有可用的数据源，请检查抓取网站输入内容。");
      }

      if (selectedVerifiedSources.length === 0) {
        throw new Error("请先至少验证一个数据源登录后再查询。");
      }

      if (selectedVerifiedSources.length < normalizedSources.recognized.length) {
        const names = selectedUnverifiedProviders.map((sourceName) => providerDisplayMap[sourceName] ?? sourceName);
        if (names.length > 0) {
          setFeedbackMessage(`已自动跳过未验证数据源：${names.join("、")}`);
        }
      }

      const response = await fetch(`${apiBaseUrl}/search-jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          sources: selectedVerifiedSources,
        }),
      });

      if (!response.ok) {
        throw new Error("搜索请求失败，请检查 API 服务是否已启动。");
      }

      const jobData: SearchJob = await response.json();
      setJob(jobData);

      const resultsResponse = await fetch(`${apiBaseUrl}/search-jobs/${jobData.id}/results`);
      if (resultsResponse.ok) {
        const resultsData: SearchJobResultsResponse = await resultsResponse.json();
        setResults(resultsData);
      }
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "未知错误");
    } finally {
      setLoading(false);
    }
  }

  function resetForm() {
    setForm(initialForm);
    setSourceInput(defaultSourceInput);
    setJob(null);
    setResults(null);
    setError(null);
    setFeedbackMessage(null);
  }

  async function submitFeedback(payload: FeedbackRequest) {
    setFeedbackMessage(null);

    try {
      const response = await fetch(`${apiBaseUrl}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error("反馈提交失败");
      }

      setFeedbackMessage(`已记录：${payload.action}`);
    } catch (feedbackError) {
      setFeedbackMessage(feedbackError instanceof Error ? feedbackError.message : "反馈提交失败");
    }
  }

  return (
    <div className="page">
      <div className="shell">
        <section className="hero">
          <h1>Huoke 线索发现 Agent</h1>
          <p>先跑通“产品词 + 国家 + 海关条件 -&gt; 公司 + 联系人 + 企业邮箱”的内部工作台。</p>
        </section>

        <div className="grid">
          <aside className="panel">
            <h2>搜索条件</h2>
            <div className="panel" style={{ padding: 16, marginBottom: 16 }}>
              <h3 style={{ marginTop: 0 }}>数据源账号管理</h3>
              <p className="hint">账号密码仅保存在当前浏览器。可填写账号密码自动登录，也可留空后点击“验证登录”手动登录。</p>

              {sourceProviders.length === 0 ? <div className="hint">加载数据源配置中...</div> : null}

              <div className="resultList">
                {sourceProviders.map((provider) => {
                  const status = sourceAuthStatus[provider.source_name];
                  const credentials = sourceCredentials[provider.source_name] ?? {};

                  return (
                    <div className="card" key={provider.source_name}>
                      <div className="cardHeader">
                        <strong>{provider.display_name}</strong>
                        <span className="tag">{status?.verified ? "已验证" : "未验证"}</span>
                      </div>

                      {provider.credential_fields.map((field) => (
                        <div className="field" key={`${provider.source_name}-${field.name}`}>
                          <label htmlFor={`${provider.source_name}-${field.name}`}>{field.label}</label>
                          <input
                            id={`${provider.source_name}-${field.name}`}
                            type={field.input_type}
                            value={credentials[field.name] ?? ""}
                            onChange={(event) =>
                              updateSourceCredential(provider.source_name, field.name, event.target.value)
                            }
                            autoComplete="off"
                          />
                        </div>
                      ))}

                      <div className="actions">
                        <button
                          className="button secondary"
                          type="button"
                          onClick={() => saveSourceCredentials(provider.source_name)}
                        >
                          保存到本地
                        </button>
                        <button
                          className="button secondary"
                          type="button"
                          disabled={sourceVerifying[provider.source_name]}
                          onClick={() => verifySourceCredentials(provider.source_name)}
                        >
                          {sourceVerifying[provider.source_name] ? "验证中..." : "验证登录"}
                        </button>
                        <button
                          className="button secondary"
                          type="button"
                          onClick={() => clearSourceCredentials(provider.source_name)}
                        >
                          清空
                        </button>
                      </div>

                      {status?.message ? <div className="hint">{status.message}</div> : null}
                      {status?.verified_at ? <div className="hint">最近验证：{status.verified_at}</div> : null}
                    </div>
                  );
                })}
              </div>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="field">
                <label htmlFor="query">自然语言查询</label>
                <textarea
                  id="query"
                  value={form.query}
                  onChange={(event) => setForm({ ...form, query: event.target.value })}
                />
              </div>

              <div className="field">
                <label htmlFor="sources">抓取网站</label>
                <input
                  id="sources"
                  value={sourceInput}
                  onChange={(event) => setSourceInput(event.target.value)}
                  placeholder="joinf, linkedin"
                />
                <p className="hint">使用逗号分隔。支持示例：`joinf`、`linkedin`、`joinf_business`、`joinf_customs`。</p>
                <div className="tags">
                  {normalizedSources.recognized.map((source) => (
                    <span className="tag" key={source}>
                      {source}
                    </span>
                  ))}
                </div>
                {normalizedSources.unsupported.length > 0 ? (
                  <div className="warningBox">暂不支持的数据源：{normalizedSources.unsupported.join("、")}</div>
                ) : null}
                {selectedUnverifiedProviders.length > 0 ? (
                  <div className="warningBox">
                    以下数据源尚未验证登录：
                    {selectedUnverifiedProviders
                      .map((sourceName) => providerDisplayMap[sourceName] ?? sourceName)
                      .join("、")}
                  </div>
                ) : null}
                {normalizedSources.recognized.length > 6 ? (
                  <div className="warningBox">
                    当前已识别 {normalizedSources.recognized.length} 个来源，抓取耗时、失败率和反爬风险都会明显上升。
                  </div>
                ) : normalizedSources.recognized.length > 4 ? (
                  <div className="warningBox">
                    当前已识别 {normalizedSources.recognized.length} 个来源，查询可能变慢，部分来源可能延迟返回。
                  </div>
                ) : null}
              </div>

              <div className="field">
                <label htmlFor="customerProfileMode">客户类型偏好</label>
                <select
                  id="customerProfileMode"
                  value={form.customer_profile_mode}
                  onChange={(event) => setForm({ ...form, customer_profile_mode: event.target.value })}
                >
                  <option value="small_wholesale">批发小单</option>
                  <option value="general">通用</option>
                  <option value="bulk_buying">大单采购</option>
                </select>
              </div>

              <div className="field">
                <label htmlFor="country">国家/地区</label>
                <input
                  id="country"
                  value={form.country ?? ""}
                  onChange={(event) => setForm({ ...form, country: event.target.value })}
                />
              </div>

              <div className="field">
                <label htmlFor="hsCode">HS Code</label>
                <input
                  id="hsCode"
                  value={form.hs_code ?? ""}
                  onChange={(event) => setForm({ ...form, hs_code: event.target.value })}
                />
              </div>

              <div className="field">
                <label htmlFor="limit">结果条数</label>
                <input
                  id="limit"
                  type="number"
                  min={1}
                  max={50}
                  value={form.limit}
                  onChange={(event) => setForm({ ...form, limit: Number(event.target.value) || 10 })}
                />
              </div>

              <div className="field">
                <label>
                  <input
                    type="checkbox"
                    checked={form.customs_required}
                    onChange={(event) => setForm({ ...form, customs_required: event.target.checked })}
                    style={{ marginRight: 8 }}
                  />
                  必须有关联海关数据
                </label>
              </div>

              <div className="actions">
                <button className="button primary" type="submit" disabled={loading}>
                  {loading ? "检索中..." : "开始搜索"}
                </button>
                <button className="button secondary" type="button" onClick={resetForm}>
                  重置
                </button>
              </div>

              <p className="hint">当前为真实来源任务流模式，建议先完成数据源登录验证再搜索。</p>
            </form>
          </aside>

          <section className="panel">
            <div className="resultsHeader">
              <div>
                <h2>搜索结果</h2>
                <p className="hint">展示任务状态、多源进度、首批结果和后台增强结果。</p>
              </div>
              {results ? <span className="tag">共 {results.total} 条</span> : null}
            </div>

            {error ? <div className="empty">{error}</div> : null}
            {feedbackMessage ? <div className="empty">{feedbackMessage}</div> : null}

            {!error && !job ? (
              <div className="empty">输入搜索条件后开始查询，系统会先创建搜索任务，再逐步返回多源聚合结果。</div>
            ) : null}

            {job ? (
              <>
                <div className="tags">
                  <span className="tag">任务 #{job.id}</span>
                  <span className="tag">状态：{job.status}</span>
                  <span className="tag">客户偏好：{job.customer_profile_mode}</span>
                  <span className="tag">国家：{job.country ?? "未指定"}</span>
                  <span className="tag">海关筛选：{job.customs_required ? "是" : "否"}</span>
                  {job.hs_code ? <span className="tag">HS Code：{job.hs_code}</span> : null}
                  {job.sources.map((source) => (
                    <span className="tag" key={source}>
                      {source}
                    </span>
                  ))}
                </div>

                <div className="panel" style={{ padding: 16, marginTop: 16, marginBottom: 16 }}>
                  <h3 style={{ marginTop: 0 }}>数据源进度</h3>
                  <div className="resultList">
                    {job.source_tasks.map((task) => (
                      <div className="card" key={task.id}>
                        <div className="cardHeader">
                          <strong>{task.source_name}</strong>
                          <span className="tag">{task.status}</span>
                        </div>
                        {task.error_message ? <div className="warningBox">{task.error_message}</div> : null}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="resultList">
                  {results?.items.map((item) => (
                    <article className="card" key={item.company_name}>
                      <div className="cardHeader">
                        <div>
                          <h3>{item.company_name}</h3>
                          <div className="meta">
                            <span className="tag">{item.country}</span>
                            {item.city ? <span className="tag">{item.city}</span> : null}
                            {item.industry ? <span className="tag">{item.industry}</span> : null}
                            <span className="tag">置信度 {item.confidence}</span>
                            <span className="tag">结果状态 {item.result_status}</span>
                            {item.intent_label ? <span className="tag">{item.intent_label}</span> : null}
                          </div>
                        </div>
                        <div className="score">{item.score}</div>
                      </div>

                      {item.website ? (
                        <div className="meta">
                          <a href={item.website} target="_blank" rel="noreferrer">
                            {item.website}
                          </a>
                        </div>
                      ) : null}

                      <div className="reasons">
                        {item.match_reasons.map((reason) => (
                          <div className="reason" key={reason}>
                            {reason}
                          </div>
                        ))}
                      </div>

                      <div className="tags">
                        {item.source_names.map((sourceName) => (
                          <span className="tag" key={`${item.id}-${sourceName}`}>
                            {sourceName}
                          </span>
                        ))}
                      </div>

                      {item.customs_summary ? (
                        <div className="tags">
                          <span className="tag">{item.customs_summary.active_label}</span>
                          <span className="tag">最近交易：{item.customs_summary.last_trade_at}</span>
                          <span className="tag">频次：{item.customs_summary.frequency}</span>
                          {item.customs_summary.hs_code ? (
                            <span className="tag">HS Code：{item.customs_summary.hs_code}</span>
                          ) : null}
                        </div>
                      ) : null}

                      <div className="contacts">
                        {item.contacts.map((contact) => (
                          <div className="contact" key={`${item.company_name}-${contact.name}`}>
                            <strong>{contact.name}</strong>
                            <div>{contact.title}</div>
                            <div>{contact.email ?? "暂无邮箱"}</div>
                            <div className="hint">
                              {contact.email_type ?? "unknown"} · 置信度 {contact.confidence}
                            </div>
                          </div>
                        ))}
                      </div>

                      <div className="actions" style={{ marginTop: 16 }}>
                        <button
                          className="button secondary"
                          type="button"
                          onClick={() =>
                            submitFeedback({
                              company_id: item.company_id,
                              action: "favorite",
                              query_text: job.query,
                            })
                          }
                        >
                          收藏
                        </button>
                        <button
                          className="button secondary"
                          type="button"
                          onClick={() =>
                            submitFeedback({
                              company_id: item.company_id,
                              action: "invalid",
                              query_text: job.query,
                            })
                          }
                        >
                          标记无效
                        </button>
                      </div>
                    </article>
                  )) ?? []}
                </div>
              </>
            ) : null}
          </section>
        </div>
      </div>
    </div>
  );
}
