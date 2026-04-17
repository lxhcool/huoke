from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class SearchJob(Base):
    __tablename__ = "search_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    hs_code: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    customer_profile_mode: Mapped[str] = mapped_column(String(50), default="small_wholesale")
    customs_required: Mapped[bool] = mapped_column(Boolean, default=False)
    limit: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[str] = mapped_column(String(50), default="queued")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_tasks: Mapped[List["SearchJobSourceTask"]] = relationship(back_populates="job")
    results: Mapped[List["SearchResultItem"]] = relationship(back_populates="job")


class SearchJobSourceTask(Base):
    __tablename__ = "search_job_source_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("search_job.id"), index=True)
    source_name: Mapped[str] = mapped_column(String(100), index=True)
    task_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="queued")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["SearchJob"] = relationship(back_populates="source_tasks")


class SearchResultItem(Base):
    __tablename__ = "search_result_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("search_job.id"), index=True)
    company_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(50), default="partial")
    score: Mapped[int] = mapped_column(Integer, default=0)
    activity_score: Mapped[int] = mapped_column(Integer, default=0)
    intent_label: Mapped[Optional[str]] = mapped_column(String(100))
    source_summary_json: Mapped[str] = mapped_column(Text, default="[]")
    match_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    base_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    enriched_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job: Mapped["SearchJob"] = relationship(back_populates="results")
