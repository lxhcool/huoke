"""
Joinf API 直接调用客户端 — 绕过浏览器，直接调用 Joinf 后端 API 获取商业数据。

认证策略（按优先级）：
1. auth-cache.json — 浏览器登录后自动保存的 loginUserId + cookies
2. storage-state.json — Playwright 浏览器登录态
3. 直接 HTTP 登录 — 用用户名密码直接调 API 登录（无需浏览器）
4. config.login_user_id — 手动配置
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.scrapers.joinf.config import JoinfScraperConfig
from app.scrapers.joinf.models import JoinfRawRow, JoinfScrapeBatch
from app.scrapers.joinf.storage import dump_batch
from app.services.ai_extractor import AIExtractor

logger = logging.getLogger("joinf_api")

# 全局取消信号复用 service 的
from app.scrapers.joinf.service import is_cancelled, clear_cancel


class JoinfApiClient:
    """直接调用 Joinf 后端 API 的客户端，无需浏览器。"""

    SEARCH_BUSINESS_URL = "https://data.joinf.com/api/bs/searchBusiness"
    # 常见的 Joinf 登录 API 端点（按可能性排序）
    LOGIN_API_URLS = [
        "https://cloud.joinf.com/api/user/login",
        "https://cloud.joinf.com/api/login",
        "https://sso.joinf.com/api/user/login",
        "https://sso.joinf.com/api/login",
        "https://data.joinf.com/api/user/login",
        "https://data.joinf.com/api/bs/login",
        "https://cloud.joinf.com/user/login",
    ]
    USER_INFO_API_URLS = [
        "https://data.joinf.com/api/user/info",
        "https://data.joinf.com/api/bs/getUserInfo",
        "https://data.joinf.com/api/bs/getLoginUser",
        "https://cloud.joinf.com/api/user/info",
    ]

    def __init__(self, config: Optional[JoinfScraperConfig] = None, ai_config: Optional[Dict] = None):
        self.config = config or JoinfScraperConfig()
        self._ai_config = ai_config
        self.ai: Optional[AIExtractor] = None
        self._login_user_id: Optional[int] = self.config.login_user_id
        self._cookies: Dict[str, str] = {}

        if ai_config and ai_config.get("api_key"):
            try:
                self.ai = AIExtractor(
                    api_key=ai_config["api_key"],
                    base_url=ai_config.get("base_url", "https://api.siliconflow.cn/v1"),
                    model=ai_config.get("model", "Qwen/Qwen3-8B"),
                )
                logger.info(f"[JoinfApi] AIExtractor 已初始化: model={self.ai.model}")
            except Exception as e:
                logger.warning(f"[JoinfApi] AIExtractor 初始化失败: {e}")

    # ================================================================
    # 认证（多策略）
    # ================================================================

    async def _ensure_auth(self) -> int:
        """确保认证信息就绪，返回 loginUserId。

        策略优先级：
        1. auth-cache.json（浏览器登录后自动保存）
        2. config.login_user_id（手动配置）
        3. 直接 HTTP 登录（用用户名密码）
        4. 从 storage-state.json 提取
        5. 调 API 获取
        """
        # 如果已经有 loginUserId 和 cookies，直接返回
        if self._login_user_id and self._cookies:
            return self._login_user_id

        # 策略1：从 auth-cache.json 读取
        if not self._cookies or not self._login_user_id:
            self._load_auth_cache()

        # 策略2：config 手动配置
        if not self._login_user_id and self.config.login_user_id:
            self._login_user_id = self.config.login_user_id
            logger.info(f"[JoinfApi] 使用配置的 loginUserId: {self._login_user_id}")

        # 策略3：直接 HTTP 登录（用用户名密码，无需浏览器）
        if (not self._login_user_id or not self._cookies) and self.config.has_credentials():
            await self._try_http_login()

        # 策略4：从 Playwright storage-state.json 提取
        if not self._cookies or not self._login_user_id:
            self._load_storage_state()

        # 策略5：从 cookies 调 API 获取 loginUserId
        if self._cookies and not self._login_user_id:
            await self._fetch_user_id_from_api()

        # 最终校验
        if not self._cookies:
            raise RuntimeError(
                "Joinf 认证失败：无法获取 cookies。\n"
                "请通过以下任一方式提供认证：\n"
                "1. 在前端点击「验证登录」完成浏览器登录\n"
                "2. 在前端点击「导入Cookie」粘贴浏览器 Cookie\n"
                "3. 配置 JOINF_USERNAME / JOINF_PASSWORD 环境变量"
            )

        if not self._login_user_id:
            raise RuntimeError(
                "Joinf 认证失败：无法获取 loginUserId。\n"
                "请在环境变量中设置 JOINF_LOGIN_USER_ID 或在前端完成一次浏览器登录"
            )

        # 保存认证缓存（下次无需重新认证）
        self.config.save_auth_cache(self._login_user_id, self._cookies)
        logger.info(f"[JoinfApi] 认证成功: loginUserId={self._login_user_id}, cookies={len(self._cookies)} 个")
        return self._login_user_id

    async def _validate_and_refresh_auth(self) -> int:
        """确保认证信息就绪，返回 loginUserId。
        
        不做额外验证请求，直接用搜索请求本身来检测是否过期。
        401 的处理在 search_business 的请求循环中进行。
        """
        return await self._ensure_auth()

    async def _refresh_session(self) -> None:
        """当 cookies 过期时，尝试重新获取有效 session
        
        策略优先级：
        1. 从 storage-state.json 重新加载（浏览器验证登录后更新的）
        2. 从 auth-cache.json 重新加载（可能已更新）
        3. 用 TGC/SSO 刷新
        4. 用用户名密码 CAS SSO 登录
        """
        # 策略1：重新从 storage-state.json 加载（浏览器验证登录会更新此文件）
        old_cookies = dict(self._cookies)
        self._cookies = {}
        self._login_user_id = None
        self._load_storage_state()
        if self._cookies and self._cookies != old_cookies:
            logger.info("[JoinfApi] 从 storage-state.json 重新加载了 cookies，验证是否有效")
            # 验证新 cookies
            if await self._test_cookies():
                self.config.save_auth_cache(self._login_user_id or 0, self._cookies)
                logger.info("[JoinfApi] storage-state.json 重新加载成功")
                return
            else:
                logger.warning("[JoinfApi] storage-state.json 的 cookies 也已过期")

        # 策略2：重新从 auth-cache.json 加载
        self._cookies = {}
        self._login_user_id = None
        self._load_auth_cache()
        if self._cookies and self._cookies != old_cookies:
            logger.info("[JoinfApi] 从 auth-cache.json 重新加载了 cookies，验证是否有效")
            if await self._test_cookies():
                return
            else:
                logger.warning("[JoinfApi] auth-cache.json 的 cookies 也已过期")

        # 策略3：用 TGC 刷新
        tgc = self._cookies.get("TGC") or old_cookies.get("TGC")
        if tgc:
            logger.info("[JoinfApi] 尝试用 TGC 刷新 session...")
            if await self._try_tgc_refresh(tgc):
                return

        # 策略4：用用户名密码 CAS SSO 登录
        if self.config.has_credentials():
            logger.info("[JoinfApi] 尝试用用户名密码重新登录...")
            self._cookies = {}
            self._login_user_id = self.config.login_user_id  # 保留 loginUserId
            await self._try_http_login()
            if self._cookies:
                if not self._login_user_id:
                    self._login_user_id = self.config.login_user_id
                self.config.save_auth_cache(self._login_user_id or 0, self._cookies)
                logger.info(f"[JoinfApi] 重新登录成功: loginUserId={self._login_user_id}, cookies={len(self._cookies)} 个")
                return
            else:
                logger.warning("[JoinfApi] CAS SSO 登录未能获取 cookies（可能有验证码）")

        raise RuntimeError(
            "Joinf session 已过期且无法自动刷新。\n"
            "请在前端重新点击「验证登录」获取新的认证信息"
        )

    async def _test_cookies(self) -> bool:
        """测试当前 cookies 是否有效"""
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            cookies=self._cookies,
            headers=self._get_headers(),
            verify=False,
        ) as client:
            try:
                payload = self._build_search_payload(
                    keyword="test", user_id=self._login_user_id or 0,
                    page_num=1, page_size=1,
                )
                resp = await client.post(self.SEARCH_BUSINESS_URL, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("code") != 401:
                        return True
                return False
            except Exception:
                return False

    async def _try_tgc_refresh(self, tgc: str) -> bool:
        """用 TGC 尝试刷新 session，成功返回 True"""
        sso_url = "https://cloud.joinf.com/login"
        service_url = "https://data.joinf.com/api/bs/searchBusiness"
        
        cookies_with_tgc = dict(self._cookies)
        cookies_with_tgc["TGC"] = tgc

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            cookies=cookies_with_tgc,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            verify=False,
        ) as client:
            try:
                resp = await client.get(
                    sso_url,
                    params={"service": service_url},
                    follow_redirects=False,
                )
                
                location = resp.headers.get("location", "")
                if "ticket=" in location:
                    ticket_resp = await client.get(location, follow_redirects=False)
                    for cookie_name, cookie_value in ticket_resp.cookies.items():
                        self._cookies[cookie_name] = cookie_value
                    for header_val in ticket_resp.headers.get_list("set-cookie"):
                        parts = header_val.split(";")[0]
                        if "=" in parts:
                            name, _, value = parts.partition("=")
                            self._cookies[name.strip()] = value.strip()
                    
                    logger.info("[JoinfApi] TGC 刷新 session 成功")
                    self.config.save_auth_cache(self._login_user_id or 0, self._cookies)
                    return True
                    
                logger.warning(f"[JoinfApi] TGC 刷新失败，SSO 返回 status={resp.status_code}, location={location}")
                return False
                
            except Exception as e:
                logger.warning(f"[JoinfApi] TGC 刷新异常: {e}")
                return False

    def _load_auth_cache(self) -> None:
        """从 auth-cache.json 加载认证缓存"""
        cache = self.config.load_auth_cache()
        if not cache:
            return

        if cache.get("login_user_id") and not self._login_user_id:
            self._login_user_id = int(cache["login_user_id"])
            logger.info(f"[JoinfApi] 从 auth-cache 加载 loginUserId: {self._login_user_id}")

        if cache.get("cookies") and not self._cookies:
            self._cookies = cache["cookies"]
            logger.info(f"[JoinfApi] 从 auth-cache 加载 {len(self._cookies)} 个 cookies")

    async def _try_http_login(self) -> None:
        """尝试直接 HTTP 登录（无需浏览器）
        
        Joinf 使用 CAS SSO 登录，流程：
        1. GET /login → 获取 LT (login ticket) 和 JSESSIONID
        2. POST /login → 提交用户名密码 + LT → 获取 TGC
        3. 用 TGC 访问目标 service → 获取 session cookies
        """
        if not self.config.has_credentials():
            return

        username = self.config.username
        password = self.config.password
        logger.info(f"[JoinfApi] 尝试 CAS SSO 直接登录: username={username}")

        sso_base = "https://cloud.joinf.com"
        service_url = "https://data.joinf.com/api/bs/searchBusiness"
        login_url = f"{sso_base}/login"

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            verify=False,
        ) as client:
            # Step 1: 访问登录页，获取 LT 和 JSESSIONID
            try:
                resp1 = await client.get(login_url, params={"service": service_url})
                html = resp1.text
                
                # 提取 LT（login ticket）
                import re as _re
                lt_match = _re.search(r'name="lt"\s+value="([^"]+)"', html)
                if not lt_match:
                    lt_match = _re.search(r'name="lt"\s*value="([^"]*)"', html)
                if not lt_match:
                    # 尝试其他模式
                    lt_match = _re.search(r'lt\s*=\s*["\']([^"\']+)["\']', html)
                
                lt = lt_match.group(1) if lt_match else ""
                
                # 提取 execution（有些 CAS 实现需要）
                execution_match = _re.search(r'name="execution"\s+value="([^"]+)"', html)
                execution = execution_match.group(1) if execution_match else ""
                
                # 收集 Step 1 的 cookies（JSESSIONID 等）
                step1_cookies = {}
                for cookie_name, cookie_value in resp1.cookies.items():
                    step1_cookies[cookie_name] = cookie_value
                    self._cookies[cookie_name] = cookie_value
                for header_val in resp1.headers.get_list("set-cookie"):
                    parts = header_val.split(";")[0]
                    if "=" in parts:
                        name, _, value = parts.partition("=")
                        step1_cookies[name.strip()] = value.strip()
                        self._cookies[name.strip()] = value.strip()

                logger.info(f"[JoinfApi] SSO 登录页: lt={'已获取' if lt else '未获取'}, cookies={len(step1_cookies)} 个")

            except Exception as e:
                logger.warning(f"[JoinfApi] 获取 SSO 登录页失败: {e}")
                return

            # Step 2: POST 登录
            try:
                login_data = {
                    "username": username,
                    "password": password,
                    "lt": lt,
                    "execution": execution,
                    "_eventId": "submit",
                    "submit": "登录",
                }
                
                resp2 = await client.post(
                    login_url,
                    data=login_data,
                    params={"service": service_url},
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": login_url,
                        "Origin": sso_base,
                    },
                    follow_redirects=False,
                )

                # 收集 TGC cookie
                for cookie_name, cookie_value in resp2.cookies.items():
                    self._cookies[cookie_name] = cookie_value
                for header_val in resp2.headers.get_list("set-cookie"):
                    parts = header_val.split(";")[0]
                    if "=" in parts:
                        name, _, value = parts.partition("=")
                        self._cookies[name.strip()] = value.strip()

                # CAS 登录成功通常返回 302 重定向到 service?ticket=xxx
                location = resp2.headers.get("location", "")
                if "ticket=" in location:
                    logger.info(f"[JoinfApi] SSO 登录成功，获取到 ticket")
                    
                    # Step 3: 用 ticket 换 session
                    resp3 = await client.get(location, follow_redirects=False)
                    for cookie_name, cookie_value in resp3.cookies.items():
                        self._cookies[cookie_name] = cookie_value
                    for header_val in resp3.headers.get_list("set-cookie"):
                        parts = header_val.split(";")[0]
                        if "=" in parts:
                            name, _, value = parts.partition("=")
                            self._cookies[name.strip()] = value.strip()
                    
                    # 如果有 loginUserId 就提取
                    if not self._login_user_id:
                        self._login_user_id = self.config.login_user_id
                    
                    logger.info(f"[JoinfApi] CAS SSO 登录成功: loginUserId={self._login_user_id}, cookies={len(self._cookies)} 个")
                    return
                    
                elif resp2.status_code == 200:
                    # 可能登录失败（密码错误等）
                    logger.warning(f"[JoinfApi] SSO 登录可能失败，status=200，页面未重定向")
                else:
                    logger.warning(f"[JoinfApi] SSO 登录返回 status={resp2.status_code}, location={location}")

            except Exception as e:
                logger.warning(f"[JoinfApi] SSO 登录 POST 失败: {e}")
                return

        logger.warning("[JoinfApi] CAS SSO 直接登录未成功，将尝试其他认证方式")

    def _extract_user_id_from_response(self, data: Any) -> None:
        """从 API 响应中提取 loginUserId"""
        if self._login_user_id:
            return

        if not isinstance(data, dict):
            return

        # 检查 data 字段
        inner = data.get("data", data)
        if isinstance(inner, dict):
            for key in ("id", "userId", "loginUserId", "uid", "user_id"):
                if key in inner and inner[key]:
                    try:
                        self._login_user_id = int(inner[key])
                        return
                    except (ValueError, TypeError):
                        continue
        # 检查顶层
        for key in ("id", "userId", "loginUserId", "uid", "user_id"):
            if key in data and data[key]:
                try:
                    self._login_user_id = int(data[key])
                    return
                except (ValueError, TypeError):
                    continue

    def _load_storage_state(self) -> None:
        """从 Playwright storage-state.json 提取 cookies 和 loginUserId"""
        path = self.config.storage_state_path
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[JoinfApi] 读取 storage-state.json 失败: {e}")
            return

        # 提取 cookies
        if not self._cookies:
            for cookie in data.get("cookies", []):
                domain = cookie.get("domain", "")
                if "joinf.com" in domain:
                    name = cookie.get("name", "")
                    value = cookie.get("value", "")
                    if name:
                        self._cookies[name] = value

        # 从 localStorage 中提取 loginUserId
        # ★ Joinf 实际存储方式：key 就是 userId（如 "404508": "show"），也检查 value
        if not self._login_user_id:
            for origin in data.get("origins", []):
                origin_str = origin.get("origin", "")
                if "joinf.com" not in origin_str:
                    continue
                for item in origin.get("localStorage", []):
                    name = item.get("name", "")
                    value = item.get("value", "")
                    # ★ 策略1：key 本身就是数字（Joinf 实际方式）
                    if name and re.match(r"^\d{4,10}$", name):
                        try:
                            num = int(name)
                            if num > 1000:
                                self._login_user_id = num
                                break
                        except (ValueError, TypeError):
                            pass
                    # 策略2：value 是数字或 JSON 包含 id
                    if value and not self._login_user_id:
                        self._try_extract_user_id(value)
                if self._login_user_id:
                    break

        logger.info(
            f"[JoinfApi] storage-state: cookies={len(self._cookies)} 个, "
            f"loginUserId={'已获取(' + str(self._login_user_id) + ')' if self._login_user_id else '未获取'}"
        )

    async def _fetch_user_id_from_api(self) -> None:
        """用现有 cookies 调 API 获取 loginUserId"""
        if self._login_user_id:
            return

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            cookies=self._cookies,
            headers=self._get_headers(),
            verify=False,
        ) as client:
            for url in self.USER_INFO_API_URLS:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        self._extract_user_id_from_response(data)
                        if self._login_user_id:
                            logger.info(f"[JoinfApi] 从 API 获取 loginUserId: {self._login_user_id} (url={url})")
                            return
                except Exception:
                    continue

    def _try_extract_user_id(self, value: str) -> None:
        """尝试从字符串中提取 userId"""
        if self._login_user_id is not None:
            return
        # 直接是数字
        try:
            num = int(value)
            if num > 1000:  # userId 通常大于 1000
                self._login_user_id = num
                return
        except (ValueError, TypeError):
            pass
        # 可能是 JSON
        try:
            obj = json.loads(value) if isinstance(value, str) else value
            if isinstance(obj, dict):
                for key in ("id", "userId", "loginUserId", "uid", "user_id"):
                    if key in obj and obj[key]:
                        try:
                            num = int(obj[key])
                            if num > 1000:
                                self._login_user_id = num
                                return
                        except (ValueError, TypeError):
                            continue
        except (json.JSONDecodeError, TypeError):
            pass

    def _get_headers(self) -> Dict[str, str]:
        """构建请求头"""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://data.joinf.com",
            "Referer": "https://data.joinf.com/searchResult",
        }

    async def _handle_401_and_retry(
        self, keyword: str, country: Optional[str], user_id: int,
        page_num: int, page_size: int, job_id: int
    ) -> Optional[Dict]:
        """处理 401，刷新认证并重试，返回新的响应 data 或 None"""
        try:
            await self._refresh_session()
            user_id = self._login_user_id or user_id
            retry_payload = self._build_search_payload(
                keyword=keyword, user_id=user_id,
                page_num=page_num, page_size=page_size, country=country,
            )
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                follow_redirects=True,
                cookies=self._cookies,
                headers=self._get_headers(),
                verify=False,
            ) as retry_client:
                resp = await retry_client.post(self.SEARCH_BUSINESS_URL, json=retry_payload)
                logger.info(f"[JoinfApi] 重试响应: status={resp.status_code}, page={page_num}")
                resp.raise_for_status()
                data = resp.json()
                # 检查是否还是 401
                if isinstance(data, dict) and data.get("code") == 401:
                    logger.error("[JoinfApi] 刷新认证后仍返回 401，认证彻底失败")
                    return None
                logger.info(f"[JoinfApi] 重试成功 keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
                return data
        except Exception as retry_err:
            logger.error(f"[JoinfApi] 刷新认证后重试失败: {retry_err}")
            return None

    # ================================================================
    # 搜索商业数据
    # ================================================================

    async def search_business(
        self,
        keyword: str,
        country: Optional[str] = None,
        max_pages: int = 5,
        page_size: int = 20,
        job_id: int = 0,
    ) -> Path:
        """直接调用 Joinf API 搜索商业数据，然后用 AI 评估匹配度。"""
        # Step 1: 确保认证（含自动刷新）
        user_id = await self._validate_and_refresh_auth()
        logger.info(f"[JoinfApi] 开始搜索: keyword={keyword}, loginUserId={user_id}")

        batch = JoinfScrapeBatch(source_type="business", keyword=keyword, country=country)
        all_api_items: List[Dict] = []

        # Step 2: 分页调用 API
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            cookies=self._cookies,
            headers=self._get_headers(),
            verify=False,
        ) as client:
            for page_num in range(1, max_pages + 1):
                if job_id and is_cancelled(job_id):
                    logger.info(f"[JoinfApi] Job {job_id} 已取消，停止搜索")
                    break

                payload = self._build_search_payload(
                    keyword=keyword,
                    user_id=user_id,
                    page_num=page_num,
                    page_size=page_size,
                    country=country,
                )

                try:
                    resp = await client.post(self.SEARCH_BUSINESS_URL, json=payload)
                    logger.info(f"[JoinfApi] API 响应: status={resp.status_code}, page={page_num}")
                    resp.raise_for_status()
                    data = resp.json()
                    # ★ 检查业务层 401（HTTP 200 但 code=401）
                    if isinstance(data, dict) and data.get("code") == 401:
                        logger.warning(f"[JoinfApi] API 返回 code=401 (session 过期)，尝试刷新认证 (page={page_num})")
                        refreshed = await self._handle_401_and_retry(
                            keyword, country, user_id, page_num, page_size, job_id
                        )
                        if refreshed:
                            data = refreshed
                        else:
                            break
                    else:
                        logger.info(f"[JoinfApi] 响应 keys={list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 401:
                        logger.warning(f"[JoinfApi] API 返回 HTTP 401，尝试刷新认证 (page={page_num})")
                        refreshed = await self._handle_401_and_retry(
                            keyword, country, user_id, page_num, page_size, job_id
                        )
                        if refreshed:
                            data = refreshed
                        else:
                            break
                    else:
                        logger.error(f"[JoinfApi] API 返回 HTTP {e.response.status_code}: {e.response.text[:300]}")
                        break
                except Exception as e:
                    logger.error(f"[JoinfApi] API 请求失败 (page={page_num}): {e}")
                    break

                # 解析响应
                api_items = self._extract_items_from_response(data)
                if not api_items:
                    logger.info(f"[JoinfApi] 第 {page_num} 页无结果，停止翻页")
                    # ★ 调试：保存第一页的原始响应以便分析
                    if page_num == 1:
                        debug_path = self.config.raw_output_dir / "api_response_debug.json"
                        self.config.raw_output_dir.mkdir(parents=True, exist_ok=True)
                        debug_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                        logger.info(f"[JoinfApi] 调试: 已保存原始响应到 {debug_path}")
                    break

                logger.info(f"[JoinfApi] 第 {page_num} 页获取到 {len(api_items)} 条结果")

                # 检查是否还有下一页
                total = self._extract_total_from_response(data)
                logger.info(f"[JoinfApi] 总结果数: {total or '未知'}, 已获取: {len(all_api_items) + len(api_items)}")

                all_api_items.extend(api_items)

                if total and page_num * page_size >= total:
                    logger.info(f"[JoinfApi] 已获取所有结果 (total={total})")
                    break

        logger.info(f"[JoinfApi] 共获取 {len(all_api_items)} 条原始结果")

        # Step 3: AI 评估每条结果是否与关键词匹配
        if self.ai and self.ai._available() and all_api_items:
            logger.info(f"[JoinfApi] 开始 AI 评估 {len(all_api_items)} 条结果")
            all_api_items = await self._evaluate_items_with_ai(all_api_items, keyword, job_id)

            # 过滤掉匹配度过低的（score < 30 基本不相关）
            matched = [item for item in all_api_items if item.get("_ai_evaluation", {}).get("match_score", 0) >= 30]
            logger.info(f"[JoinfApi] AI 评估完成: {len(matched)}/{len(all_api_items)} 条匹配 (score >= 30)")
            all_api_items = matched
        else:
            logger.warning(f"[JoinfApi] AI 不可用，保留所有 {len(all_api_items)} 条结果（未经过滤）")

        # Step 4: 获取联系人详情
        for item in all_api_items:
            if job_id and is_cancelled(job_id):
                break
            bvd_id = item.get("id")
            if bvd_id and user_id:
                try:
                    detail = await asyncio.wait_for(
                        self._fetch_company_contacts(bvd_id, user_id),
                        timeout=15.0,
                    )
                    if detail.get("contact_list"):
                        item["_contact_detail"] = detail["contact_list"]
                    if detail.get("sns_detail"):
                        item["_sns_detail"] = detail["sns_detail"]
                except asyncio.TimeoutError:
                    logger.warning(f"[JoinfApi] 获取联系人超时 ({bvd_id})，跳过")
                except Exception as e:
                    logger.warning(f"[JoinfApi] 获取联系人失败 ({bvd_id}): {e}")

        # Step 5: 转换为 JoinfRawRow 格式并保存
        for idx, item in enumerate(all_api_items):
            row = self._api_item_to_raw_row(item, idx)
            batch.items.append(row)

        if job_id:
            clear_cancel(job_id)

        return dump_batch(batch, self.config.raw_output_dir)

    def _build_search_payload(
        self,
        keyword: str,
        user_id: int,
        page_num: int,
        page_size: int,
        country: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构建搜索 API 请求体"""
        countries = []
        exclude_countries = ["CHINA"]

        if country:
            country_upper = country.strip().upper()
            country_map = {
                "美国": "US", "英国": "GB", "德国": "DE", "法国": "FR",
                "日本": "JP", "韩国": "KR", "澳大利亚": "AU", "加拿大": "CA",
                "印度": "IN", "巴西": "BR", "墨西哥": "MX", "西班牙": "ES",
                "意大利": "IT", "荷兰": "NL", "俄罗斯": "RU",
            }
            if country in country_map:
                countries = [country_map[country]]
            elif len(country_upper) == 2:
                countries = [country_upper]
            else:
                countries = [country]

        return {
            "loginUserId": user_id,
            "countries": countries,
            "etlMark": 0,
            "socialMediaFlag": 0,
            "labelIds": [],
            "labelQueryType": 1,
            "pageNum": page_num,
            "pageSize": page_size,
            "searchType": 1,
            "keywords": keyword,
            "multiKeywords": [keyword],
            "sortField": "",
            "sortType": "",
            "fullMatch": 1,
            "seeMore": 0,
            "industries": [],
            "industriesSession": [],
            "excludeCountries": exclude_countries,
        }

    # ================================================================
    # 响应解析
    # ================================================================

    def _extract_items_from_response(self, data: Any) -> List[Dict]:
        """从 API 响应中提取结果列表 — 兼容多种响应格式"""
        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            # 常见格式: { code: 200, data: { list: [...] } }
            inner = data.get("data", {})
            if isinstance(inner, dict):
                for key in ("businessListResponses", "customsListResponses", "list", "rows", "records", "items", "result", "businessList", "pageInfo"):
                    if key in inner and isinstance(inner[key], list):
                        return inner[key]
                    # pageInfo 可能是 { list: [...], total: N }
                    if key in inner and isinstance(inner[key], dict):
                        sub = inner[key]
                        for sub_key in ("list", "rows", "records", "items", "result"):
                            if sub_key in sub and isinstance(sub[sub_key], list):
                                return sub[sub_key]
                if isinstance(inner, list):
                    return inner
            elif isinstance(inner, list):
                return inner

            # 格式: { code: 200, list: [...] }
            for key in ("list", "rows", "records", "items", "result", "businessList"):
                if key in data and isinstance(data[key], list):
                    return data[key]

        return []

    def _extract_total_from_response(self, data: Any) -> Optional[int]:
        """从 API 响应中提取总结果数"""
        if not isinstance(data, dict):
            return None

        inner = data.get("data", {})
        if isinstance(inner, dict):
            for key in ("total", "totalCount", "totalElements", "count", "totalRecord"):
                if key in inner:
                    try:
                        return int(inner[key])
                    except (ValueError, TypeError):
                        pass
            # pageInfo 内部
            if "pageInfo" in inner and isinstance(inner["pageInfo"], dict):
                for key in ("total", "totalCount", "totalElements", "count"):
                    if key in inner["pageInfo"]:
                        try:
                            return int(inner["pageInfo"][key])
                        except (ValueError, TypeError):
                            pass
        for key in ("total", "totalCount", "count", "totalRecord"):
            if key in data:
                try:
                    return int(data[key])
                except (ValueError, TypeError):
                    pass
        return None

    # ================================================================
    # 结果转换
    # ================================================================

    _FIELD_MAP = {
        "companyName": "company_name",
        "company_name": "company_name",
        "name": "company_name",
        "nameEn": "company_name",
        "countryName": "country",
        "countryNameEn": "country",
        "country": "country",
        "countryEn": "country_en",
        "countryCode": "country_code",
        "website": "website",
        "websiteUrl": "website",
        "url": "website",
        "homePage": "website",
        "industry": "industry",
        "industryName": "industry",
        "mainIndustry": "industry",
        "mainBusiness": "main_business",
        "description": "description",
        "companyDesc": "description",
        "companyDescription": "description",
        "intro": "description",
        "fullOverview": "description",
        "emailCount": "email_count",
        "emailNum": "email_count",
        "emailSize": "email_count",
        "phone": "phone",
        "tel": "phone",
        "telephone": "phone",
        "address": "address",
        "companyAddr": "address",
        "cityName": "city",
        "city": "city",
        "cityNameEn": "city",
        "employeeSize": "employee_size",
        "employees": "employee_size",
        "foundedYear": "founded_year",
        "revenue": "revenue",
        "tradeMark": "trademark",
        "socialMedia": "social_media",
        "snsList": "social_media",
        "websiteLogo": "website_logo",
        "grade": "grade",
        "star": "star",
        "contactTotal": "contact_total",
        "hasEmail": "has_email",
        "hasWebsite": "has_website",
    }

    _FIELD_LABELS = {
        "company_name": "公司名称",
        "country": "国家",
        "country_code": "国家代码",
        "website": "网站",
        "industry": "行业",
        "main_business": "主营业务",
        "description": "简介",
        "email_count": "邮箱数量",
        "phone": "电话",
        "address": "地址",
        "city": "城市",
        "employee_size": "员工规模",
        "founded_year": "成立年份",
        "revenue": "营收",
        "trademark": "商标",
        "social_media": "社交媒体",
        "website_logo": "公司Logo",
        "grade": "信用评级",
        "star": "星级",
        "contact_total": "联系人总数",
    }

    async def _fetch_company_contacts(self, bvd_id: str, user_id: int) -> Dict:
        """获取公司联系人列表 + 社交媒体详情（纯 HTTP，无需浏览器）"""
        sns_data = None
        contact_data = None

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            cookies=self._cookies,
            headers=self._get_headers(),
            verify=False,
        ) as client:
            # 1) selectSnsByBvdId — 社交媒体详情
            try:
                sns_resp = await client.post(
                    "https://data.joinf.com/api/bs/selectSnsByBvdId",
                    json={"id": bvd_id, "loginUserId": user_id},
                )
                if sns_resp.status_code == 200:
                    sns_result = sns_resp.json()
                    if isinstance(sns_result, dict) and sns_result.get("code") == 0:
                        sns_data = sns_result.get("data")
            except Exception as e:
                logger.warning(f"[JoinfApi] selectSnsByBvdId 失败 ({bvd_id}): {e}")

            await asyncio.sleep(0.3)

            # 2) selectContactBvdIdList — 联系人列表
            try:
                contact_resp = await client.post(
                    "https://data.joinf.com/api/bs/selectContactBvdIdList",
                    json={
                        "pageNum": 1, "pageSize": 100,
                        "dataFromList": [], "markList": [], "isCollection": 0,
                        "keyword": None, "role": None, "startTime": None, "endTime": None,
                        "bvdId": bvd_id, "customerId": None, "jobType": 0,
                        "loginUserId": user_id,
                    },
                )
                if contact_resp.status_code == 200:
                    contact_result = contact_resp.json()
                    if isinstance(contact_result, dict) and contact_result.get("code") == 0:
                        contact_data = contact_result.get("data")
            except Exception as e:
                logger.warning(f"[JoinfApi] selectContactBvdIdList 失败 ({bvd_id}): {e}")

        return {"sns_detail": sns_data, "contact_list": contact_data}

    def _api_item_to_raw_row(self, item: Dict, index: int) -> JoinfRawRow:
        """将 API 返回的单条结果转换为 JoinfRawRow"""
        cells = []
        metadata: Dict[str, Any] = {}

        for api_key, meta_key in self._FIELD_MAP.items():
            if api_key in item and item[api_key] is not None:
                value = item[api_key]
                if isinstance(value, (list, dict)):
                    if value:
                        metadata[meta_key] = value
                else:
                    value_str = str(value).strip()
                    if value_str:
                        metadata[meta_key] = value_str

        for meta_key, label in self._FIELD_LABELS.items():
            if meta_key in metadata:
                value = metadata[meta_key]
                if isinstance(value, list):
                    if meta_key == "social_media":
                        parts = []
                        for s in value[:5]:
                            if isinstance(s, dict):
                                url = s.get("snsUrl") or s.get("url") or ""
                                s_type = s.get("type")
                                sm_label = {1: "Facebook", 2: "Twitter", 3: "LinkedIn", 4: "YouTube", 5: "Instagram", 7: "Instagram", 8: "YouTube"}.get(s_type, "社交")
                                if url:
                                    parts.append(f"{sm_label}: {url}")
                            else:
                                parts.append(str(s))
                        value = ", ".join(parts) if parts else ""
                    else:
                        value = ", ".join(str(v) for v in value[:5])
                if value:
                    cells.append(f"{label}: {value}")

        links = []
        if metadata.get("website"):
            url = metadata["website"]
            if not url.startswith("http"):
                url = f"https://{url}"
            links.append({"href": url, "text": metadata.get("company_name", "")})
        metadata["links"] = links

        if "_ai_evaluation" in item:
            metadata["ai_evaluation"] = item["_ai_evaluation"]

        # 联系人详情（从 selectContactBvdIdList 获取）
        if "_contact_detail" in item:
            metadata["contact_detail"] = item["_contact_detail"]

        # 社交媒体详情（从 selectSnsByBvdId 获取）
        if "_sns_detail" in item:
            metadata["sns_detail"] = item["_sns_detail"]

        metadata["api_raw"] = {k: v for k, v in item.items() if not k.startswith("_")}

        return JoinfRawRow(
            source_type="business",
            page_url="https://data.joinf.com/searchResult",
            row_index=index,
            cells=cells,
            metadata=metadata,
        )

    # ================================================================
    # AI 评估
    # ================================================================

    async def _evaluate_items_with_ai(
        self,
        items: List[Dict],
        keyword: str,
        job_id: int = 0,
    ) -> List[Dict]:
        """用 AI 评估每条结果是否匹配关键词"""
        if not self.ai or not self.ai._available():
            return items

        evaluated = []
        for index, item in enumerate(items):
            if job_id and is_cancelled(job_id):
                logger.info(f"[JoinfApi] Job {job_id} 已取消，已评估 {index}/{len(items)} 条")
                evaluated.extend(items[index:])
                break

            try:
                eval_text = self._build_evaluation_text(item)

                # 如果有网站，尝试获取网站内容
                website_url = self._extract_website_from_item(item)
                website_text = ""
                if website_url:
                    website_text = await self._fetch_website_text(website_url)

                evaluation = await self.ai.evaluate_company(
                    row_text=eval_text,
                    my_product=keyword,
                    source_type="business",
                    website_text=website_text,
                )

                if evaluation:
                    item["_ai_evaluation"] = evaluation
                    score = evaluation.get("match_score", 0)
                    ctype = evaluation.get("customer_type", "unknown")
                    logger.info(
                        f"[JoinfApi] 评估 {index}/{len(items)}: "
                        f"{evaluation.get('company_name', 'N/A')} → "
                        f"匹配度={score} 类型={ctype}"
                    )
                else:
                    logger.warning(f"[JoinfApi] 评估 {index}: AI 返回空结果")

            except Exception as e:
                logger.warning(f"[JoinfApi] AI 评估异常 (index={index}): {e}")

            evaluated.append(item)

        return evaluated

    def _build_evaluation_text(self, item: Dict) -> str:
        """从 API item 构建给 AI 评估的文本"""
        parts = []
        for key, value in item.items():
            if key.startswith("_"):
                continue
            if value is None:
                continue
            if isinstance(value, str) and value.strip():
                parts.append(f"{key}: {value}")
            elif isinstance(value, (int, float)):
                parts.append(f"{key}: {value}")
            elif isinstance(value, list) and value:
                parts.append(f"{key}: {', '.join(str(v) for v in value[:10])}")
            elif isinstance(value, dict) and value:
                for k2, v2 in value.items():
                    if v2 and isinstance(v2, (str, int, float)):
                        parts.append(f"{key}.{k2}: {v2}")
        return "\n".join(parts)

    def _extract_website_from_item(self, item: Dict) -> Optional[str]:
        """从 API item 中提取网站 URL"""
        for key in ("website", "websiteUrl", "url", "homePage"):
            url = item.get(key)
            if url and isinstance(url, str) and url.strip():
                url = url.strip()
                if not url.startswith("http"):
                    url = f"https://{url}"
                skip_domains = ["joinf.com", "linkedin.com", "facebook.com", "google.com"]
                if any(skip in url.lower() for skip in skip_domains):
                    continue
                return url
        return None

    async def _fetch_website_text(self, url: str) -> str:
        """用 httpx 访问网站并提取可见文本内容"""
        import re

        if not url.startswith("http"):
            url = f"https://{url}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }

        for proto_url in [url, url.replace("https://", "http://")]:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(15.0, connect=5.0),
                    follow_redirects=True,
                    headers=headers,
                    verify=False,
                ) as client:
                    resp = await client.get(proto_url)
                    resp.raise_for_status()
                    html = resp.text
                    break
            except Exception:
                continue
        else:
            return ""

        text = html
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)

        import html as html_module
        text = html_module.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text[:8000]
