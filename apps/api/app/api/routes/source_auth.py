from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.schemas.source_auth import (
    SourceAuthCookieImportRequest,
    SourceAuthProviderListResponse,
    SourceAuthVerifyRequest,
    SourceAuthVerifyResponse,
)
from app.services.source_auth import import_source_cookie, list_source_auth_providers, verify_source_auth

router = APIRouter(tags=["source-auth"])


@router.get("/source-auth/providers", response_model=SourceAuthProviderListResponse)
def list_auth_providers() -> SourceAuthProviderListResponse:
    return SourceAuthProviderListResponse(items=list_source_auth_providers())


@router.post("/source-auth/{source_name}/verify", response_model=SourceAuthVerifyResponse)
async def verify_auth(source_name: str, payload: SourceAuthVerifyRequest) -> SourceAuthVerifyResponse:
    import logging
    logger = logging.getLogger("source_auth")
    
    try:
        logger.info(f"Verifying source: {source_name}, credentials keys: {list(payload.credentials.keys())}")
        storage_state_path = await verify_source_auth(source_name, payload.credentials)
        logger.info(f"Verification successful for {source_name}")
        return SourceAuthVerifyResponse(
            source_name=source_name,
            status="verified",
            message="登录态验证成功",
            verified_at=datetime.utcnow(),
            storage_state_path=str(storage_state_path),
        )
    except ValueError as error:
        detail = str(error) or f"ValueError: {repr(error)}"
        logger.error(f"ValueError: {detail}")
        raise HTTPException(status_code=404, detail=detail)
    except RuntimeError as error:
        import traceback as _tb
        detail = str(error) or f"RuntimeError (empty msg): {_tb.format_exc()}"
        logger.error(f"RuntimeError: {detail}\n{_tb.format_exc()}")
        raise HTTPException(status_code=400, detail=detail)
    except Exception as error:
        import traceback
        error_type = type(error).__name__
        message = str(error)
        tb = traceback.format_exc()
        logger.error(f"Unexpected error: {error_type}: {message}\n{tb}")
        if not message:
            message = f"{error_type}: {tb}"
        if "Executable doesn't exist" in message and "playwright install" in message:
            raise HTTPException(
                status_code=400,
                detail="Playwright 浏览器内核未安装，请执行：cd apps/api && .venv/Scripts/python.exe -m playwright install chromium",
            )
        raise HTTPException(status_code=400, detail=f"登录验证失败：{message}")


@router.post("/source-auth/{source_name}/import-cookie", response_model=SourceAuthVerifyResponse)
async def import_cookie(source_name: str, payload: SourceAuthCookieImportRequest) -> SourceAuthVerifyResponse:
    try:
        storage_state_path = import_source_cookie(source_name, payload.cookie_string)
        return SourceAuthVerifyResponse(
            source_name=source_name,
            status="verified",
            message="Cookie 导入成功，登录态已保存",
            verified_at=datetime.utcnow(),
            storage_state_path=str(storage_state_path),
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error) or repr(error))
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error) or repr(error))
