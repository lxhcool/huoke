"""
AI 驱动的通用网页抓取服务 — 全流程 AI 化。

架构：
  1. analyze_results_page()  -> AI 分析结果列表页 HTML -> 返回行选择器、详情按钮选择器
  2. extract_business_detail() -> AI 从详情页文本提取结构化数据
  3. extract_customs_detail() -> AI 从海关详情页提取结构化数据

兼容 OpenAI 格式的 API（硅基流动 SiliconFlow、OpenAI、DeepSeek 等均可使用）。
使用 httpx 直接调用 REST API，无需 openai SDK。

用法：
    from app.services.ai_extractor import AIExtractor
    ai = AIExtractor(api_key="sk-xxx", base_url="https://api.siliconflow.cn/v1", model="Qwen/Qwen3-8B")

    # 步骤1：让 AI 分析结果列表页结构
    structure = await ai.analyze_results_page(page_html)

    # 步骤2：用 AI 返回的选择器操作页面（找行、点按钮）

    # 步骤3：进详情页后用 AI 提取数据
    detail = await ai.extract_business_detail(detail_page_text)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# 默认超时（LLM 响应可能较慢）
_DEFAULT_TIMEOUT = 60.0


# ============================================================
# 页面结构分析 Schema — AI 分析结果列表页的 DOM 结构
# ============================================================
PAGE_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "page_type": {
            "type": "string",
            "enum": ["search_results", "detail", "unknown"],
            "description": "页面类型"
        },
        "row_selector": {
            "type": "string",
            "description": (
                "结果行/卡片的 CSS 选择器。每个匹配元素代表一条搜索结果。"
                "必须是能匹配多个元素的容器选择器。优先使用类名如 li.row-is-see, "
                "也可以用 :has() 等伪类。给出最精确的那个。"
            )
        },
        "row_count": {
            "type": "integer",
            "description": "当前页面可见的结果行数量"
        },
        "detail_button_selector": {
            "type": "string",
            "description": (
                "每行内部'查看详情/解密/更多'等进入详情页的按钮 CSS 选择器。"
                "可以是 span, button, a 等 Playwright 支持的选择器语法。"
                "例如: span:text('查看详情'), button:has-text('解密'), a[href*='detail']"
            )
        },
        "has_pagination": {
            "type": "boolean",
            "description": "是否有分页（多页结果）"
        },
        "next_page_selector": {
            "type": ["string", "null"],
            "description": "'下一页'按钮的 CSS 选择器，没有就 null"
        },
        "total_results_hint": {
            "type": ["string", "null"],
            "description": "页面上显示的总结果数文字（如 '共428条结果'）"
        },
        "field_selectors": {
            "type": "object",
            "description": "每行内部各业务字段的 CSS 选择器（相对于行元素）",
            "properties": {
                "company_name": {
                    "type": ["string", "null"],
                    "description": "公司名称所在元素的 CSS 选择器，如 .company-name、h3 a、.title 等"
                },
                "website": {
                    "type": ["string", "null"],
                    "description": "公司网站链接所在元素的 CSS 选择器，如 .website a、a[href*='http']、.url 等"
                },
                "country": {
                    "type": ["string", "null"],
                    "description": "国家/地区所在元素的 CSS 选择器，如 .country、.region、.location 等"
                },
                "description": {
                    "type": ["string", "null"],
                    "description": "公司简介/描述所在元素的 CSS 选择器，如 .description、.intro、.line-clamp-2 等"
                },
                "email_count": {
                    "type": ["string", "null"],
                    "description": "邮箱数量所在元素的 CSS 选择器，如 .email-count、.c-right 等"
                },
                "social_media": {
                    "type": ["string", "null"],
                    "description": "社交媒体链接容器元素的 CSS 选择器，如 .social-media、.social-links 等"
                }
            }
        }
    },
    "required": ["page_type", "row_selector", "row_count", "detail_button_selector"]
}

ANALYZE_PAGE_PROMPT = """你是一个网页自动化专家，擅长分析搜索结果页面的 DOM 结构。

用户会给你一个搜索结果页面的完整 HTML 片段（截取了列表区域）。
你需要分析出：
1. 每条搜索结果对应什么 HTML 元素？（行/卡片）
2. 点击哪里可以进入该结果的详情页？
3. 有没有翻页功能？
4. 每行内部各业务字段（公司名、网站、国家、描述等）对应什么 CSS 选择器？

