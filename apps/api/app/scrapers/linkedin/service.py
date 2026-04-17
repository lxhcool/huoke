from __future__ import annotations

import asyncio
from typing import List, Optional
from urllib.parse import quote_plus

from app.scrapers.linkedin.browser import LinkedinBrowserSession
from app.scrapers.linkedin.config import LinkedinScraperConfig
from app.scrapers.linkedin.models import LinkedinRawRow, LinkedinScrapeBatch
from app.scrapers.linkedin.selectors import LinkedinSelectors
from app.scrapers.linkedin.storage import dump_batch


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

            await session.page.wait_for_timeout(2500)
            snapshot_path = self.config.screenshot_dir / f"{source_type}-results.png"
            await session.page.screenshot(path=str(snapshot_path), full_page=True)
            batch.page_snapshots.append(str(snapshot_path))
            batch.items.extend(await self._extract_rows(session.page, source_type))

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
        max_count = min(count, 20)
        for index in range(max_count):
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
