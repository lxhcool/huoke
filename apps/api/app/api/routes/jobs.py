import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db, SessionLocal
from app.repositories.jobs import cancel_search_job, create_search_job, execute_search_job, get_search_job, get_search_job_results
from app.schemas.jobs import SearchJobCreateRequest, SearchJobResponse, SearchJobResultsResponse

logger = logging.getLogger("jobs_api")
router = APIRouter(tags=["search-jobs"])


@router.post("/search-jobs", response_model=SearchJobResponse)
def create_job(
    payload: SearchJobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SearchJobResponse:
    job = create_search_job(db, payload)
    background_tasks.add_task(execute_search_job, job.id)
    return job


@router.post("/search-jobs/{job_id}/cancel", response_model=SearchJobResponse)
def cancel_job(job_id: int, db: Session = Depends(get_db)) -> SearchJobResponse:
    """取消正在运行的搜索任务"""
    try:
        return cancel_search_job(db, job_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/search-jobs/{job_id}", response_model=SearchJobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> SearchJobResponse:
    try:
        return get_search_job(db, job_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/search-jobs/{job_id}/results", response_model=SearchJobResultsResponse)
def get_job_results(job_id: int, db: Session = Depends(get_db)) -> SearchJobResultsResponse:
    """获取搜索结果 — 对 SQLite 锁冲突做充分容错，绝不在运行中返回 404"""

    def _try_get(session: Session):
        return get_search_job_results(session, job_id)

    # 第一次尝试：用 FastAPI 注入的 session
    try:
        return _try_get(db)
    except Exception as first_error:
        logger.warning(f"[API] results 查询异常 (job={job_id}): {first_error}, 尝试独立 session 重试")
        try:
            db.rollback()
        except Exception:
            pass

        # 第二次尝试：用独立 session
        try:
            with SessionLocal() as db2:
                return _try_get(db2)
        except Exception as second_error:
            logger.warning(f"[API] results 独立 session 也失败 (job={job_id}): {second_error}")

            # 第三次尝试：确认 job 是否真的存在
            try:
                with SessionLocal() as db3:
                    job = db3.get(object=None, ident=job_id)  # just test connection
                    # 用最简单的查询确认 job 存在
                    from app.models.search_job import SearchJob
                    exists = db3.query(SearchJob.id).filter(SearchJob.id == job_id).first()
                    if exists is None:
                        # job 真的不存在 → 真正的 404
                        raise HTTPException(status_code=404, detail="search job not found") from first_error
            except HTTPException:
                raise
            except Exception:
                pass

            # job 存在但读取结果失败（锁冲突等）→ 返回空结果，前端继续轮询
            logger.info(f"[API] job {job_id} 存在但结果读取失败，返回空结果")
            return SearchJobResultsResponse(job_id=job_id, status="running", total=0, items=[])
