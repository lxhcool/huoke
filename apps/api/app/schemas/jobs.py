from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.search import ContactItem, CustomsSummary


class SearchJobCreateRequest(BaseModel):
    query: str
    sources: List[str] = Field(default_factory=lambda: ["joinf_business", "joinf_customs", "linkedin_company", "linkedin_contact"])
    country: Optional[str] = None
    hs_code: Optional[str] = None
    customer_profile_mode: str = "small_wholesale"
    customs_required: bool = False
    limit: int = Field(default=10, ge=1, le=50)


class SourceTaskResponse(BaseModel):
    id: int
    source_name: str
    task_type: str
    status: str
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class SearchJobResponse(BaseModel):
    id: int
    query: str
    country: Optional[str] = None
    hs_code: Optional[str] = None
    customer_profile_mode: str
    customs_required: bool
    limit: int
    status: str
    sources: List[str]
    result_count: int
    created_at: datetime
    updated_at: datetime
    source_tasks: List[SourceTaskResponse]


class SearchJobResultItem(BaseModel):
    id: int
    company_id: int
    company_name: str
    country: str
    city: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    score: int
    confidence: str
    result_status: str
    intent_label: Optional[str] = None
    source_names: List[str]
    match_reasons: List[str]
    contacts: List[ContactItem]
    customs_summary: Optional[CustomsSummary] = None


class SearchJobResultsResponse(BaseModel):
    job_id: int
    status: str
    total: int
    items: List[SearchJobResultItem]
