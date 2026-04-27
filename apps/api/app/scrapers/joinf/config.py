from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import settings


@dataclass
class JoinfScraperConfig:
    base_url: str = "https://data.joinf.com/searchResult"
    login_url: str = "https://cloud.joinf.com"
    storage_state_path: Path = Path("runtime/joinf/storage-state.json")
    auth_cache_path: Path = Path("runtime/joinf/auth-cache.json")
    raw_output_dir: Path = Path("runtime/joinf/raw")
    screenshot_dir: Path = Path("runtime/joinf/screenshots")
    timeout_ms: int = 60000
    headless: bool = os.getenv("APP_ENV", "development") == "production"
    username: Optional[str] = os.getenv("JOINF_USERNAME") or settings.joinf_username
    password: Optional[str] = os.getenv("JOINF_PASSWORD") or settings.joinf_password
    login_user_id: Optional[int] = None

    def __post_init__(self):
        # 支持从环境变量或 settings 直接配置 loginUserId
        if self.login_user_id is None:
            env_val = os.getenv("JOINF_LOGIN_USER_ID")
            if env_val:
                try:
                    self.login_user_id = int(env_val)
                except (ValueError, TypeError):
                    pass
        if self.login_user_id is None and settings.joinf_login_user_id:
            self.login_user_id = settings.joinf_login_user_id

    def ensure_dirs(self) -> None:
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def has_credentials(self) -> bool:
        return bool(self.username and self.password)

    def save_auth_cache(self, login_user_id: int, cookies: dict | None = None) -> None:
        """保存认证缓存（loginUserId + cookies），供 API 客户端直接使用"""
        self.ensure_dirs()
        cache = {"login_user_id": login_user_id}
        if cookies:
            cache["cookies"] = cookies
        self.auth_cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_auth_cache(self) -> dict | None:
        """加载认证缓存"""
        if not self.auth_cache_path.exists():
            return None
        try:
            return json.loads(self.auth_cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None
