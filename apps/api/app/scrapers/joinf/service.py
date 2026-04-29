from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.scrapers.joinf.browser import JoinfBrowserSession
from app.scrapers.joinf.config import JoinfScraperConfig
from app.scrapers.joinf.models import JoinfRawRow, JoinfScrapeBatch
from app.scrapers.joinf.selectors import JoinfSelectors
from app.scrapers.joinf.storage import dump_batch
from app.services.ai_extractor import AIExtractor

MAX_PAGES = 3
FREIGHT_KEYWORDS = ["货运", "物流", "freight", "logistics", "shipping", "cargo", "forwarding", "货代"]

# 全局取消信号：存被取消的 job_id，scraper 循环中定期检查
_cancelled_jobs: set[int] = set()
# 全局运行中 job 集合：用于 Ctrl+C 时快速取消
_running_job_ids: set[int] = set()


def request_cancel(job_id: int) -> None:
    """标记 job 为取消状态，正在运行的 scraper 会检测到"""
    _cancelled_jobs.add(job_id)


def is_cancelled(job_id: int) -> bool:
    """检查 job 是否已被取消"""
    return job_id in _cancelled_jobs


def clear_cancel(job_id: int) -> None:
    """清理取消标记"""
    _cancelled_jobs.discard(job_id)
    _running_job_ids.discard(job_id)


def mark_job_running(job_id: int) -> None:
    """标记 job 正在运行（用于 Ctrl+C 时快速取消）"""
    if job_id:
        _running_job_ids.add(job_id)


def cancel_all_jobs() -> None:
    """取消所有运行中的 job — Ctrl+C 或服务关闭时调用"""
    if _running_job_ids:
        print(f"[Joinf] 取消所有运行中的 job: {_running_job_ids}")
        _cancelled_jobs.update(_running_job_ids)
        _running_job_ids.clear()


