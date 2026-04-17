from __future__ import annotations

import re

from app.schemas.search import ParsedQuery, SearchRequest


KEYWORD_MAPPINGS = {
    "激光切割设备": ["laser cutting", "cutting equipment", "laser equipment"],
    "激光切割机": ["laser cutting machine", "laser cutting"],
    "激光切割": ["laser cutting"],
    "切割设备": ["cutting equipment"],
    "钣金": ["sheet metal"],
    "钣金加工": ["sheet metal fabrication"],
    "批发": ["wholesale"],
    "小单": ["small batch", "low moq"],
    "试单": ["trial order", "low moq"],
    "补货": ["restock"],
    "分销商": ["distributor"],
    "经销商": ["reseller"],
}

STOP_PHRASES = [
    "帮我找",
    "最近一年",
    "最近",
    "有进口记录",
    "的公司",
    "公司",
    "客户",
]


def _extract_keywords(query: str, profile_mode: str) -> list[str]:
    normalized_query = query.strip().lower()
    keywords: list[str] = []

    for phrase, mapped_keywords in KEYWORD_MAPPINGS.items():
        if phrase in query:
            keywords.extend(mapped_keywords)

    cleaned_query = query
    for phrase in STOP_PHRASES:
        cleaned_query = cleaned_query.replace(phrase, " ")

    cleaned_query = re.sub(r"[，,、。；;：:\s]+", " ", cleaned_query).strip()

    for token in cleaned_query.split(" "):
        token = token.strip()
        if not token or len(token) <= 1:
            continue
        if re.search(r"[a-zA-Z]", token):
            keywords.append(token.lower())

    if profile_mode == "small_wholesale":
        keywords.extend(["wholesale", "low moq", "restock"])
    elif profile_mode == "bulk_buying":
        keywords.extend(["bulk order", "large volume"])

    deduplicated: list[str] = []
    for keyword in keywords:
        if keyword not in deduplicated:
            deduplicated.append(keyword)

    return deduplicated


def parse_query(request: SearchRequest) -> ParsedQuery:
    query = request.query.strip()
    normalized_keywords = [part.strip() for part in query.replace("，", ",").split(",") if part.strip()]

    extracted_keywords = _extract_keywords(query, request.customer_profile_mode)
    normalized_keywords.extend(extracted_keywords)

    deduplicated_keywords: list[str] = []
    for keyword in normalized_keywords:
        if keyword not in deduplicated_keywords:
            deduplicated_keywords.append(keyword)

    if not deduplicated_keywords:
        deduplicated_keywords = [query]

    return ParsedQuery(
        original_query=request.query,
        normalized_keywords=deduplicated_keywords,
        country=request.country,
        hs_code=request.hs_code,
        customer_profile_mode=request.customer_profile_mode,
        customs_required=request.customs_required,
        limit=request.limit,
    )
