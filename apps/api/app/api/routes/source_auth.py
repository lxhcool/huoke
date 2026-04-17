from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.schemas.source_auth import (
    SourceAuthProviderListResponse,
    SourceAuthVerifyRequest,
    SourceAuthVerifyResponse,
)
from app.services.source_auth import list_source_auth_providers, verify_source_auth

router = APIRouter(tags=["source-auth"])


@router.get("/source-auth/providers", response_model=SourceAuthProviderListResponse)
def list_auth_providers() -> SourceAuthProviderListResponse:
    return SourceAuthProviderListResponse(items=list_source_auth_providers())


@router.post("/source-auth/{source_name}/verify", response_model=SourceAuthVerifyResponse)
async def verify_auth(source_name: str, payload: SourceAuthVerifyRequest) -> SourceAuthVerifyResponse:
    try:
        storage_state_path = await verify_source_auth(source_name, payload.credentials)
        return SourceAuthVerifyResponse(
            source_name=source_name,
            status="verified",
            message="登录态验证成功",
            verified_at=datetime.utcnow(),
            storage_state_path=str(storage_state_path),
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        message = str(error)
        if "Executable doesn't exist" in message and "playwright install" in message:
            raise HTTPException(
                status_code=400,
                detail="Playwright 浏览器内核未安装，请执行：cd apps/api && source .venv/bin/activate && playwright install chromium",
            ) from error
        raise HTTPException(status_code=400, detail=f"登录验证失败：{message}") from error
