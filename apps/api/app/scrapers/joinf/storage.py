from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.scrapers.joinf.models import JoinfScrapeBatch


def dump_batch(batch: JoinfScrapeBatch, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    file_path = output_dir / f"{batch.source_type}-{timestamp}.json"
    file_path.write_text(json.dumps(batch.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path

