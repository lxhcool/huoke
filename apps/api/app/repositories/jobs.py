from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import List

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.raw_source_record import RawSourceRecord
from app.models.search_job import SearchJob, SearchJobSourceTask, SearchResultItem
from app.scrapers.joinf.extractors import extract_business_record, extract_customs_record
from app.scrapers.linkedin.config import LinkedinScraperConfig
from app.scrapers.linkedin.extractors import extract_company_record as extract_linkedin_company_record
from app.scrapers.linkedin.extractors import extract_contact_record as extract_linkedin_contact_record
from app.scrapers.linkedin.service import LinkedinScraperService
from app.schemas.jobs import SearchJobCreateRequest, SearchJobResponse, SearchJobResultItem, SearchJobResultsResponse, SourceTaskResponse
from app.schemas.search import ContactItem, CustomsSummary
from app.scrapers.joinf.config import JoinfScraperConfig
from app.scrapers.joinf.service import JoinfScraperService


SOURCE_SEQUENCE = ["joinf_business", "joinf_customs", "linkedin_company", "linkedin_contact"]


def create_search_job(db: Session, payload: SearchJobCreateRequest) -> SearchJobResponse:
    job = SearchJob(
        query=payload.query,
        country=payload.country,
        hs_code=payload.hs_code,
        customer_profile_mode=payload.customer_profile_mode,
        customs_required=payload.customs_required,
        limit=payload.limit,
        status="queued",
        sources_json=json.dumps(payload.sources, ensure_ascii=False),
    )
    db.add(job)
    db.flush()

    source_tasks: List[SearchJobSourceTask] = []
    for source_name in payload.sources:
        source_tasks.append(
            SearchJobSourceTask(
                job_id=job.id,
                source_name=source_name,
                task_type="search",
                status="queued",
            )
        )
    db.add_all(source_tasks)

    db.commit()
    return get_search_job(db, job.id)


def refresh_search_job(db: Session, job_id: int) -> None:
    job = db.get(SearchJob, job_id)
    if job is None:
        return

    task_statuses = [task.status for task in job.source_tasks]
    if any(status == "running" for status in task_statuses):
        job.status = "running"
    elif any(status == "queued" for status in task_statuses):
        job.status = "queued"
    elif any(status == "failed" for status in task_statuses):
        job.status = "completed_with_errors"
    else:
        job.status = "completed"

    completed_sources = {task.source_name for task in job.source_tasks if task.status == "completed"}
    terminal = all(status in {"completed", "failed"} for status in task_statuses)

    for result in job.results:
        if "linkedin_contact" in completed_sources:
            result.status = "ready"
        elif "joinf_customs" in completed_sources or "linkedin_company" in completed_sources:
            result.status = "enriching"
        elif terminal:
            result.status = "ready"
        else:
            result.status = "partial"

    job.updated_at = datetime.utcnow()
    db.commit()


