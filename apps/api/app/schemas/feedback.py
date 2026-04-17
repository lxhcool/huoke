from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    company_id: int
    action: str = Field(..., description="favorite | invalid | useful")
    user_name: Optional[str] = "internal_user"
    query_text: Optional[str] = None
    note: Optional[str] = None


class FeedbackResponse(BaseModel):
    id: int
    company_id: int
    action: str
    user_name: Optional[str] = None
    query_text: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
