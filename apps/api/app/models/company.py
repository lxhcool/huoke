from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class CompanyMaster(Base):
    __tablename__ = "company_master"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    standard_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    city: Mapped[Optional[str]] = mapped_column(String(100))
    website: Mapped[Optional[str]] = mapped_column(String(255))
    domain: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    industry: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    keywords_text: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(1), default="B")
    confidence_score: Mapped[float] = mapped_column(Float, default=0.7)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company_contacts: Mapped[List["CompanyContactRelation"]] = relationship(back_populates="company")
    company_customs: Mapped[List["CompanyCustomsRelation"]] = relationship(back_populates="company")


class CompanyCustomsRelation(Base):
    __tablename__ = "company_customs_relation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company_master.id"), index=True)
    customs_record_id: Mapped[int] = mapped_column(ForeignKey("customs_record.id"), index=True)
    match_confidence: Mapped[str] = mapped_column(String(1), default="B")

    company: Mapped["CompanyMaster"] = relationship(back_populates="company_customs")
    customs_record: Mapped["CustomsRecord"] = relationship(back_populates="company_customs")
