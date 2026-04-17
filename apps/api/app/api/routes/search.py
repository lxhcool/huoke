from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.search import SearchRequest, SearchResponse
from fastapi import Depends

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    raise HTTPException(status_code=410, detail="/api/search 已弃用，请改用 /api/search-jobs 任务流接口")
