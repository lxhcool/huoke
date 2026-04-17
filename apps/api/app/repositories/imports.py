from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import CompanyCustomsRelation, CompanyMaster
from app.models.contact import CompanyContactRelation, ContactMaster
from app.models.customs import CustomsRecord
from app.schemas.imports import ImportCompanyItem, ImportRequest, ImportResponse


def _parse_trade_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value)


def _find_company(db: Session, item: ImportCompanyItem) -> Optional[CompanyMaster]:
    if item.domain:
        existing = db.scalar(select(CompanyMaster).where(CompanyMaster.domain == item.domain))
        if existing:
            return existing
    return db.scalar(
        select(CompanyMaster).where(
            CompanyMaster.standard_name == item.standard_name,
            CompanyMaster.country == item.country,
        )
    )


def import_companies(db: Session, payload: ImportRequest) -> ImportResponse:
    imported_companies = 0
    imported_contacts = 0
    imported_customs_records = 0

    for item in payload.companies:
        company = _find_company(db, item)
        if company is None:
            company = CompanyMaster(
                standard_name=item.standard_name,
                country=item.country,
                city=item.city,
                website=item.website,
                domain=item.domain,
                industry=item.industry,
                keywords_text=item.keywords_text,
                description=item.description,
                confidence_level=item.confidence_level,
                confidence_score=item.confidence_score,
            )
            db.add(company)
            db.flush()
            imported_companies += 1
        else:
            company.city = item.city or company.city
            company.website = item.website or company.website
            company.domain = item.domain or company.domain
            company.industry = item.industry or company.industry
            company.keywords_text = item.keywords_text or company.keywords_text
            company.description = item.description or company.description

        for contact_item in item.contacts:
            contact = None
            if contact_item.email:
                contact = db.scalar(select(ContactMaster).where(ContactMaster.email == contact_item.email))
            if contact is None:
                contact = db.scalar(
                    select(ContactMaster).where(
                        ContactMaster.full_name == contact_item.full_name,
                        ContactMaster.job_title == contact_item.job_title,
                    )
                )
            if contact is None:
                contact = ContactMaster(
                    full_name=contact_item.full_name,
                    job_title=contact_item.job_title,
                    email=contact_item.email,
                    email_type=contact_item.email_type,
                    confidence_level=contact_item.confidence_level,
                )
                db.add(contact)
                db.flush()
                imported_contacts += 1

            relation = db.scalar(
                select(CompanyContactRelation).where(
                    CompanyContactRelation.company_id == company.id,
                    CompanyContactRelation.contact_id == contact.id,
                )
            )
            if relation is None:
                db.add(
                    CompanyContactRelation(
                        company_id=company.id,
                        contact_id=contact.id,
                        priority_rank=contact_item.priority_rank,
                    )
                )

        for customs_item in item.customs_records:
            trade_date = _parse_trade_date(customs_item.trade_date)
            customs_record = db.scalar(
                select(CustomsRecord).where(
                    CustomsRecord.subject_name == customs_item.subject_name,
                    CustomsRecord.hs_code == customs_item.hs_code,
                    CustomsRecord.trade_date == trade_date,
                )
            )
            if customs_record is None:
                customs_record = CustomsRecord(
                    subject_name=customs_item.subject_name,
                    trade_direction=customs_item.trade_direction,
                    hs_code=customs_item.hs_code,
                    product_description=customs_item.product_description,
                    trade_date=trade_date,
                    trade_frequency=customs_item.trade_frequency,
                    active_label=customs_item.active_label,
                )
                db.add(customs_record)
                db.flush()
                imported_customs_records += 1

            relation = db.scalar(
                select(CompanyCustomsRelation).where(
                    CompanyCustomsRelation.company_id == company.id,
                    CompanyCustomsRelation.customs_record_id == customs_record.id,
                )
            )
            if relation is None:
                db.add(
                    CompanyCustomsRelation(
                        company_id=company.id,
                        customs_record_id=customs_record.id,
                        match_confidence=customs_item.match_confidence,
                    )
                )

    db.commit()
    return ImportResponse(
        imported_companies=imported_companies,
        imported_contacts=imported_contacts,
        imported_customs_records=imported_customs_records,
    )
