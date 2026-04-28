from __future__ import annotations

from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from app.scrapers.joinf.config import JoinfScraperConfig


class JoinfBrowserSession:
    def __init__(self, config: JoinfScraperConfig):
        self.config = config
        self.playwright = None
        self.browser = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self) -> "JoinfBrowserSession":
        import os
        self.config.ensure_dirs()
        self.playwright = await async_playwright().start()

        # Docker/CI 环境需要额外启动参数
        launch_args = []
        if os.getenv("APP_ENV") == "production" or os.getenv("CHROMIUM_FLAGS"):
            launch_args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--no-zygote",
                "--single-process",
                "--disable-extensions",
            ]

        self.browser = await self.playwright.chromium.launch(
            headless=self.config.headless,
            args=launch_args if launch_args else None,
        )

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
