from __future__ import annotations

from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from app.scrapers.linkedin.config import LinkedinScraperConfig


class LinkedinBrowserSession:
    def __init__(self, config: LinkedinScraperConfig):
        self.config = config
        self.playwright = None
        self.browser = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self) -> "LinkedinBrowserSession":
        self.config.ensure_dirs()
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.config.headless)

        storage_state = str(self.config.storage_state_path) if self.config.storage_state_path.exists() else None
        self.context = await self.browser.new_context(storage_state=storage_state)
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.config.timeout_ms)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.context is not None:
            await self.context.storage_state(path=str(self.config.storage_state_path))
            await self.context.close()
        if self.browser is not None:
            await self.browser.close()
        if self.playwright is not None:
            await self.playwright.stop()

