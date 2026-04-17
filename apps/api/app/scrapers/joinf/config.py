from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import settings


@dataclass
class JoinfScraperConfig:
    base_url: str = "https://cloud.joinf.com"
    login_url: str = "https://cloud.joinf.com"
    storage_state_path: Path = Path("runtime/joinf/storage-state.json")
    raw_output_dir: Path = Path("runtime/joinf/raw")
    screenshot_dir: Path = Path("runtime/joinf/screenshots")
    timeout_ms: int = 30000
    headless: bool = False
    username: Optional[str] = os.getenv("JOINF_USERNAME") or settings.joinf_username
    password: Optional[str] = os.getenv("JOINF_PASSWORD") or settings.joinf_password

    def ensure_dirs(self) -> None:
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def has_credentials(self) -> bool:
        return bool(self.username and self.password)
