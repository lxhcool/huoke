from __future__ import annotations

import json
from dataclasses import dataclass
from http.cookiejar import Cookie
from pathlib import Path
from typing import Awaitable, Callable, Dict, List

from app.schemas.source_auth import SourceAuthProviderItem, SourceCredentialField
from app.scrapers.joinf.config import JoinfScraperConfig
from app.scrapers.linkedin.config import LinkedinScraperConfig


VerifyHandler = Callable[[Dict[str, str]], Awaitable[Path]]


@dataclass(frozen=True)
class SourceAuthProvider:
    source_name: str
    display_name: str
    task_sources: List[str]
    credential_fields: List[SourceCredentialField]
    verify_handler: VerifyHandler


async def _verify_joinf(credentials: Dict[str, str]) -> Path:
    """Joinf 验证登录 — 优先用纯 HTTP CAS SSO 登录，失败后弹出浏览器让用户手动完成。

    流程：
    1. 尝试 HTTP CAS SSO 直接登录（用 api_client 的 _try_http_login）
    2. 登录成功后调 API 获取 loginUserId
    3. 如果失败（验证码等），弹出有头浏览器让用户手动登录，等待完成后保存会话
    """
    from app.scrapers.joinf.api_client import JoinfApiClient

    username = credentials.get("username", "").strip()
    password = credentials.get("password", "").strip()
    login_user_id_str = credentials.get("login_user_id", "").strip()
    user_id_int = None
    if login_user_id_str:
        try:
            user_id_int = int(login_user_id_str)
        except (ValueError, TypeError):
            pass

    config = JoinfScraperConfig(username=username or None, password=password or None, login_user_id=user_id_int)
    config.ensure_dirs()

    # 策略1：纯 HTTP CAS SSO 登录
    if config.has_credentials():
        print(f"[SourceAuth] 尝试纯 HTTP CAS SSO 登录: username={username}")
        api_client = JoinfApiClient(config=config)

        try:
            # 调用 CAS SSO 登录流程
            await api_client._try_http_login()

            if api_client._cookies:
                # ★ 登录成功后，尝试从 API 获取 loginUserId
                if not api_client._login_user_id:
                    await api_client._fetch_user_id_from_api()
                if not api_client._login_user_id and config.login_user_id:
                    api_client._login_user_id = config.login_user_id

                # 验证 cookies 是否有效
                is_valid = await api_client._test_cookies()
                if is_valid:
                    # 保存认证缓存
                    api_client.config.save_auth_cache(
                        api_client._login_user_id or 0,
                        api_client._cookies,
                    )
                    # 同时保存到 storage-state.json（供 browser_proxy 等使用）
                    storage_cookies = []
                    for name, value in api_client._cookies.items():
                        storage_cookies.append({
                            "name": name,
                            "value": value,
                            "domain": ".joinf.com",
                            "path": "/",
                            "httpOnly": False,
                            "secure": True,
                            "sameSite": "Lax",
                        })
                    storage_state = {"cookies": storage_cookies, "origins": []}
                    config.storage_state_path.write_text(
                        json.dumps(storage_state, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print(f"[SourceAuth] HTTP CAS SSO 登录成功: loginUserId={api_client._login_user_id}, cookies={len(api_client._cookies)} 个")
                    return config.storage_state_path
                else:
                    print("[SourceAuth] CAS SSO 登录获取了 cookies 但验证失败（可能需要验证码）")
            else:
                print("[SourceAuth] CAS SSO 登录未能获取 cookies（可能需要验证码）")
        except Exception as e:
            print(f"[SourceAuth] HTTP CAS SSO 登录异常: {e}")

    # 策略2：检查是否已有有效缓存
    auth_cache = config.load_auth_cache()
    if auth_cache and auth_cache.get("cookies") and auth_cache.get("login_user_id"):
        api_client = JoinfApiClient(config=config)
        api_client._cookies = auth_cache["cookies"]
        api_client._login_user_id = auth_cache["login_user_id"]
        if await api_client._test_cookies():
            print(f"[SourceAuth] 已有有效缓存: loginUserId={auth_cache['login_user_id']}")
            return config.storage_state_path

    # 策略3：弹出浏览器让用户手动登录（有头模式）
    print("[SourceAuth] 自动登录失败，弹出浏览器请手动完成登录...")
    try:
        from app.scrapers.joinf.browser import JoinfBrowserSession

        # 验证登录时强制有头模式，让用户能看到浏览器
        verify_config = JoinfScraperConfig(
            username=username or None,
            password=password or None,
            login_user_id=user_id_int,
            headless=False,
        )
        verify_config.ensure_dirs()

        async with JoinfBrowserSession(verify_config) as session:
            await session.page.goto("https://cloud.joinf.com", wait_until="domcontentloaded")

            # 如果有账号密码，尝试自动填入
            if username and password:
                try:
                    await session.page.fill('input[name="username"], input[type="text"]', username, timeout=3000)
                    await session.page.fill('input[name="password"], input[type="password"]', password, timeout=3000)
                    submit_btn = session.page.locator('button[type="submit"], input[type="submit"]')
                    if await submit_btn.count() > 0:
                        await submit_btn.first.click()
                except Exception:
                    pass  # 自动填入失败没关系，用户可以手动操作

            # 等待用户手动完成登录（最多 4 分钟）
            print("[SourceAuth] 等待用户在浏览器中完成登录（最多 4 分钟）...")
            try:
                await session.page.wait_for_url(
                    "**/trade.joinf.com/**",
                    timeout=240_000,
                )
            except Exception:
                # 也可能跳转到其他已登录页面
                current_url = session.page.url
                if "joinf.com" not in current_url or "login" in current_url:
                    raise RuntimeError("浏览器登录超时或未成功，请重试")

            # 登录成功，保存 storage state（在 __aexit__ 中自动保存）
            print("[SourceAuth] 浏览器登录成功，已保存登录状态")
            return verify_config.storage_state_path

    except Exception as e:
        raise RuntimeError(f"Joinf 浏览器登录失败：{e}。请重新点击「验证登录」，在弹出的浏览器中手动输入账号密码完成登录")


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
        display_name="外贸数据",
        task_sources=["joinf_business", "joinf_customs"],
        credential_fields=[
            SourceCredentialField(name="username", label="账号", input_type="text", required=True),
            SourceCredentialField(name="password", label="密码", input_type="password", required=True),
            SourceCredentialField(name="login_user_id", label="用户ID（可选）", input_type="text", required=False),
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
