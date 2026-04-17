from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.jobs import create_search_job, execute_search_job, get_search_job, get_search_job_results
from app.schemas.jobs import SearchJobCreateRequest, SearchJobResponse, SearchJobResultsResponse

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


@router.get("/search-jobs/{job_id}", response_model=SearchJobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> SearchJobResponse:
    try:
        return get_search_job(db, job_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/search-jobs/{job_id}/results", response_model=SearchJobResultsResponse)
def get_job_results(job_id: int, db: Session = Depends(get_db)) -> SearchJobResultsResponse:
    try:
        return get_search_job_results(db, job_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
