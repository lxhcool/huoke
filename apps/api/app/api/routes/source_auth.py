from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.schemas.source_auth import (
    SourceAuthCookieImportRequest,
    SourceAuthProviderListResponse,
    SourceAuthVerifyRequest,
    SourceAuthVerifyResponse,
    SourceAuthVerifyTaskResponse,
    SourceAuthVerifyTaskStatus,
)
from app.services.source_auth import import_source_cookie, list_source_auth_providers, verify_source_auth

router = APIRouter(tags=["source-auth"])
logger = logging.getLogger("source_auth")

# ── 内存中的异步验证任务存储 ──────────────────────────────────────
_verify_tasks: dict[str, SourceAuthVerifyTaskStatus] = {}


def _run_verify_sync(task_id: str, source_name: str, credentials: dict) -> None:
    """在线程池中同步执行验证，避免事件循环嵌套问题"""
    import sys
    task = _verify_tasks.get(task_id)
    if not task:
        return
    task.status = "running"
    task.message = "正在启动浏览器登录..."
    try:
        # 在线程中创建新的事件循环来运行异步验证
        import concurrent.futures
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            storage_state_path = loop.run_until_complete(
                verify_source_auth(source_name, credentials)
            )
        finally:
            loop.close()
        task.status = "verified"
        task.message = "登录验证成功"
        task.verified_at = datetime.utcnow()
        logger.info(f"[VerifyTask] {task_id} verified successfully")
    except ValueError as e:
        task.status = "failed"
        task.message = str(e) or "不支持的数据源"
        logger.error(f"[VerifyTask] {task_id} ValueError: {e}")
    except RuntimeError as e:
        task.status = "failed"
        task.message = str(e) or "登录验证失败"
        logger.error(f"[VerifyTask] {task_id} RuntimeError: {e}")
    except Exception as e:
        import traceback
        error_type = type(e).__name__
        message = str(e)
        tb = traceback.format_exc()
        if "Executable doesn't exist" in message and "playwright install" in message:
            task.message = "服务器浏览器内核未安装，请联系管理员"
        else:
            task.message = f"登录验证失败：{message}" if message else f"{error_type}"
        logger.error(f"[VerifyTask] {task_id} failed: {error_type}: {message}\n{tb}")


@router.get("/source-auth/providers", response_model=SourceAuthProviderListResponse)
def list_auth_providers() -> SourceAuthProviderListResponse:
    return SourceAuthProviderListResponse(items=list_source_auth_providers())


@router.post("/source-auth/{source_name}/verify", response_model=SourceAuthVerifyTaskResponse)
async def verify_auth(source_name: str, payload: SourceAuthVerifyRequest) -> SourceAuthVerifyTaskResponse:
    """启动异步验证任务，立即返回 task_id，前端轮询状态"""
    logger.info(f"Starting async verify for source: {source_name}, credentials keys: {list(payload.credentials.keys())}")

    task_id = str(uuid.uuid4())[:8]
    task = SourceAuthVerifyTaskStatus(
        task_id=task_id,
        source_name=source_name,
        status="pending",
        message="验证任务已创建，等待执行...",
    )
    _verify_tasks[task_id] = task

    # 在线程池中运行，避免事件循环嵌套
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        None,
        _run_verify_sync,
        task_id,
        source_name,
        payload.credentials,
    )

    return SourceAuthVerifyTaskResponse(
        task_id=task_id,
        source_name=source_name,
        status=task.status,
        message=task.message,
    )


@router.get("/source-auth/verify-status/{task_id}", response_model=SourceAuthVerifyTaskStatus)
def get_verify_status(task_id: str) -> SourceAuthVerifyTaskStatus:
    """查询验证任务状态"""
    task = _verify_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="验证任务不存在或已过期")
    return task


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
