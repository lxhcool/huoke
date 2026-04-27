from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime
from pathlib import Path
from typing import List

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.raw_source_record import RawSourceRecord
from app.models.search_job import SearchJob, SearchJobSourceTask, SearchResultItem
from app.scrapers.joinf.browser_proxy import JoinfBrowserProxy
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


def _maybe_decode_b64(value: str) -> str:
    """joinf API 的邮箱字段可能是 Base64 编码，尝试解码"""
    if not value or not isinstance(value, str):
        return value or ""
    v = value.strip()
    # 简单判断：如果包含 @ 说明已经是明文
    if "@" in v:
        return v
    # 尝试 Base64 解码
    try:
        decoded = base64.b64decode(v).decode("utf-8", errors="ignore")
        if "@" in decoded:
            return decoded
    except Exception:
        pass
    return v


def _clean_social_media(raw: Any) -> list:
    """清洗社交媒体数据：只保留有 URL 的记录，去除无用字段"""
    if not raw:
        return []
    items = raw if isinstance(raw, list) else []
    result = []
    for s in items:
        if not isinstance(s, dict):
            continue
        url = s.get("snsUrl") or s.get("url") or ""
        if not url:
            continue
        result.append({
            "type": s.get("type"),
            "snsUrl": url,
            "url": url,
        })
    return result


def _clean_grade(raw: Any) -> str:
    """清洗信用评级：0.94 → 'A'，0.7 → 'B'，数字转为字母评级"""
    if not raw:
        return ""
    s = str(raw).strip()
    if s in ("-1", "0", ""):
        return ""
    # 如果是 0~1 之间的小数，转为字母评级
    try:
        v = float(s)
        if v < 0:
            return ""
        if v <= 1.0:
            if v >= 0.9:
                return "A"
            elif v >= 0.7:
                return "B"
            elif v >= 0.5:
                return "C"
            else:
                return "D"
        # 如果已经是 1-5 的数字
        return str(int(v)) if v == int(v) else s
    except (ValueError, TypeError):
        return s


def _clean_main_business(raw: Any) -> str:
    """清洗主营业务：英文关键词逗号分隔 → 去重、去空、格式化"""
    if not raw:
        return ""
    if isinstance(raw, list):
        items = [str(v).strip() for v in raw if v and str(v).strip()]
    else:
        s = str(raw).strip()
        if not s:
            return ""
        items = [p.strip() for p in s.replace(",", "，").replace("，", ",").split(",") if p.strip()]
    # 去重（不区分大小写）
    seen = set()
    unique = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return ", ".join(unique[:10])


def _ensure_str(value: Any, max_len: int = 200) -> str:
    """确保值是字符串；dict/list/None 返回空字符串"""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    s = str(value).strip()
    if s in ("-1", "0"):
        return ""
    return s[:max_len]


def _extract_contacts_from_detail(contact_detail) -> list:
    """从 joinf contact_detail 提取联系人，过滤无有效信息的记录，去重"""
    contacts = []
    seen_names = set()

    items = []
    if isinstance(contact_detail, list):
        items = contact_detail
    elif isinstance(contact_detail, dict):
        items = contact_detail.get("list", contact_detail.get("rows", contact_detail.get("records", [])))

    for cd in items:
        if not isinstance(cd, dict):
            continue
        c_email = _maybe_decode_b64(cd.get("email") or cd.get("emailAddress") or "")
        c_phone = cd.get("phone") or cd.get("telephone") or cd.get("mobile") or ""
        c_name = cd.get("name") or cd.get("contactName") or cd.get("fullName") or ""
        c_title = cd.get("title") or cd.get("position") or cd.get("jobTitle") or cd.get("role") or ""
        c_linkedin = cd.get("linkedinUrl") or ""

        # 清洗：title 可能是 -1 等无效值，转为 str 后过滤
        c_title_str = str(c_title).strip() if c_title is not None else ""
        if c_title_str in ("-1", "0", ""):
            c_title_str = ""

        c_name_str = str(c_name).strip() if c_name is not None else ""
        if c_name_str in ("-1", "0"):
            c_name_str = ""

        # 过滤：必须有邮箱或电话才算有效联系人
        if not c_email and not c_phone:
            continue

        # 去重：按名字（小写）去重
        name_key = c_name_str.strip().lower() if c_name_str else ""
        if name_key and name_key in seen_names:
            continue
        if name_key:
            seen_names.add(name_key)

        contacts.append({
            "name": c_name_str, "title": c_title_str,
            "email": c_email or None, "phone": c_phone or None,
            "linkedin_url": c_linkedin or None, "confidence": "A",
        })

    return contacts


