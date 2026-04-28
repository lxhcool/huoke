from __future__ import annotations

import json
from dataclasses import dataclass
from http.cookiejar import Cookie
from pathlib import Path
from typing import Awaitable, Callable, Dict, List

from app.schemas.source_auth import SourceAuthProviderItem, SourceCredentialField
from app.scrapers.joinf.config import JoinfScraperConfig
from app.scrapers.joinf.service import JoinfScraperService
from app.scrapers.linkedin.config import LinkedinScraperConfig
from app.scrapers.linkedin.service import LinkedinScraperService


VerifyHandler = Callable[[Dict[str, str]], Awaitable[Path]]


@dataclass(frozen=True)
class SourceAuthProvider:
    source_name: str
    display_name: str
    task_sources: List[str]
    credential_fields: List[SourceCredentialField]
    verify_handler: VerifyHandler


def _run_joinf_verify_in_thread(username: str, password: str, login_user_id: str | None = None) -> Path:
    """Run Playwright login in a dedicated thread with its own ProactorEventLoop.
    
    uvicorn sets WindowsSelectorEventLoopPolicy globally on Windows, which
    makes asyncio.run() create SelectorEventLoop that cannot spawn subprocesses.
    Playwright needs subprocess support to launch the browser.
    We restore ProactorEventLoopPolicy in this thread so asyncio.run() works.
    """
    import asyncio
    import os
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    user_id_int = None
    if login_user_id:
        try:
            user_id_int = int(login_user_id.strip())
        except (ValueError, TypeError):
            pass

    # ★ 验证登录时强制使用非 headless 模式，让用户可以通过 noVNC 远程操作浏览器
    # 临时设置环境变量，使 JoinfScraperConfig.headless=False
    os.environ["ENABLE_HEADED_VERIFY"] = "1"

    config = JoinfScraperConfig(username=username or None, password=password or None, login_user_id=user_id_int)
    service = JoinfScraperService(config)
    result = asyncio.run(
        service.ensure_login_session(allow_manual=True, interactive_manual=True, manual_timeout_seconds=300)
    )

    # 清理环境变量
    os.environ.pop("ENABLE_HEADED_VERIFY", None)

    # ★ ensure_login_session 内部已自动提取 loginUserId 并保存到 auth-cache
    # 但如果自动提取失败（跨域 localStorage 不可访问），这里用 config 中的 loginUserId 兜底
    auth_cache = config.load_auth_cache()
    if (not auth_cache or not auth_cache.get("login_user_id")) and config.login_user_id:
        storage_data = {}
        try:
            storage_data = json.loads(config.storage_state_path.read_text(encoding="utf-8")) if config.storage_state_path.exists() else {}
        except Exception:
            pass
        cookies = {}
        for cookie in storage_data.get("cookies", []):
            if "joinf.com" in cookie.get("domain", ""):
                cookies[cookie["name"]] = cookie.get("value", "")
        config.save_auth_cache(config.login_user_id, cookies)
        print(f"[SourceAuth] 兜底保存 loginUserId={config.login_user_id} 到 auth-cache")

    return result


async def _verify_joinf(credentials: Dict[str, str]) -> Path:
    import asyncio
    import concurrent.futures

    username = credentials.get("username", "").strip()
    password = credentials.get("password", "").strip()
    login_user_id = credentials.get("login_user_id", "").strip()

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(
            pool,
            _run_joinf_verify_in_thread,
            username,
            password,
            login_user_id,
        )


async def _verify_linkedin(credentials: Dict[str, str]) -> Path:
    username = credentials.get("username", "").strip()
    password = credentials.get("password", "").strip()
    config = LinkedinScraperConfig(username=username or None, password=password or None)
    service = LinkedinScraperService(config)
    storage_state_path = await service.ensure_login_session(
        allow_manual=True,
        interactive_manual=False,
        manual_timeout_seconds=300,
    )
    return Path(storage_state_path)


SOURCE_AUTH_PROVIDERS: Dict[str, SourceAuthProvider] = {
    "joinf": SourceAuthProvider(
        source_name="joinf",
        display_name="Joinf",
        task_sources=["joinf_business", "joinf_customs"],
        credential_fields=[
            SourceCredentialField(name="username", label="账号", input_type="text", required=True),
            SourceCredentialField(name="password", label="密码", input_type="password", required=True),
        ],
        verify_handler=_verify_joinf,
    ),
}


def list_source_auth_providers() -> List[SourceAuthProviderItem]:
    return [
        SourceAuthProviderItem(
            source_name=provider.source_name,
            display_name=provider.display_name,
            task_sources=provider.task_sources,
            credential_fields=provider.credential_fields,
        )
        for provider in SOURCE_AUTH_PROVIDERS.values()
    ]


