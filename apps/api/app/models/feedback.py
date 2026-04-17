from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class LeadFeedback(Base):
    __tablename__ = "lead_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company_master.id"), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(100), default="internal_user")
    query_text: Mapped[Optional[str]] = mapped_column(Text)
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