⚠️ field_selectors 特别重要！你需要仔细分析每行 HTML 内部结构，找出各字段对应的元素。
例如：
- 公司名称可能在 .company-name、h3、.title 等元素内
- 网站链接可能在 .websiteBox a、.url a、a[href^="http"] 等元素内
- 国家可能在 .country、.region、.location 等元素内
- 公司描述可能在 .description、.intro、.line-clamp-2 等元素内
- 邮箱数量可能在含"邮箱"文字的元素附近
- 社交媒体链接在 .social-media 等容器内

⚠️ detail_button_selector（详情按钮选择器）特别重要，必须准确！
常见形式包括但不仅限于：
- 带 cursor-pointer 类名的元素：如 .company-name（公司名）、div.cursor-pointer（Vue 路由常用 div+click 实现跳转）
- <a> 或 <button> 标签（如 a:has-text("查看详情")）
- 包含"查看详情"、"详情"、"解密"等文字的 span/button
- 某些表格中整行 tr 都可以点击

判断方法：在 HTML 中找每行内部看起来能触发页面跳转或弹出详情弹窗的元素。
特别注意：
- 如果是 Element UI / Ant Design 等表格，详情入口通常是行内某个带 cursor-pointer 的 div/span（如公司名、产品名），不是 <a> 标签
- 优先找 .company-name、.cursor-pointer 这类语义明确的类
- 如果整行都可点击，detail_button_selector 写 "self"

