from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ImportContactItem(BaseModel):
    full_name: str
    job_title: Optional[str] = None
    email: Optional[str] = None
    email_type: Optional[str] = "business"
    confidence_level: str = "B"
    priority_rank: int = 50


class ImportCustomsItem(BaseModel):
    subject_name: str
    trade_direction: Optional[str] = "import"
    hs_code: Optional[str] = None
    product_description: Optional[str] = None
    trade_date: Optional[str] = None
    trade_frequency: int = 1
    active_label: Optional[str] = None
    match_confidence: str = "B"


class ImportCompanyItem(BaseModel):
    standard_name: str
    country: Optional[str] = None
    city: Optional[str] = None
    website: Optional[str] = None
    domain: Optional[str] = None
    industry: Optional[str] = None
    keywords_text: Optional[str] = None
    description: Optional[str] = None
    confidence_level: str = "B"
    confidence_score: float = Field(default=0.7, ge=0, le=1)
    contacts: List[ImportContactItem] = Field(default_factory=list)
    customs_records: List[ImportCustomsItem] = Field(default_factory=list)


class ImportRequest(BaseModel):
    companies: List[ImportCompanyItem]


class ImportResponse(BaseModel):
    imported_companies: int
    imported_contacts: int
    imported_customs_records: int