def create_search_job(db: Session, payload: SearchJobCreateRequest) -> SearchJobResponse:
    job = SearchJob(
        query=payload.query,
        country=payload.country,
        hs_code=payload.hs_code,
        customer_profile_mode=payload.customer_profile_mode,
        customs_required=payload.customs_required,
        limit=payload.limit,
        min_score=payload.min_score,
        status="queued",
        sources_json=json.dumps(payload.sources, ensure_ascii=False),
        ai_config_json=json.dumps(payload.ai_config, ensure_ascii=False) if payload.ai_config else None,
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
            # ★ 每个任务开始前重新读取 job 状态，检查是否已取消
            db.refresh(job)
            if job.status == "cancelled":
                print(f"[Job {job_id}] 已取消，停止执行剩余任务")
                # 将所有未完成的 task 标记为 cancelled
                for t in job.source_tasks:
                    if t.status in ("queued", "running"):
                        t.status = "cancelled"
                db.commit()
                return
            
            _run_task(db, job, task)

        # 再次检查取消状态
        db.refresh(job)
        if job.status != "cancelled":
            refresh_search_job(db, job_id)


def cancel_search_job(db: Session, job_id: int) -> SearchJobResponse:
    """取消搜索任务 — 将 job 状态设为 cancelled，后台循环会检测到并停止"""
    from app.scrapers.joinf.service import request_cancel
    
    job = db.get(SearchJob, job_id)
    if job is None:
        raise ValueError("search job not found")
    
    if job.status in ("completed", "failed", "cancelled"):
        return _serialize_job(job)
    
    job.status = "cancelled"
    db.commit()
    
    # ★ 设置全局取消信号，让正在运行的 scraper 能立即检测到
    request_cancel(job_id)
    print(f"[Job {job_id}] 已标记为 cancelled，全局取消信号已设置")
    
    return _serialize_job(job)


def get_search_job(db: Session, job_id: int) -> SearchJobResponse:
    job = db.get(SearchJob, job_id)
    if job is None:
        raise ValueError("search job not found")
    try:
        refresh_search_job(db, job_id)
        db.refresh(job)
    except Exception:
        db.rollback()
    return _serialize_job(job)


def get_search_job_results(db: Session, job_id: int) -> SearchJobResultsResponse:
    # ★ 纯只读查询，不做任何 commit / refresh
    db.expire_on_commit = False

    job = db.get(SearchJob, job_id)
    if job is None:
        raise ValueError("search job not found")

    # 判断是否运行中
    is_running = False
    try:
        task_statuses = [task.status for task in job.source_tasks]
        is_running = any(s in ("running", "queued") for s in task_statuses)
    except Exception:
        db.rollback()
        try:
            job = db.get(SearchJob, job_id)
            if job is None:
                raise ValueError("search job not found")
            task_statuses = [task.status for task in job.source_tasks]
            is_running = any(s in ("running", "queued") for s in task_statuses)
        except Exception:
            is_running = True  # 读取失败时假设还在运行

    # ★ 不再调用 refresh_search_job（它会 commit，和并发读冲突）
    # 仅在 job 已终态且 status 字段还是 running 时做一次轻量更新
    job_status = job.status
    if not is_running and job_status in ("running", "queued"):
        try:
            if any(s == "failed" for s in task_statuses):
                job.status = "completed_with_errors"
            else:
                job.status = "completed"
            job_status = job.status
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

    # ★ 用原始查询获取结果，避免 ORM 懒加载 + session 过期问题
    from app.models.search_job import SearchResultItem as ResultModel
    try:
        result_rows = db.query(ResultModel).filter(ResultModel.job_id == job_id).order_by(ResultModel.score.desc()).all()
    except Exception:
        db.rollback()
        try:
            result_rows = db.query(ResultModel).filter(ResultModel.job_id == job_id).order_by(ResultModel.score.desc()).all()
        except Exception:
            result_rows = []

    # 获取已完成的 source 列表
    completed_sources: set = set()
    try:
        completed_sources = {task.source_name for task in job.source_tasks if task.status == "completed"}
    except Exception:
        try:
            db.rollback()
            job = db.get(SearchJob, job_id)
            if job:
                completed_sources = {task.source_name for task in job.source_tasks if task.status == "completed"}
        except Exception:
            pass

    items: List[SearchJobResultItem] = []

    for result in result_rows:
        base_payload = json.loads(result.base_payload_json)
        enriched_payload = json.loads(result.enriched_payload_json)
        payload = dict(base_payload)

        result_sources = json.loads(result.source_summary_json)
        source_names = [item["source_name"] for item in result_sources if item.get("status") == "completed"]

        if "joinf_customs" in completed_sources:
            payload["customs_summary"] = enriched_payload.get("customs_summary")
        if "linkedin_contact" in completed_sources:
            # linkedin_contact 可能带来额外联系人，合并而非覆盖
            linkedin_contacts = enriched_payload.get("contacts", [])
            if linkedin_contacts:
                existing_contacts = payload.get("contacts", [])
                existing_names = {c.get("name", "").strip().lower() for c in existing_contacts if c.get("name")}
                for lc in linkedin_contacts:
                    if lc.get("name", "").strip().lower() not in existing_names:
                        existing_contacts.append(lc)
                payload["contacts"] = existing_contacts

        # ★ 关键修复：始终从 enriched_payload 获取 contacts
        # enriched_payload 中包含了流式写入时存入的联系人数据，
        # 不能因为 linkedin_contact 未完成就不返回
        if "contacts" not in payload:
            payload["contacts"] = enriched_payload.get("contacts", [])

        match_reasons = json.loads(result.match_reasons_json)
        def _sanitize_contact(c: dict) -> dict:
            """确保 ContactItem 各字段类型正确，避免 Pydantic string_type 验证错误"""
            out = {}
            for k, v in c.items():
                if v is None:
                    out[k] = None
                elif isinstance(v, str):
                    out[k] = v
                else:
                    out[k] = str(v)
            return out

        contacts = [ContactItem(**_sanitize_contact(c)) for c in payload.get("contacts", [])]
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
                main_business=payload.get("main_business"),
                phone=payload.get("phone"),
                address=payload.get("address"),
                description=payload.get("description"),
                employee_size=payload.get("employee_size"),
                email_count=payload.get("email_count"),
                linkedin_url=payload.get("linkedin_company_url") or payload.get("linkedin_url"),
                website_logo=payload.get("website_logo"),
                grade=payload.get("grade"),
                star=payload.get("star") if payload.get("star") is None else float(payload["star"]),
                social_media=payload.get("social_media"),
                score=result.score,
                confidence=payload.get("confidence", "B"),
                result_status=result.status,
                intent_label=result.intent_label,
                source_names=source_names,
                match_reasons=match_reasons,
                contacts=contacts,
                customs_summary=CustomsSummary(**customs_summary) if customs_summary else None,
                ai_summary=enriched_payload.get("ai_summary"),
            )
        )

    return SearchJobResultsResponse(job_id=job.id, status=job_status, total=len(items), items=items)


