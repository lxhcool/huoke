from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

from app.scrapers.joinf.browser import JoinfBrowserSession
from app.scrapers.joinf.config import JoinfScraperConfig
from app.scrapers.joinf.models import JoinfRawRow, JoinfScrapeBatch
from app.scrapers.joinf.selectors import JoinfSelectors
from app.scrapers.joinf.storage import dump_batch


class JoinfScraperService:
    def __init__(self, config: Optional[JoinfScraperConfig] = None):
        self.config = config or JoinfScraperConfig()

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
                if interactive_manual:
                    print("请在打开的浏览器中手动完成 Joinf 登录，完成后回到终端按回车继续。")
                    await asyncio.to_thread(input)
                    logged_in = await self._is_logged_in(session.page)
                else:
                    logged_in = await self._wait_for_manual_login(session.page, manual_timeout_seconds)

            if not logged_in:
                raise RuntimeError("Joinf 登录失败，请检查账号密码或手动登录是否在超时时间内完成")

            await session.page.goto(self.config.base_url)
            if not await self._is_logged_in(session.page):
                raise RuntimeError("Joinf 登录已完成，但未进入可抓取业务页，请确认登录后停留在业务系统页面")

            await session.page.screenshot(path=str(self.config.screenshot_dir / "login-success.png"), full_page=True)
        return self.config.storage_state_path

    async def _wait_for_manual_login(self, page, timeout_seconds: int) -> bool:
        for _ in range(max(1, timeout_seconds)):
            if await self._is_logged_in(page):
                return True
            await page.wait_for_timeout(1000)
        return await self._is_logged_in(page)

    async def scrape_business_data(self, keyword: str, country: Optional[str] = None) -> Path:
        return await self._scrape_source("business", keyword, country)

    async def scrape_customs_data(self, keyword: str, country: Optional[str] = None) -> Path:
        return await self._scrape_source("customs", keyword, country)

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
                    raise RuntimeError("Joinf 当前未登录，请先在前端执行“验证登录”并确保登录成功")

            print("Joinf 已进入人工抓取模式：请手动打开目标结果页，系统将自动识别表格并开始抓取。")
            table_ready = await self._wait_for_table_rows(session.page, wait_seconds=wait_seconds)
            if not table_ready:
                raise RuntimeError("人工抓取超时：未检测到结果表格，请重试并先手动进入结果页")

            snapshot_path = self.config.screenshot_dir / f"{source_type}-manual-results.png"
            await session.page.screenshot(path=str(snapshot_path), full_page=True)
            batch.page_snapshots.append(str(snapshot_path))
            batch.items.extend(await self._extract_rows(session.page, source_type))

        return dump_batch(batch, self.config.raw_output_dir)

    async def _scrape_source(self, source_type: str, keyword: str, country: Optional[str]) -> Path:
        batch = JoinfScrapeBatch(source_type=source_type, keyword=keyword, country=country)

        async with JoinfBrowserSession(self.config) as session:
            assert session.page is not None
            await session.page.goto(self.config.base_url)

            if not await self._is_logged_in(session.page):
                if self.config.has_credentials() and await self._try_auto_login(session.page):
                    await session.page.goto(self.config.base_url)
                else:
                    raise RuntimeError("Joinf 当前未登录，请先在前端执行“验证登录”并确保登录成功")

            await self._enter_data_source_page(session.page, source_type, keyword, country)
            await self._apply_filters(session.page, keyword, country)
            snapshot_path = self.config.screenshot_dir / f"{source_type}-results.png"
            await session.page.screenshot(path=str(snapshot_path), full_page=True)
            batch.page_snapshots.append(str(snapshot_path))
            batch.items.extend(await self._extract_rows(session.page, source_type))

        return dump_batch(batch, self.config.raw_output_dir)

    async def _enter_data_source_page(self, page, source_type: str, keyword: str, country: Optional[str]) -> None:
        entered_global_buyers = await self._try_enter_global_buyers_page(page, source_type, keyword, country)
        if entered_global_buyers:
            return

        await self._enter_legacy_data_source_page(page, source_type)

    async def _enter_legacy_data_source_page(self, page, source_type: str) -> None:
        await self._click_first(page, JoinfSelectors.data_marketing_nav_candidates)
        if source_type == "business":
            await self._click_first(page, JoinfSelectors.business_data_nav_candidates)
        else:
            await self._click_first(page, JoinfSelectors.customs_data_nav_candidates)

    async def _try_enter_global_buyers_page(self, page, source_type: str, keyword: str, country: Optional[str]) -> bool:
        if await self._try_click_first(page, JoinfSelectors.global_buyers_direct_nav_candidates):
            await self._fill_custom_info(page, keyword, country)
            await self._try_switch_source_tab(page, source_type)
            return True

        if not await self._try_click_first(page, JoinfSelectors.data_marketing_nav_candidates):
            return False

        if not await self._try_click_first(page, JoinfSelectors.global_buyers_nav_candidates):
            return False

        await self._fill_custom_info(page, keyword, country)
        await self._try_switch_source_tab(page, source_type)
        return True

    async def _try_switch_source_tab(self, page, source_type: str) -> None:
        if source_type == "business":
            await self._try_click_first(page, JoinfSelectors.business_data_nav_candidates)
            return
        await self._try_click_first(page, JoinfSelectors.customs_data_nav_candidates)

    async def _fill_custom_info(self, page, keyword: str, country: Optional[str]) -> None:
        await self._try_click_first(page, JoinfSelectors.custom_info_entry_candidates, wait_ms=800)

        keyword_input = await self._find_first(page, JoinfSelectors.custom_keyword_input_candidates)
        if keyword_input is not None:
            await self._try_fill_with_fallback(
                page,
                keyword_input,
                keyword,
                JoinfSelectors.custom_dropdown_input_candidates,
            )

        if country:
            country_input = await self._find_first(page, JoinfSelectors.custom_country_input_candidates)
            if country_input is not None:
                await self._try_fill_with_fallback(
                    page,
                    country_input,
                    country,
                    JoinfSelectors.custom_dropdown_input_candidates,
                )

        if await self._try_click_first(page, JoinfSelectors.custom_info_submit_candidates, wait_ms=1500):
            return

        if keyword_input is not None:
            await keyword_input.press("Enter")
            await page.wait_for_timeout(1200)

    async def _apply_filters(self, page, keyword: str, country: Optional[str]) -> None:
        search_input = await self._find_first(page, JoinfSelectors.search_input_candidates)
        if search_input is not None:
            await self._try_fill_with_fallback(
                page,
                search_input,
                keyword,
                JoinfSelectors.search_dropdown_input_candidates,
            )

        if country:
            country_input = await self._find_first(page, JoinfSelectors.country_filter_candidates)
            if country_input is not None:
                await self._try_fill_with_fallback(
                    page,
                    country_input,
                    country,
                    JoinfSelectors.country_dropdown_input_candidates,
                )

        await page.wait_for_timeout(1500)

    async def _extract_rows(self, page, source_type: str) -> List[JoinfRawRow]:
        rows: List[JoinfRawRow] = []
        row_locator = await self._find_first(page, JoinfSelectors.table_row_candidates, locator_mode=True)

        if row_locator is None:
            return rows

        count = await row_locator.count()
        for index in range(count):
            row = row_locator.nth(index)
            cell_locator = row.locator("td")
            cell_count = await cell_locator.count()
            cells: List[str] = []
            links: List[str] = []

            if cell_count > 0:
                for cell_index in range(cell_count):
                    cell = cell_locator.nth(cell_index)
                    cell_text = (await cell.inner_text()).strip()
                    if cell_text:
                        cells.append(cell_text)
                    link_locator = cell.locator("a")
                    link_count = await link_locator.count()
                    for link_index in range(link_count):
                        href = await link_locator.nth(link_index).get_attribute("href")
                        if href:
                            links.append(href)
            else:
                text = await row.inner_text()
                cells = [cell.strip() for cell in text.split("\n") if cell.strip()]

            rows.append(
                JoinfRawRow(
                    source_type=source_type,
                    page_url=page.url,
                    row_index=index,
                    cells=cells,
                    metadata={"links": links},
                )
            )

        return rows

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
        if "login" in current_url:
            return False

        has_visible_login_inputs = await self._has_visible_selector(page, JoinfSelectors.login_username_input_candidates) and await self._has_visible_selector(
            page, JoinfSelectors.login_password_input_candidates
        )
        if has_visible_login_inputs:
            return False

        if await self._has_visible_selector(page, JoinfSelectors.login_success_candidates):
            return True

        if await self._has_visible_selector(page, JoinfSelectors.login_page_marker_candidates):
            return False

        return True

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
        for _ in range(max(1, wait_seconds)):
            row_locator = await self._find_first(page, JoinfSelectors.table_row_candidates, locator_mode=True)
            if row_locator is not None:
                try:
                    if await row_locator.count() > 0:
                        return True
                except Exception:
                    pass
            await page.wait_for_timeout(1000)
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