class JoinfScraperService:
    def __init__(self, config: Optional[JoinfScraperConfig] = None, ai_config: Optional[Dict] = None):
        self.config = config or JoinfScraperConfig()
        self._ai_config = ai_config
        self.ai: Optional[AIExtractor] = None
        if ai_config and ai_config.get("api_key"):
            try:
                self.ai = AIExtractor(
                    api_key=ai_config["api_key"],
                    base_url=ai_config.get("base_url", "https://api.siliconflow.cn/v1"),
                    model=ai_config.get("model", "Qwen/Qwen3-8B"),
                )
                print(f"=== [DEBUG] AIExtractor initialized: base_url={self.ai.base_url}, model={self.ai.model}")
            except Exception as e:
                logging.getLogger("joinf_service").warning(f"[JoinfScraperService] AIExtractor 初始化失败: {e}")
                print(f"=== [DEBUG] AIExtractor init FAILED: {e}")
        else:
            print(f"=== [DEBUG] No AI config or no api_key, AI will NOT be available")

    async def ensure_login_session(
        self,
        allow_manual: bool = True,
        interactive_manual: bool = True,
        manual_timeout_seconds: int = 180,
    ) -> Path:
        async with JoinfBrowserSession(self.config) as session:
            assert session.page is not None
            await session.page.goto(self.config.login_url)
            await session.page.screenshot(path=str(self.config.screenshot_dir / "login-page.png"), full_page=True)

            logged_in = await self._is_logged_in(session.page)
            if not logged_in and self.config.has_credentials():
                logged_in = await self._try_auto_login(session.page)

            if not logged_in and allow_manual:
                logged_in = await self._wait_for_manual_login(session.page, manual_timeout_seconds)

            if not logged_in:
                raise RuntimeError("Joinf 登录失败：超时未检测到登录成功，请重试并在弹出的浏览器中完成登录（含验证码）")

            # Navigate to the data page to capture full session state
            await session.page.goto(self.config.base_url)
            await session.page.wait_for_timeout(2000)
            # Save one more time to capture cookies from data.joinf.com
            await session.page.screenshot(path=str(self.config.screenshot_dir / "login-success.png"), full_page=True)

            # ★ 提取 loginUserId 并保存认证缓存
            await self._save_auth_cache_from_page(session.page)

        return self.config.storage_state_path

    async def _wait_for_manual_login(self, page, timeout_seconds: int) -> bool:
        for _ in range(max(1, timeout_seconds)):
            if await self._is_logged_in(page):
                return True
            await page.wait_for_timeout(1000)
        return await self._is_logged_in(page)

    async def _save_auth_cache_from_page(self, page) -> None:
        """从浏览器页面提取 loginUserId 和 cookies，保存到 auth-cache.json 供 API 客户端使用
        
        注意：page.evaluate() 只能访问当前页面的 localStorage，
        而 Joinf 的 loginUserId 存在 edmsys.joinf.com 的 localStorage 里（key 就是 userId 数字），
        所以还需要从 storage-state.json 中提取（它包含所有域的 localStorage）。
        """
        import json as json_mod
        import re as re_mod

        user_id = None

        # 策略1：从 config.login_user_id 获取（.env 或环境变量已配置）
        if self.config.login_user_id:
            user_id = str(self.config.login_user_id)
            print(f"[Joinf] 使用预配置的 loginUserId: {user_id}")

        # 策略2：从 storage-state.json 的 localStorage 中提取（包含所有域）
        if not user_id and self.config.storage_state_path.exists():
            try:
                storage_data = json_mod.loads(self.config.storage_state_path.read_text(encoding="utf-8"))
                for origin in storage_data.get("origins", []):
                    origin_str = origin.get("origin", "")
                    if "joinf.com" not in origin_str:
                        continue
                    for item in origin.get("localStorage", []):
                        name = item.get("name", "")
                        # ★ key 本身是数字（Joinf 实际方式："404508": "show"）
                        if re_mod.match(r"^\d{4,10}$", name):
                            user_id = name
                            print(f"[Joinf] 从 storage-state.json 提取 loginUserId: {user_id} (origin={origin_str})")
                            break
                        # value 中包含 login_id 等
                        value = item.get("value", "")
                        if value and not user_id:
                            try:
                                obj = json_mod.loads(value)
                                if isinstance(obj, dict):
                                    for k in ("login_id", "loginUserId", "userId", "id", "uid"):
                                        if obj.get(k):
                                            try:
                                                num = int(obj[k])
                                                if num > 1000:
                                                    user_id = str(num)
                                                    break
                                            except (ValueError, TypeError):
                                                pass
                            except (json_mod.JSONDecodeError, TypeError):
                                pass
                    if user_id:
                        break
            except Exception as e:
                print(f"[Joinf] 从 storage-state.json 提取 loginUserId 失败: {e}")

        # 策略3：从当前页面 JS 提取（可能失败，因为跨域 localStorage 不可访问）
        if not user_id:
            try:
                user_id = await page.evaluate("""() => {
                    // localStorage KEY 就是 userId
                    const keys = Object.keys(localStorage);
                    for (const key of keys) {
                        if (/^\\d{4,10}$/.test(key)) return key;
                    }
                    // localStorage VALUE
                    for (const key of keys) {
                        const val = localStorage.getItem(key);
                        if (val && /^\\d{4,10}$/.test(val)) return val;
                        try {
                            const obj = JSON.parse(val);
                            if (typeof obj === 'object' && obj !== null) {
                                for (const idKey of ['login_id', 'loginUserId', 'userId', 'id', 'uid', 'user_id']) {
                                    if (obj[idKey] != null) {
                                        const v = parseInt(String(obj[idKey]), 10);
                                        if (v > 1000) return String(v);
                                    }
                                }
                            }
                        } catch(e) {}
                    }
                    // cookie
                    const cookiePairs = document.cookie.split(';');
                    for (const pair of cookiePairs) {
                        const [k, ...rest] = pair.split('=');
                        const v = rest.join('=').trim();
                        const kLower = k.trim().toLowerCase();
                        if (['userid', 'loginuserid', 'uid', 'user_id', 'id'].includes(kLower)) {
                            if (/^\\d{4,10}$/.test(v)) return v;
                        }
                    }
                    return null;
                }""")
            except Exception as e:
                print(f"[Joinf] 从页面 JS 提取 loginUserId 失败: {e}")

        if user_id:
            try:
                user_id_int = int(user_id)
                # 提取 cookies
                cookies = {}
                storage_data = json_mod.loads(self.config.storage_state_path.read_text(encoding="utf-8")) if self.config.storage_state_path.exists() else {}
                for cookie in storage_data.get("cookies", []):
                    domain = cookie.get("domain", "")
                    if "joinf.com" in domain:
                        name = cookie.get("name", "")
                        value = cookie.get("value", "")
                        if name:
                            cookies[name] = value

                self.config.save_auth_cache(user_id_int, cookies)
                print(f"[Joinf] 已保存认证缓存: loginUserId={user_id_int}, cookies={len(cookies)} 个")
            except Exception as e:
                print(f"[Joinf] 保存认证缓存失败: {e}")
        else:
            print(f"[Joinf] 未能从页面提取 loginUserId，API 客户端可能需要手动配置")

    async def scrape_business_data(self, keyword: str, country: Optional[str] = None, job_id: int = 0) -> Path:
        return await self._scrape_source("business", keyword, country, job_id=job_id)

    async def scrape_customs_data(self, keyword: str, country: Optional[str] = None, job_id: int = 0) -> Path:
        return await self._scrape_source("customs", keyword, country, job_id=job_id)

    async def scrape_from_manual_navigation(
        self,
        source_type: str,
        keyword: str,
        country: Optional[str] = None,
        wait_seconds: int = 180,
    ) -> Path:
        batch = JoinfScrapeBatch(source_type=source_type, keyword=keyword, country=country)

        async with JoinfBrowserSession(self.config) as session:
            assert session.page is not None
            await session.page.goto(self.config.base_url)

            if not await self._is_logged_in(session.page):
                if self.config.has_credentials() and await self._try_auto_login(session.page):
                    await session.page.goto(self.config.base_url)
                else:
                    raise RuntimeError('Joinf 当前未登录，请先在前端执行"验证登录"并确保登录成功')

            print("Joinf 已进入人工抓取模式：请手动打开目标结果页，系统将自动识别表格并开始抓取。")
            table_ready = await self._wait_for_table_rows(session.page, wait_seconds=wait_seconds)
            if not table_ready:
                raise RuntimeError("人工抓取超时：未检测到结果表格，请重试并先手动进入结果页")

            snapshot_path = self.config.screenshot_dir / f"{source_type}-manual-results.png"
            await session.page.screenshot(path=str(snapshot_path), full_page=True)
            batch.page_snapshots.append(str(snapshot_path))

            # ★ 用 AI 分析页面结构 + AI 驱动提取（和自动抓取一致）
            page_structure = await self._analyze_page_with_ai(session.page, source_type)
            if page_structure and page_structure.get("row_selector"):
                page_rows = await self._extract_rows_ai(session.page, source_type, page_structure)
                print(f"[Joinf] 人工抓取: 提取到 {len(page_rows)} 行")
                # ★ AI 客户评估
                if self.ai and self.ai._available():
                    page_rows = await self._enrich_rows_with_detail_ai(
                        session.page, page_rows, page_structure, keyword=keyword
                    )
                batch.items.extend(page_rows)
            else:
                print(f"[Joinf] 人工抓取: 未能分析出页面结构，无数据提取")

        return dump_batch(batch, self.config.raw_output_dir)

    async def _scrape_source(self, source_type: str, keyword: str, country: Optional[str], job_id: int = 0) -> Path:
        batch = JoinfScrapeBatch(source_type=source_type, keyword=keyword, country=country)
        
        # ★ 标记 job 正在运行（用于 Ctrl+C 时快速取消）
        mark_job_running(job_id)

        try:
            async with JoinfBrowserSession(self.config) as session:
                assert session.page is not None
                page = session.page

                # Step 1: 进入首页
                print(f"[Joinf] Step 1: 导航到 {self.config.base_url}")
                await page.goto(self.config.base_url)
                await page.wait_for_timeout(2000)

                # Step 2: 检查登录状态
                print(f"[Joinf] Step 2: 检查登录状态, 当前 URL={page.url}")
                if not await self._is_logged_in(page):
                    if self.config.has_credentials():
                        print(f"[Joinf] Step 2a: 尝试自动登录")
                        await page.goto(self.config.login_url)
                        await page.wait_for_timeout(2000)
                        if await self._try_auto_login(page):
                            print(f"[Joinf] Step 2a: 自动登录成功")
                            await page.goto(self.config.base_url)
                            await page.wait_for_timeout(2000)
                        else:
                            raise RuntimeError('Joinf 自动登录失败，请先在前端点击「验证登录」')
                    else:
                        raise RuntimeError('Joinf 当前未登录，请先在前端执行「验证登录」并确保登录成功')

                # Step 3: 导航到数据源页面（商业/海关）
                print(f"[Joinf] Step 3: 导航到 {source_type} 数据页面")
                await self._navigate_to_source(page, source_type)
                await page.wait_for_timeout(2000)

                # Step 4: 在搜索框输入关键词并搜索
                print(f"[Joinf] Step 4: 输入关键词 '{keyword}' 并搜索")
                await self._do_search(page, keyword, country)
                await page.wait_for_timeout(5000)

                # Step 5: 保存搜索结果页 HTML（供 AI 分析），截图可选
                await self._dump_page_debug(page, f"{source_type}-step4-after-search")

                # Step 6: ★ 让 AI 分析页面结构，获取行选择器和详情按钮选择器
                print(f"[Joinf] Step 6: AI 分析页面结构")
                page_structure = await self._analyze_page_with_ai(page, source_type)

                if not page_structure or not page_structure.get("row_selector"):
                    print(f"[Joinf] AI 未能分析出页面结构，抓取终止")
                    print(f"[Joinf] 提示：请确认 AI 配置正确且 API Key 有效")
                    return dump_batch(batch, self.config.raw_output_dir)
                
                # Step 7: 用 AI 返回的选择器逐页提取 + AI 客户评估
                print(f"[Joinf] Step 7: 开始提取数据 + AI 客户评估")
                for page_num in range(MAX_PAGES):
                    # ★ 取消检查
                    if job_id and is_cancelled(job_id):
                        print(f"[Joinf] Job {job_id} 已取消，停止抓取")
                        break

                    page_rows = await self._extract_rows_ai(page, source_type, page_structure)
                    print(f"[Joinf] Page {page_num + 1}: 提取到 {len(page_rows)} 行")
                    if not page_rows:
                        break

                    # ★ 取消检查（AI 评估循环很长，需要中途检查）
                    if job_id and is_cancelled(job_id):
                        print(f"[Joinf] Job {job_id} 已取消，跳过 AI 评估")
                        batch.items.extend(page_rows)
                        break

                    # ★ AI 评估每家公司是否是潜在客户（不再点详情页）
                    page_rows = await self._enrich_rows_with_detail_ai(
                        page, page_rows, page_structure, keyword=keyword, job_id=job_id
                    )

                    batch.items.extend(page_rows)

                    if page_num < MAX_PAGES - 1:
                        next_sel = page_structure.get("next_page_selector")
                        has_next = False
                        if next_sel:
                            has_next = await self._try_click_first(page, [next_sel], wait_ms=2000)
                        if not has_next and page_structure.get("has_pagination"):
                            # AI 说有分页但没给选择器，尝试通用翻页
                            has_next = await self._try_click_first(
                                page, JoinfSelectors.pagination_next_button_candidates, wait_ms=2000
                            )
                        if not has_next:
                            print(f"[Joinf] 没有更多页了")
                            break
                        await page.wait_for_timeout(1500)

        except Exception as e:
            # ★ 浏览器断开等异常时，保存已抓取的中间结果而不是直接丢弃
            if batch.items:
                print(f"[Joinf] 抓取异常 ({e})，但已有 {len(batch.items)} 条数据，保存中间结果")
                return dump_batch(batch, self.config.raw_output_dir)
            raise

        return dump_batch(batch, self.config.raw_output_dir)

    async def _navigate_to_source(self, page, source_type: str) -> None:
        """导航到商业数据或海关数据页面，尝试多种方式"""
        # 方式1：直接点击导航菜单
        nav_selectors = (
            JoinfSelectors.global_buyers_direct_nav_candidates
            + JoinfSelectors.data_marketing_nav_candidates
        )
        for selector in nav_selectors:
            try:
                loc = page.locator(selector)
                if await loc.count() > 0:
                    first = loc.first
                    if await first.is_visible():
                        print(f"[Joinf] _navigate: 点击导航 '{selector}'")
                        await first.click()
                        await page.wait_for_timeout(1500)
                        break
            except Exception:
                continue
        else:
            print(f"[Joinf] _navigate: 未找到导航菜单，尝试侧边栏")

        # 切换到对应的数据标签（商业/海关）
        tab_selectors = (
            JoinfSelectors.business_data_nav_candidates
            if source_type == "business"
            else JoinfSelectors.customs_data_nav_candidates
        )
        for selector in tab_selectors:
            try:
                loc = page.locator(selector)
                if await loc.count() > 0:
                    first = loc.first
                    if await first.is_visible():
                        print(f"[Joinf] _navigate: 切换到 {source_type} 标签 '{selector}'")
                        await first.click()
                        await page.wait_for_timeout(1500)
                        return
            except Exception:
                continue

        print(f"[Joinf] _navigate: 未找到 {source_type} 标签切换按钮，可能已在正确页面")

    async def _do_search(self, page, keyword: str, country: Optional[str]) -> None:
        """在当前页面找到搜索框，输入关键词并搜索"""
        # 尝试各种搜索输入框选择器
        all_search_selectors = [
            # 优先精确匹配
            "input[placeholder*='关键词']",
            "input[placeholder*='产品']",
            "input[placeholder*='搜索']",
            "input[placeholder*='请输入']",
            "input[placeholder*='查询']",
            # Element UI 下拉框
            ".el-input__inner[type='text']",
            ".el-input input[type='text']",
            # 通用
            "input[type='text']",
            "input:not([type])",
        ]

        search_input = None
        for selector in all_search_selectors:
            try:
                loc = page.locator(selector)
                count = await loc.count()
                if count > 0:
                    # 找第一个可见的
                    for i in range(count):
                        candidate = loc.nth(i)
                        if await candidate.is_visible():
                            search_input = candidate
                            print(f"[Joinf] _do_search: 找到搜索框 '{selector}' (index={i})")
                            break
                    if search_input:
                        break
            except Exception:
                continue

        if search_input is None:
            print(f"[Joinf] _do_search: 未找到搜索框，尝试页面内所有 input")
            await self._dump_page_debug(page, "no-search-input")
            # 最后手段：找页面上任何可见的 text input
            all_inputs = page.locator("input:visible")
            count = await all_inputs.count()
            print(f"[Joinf] _do_search: 页面上有 {count} 个可见 input")
            if count > 0:
                search_input = all_inputs.first
            else:
                print(f"[Joinf] _do_search: 没有任何可见 input，无法搜索")
                return

        # 填入关键词
        try:
            await search_input.click()
            await page.wait_for_timeout(300)
            await search_input.fill("")
            await search_input.fill(keyword)
            print(f"[Joinf] _do_search: 已填入关键词 '{keyword}'")
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"[Joinf] _do_search: fill 失败: {e}，尝试 type")
            try:
                await search_input.click()
                await page.keyboard.press("ControlOrMeta+A")
                await page.keyboard.type(keyword)
            except Exception as e2:
                print(f"[Joinf] _do_search: type 也失败: {e2}")

        # 尝试按 Enter 或点击搜索按钮
        try:
            await search_input.press("Enter")
            print(f"[Joinf] _do_search: 按 Enter 搜索")
        except Exception:
            pass

        # 尝试点击搜索/查询按钮
        for btn_selector in [
            "button:has-text('搜索')", "button:has-text('查询')", "button:has-text('确定')",
            "button:has-text('搜 索')", "[class*='search'] button", "[class*='btn-search']",
        ]:
            try:
                loc = page.locator(btn_selector)
                if await loc.count() > 0:
                    await loc.first.click()
                    print(f"[Joinf] _do_search: 点击搜索按钮 '{btn_selector}'")
                    break
            except Exception:
                continue

    # ================================================================
    # AI 驱动的页面分析和提取方法（替代旧的选择器猜谜）
    # ================================================================

    async def _analyze_page_with_ai(self, page, source_type: str) -> Dict[str, Any]:
        """让 AI 分析结果列表页的 DOM 结构，返回选择器信息。
        
        降级策略：AI 分析失败或选择器不匹配时，扫描页面自动推断。
        """
        print(f"=== [DEBUG] _analyze_page_with_ai called, self.ai={'SET' if self.ai else 'NONE'}")

        # 策略1：AI 分析
        if self.ai and self.ai._available():
            try:
                html_content = await page.content()
                structure = await self.ai.analyze_results_page(
                    page_html=html_content,
                    url=page.url,
                    source_type=source_type,
                )
                if structure and structure.get("row_selector"):
                    row_sel = structure["row_selector"]
                    # ★ 关键：验证 AI 返回的选择器在页面上能否匹配到元素
                    try:
                        actual_count = await page.locator(row_sel).count()
                    except Exception:
                        actual_count = 0

                    if actual_count > 0:
                        # ★ 行数合理性检查：如果 AI 返回的选择器只匹配到极少数行，可能选错了
                        if actual_count < 5:
                            print(f"[Joinf] AI 选择器只匹配 {actual_count} 行（太少），尝试智能推断获取更多行")
                        else:
                            print(f"[Joinf] AI 页面分析成功（验证匹配 {actual_count} 行）:")
                            print(f"       行选择器: {row_sel}")
                            print(f"       详情按钮: {structure.get('detail_button_selector')}")
                            structure["row_count"] = actual_count
                            return structure
                    else:
                        print(f"[Joinf] AI 返回的选择器 '{row_sel}' 在页面上匹配 0 行，AI 可能猜错了，降级到智能推断")
                else:
                    print(f"[Joinf] AI 返回空结构，尝试智能推断")
            except Exception as e:
                print(f"[Joinf] AI 页面分析异常: {e}，尝试智能推断")

        # 策略2：智能推断 — 扫描页面常见表格结构
        structure = await self._infer_page_structure(page, source_type)
        if structure and structure.get("row_selector"):
            print(f"[Joinf] 智能推断页面结构成功:")
            print(f"       行选择器: {structure.get('row_selector')}")
            print(f"       行数量:   {structure.get('row_count')}")
            return structure

        print(f"[Joinf] 所有分析策略均失败")
        return {}

    async def _infer_page_structure(self, page, source_type: str) -> Dict[str, Any]:
        """自动检测页面中的重复列表模式 — 不依赖任何硬编码选择器。
        
        核心思路：搜索结果必定是列表，扫描 DOM 找出「同父元素下重复出现
        且内容丰富、含链接、文本多样」的元素组，那就是数据行。
        
        关键过滤：
        - 兄弟数量 5~50（搜索结果通常每页 10-30 条，排除导航/侧边栏）
        - 每行必须含链接（数据行总有公司名/网站等链接）
        - 文本多样性（兄弟间文本应各不相同，排除重复导航）
        - 过滤工具类（border-、cursor- 等）使选择器更稳定
        """
        print(f"[Joinf] 自动检测页面列表模式...")
        
        try:
            candidates = await page.evaluate("""() => {
                const results = [];
                const allElements = document.querySelectorAll('*');
                const groups = {};
                
                // 工具类/样式类过滤：这些类不稳定，不应参与签名
                const isJunkClass = (c) => /^(border-|cursor-|hover:|focus:|active:|disabled|selected|visited|pointer|whitespace|truncate|font-|text-\\[|w-\\[|h-\\[|min-w-|max-w-|flex$|items-|justify-|gap-|p-|m-|px-|py-|mx-|my-|mt-|mb-|ml-|mr-|rounded|shadow|opacity-|overflow|relative$|absolute$|fixed$|sticky$|hidden$|visible$|block$|inline$)/.test(c);
                
                for (const el of allElements) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 30 || rect.height < 15) continue;
                    
                    const skipTags = ['BODY','HTML','HEAD','SCRIPT','STYLE','NAV','FOOTER','HEADER','FORM','MAIN','SECTION','ASIDE','NOSCRIPT','SVG','PATH','IMG','BR','HR','INPUT','BUTTON','SELECT','TEXTAREA','LABEL','IFRAME'];
                    if (skipTags.includes(el.tagName)) continue;
                    
                    const tag = el.tagName.toLowerCase();
                    // 过滤掉工具类和随机 hash 类，只保留语义类
                    const semanticClasses = Array.from(el.classList || []).filter(c => 
                        !isJunkClass(c) && !/[0-9]{4,}|[_-][0-9a-f]{5,}|data-v-/.test(c)
                    ).sort().join('.');
                    
                    // ★ 关键修复：对于 li/tr 等列表标签，即使没有语义class也参与分组
                    // Joinf 的结果行只有 border-b/cursor-pointer 等工具类，不能跳过
                    const isListTag = ['li', 'tr'].includes(tag);
                    if (!semanticClasses && !isListTag) continue;
                    
                    // 有语义类用 tag.classes，没有则用 tag（如 li / tr）
                    const sig = semanticClasses ? (tag + '.' + semanticClasses) : tag;
                    if (!groups[sig]) groups[sig] = [];
                    groups[sig].push(el);
                }
                
                // 找出同父元素下出现 3~100 次的组
                for (const [sig, elements] of Object.entries(groups)) {
                    if (elements.length < 3 || elements.length > 100) continue;
                    
                    const parentMap = {};
                    for (const el of elements) {
                        const parent = el.parentElement;
                        if (!parent) continue;
                        const pKey = parent.tagName + '.' + Array.from(parent.classList || []).filter(c => !isJunkClass(c)).sort().join('.');
                        if (!parentMap[pKey]) parentMap[pKey] = { parent, elements: [] };
                        parentMap[pKey].elements.push(el);
                    }
                    
                    for (const { parent, elements: siblings } of Object.values(parentMap)) {
                        if (siblings.length < 5 || siblings.length > 100) continue;
                        
                        const sample = siblings[0];
                        
                        // ★ 每行必须包含链接或可点击元素（公司名/网站等）
                        const linkCount = sample.querySelectorAll('a[href]').length;
                        const cursorCount = sample.querySelectorAll('[class*="cursor-pointer"], [class*="company-name"]').length;
                        if (linkCount < 1 && cursorCount < 1) continue;
                        
                        // 计算文本密度（取前 5 个兄弟的平均值）
                        let totalText = 0;
                        for (const el of siblings.slice(0, 5)) {
                            totalText += (el.innerText || '').trim().length;
                        }
                        const avgLen = totalText / Math.min(siblings.length, 5);
                        if (avgLen < 30) continue;
                        
                        // ★ 文本多样性：兄弟间文本应各不相同（排除重复导航）
                        const texts = siblings.slice(0, 10).map(el => (el.innerText || '').trim().substring(0, 50));
                        const uniqueTexts = new Set(texts);
                        // 至少 50% 的兄弟有不同文本
                        if (uniqueTexts.size < Math.min(texts.length, 3)) continue;
                        
                        const childElementCount = sample.querySelectorAll('*').length;
                        if (childElementCount < 3) continue;
                        
                        // 构建选择器：优先用语义类，没有语义类时用父元素限定
                        const cClasses = Array.from(sample.classList || []).filter(c => !isJunkClass(c)).sort();
                        let childSel;
                        if (cClasses.length > 0) {
                            childSel = sample.tagName.toLowerCase() + '.' + cClasses.join('.');
                        } else {
                            // 无语义类：用父元素class限定，如 ul.result-list > li
                            const pClasses = Array.from(parent.classList || []).filter(c => !isJunkClass(c) && !/[0-9]{4,}|data-v-/.test(c)).sort();
                            if (pClasses.length > 0) {
                                childSel = parent.tagName.toLowerCase() + '.' + pClasses.join('.') + ' > ' + sample.tagName.toLowerCase();
                            } else {
                                childSel = sample.tagName.toLowerCase();
                            }
                        }
                        const sampleText = (sample.innerText || '').substring(0, 200).replace(/\\n/g, ' ');
                        
                        results.push({
                            row_selector: childSel,
                            count: siblings.length,
                            avg_text_len: Math.round(avgLen),
                            child_elements: childElementCount,
                            link_count: linkCount + cursorCount,
                            text_diversity: uniqueTexts.size,
                            sample_text: sampleText,
                        });
                    }
                }
                
                // ★ 排序：综合评分，优先搜索结果行
                results.sort((a, b) => {
                    // 1. 兄弟数量评分：5-50 最优，<5 或 >50 扣分
                    const idealCount = 20;
                    const countScore = (r) => {
                        const diff = Math.abs(r.count - idealCount);
                        if (diff <= 15) return 100;  // 5-50: 满分
                        if (r.count > 50) return Math.max(0, 50 - (r.count - 50));  // >50: 急剧扣分
                        return Math.max(0, 30 - (5 - r.count) * 10);  // <5: 扣分
                    };
                    // 2. 文本丰富度
                    const textScore = (r) => Math.min(r.avg_text_len, 200);
                    // 3. 链接数（数据行有多链接）
                    const linkScore = (r) => Math.min(r.link_count * 5, 30);
                    // 4. 文本多样性
                    const diversityScore = (r) => Math.min(r.text_diversity * 3, 30);
                    
                    const scoreA = countScore(a) + textScore(a) + linkScore(a) + diversityScore(a);
                    const scoreB = countScore(b) + textScore(b) + linkScore(b) + diversityScore(b);
                    return scoreB - scoreA;
                });
                
                return results.slice(0, 5);
            }""")
            
            if candidates:
                print(f"[Joinf] 检测到 {len(candidates)} 个候选列表模式:")
                for i, c in enumerate(candidates):
                    print(f"       [{i}] selector='{c['row_selector']}' count={c['count']} avgLen={c['avg_text_len']} children={c['child_elements']} sample='{c['sample_text'][:80]}'")
                
                best = candidates[0]
                print(f"[Joinf] 选择最佳列表: '{best['row_selector']}' ({best['count']} 行, 平均文本 {best['avg_text_len']} 字符)")
                return {
                    "page_type": "search_results",
                    "row_selector": best["row_selector"],
                    "row_count": best["count"],
                    "detail_button_selector": "",
                    "has_pagination": True,
                    "next_page_selector": "",
                }
        except Exception as e:
            print(f"[Joinf] 自动列表检测异常: {e}")
        
        return {}

    async def _extract_rows_ai(self, page, source_type: str, structure: Dict[str, Any]) -> List[JoinfRawRow]:
        """从列表行中提取结果 — 不硬编码任何 CSS 选择器。
        
        核心思路：
        1. 用 row_selector 找到每个列表行
        2. 从每行提取全部原始内容（文本 + 链接），不做任何字段假设
        3. 用 AI 分析样本行内容，识别出各字段对应的文本片段
        4. 将 AI 的字段映射应用到所有行
        """
        rows: List[JoinfRawRow] = []
        row_sel = structure.get("row_selector", "")
        
        if not row_sel:
            print(f"[Joinf] 无行选择器，跳过提取")
            return rows

        try:
            row_locator = page.locator(row_sel)
            count = await row_locator.count()
            print(f"[Joinf] 选择器 '{row_sel}' 匹配 {count} 行")

            if count == 0:
                print(f"[Joinf] 选择器未匹配任何行，保存调试信息")
                await self._dump_page_debug(page, f"{source_type}-no-rows-ai")
                return rows

            # ── 阶段1：从每行提取原始内容（文本 + 链接） ──
            raw_rows = []
            for index in range(count):
                row_el = row_locator.nth(index)
                
                # 提取全部可见文本
                full_text = ""
                try:
                    full_text = (await row_el.inner_text()).strip()
                except Exception:
                    pass
                
                # 提取所有链接
                links = []
                try:
                    all_link_els = row_el.locator("a[href]")
                    link_count = await all_link_els.count()
                    for i in range(link_count):
                        href = await all_link_els.nth(i).get_attribute("href")
                        link_text = ""
                        try:
                            link_text = (await all_link_els.nth(i).inner_text()).strip()[:80]
                        except Exception:
                            pass
                        if href:
                            links.append({"href": href, "text": link_text})
                except Exception:
                    pass
                
                # 提取每个直接子元素的文本（用于 AI 更精准地定位字段）
                child_segments = []
                try:
                    child_segments = await row_el.evaluate("""el => {
                        const segments = [];
                        // ★ 方法1：优先用直接子元素的 innerText 分列
                        // 直接子元素通常对应不同的数据列（公司名、网站、数量等）
                        const directChildren = el.querySelectorAll(':scope > *');
                        if (directChildren.length >= 2) {
                            for (const child of directChildren) {
                                const t = child.innerText ? child.innerText.trim() : '';
                                if (t.length > 0) {
                                    const tag = child.tagName.toLowerCase();
                                    const cls = Array.from(child.classList || []).join('.');
                                    segments.push({ selector: tag + (cls ? '.' + cls : ''), text: t.substring(0, 200) });
                                }
                            }
                            if (segments.length >= 2) return segments;
                        }
                        // ★ 方法2：降级到叶子文本节点遍历
                        segments.length = 0;
                        const walk = (node, path = '') => {
                            if (node.nodeType === Node.TEXT_NODE) {
                                const t = node.textContent.trim();
                                if (t.length > 0) {
                                    const parent = node.parentElement;
                                    const tag = parent ? parent.tagName.toLowerCase() : '';
                                    const cls = parent ? Array.from(parent.classList || []).join('.') : '';
                                    segments.push({ selector: tag + (cls ? '.' + cls : ''), text: t.substring(0, 200) });
                                }
                            } else if (node.nodeType === Node.ELEMENT_NODE) {
                                const tag = node.tagName;
                                if (['SCRIPT','STYLE','NOSCRIPT'].includes(tag)) return;
                                for (const child of node.childNodes) {
                                    walk(child, path + '/' + tag);
                                }
                            }
                        };
                        walk(el);
                        // 去重相邻重复
                        const deduped = [];
                        for (const s of segments) {
                            if (!deduped.length || deduped[deduped.length-1].text !== s.text) {
                                deduped.push(s);
                            }
                        }
                        return deduped;
                    }""")
                except Exception as e:
                    print(f"[Joinf] child_segments 提取失败: {e}")
                    pass
                
                raw_rows.append({
                    "index": index,
                    "full_text": full_text,
                    "links": links,
                    "child_segments": child_segments,
                })

            # ── 阶段2：AI 分析样本行，识别字段映射 ──
            field_mapping = None
            if self.ai and self.ai._available() and raw_rows:
                sample = raw_rows[0]
                field_mapping = await self._ai_map_row_fields(sample, source_type)
                if field_mapping:
                    print(f"[Joinf] AI 字段映射: {field_mapping}")
                else:
                    print(f"[Joinf] AI 字段映射失败，将使用原始文本")

            # ── 阶段3：应用字段映射，构建结构化行数据 ──
            seen_row_texts = set()  # ★ 去重：相同 full_text 的行只保留一条
            for raw in raw_rows:
                # ★ 去重检查
                dedup_key = raw["full_text"].strip()[:200]
                if dedup_key in seen_row_texts:
                    print(f"[Joinf] 跳过重复行 index={raw['index']}: {dedup_key[:60]}")
                    continue
                seen_row_texts.add(dedup_key)
                
                cells = []
                metadata = {"links": raw["links"]}
                
                full_text = raw["full_text"]
                links = raw["links"]
                child_segments = raw["child_segments"]

                if field_mapping:
                    # ★ 用 AI 返回的映射从 child_segments 中提取字段
                    # 关键：跟踪已使用的 segment，防止同一个文本被分配到多个字段
                    used_segment_indices = set()
                    for field_name, selector_hint in field_mapping.items():
                        if not selector_hint:
                            continue
                        value, seg_idx = self._extract_field_from_segments_v2(
                            child_segments, selector_hint, field_name, used_segment_indices
                        )
                        if value:
                            metadata[field_name] = value
                            if seg_idx is not None:
                                used_segment_indices.add(seg_idx)
                    
                    # 构建结构化 cells
                    structured_parts = []
                    field_labels = {
                        "company_name": "公司名称",
                        "website": "网站",
                        "country": "国家",
                        "description": "公司简介",
                        "email_count": "邮箱数量",
                    }
                    for field, label in field_labels.items():
                        if metadata.get(field):
                            structured_parts.append(f"{label}: {metadata[field]}")
                    cells = structured_parts if structured_parts else self._build_cells_from_segments(child_segments, full_text)
                else:
                    # ★ 无 AI 映射时，优先用 child_segments 分列（比 full_text 更精确）
                    cells = self._build_cells_from_segments(child_segments, full_text)
                    # 从链接和文本中尝试提取网站
                    metadata["website"] = self._extract_website_url(full_text + "\n" + "\n".join(
                        f"链接: {l.get('text','')} -> {l.get('href','')}" for l in links
                    ))

                rows.append(JoinfRawRow(
                    source_type=source_type,
                    page_url=page.url,
                    row_index=raw["index"],
                    cells=cells,
                    metadata=metadata,
                ))

        except Exception as e:
            print(f"[Joinf] _extract_rows_ai 异常: {e}")

        return rows

    async def _ai_map_row_fields(self, sample_row: Dict, source_type: str) -> Optional[Dict[str, str]]:
        """让 AI 分析一个样本行的内容，返回各字段对应的 DOM 选择器提示。
        
        AI 不是返回 CSS 选择器（因为 class 名可能无意义），而是返回
        「看起来像公司名的那个文本段对应的 selector」，我们用这个
        selector 去 child_segments 中匹配。
        """
        if not self.ai or not self.ai._available():
            return None

        segments_text = "\n".join(
            f"[{s['selector']}] {s['text']}" 
            for s in (sample_row.get("child_segments") or [])[:30]
        )
        links_text = "\n".join(
            f"链接: {l.get('text','')} -> {l.get('href','')}"
            for l in (sample_row.get("links") or [])[:10]
        )

        prompt = (
            "你是一个网页数据提取专家。下面是一个搜索结果列表中某一行的内容，"
            "已经将每个文本片段与其所在元素的 CSS 选择器标注出来。\n\n"
            "请分析这些文本片段，识别出以下字段分别对应哪个选择器：\n"
            "- company_name: 公司名称\n"
            "- website: 公司网站URL或域名\n"
            "- country: 国家/地区\n"
            "- description: 公司描述/简介\n"
            "- email_count: 邮箱数量（如果有的话）\n\n"
            "如果某个字段在文本中找不到，返回 null。\n"
            "返回 JSON，格式：{\"company_name\": \".company-name\", \"website\": \".websiteBox .text-primary\", ...}\n"
            "选择器应该尽量精确，能匹配到包含该字段文本的元素。\n\n"
            f"=== 行内容片段 ===\n{segments_text}\n\n"
            f"=== 行内链接 ===\n{links_text}\n\n"
            "直接返回 JSON，不要加 markdown。"
        )

        try:
            field_schema = {
                "type": "object",
                "properties": {
                    "company_name": {"type": ["string", "null"], "description": "公司名称文本对应的 CSS 选择器"},
                    "website": {"type": ["string", "null"], "description": "网站URL/域名文本对应的 CSS 选择器"},
                    "country": {"type": ["string", "null"], "description": "国家/地区文本对应的 CSS 选择器"},
                    "description": {"type": ["string", "null"], "description": "公司描述文本对应的 CSS 选择器"},
                    "email_count": {"type": ["string", "null"], "description": "邮箱数量文本对应的 CSS 选择器"},
                }
            }
            result = await self.ai._call(
                "你是网页数据提取专家，根据文本片段和其选择器标注，识别各业务字段对应的选择器。直接返回 JSON。",
                prompt,
                field_schema,
                max_tokens=512,
            )
            if result:
                # 过滤掉 null 值
                return {k: v for k, v in result.items() if v}
        except Exception as e:
            print(f"[Joinf] AI 字段映射异常: {e}")
        
        return None

    def _extract_field_from_segments(self, child_segments: List[Dict], selector_hint: str, field_name: str) -> str:
        """根据 AI 返回的选择器提示，从 child_segments 中匹配并提取字段值。
        
        匹配策略：选择器可能不完全精确，所以做模糊匹配：
        1. 精确匹配：selector 完全一致
        2. 前缀匹配：selector 的 class 部分包含 hint 中的 class
        3. 文本内容匹配：根据字段名语义判断（如 website 找含 URL 的文本）
        """
        if not child_segments:
            return ""

        # 策略1：精确匹配
        for seg in child_segments:
            if seg.get("selector") == selector_hint:
                return seg.get("text", "")

        # 策略2：选择器包含 hint 中的关键 class
        hint_classes = [c for c in selector_hint.replace(".", " .").split() if c.startswith(".")]
        if hint_classes:
            for seg in child_segments:
                seg_sel = seg.get("selector", "")
                for hc in hint_classes:
                    if hc in seg_sel:
                        return seg.get("text", "")

        # 策略3：根据字段名语义匹配
        semantic_hints = {
            "company_name": lambda t: len(t) > 2 and len(t) < 100 and not re.match(r'https?://', t),
            "website": lambda t: bool(re.match(r'(https?://|www\.|[a-z0-9-]+\.(com|net|org|io|co|site|tech))', t, re.I)),
            "country": lambda t: len(t) < 20 and not re.match(r'https?://', t),
            "description": lambda t: len(t) > 20,
            "email_count": lambda t: bool(re.search(r'\d+\s*邮箱', t)),
        }
        
        checker = semantic_hints.get(field_name)
        if checker:
            for seg in child_segments:
                if checker(seg.get("text", "")):
                    return seg.get("text", "")

        return ""

    def _extract_field_from_segments_v2(
        self, child_segments: List[Dict], selector_hint: str, field_name: str, used_indices: set
    ) -> tuple:
        """V2: 与 V1 相同的匹配逻辑，但跳过已使用的 segment，返回 (value, segment_index)。
        
        防止同一个 segment 文本被分配到多个字段（如公司名同时被映射为国家）。
        """
        if not child_segments:
            return ("", None)

        # 策略1：精确匹配
        for i, seg in enumerate(child_segments):
            if i in used_indices:
                continue
            if seg.get("selector") == selector_hint:
                return (seg.get("text", ""), i)

        # 策略2：选择器包含 hint 中的关键 class
        hint_classes = [c for c in selector_hint.replace(".", " .").split() if c.startswith(".")]
        if hint_classes:
            for i, seg in enumerate(child_segments):
                if i in used_indices:
                    continue
                seg_sel = seg.get("selector", "")
                for hc in hint_classes:
                    if hc in seg_sel:
                        return (seg.get("text", ""), i)

        # 策略3：根据字段名语义匹配（更严格的规则）
        semantic_hints = {
            "company_name": lambda t: (
                len(t) > 2 and len(t) < 100 
                and not re.match(r'https?://', t)
                and not re.match(r'[a-zA-Z0-9-]+\.(com|net|org|io|co|site|tech)', t)  # 排除域名
            ),
            "website": lambda t: bool(re.match(r'(https?://|www\.|[a-z0-9-]+\.(com|net|org|io|co|site|tech))', t, re.I)),
            "country": lambda t: (
                len(t) >= 2 and len(t) < 50
                and not re.match(r'https?://', t)
                and not re.match(r'[a-zA-Z0-9-]+\.(com|net|org|io|co|site|tech)', t)  # 排除域名
                and not re.match(r'\+?\d+$', t)  # 排除纯数字
            ),
            "description": lambda t: len(t) > 20,
            "email_count": lambda t: bool(re.search(r'\d+\s*邮箱', t)),
        }
        
        checker = semantic_hints.get(field_name)
        if checker:
            for i, seg in enumerate(child_segments):
                if i in used_indices:
                    continue
                if checker(seg.get("text", "")):
                    return (seg.get("text", ""), i)

        return ("", None)

    def _build_cells_from_segments(self, child_segments: List[Dict], full_text: str) -> List[str]:
        """从 child_segments 构建分列的 cells — 比 full_text.split("\\n") 更精确。
        
        child_segments 包含每个文本节点的内容，即使 DOM 中没有换行也能分列。
        过滤规则：
        - 去掉很短的片段（<2字符）
        - 去掉重复片段
        - 保留有意义的文本（公司名、网站、国家等）
        
        最终降级：如果 child_segments 和 full_text 都无法分列，
        尝试智能拆分拼接的字符串（如 "zjbsledzjbsled.com+21010" → ["zjbsled", "zjbsled.com", "+2", "10", "10"]）
        """
        if not child_segments:
            # 降级到 full_text
            cells = [line.strip() for line in full_text.split("\n") if line.strip()]
            if len(cells) > 1:
                return cells
            # full_text 也没有换行，尝试智能拆分
            return self._smart_split_concatenated_text(full_text)
        
        seen = set()
        cells = []
        for seg in child_segments:
            text = seg.get("text", "").strip()
            if not text or len(text) < 2:
                continue
            # 去重
            if text in seen:
                continue
            seen.add(text)
            cells.append(text)
        
        # 如果 segments 过滤后太少（可能文本全在一个节点），降级
        if len(cells) <= 1 and full_text:
            alt_cells = [line.strip() for line in full_text.split("\n") if line.strip()]
            if len(alt_cells) > len(cells):
                return alt_cells
            # full_text 也没有换行，尝试智能拆分
            return self._smart_split_concatenated_text(full_text)
        
        return cells

    def _smart_split_concatenated_text(self, text: str) -> List[str]:
        """尝试智能拆分拼接在一起的文本。
        
        例如："zjbsledzjbsled.com+21010" 
        → 识别出域名 zjbsled.com，发现前缀 "zjbsled" 是公司名
        → 拆分为 ["zjbsled", "zjbsled.com", "+2", "10", "10"]
        """
        if not text or len(text) < 3:
            return [text] if text else []
        
        import re
        
        # 策略1：用域名做切分，并尝试分离公司名前缀
        # 匹配短域名（3-20字符的域名主体），避免贪心匹配整个前缀
        domain_match = re.search(
            r'([a-zA-Z0-9](?:[a-zA-Z0-9-]{1,18}[a-zA-Z0-9])?\.(?:com|net|org|io|co|site|tech|store|online|biz|info|de|uk|fr|it|es|nl|eu|us|cn|jp))',
            text
        )
        if domain_match:
            parts = []
            before = text[:domain_match.start()]
            domain = domain_match.group(1)
            after = text[domain_match.end():]
            
            # ★ 检查 before 是否包含 domain 的前缀（公司名和域名往往同根）
            domain_root = domain.split('.')[0].lower()
            if before and domain_root and before.lower().endswith(domain_root):
                overlap_pos = before.lower().rfind(domain_root)
                if overlap_pos > 0:
                    parts.append(before[:overlap_pos])  # 真正的公司名
                # before 的重叠部分和 domain 重复，只保留 domain
            elif before:
                parts.append(before)
            
            parts.append(domain)
            
            if after:
                after_parts = re.split(r'(\+\d+)', after)
                result_after = []
                for p in after_parts:
                    if not p:
                        continue
                    num_parts = re.split(r'(\d{2,})', p)
                    result_after.extend([np for np in num_parts if np])
                parts.extend(result_after)
            return parts
        
        # 策略2：用数字前缀做切分
        parts = re.split(r'(\+\d+|\d{3,})', text)
        result = [p for p in parts if p]
        if len(result) > 1:
            return result
        
        # 策略3：无法拆分，返回原文
        return [text]

    async def _enrich_rows_with_detail_ai(
        self, 
        page, 
        rows: List[JoinfRawRow], 
        structure: Dict[str, Any],
        keyword: str = "",
        job_id: int = 0,
    ) -> List[JoinfRawRow]:
        """
        AI 驱动的客户评估（访问公司网站版）：
        
        流程：
        1. 从列表行文本提取基本信息（公司名、网站URL等）
        2. 如果有网站URL → 用 httpx 访问网站获取页面文本
        3. 将列表信息 + 网站内容一起给 AI 分析
        4. AI 基于网站内容判断客户匹配度
        
        这样 AI 不仅能看到列表上的公司名和国家，
        还能看到该公司网站上实际做什么业务，判断更准确。
        """
        enriched_rows: List[JoinfRawRow] = []

        if not self.ai or not self.ai._available():
            print(f"[Joinf] enrich: AI 不可用，跳过客户评估")
            return rows

        source_type = rows[0].source_type if rows else "business"
        my_product = keyword or "该产品"
        print(f"[Joinf] enrich[{source_type}]: AI 评估 {len(rows)} 条结果，目标客户: 采购「{my_product}」的买家")

        for index, row in enumerate(rows):
            # ★ 每条都检查取消状态（AI 调用很慢，必须及时响应取消）
            if job_id and is_cancelled(job_id):
                print(f"[Joinf] enrich: Job {job_id} 已取消，已评估 {index}/{len(rows)} 条")
                enriched_rows.extend(rows[index:])
                break

            try:
                # 拼接该行的全部可见文本
                row_text = "\n".join(row.cells) if row.cells else ""

                # 追加链接信息（AI 可以从中提取网站 URL）
                links = row.metadata.get("links", [])
                if links:
                    link_lines = []
                    for link in links:
                        if isinstance(link, dict):
                            href = link.get("href", "")
                            text = link.get("text", "")
                            if text and text != "social-media":
                                link_lines.append(f"链接: {text} -> {href}")
                            elif text != "social-media":
                                link_lines.append(f"链接: {href}")
                        elif isinstance(link, str):
                            link_lines.append(f"链接: {link}")
                    if link_lines:
                        row_text += "\n\n页面链接：\n" + "\n".join(link_lines)

                if not row_text.strip():
                    print(f"[Joinf] enrich[{index}]: 行文本为空，跳过")
                    enriched_rows.append(row)
                    continue

                # ★ 核心：优先用结构化提取的网站URL，否则从文本正则提取
                website_url = row.metadata.get("website") or self._extract_website_url(row_text)
                website_text = ""
                if website_url:
                    print(f"[Joinf] enrich[{index}]: 访问公司网站 {website_url}")
                    website_text = await self._fetch_website_text(website_url)
                    if website_text:
                        print(f"[Joinf] enrich[{index}]: 获取到网站内容 ({len(website_text)} 字符)")
                    else:
                        print(f"[Joinf] enrich[{index}]: 网站内容获取失败，仅基于列表信息评估")

                # ★ 核心：让 AI 综合列表信息 + 网站内容评估客户匹配度
                evaluation = await self.ai.evaluate_company(
                    row_text=row_text,
                    my_product=my_product,
                    source_type=source_type,
                    website_text=website_text,
                )

                if evaluation:
                    row.metadata["ai_evaluation"] = evaluation
                    score = evaluation.get("match_score", 0)
                    ctype = evaluation.get("customer_type", "unknown")
                    reason = evaluation.get("match_reason", "")[:60]
                    website_tag = " [有网站]" if website_text else ""
                    print(f"[Joinf] enrich[{index}]: {evaluation.get('company_name', 'N/A')} → 匹配度={score} 类型={ctype}{website_tag} ({reason})")
                else:
                    print(f"[Joinf] enrich[{index}]: AI 评估返回空")

                enriched_rows.append(row)

            except Exception as e:
                print(f"[Joinf] enrich error at index {index}: {e}")
                enriched_rows.append(row)

        return enriched_rows

    def _extract_website_url(self, row_text: str) -> Optional[str]:
        """从行文本中提取公司网站 URL
        
        支持格式：
        - https://www.example.com
        - http://example.com
        - www.example.com
        - example.com（从链接 href 中提取，或从文本中识别常见域名后缀）
        """
        import re
        
        # 1. 优先找链接信息中的 URL（更可靠，来自 <a href> 属性）
        links_section = ""
        if "页面链接：" in row_text:
            links_section = row_text[row_text.index("页面链接："):]
        
        # 先从链接部分提取（排除平台/社交等非公司网站）
        skip_domains = [
            "joinf.com", "linkedin.com", "google.com", "facebook.com", "javascript:",
            "mangoerp.com", "twitter.com", "youtube.com", "instagram.com", "pinterest.com",
            "whatsapp.com", "skype.com", "wechat.com", "weixin.qq.com",
            "amazon.com", "alibaba.com", "made-in-china.com", "globalsources.com",
            "login.", "auth.", "accounts.", "sso.",  # 登录/认证页面
        ]
        for section in [links_section, row_text]:
            # http/https 链接
            url_pattern = r'https?://[^\s<>"\']+(?<![.,;:!?)\]}>])'
            matches = re.findall(url_pattern, section)
            for url in matches:
                if any(skip in url.lower() for skip in skip_domains):
                    continue
                return url
            
            # www. 开头
            www_pattern = r'www\.[^\s<>"\']+(?<![.,;:!?)\]}>])'
            matches = re.findall(www_pattern, section)
            if matches:
                return f"https://{matches[0]}"
        
        # 2. 从文本中识别裸域名（如 zjbsled.com、usofull.site）
        # 常见域名后缀
        domain_pattern = r'(?:^|\s)([a-zA-Z0-9][\w-]*\.(?:com|net|org|io|co|site|tech|store|online|biz|info|de|uk|fr|it|es|nl|eu|us|cn|jp|kr|au|ca|in|br|mx|cc|tv|me|app|dev|cloud|live|world|global|international|ltd|group|company|solutions|systems|industries))\b'
        matches = re.findall(domain_pattern, row_text, re.IGNORECASE)
        for domain in matches:
            # 排除平台域名和非公司网站
            if any(skip in domain.lower() for skip in [
                "joinf.com", "linkedin.com", "google.com", "facebook.com",
                "mangoerp.com", "twitter.com", "youtube.com", "instagram.com",
                "whatsapp.com", "skype.com", "amazon.com", "alibaba.com",
            ]):
                continue
            return f"https://{domain}"
        
        return None

    async def _fetch_website_text(self, url: str) -> str:
        """用 httpx 访问网站并提取可见文本内容"""
        import httpx
        import re
        
        # 确保URL格式正确
        if not url.startswith("http"):
            url = f"https://{url}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        # 先试 HTTPS，失败降级到 HTTP
        for proto_url in [url, url.replace("https://", "http://")]:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(15.0, connect=5.0),
                    follow_redirects=True,
                    headers=headers,
                    verify=False,  # 很多公司网站证书有问题，跳过验证
                ) as client:
                    resp = await client.get(proto_url)
                    resp.raise_for_status()
                    html = resp.text
                    break
            except Exception as e:
                err_msg = str(e) or type(e).__name__
                if proto_url.startswith("https://") and proto_url != url.replace("https://", "http://"):
                    # HTTPS 失败，尝试 HTTP 降级
                    print(f"[Joinf] _fetch_website_text: HTTPS 访问 {proto_url} 失败 ({err_msg})，尝试 HTTP")
                    continue
                else:
                    print(f"[Joinf] _fetch_website_text: 访问 {proto_url} 失败: {err_msg}")
                    return ""
        else:
            return ""
        
        # 从 HTML 中提取可见文本（去掉标签）
        text = html
        
        # 去掉 <script> 和 <style> 标签内容
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # 去掉所有 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', text)
        
        # 解码 HTML 实体
        import html as html_module
        text = html_module.unescape(text)
        
        # 清理空白
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 截取有效部分（首页内容通常在前面）
        return text[:10000]

    async def _enrich_business_rows_with_detail(self, page, rows: List[JoinfRawRow]) -> List[JoinfRawRow]:
        """兼容旧接口 → 调用新的 AI 驱动方法"""
        return await self._enrich_rows_with_detail_ai(page, rows, self._fallback_structure())

    async def _enrich_customs_rows_with_detail(self, page, rows: List[JoinfRawRow]) -> List[JoinfRawRow]:
        """兼容旧接口 → 调用新的 AI 驱动方法"""
        return await self._enrich_rows_with_detail_ai(page, rows, self._fallback_structure())

    # ================================================================
    # 工具方法（登录、点击、查找等）
    # ================================================================

    async def _click_first(self, page, selectors: List[str]) -> None:
        locator = await self._find_first(page, selectors)
        if locator is None:
            raise RuntimeError(f"未找到可点击元素：{selectors}")
        await locator.click()
        await page.wait_for_timeout(1000)

    async def _try_click_first(self, page, selectors: List[str], wait_ms: int = 1000) -> bool:
        locator = await self._find_first(page, selectors)
        if locator is None:
            return False
        await locator.click()
        await page.wait_for_timeout(wait_ms)
        return True

    async def _find_first(self, page, selectors: List[str], locator_mode: bool = False):
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                if count <= 0:
                    continue

                if locator_mode:
                    return locator

                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        if await candidate.is_visible():
                            return candidate
                    except Exception:
                        continue

                return locator.first
            except Exception:
                continue
        return None

    async def _try_auto_login(self, page) -> bool:
        username_input = await self._find_first(page, JoinfSelectors.login_username_input_candidates)
        password_input = await self._find_first(page, JoinfSelectors.login_password_input_candidates)

        if username_input is None or password_input is None:
            return False

        await username_input.fill(self.config.username or "")
        await password_input.fill(self.config.password or "")

        submit_button = await self._find_first(page, JoinfSelectors.login_submit_candidates)
        if submit_button is not None:
            await submit_button.click()
        else:
            await password_input.press("Enter")

        await page.wait_for_timeout(2500)
        return await self._is_logged_in(page)

    async def _is_logged_in(self, page) -> bool:
        current_url = (page.url or "").lower()

        # If on data.joinf.com with a non-login path, we're logged in
        if "data.joinf.com" in current_url and "login" not in current_url:
            # Check that we're not on a page that shows login form
            has_login_form = await self._has_visible_selector(page, JoinfSelectors.login_password_input_candidates)
            if not has_login_form:
                return True

        # If URL contains "login", definitely not logged in
        if "login" in current_url:
            return False

        # Check for visible login form
        has_visible_login_inputs = await self._has_visible_selector(page, JoinfSelectors.login_username_input_candidates) and await self._has_visible_selector(
            page, JoinfSelectors.login_password_input_candidates
        )
        if has_visible_login_inputs:
            return False

        # Check for login success indicators
        if await self._has_visible_selector(page, JoinfSelectors.login_success_candidates):
            return True

        # Check for login page markers
        if await self._has_visible_selector(page, JoinfSelectors.login_page_marker_candidates):
            return False

        # Default: if on data.joinf.com without login indicators, assume logged in
        if "joinf.com" in current_url:
            return True

        return False

    async def _has_visible_selector(self, page, selectors: List[str]) -> bool:
        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    try:
                        if await candidate.is_visible():
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False

    async def _wait_for_table_rows(self, page, wait_seconds: int) -> bool:
        for i in range(max(1, wait_seconds)):
            row_locator = await self._find_first(page, JoinfSelectors.table_row_candidates, locator_mode=True)
            if row_locator is not None:
                try:
                    if await row_locator.count() > 0:
                        return True
                except Exception:
                    pass
            if i == 0:
                print(f"[Joinf] _wait_for_table_rows: 等待表格出现，当前 URL={page.url}")
            if i % 30 == 29:
                print(f"[Joinf] _wait_for_table_rows: 已等待 {i+1} 秒，仍未检测到表格")
            await page.wait_for_timeout(1000)
        # Timeout - dump debug info
        print(f"[Joinf] _wait_for_table_rows: 超时 {wait_seconds} 秒未检测到表格")
        await self._dump_page_debug(page, "wait-table-timeout")
        return False

    async def _try_fill_with_fallback(self, page, locator, value: str, dropdown_selectors: List[str]) -> bool:
        if not value:
            return False

        try:
            await locator.fill(value)
            await locator.press("Enter")
            await page.wait_for_timeout(600)
            return True
        except Exception:
            pass

        try:
            await locator.click()
        except Exception:
            try:
                await locator.click(force=True)
            except Exception:
                return False

        dropdown_input = await self._find_first(page, dropdown_selectors)
        if dropdown_input is not None:
            try:
                await dropdown_input.fill(value)
                await dropdown_input.press("Enter")
                await page.wait_for_timeout(700)
                return True
            except Exception:
                pass

        try:
            await page.keyboard.press("ControlOrMeta+A")
        except Exception:
            pass

        try:
            await page.keyboard.type(value)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(700)
            return True
        except Exception:
            return False

    async def _dump_page_debug(self, page, label: str) -> None:
        """Save page HTML and screenshot for debugging when selectors don't match."""
        try:
            self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
            html_path = self.config.screenshot_dir / f"{label}.html"
            html_content = await page.content()
            html_path.write_text(html_content, encoding="utf-8")
            print(f"[Joinf] Debug: saved HTML to {html_path} (length={len(html_content)})")

            ss_path = self.config.screenshot_dir / f"{label}.png"
            try:
                await page.screenshot(path=str(ss_path), timeout=10000)
                print(f"[Joinf] Debug: saved screenshot to {ss_path}")
            except Exception as ss_err:
                print(f"[Joinf] Debug: screenshot skipped ({ss_err})")

            # 扫描页面上的常见列表/表格/卡片结构
            scan_selectors = [
                "table", ".el-table", ".ant-table",
                "[class*='table']", "[class*='list']",
                "[class*='card']", "[class*='result']",
                "[class*='item']", "[class*='row']",
                "[class*='company']",
                "ul > li",
                "a[href*='detail']", "a[href*='company']",
                "a[href*='view']", "a[href*='/data']",
            ]
            for selector in scan_selectors:
                try:
                    loc = page.locator(selector)
                    cnt = await loc.count()
                    if cnt > 0:
                        # 获取前几个元素的 outerHTML 片段用于识别
                        sample = ""
                        try:
                            sample = (await loc.first.inner_text())[:80].replace("\n", " ")
                        except Exception:
                            pass
                        print(f"[Joinf] Debug: found {cnt}x '{selector}' -> \"{sample}\"")
                except Exception:
                    pass
        except Exception as e:
            print(f"[Joinf] Debug: failed to dump page debug: {e}")


def _is_freight_company(name: str) -> bool:
    lowered = (name or "").lower()
    return any(keyword in lowered for keyword in FREIGHT_KEYWORDS)
