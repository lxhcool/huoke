from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.imports import import_companies
from app.schemas.imports import ImportRequest, ImportResponse

router = APIRouter(tags=["imports"])


@router.post("/imports/companies", response_model=ImportResponse)
def import_company_data(payload: ImportRequest, db: Session = Depends(get_db)) -> ImportResponse:
    return import_companies(db, payload)
