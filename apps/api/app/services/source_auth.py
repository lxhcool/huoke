from __future__ import annotations

from dataclasses import dataclass
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


async def _verify_joinf(credentials: Dict[str, str]) -> Path:
    username = credentials.get("username", "").strip()
    password = credentials.get("password", "").strip()
    config = JoinfScraperConfig(username=username or None, password=password or None)
    service = JoinfScraperService(config)
    return await service.ensure_login_session(allow_manual=True, interactive_manual=False, manual_timeout_seconds=240)


async def _verify_linkedin(credentials: Dict[str, str]) -> Path:
    username = credentials.get("username", "").strip()
    password = credentials.get("password", "").strip()
    config = LinkedinScraperConfig(username=username or None, password=password or None)
    service = LinkedinScraperService(config)
    storage_state_path = await service.ensure_login_session(
        allow_manual=True,
        interactive_manual=False,
        manual_timeout_seconds=240,
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
    "linkedin": SourceAuthProvider(
        source_name="linkedin",
        display_name="LinkedIn",
        task_sources=["linkedin_company", "linkedin_contact"],
        credential_fields=[
            SourceCredentialField(name="username", label="账号", input_type="text", required=True),
            SourceCredentialField(name="password", label="密码", input_type="password", required=True),
        ],
        verify_handler=_verify_linkedin,
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