async def verify_source_auth(source_name: str, credentials: Dict[str, str]) -> Path:
    provider = SOURCE_AUTH_PROVIDERS.get(source_name)
    if provider is None:
        raise ValueError(f"unsupported source auth provider: {source_name}")

    has_any_credential = any((credentials.get(field.name, "").strip() for field in provider.credential_fields))
    if has_any_credential:
        for field in provider.credential_fields:
            if field.required and not credentials.get(field.name, "").strip():
                raise RuntimeError(f"{provider.display_name} 缺少必填凭证字段：{field.label}")

    return await provider.verify_handler(credentials)


def map_task_source_to_provider(task_source: str) -> str | None:
    for source_name, provider in SOURCE_AUTH_PROVIDERS.items():
        if task_source in provider.task_sources:
            return source_name
    return None


# ── Cookie import ──────────────────────────────────────────────

SOURCE_DOMAIN_MAP: Dict[str, str] = {
    "joinf": ".joinf.com",
    "linkedin": ".linkedin.com",
}


def _extract_cookie_from_curl(text: str) -> str:
    """Try to extract the cookie string from a full curl command or raw Cookie header."""
    import re
    # Try -b "cookie_string" or --cookie "cookie_string"
    m = re.search(r'(?:-b|--cookie)\s+"([^"]+)"', text)
    if m:
        return m.group(1)
    # Try -b 'cookie_string'
    m = re.search(r"(?:-b|--cookie)\s+'([^']+)'", text)
    if m:
        return m.group(1)
    # Not a curl command, return as-is
    return text


def _parse_cookie_string(cookie_string: str, domain: str) -> List[Dict]:
    """Parse a raw cookie string (from browser DevTools) into Playwright cookie format."""
    cookies = []
    # Unescape Windows cmd caret escaping (^% -> %)
    raw = cookie_string.replace("^%", "%").replace("^^", "^")
    for part in raw.strip().split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append({
            "name": name,
            "value": value,
            "domain": domain,
            "path": "/",
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        })
    return cookies


def import_source_cookie(source_name: str, cookie_string: str) -> Path:
    """Convert a browser cookie string (or curl command) into a Playwright storage_state.json file."""
    if source_name not in SOURCE_AUTH_PROVIDERS:
        raise ValueError(f"unsupported source auth provider: {source_name}")

    domain = SOURCE_DOMAIN_MAP.get(source_name)
    if not domain:
        raise ValueError(f"no domain mapping for source: {source_name}")

    # If user pasted a full curl command, extract just the cookie part
    extracted = _extract_cookie_from_curl(cookie_string)
    cookies = _parse_cookie_string(extracted, domain)
    if not cookies:
        raise RuntimeError("Cookie 为空，请从浏览器中复制完整的 Cookie 字符串")

    # Determine storage_state_path from config
    if source_name == "joinf":
        config = JoinfScraperConfig()
    elif source_name == "linkedin":
        config = LinkedinScraperConfig()
    else:
        raise ValueError(f"unsupported source: {source_name}")

    config.ensure_dirs()
    storage_state_path = config.storage_state_path

    storage_state = {"cookies": cookies, "origins": []}
    storage_state_path.write_text(json.dumps(storage_state, ensure_ascii=False, indent=2), encoding="utf-8")

    # ★ 同时保存到 auth-cache.json（供 API 客户端直接使用）
    if source_name == "joinf" and hasattr(config, "save_auth_cache"):
        cookie_dict = {c["name"]: c["value"] for c in cookies if c.get("name")}
        # 尝试从 cookie 值中提取 loginUserId
        login_user_id = _extract_login_user_id_from_cookies(cookie_dict)
        if login_user_id:
            config.save_auth_cache(login_user_id, cookie_dict)
            print(f"[SourceAuth] 已保存认证缓存: loginUserId={login_user_id}")

    return storage_state_path


def _extract_login_user_id_from_cookies(cookies: dict) -> int | None:
    """从 cookies 中尝试提取 loginUserId"""
    # 常见的存储 userId 的 cookie 名
    for key in ("userId", "loginUserId", "uid", "user_id", "id", "userInfo", "user_info"):
        value = cookies.get(key)
        if value:
            try:
                num = int(value)
                if num > 1000:
                    return num
            except (ValueError, TypeError):
                pass
            # 可能是 JSON
            try:
                obj = json.loads(value)
                if isinstance(obj, dict):
                    for k in ("id", "userId", "loginUserId", "uid"):
                        if obj.get(k):
                            try:
                                return int(obj[k])
                            except (ValueError, TypeError):
                                pass
            except (json.JSONDecodeError, TypeError):
                pass
    return None