def execute_search_job(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(SearchJob, job_id)
        if job is None:
            return

        ordered_tasks = sorted(
            job.source_tasks,
            key=lambda item: SOURCE_SEQUENCE.index(item.source_name) if item.source_name in SOURCE_SEQUENCE else len(SOURCE_SEQUENCE),
        )

        for task in ordered_tasks:
            _run_task(db, job, task)

        refresh_search_job(db, job_id)


def get_search_job(db: Session, job_id: int) -> SearchJobResponse:
    refresh_search_job(db, job_id)
    job = db.get(SearchJob, job_id)
    if job is None:
        raise ValueError("search job not found")
    return _serialize_job(job)


def get_search_job_results(db: Session, job_id: int) -> SearchJobResultsResponse:
    refresh_search_job(db, job_id)
    job = db.get(SearchJob, job_id)
    if job is None:
        raise ValueError("search job not found")

    items: List[SearchJobResultItem] = []

    for result in sorted(job.results, key=lambda item: item.score, reverse=True):
        base_payload = json.loads(result.base_payload_json)
        enriched_payload = json.loads(result.enriched_payload_json)
        payload = dict(base_payload)

        completed_sources = {task.source_name for task in job.source_tasks if task.status == "completed"}
        result_sources = json.loads(result.source_summary_json)
        source_names = [item["source_name"] for item in result_sources if item.get("status") == "completed"]

        if "joinf_customs" in completed_sources:
            payload["customs_summary"] = enriched_payload.get("customs_summary")
        if "linkedin_contact" in completed_sources:
            payload["contacts"] = enriched_payload.get("contacts", [])

        match_reasons = json.loads(result.match_reasons_json)
        contacts = [ContactItem(**contact) for contact in payload.get("contacts", [])]
        customs_summary = payload.get("customs_summary")

        items.append(
            SearchJobResultItem(
                id=result.id,
                company_id=result.company_id,
                company_name=payload.get("company_name"),
                country=payload.get("country"),
                city=payload.get("city"),
                website=payload.get("website"),
                industry=payload.get("industry"),
                score=result.score,
                confidence=payload.get("confidence", "B"),
                result_status=result.status,
                intent_label=result.intent_label,
                source_names=source_names,
                match_reasons=match_reasons,
                contacts=contacts,
                customs_summary=CustomsSummary(**customs_summary) if customs_summary else None,
            )
        )

    return SearchJobResultsResponse(job_id=job.id, status=job.status, total=len(items), items=items)


def _serialize_job(job: SearchJob) -> SearchJobResponse:
    return SearchJobResponse(
        id=job.id,
        query=job.query,
        country=job.country,
        hs_code=job.hs_code,
        customer_profile_mode=job.customer_profile_mode,
        customs_required=job.customs_required,
        limit=job.limit,
        status=job.status,
        sources=json.loads(job.sources_json),
        result_count=len(job.results),
        created_at=job.created_at,
        updated_at=job.updated_at,
        source_tasks=[
            SourceTaskResponse(
                id=task.id,
                source_name=task.source_name,
                task_type=task.task_type,
                status=task.status,
                error_message=task.error_message,
                started_at=task.started_at,
                finished_at=task.finished_at,
            )
            for task in sorted(job.source_tasks, key=lambda item: item.id)
        ],
    )


def _completed_source_names(tasks: List[SearchJobSourceTask]) -> List[str]:
    return [task.source_name for task in tasks if task.status == "completed"]


def _run_task(db: Session, job: SearchJob, task: SearchJobSourceTask) -> None:
    task.status = "running"
    task.started_at = datetime.utcnow()
    db.commit()

    try:
        if task.source_name == "joinf_business":
            output_path = asyncio.run(_run_joinf_scrape("business", job.query, job.country))
            _store_raw_batch(db, job.id, task.source_name, output_path)
            _sync_business_results_from_joinf_batch(db, job, output_path)
        elif task.source_name == "joinf_customs":
            output_path = asyncio.run(_run_joinf_scrape("customs", job.query, job.country))
            _store_raw_batch(db, job.id, task.source_name, output_path)
            _sync_customs_results_from_joinf_batch(db, job, output_path)
        elif task.source_name == "linkedin_company":
            output_path = asyncio.run(_run_linkedin_scrape("company", job.query, job.country))
            _store_raw_batch(db, job.id, task.source_name, output_path)
            _sync_linkedin_company_results_from_batch(db, job, output_path)
        elif task.source_name == "linkedin_contact":
            output_path = asyncio.run(_run_linkedin_scrape("contact", job.query, job.country))
            _store_raw_batch(db, job.id, task.source_name, output_path)
            _sync_linkedin_contact_results_from_batch(db, job, output_path)
        else:
            raise RuntimeError(f"unsupported source task: {task.source_name}")

        task.status = "completed"
        task.finished_at = datetime.utcnow()
        task.error_message = None
    except Exception as error:
        task.status = "failed"
        task.finished_at = datetime.utcnow()
        task.error_message = str(error)
    finally:
        db.commit()
        refresh_search_job(db, job.id)


async def _run_joinf_scrape(source_type: str, keyword: str, country: str | None) -> Path:
    config = JoinfScraperConfig()
    service = JoinfScraperService(config)

    if not config.storage_state_path.exists():
        if not config.has_credentials():
            raise RuntimeError(
                "Joinf 登录态不存在，请先在前端点击“验证登录”或执行 python -m app.scripts.joinf_capture login"
            )
        await service.ensure_login_session(allow_manual=False)

    try:
        output_path: Path
        if source_type == "business":
            output_path = await service.scrape_business_data(keyword, country)
        else:
            output_path = await service.scrape_customs_data(keyword, country)

        if _batch_item_count(output_path) <= 0:
            raise RuntimeError("自动抓取未识别到结果表格")

        return output_path
    except Exception as error:
        fallback_error_markers = [
            "未找到可点击元素",
            "element is not editable",
            "人工抓取超时",
            "当前未登录",
            "自动抓取未识别到结果表格",
        ]
        if not any(marker in str(error) for marker in fallback_error_markers):
            raise

        output_path = await service.scrape_from_manual_navigation(
            source_type=source_type,
            keyword=keyword,
            country=country,
            wait_seconds=240,
        )
        if _batch_item_count(output_path) <= 0:
            raise RuntimeError("人工抓取未识别到结果表格，请在有结果的列表页停留后重试")

        return output_path


async def _run_linkedin_scrape(source_type: str, keyword: str, country: str | None) -> Path:
    config = LinkedinScraperConfig()
    service = LinkedinScraperService(config)

    if not config.storage_state_path.exists():
        if not config.has_credentials():
            raise RuntimeError(
                "LinkedIn 登录态不存在，请先在前端点击“验证登录”或执行 python -m app.scripts.linkedin_capture login"
            )
        await service.ensure_login_session(allow_manual=False)

    if source_type == "company":
        output_path = await service.scrape_company_data(keyword, country)
    else:
        output_path = await service.scrape_contact_data(keyword, country)

    return Path(output_path)


def _store_raw_batch(db: Session, job_id: int, source_name: str, output_path: Path) -> None:
    raw_payload = output_path.read_text(encoding="utf-8")
    db.add(
        RawSourceRecord(
            job_id=job_id,
            source_name=source_name,
            record_type="batch",
            file_path=str(output_path),
            raw_payload=raw_payload,
        )
    )
    db.commit()


def _sync_business_results_from_joinf_batch(db: Session, job: SearchJob, output_path: Path) -> None:
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    items = payload.get("items", [])

    for raw_item in items[: job.limit]:
        extracted = extract_business_record(raw_item, fallback_country=job.country)
        company_name = extracted.get("company_name")
        if not company_name:
            continue

        company_id = _synthetic_company_id(job.id, raw_item.get("row_index", 0))

        base_payload = {
            "company_name": extracted.get("company_name"),
            "country": extracted.get("country"),
            "city": extracted.get("city"),
            "website": extracted.get("website"),
            "industry": extracted.get("industry"),
            "score": 70,
            "confidence": "B",
            "contacts": [],
            "customs_summary": None,
        }
        enriched_payload = {**base_payload, "contacts": extracted.get("contacts", [])}

        source_summary = [{"source_name": "joinf_business", "status": "completed"}]
        match_reasons = ["来自 Joinf 商业数据真实抓取", f"关键词：{job.query}"]
        if extracted.get("website"):
            match_reasons.append("已抓取官网链接")
        if extracted.get("contacts"):
            match_reasons.append("已抓取联系人或联系方式")

        existing = _find_result_by_company_name(job, company_name)
        if existing is None:
            db.add(
                SearchResultItem(
                    job_id=job.id,
                    company_id=company_id,
                    status="partial",
                    score=70,
                    activity_score=0,
                    intent_label="真实来源结果",
                    source_summary_json=json.dumps(source_summary, ensure_ascii=False),
                    match_reasons_json=json.dumps(match_reasons, ensure_ascii=False),
                    base_payload_json=json.dumps(base_payload, ensure_ascii=False),
                    enriched_payload_json=json.dumps(enriched_payload, ensure_ascii=False),
                )
            )
        else:
            existing.base_payload_json = json.dumps(base_payload, ensure_ascii=False)
            merged_enriched = {**json.loads(existing.enriched_payload_json), **enriched_payload}
            existing.enriched_payload_json = json.dumps(merged_enriched, ensure_ascii=False)
            existing.source_summary_json = _merge_source_summary(existing.source_summary_json, "joinf_business")
            existing.match_reasons_json = json.dumps(match_reasons, ensure_ascii=False)

    db.commit()


def _sync_customs_results_from_joinf_batch(db: Session, job: SearchJob, output_path: Path) -> None:
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    items = payload.get("items", [])

    for raw_item in items[: job.limit]:
        extracted = extract_customs_record(raw_item, fallback_hs_code=job.hs_code, fallback_country=job.country)
        company_name = extracted.get("company_name")
        if not company_name:
            continue

        customs_summary = {
            "active_label": "Joinf 海关数据已抓取",
            "last_trade_at": extracted.get("trade_date") or "Unknown",
            "hs_code": extracted.get("hs_code"),
            "frequency": extracted.get("frequency") or 1,
        }

        existing = _find_result_by_company_name(job, company_name)
        if existing is None:
            base_payload = {
                "company_name": company_name,
                "country": extracted.get("country"),
                "city": None,
                "website": None,
                "industry": extracted.get("product_description"),
                "score": 60,
                "confidence": "B",
                "contacts": [],
                "customs_summary": None,
            }
            enriched_payload = {**base_payload, "customs_summary": customs_summary}
            db.add(
                SearchResultItem(
                    job_id=job.id,
                    company_id=_synthetic_company_id(job.id, raw_item.get("row_index", 0) + 1000),
                    status="enriching",
                    score=60,
                    activity_score=customs_summary["frequency"] * 5,
                    intent_label="真实来源结果",
                    source_summary_json=json.dumps([{"source_name": "joinf_customs", "status": "completed"}], ensure_ascii=False),
                    match_reasons_json=json.dumps([
                        "来自 Joinf 海关数据真实抓取",
                        f"关键词：{job.query}",
                        f"HS Code：{customs_summary['hs_code'] or '未知'}",
                    ], ensure_ascii=False),
                    base_payload_json=json.dumps(base_payload, ensure_ascii=False),
                    enriched_payload_json=json.dumps(enriched_payload, ensure_ascii=False),
                )
            )
        else:
            enriched_payload = json.loads(existing.enriched_payload_json)
            enriched_payload["customs_summary"] = customs_summary
            existing.enriched_payload_json = json.dumps(enriched_payload, ensure_ascii=False)
            existing.activity_score = customs_summary["frequency"] * 5
            existing.score = max(existing.score, 78)
            existing.source_summary_json = _merge_source_summary(existing.source_summary_json, "joinf_customs")
            existing.match_reasons_json = json.dumps([
                "来自 Joinf 海关数据真实抓取",
                f"关键词：{job.query}",
                f"HS Code：{customs_summary['hs_code'] or '未知'}",
            ], ensure_ascii=False)

    db.commit()


def _sync_linkedin_company_results_from_batch(db: Session, job: SearchJob, output_path: Path) -> None:
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    items = payload.get("items", [])

    for raw_item in items[: job.limit]:
        extracted = extract_linkedin_company_record(raw_item, fallback_country=job.country)
        company_name = extracted.get("company_name")
        if not company_name or company_name == "Unknown Company":
            continue

        match_reasons = [
            "来自 LinkedIn 公司结果页抓取",
            f"关键词：{job.query}",
        ]
        if extracted.get("employee_size"):
            match_reasons.append(f"员工规模：{extracted['employee_size']}")

        existing = _find_result_by_company_name(job, company_name)
        if existing is None:
            base_payload = {
                "company_name": company_name,
                "country": extracted.get("country") or "Unknown",
                "city": None,
                "website": extracted.get("website"),
                "industry": extracted.get("industry"),
                "score": 62,
                "confidence": "B",
                "contacts": [],
                "customs_summary": None,
            }
            enriched_payload = {
                **base_payload,
                "linkedin_company_url": extracted.get("linkedin_url"),
                "employee_size": extracted.get("employee_size"),
            }
            db.add(
                SearchResultItem(
                    job_id=job.id,
                    company_id=_synthetic_company_id(job.id, raw_item.get("row_index", 0) + 2000),
                    status="enriching",
                    score=62,
                    activity_score=0,
                    intent_label="真实来源结果",
                    source_summary_json=json.dumps([{"source_name": "linkedin_company", "status": "completed"}], ensure_ascii=False),
                    match_reasons_json=json.dumps(match_reasons, ensure_ascii=False),
                    base_payload_json=json.dumps(base_payload, ensure_ascii=False),
                    enriched_payload_json=json.dumps(enriched_payload, ensure_ascii=False),
                )
            )
            continue

        base_payload = json.loads(existing.base_payload_json)
        enriched_payload = json.loads(existing.enriched_payload_json)
        if not base_payload.get("industry") and extracted.get("industry"):
            base_payload["industry"] = extracted.get("industry")
        if not base_payload.get("website") and extracted.get("website"):
            base_payload["website"] = extracted.get("website")
        if base_payload.get("country") in {None, "Unknown"} and extracted.get("country"):
            base_payload["country"] = extracted.get("country")

        enriched_payload.update(base_payload)
        if extracted.get("linkedin_url"):
            enriched_payload["linkedin_company_url"] = extracted.get("linkedin_url")
        if extracted.get("employee_size"):
            enriched_payload["employee_size"] = extracted.get("employee_size")

        existing.base_payload_json = json.dumps(base_payload, ensure_ascii=False)
        existing.enriched_payload_json = json.dumps(enriched_payload, ensure_ascii=False)
        existing.score = max(existing.score, 72)
        existing.source_summary_json = _merge_source_summary(existing.source_summary_json, "linkedin_company")
        existing.match_reasons_json = json.dumps(match_reasons, ensure_ascii=False)

    db.commit()


def _sync_linkedin_contact_results_from_batch(db: Session, job: SearchJob, output_path: Path) -> None:
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    items = payload.get("items", [])

    for raw_item in items[: job.limit * 2]:
        extracted = extract_linkedin_contact_record(raw_item)
        contact_name = extracted.get("name")
        company_name = extracted.get("company_name")
        if not contact_name:
            continue

        match_reasons = [
            "来自 LinkedIn 联系人结果页抓取",
            f"关键词：{job.query}",
        ]
        if extracted.get("title"):
            match_reasons.append(f"岗位：{extracted['title']}")

        contact_payload = {
            "name": contact_name,
            "title": extracted.get("title") or "Unknown Title",
            "email": None,
            "email_type": None,
            "confidence": "B",
            "linkedin_url": extracted.get("linkedin_url"),
        }

        existing = _find_result_by_company_name(job, company_name) if company_name else None
        if existing is None:
            guessed_company_name = company_name or f"LinkedIn Lead {raw_item.get('row_index', 0) + 1}"
            base_payload = {
                "company_name": guessed_company_name,
                "country": job.country or "Unknown",
                "city": None,
                "website": None,
                "industry": None,
                "score": 58,
                "confidence": "B",
                "contacts": [],
                "customs_summary": None,
            }
            enriched_payload = {
                **base_payload,
                "contacts": [contact_payload],
            }
            db.add(
                SearchResultItem(
                    job_id=job.id,
                    company_id=_synthetic_company_id(job.id, raw_item.get("row_index", 0) + 3000),
                    status="ready",
                    score=58,
                    activity_score=0,
                    intent_label="真实来源结果",
                    source_summary_json=json.dumps([{"source_name": "linkedin_contact", "status": "completed"}], ensure_ascii=False),
                    match_reasons_json=json.dumps(match_reasons, ensure_ascii=False),
                    base_payload_json=json.dumps(base_payload, ensure_ascii=False),
                    enriched_payload_json=json.dumps(enriched_payload, ensure_ascii=False),
                )
            )
            continue

        enriched_payload = json.loads(existing.enriched_payload_json)
        existing_contacts = enriched_payload.get("contacts") or []
        if not any(_same_contact(candidate, contact_payload) for candidate in existing_contacts):
            existing_contacts.append(contact_payload)
            enriched_payload["contacts"] = existing_contacts
            existing.enriched_payload_json = json.dumps(enriched_payload, ensure_ascii=False)

        existing.score = max(existing.score, 78)
        existing.source_summary_json = _merge_source_summary(existing.source_summary_json, "linkedin_contact")
        existing.match_reasons_json = json.dumps(match_reasons, ensure_ascii=False)

    db.commit()


def _find_result_by_company_name(job: SearchJob, company_name: str) -> SearchResultItem | None:
    target = company_name.strip().lower()
    for result in job.results:
        payload = json.loads(result.base_payload_json)
        if payload.get("company_name", "").strip().lower() == target:
            return result
    return None


def _merge_source_summary(source_summary_json: str, source_name: str) -> str:
    items = json.loads(source_summary_json)
    for item in items:
        if item.get("source_name") == source_name:
            item["status"] = "completed"
            return json.dumps(items, ensure_ascii=False)
    items.append({"source_name": source_name, "status": "completed"})
    return json.dumps(items, ensure_ascii=False)


def _synthetic_company_id(job_id: int, row_index: int) -> int:
    return job_id * 100000 + row_index + 1


def _same_contact(left: dict, right: dict) -> bool:
    left_name = (left.get("name") or "").strip().lower()
    right_name = (right.get("name") or "").strip().lower()
    if not left_name or left_name != right_name:
        return False

    left_title = (left.get("title") or "").strip().lower()
    right_title = (right.get("title") or "").strip().lower()
    if left_title and right_title and left_title != right_title:
        return False

    return True


def _batch_item_count(output_path: Path) -> int:
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        items = payload.get("items", [])
        if isinstance(items, list):
            return len(items)
    except Exception:
        return 0

    return 0
