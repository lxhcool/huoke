from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import settings


@dataclass
class LinkedinScraperConfig:
    base_url: str = "https://www.linkedin.com"
    login_url: str = "https://www.linkedin.com/login"
    storage_state_path: Path = Path("runtime/linkedin/storage-state.json")
    raw_output_dir: Path = Path("runtime/linkedin/raw")
    screenshot_dir: Path = Path("runtime/linkedin/screenshots")
    timeout_ms: int = 30000
    headless: bool = os.getenv("APP_ENV", "development") == "production"
    username: Optional[str] = os.getenv("LINKEDIN_USERNAME") or settings.linkedin_username
    password: Optional[str] = os.getenv("LINKEDIN_PASSWORD") or settings.linkedin_password

    def ensure_dirs(self) -> None:
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def has_credentials(self) -> bool:
        return bool(self.username and self.password)
