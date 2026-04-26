from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.search import ContactItem, CustomsSummary


class SearchJobCreateRequest(BaseModel):
    query: str
    sources: List[str] = Field(default_factory=lambda: ["joinf_business", "joinf_customs", "linkedin_company", "linkedin_contact"])
    country: Optional[str] = None
    hs_code: Optional[str] = None
    customer_profile_mode: str = "small_wholesale"
    customs_required: bool = False
    limit: int = Field(default=10, ge=1, le=500)
    min_score: int = Field(default=0, ge=0, le=100, description="AI 最低匹配分数，低于此分数的结果不保存（0=保存全部）")
    ai_config: Optional[Dict[str, str]] = Field(
        default=None,
        description="AI 提取服务配置（从前端 localStorage 传入）：{ api_key, base_url, model }",
    )


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
    min_score: int = 0
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
    main_business: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None
    employee_size: Optional[str] = None
    email_count: Optional[int] = None
    linkedin_url: Optional[str] = None
    website_logo: Optional[str] = None
    grade: Optional[str] = None
    star: Optional[float] = None
    social_media: Optional[List[Dict]] = None
    score: int
    confidence: str
    result_status: str
    intent_label: Optional[str] = None
    source_names: List[str]
    match_reasons: List[str]
    contacts: List[ContactItem]
    customs_summary: Optional[CustomsSummary] = None
    ai_summary: Optional[str] = None


class SearchJobResultsResponse(BaseModel):
    job_id: int
    status: str
    total: int
    items: List[SearchJobResultItem]
