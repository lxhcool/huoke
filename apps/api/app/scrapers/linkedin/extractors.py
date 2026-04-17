from __future__ import annotations

import re
from typing import List, Optional


def extract_company_record(raw_item: dict, fallback_country: Optional[str] = None) -> dict:
    cells = [cell.strip() for cell in raw_item.get("cells", []) if cell and cell.strip()]
    links = (raw_item.get("metadata", {}) or {}).get("links", [])

    company_name = _pick_company_name(cells)
    industry = _pick_industry(cells)
    employee_size = _pick_employee_size(cells)
    linkedin_url = _pick_linkedin_company_url(links)

    return {
        "company_name": company_name,
        "country": fallback_country or "Unknown",
        "industry": industry,
        "website": None,
        "employee_size": employee_size,
        "linkedin_url": linkedin_url,
    }


def extract_contact_record(raw_item: dict) -> dict:
    cells = [cell.strip() for cell in raw_item.get("cells", []) if cell and cell.strip()]
    links = (raw_item.get("metadata", {}) or {}).get("links", [])

    name = _pick_contact_name(cells)
    title = _pick_contact_title(cells)
    company_name = _pick_contact_company(cells)
    linkedin_url = _pick_linkedin_profile_url(links)

    return {
        "name": name,
        "title": title,
        "company_name": company_name,
        "linkedin_url": linkedin_url,
    }


def _pick_company_name(cells: List[str]) -> str:
    for cell in cells:
        candidate = cell.strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if any(flag in lowered for flag in ["followers", "employee", "connection", "results"]):
            continue
        if candidate.startswith("http"):
            continue
        if len(candidate) < 2:
            continue
        return candidate[:150]
    return "Unknown Company"


def _pick_industry(cells: List[str]) -> Optional[str]:
    industry_keywords = [
        "manufacturing",
        "machinery",
        "industrial",
        "automation",
        "wholesale",
        "import",
        "export",
        "sourcing",
    ]
    for cell in cells:
        lowered = cell.lower()
        if any(keyword in lowered for keyword in industry_keywords):
            return cell[:120]
    return None


def _pick_employee_size(cells: List[str]) -> Optional[str]:
    for cell in cells:
        lowered = cell.lower()
        if "employee" in lowered or "employees" in lowered:
            return cell[:80]
    return None


def _pick_linkedin_company_url(links: List[str]) -> Optional[str]:
    for link in links:
        if "/company/" in link:
            return link
    return None


def _pick_contact_name(cells: List[str]) -> str:
    for cell in cells:
        candidate = re.sub(r"\s+", " ", cell).strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if any(flag in lowered for flag in ["connection", "followers", "view"]):
            continue
        if len(candidate.split()) > 1 and len(candidate) <= 80:
            return candidate
    return cells[0][:80] if cells else "Unknown Contact"


def _pick_contact_title(cells: List[str]) -> str:
    title_keywords = ["manager", "director", "head", "buyer", "procurement", "sourcing", "ceo", "founder", "sales"]
    for cell in cells:
        lowered = cell.lower()
        if any(keyword in lowered for keyword in title_keywords):
            return cell[:120]
    if len(cells) >= 2:
        return cells[1][:120]
    return "Unknown Title"


def _pick_contact_company(cells: List[str]) -> Optional[str]:
    for cell in cells:
        if " at " in cell.lower():
            parts = re.split(r"\bat\b", cell, flags=re.I)
            if len(parts) >= 2:
                company_name = parts[-1].strip(" -·|")
                if company_name:
                    return company_name[:120]

    for cell in cells:
        lowered = cell.lower()
        if any(flag in lowered for flag in ["ltd", "inc", "gmbh", "llc", "company", "corp"]):
            return cell[:120]

    return None


def _pick_linkedin_profile_url(links: List[str]) -> Optional[str]:
    for link in links:
        if "/in/" in link:
            return link
    return None

