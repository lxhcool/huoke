from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class CustomsRecord(Base):
    __tablename__ = "customs_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    subject_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    trade_direction: Mapped[Optional[str]] = mapped_column(String(50), default="import")
    hs_code: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    product_description: Mapped[Optional[str]] = mapped_column(Text)
    trade_date: Mapped[Optional[date]] = mapped_column(Date)
    trade_frequency: Mapped[int] = mapped_column(Integer, default=1)
    trade_amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    active_label: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company_customs: Mapped[List["CompanyCustomsRelation"]] = relationship(back_populates="customs_record")
