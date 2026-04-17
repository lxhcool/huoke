from __future__ import annotations

from typing import List

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.prompt_profiles import get_profile_definition
from app.models.company import CompanyCustomsRelation, CompanyMaster
from app.models.contact import CompanyContactRelation
from app.schemas.search import ContactItem, CustomsSummary, LeadItem, ParsedQuery, SearchResponse


def _build_company_query(parsed_query: ParsedQuery) -> Select[tuple[CompanyMaster]]:
    statement = select(CompanyMaster).options(
        selectinload(CompanyMaster.company_contacts).selectinload(CompanyContactRelation.contact),
        selectinload(CompanyMaster.company_customs).selectinload(CompanyCustomsRelation.customs_record),
    )

    if parsed_query.country:
        statement = statement.where(CompanyMaster.country.ilike(parsed_query.country))

    keyword_filters = []
    for keyword in parsed_query.normalized_keywords:
        like_keyword = f"%{keyword}%"
        keyword_filters.extend(
            [
                CompanyMaster.standard_name.ilike(like_keyword),
                CompanyMaster.industry.ilike(like_keyword),
                CompanyMaster.keywords_text.ilike(like_keyword),
                CompanyMaster.description.ilike(like_keyword),
            ]
        )

    if keyword_filters:
        statement = statement.where(or_(*keyword_filters))

    if parsed_query.customs_required:
        statement = statement.where(CompanyMaster.company_customs.any())

    return statement.limit(parsed_query.limit)


def _calculate_score(company: CompanyMaster, parsed_query: ParsedQuery) -> int:
    score = 40
    profile = get_profile_definition(parsed_query.customer_profile_mode)
    searchable_text = " ".join(
        filter(
            None,
            [company.standard_name, company.industry, company.keywords_text, company.description],
        )
    ).lower()

    for keyword in parsed_query.normalized_keywords:
        if keyword.lower() in searchable_text:
            score += 10

    for focus_term in profile.get("search_focus_terms", []):
        if focus_term.lower() in searchable_text:
            score += 7

    for avoid_term in profile.get("avoid_terms", []):
        if avoid_term.lower() in searchable_text:
            score -= 4

    if parsed_query.country and company.country and parsed_query.country.lower() == company.country.lower():
        score += 10

    if company.company_contacts:
        score += 12

    if company.company_customs:
        score += 18

    score += int(company.confidence_score * 10)
    return min(score, 99)


def _build_reasons(company: CompanyMaster, parsed_query: ParsedQuery) -> List[str]:
    reasons: List[str] = []
    profile = get_profile_definition(parsed_query.customer_profile_mode)

    if parsed_query.country and company.country and parsed_query.country.lower() == company.country.lower():
        reasons.append("国家与查询条件一致")

    if company.industry:
        reasons.append(f"行业命中：{company.industry}")

    if company.company_customs:
        reasons.append("存在海关记录，可用于判断采购活跃度")

    if any(relation.contact and relation.contact.email for relation in company.company_contacts):
        reasons.append("已找到可触达联系人和企业邮箱")

    if parsed_query.customer_profile_mode == "small_wholesale":
        reasons.append("当前按“批发小单”偏好筛选，更关注低MOQ、试单和补货型客户")
    elif parsed_query.customer_profile_mode == "bulk_buying":
        reasons.append("当前按“大单采购”偏好筛选，更关注批量采购和规模型客户")

    for focus_term in profile.get("search_focus_terms", [])[:2]:
        if focus_term.lower() in " ".join(filter(None, [company.industry, company.keywords_text, company.description])).lower():
            reasons.append(f"偏好命中：{focus_term}")

    for keyword in parsed_query.normalized_keywords[:2]:
        reasons.append(f"关键词命中：{keyword}")

    return reasons[:4]


def search_leads(db: Session, parsed_query: ParsedQuery) -> SearchResponse:
    companies = db.scalars(_build_company_query(parsed_query)).unique().all()
    items: List[LeadItem] = []

    for company in companies:
        contacts = []
        for relation in sorted(company.company_contacts, key=lambda item: item.priority_rank):
            if relation.contact is None:
                continue
            contacts.append(
                ContactItem(
                    name=relation.contact.full_name,
                    title=relation.contact.job_title or "Unknown",
                    email=relation.contact.email,
                    email_type=relation.contact.email_type,
                    confidence=relation.contact.confidence_level,
                )
            )

        customs_summary = None
        if company.company_customs:
            latest = sorted(
                [relation.customs_record for relation in company.company_customs if relation.customs_record],
                key=lambda item: item.trade_date or item.created_at.date(),
                reverse=True,
            )[0]
            customs_summary = CustomsSummary(
                active_label=latest.active_label or "存在海关记录",
                last_trade_at=str(latest.trade_date or latest.created_at.date()),
                hs_code=latest.hs_code,
                frequency=latest.trade_frequency,
            )

        items.append(
            LeadItem(
                company_id=company.id,
                company_name=company.standard_name,
                country=company.country or "Unknown",
                city=company.city,
                website=company.website,
                industry=company.industry,
                score=_calculate_score(company, parsed_query),
                confidence=company.confidence_level,
                match_reasons=_build_reasons(company, parsed_query),
                contacts=contacts,
                customs_summary=customs_summary,
            )
        )

    items.sort(key=lambda item: item.score, reverse=True)
    return SearchResponse(parsed_query=parsed_query, total=len(items), items=items)
