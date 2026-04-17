from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class LinkedinRawRow:
    source_type: str
    page_url: str
    row_index: int
    cells: List[str] = field(default_factory=list)
    metadata: Dict[str, List[str]] = field(default_factory=dict)
    captured_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LinkedinScrapeBatch:
    source_type: str
    keyword: str
    country: Optional[str]
    items: List[LinkedinRawRow] = field(default_factory=list)
    page_snapshots: List[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "keyword": self.keyword,
            "country": self.country,
            "items": [item.to_dict() for item in self.items],
            "page_snapshots": self.page_snapshots,
            "started_at": self.started_at,
        }

