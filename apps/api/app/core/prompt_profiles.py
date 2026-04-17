from __future__ import annotations

from typing import Dict


PROFILE_DEFINITIONS: Dict[str, dict] = {
    "general": {
        "label": "通用",
        "description": "适用于未明确区分采购规模的通用搜索和文案场景。",
        "search_focus_terms": ["supplier", "manufacturer", "buyer", "industrial"],
        "avoid_terms": [],
        "lead_discovery_prompt": (
            "请基于产品词、国家和采购信号识别潜在线索，不预设客户一定是大单或小单，"
            "优先返回与产品和地区匹配、且具备真实采购可能性的公司。"
        ),
    },
    "small_wholesale": {
        "label": "批发小单",
        "description": "适用于批发、小批量、多频次补货、试单型客户。",
        "search_focus_terms": [
            "wholesale",
            "distributor",
            "reseller",
            "small batch",
            "low moq",
            "restock",
            "flexible order",
        ],
        "avoid_terms": ["bulk order", "large volume", "mass procurement", "container order"],
        "lead_discovery_prompt": (
            "请优先识别适合批发、小单、多频次补货的海外客户，不要默认推荐大型批量采购商。"
            "重点关注批发商、分销商、经销商、中小零售批发客户，以及支持低MOQ、试单和灵活补货的客户。"
        ),
    },
    "bulk_buying": {
        "label": "大单采购",
        "description": "适用于大型采购、项目型客户和高产能需求场景。",
        "search_focus_terms": ["bulk order", "large volume", "mass procurement", "container order"],
        "avoid_terms": ["small batch", "low moq"],
        "lead_discovery_prompt": (
            "请优先识别大型项目采购商、批量采购商和高频大规模补货客户，"
            "重点关注产能需求、长期大单合作和规模型采购特征。"
        ),
    },
}


def get_profile_definition(profile_mode: str) -> dict:
    return PROFILE_DEFINITIONS.get(profile_mode, PROFILE_DEFINITIONS["general"])

