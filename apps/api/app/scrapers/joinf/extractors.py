from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def extract_business_record(raw_item: dict, fallback_country: Optional[str] = None) -> dict:
    cells = raw_item.get("cells", [])
    metadata = raw_item.get("metadata", {}) or {}
    links = metadata.get("links", []) or []
    detail = metadata.get("detail", {}) or {}

    company_name = detail.get("company_name") or _pick_company_name(cells)
    website = detail.get("website") or _pick_website(cells, links)
    country = detail.get("country") or _pick_country(cells, fallback_country)
    city = detail.get("city") or _pick_city(cells, country)
    industry = detail.get("industry") or _pick_industry(cells)
    description = detail.get("description")
    phone = detail.get("phone") or _pick_phone(cells)
    address = detail.get("address")

    # 合并列表页联系人 + 详情页联系人
    list_contacts = []
    contact_name = _pick_contact_name(cells)
    contact_title = _pick_contact_title(cells)
    contact_email = _pick_email(cells)
    contact_phone = _pick_phone(cells)
    if any([contact_name, contact_title, contact_email, contact_phone]):
        list_contacts.append({
            "name": contact_name,
            "title": contact_title,
            "email": contact_email,
            "email_type": "business" if contact_email else None,
            "confidence": "B",
            "phone": contact_phone,
        })

    detail_contacts = detail.get("contacts", []) or []
    merged_contacts = _merge_contacts(list_contacts, detail_contacts)

    return {
        "company_name": company_name,
        "country": country,
        "city": city,
        "website": website,
        "industry": industry,
        "description": description,
        "phone": phone,
        "address": address,
        "contacts": merged_contacts,
        "detail_url": links[0] if links else raw_item.get("page_url"),
    }


def extract_customs_record(raw_item: dict, fallback_hs_code: Optional[str] = None, fallback_country: Optional[str] = None) -> dict:
    cells = raw_item.get("cells", [])
    metadata = raw_item.get("metadata", {}) or {}
    links = metadata.get("links", []) or []
    detail = metadata.get("detail", {}) or {}

    # 优先从 detail（结构化数据）获取，fallback 到 cells 解析
    buyer = detail.get("buyer") or _pick_buyer(cells)
    supplier = detail.get("supplier") or _pick_supplier(cells)
    trade_date = detail.get("trade_date") or _pick_trade_date(cells)
    hs_code = detail.get("hs_code") or _pick_hs_code(cells, fallback_hs_code)
    product_description = detail.get("product_description") or _pick_product_description(cells)
    weight = detail.get("weight") or _pick_weight(cells)
    quantity = detail.get("quantity") or _pick_quantity(cells)
    amount = detail.get("amount") or _pick_amount(cells)
    frequency = detail.get("frequency") or _pick_frequency(cells)
    country = detail.get("country") or detail.get("country_cn") or _pick_country(cells, fallback_country)
    origin = detail.get("origin") or detail.get("origin_cn") or ""

    return {
        "buyer": buyer,
        "supplier": supplier,
        "trade_date": trade_date,
        "hs_code": hs_code,
        "product_description": product_description,
        "weight": weight,
        "quantity": quantity,
        "amount": amount,
        "frequency": frequency,
        "country": country,
        "origin": origin,
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
        # ★ 排除纯域名（如 "zjbsled.com"）
        if re.fullmatch(r"[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", candidate):
            continue
        # ★ 排除纯数字或 "+数字" 模式
        if re.fullmatch(r"\+?\d+", candidate):
            continue
        return candidate
    return cells[0] if cells else "Unknown Company"


def _pick_website(cells: List[str], links: List) -> Optional[str]:
    for link in links:
        # 支持 dict 格式 {"href": "...", "text": "..."}
        if isinstance(link, dict):
            href = link.get("href", "")
        else:
            href = link
        if href.startswith("http") and "linkedin.com" not in href and "joinf.com" not in href:
            return href
    for cell in cells:
        if cell.startswith("http://") or cell.startswith("https://") or cell.startswith("www."):
            url = cell if cell.startswith("http") else f"https://{cell}"
            if "joinf.com" not in url and "linkedin.com" not in url:
                return url
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


def _pick_buyer(cells: List[str]) -> str:
    for cell in cells:
        if cell.startswith("采购商:"):
            return cell[len("采购商:"):].strip()
    return ""


def _pick_supplier(cells: List[str]) -> str:
    for cell in cells:
        if cell.startswith("供应商:"):
            return cell[len("供应商:"):].strip()
    return ""


def _pick_weight(cells: List[str]) -> Optional[str]:
    for cell in cells:
        if cell.startswith("重量:"):
            return cell[len("重量:"):].strip()
    return None


def _pick_quantity(cells: List[str]) -> Optional[str]:
    for cell in cells:
        if cell.startswith("数量:"):
            return cell[len("数量:"):].strip()
    return None


def _pick_amount(cells: List[str]) -> Optional[str]:
    for cell in cells:
        if cell.startswith("金额:"):
            return cell[len("金额:"):].strip()
    return None


def _looks_like_date(value: str) -> bool:
    return bool(re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value))


def _looks_like_name(value: str) -> bool:
    tokens = value.strip().split()
    return 1 < len(tokens) <= 4 and all(token[:1].isalpha() for token in tokens if token)


def _looks_like_company(value: str) -> bool:
    lowered = value.lower()
    return any(keyword in lowered for keyword in ["ltd", "gmbh", "inc", "co.", "llc", "company", "corporation", "corp"])


def _merge_contacts(list_contacts: List[dict], detail_contacts: List[dict]) -> List[dict]:
    if not detail_contacts:
        return list_contacts
    if not list_contacts:
        return detail_contacts

    merged = list(list_contacts)
    for dc in detail_contacts:
        dc_name = (dc.get("name") or "").strip().lower()
        if not dc_name:
            continue
        is_dup = any(
            (lc.get("name") or "").strip().lower() == dc_name
            for lc in merged
        )
        if not is_dup:
            merged.append(dc)

    return merged
