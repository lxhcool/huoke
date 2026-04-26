from __future__ import annotations

import asyncio
import random
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from app.scrapers.linkedin.browser import LinkedinBrowserSession
from app.scrapers.linkedin.config import LinkedinScraperConfig
from app.scrapers.linkedin.models import LinkedinRawRow, LinkedinScrapeBatch
from app.scrapers.linkedin.selectors import LinkedinSelectors
from app.scrapers.linkedin.storage import dump_batch

MAX_PAGES = 2
MAX_ITEMS_PER_PAGE = 10
MIN_DELAY = 2
MAX_DELAY = 8


async def _random_delay() -> None:
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


class LinkedinScraperService:
    def __init__(self, config: Optional[LinkedinScraperConfig] = None):
        self.config = config or LinkedinScraperConfig()

    async def ensure_login_session(
        self,
        allow_manual: bool = True,
        interactive_manual: bool = True,
        manual_timeout_seconds: int = 180,
    ) -> str:
        async with LinkedinBrowserSession(self.config) as session:
            assert session.page is not None
            await session.page.goto(self.config.login_url)
            await self._guard_supported_domain(session.page)
            await session.page.screenshot(path=str(self.config.screenshot_dir / "login-page.png"), full_page=True)

            logged_in = await self._is_logged_in(session.page)
            if not logged_in and self.config.has_credentials():
                logged_in = await self._try_auto_login(session.page)

            if not logged_in and allow_manual:
                if interactive_manual:
                    print("请在打开的浏览器中手动完成 LinkedIn 登录，完成后回到终端按回车继续。")
                    await asyncio.to_thread(input)
                    logged_in = await self._is_logged_in(session.page)
                else:
                    logged_in = await self._wait_for_manual_login(session.page, manual_timeout_seconds)

            if not logged_in:
                raise RuntimeError("LinkedIn 登录失败，请检查账号密码或手动登录是否在超时时间内完成")

            await session.page.screenshot(path=str(self.config.screenshot_dir / "login-success.png"), full_page=True)

        return str(self.config.storage_state_path)

    async def _wait_for_manual_login(self, page, timeout_seconds: int) -> bool:
        for _ in range(max(1, timeout_seconds)):
            if await self._is_logged_in(page):
                return True
            await page.wait_for_timeout(1000)
        return await self._is_logged_in(page)

    async def scrape_company_data(self, keyword: str, country: Optional[str] = None) -> str:
        return await self._scrape_source("company", keyword, country)

    async def scrape_contact_data(self, keyword: str, country: Optional[str] = None) -> str:
        return await self._scrape_source("contact", keyword, country)

    async def _scrape_source(self, source_type: str, keyword: str, country: Optional[str]) -> str:
        batch = LinkedinScrapeBatch(source_type=source_type, keyword=keyword, country=country)

        async with LinkedinBrowserSession(self.config) as session:
            assert session.page is not None

            search_url = self._build_search_url(source_type, keyword)
            await session.page.goto(search_url)
            await self._guard_supported_domain(session.page)

            if not await self._is_logged_in(session.page):
                if not self.config.has_credentials():
                    raise RuntimeError("LinkedIn 登录态不存在，请先执行 python -m app.scripts.linkedin_capture login")
                if not await self._try_auto_login(session.page):
                    raise RuntimeError("LinkedIn 自动登录失败，请检查 LINKEDIN_USERNAME/LINKEDIN_PASSWORD")
                await session.page.goto(search_url)
                await self._guard_supported_domain(session.page)

            await _random_delay()
            snapshot_path = self.config.screenshot_dir / f"{source_type}-results.png"
            await session.page.screenshot(path=str(snapshot_path), full_page=True)
            batch.page_snapshots.append(str(snapshot_path))

            # 多页抓取 + 详情页深入
            for page_num in range(MAX_PAGES):
                page_rows = await self._extract_rows(session.page, source_type)
                if not page_rows:
                    break

                # 限制每页最多抓取条数
                page_rows = page_rows[:MAX_ITEMS_PER_PAGE]

                if source_type == "company":
                    page_rows = await self._enrich_company_rows_with_detail(session.page, page_rows)

                batch.items.extend(page_rows)

                if page_num < MAX_PAGES - 1:
                    has_next = await self._try_click_pagination_next(session.page)
                    if not has_next:
                        break
                    await _random_delay()

        return str(dump_batch(batch, self.config.raw_output_dir))

    def _build_search_url(self, source_type: str, keyword: str) -> str:
        encoded = quote_plus(keyword)
        if source_type == "company":
            return f"{self.config.base_url}/search/results/companies/?keywords={encoded}"
        return f"{self.config.base_url}/search/results/people/?keywords={encoded}"

    async def _extract_rows(self, page, source_type: str) -> List[LinkedinRawRow]:
        rows: List[LinkedinRawRow] = []
        row_selectors = (
            LinkedinSelectors.company_result_row_candidates
            if source_type == "company"
            else LinkedinSelectors.contact_result_row_candidates
        )
        row_locator = await self._find_first(page, row_selectors, locator_mode=True)

        if row_locator is None:
            return rows

        count = await row_locator.count()
        for index in range(count):
            row = row_locator.nth(index)
            text = (await row.inner_text()).strip()
            cells = [cell.strip() for cell in text.split("\n") if cell.strip()]

            link_locator = row.locator("a[href]")
            links: List[str] = []
            link_count = await link_locator.count()
            for link_index in range(link_count):
                href = await link_locator.nth(link_index).get_attribute("href")
                normalized = self._normalize_link(href)
                if normalized:
                    links.append(normalized)

            rows.append(
                LinkedinRawRow(
                    source_type=source_type,
                    page_url=page.url,
                    row_index=index,
                    cells=cells,
                    metadata={"links": links},
                )
            )

        return rows

    async def _enrich_company_rows_with_detail(self, page, rows: List[LinkedinRawRow]) -> List[LinkedinRawRow]:
        enriched_rows: List[LinkedinRawRow] = []

        for row in rows:
            links = (row.metadata or {}).get("links", []) or []
            company_url = None
            for link in links:
                if "/company/" in link:
                    company_url = link
                    break

            if not company_url:
                enriched_rows.append(row)
                continue

            try:
                await _random_delay()
                await page.goto(company_url)
                await self._guard_supported_domain(page)
                await _random_delay()

                detail = await self._extract_company_detail(page)
                row.metadata["detail"] = detail
                enriched_rows.append(row)

                # 返回搜索结果页
                await page.go_back()
                await _random_delay()
            except Exception:
                enriched_rows.append(row)
                try:
                    await page.go_back()
                    await _random_delay()
                except Exception:
                    pass

        return enriched_rows

    async def _extract_company_detail(self, page) -> Dict[str, object]:
        detail: Dict[str, object] = {}

        company_name = await self._try_get_text(page, LinkedinSelectors.company_name_candidates)
        if company_name:
            detail["company_name"] = company_name

        industry = await self._try_get_text(page, LinkedinSelectors.company_industry_candidates)
        if industry:
            detail["industry"] = industry

        employee_size = await self._try_get_text(page, LinkedinSelectors.company_size_candidates)
        if employee_size:
            detail["employee_size"] = employee_size

        website = await self._try_get_href(page, LinkedinSelectors.company_website_candidates)
        if website:
            detail["website"] = website

        description = await self._try_get_text(page, LinkedinSelectors.company_description_candidates)
        if description:
            detail["description"] = description

        address = await self._try_get_text(page, LinkedinSelectors.company_headquarters_candidates)
        if address:
            detail["address"] = address

        current_url = page.url
        if "/company/" in current_url:
            detail["linkedin_url"] = current_url

        return detail

    async def _try_click_pagination_next(self, page) -> bool:
        for selector in LinkedinSelectors.pagination_next_candidates:
            try:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    btn = locator.first
                    if await btn.is_visible() and await btn.is_enabled():
                        await btn.click()
                        await _random_delay()
                        return True
            except Exception:
                continue
        return False

    async def _try_get_text(self, page, selectors: List[str]) -> Optional[str]:
        locator = await self._find_first(page, selectors)
        if locator is None:
            return None
        try:
            text = (await locator.inner_text()).strip()
            return text if text else None
        except Exception:
            return None

    async def _try_get_href(self, page, selectors: List[str]) -> Optional[str]:
        locator = await self._find_first(page, selectors)
        if locator is None:
            return None
        try:
            href = await locator.get_attribute("href")
            return href.strip() if href else None
        except Exception:
            return None

    def _normalize_link(self, href: Optional[str]) -> Optional[str]:
        if not href:
            return None
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return f"{self.config.base_url}{href}"
        return None

    async def _find_first(self, page, selectors: List[str], locator_mode: bool = False):
        for selector in selectors:
            try:
                locator = page.locator(selector)
                if await locator.count() > 0:
                    return locator if locator_mode else locator.first
            except Exception:
                continue
        return None

    async def _try_auto_login(self, page) -> bool:
        await page.goto(self.config.login_url)
        await self._guard_supported_domain(page)
        username_input = await self._find_first(page, LinkedinSelectors.login_username_input_candidates)
        password_input = await self._find_first(page, LinkedinSelectors.login_password_input_candidates)

        if username_input is None or password_input is None:
            return False

        await username_input.fill(self.config.username or "")
        await password_input.fill(self.config.password or "")

        submit_button = await self._find_first(page, LinkedinSelectors.login_submit_candidates)
        if submit_button is not None:
            await submit_button.click()
        else:
            await password_input.press("Enter")

        await page.wait_for_timeout(3500)
        return await self._is_logged_in(page)

    async def _is_logged_in(self, page) -> bool:
        current_url = (page.url or "").lower()
        if "/checkpoint/" in current_url:
            return False

        for selector in LinkedinSelectors.login_success_candidates:
            try:
                if await page.locator(selector).count() > 0:
                    return True
            except Exception:
                continue

        if "/login" in current_url:
            return False

        username_input = await self._find_first(page, LinkedinSelectors.login_username_input_candidates)
        password_input = await self._find_first(page, LinkedinSelectors.login_password_input_candidates)
        if username_input is not None and password_input is not None:
            return False

        return True

    async def _guard_supported_domain(self, page) -> None:
        current_url = (page.url or "").lower()
        if "linkedin.cn" not in current_url:
            return

        await page.goto(self.config.login_url)
        await page.wait_for_timeout(800)
        current_url = (page.url or "").lower()
        if "linkedin.cn" in current_url:
            raise RuntimeError("当前网络环境会自动跳转到 linkedin.cn，无法使用 linkedin.com 账号，请切换网络后重试")
