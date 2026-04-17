from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def extract_business_record(raw_item: dict, fallback_country: Optional[str] = None) -> dict:
    cells = raw_item.get("cells", [])
    metadata = raw_item.get("metadata", {}) or {}
    links = metadata.get("links", []) or []

    company_name = _pick_company_name(cells)
    website = _pick_website(cells, links)
    country = _pick_country(cells, fallback_country)
    city = _pick_city(cells, country)
    industry = _pick_industry(cells)
    contact_name = _pick_contact_name(cells)
    contact_title = _pick_contact_title(cells)
    contact_email = _pick_email(cells)
    phone = _pick_phone(cells)

    return {
        "company_name": company_name,
        "country": country,
        "city": city,
        "website": website,
        "industry": industry,
        "contacts": [
            {
                "name": contact_name,
                "title": contact_title,
                "email": contact_email,
                "email_type": "business" if contact_email else None,
                "confidence": "B",
                "phone": phone,
            }
        ] if any([contact_name, contact_title, contact_email, phone]) else [],
        "detail_url": links[0] if links else raw_item.get("page_url"),
    }


def extract_customs_record(raw_item: dict, fallback_hs_code: Optional[str] = None, fallback_country: Optional[str] = None) -> dict:
    cells = raw_item.get("cells", [])
    metadata = raw_item.get("metadata", {}) or {}
    links = metadata.get("links", []) or []

    company_name = _pick_company_name(cells)
    country = _pick_country(cells, fallback_country)
    hs_code = _pick_hs_code(cells, fallback_hs_code)
    trade_date = _pick_trade_date(cells)
    frequency = _pick_frequency(cells)
    product_description = _pick_product_description(cells)

    return {
        "company_name": company_name,
        "country": country,
        "hs_code": hs_code,
        "trade_date": trade_date,
        "frequency": frequency,
        "product_description": product_description,
        "detail_url": links[0] if links else raw_item.get("page_url"),
    }


def _pick_company_name(cells: List[str]) -> str:
    for cell in cells:
        candidate = cell.strip()
        if not candidate:
            continue
        if any(keyword in candidate.lower() for keyword in ["http", "www.", "@"]):
            continue
        if _looks_like_date(candidate):
            continue
        if re.fullmatch(r"[0-9\-_/]+", candidate):
            continue
        return candidate
    return cells[0] if cells else "Unknown Company"


def _pick_website(cells: List[str], links: List[str]) -> Optional[str]:
    for link in links:
        if link.startswith("http") and "linkedin.com" not in link:
            return link
    for cell in cells:
        if cell.startswith("http://") or cell.startswith("https://") or cell.startswith("www."):
            return cell if cell.startswith("http") else f"https://{cell}"
    return None


def _pick_country(cells: List[str], fallback_country: Optional[str]) -> str:
    common_countries = [
        "Germany", "USA", "United States", "France", "Japan", "Spain", "Italy", "UK",
        "United Kingdom", "Netherlands", "Canada", "Australia", "Mexico", "India",
    ]
    for cell in cells:
        for country in common_countries:
            if country.lower() in cell.lower():
                return country
    return fallback_country or "Unknown"


def _pick_city(cells: List[str], country: Optional[str]) -> Optional[str]:
    for cell in cells:
        candidate = cell.strip()
        if not candidate or len(candidate) > 40:
            continue
        if country and country.lower() in candidate.lower():
            continue
        if any(char.isdigit() for char in candidate):
            continue
        if any(keyword in candidate.lower() for keyword in ["manager", "director", "engineer", "procurement"]):
            continue
        if candidate.isupper() and len(candidate) <= 3:
            continue
        return candidate
    return None


def _pick_industry(cells: List[str]) -> Optional[str]:
    industry_keywords = [
        "manufactur", "fabrication", "machinery", "industrial", "equipment", "automation",
        "sheet metal", "trading", "distributor", "wholesale",
    ]
    for cell in cells:
        lowered = cell.lower()
        if any(keyword in lowered for keyword in industry_keywords):
            return cell[:120]
    return None


def _pick_contact_name(cells: List[str]) -> Optional[str]:
    for index, cell in enumerate(cells):
        if _looks_like_name(cell) and not _looks_like_company(cell):
            return cell
        if index > 6:
            break
    return None


def _pick_contact_title(cells: List[str]) -> Optional[str]:
    title_keywords = ["manager", "director", "head", "buyer", "procurement", "sourcing", "ceo", "founder"]
    for cell in cells:
        lowered = cell.lower()
        if any(keyword in lowered for keyword in title_keywords):
            return cell[:120]
    return None


def _pick_email(cells: List[str]) -> Optional[str]:
    for cell in cells:
        match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", cell, flags=re.I)
        if match:
            return match.group(0)
    return None


def _pick_phone(cells: List[str]) -> Optional[str]:
    for cell in cells:
        compact = re.sub(r"\s+", "", cell)
        if re.search(r"\+?[0-9][0-9\-()]{6,}", compact):
            return cell[:60]
    return None


def _pick_hs_code(cells: List[str], fallback_hs_code: Optional[str]) -> Optional[str]:
    for cell in cells:
        digits = re.sub(r"\D", "", cell)
        if 4 <= len(digits) <= 10:
            return digits
    return fallback_hs_code


def _pick_trade_date(cells: List[str]) -> str:
    for cell in cells:
        if _looks_like_date(cell):
            return cell[:40]
    return "Unknown"


def _pick_frequency(cells: List[str]) -> int:
    for cell in cells:
        digits = re.sub(r"\D", "", cell)
        if digits:
            value = int(digits)
            if 1 <= value <= 999:
                return value
    return 1


def _pick_product_description(cells: List[str]) -> Optional[str]:
    for cell in cells:
        if len(cell) > 12 and not _looks_like_date(cell) and "@" not in cell and "http" not in cell:
            return cell[:160]
    return None


def _looks_like_date(value: str) -> bool:
    return bool(re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value))


def _looks_like_name(value: str) -> bool:
    tokens = value.strip().split()
    return 1 < len(tokens) <= 4 and all(token[:1].isalpha() for token in tokens if token)


def _looks_like_company(value: str) -> bool:
    lowered = value.lower()
    return any(keyword in lowered for keyword in ["ltd", "gmbh", "inc", "co.", "llc", "company", "corporation", "corp"])
