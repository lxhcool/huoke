from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class ContactMaster(Base):
    __tablename__ = "contact_master"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_title: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    email_type: Mapped[Optional[str]] = mapped_column(String(50), default="business")
    confidence_level: Mapped[str] = mapped_column(String(1), default="B")
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company_contacts: Mapped[List["CompanyContactRelation"]] = relationship(back_populates="contact")


class CompanyContactRelation(Base):
    __tablename__ = "company_contact_relation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company_master.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact_master.id"), index=True)
    relation_type: Mapped[Optional[str]] = mapped_column(String(50), default="employee")
    priority_rank: Mapped[int] = mapped_column(Integer, default=50)

    company: Mapped["CompanyMaster"] = relationship(back_populates="company_contacts")
    contact: Mapped["ContactMaster"] = relationship(back_populates="company_contacts")