def _serialize_job(job: SearchJob) -> SearchJobResponse:
    return SearchJobResponse(
        id=job.id,
        query=job.query,
        country=job.country,
        hs_code=job.hs_code,
        customer_profile_mode=job.customer_profile_mode,
        customs_required=job.customs_required,
        limit=job.limit,
        min_score=job.min_score,
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
    # ★ 检查 job 是否已取消
    db.refresh(job)
    if job.status == "cancelled":
        task.status = "cancelled"
        db.commit()
        print(f"[Job {job.id}] 任务 {task.source_name} 因取消而跳过")
        return

    task.status = "running"
    task.started_at = datetime.utcnow()
    db.commit()

    # uvicorn sets WindowsSelectorEventLoopPolicy on Windows, which breaks
    # asyncio.create_subprocess_exec (needed by Playwright). Restore the
    # ProactorEventLoopPolicy so asyncio.run() works correctly.
    import sys
    if sys.platform == "win32":
        import asyncio as _asyncio
        _asyncio.set_event_loop_policy(_asyncio.WindowsProactorEventLoopPolicy())

    try:
        # 从 job 中解析 AI 配置（前端 localStorage 传入）
        ai_config: dict | None = None
        if job.ai_config_json:
            try:
                ai_config = json.loads(job.ai_config_json)
                print(f"=== [DEBUG] Job {job.id} AI config loaded: has_key={bool(ai_config.get('api_key'))}, model={ai_config.get('model', 'N/A')}")
            except Exception as e:
                print(f"=== [DEBUG] Job {job.id} ai_config_json parse FAILED: {e}")
                ai_config = None
        else:
            print(f"=== [DEBUG] Job {job.id} NO ai_config_json in DB")

        if task.source_name == "joinf_business":
            # ★ 流式处理：每条结果即时写入 DB，前端可实时看到
            output_path = asyncio.run(_run_joinf_api_scrape_streaming(
                job_id=job.id, keyword=job.query, country=job.country, ai_config=ai_config,
                limit=job.limit, min_score=job.min_score,
            ))
        elif task.source_name == "joinf_customs":
            output_path = asyncio.run(_run_joinf_customs_api_scrape_streaming(
                job_id=job.id, keyword=job.query, country=job.country, ai_config=ai_config,
                limit=job.limit,
            ))
        elif task.source_name == "linkedin_company":
            output_path = asyncio.run(_run_linkedin_scrape("company", job.query, job.country, ai_config))
            _store_raw_batch(db, job.id, task.source_name, output_path)
            _sync_linkedin_company_results_from_batch(db, job, output_path)
        elif task.source_name == "linkedin_contact":
            output_path = asyncio.run(_run_linkedin_scrape("contact", job.query, job.country, ai_config))
            _store_raw_batch(db, job.id, task.source_name, output_path)
            _sync_linkedin_contact_results_from_batch(db, job, output_path)
        else:
            raise RuntimeError(f"unsupported source task: {task.source_name}")

        task.status = "completed"
        task.finished_at = datetime.utcnow()
        task.error_message = None

        # ★ 如果 job 已被取消，将 task 标记为 cancelled
        db.refresh(job)
        if job.status == "cancelled":
            task.status = "cancelled"

    except Exception as error:
        task.status = "failed"
        task.finished_at = datetime.utcnow()
        task.error_message = str(error)
    finally:
        db.commit()
        refresh_search_job(db, job.id)


async def _run_joinf_api_scrape_streaming(
    job_id: int, keyword: str, country: str | None, ai_config: dict | None = None,
    limit: int = 100, min_score: int = 0,
) -> Path:
    """流式处理 Joinf 搜索 — 每条结果即时写入 DB"""
    from app.scrapers.joinf.config import JoinfScraperConfig
    from app.scrapers.joinf.extractors import extract_business_record
    from app.services.ai_extractor import AIExtractor

    config = JoinfScraperConfig()
    proxy = JoinfBrowserProxy(config, ai_config=ai_config)

    # ★ 初始化 AIExtractor 用于商业数据总结
    ai_extractor_biz: Optional[AIExtractor] = None
    if ai_config and ai_config.get("api_key"):
        try:
            ai_extractor_biz = AIExtractor(
                api_key=ai_config["api_key"],
                base_url=ai_config.get("base_url", ""),
                model=ai_config.get("model", ""),
            )
        except Exception as e:
            print(f"[JoinfApi] AIExtractor(商业) 初始化失败: {e}")

    # ★ 根据 limit 动态计算分页参数
    page_size = 20
    max_pages = max(1, (limit + page_size - 1) // page_size)  # 向上取整
    max_pages = min(max_pages, 50)  # 最多50页，防止无限翻页

    print(f"[JoinfApi] 开始流式浏览器代理搜索: keyword={keyword}, country={country}, job_id={job_id}, min_score={min_score}")

    written_count = 0

    async def _on_item_ready(raw_row) -> None:
        """每处理完一条结果，立即写入 DB"""
        nonlocal written_count
        with SessionLocal() as db:
            job = db.get(SearchJob, job_id)
            if job is None or job.status == "cancelled":
                return

            metadata = raw_row.metadata or {}

            # ★ 评分过滤：如果 AI 评分低于 min_score，跳过不写入
            ai_eval = metadata.get("ai_evaluation", {})
            ai_score = ai_eval.get("match_score", 0)
            if min_score > 0 and ai_score > 0 and ai_score < min_score:
                print(f"[JoinfApi] 跳过低分项: {metadata.get('company_name', 'N/A')} (score={ai_score} < min_score={min_score})")
                return

            api_raw = metadata.get("api_raw", {})

            structured_name = metadata.get("company_name", "")
            structured_website = metadata.get("website", "")
            structured_country = metadata.get("country", "")
            structured_city = metadata.get("city") or ""
            structured_industry = metadata.get("industry") or ""
            structured_main_business = metadata.get("main_business") or ""
            structured_description = metadata.get("description") or ""
            structured_phone = metadata.get("phone") or ""
            structured_address = metadata.get("address") or ""
            structured_email_count = metadata.get("email_count")
            structured_website_logo = metadata.get("website_logo") or ""
            structured_grade = metadata.get("grade") or ""
            structured_star = metadata.get("star")
            structured_social_media = metadata.get("social_media")

            extracted = extract_business_record(raw_row.to_dict(), fallback_country=country)
            company_name = structured_name or extracted.get("company_name")
            if not company_name:
                return

            if structured_country and structured_country.strip().lower() == company_name.strip().lower():
                structured_country = ""

            company_id = _synthetic_company_id(job_id, raw_row.row_index)

            # AI 评估
            ai_eval = metadata.get("ai_evaluation", {})
            ai_score = ai_eval.get("match_score", 0)
            ai_customer_type = ai_eval.get("customer_type", "")
            ai_match_reason = ai_eval.get("match_reason", "")
            ai_products = ai_eval.get("products", [])
            ai_contact = ai_eval.get("contact_info", {})
            ai_description = ai_eval.get("description")
            ai_country = ai_eval.get("country")
            ai_website = ai_eval.get("website")

            base_payload = {
                "company_name": company_name,
                "country": structured_country or extracted.get("country") or ai_country or "",
                "city": structured_city or extracted.get("city") or "",
                "website": structured_website or extracted.get("website") or ai_website or "",
                "industry": structured_industry or extracted.get("industry") or "",
                "main_business": _clean_main_business(structured_main_business),
                "phone": _ensure_str(structured_phone or extracted.get("phone") or ai_contact.get("phone")),
                "address": _ensure_str(structured_address or extracted.get("address") or ai_contact.get("address")),
                "description": ai_description or structured_description or extracted.get("description") or "",
                "email_count": structured_email_count,
                "products": ai_products,
                "website_logo": structured_website_logo,
                "grade": _clean_grade(structured_grade),
                "star": structured_star,
                "social_media": _clean_social_media(structured_social_media),
            }

            if ai_score > 0:
                score = ai_score
            elif api_raw:
                score = 60
            else:
                score = 50
            confidence = "A" if score >= 70 else ("B" if score >= 40 else "C")

            # 联系人
            contacts = extracted.get("contacts", [])
            if ai_contact.get("email") or ai_contact.get("phone"):
                contacts.append({
                    "name": "", "title": ai_customer_type or "",
                    "email": ai_contact.get("email"), "phone": ai_contact.get("phone"),
                    "confidence": confidence,
                })

            # 从 contact_detail 提取真实联系人（仅保留有邮箱或电话的，去重）
            contact_detail = metadata.get("contact_detail")
            if contact_detail:
                detail_contacts = _extract_contacts_from_detail(contact_detail)
                contacts.extend(detail_contacts)

            # sns_detail 补充社交媒体
            sns_detail = metadata.get("sns_detail")
            if sns_detail:
                if structured_social_media is None:
                    structured_social_media = []
                if isinstance(sns_detail, list):
                    structured_social_media.extend(sns_detail)
                elif isinstance(sns_detail, dict):
                    for s in sns_detail.get("list", sns_detail.get("rows", [])):
                        structured_social_media.append(s)
                base_payload["social_media"] = structured_social_media

            enriched_payload = {**base_payload, "contacts": contacts}

            # ★ AI 总结（商业数据）
            if ai_extractor_biz:
                try:
                    biz_input_parts = [
                        f"公司名：{company_name}",
                        f"国家：{structured_country or extracted.get('country', '')}",
                        f"行业：{structured_industry or extracted.get('industry', '')}",
                        f"主营业务：{structured_main_business or extracted.get('main_business', '')}",
                        f"简介：{structured_description or extracted.get('description', '')}"[:200],
                    ]
                    biz_input_text = "\n".join(p for p in biz_input_parts if p and not p.endswith("："))
                    biz_summary_result = await asyncio.wait_for(
                        ai_extractor_biz._call(
                            system_prompt=(
                                "你是国际贸易B2B客户分析专家。根据公司基本信息，生成一条简短的中文总结（50字以内），"
                                "概括这家公司的核心业务和潜在客户价值。直接返回 JSON，不加 markdown。"
                            ),
                            user_content=f"用户搜索的产品关键词：{keyword}\n\n公司信息：\n{biz_input_text}\n\n请生成总结。",
                            schema={
                                "type": "object",
                                "properties": {
                                    "ai_summary": {
                                        "type": "string",
                                        "description": "总结（50字以内，概括公司核心业务和潜在客户价值）",
                                    },
                                },
                                "required": ["ai_summary"],
                            },
                            max_tokens=256,
                        ),
                        timeout=15.0,
                    )
                    if biz_summary_result and biz_summary_result.get("ai_summary"):
                        enriched_payload["ai_summary"] = biz_summary_result["ai_summary"]
                        print(f"[JoinfApi] AI 总结(商业): {company_name} → {biz_summary_result['ai_summary']}")
                except asyncio.TimeoutError:
                    print(f"[JoinfApi] AI 总结(商业)超时: {company_name}")
                except Exception as e:
                    print(f"[JoinfApi] AI 总结(商业)异常: {company_name}: {e}")

            match_reasons = [f"关键词：{keyword}"]
            if ai_match_reason:
                match_reasons.insert(0, ai_match_reason)
            if ai_customer_type:
                match_reasons.append(f"客户类型：{ai_customer_type}")
            if ai_products:
                match_reasons.append(f"经营产品：{', '.join(str(p) for p in ai_products[:5])}")
            if structured_website or ai_website:
                match_reasons.append("已获取官网链接")
            if contacts:
                contact_emails = [c for c in contacts if c.get("email")]
                contact_phones = [c for c in contacts if c.get("phone")]
                if contact_emails:
                    match_reasons.append(f"已获取 {len(contact_emails)} 个联系人邮箱")
                if contact_phones:
                    match_reasons.append(f"已获取 {len(contact_phones)} 个联系人电话")
            existing = _find_result_by_company_name(job, company_name)
            if existing is None:
                db.add(SearchResultItem(
                    job_id=job.id, company_id=company_id,
                    status="partial", score=score, activity_score=0,
                    intent_label="真实来源结果",
                    source_summary_json=json.dumps([{"source_name": "joinf_business", "status": "completed"}], ensure_ascii=False),
                    match_reasons_json=json.dumps(match_reasons, ensure_ascii=False),
                    base_payload_json=json.dumps(base_payload, ensure_ascii=False),
                    enriched_payload_json=json.dumps(enriched_payload, ensure_ascii=False),
                ))
            else:
                existing.base_payload_json = json.dumps(base_payload, ensure_ascii=False)
                merged_enriched = {**json.loads(existing.enriched_payload_json), **enriched_payload}
                existing.enriched_payload_json = json.dumps(merged_enriched, ensure_ascii=False)
                existing.source_summary_json = _merge_source_summary(existing.source_summary_json, "joinf_business")
                existing.match_reasons_json = json.dumps(match_reasons, ensure_ascii=False)
                existing.score = max(existing.score, score)

            db.commit()
            written_count += 1
            print(f"[JoinfApi] 流式写入第 {written_count} 条: {company_name} (score={score})")

    output_path = await proxy.search_business(
        keyword=keyword, country=country, max_pages=max_pages, page_size=page_size,
        job_id=job_id, on_item_ready=_on_item_ready, min_score=min_score,
    )

    # ★ 如果已被取消，直接返回不报错
    from app.scrapers.joinf.service import is_cancelled
    if is_cancelled(job_id):
        print(f"[JoinfApi] 流式搜索已取消: {written_count} 条已写入 DB")
        return output_path

    if written_count <= 0 and _batch_item_count(output_path) <= 0:
        raise RuntimeError("Joinf 搜索未返回结果")

    # 保存原始 batch 文件（备份）
    _store_raw_batch(SessionLocal(), job_id, "joinf_business", output_path)

    print(f"[JoinfApi] 流式搜索完成: {written_count} 条已写入 DB, 原始文件: {output_path}")
    return output_path


async def _run_joinf_scrape(source_type: str, keyword: str, country: str | None, ai_config: dict | None = None, job_id: int = 0) -> Path:
    import logging
    from app.scrapers.joinf.service import is_cancelled, clear_cancel
    logger = logging.getLogger("joinf_scrape")
    print(f"=== [DEBUG] _run_joinf_scrape called: source={source_type}, ai_config={'PRESENT' if ai_config else 'NONE'}, job_id={job_id}")
    config = JoinfScraperConfig()
    service = JoinfScraperService(config, ai_config=ai_config)

    logger.info(f"Starting Joinf {source_type} scrape: keyword={keyword}, country={country}")
    logger.info(f"Storage state exists: {config.storage_state_path.exists()} at {config.storage_state_path}")

    if not config.storage_state_path.exists():
        if not config.has_credentials():
            raise RuntimeError(
                "Joinf 登录态不存在，请先在前端点击「验证登录」"
            )
        await service.ensure_login_session(allow_manual=False)

    try:
        output_path: Path
        if source_type == "business":
            output_path = await service.scrape_business_data(keyword, country, job_id=job_id)
        else:
            output_path = await service.scrape_customs_data(keyword, country, job_id=job_id)

        # ★ 如果已被取消，不报错直接返回
        if job_id and is_cancelled(job_id):
            logger.info(f"Joinf {source_type} scrape 已取消")
            return output_path

        if _batch_item_count(output_path) <= 0:
            raise RuntimeError("自动抓取未识别到结果表格")

        logger.info(f"Joinf {source_type} scrape completed: {output_path}")
        if job_id:
            clear_cancel(job_id)
        return output_path
    except Exception as error:
        logger.warning(f"Joinf {source_type} auto-scrape failed: {error}")
        
        # ★ 浏览器断开/已关闭 → 不再尝试人工模式（浏览器已不可用）
        browser_dead_markers = [
            "Target page, context or browser has been closed",
            "Connection closed",
            "browser has been closed",
            "Browser closed",
        ]
        if any(marker in str(error) for marker in browser_dead_markers):
            logger.warning(f"浏览器已断开，不再尝试人工模式: {error}")
            raise
        
        fallback_error_markers = [
            "未找到可点击元素",
            "element is not editable",
            "人工抓取超时",
            "当前未登录",
            "自动抓取未识别到结果表格",
            "Timeout",
            "Navigation",
        ]
        if not any(marker in str(error) for marker in fallback_error_markers):
            raise

        logger.info(f"Attempting manual navigation fallback for {source_type}")
        output_path = await service.scrape_from_manual_navigation(
            source_type=source_type,
            keyword=keyword,
            country=country,
            wait_seconds=240,
        )
        if _batch_item_count(output_path) <= 0:
            raise RuntimeError("人工抓取未识别到结果表格，请在有结果的列表页停留后重试")

        return output_path


async def _run_linkedin_scrape(source_type: str, keyword: str, country: str | None, ai_config: dict | None = None) -> Path:
    config = LinkedinScraperConfig()
    service = LinkedinScraperService(config)

    if not config.storage_state_path.exists():
        if not config.has_credentials():
            raise RuntimeError(
                "LinkedIn 登录态不存在，请先在前端点击「验证登录」"
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
        metadata = raw_item.get("metadata", {}) or {}

        # ★ 优先用结构化提取的数据（API 返回或 AI 映射）
        # API 方式的 metadata 中有完整的结构化字段
        api_raw = metadata.get("api_raw", {})

        structured_name = metadata.get("company_name", "")
        structured_website = metadata.get("website", "")
        structured_country = metadata.get("country", "")
        structured_city = metadata.get("city") or ""
        structured_industry = metadata.get("industry") or ""
        structured_main_business = metadata.get("main_business") or ""
        structured_description = metadata.get("description") or ""
        structured_phone = metadata.get("phone") or ""
        structured_address = metadata.get("address") or ""
        structured_email_count = metadata.get("email_count")
        structured_website_logo = metadata.get("website_logo") or ""
        structured_grade = metadata.get("grade") or ""
        structured_star = metadata.get("star")
        structured_social_media = metadata.get("social_media")

        company_name = structured_name or extracted.get("company_name")
        if not company_name:
            continue

        # ★ 验证 country：如果 AI 映射的 country 与 company_name 相同，说明映射错误
        if structured_country and structured_country.strip().lower() == company_name.strip().lower():
            structured_country = ""

        company_id = _synthetic_company_id(job.id, raw_item.get("row_index", 0))

        # ★ 从 AI 评估结果中获取匹配度和客户画像
        ai_eval = metadata.get("ai_evaluation", {})
        ai_score = ai_eval.get("match_score", 0)
        ai_customer_type = ai_eval.get("customer_type", "")
        ai_match_reason = ai_eval.get("match_reason", "")
        ai_products = ai_eval.get("products", [])
        ai_contact = ai_eval.get("contact_info", {})
        ai_description = ai_eval.get("description")
        ai_country = ai_eval.get("country")
        ai_website = ai_eval.get("website")

        base_payload = {
            "company_name": company_name,
            "country": structured_country or extracted.get("country") or ai_country or "",
            "city": structured_city or extracted.get("city") or "",
            "website": structured_website or extracted.get("website") or ai_website or "",
            "industry": structured_industry or extracted.get("industry") or "",
            "main_business": _clean_main_business(structured_main_business),
            "phone": _ensure_str(structured_phone or extracted.get("phone") or ai_contact.get("phone")),
            "address": _ensure_str(structured_address or extracted.get("address") or ai_contact.get("address")),
            "description": ai_description or structured_description or extracted.get("description") or "",
            "email_count": structured_email_count,
            "products": ai_products,
            "website_logo": structured_website_logo,
            "grade": _clean_grade(structured_grade),
            "star": structured_star,
            "social_media": _clean_social_media(structured_social_media),
        }

        # ★ API 数据的 score 以 AI 评估为主，无 AI 评估时给较高默认分（API 数据本身更可靠）
        if ai_score > 0:
            score = ai_score
        elif api_raw:
            score = 60  # API 数据可靠性高于 DOM 抓取
        else:
            score = 50
        confidence = "A" if score >= 70 else ("B" if score >= 40 else "C")

        # 联系人
        contacts = extracted.get("contacts", [])
        if ai_contact.get("email") or ai_contact.get("phone"):
            contacts.append({
                "name": "",
                "title": ai_customer_type or "",
                "email": ai_contact.get("email"),
                "phone": ai_contact.get("phone"),
                "confidence": confidence,
            })

        # ★ 从 contact_detail（selectContactBvdIdList 接口）提取真实联系人（仅保留有邮箱或电话的，去重）
        contact_detail = metadata.get("contact_detail")
        if contact_detail:
            detail_contacts = _extract_contacts_from_detail(contact_detail)
            contacts.extend(detail_contacts)

        # ★ 从 sns_detail（selectSnsByBvdId 接口）提取更多社交媒体
        sns_detail = metadata.get("sns_detail")
        if sns_detail:
            if structured_social_media is None:
                structured_social_media = []
            if isinstance(sns_detail, list):
                structured_social_media.extend(sns_detail)
            elif isinstance(sns_detail, dict):
                for s in sns_detail.get("list", sns_detail.get("rows", [])):
                    structured_social_media.append(s)
            base_payload["social_media"] = structured_social_media

        enriched_payload = {**base_payload, "contacts": contacts}

        source_summary = [{"source_name": "joinf_business", "status": "completed"}]
        match_reasons = [f"关键词：{job.query}"]
        if ai_match_reason:
            match_reasons.insert(0, ai_match_reason)
        if ai_customer_type:
            match_reasons.append(f"客户类型：{ai_customer_type}")
        if ai_products:
            match_reasons.append(f"经营产品：{', '.join(str(p) for p in ai_products[:5])}")
        if structured_website or ai_website:
            match_reasons.append("已获取官网链接")
        if ai_contact.get("email"):
            match_reasons.append("已获取邮箱")
        if ai_contact.get("phone") or structured_phone:
            match_reasons.append("已获取电话")
        if contacts:
            contact_emails = [c for c in contacts if c.get("email")]
            contact_phones = [c for c in contacts if c.get("phone")]
            if contact_emails:
                match_reasons.append(f"已获取 {len(contact_emails)} 个联系人邮箱")
            if contact_phones:
                match_reasons.append(f"已获取 {len(contact_phones)} 个联系人电话")
        existing = _find_result_by_company_name(job, company_name)
        if existing is None:
            db.add(
                SearchResultItem(
                    job_id=job.id,
                    company_id=company_id,
                    status="partial",
                    score=score,
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
            # 取最高分
            existing.score = max(existing.score, score)

    db.commit()


async def _run_joinf_customs_api_scrape_streaming(
    job_id: int, keyword: str, country: str | None, ai_config: dict | None = None,
    limit: int = 100,
) -> Path:
    """流式处理 Joinf 海关数据 — 每条结果即时写入 DB"""
    from app.scrapers.joinf.config import JoinfScraperConfig
    from app.services.ai_extractor import AIExtractor

    config = JoinfScraperConfig()
    proxy = JoinfBrowserProxy(config, ai_config=ai_config)

    # 初始化 AI 提取器（用于润色产品描述 + 生成总结）
    ai_extractor: Optional[AIExtractor] = None
    if ai_config and ai_config.get("api_key"):
        try:
            ai_extractor = AIExtractor(
                api_key=ai_config["api_key"],
                base_url=ai_config.get("base_url", "https://api.siliconflow.cn/v1"),
                model=ai_config.get("model", "Qwen/Qwen3-8B"),
            )
        except Exception as e:
            print(f"[JoinfCustomsApi] AIExtractor 初始化失败: {e}")

    page_size = 20
    max_pages = max(1, (limit + page_size - 1) // page_size)
    max_pages = min(max_pages, 50)

    print(f"[JoinfCustomsApi] 开始流式海关数据搜索: keyword={keyword}, country={country}, job_id={job_id}")

    written_count = 0

    async def _ai_summarize_customs(customs_data: dict) -> dict:
        """AI 润色产品描述 + 生成总结，返回更新后的 customs_data"""
        if not ai_extractor or not ai_extractor._available():
            return customs_data

        product_desc = customs_data.get("product_description", "")
        buyer = customs_data.get("buyer", "")
        supplier = customs_data.get("supplier", "")
        hs_code = customs_data.get("hs_code", "")
        origin = customs_data.get("origin", "")

        # 构建输入文本
        input_parts = [
            f"采购商：{buyer}",
            f"供应商：{supplier}" if supplier else "",
            f"HS编码：{hs_code}" if hs_code else "",
            f"原产国：{origin}" if origin else "",
            f"产品描述（原始）：{product_desc}" if product_desc else "",
            f"重量：{customs_data.get('weight', '')}",
            f"数量：{customs_data.get('quantity', '')}",
            f"金额：{customs_data.get('amount', '')}",
        ]
        input_text = "\n".join(p for p in input_parts if p)

        try:
            summary_result = await asyncio.wait_for(
                ai_extractor._call(
                    system_prompt=(
                        "你是国际贸易海关数据分析专家。用户给你一条海关进出口记录的原始数据。\n"
                        "你需要：\n"
                        "1. 将原始产品描述润色为通顺、专业的中文产品描述（保留关键规格和英文术语）\n"
                        "2. 生成一条简短的 AI 总结（中文，50字以内），概括这笔交易的核心信息\n"
                        "直接返回 JSON，不加 markdown。"
                    ),
                    user_content=(
                        f"用户搜索的产品关键词：{keyword}\n\n"
                        f"海关记录原始数据：\n{input_text}\n\n"
                        f"请润色产品描述并生成总结。"
                    ),
                    schema={
                        "type": "object",
                        "properties": {
                            "product_description_polished": {
                                "type": "string",
                                "description": "润色后的产品描述（中文为主，保留专业英文术语如LED、HS编码等）",
                            },
                            "ai_summary": {
                                "type": "string",
                                "description": "AI 总结（50字以内，概括这笔交易的核心信息，如：采购商从某国进口某类产品）",
                            },
                        },
                        "required": ["product_description_polished", "ai_summary"],
                    },
                    max_tokens=1024,
                ),
                timeout=30.0,
            )
            if summary_result:
                if summary_result.get("product_description_polished"):
                    customs_data["product_description"] = summary_result["product_description_polished"]
                if summary_result.get("ai_summary"):
                    customs_data["ai_summary"] = summary_result["ai_summary"]
                print(f"[JoinfCustomsApi] AI 总结: {buyer} → {summary_result.get('ai_summary', 'N/A')}")
        except asyncio.TimeoutError:
            print(f"[JoinfCustomsApi] AI 总结超时: {buyer}")
        except Exception as e:
            print(f"[JoinfCustomsApi] AI 总结异常: {buyer}: {e}")

        return customs_data

    async def _on_item_ready(raw_row) -> None:
        """每处理完一条海关结果，立即写入 DB"""
        nonlocal written_count
        with SessionLocal() as db:
            job = db.get(SearchJob, job_id)
            if job is None or job.status == "cancelled":
                return

            metadata = raw_row.metadata or {}
            api_raw = metadata.get("api_raw", {})

            extracted = extract_customs_record(raw_row.to_dict(), fallback_hs_code=job.hs_code, fallback_country=job.country)
            buyer = extracted.get("buyer") or metadata.get("buyer", "")
            if not buyer:
                return

            company_id = _synthetic_company_id(job_id, raw_row.row_index + 1000)

            customs_summary = {
                "active_label": "海关数据已抓取",
                "trade_date": extracted.get("trade_date") or "Unknown",
                "hs_code": extracted.get("hs_code"),
                "frequency": extracted.get("frequency") or 1,
                "buyer": buyer,
                "supplier": extracted.get("supplier") or "",
                "product_description": extracted.get("product_description") or "",
                "weight": extracted.get("weight") or "",
                "quantity": extracted.get("quantity") or "",
                "amount": extracted.get("amount") or "",
                "origin": extracted.get("origin") or "",
            }

            # AI 润色产品描述 + 生成总结
            customs_summary = await _ai_summarize_customs(customs_summary)

            # 海关数据默认评分 60（有海关交易记录 = 有采购需求）
            score = 60
            confidence = "B"

            base_payload = {
                "company_name": buyer,
                "country": extracted.get("country") or metadata.get("country") or "",
                "city": None,
                "website": None,
                "industry": "",
                "description": customs_summary.get("ai_summary", ""),
                "phone": "",
                "address": "",
                "email_count": None,
                "products": [],
                "grade": "",
                "star": None,
                "social_media": [],
            }

            enriched_payload = {**base_payload, "customs_summary": customs_summary}

            match_reasons = [
                f"关键词：{keyword}",
                f"采购商：{buyer}",
                f"HS Code：{customs_summary['hs_code'] or '未知'}",
                f"最近交易：{customs_summary['trade_date']}",
                f"交易频次：{customs_summary['frequency']}",
            ]
            if customs_summary["supplier"]:
                match_reasons.append(f"供应商：{customs_summary['supplier']}")
            if customs_summary.get("ai_summary"):
                match_reasons.append(customs_summary["ai_summary"])

            existing = _find_result_by_company_name(job, buyer)
            if existing is None:
                db.add(SearchResultItem(
                    job_id=job.id, company_id=company_id,
                    status="enriching", score=score, activity_score=customs_summary["frequency"] * 5,
                    intent_label="海关数据",
                    source_summary_json=json.dumps([{"source_name": "joinf_customs", "status": "completed"}], ensure_ascii=False),
                    match_reasons_json=json.dumps(match_reasons, ensure_ascii=False),
                    base_payload_json=json.dumps(base_payload, ensure_ascii=False),
                    enriched_payload_json=json.dumps(enriched_payload, ensure_ascii=False),
                ))
            else:
                # 合并海关数据到已有记录
                existing_enriched = json.loads(existing.enriched_payload_json)
                existing_enriched["customs_summary"] = customs_summary
                existing_enriched["description"] = customs_summary.get("ai_summary", existing_enriched.get("description", ""))
                existing.enriched_payload_json = json.dumps(existing_enriched, ensure_ascii=False)
                existing.activity_score = customs_summary["frequency"] * 5
                existing.score = max(existing.score, score)
                existing.source_summary_json = _merge_source_summary(existing.source_summary_json, "joinf_customs")
                existing.match_reasons_json = json.dumps(match_reasons, ensure_ascii=False)

            db.commit()
            written_count += 1
            print(f"[JoinfCustomsApi] 流式写入第 {written_count} 条: {buyer}")

    output_path = await proxy.search_customs(
        keyword=keyword, country=country, max_pages=max_pages, page_size=page_size,
        job_id=job_id, on_item_ready=_on_item_ready,
    )

    from app.scrapers.joinf.service import is_cancelled
    if is_cancelled(job_id):
        print(f"[JoinfCustomsApi] 流式搜索已取消: {written_count} 条已写入 DB")
        return output_path

    # 保存原始 batch 文件
    _store_raw_batch(SessionLocal(), job_id, "joinf_customs", output_path)

    print(f"[JoinfCustomsApi] 流式搜索完成: {written_count} 条已写入 DB, 原始文件: {output_path}")
    return output_path


def _sync_customs_results_from_joinf_batch(db: Session, job: SearchJob, output_path: Path) -> None:
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    items = payload.get("items", [])

    for raw_item in items[: job.limit]:
        extracted = extract_customs_record(raw_item, fallback_hs_code=job.hs_code, fallback_country=job.country)
        buyer = extracted.get("buyer")
        if not buyer:
            continue

        customs_summary = {
            "active_label": "海关数据已抓取",
            "trade_date": extracted.get("trade_date") or "Unknown",
            "hs_code": extracted.get("hs_code"),
            "frequency": extracted.get("frequency") or 1,
            "buyer": buyer,
            "supplier": extracted.get("supplier") or "",
            "product_description": extracted.get("product_description") or "",
            "weight": extracted.get("weight") or "",
            "quantity": extracted.get("quantity") or "",
            "amount": extracted.get("amount") or "",
            "origin": extracted.get("origin") or "",
        }

        existing = _find_result_by_company_name(job, buyer)
        if existing is None:
            base_payload = {
                "company_name": buyer,
                "country": extracted.get("country"),
                "city": None,
                "website": None,
                "industry": "",
                "description": "",
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
                    intent_label="海关数据",
                    source_summary_json=json.dumps([{"source_name": "joinf_customs", "status": "completed"}], ensure_ascii=False),
                    match_reasons_json=json.dumps([
                        f"关键词：{job.query}",
                        f"采购商：{buyer}",
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
            existing.score = max(existing.score, 60)
            existing.source_summary_json = _merge_source_summary(existing.source_summary_json, "joinf_customs")
            existing.match_reasons_json = json.dumps([
                f"关键词：{job.query}",
                f"采购商：{buyer}",
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
        if extracted.get("description"):
            match_reasons.append("已抓取公司简介")
        if extracted.get("address"):
            match_reasons.append("已抓取总部地址")
        if extracted.get("website"):
            match_reasons.append("已抓取官网链接")

        existing = _find_result_by_company_name(job, company_name)
        if existing is None:
            base_payload = {
                "company_name": company_name,
                "country": extracted.get("country") or "Unknown",
                "city": None,
                "website": extracted.get("website"),
                "industry": extracted.get("industry"),
                "description": extracted.get("description"),
                "address": extracted.get("address"),
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
        if not base_payload.get("description") and extracted.get("description"):
            base_payload["description"] = extracted.get("description")
        if not base_payload.get("address") and extracted.get("address"):
            base_payload["address"] = extracted.get("address")

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
                "description": None,
                "phone": None,
                "address": None,
                "employee_size": None,
                "linkedin_url": None,
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
