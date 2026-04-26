from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., description="自然语言搜索请求")
    country: Optional[str] = Field(default=None, description="国家或地区")
    hs_code: Optional[str] = Field(default=None, description="HS Code")
    customer_profile_mode: str = Field(default="small_wholesale", description="general | small_wholesale | bulk_buying")
    customs_required: bool = Field(default=False, description="是否必须有关联海关数据")
    limit: int = Field(default=10, ge=1, le=50)


class ParsedQuery(BaseModel):
    original_query: str
    normalized_keywords: List[str]
    country: Optional[str] = None
    hs_code: Optional[str] = None
    customer_profile_mode: str = "small_wholesale"
    customs_required: bool = False
    limit: int = 10


class ContactItem(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    email_type: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    confidence: Optional[str] = None


class CustomsSummary(BaseModel):
    active_label: str = ""
    trade_date: str = ""
    hs_code: Optional[str] = None
    frequency: int = 0
    buyer: str = ""
    supplier: Optional[str] = None
    product_description: Optional[str] = None
    weight: Optional[str] = None
    quantity: Optional[str] = None
    amount: Optional[str] = None
    origin: Optional[str] = None
    ai_summary: Optional[str] = None
    # 兼容旧字段
    last_trade_at: Optional[str] = None


class LeadItem(BaseModel):
    company_id: int
    company_name: str
    country: str
    city: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    score: int
    confidence: str
    match_reasons: List[str]
    contacts: List[ContactItem]
    customs_summary: Optional[CustomsSummary] = None
    ai_summary: Optional[str] = None


class SearchResponse(BaseModel):
    parsed_query: ParsedQuery
    total: int
    items: List[LeadItem]