分析规则：
- row_selector 必须是一个能匹配多条记录的 CSS 选择器
- 优先使用明确的类名（如 li.row-is-see, tr.el-table__row, div.result-item）
- 可以使用 Playwright 扩展语法如 :text(), :has() 等
- detail_button_selector 必须是行内相对选择器（相对于每行），不是全局的
- 如果整行都可点击，detail_button_selector 写 "self" 表示直接点行本身
- field_selectors 中的选择器都是相对于每行元素的，不是全局的
- 如果某个字段在 HTML 中找不到对应元素，填 null
- 直接返回 JSON，不要加 markdown 代码块"""

# ============================================================
# 商业数据详情提取 Schema
# ============================================================
BUSINESS_DETAIL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "company_name": {"type": "string", "description": "公司名称"},
        "country": {"type": ["string", "null"], "description": "所在国家"},
        "city": {"type": ["string", "null"], "description": "城市"},
        "industry": {"type": ["string", "null"], "description": "行业"},
        "website": {"type": ["string", "null"], "description": "公司网站 URL"},
        "description": {"type": "string", "description": "公司简介/描述"},
        "phone": {"type": ["string", "null"], "description": "电话号码"},
        "address": {"type": ["string", "null"], "description": "详细地址"},
        "founded_year": {"type": ["string", "null"], "description": "成立年份"},
        "employees": {"type": ["string", "null"], "description": "员工规模"},
        "revenue": {"type": ["string", "null"], "description": "年营收"},
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "联系人姓名"},
                    "title": {"type": "string", "description": "职位"},
                    "email": {"type": ["string", "null"], "description": "邮箱地址"},
                    "phone": {"type": ["string", "null"], "description": "电话"},
                    "confidence": {"type": "string", "enum": ["A", "B", "C"]},
                },
                "required": ["name", "title"]
            }
        },
        "social_media": {"type": "array", "items": {"type": "string"}},
        "products": {"type": "array", "items": {"type": "string"}, "description": "主营产品"},
        "markets": {"type": "array", "items": {"type": "string"}, "description": "出口市场"},
        "certifications": {"type": "array", "items": {"type": "string"}, "description": "认证资质"},
    },
    "required": ["company_name", "description"]
}

SYSTEM_PROMPT_BUSINESS = """你是专业商业数据提取助手。用户给你公司详情页的全部可见文本。
从中精确提取公司信息，返回严格 JSON。
规则：
1. 只提取明确存在的信息，不编造
2. 缺失字段填 null 或 []
3. 邮箱要合理格式（含@和域名）
4. description 尽量保留原文
5. 直接返回 JSON，不加 markdown
6. 保持原始语言不翻译"""

# ============================================================
# 海关数据详情提取 Schema
# ============================================================
CUSTOMS_DETAIL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "company_name": {"type": "string", "description": "采购商/公司名称"},
        "country": {"type": ["string", "null"], "description": "所在国家"},
        "hs_code": {"type": ["string", "null"], "description": "HS编码"},
        "product_description": {"type": "string", "description": "产品描述"},
        "trade_date": {"type": ["string", "null"], "description": "最近交易日期"},
        "frequency": {"type": ["integer", "null"], "description": "交易频次/次数"},
        "background": {"type": "string", "description": "公司背景信息"},
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "title": {"type": "string"},
                    "email": {"type": ["string", "null"]},
                    "phone": {"type": ["string", "null"]},
                    "confidence": {"type": "string", "enum": ["A", "B", "C"]},
                },
                "required": ["name", "title"]
            }
        },
    },
    "required": ["company_name"]
}

SYSTEM_PROMPT_CUSTOMS = """你是海关贸易数据提取助手。用户给你海关采购商详情页的全部可见文本。
从中精确提取采购商信息，返回严格 JSON。
规则：只提取明确信息，不编造；frequency 提取数字；直接 JSON 不加 markdown；保持原语言不翻译"""


class AIExtractor:
    """
    基于 LLM 的全链路网页抓取 AI 服务。

    三大能力：
    - analyze_results_page(): 分析结果列表页 DOM 结构
    - extract_business_detail(): 从商业详情页提取数据
    - extract_customs_detail(): 从海关详情页提取数据

    兼容 OpenAI 格式 API（硅基流动 / OpenAI / DeepSeek / 通义千问 等）。
    使用 httpx 直接调用 REST API，无需 openai SDK。
    所有配置通过构造函数传入（由前端 localStorage -> 搜索请求 -> 后端透传）。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
    ):
        """
        Args:
            api_key: API 密钥
            base_url: OpenAI 兼容 API 地址（如 https://api.siliconflow.cn/v1）
            model: 模型名称（如 Qwen/Qwen3-8B）
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

        if not self.api_key:
            logger.warning("[AIExtractor] 未配置 api_key，AI 功能不可用")

    def _available(self) -> bool:
        return bool(self.api_key)

    async def _call(
        self,
        system_prompt: str,
        user_content: str,
        schema: Dict[str, Any],
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """统一的 LLM 调用方法 — 使用 httpx 直连 OpenAI 兼容接口。
        
        降级策略：
        1. 先尝试 json_schema（OpenAI Structured Outputs）
        2. 失败则尝试 json_object（通用 JSON 模式，需要在 prompt 中描述格式）
        3. 再失败则无 response_format，从回复中提取 JSON
        """
        if not self._available():
            return {}

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        # Qwen3 禁用思考模式：在 user message 末尾加 /no_think
        # 这是 Qwen3 官方推荐的关闭思考模式的方式
        no_think_tag = ""
        if "qwen" in self.model.lower():
            no_think_tag = " /no_think"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content + no_think_tag},
        ]

        # 公共参数
        base_payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        # SiliconFlow 等 API 支持 enable_thinking 参数
        if "qwen" in self.model.lower():
            base_payload["enable_thinking"] = False

        # 策略1: json_schema（OpenAI Structured Outputs，部分模型不支持）
        p1 = {**base_payload, "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "output", "schema": schema},
        }}
        result = await self._try_call(url, headers, p1)
        if result is not None:
            return result

        # 策略2: json_object（通用 JSON 模式，更多模型支持）
        schema_hint = self._schema_to_hint(schema)
        enhanced_system = system_prompt + "\n\n你必须返回严格符合以下格式的 JSON：\n" + schema_hint
        p2 = {
            **base_payload,
            "messages": [
                {"role": "system", "content": enhanced_system},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
        }
        result = await self._try_call(url, headers, p2)
        if result is not None:
            return result

        # 策略3: 无 response_format，从回复中提取 JSON
        enhanced_system += "\n\n直接返回 JSON，不要加 markdown 代码块。"
        p3 = {
            **base_payload,
            "messages": [
                {"role": "system", "content": enhanced_system},
                {"role": "user", "content": user_content},
            ],
        }
        # 移除 response_format 避免干扰
        p3.pop("response_format", None)
        result = await self._try_call(url, headers, p3, extract_json=True)
        if result is not None:
            return result

        logger.error("[AIExtractor] 所有调用策略均失败")
        return {}

    async def _try_call(
        self,
        url: str,
        headers: dict,
        payload: dict,
        extract_json: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """执行一次 LLM 调用，返回解析后的 dict 或 None（失败时）"""
        fmt_type = payload.get("response_format", {}).get("type", "none")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(_DEFAULT_TIMEOUT)) as client:
                resp = await client.post(url, json=payload, headers=headers)
                
                if resp.status_code != 200:
                    print(f"[AIExtractor] API 返回 HTTP {resp.status_code}: {resp.text[:500]}")
                    resp.raise_for_status()
                
                data = resp.json()

            # 检查 API 返回错误
            if "error" in data:
                err_msg = data["error"].get("message", str(data["error"]))
                print(f"[AIExtractor] API 错误 (format={fmt_type}): {err_msg[:300]}")
                logger.warning(f"[AIExtractor] API error (format={fmt_type}): {err_msg[:300]}")
                return None

            # ★ 调试：打印完整的 message 结构
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""
            
            # 如果 content 为空，详细打印调试信息
            if not content.strip():
                print(f"[AIExtractor] ⚠️ content 为空! (format={fmt_type})")
                print(f"    message keys: {list(message.keys())}")
                print(f"    reasoning_content 长度: {len(reasoning)}")
                if reasoning.strip():
                    print(f"    reasoning_content 末尾200字: ...{reasoning[-200:]}")
                # 尝试从 reasoning_content 提取 JSON
                if reasoning.strip():
                    extracted = self._extract_json_string(reasoning)
                    if extracted.strip() and extracted.strip() != reasoning.strip():
                        content = extracted
                        print(f"    从 reasoning 提取到内容: {content[:200]}")
                    else:
                        # reasoning 本身可能末尾有 JSON
                        last_brace = reasoning.rfind("}")
                        if last_brace > 0:
                            # 从最后一个 { 到最后一个 } 截取
                            search_start = max(0, last_brace - 2000)
                            sub = reasoning[search_start:last_brace+1]
                            brace_start = sub.find("{")
                            if brace_start >= 0:
                                content = sub[brace_start:]
                                print(f"    从 reasoning 末尾截取: {content[:200]}")

            if not content.strip():
                print(f"[AIExtractor] LLM 返回空内容 (format={fmt_type})")
                return None

            if extract_json:
                content = self._extract_json_string(content)

            result = json.loads(content)
            if isinstance(result, dict):
                print(f"[AIExtractor] LLM 调用成功 (format={fmt_type})")
                logger.info(f"[AIExtractor] LLM 调用成功 (format={fmt_type})")
                return result
            print(f"[AIExtractor] LLM 返回非 dict 类型: {type(result)}")
            return None
        except json.JSONDecodeError as e:
            raw = content[:300] if isinstance(content, str) else str(content)[:300]
            print(f"[AIExtractor] JSON 解析失败 (format={fmt_type}): {e}, 原文: {raw}")
            logger.warning(f"[AIExtractor] JSON 解析失败 (format={fmt_type}): {e}")
            return None
        except Exception as e:
            print(f"[AIExtractor] LLM 调用失败 (format={fmt_type}): {e}")
            logger.warning(f"[AIExtractor] LLM 调用失败 (format={fmt_type}): {e}")
            return None

    @staticmethod
    def _extract_json_string(text: str) -> str:
        """从可能包含 markdown 代码块的文本中提取 JSON 字符串"""
        import re
        # 尝试提取 ```json ... ``` 或 ``` ... ``` 中的内容
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # 如果整个文本看起来像 JSON
        text = text.strip()
        if text.startswith("{") and text.endswith("}"):
            return text
        # 找第一个 { 到最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return text[start:end+1]
        return text

    @staticmethod
    def _schema_to_hint(schema: Dict[str, Any], indent: int = 0) -> str:
        """将 JSON Schema 转换为人类可读的格式提示（用于 json_object 模式）"""
        props = schema.get("properties", {})
        required = schema.get("required", [])
        lines = []
        prefix = "  " * indent
        for key, val in props.items():
            req = " (必填)" if key in required else ""
            desc = val.get("description", "")
            t = val.get("type", "string")
            if isinstance(t, list):
                t = t[0]
            
            if t == "object":
                lines.append(f"{prefix}{key}{req}: {{")
                lines.append(AIExtractor._schema_to_hint(val, indent + 1))
                lines.append(f"{prefix}}}")
            elif t == "array":
                items = val.get("items", {})
                lines.append(f"{prefix}{key}{req}: [{{{AIExtractor._schema_to_hint(items, 0)}}}]")
            else:
                lines.append(f"{prefix}{key}: {t}{req} — {desc}")
        return "\n".join(lines)

    # ================================================================
    # 能力1：分析结果列表页的 DOM 结构（核心！适配任意网站）
    # ================================================================
    async def analyze_results_page(
        self,
        page_html: str,
        url: str = "",
        source_type: str = "business",
    ) -> Dict[str, Any]:
        """
        分析搜索结果列表页的 HTML 结构，返回如何定位行和详情按钮。

        Returns:
            { row_selector, detail_button_selector, row_count, ... }
        """
        if not self._available():
            logger.warning("[AIExtractor] 不可用，返回默认空结果")
            return {}

        html_snippet = page_html[:30000]
        if len(page_html) > 30000:
            html_snippet += f"\n<!-- HTML 已截断，原始长度 {len(page_html)} -->"

        context = f"页面 URL: {url}\n" if url else ""
        context += f"数据类型: {source_type}（商业数据或海关数据）\n\n"
        context += "以下是搜索结果页面的 HTML（列表区域）：\n\n"

        user_content = context + html_snippet

        logger.info(f"[AIExtractor] 分析结果列表页 HTML ({len(html_snippet)} 字符)")
        result = await self._call(ANALYZE_PAGE_PROMPT, user_content, PAGE_ANALYSIS_SCHEMA, max_tokens=1024)

        if result:
            logger.info(
                f"[AIExtractor] 页面分析完成: type={result.get('page_type')} "
                f"rows={result.get('row_count')} "
                f"row_sel={result.get('row_selector', 'N/A')} "
                f"btn={result.get('detail_button_selector', 'N/A')}"
            )
        else:
            logger.warning("[AIExtractor] 页面分析返回空结果")

        return result

    # ================================================================
    # 核心能力：AI 评估客户匹配度
    # 流程：列表行文本 → 提取网站URL → 访问网站 → AI 分析网站内容
    # ================================================================
    EVALUATE_COMPANY_SCHEMA: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "company_name": {"type": "string", "description": "公司名称"},
            "country": {"type": ["string", "null"], "description": "国家"},
            "website": {"type": ["string", "null"], "description": "网址"},
            "description": {"type": ["string", "null"], "description": "用中文概括的公司简介，基于对该公司业务的理解，不要照搬原文"},
            "products": {"type": "array", "items": {"type": "string"}, "description": "该公司经营的产品/业务"},
            "customer_type": {
                "type": ["string", "null"],
                "description": "客户类型分类：dealer(经销商)、wholesaler(批发商)、retailer(零售商)、distributor(分销商)、project_buyer(项目采购商如装修/展厅)、manufacturer(制造商)、competitor(竞争对手/供应商)、freight(货代物流)、unrelated(不相关)",
            },
            "match_score": {"type": "integer", "description": "匹配度评分 0-100"},
            "match_reason": {"type": "string", "description": "简述匹配/不匹配的理由，基于网站内容说明为什么这个公司是或不是潜在客户"},
            "contact_info": {
                "type": "object",
                "properties": {
                    "email": {"type": ["string", "null"], "description": "邮箱"},
                    "phone": {"type": ["string", "null"], "description": "电话"},
                    "linkedin": {"type": ["string", "null"], "description": "LinkedIn"},
                    "address": {"type": ["string", "null"], "description": "地址"},
                },
            },
        },
        "required": ["company_name", "match_score", "match_reason", "description", "customer_type"],
    }

    async def evaluate_company(
        self,
        row_text: str,
        my_product: str,
        source_type: str = "business",
        website_text: str = "",
    ) -> Dict[str, Any]:
        """
        AI 评估该公司是否为潜在客户。

        核心思路：结合列表信息和公司网站内容，让 AI 深度分析
        该公司是否是潜在买家。

        流程：
        1. 从列表行文本提取基本信息（公司名、国家、网站URL）
        2. 如果有网站URL，访问网站获取页面文本
        3. 将列表信息 + 网站内容一起给 AI 分析

        例如用户卖 LED 灯批发：
        - 国外 LED 经销商网站 → 高匹配（可以直接供货）
        - 展厅/博物馆网站提到装修项目 → 高匹配（项目采购，大量用灯）
        - 照明设计公司网站 → 高匹配（设计方案中会指定产品）
        - 竞争对手网站（也是卖灯的制造商）→ 低匹配（不是买家）
        - 货代公司网站 → 0分（不是买家）
        """
        if not self._available():
            return {}

        # 构建上下文
        context_parts = [
            f"用户的产品/业务：{my_product}",
            f"用户的定位：批发商/供应商，寻找可以供货的海外买家",
            f"数据来源：{'商业数据（公司信息）' if source_type == 'business' else '海关数据（进出口记录）'}",
        ]

        # 列表行信息
        user_content = f"=== 搜索列表行信息 ===\n{row_text[:3000]}"

        # 如果有网站内容，添加到分析上下文
        if website_text and website_text.strip():
            context_parts.append(
                "已获取该公司网站页面内容，请重点基于网站内容分析该公司是否是潜在客户。"
                "网站内容比列表信息更全面、更准确，应作为判断的主要依据。"
            )
            user_content += f"\n\n=== 该公司网站页面内容 ===\n{website_text[:8000]}"
        else:
            context_parts.append(
                "未能获取该公司网站内容，仅基于搜索列表行信息进行初步评估。"
                "如果信息不足，match_score 不超过 50。"
            )

        prompt = (
            f"你是一个专业的国际贸易客户开发专家，擅长分析公司是否为潜在采购客户。\n\n"
            + "\n".join(context_parts)
            + "\n\n请你从「供货」角度分析：\n\n"
            f"1. 这家公司是否需要采购「{my_product}」？\n"
            f"2. 匹配度评分（0-100）\n"
            f"3. 客户类型（经销商/批发商/零售商/分销商/项目采购商/制造商/竞争对手/货代/不相关）\n"
            f"4. 匹配理由（基于网站内容详细说明）\n"
            f"5. 提取可见信息（公司名、国家、网站、联系方式等）\n\n"
            f"⚠️ 重点提取以下信息（非常重要）：\n"
            f"- company_name：公司名称，务必准确提取\n"
            f"- website：公司网站URL\n"
            f"- contact_info：联系方式（邮箱、电话、地址），从网站内容中仔细查找\n"
            f"- products：该公司经营的产品/业务列表\n"
            f"- description：用你自己的理解总结公司简介，不要照搬原文，用简洁通顺的中文概括该公司的核心业务和特点，控制在100字以内\n\n"
            f"⚠️ 语言要求（非常重要）：\n"
            f"- 所有文本字段（description、match_reason、products、customer_type 等）必须使用中文\n"
            f"- description：不要逐字翻译原文，而是基于你对该公司业务的理解，用自然流畅的中文概括。例如原文是 \"A leading manufacturer of precision metal components for the automotive industry\"，你应该写 \"汽车行业精密金属零部件领先制造商\"，而不是生硬直译\n"
            f"- customer_type 使用中文：经销商、批发商、零售商、分销商、项目采购商、制造商、竞争对手、货代、不相关\n"
            f"- match_reason：用中文详细说明匹配/不匹配的原因，要有实际内容\n"
            f"- products：用中文列出产品/业务，保留专业术语英文原文（如 LED、OEM、CNC）\n\n"
            f"评分规则：\n"
            f"- 该公司是产品的经销商/分销商/批发商 → 高分(80-100)，可以直接供货\n"
            f"- 该公司虽不直接经营该产品，但业务场景需要大量采购 → 高分(70-89)\n"
            f"  例如：卖灯的经销商、需要装修的展厅/博物馆、照明设计公司、工程承包商\n"
            f"- 该公司经营互补产品，可能附带采购 → 中分(40-69)\n"
            f"  例如：建材商同时卖灯具、电工器材商\n"
            f"- 该公司是竞争对手（供应商而非买家）→ 低分(10-39)\n"
            f"  例如：同样是LED制造商、同样是出口商\n"
            f"- 该公司是货代/物流公司 → 0分\n"
            f"- 信息不足以判断 → 30分\n\n"
            f"直接返回 JSON，不加 markdown。"
        )

        result = await self._call(prompt, user_content, self.EVALUATE_COMPANY_SCHEMA, max_tokens=4096)

        if result:
            logger.info(f"[AIExtractor] 客户评估: {result.get('company_name', 'N/A')} -> 匹配度={result.get('match_score', 0)} 类型={result.get('customer_type', 'N/A')}")
        return result

    # ================================================================
    # 能力1.5：AI 修正详情按钮选择器（选择器匹配失败时调用）
    # ================================================================
    async def fix_detail_selector(
        self,
        row_html: str,
        failed_selector: str,
        url: str = "",
    ) -> str:
        """
        当 AI 返回的 detail_button_selector 匹配不到元素时，
        把该行的 HTML 发给 AI，让它重新判断该点哪里。

        Returns:
            修正后的 Playwright locator 字符串，如 ".company-name" 或 "self"
        """
        if not self._available():
            return ""

        FIX_SELECTOR_SCHEMA: Dict[str, Any] = {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "修正后的 Playwright locator（CSS 选择器或 :text() 语法）"
                },
                "reason": {
                    "type": "string",
                    "description": "简短说明为什么这个选择器更准确"
                }
            },
            "required": ["selector"]
        }

        html_snippet = row_html[:8000]

        user_content = (
            f"页面 URL: {url}\n\n"
            f"之前建议的选择器 '{failed_selector}' 在该行中匹配不到任何元素。\n"
            f"以下是这一行的完整 HTML：\n\n{html_snippet}\n\n"
            f"请仔细分析这行 HTML，告诉我应该点击哪个元素才能进入公司详情页。\n"
            f"返回一个准确的 Playwright locator（如 .company-name、div.cursor-pointer、self 等）。"
        )

        result = await self._call(
            "你是网页自动化专家。用户给你一行的 HTML 片段，你需要找到其中能点击进入详情页的元素，返回它的 Playwright locator。如果整行可点击就返回 'self'。直接返回 JSON。",
            user_content,
            FIX_SELECTOR_SCHEMA,
            max_tokens=512,
        )

        selector = result.get("selector", "") if result else ""
        if selector:
            logger.info(f"[AIExtractor] 选择器修正: '{failed_selector}' → '{selector}' ({result.get('reason', '')})")
        return selector

    # ================================================================
    # 能力2：从商业详情页提取结构化数据
    # ================================================================
    async def extract_business_detail(self, page_text: str) -> Dict[str, Any]:
        """从公司详情页文本中提取完整的商业数据。"""
        if not self._available():
            return {}

        logger.info(f"[AIExtractor] 提取商业详情 ({len(page_text)} 字符)")
        result = await self._call(
            SYSTEM_PROMPT_BUSINESS,
            f"请从以下公司详情页面文本中提取全部信息：\n\n{page_text}",
            BUSINESS_DETAIL_SCHEMA,
            max_tokens=4096,
        )

        if result:
            logger.info(f"[AIExtractor] 商业详情提取成功: {result.get('company_name', 'N/A')}")
        return result

    # ================================================================
    # 能力3：从海关详情页提取结构化数据
    # ================================================================
    async def extract_customs_detail(self, page_text: str) -> Dict[str, Any]:
        """从海关采购商详情页文本中提取数据。"""
        if not self._available():
            return {}

        logger.info(f"[AIExtractor] 提取海关详情 ({len(page_text)} 字符)")
        result = await self._call(
            SYSTEM_PROMPT_CUSTOMS,
            f"请从以下海关数据页面文本中提取采购商详细信息：\n\n{page_text}",
            CUSTOMS_DETAIL_SCHEMA,
            max_tokens=2048,
        )

        if result:
            logger.info(f"[AIExtractor] 海关详情提取成功: {result.get('company_name', 'N/A')}")
        return result
