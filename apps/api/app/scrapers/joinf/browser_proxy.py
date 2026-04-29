"""
Joinf 浏览器代理 — 通过 page.evaluate(fetch()) 调 API。

核心思路：
- 每次搜索时启动浏览器，用 storage-state 加载已有 session
- 通过浏览器的 fetch() 调 Joinf API，浏览器自动管理 cookies
- 如果 session 过期（401 或跳转登录页），尝试自动登录
- 搜索完成后关闭浏览器，保存更新后的 storage-state
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.scrapers.joinf.config import JoinfScraperConfig
from app.scrapers.joinf.models import JoinfRawRow, JoinfScrapeBatch
from app.scrapers.joinf.storage import dump_batch
from app.services.ai_extractor import AIExtractor
from app.scrapers.joinf.service import is_cancelled, clear_cancel

logger = logging.getLogger("joinf_browser_proxy")


class JoinfBrowserProxy:
    """通过浏览器代理调 Joinf API 的客户端"""

    def __init__(self, config: Optional[JoinfScraperConfig] = None, ai_config: Optional[Dict] = None):
        self.config = config or JoinfScraperConfig()
        self.ai: Optional[AIExtractor] = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._login_user_id: Optional[int] = self.config.login_user_id

        if ai_config and ai_config.get("api_key"):
            try:
                self.ai = AIExtractor(
                    api_key=ai_config["api_key"],
                    base_url=ai_config.get("base_url", "https://api.siliconflow.cn/v1"),
                    model=ai_config.get("model", "Qwen/Qwen3-8B"),
                )
                logger.info(f"[BrowserProxy] AIExtractor 已初始化: model={self.ai.model}")
            except Exception as e:
                logger.warning(f"[BrowserProxy] AIExtractor 初始化失败: {e}")

    async def search_business(
        self,
        keyword: str,
        country: Optional[str] = None,
        max_pages: int = 5,
        page_size: int = 20,
        job_id: int = 0,
        on_item_ready: Optional[callable] = None,
        min_score: int = 0,
    ) -> Path:
        """通过浏览器代理调 Joinf API 搜索商业数据"""
        from playwright.async_api import async_playwright

        self.config.ensure_dirs()

        # Step 1: 启动浏览器 + 加载 storage-state
        logger.info("[BrowserProxy] 启动浏览器...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )

        storage_state = str(self.config.storage_state_path) if self.config.storage_state_path.exists() else None
        self._context = await self._browser.new_context(storage_state=storage_state)
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.config.timeout_ms)

        try:
            # Step 2: 导航到数据页面
            await self._page.goto("https://data.joinf.com/searchResult")
            await self._page.wait_for_timeout(3000)

            # Step 3: 检查是否 session 过期（被重定向到登录页）
            current_url = self._page.url
            if "login" in current_url or ("cloud.joinf.com" in current_url and "data.joinf.com" not in current_url):
                logger.info("[BrowserProxy] Session 过期，尝试自动登录...")
                logged_in = await self._try_auto_login()
                if not logged_in:
                    raise RuntimeError(
                        "Joinf 浏览器登录失败（可能有验证码）。\n"
                        "请在前端重新点击「验证登录」"
                    )

            # 提取 loginUserId
            self._extract_login_user_id()
            user_id = self._login_user_id or 0
            logger.info(f"[BrowserProxy] 浏览器就绪: loginUserId={user_id}")

            # Step 4: 用 fetch 调一次 API 验证 session
            test_result = await self._fetch_via_browser(
                self._build_search_payload(keyword, user_id, 1, 1, country)
            )
            if test_result and isinstance(test_result, dict) and test_result.get("code") == 401:
                logger.warning("[BrowserProxy] 初始 fetch 返回 401，尝试刷新...")
                # 刷新页面重试
                await self._page.goto("https://data.joinf.com/searchResult")
                await self._page.wait_for_timeout(3000)
                current_url = self._page.url
                if "login" in current_url or "cloud.joinf.com" in current_url:
                    logged_in = await self._try_auto_login()
                    if not logged_in:
                        raise RuntimeError("Joinf session 过期且无法自动恢复，请重新验证登录")

            # Step 5: 分页搜索
            batch = JoinfScrapeBatch(source_type="business", keyword=keyword, country=country)
            all_api_items: List[Dict] = []

            for page_num in range(1, max_pages + 1):
                if job_id and is_cancelled(job_id):
                    logger.info(f"[BrowserProxy] Job {job_id} 已取消")
                    break

                payload = self._build_search_payload(keyword, user_id, page_num, page_size, country)

                try:
                    result = await self._fetch_via_browser(payload)
                except Exception as e:
                    logger.error(f"[BrowserProxy] fetch 异常 (page={page_num}): {e}")
                    break

                if result is None:
                    logger.error(f"[BrowserProxy] fetch 返回 None")
                    break

                if isinstance(result, dict) and result.get("code") == 401:
                    logger.warning(f"[BrowserProxy] 401 (page={page_num})，session 过期")
                    raise RuntimeError("Joinf session 过期且无法恢复，请重新验证登录")

                api_items = self._extract_items(result)
                if not api_items:
                    logger.info(f"[BrowserProxy] 第 {page_num} 页无结果")
                    if page_num == 1:
                        debug_path = self.config.raw_output_dir / "browser_proxy_debug.json"
                        self.config.raw_output_dir.mkdir(parents=True, exist_ok=True)
                        debug_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                        # ★ 额外保存前500字符的原始响应结构，方便排查解析问题
                        logger.info(f"[BrowserProxy] 第1页原始响应 (前500字): {json.dumps(result, ensure_ascii=False)[:500]}")
                    break

                total = self._extract_total(result)
                logger.info(f"[BrowserProxy] 第 {page_num} 页: {len(api_items)} 条 (API总数={total}, 请求pageSize={page_size})")
                all_api_items.extend(api_items)

                if total and page_num * page_size >= total:
                    logger.info(f"[BrowserProxy] 全部获取 (total={total})")
                    break

            logger.info(f"[BrowserProxy] 共 {len(all_api_items)} 条原始结果")

            # Step 6: 逐条处理（AI 评估 + 联系人 + 回调），流式输出
            processed_items: List[Dict] = []
            for idx, item in enumerate(all_api_items):
                if job_id and is_cancelled(job_id):
                    break

                # Step 6a: AI 评估
                if self.ai and self.ai._available():
                    try:
                        eval_text = self._build_evaluation_text(item)
                        website_url = self._extract_website(item)
                        website_text = ""
                        if website_url:
                            if job_id and is_cancelled(job_id):
                                break
                            website_text = await self._fetch_website_text(website_url)
                        # AI 调用前再次检查取消
                        if job_id and is_cancelled(job_id):
                            break
                        # ★ 加超时：AI 评估最多等 45 秒，避免卡住无法取消
                        evaluation = await asyncio.wait_for(
                            self.ai.evaluate_company(
                                row_text=eval_text, my_product=keyword,
                                source_type="business", website_text=website_text,
                            ),
                            timeout=45.0,
                        )
                        if evaluation:
                            item["_ai_evaluation"] = evaluation
                            score = evaluation.get("match_score", 0)
                            ctype = evaluation.get("customer_type", "unknown")
                            logger.info(
                                f"[BrowserProxy] 评估 {idx+1}/{len(all_api_items)}: "
                                f"{evaluation.get('company_name', 'N/A')} → 匹配度={score} 类型={ctype}"
                            )
                            # ★ 可配置的评分阈值过滤（min_score > 0 时生效）
                            if min_score > 0 and score > 0 and score < min_score:
                                logger.info(f"[BrowserProxy] 跳过低分项 (score={score} < min_score={min_score})")
                                continue
                    except asyncio.TimeoutError:
                        logger.warning(f"[BrowserProxy] AI 评估超时 (index={idx})，跳过")
                    except asyncio.CancelledError:
                        logger.info(f"[BrowserProxy] AI 评估被取消 (index={idx})")
                        break
                    except Exception as e:
                        logger.warning(f"[BrowserProxy] AI 评估异常 (index={idx}): {e}")

                # Step 6b: 获取联系人详情（取消检查）
                if job_id and is_cancelled(job_id):
                    break
                bvd_id = item.get("id")
                if bvd_id and user_id and self._page and not self._page.is_closed():
                    try:
                        detail = await asyncio.wait_for(
                            self._fetch_company_contacts(bvd_id, user_id),
                            timeout=15.0,
                        )
                        if detail.get("contact_list"):
                            item["_contact_detail"] = detail["contact_list"]
                        if detail.get("sns_detail"):
                            item["_sns_detail"] = detail["sns_detail"]
                    except asyncio.TimeoutError:
                        logger.warning(f"[BrowserProxy] 获取联系人超时 ({bvd_id})，跳过")
                    except Exception as e:
                        logger.warning(f"[BrowserProxy] 获取联系人失败 ({bvd_id}): {e}")

                # Step 6c: 转换并保存到 batch
                raw_row = self._api_item_to_raw_row(item, len(processed_items))
                batch.items.append(raw_row)
                processed_items.append(item)

                # Step 6d: 流式回调 — 通知外部已有一条结果可用
                if on_item_ready:
                    try:
                        await on_item_ready(raw_row)
                    except Exception as e:
                        logger.warning(f"[BrowserProxy] on_item_ready 回调失败: {e}")

            logger.info(f"[BrowserProxy] 处理完成: {len(processed_items)}/{len(all_api_items)} 条通过")

            if job_id:
                clear_cancel(job_id)

            return dump_batch(batch, self.config.raw_output_dir)

        finally:
            # 保存 storage-state 并关闭浏览器
            try:
                if self._context:
                    await self._context.storage_state(path=str(self.config.storage_state_path))
            except Exception:
                pass
            try:
                if self._browser:
                    await self._browser.close()
            except Exception:
                pass
            try:
                if self._playwright:
                    await self._playwright.stop()
            except Exception:
                pass

    async def search_customs(
        self,
        keyword: str,
        country: Optional[str] = None,
        max_pages: int = 5,
        page_size: int = 20,
        job_id: int = 0,
        on_item_ready: Optional[callable] = None,
    ) -> Path:
        """通过浏览器代理调 Joinf 海关数据 API"""
        from playwright.async_api import async_playwright

        self.config.ensure_dirs()

        # Step 1: 启动浏览器 + 加载 storage-state
        logger.info("[BrowserProxy-Customs] 启动浏览器...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )

        storage_state = str(self.config.storage_state_path) if self.config.storage_state_path.exists() else None
        self._context = await self._browser.new_context(storage_state=storage_state)
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.config.timeout_ms)

        try:
            # Step 2: 导航到海关数据页面
            await self._page.goto("https://data.joinf.com/customsData")
            await self._page.wait_for_timeout(3000)

            # Step 3: 检查 session
            current_url = self._page.url
            if "login" in current_url or ("cloud.joinf.com" in current_url and "data.joinf.com" not in current_url):
                logger.info("[BrowserProxy-Customs] Session 过期，尝试自动登录...")
                logged_in = await self._try_auto_login()
                if not logged_in:
                    raise RuntimeError("Joinf 海关数据登录失败，请在前端重新点击「验证登录」")

            # 提取 loginUserId
            self._extract_login_user_id()
            user_id = self._login_user_id or 0
            logger.info(f"[BrowserProxy-Customs] 浏览器就绪: loginUserId={user_id}")

            # Step 4: 分页搜索
            batch = JoinfScrapeBatch(source_type="customs", keyword=keyword, country=country)
            all_api_items: List[Dict] = []

            for page_num in range(1, max_pages + 1):
                if job_id and is_cancelled(job_id):
                    logger.info(f"[BrowserProxy-Customs] Job {job_id} 已取消")
                    break

                payload = self._build_customs_payload(keyword, user_id, page_num, page_size, country)

                try:
                    result = await self._fetch_customs_api(payload)
                except Exception as e:
                    logger.error(f"[BrowserProxy-Customs] fetch 异常 (page={page_num}): {e}")
                    break

                if result is None:
                    logger.error(f"[BrowserProxy-Customs] fetch 返回 None")
                    break

                if isinstance(result, dict) and result.get("code") == 401:
                    raise RuntimeError("Joinf session 过期，请重新验证登录")

                api_items = self._extract_items(result)
                if not api_items:
                    logger.info(f"[BrowserProxy-Customs] 第 {page_num} 页无结果")
                    break

                total = self._extract_total(result)
                logger.info(f"[BrowserProxy-Customs] 第 {page_num} 页: {len(api_items)} 条 (API总数={total})")
                all_api_items.extend(api_items)

                if total and page_num * page_size >= total:
                    logger.info(f"[BrowserProxy-Customs] 全部获取 (total={total})")
                    break

            logger.info(f"[BrowserProxy-Customs] 共 {len(all_api_items)} 条原始结果")

            # Step 5: 逐条转换 + 流式回调
            processed_items: List[Dict] = []
            for idx, item in enumerate(all_api_items):
                if job_id and is_cancelled(job_id):
                    break

                # 转换并保存到 batch
                raw_row = self._customs_item_to_raw_row(item, len(processed_items))
                batch.items.append(raw_row)
                processed_items.append(item)

                # 流式回调
                if on_item_ready:
                    try:
                        await on_item_ready(raw_row)
                    except Exception as e:
                        logger.warning(f"[BrowserProxy-Customs] on_item_ready 异常: {e}")

            logger.info(f"[BrowserProxy-Customs] 处理完成: {len(processed_items)} 条")

            if job_id:
                clear_cancel(job_id)

            return dump_batch(batch, self.config.raw_output_dir)

        finally:
            try:
                if self._context:
                    await self._context.storage_state(path=str(self.config.storage_state_path))
            except Exception:
                pass
            try:
                if self._browser:
                    await self._browser.close()
            except Exception:
                pass
            try:
                if self._playwright:
                    await self._playwright.stop()
            except Exception:
                pass

    async def _try_auto_login(self) -> bool:
        """尝试在浏览器中自动登录"""
        if not self.config.has_credentials():
            return False

        page = self._page
        try:
            await page.goto("https://cloud.joinf.com/login")
            await page.wait_for_timeout(2000)

            # 填写用户名
            for sel in ['input[name="username"]', 'input[type="text"]', '#username']:
                try:
                    loc = page.locator(sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        await loc.first.fill(self.config.username or "")
                        break
                except Exception:
                    continue

            # 填写密码
            for sel in ['input[name="password"]', 'input[type="password"]', '#password']:
                try:
                    loc = page.locator(sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        await loc.first.fill(self.config.password or "")
                        break
                except Exception:
                    continue

            # 点击登录
            for sel in ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("登录")', 'button:has-text("Login")']:
                try:
                    loc = page.locator(sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        await loc.first.click()
                        break
                except Exception:
                    continue

            await page.wait_for_timeout(5000)

            # 检查登录是否成功
            current_url = page.url
            if "login" not in current_url and "cloud.joinf.com" not in current_url:
                await page.goto("https://data.joinf.com/searchResult")
                await page.wait_for_timeout(3000)
                return True

            return False
        except Exception as e:
            logger.warning(f"[BrowserProxy] 自动登录异常: {e}")
            return False

    def _extract_login_user_id(self) -> None:
        """提取 loginUserId"""
        if self._login_user_id:
            return

        # 从 storage-state.json 提取
        if self.config.storage_state_path.exists():
            try:
                data = json.loads(self.config.storage_state_path.read_text(encoding="utf-8"))
                for origin in data.get("origins", []):
                    if "joinf.com" not in origin.get("origin", ""):
                        continue
                    for item in origin.get("localStorage", []):
                        name = item.get("name", "")
                        if re.match(r"^\d{4,10}$", name):
                            self._login_user_id = int(name)
                            return
                        value = item.get("value", "")
                        if value:
                            try:
                                obj = json.loads(value)
                                if isinstance(obj, dict):
                                    for k in ("login_id", "loginUserId", "userId", "id", "uid"):
                                        if obj.get(k):
                                            try:
                                                num = int(obj[k])
                                                if num > 1000:
                                                    self._login_user_id = num
                                                    return
                                            except (ValueError, TypeError):
                                                pass
                            except (json.JSONDecodeError, TypeError):
                                pass
            except Exception as e:
                logger.warning(f"[BrowserProxy] 提取 loginUserId 失败: {e}")

        if not self._login_user_id and self.config.login_user_id:
            self._login_user_id = self.config.login_user_id

    async def _fetch_api(self, url: str, payload: Dict, max_retries: int = 2) -> Optional[Dict]:
        """通用浏览器 fetch — 通过 page.evaluate 调任意 Joinf API，支持重试"""
        import asyncio

        for attempt in range(max_retries + 1):
            page = self._page
            if not page or page.is_closed():
                logger.warning(f"[BrowserProxy] 页面已关闭，无法 fetch: {url}")
                return None

            try:
                payload_json = json.dumps(payload, ensure_ascii=False)

                result = await page.evaluate("""async ([payloadStr, apiUrl]) => {
                    try {
                        const payload = JSON.parse(payloadStr);
                        const resp = await fetch(apiUrl, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json;charset=UTF-8',
                                'Accept': 'application/json, text/plain, */*',
                            },
                            body: JSON.stringify(payload),
                        });
                        if (resp.ok) {
                            return await resp.json();
                        } else {
                            return {code: resp.status, errMsg: `HTTP ${resp.status}`, success: false};
                        }
                    } catch(e) {
                        return {code: -1, errMsg: e.message, success: false};
                    }
                }""", [payload_json, url])

                return result

            except Exception as e:
                err_msg = str(e)
                if attempt < max_retries and ("Connection closed" in err_msg or "disconnected" in err_msg.lower() or "Timeout" in err_msg):
                    wait = (attempt + 1) * 2
                    logger.warning(f"[BrowserProxy] fetch 失败 (attempt={attempt+1}), {wait}s 后重试: {e}")
                    await asyncio.sleep(wait)
                    # 尝试重新导航页面恢复连接
                    if page and not page.is_closed():
                        try:
                            await page.reload()
                            await page.wait_for_timeout(2000)
                        except Exception:
                            pass
                    continue
                else:
                    logger.warning(f"[BrowserProxy] fetch 失败 (attempt={attempt+1}/{max_retries+1}): {e}")
                    return None

        return None

    async def _fetch_via_browser(self, payload: Dict) -> Optional[Dict]:
        """通过浏览器 page.evaluate(fetch()) 调搜索 API"""
        return await self._fetch_api(
            "https://data.joinf.com/api/bs/searchBusiness", payload
        )

    async def _fetch_customs_api(self, payload: Dict) -> Optional[Dict]:
        """通过浏览器调海关数据 API"""
        return await self._fetch_api(
            "https://data.joinf.com/api/cdsc/selectCustomsDataList", payload
        )

    def _build_customs_payload(
        self, keyword: str, user_id: int, page_num: int, page_size: int, country: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构建海关数据搜索请求体"""
        from datetime import datetime
        now = datetime.utcnow()
        # 默认查最近1年
        end_date = now.strftime("%Y%m")
        start_year = now.year - 1
        start_date = f"{start_year}{now.strftime('%m')}"

        return {
            "pageNum": page_num,
            "pageSize": page_size,
            "sortField": "",
            "sortType": "",
            "types": 1,
            "multiKeywords": [keyword],
            "dataType": "1",
            "countField": 0,
            "ioType": 2,       # 进口
            "countType": 1,
            "matchType": 0,
            "startDate": start_date,
            "endDate": end_date,
            "searchType": 0,
            "forwarder": 1,
            "loginUserId": user_id,
        }

    # 海关数据字段映射 — 基于 selectCustomsDataList API 实际返回字段
    _CUSTOMS_FIELD_MAP = {
        "cord": "buyer",            # 采购商 (Consignee)
        "sord": "supplier",        # 供应商 (Shipper)
        "date2": "trade_date",     # 交易日期
        "hsCode": "hs_code",       # HS编码
        "hsDescription": "product_description",  # 产品描述
        "weight": "weight",        # 重量
        "qty": "quantity",         # 数量
        "fobPrice": "amount",      # 金额
        "tradeCount": "frequency", # 交易频次
        "country": "country",      # 进口国
        "countryName": "country_cn",  # 进口国中文名
        "origin": "origin",        # 原产国
        "originName": "origin_cn", # 原产国中文名
    }

    _CUSTOMS_FIELD_LABELS = {
        "buyer": "采购商", "supplier": "供应商",
        "trade_date": "交易日期", "hs_code": "HS编码",
        "product_description": "产品描述",
        "weight": "重量", "quantity": "数量", "amount": "金额",
        "frequency": "交易频次",
        "country": "进口国", "origin": "原产国",
    }

    def _customs_item_to_raw_row(self, item: Dict, index: int) -> JoinfRawRow:
        cells = []
        metadata: Dict[str, Any] = {}

        for api_key, meta_key in self._CUSTOMS_FIELD_MAP.items():
            if api_key in item and item[api_key] is not None:
                value = item[api_key]
                if isinstance(value, (list, dict)):
                    if value:
                        metadata[meta_key] = value
                else:
                    value_str = str(value).strip()
                    if value_str:
                        metadata[meta_key] = value_str

        for meta_key, label in self._CUSTOMS_FIELD_LABELS.items():
            if meta_key in metadata:
                value = metadata[meta_key]
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value[:5])
                if value:
                    cells.append(f"{label}: {value}")

        # 同时放入 detail 供 extract_customs_record 使用
        metadata["detail"] = {k: v for k, v in metadata.items() if k not in ("api_raw", "detail") and not isinstance(v, (list, dict))}

        metadata["api_raw"] = {k: v for k, v in item.items() if not k.startswith("_")}

        return JoinfRawRow(
            source_type="customs",
            page_url="https://data.joinf.com/customsData",
            row_index=index,
            cells=cells,
            metadata=metadata,
        )

    async def _fetch_company_contacts(self, bvd_id: str, user_id: int) -> Dict:
        """获取公司联系人列表 + 社交媒体详情"""
        import asyncio

        sns_data = None
        contact_data = None

        # 检查浏览器是否还活着
        if not self._page or self._page.is_closed():
            logger.warning(f"[BrowserProxy] 跳过联系人获取 (页面已关闭): {bvd_id}")
            return {"sns_detail": None, "contact_list": None}

        # 1) selectSnsByBvdId — 社交媒体详情
        try:
            sns_result = await self._fetch_api(
                "https://data.joinf.com/api/bs/selectSnsByBvdId",
                {"id": bvd_id, "loginUserId": user_id},
            )
            if sns_result and isinstance(sns_result, dict) and sns_result.get("code") == 0:
                sns_data = sns_result.get("data")
        except Exception as e:
            logger.warning(f"[BrowserProxy] selectSnsByBvdId 失败 ({bvd_id}): {e}")

        # 间隔避免被限流
        await asyncio.sleep(0.5)

        # 再次检查浏览器
        if not self._page or self._page.is_closed():
            logger.warning(f"[BrowserProxy] 跳过联系人列表获取 (页面已关闭): {bvd_id}")
            return {"sns_detail": sns_data, "contact_list": None}

        # 2) selectContactBvdIdList — 联系人列表
        try:
            contact_result = await self._fetch_api(
                "https://data.joinf.com/api/bs/selectContactBvdIdList",
                {
                    "pageNum": 1, "pageSize": 100,
                    "dataFromList": [], "markList": [], "isCollection": 0,
                    "keyword": None, "role": None, "startTime": None, "endTime": None,
                    "bvdId": bvd_id, "customerId": None, "jobType": 0,
                    "loginUserId": user_id,
                },
            )
            if contact_result and isinstance(contact_result, dict) and contact_result.get("code") == 0:
                contact_data = contact_result.get("data")
        except Exception as e:
            logger.warning(f"[BrowserProxy] selectContactBvdIdList 失败 ({bvd_id}): {e}")

        return {"sns_detail": sns_data, "contact_list": contact_data}

    def _build_search_payload(
        self, keyword: str, user_id: int, page_num: int, page_size: int, country: Optional[str] = None,
    ) -> Dict[str, Any]:
        countries = []
        if country:
            country_map = {
                "美国": "US", "英国": "GB", "德国": "DE", "法国": "FR",
                "日本": "JP", "韩国": "KR", "澳大利亚": "AU", "加拿大": "CA",
                "印度": "IN", "巴西": "BR", "墨西哥": "MX", "西班牙": "ES",
                "意大利": "IT", "荷兰": "NL", "俄罗斯": "RU",
            }
            if country in country_map:
                countries = [country_map[country]]
            elif len(country.strip()) == 2:
                countries = [country.strip().upper()]
            else:
                countries = [country]

        return {
            "loginUserId": user_id,
            "countries": countries,
            "etlMark": 0, "socialMediaFlag": 0, "labelIds": [], "labelQueryType": 1,
            "pageNum": page_num, "pageSize": page_size, "searchType": 1,
            "keywords": keyword, "multiKeywords": [keyword],
            "sortField": "", "sortType": "", "fullMatch": 1, "seeMore": 0,
            "industries": [], "industriesSession": [], "excludeCountries": ["CHINA"],
        }

    # ================================================================
    # 响应解析
    # ================================================================

    def _extract_items(self, data: Any) -> List[Dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            inner = data.get("data", {})
            if isinstance(inner, dict):
                for key in ("list", "rows", "records", "items", "result", "businessList", "businessListResponses", "pageInfo"):
                    if key in inner and isinstance(inner[key], list):
                        return inner[key]
                    if key in inner and isinstance(inner[key], dict):
                        for sub_key in ("list", "rows", "records", "items", "result"):
                            if sub_key in inner[key] and isinstance(inner[key][sub_key], list):
                                return inner[key][sub_key]
                if isinstance(inner, list):
                    return inner
            elif isinstance(inner, list):
                return inner
            for key in ("list", "rows", "records", "items", "result", "businessList"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    def _extract_total(self, data: Any) -> Optional[int]:
        if not isinstance(data, dict):
            return None
        inner = data.get("data", {})
        if isinstance(inner, dict):
            for key in ("total", "totalCount", "totalElements", "count", "totalRecord", "max"):
                if key in inner:
                    try:
                        return int(inner[key])
                    except (ValueError, TypeError):
                        pass
        for key in ("total", "totalCount", "count", "totalRecord"):
            if key in data:
                try:
                    return int(data[key])
                except (ValueError, TypeError):
                    pass
        return None

    # ================================================================
    # 结果转换
    # ================================================================

    _FIELD_MAP = {
        "companyName": "company_name", "name": "company_name", "nameEn": "company_name",
        "countryName": "country", "countryNameEn": "country", "country": "country",
        "countryEn": "country_en",
        "countryCode": "country_code",
        "website": "website", "websiteUrl": "website", "url": "website", "homePage": "website",
        "industry": "industry", "industryName": "industry", "mainIndustry": "industry",
        "mainBusiness": "main_business",
        "description": "description", "companyDesc": "description", "companyDescription": "description",
        "intro": "description", "fullOverview": "description",
        "emailCount": "email_count", "emailNum": "email_count", "emailSize": "email_count",
        "phone": "phone", "tel": "phone", "telephone": "phone",
        "address": "address", "companyAddr": "address",
        "cityName": "city", "city": "city", "cityNameEn": "city",
        "employeeSize": "employee_size", "employees": "employee_size",
        "foundedYear": "founded_year", "revenue": "revenue",
        "tradeMark": "trademark", "socialMedia": "social_media",
        "snsList": "social_media",
        "websiteLogo": "website_logo",
        "grade": "grade", "star": "star",
        "contactTotal": "contact_total",
        "hasEmail": "has_email", "hasWebsite": "has_website",
    }

    _FIELD_LABELS = {
        "company_name": "公司名称", "country": "国家", "country_code": "国家代码",
        "website": "网站", "industry": "行业", "main_business": "主营业务",
        "description": "简介", "email_count": "邮箱数量", "phone": "电话",
        "address": "地址", "city": "城市", "employee_size": "员工规模",
        "founded_year": "成立年份", "revenue": "营收", "trademark": "商标",
        "social_media": "社交媒体", "website_logo": "公司Logo",
        "grade": "信用评级", "star": "星级", "contact_total": "联系人总数",
    }

    def _api_item_to_raw_row(self, item: Dict, index: int) -> JoinfRawRow:
        cells = []
        metadata: Dict[str, Any] = {}

        for api_key, meta_key in self._FIELD_MAP.items():
            if api_key in item and item[api_key] is not None:
                value = item[api_key]
                if isinstance(value, (list, dict)):
                    if value:
                        metadata[meta_key] = value
                else:
                    value_str = str(value).strip()
                    if value_str:
                        metadata[meta_key] = value_str

        for meta_key, label in self._FIELD_LABELS.items():
            if meta_key in metadata:
                value = metadata[meta_key]
                if isinstance(value, list):
                    if meta_key == "social_media":
                        # 社交媒体：提取平台名+URL，不显示原始 dict
                        parts = []
                        for s in value[:5]:
                            if isinstance(s, dict):
                                url = s.get("snsUrl") or s.get("url") or ""
                                s_type = s.get("type")
                                sm_label = {1: "Facebook", 2: "Twitter", 3: "LinkedIn", 4: "YouTube", 5: "Instagram", 7: "Instagram", 8: "YouTube"}.get(s_type, "社交")
                                if url:
                                    parts.append(f"{sm_label}: {url}")
                            else:
                                parts.append(str(s))
                        value = ", ".join(parts) if parts else ""
                    else:
                        value = ", ".join(str(v) for v in value[:5])
                if value:
                    cells.append(f"{label}: {value}")

        links = []
        if metadata.get("website"):
            url = metadata["website"]
            if not url.startswith("http"):
                url = f"https://{url}"
            links.append({"href": url, "text": metadata.get("company_name", "")})
        metadata["links"] = links

        if "_ai_evaluation" in item:
            metadata["ai_evaluation"] = item["_ai_evaluation"]

        # 联系人详情（从 selectContactBvdIdList 获取）
        if "_contact_detail" in item:
            metadata["contact_detail"] = item["_contact_detail"]

        # 社交媒体详情（从 selectSnsByBvdId 获取）
        if "_sns_detail" in item:
            metadata["sns_detail"] = item["_sns_detail"]

        metadata["api_raw"] = {k: v for k, v in item.items() if not k.startswith("_")}

        return JoinfRawRow(
            source_type="business",
            page_url="https://data.joinf.com/searchResult",
            row_index=index,
            cells=cells,
            metadata=metadata,
        )

    # ================================================================
    # AI 评估
    # ================================================================

    async def _evaluate_items_with_ai(
        self, items: List[Dict], keyword: str, job_id: int = 0,
    ) -> List[Dict]:
        if not self.ai or not self.ai._available():
            return items

        evaluated = []
        for index, item in enumerate(items):
            if job_id and is_cancelled(job_id):
                evaluated.extend(items[index:])
                break

            try:
                eval_text = self._build_evaluation_text(item)
                website_url = self._extract_website(item)
                website_text = ""
                if website_url:
                    website_text = await self._fetch_website_text(website_url)

                evaluation = await self.ai.evaluate_company(
                    row_text=eval_text, my_product=keyword,
                    source_type="business", website_text=website_text,
                )

                if evaluation:
                    item["_ai_evaluation"] = evaluation
                    score = evaluation.get("match_score", 0)
                    ctype = evaluation.get("customer_type", "unknown")
                    logger.info(
                        f"[BrowserProxy] 评估 {index}/{len(items)}: "
                        f"{evaluation.get('company_name', 'N/A')} → 匹配度={score} 类型={ctype}"
                    )
            except Exception as e:
                logger.warning(f"[BrowserProxy] AI 评估异常 (index={index}): {e}")

            evaluated.append(item)

        return evaluated

    def _build_evaluation_text(self, item: Dict) -> str:
        parts = []
        for key, value in item.items():
            if key.startswith("_") or value is None:
                continue
            if isinstance(value, str) and value.strip():
                parts.append(f"{key}: {value}")
            elif isinstance(value, (int, float)):
                parts.append(f"{key}: {value}")
            elif isinstance(value, list) and value:
                parts.append(f"{key}: {', '.join(str(v) for v in value[:10])}")
            elif isinstance(value, dict) and value:
                for k2, v2 in value.items():
                    if v2 and isinstance(v2, (str, int, float)):
                        parts.append(f"{key}.{k2}: {v2}")
        return "\n".join(parts)

    def _extract_website(self, item: Dict) -> Optional[str]:
        for key in ("website", "websiteUrl", "url", "homePage"):
            url = item.get(key)
            if url and isinstance(url, str) and url.strip():
                url = url.strip()
                if not url.startswith("http"):
                    url = f"https://{url}"
                skip = ["joinf.com", "linkedin.com", "facebook.com", "google.com"]
                if any(s in url.lower() for s in skip):
                    continue
                return url
        return None

    async def _fetch_website_text(self, url: str) -> str:
        import httpx as _httpx

        if not url.startswith("http"):
            url = f"https://{url}"

        for proto_url in [url, url.replace("https://", "http://")]:
            try:
                async with _httpx.AsyncClient(
                    timeout=_httpx.Timeout(15.0, connect=5.0),
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
                    verify=False,
                ) as client:
                    resp = await client.get(proto_url)
                    resp.raise_for_status()
                    html = resp.text
                    break
            except Exception:
                continue
        else:
            return ""

        import re as _re
        import html as html_module
        text = _re.sub(r'<script[^>]*>.*?</script>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
        text = _re.sub(r'<style[^>]*>.*?</style>', '', text, flags=_re.DOTALL | _re.IGNORECASE)
        text = _re.sub(r'<[^>]+>', ' ', text)
        text = html_module.unescape(text)
        return _re.sub(r'\s+', ' ', text).strip()[:8000]
