from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class SourceCredentialField(BaseModel):
    name: str
    label: str
    input_type: Literal["text", "password"] = "text"
    required: bool = True


class SourceAuthProviderItem(BaseModel):
    source_name: str
    display_name: str
    task_sources: List[str]
    credential_fields: List[SourceCredentialField]


class SourceAuthProviderListResponse(BaseModel):
    items: List[SourceAuthProviderItem]


class SourceAuthVerifyRequest(BaseModel):
    credentials: Dict[str, str] = Field(default_factory=dict)


class SourceAuthCookieImportRequest(BaseModel):
    cookie_string: str = Field(..., description="浏览器中复制的 Cookie 字符串")


class SourceAuthVerifyResponse(BaseModel):
    source_name: str
    status: Literal["verified", "failed"]
    message: str
    verified_at: datetime
    storage_state_path: str


class SourceAuthVerifyTaskResponse(BaseModel):
    task_id: str
    source_name: str
    status: Literal["pending", "running", "verified", "failed"]
    message: str = ""


class SourceAuthVerifyTaskStatus(BaseModel):
    task_id: str
    source_name: str
    status: Literal["pending", "running", "verified", "failed"]
    message: str = ""
    verified_at: Optional[datetime] = None

