"""Pipeline execution + persistence logic for the worker."""
from __future__ import annotations

import json
import time
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.classifier import classify
from scraper.agents.orchestrator import decide_flag
from scraper.agents.prompts.builder import build_few_shot_from_db
from scraper.agents.reviewer import review
from scraper.db.models import Classification, JobQueue, ReviewQueue
from scraper.extract.html import extract_from_url
from scraper.extract.pdf import extract_from_pdf
from scraper.llm import LLMClient
from scraper.agents.types import AttributeExtraction
from scraper.search.cascade import run_cascade
from scraper.search.merge import merge_fichas

log = structlog.get_logger()

_null_ae = AttributeExtraction(value=None, confidence=0.0, reasoning="", raw_quote=None)


async def _run_cascade_classify_review(
    nombre: str, rules_md: str, llm: LLMClient, session: AsyncSession
) -> tuple:
    start = time.monotonic()
    few_shot = await build_few_shot_from_db(session, limit=20)
    cascade = await run_cascade(nombre=nombre, session=session, llm=llm)
    if not cascade.fichas:
        duration_ms = int((time.monotonic() - start) * 1000)
        return None, None, "low_quality", "no_source", llm.cost.total_usd, duration_ms, [], None, None

    merge = merge_fichas(cascade.fichas)
    extra = merge.merged_context
    for f in cascade.fichas:
        if f.class_options:
            import json as _json
            extra += f"\nclass_options detectadas: {_json.dumps(f.class_options, ensure_ascii=False)}"
            break
    context = {
        "administrador": merge.primary.attributes.get("administrador", _null_ae).value,
        "gestor": merge.primary.attributes.get("gestor", _null_ae).value,
        "moneda": merge.primary.attributes.get("moneda", _null_ae).value,
        "liquidez": merge.primary.attributes.get("liquidez", _null_ae).value,
        "extra": extra,
    }

    cls_result = await classify(
        llm=llm,
        producto_nombre=nombre,
        product_context=context,
        rules_md=rules_md,
        few_shot_examples=few_shot,
    )
    rev_result = await review(
        llm=llm,
        producto_nombre=nombre,
        product_context=context,
        classifier_output=cls_result,
        rules_md=rules_md,
    )
    flag = decide_flag(cls_result, rev_result)
    source_used = f"cascade_level_{cascade.level}"
    duration_ms = int((time.monotonic() - start) * 1000)
    citations = []
    for f in cascade.fichas:
        citations.extend(f.citations or [])
    rev_dict = {
        "veredicto": rev_result.veredicto,
        "global_verdict": rev_result.global_verdict,
        "reviewer_confidence": rev_result.reviewer_confidence,
    }
    sources_json = [
        {"url": s.url, "label": s.label,
         "document_date": s.document_date.isoformat() if s.document_date else None,
         "source_type": s.source_type}
        for s in merge.all_sources
    ]
    conflicts_json = [
        {"attribute": c.attribute, "chosen_value": c.chosen_value,
         "chosen_source": c.chosen_source,
         "alternatives": [
             {"value": a.value, "source_url": a.source_url,
              "source_label": a.source_label,
              "document_date": a.document_date.isoformat() if a.document_date else None,
              "raw_quote": a.raw_quote}
             for a in c.alternatives
         ]}
        for c in merge.conflicts
    ] or None
    return cls_result, rev_dict, flag, source_used, llm.cost.total_usd, duration_ms, citations, sources_json, conflicts_json


async def process_job_via_cascade(
    *,
    session: AsyncSession,
    job: JobQueue,
    llm: LLMClient,
    rules_md: str,
) -> int:
    (
        cls_result, rev_dict, flag, source_used,
        cost_usd, duration_ms, citations, sources_json, conflicts_json,
    ) = await _run_cascade_classify_review(job.nombre, rules_md, llm, session)

    classifier_output = {}
    per_attr_conf = {}
    global_conf = None
    if cls_result is not None:
        classifier_json = cls_result.to_json() if hasattr(cls_result, "to_json") else cls_result
        if isinstance(classifier_json, str):
            classifier_output = json.loads(classifier_json)
        else:
            classifier_output = classifier_json
        per_attr_conf = {k: v.confidence for k, v in cls_result.attributes.items()}
        global_conf = cls_result.global_confidence

    cls_row = Classification(
        product_name_input=job.nombre,
        classifier_output=classifier_output,
        reviewer_output=rev_dict or {},
        global_confidence=global_conf,
        per_attribute_confidence=per_attr_conf,
        final_status=flag,
        source_used=source_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        sources_used=sources_json,
        field_conflicts=conflicts_json,
    )
    cls_id = await _persist_classification(
        session, cls_row, flag,
        target_classification_id=job.target_classification_id,
    )

    log.info(
        "worker_job_processed",
        job_id=job.id,
        classification_id=cls_id,
        flag=flag,
        cost_usd=cost_usd,
    )
    return cls_id


def _flag_priority(flag: str) -> int:
    return {"low_quality": 0, "needs_review": 1, "auto_approvable": 2}.get(flag, 3)


def _save_classification_and_review(
    cls_result, rev_result, job, flag, source_used, duration_ms, cost_usd,
):
    """Build Classification + ReviewQueue ORM objects (not yet added to session)."""
    classifier_output = {}
    per_attr_conf = {}
    global_conf = None
    if cls_result is not None:
        classifier_json = cls_result.to_json() if hasattr(cls_result, "to_json") else cls_result
        if isinstance(classifier_json, str):
            classifier_output = json.loads(classifier_json)
        else:
            classifier_output = classifier_json
        per_attr_conf = {k: v.confidence for k, v in cls_result.attributes.items()}
        global_conf = cls_result.global_confidence

    cls_row = Classification(
        product_name_input=job.nombre,
        classifier_output=classifier_output,
        reviewer_output={
            "veredicto": rev_result.veredicto,
            "global_verdict": rev_result.global_verdict,
            "reviewer_confidence": rev_result.reviewer_confidence,
        } if rev_result else {},
        global_confidence=global_conf,
        per_attribute_confidence=per_attr_conf,
        final_status=flag,
        source_used=source_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )
    return cls_row


async def _persist_classification(session, cls_row, flag, target_classification_id=None):
    if target_classification_id:
        log.info("persist_merge_mode", target_id=target_classification_id)
        return await _update_existing_classification(
            session, cls_row, flag, target_classification_id
        )
    log.info("persist_create_mode")
    session.add(cls_row)
    await session.commit()
    await session.refresh(cls_row)
    review_row = ReviewQueue(
        classification_id=cls_row.id,
        flag=flag,
        priority=_flag_priority(flag),
    )
    session.add(review_row)
    await session.commit()
    return cls_row.id


def _merge_classifier_outputs(old_output: dict, new_output: dict) -> dict:
    """Merge two classifier outputs, keeping higher-confidence values per attribute."""
    merged = dict(old_output)
    old_attrs = old_output.get("attributes", {})
    new_attrs = new_output.get("attributes", {})

    merged_attrs = dict(old_attrs)
    for key, new_val in new_attrs.items():
        old_val = old_attrs.get(key, {})
        old_conf = old_val.get("confidence", 0.0) if isinstance(old_val, dict) else 0.0
        new_conf = new_val.get("confidence", 0.0) if isinstance(new_val, dict) else 0.0
        if new_conf > old_conf:
            merged_attrs[key] = new_val
        elif new_conf == old_conf and new_val.get("value") is not None and old_val.get("value") is None:
            merged_attrs[key] = new_val

    merged["attributes"] = merged_attrs

    if new_output.get("class_options") and not old_output.get("class_options"):
        merged["class_options"] = new_output["class_options"]
    new_gc = new_output.get("global_confidence", 0)
    old_gc = old_output.get("global_confidence", 0)
    merged["global_confidence"] = max(new_gc or 0, old_gc or 0)

    return merged


def _merge_sources(old_sources: list[dict] | None, new_sources: list[dict] | None) -> list[dict]:
    """Combine source lists, deduplicating by URL."""
    combined = list(old_sources or [])
    seen_urls = {s.get("url") for s in combined if s.get("url")}
    for s in (new_sources or []):
        if s.get("url") not in seen_urls:
            combined.append(s)
            seen_urls.add(s.get("url"))
    return combined


async def _update_existing_classification(session, new_cls_row, flag, target_id):
    from sqlalchemy import select, update
    r = await session.execute(
        select(Classification).where(Classification.id == target_id)
    )
    existing = r.scalar_one_or_none()
    if existing is None:
        log.warning("target_classification_not_found", target_id=target_id)
        return await _persist_classification(session, new_cls_row, flag)

    old_output = existing.classifier_output or {}
    new_output = new_cls_row.classifier_output or {}
    old_attr_count = len(old_output.get("attributes", {}))
    new_attr_count = len(new_output.get("attributes", {}))
    old_source_count = len(existing.sources_used or [])
    new_source_count = len(new_cls_row.sources_used or [])
    log.info("merge_before",
             target_id=target_id,
             old_attrs=old_attr_count, new_attrs=new_attr_count,
             old_sources=old_source_count, new_sources=new_source_count,
             old_source_used=existing.source_used)
    existing.classifier_output = _merge_classifier_outputs(old_output, new_output)

    if new_cls_row.reviewer_output:
        existing.reviewer_output = new_cls_row.reviewer_output

    old_per_attr = existing.per_attribute_confidence or {}
    new_per_attr = new_cls_row.per_attribute_confidence or {}
    merged_conf = dict(old_per_attr)
    for k, v in new_per_attr.items():
        if v > merged_conf.get(k, 0.0):
            merged_conf[k] = v
    existing.per_attribute_confidence = merged_conf
    existing.global_confidence = max(
        existing.global_confidence or 0, new_cls_row.global_confidence or 0
    )

    existing.final_status = flag
    existing.source_used = f"{existing.source_used or ''}+{new_cls_row.source_used or ''}"
    existing.duration_ms = (existing.duration_ms or 0) + (new_cls_row.duration_ms or 0)
    existing.cost_usd = (existing.cost_usd or 0) + (new_cls_row.cost_usd or 0)
    existing.sources_used = _merge_sources(existing.sources_used, new_cls_row.sources_used)
    existing.field_conflicts = new_cls_row.field_conflicts or existing.field_conflicts
    await session.commit()

    await session.execute(
        update(ReviewQueue)
        .where(ReviewQueue.classification_id == target_id)
        .where(ReviewQueue.human_decision.is_(None))
        .values(flag=flag, priority=_flag_priority(flag))
    )
    await session.commit()

    log.info("classification_merged", target_id=target_id, new_flag=flag)
    return existing.id


async def process_job_via_pdf(
    *,
    session: AsyncSession,
    job: JobQueue,
    llm: LLMClient,
    rules_md: str,
) -> int:
    start = time.monotonic()
    few_shot = await build_few_shot_from_db(session, limit=20)

    ficha = await extract_from_pdf(path=Path(job.pdf_path), llm=llm, nombre=job.nombre)
    merge = merge_fichas([ficha])

    import json as _json
    extra_parts = [f"PDF source: {job.pdf_path}"]
    for attr_key in ("foco_geografico", "clase_activo", "subyacente", "comision", "minimo_inversion"):
        ae = ficha.attributes.get(attr_key)
        if ae and ae.value is not None:
            extra_parts.append(f"Extractor {attr_key}: {ae.value!r} (conf={ae.confidence:.2f}, quote={ae.raw_quote!r})")
    if ficha.class_options:
        extra_parts.append(f"class_options detectadas por extractor: {_json.dumps(ficha.class_options, ensure_ascii=False)}")
    context = {
        "administrador": merge.primary.attributes.get("administrador", _null_ae).value,
        "gestor": merge.primary.attributes.get("gestor", _null_ae).value,
        "moneda": merge.primary.attributes.get("moneda", _null_ae).value,
        "liquidez": merge.primary.attributes.get("liquidez", _null_ae).value,
        "extra": "\n".join(extra_parts),
    }

    cls_result = await classify(
        llm=llm, producto_nombre=job.nombre, product_context=context,
        rules_md=rules_md, few_shot_examples=few_shot,
    )
    rev_result = await review(
        llm=llm, producto_nombre=job.nombre, product_context=context,
        classifier_output=cls_result, rules_md=rules_md,
    )
    flag = decide_flag(cls_result, rev_result)
    duration_ms = int((time.monotonic() - start) * 1000)

    cls_row = _save_classification_and_review(
        cls_result, rev_result, job, flag, "direct_pdf", duration_ms, llm.cost.total_usd,
    )
    cls_row.sources_used = [
        {"url": s.url, "label": s.label,
         "document_date": s.document_date.isoformat() if s.document_date else None,
         "source_type": s.source_type}
        for s in merge.all_sources
    ]
    cls_row.field_conflicts = [
        {"attribute": c.attribute, "chosen_value": c.chosen_value,
         "chosen_source": c.chosen_source,
         "alternatives": [
             {"value": a.value, "source_url": a.source_url,
              "source_label": a.source_label,
              "document_date": a.document_date.isoformat() if a.document_date else None,
              "raw_quote": a.raw_quote}
             for a in c.alternatives
         ]}
        for c in merge.conflicts
    ] or None
    target_cls_id = job.target_classification_id
    log.info("process_job_via_pdf_persist",
             job_id=job.id, target_cls_id=target_cls_id, job_nombre=job.nombre)
    return await _persist_classification(
        session, cls_row, flag,
        target_classification_id=target_cls_id,
    )


async def process_job_via_url(
    *,
    session: AsyncSession,
    job: JobQueue,
    llm: LLMClient,
    rules_md: str,
) -> int:
    start = time.monotonic()
    few_shot = await build_few_shot_from_db(session, limit=20)

    fichas = await extract_from_url(url=job.url, llm=llm, nombre=job.nombre)
    if not fichas:
        raise RuntimeError(f"extract_from_url returned no fichas for {job.url}")

    merge = merge_fichas(fichas)
    extra = merge.merged_context
    for f in fichas:
        if f.class_options:
            import json as _json
            extra += f"\nclass_options detectadas: {_json.dumps(f.class_options, ensure_ascii=False)}"
            break
    context = {
        "administrador": merge.primary.attributes.get("administrador", _null_ae).value,
        "gestor": merge.primary.attributes.get("gestor", _null_ae).value,
        "moneda": merge.primary.attributes.get("moneda", _null_ae).value,
        "liquidez": merge.primary.attributes.get("liquidez", _null_ae).value,
        "extra": extra,
    }

    cls_result = await classify(
        llm=llm, producto_nombre=job.nombre, product_context=context,
        rules_md=rules_md, few_shot_examples=few_shot,
    )
    rev_result = await review(
        llm=llm, producto_nombre=job.nombre, product_context=context,
        classifier_output=cls_result, rules_md=rules_md,
    )
    flag = decide_flag(cls_result, rev_result)
    duration_ms = int((time.monotonic() - start) * 1000)

    cls_row = _save_classification_and_review(
        cls_result, rev_result, job, flag, "direct_url", duration_ms, llm.cost.total_usd,
    )
    cls_row.sources_used = [
        {"url": s.url, "label": s.label,
         "document_date": s.document_date.isoformat() if s.document_date else None,
         "source_type": s.source_type}
        for s in merge.all_sources
    ]
    cls_row.field_conflicts = [
        {"attribute": c.attribute, "chosen_value": c.chosen_value,
         "chosen_source": c.chosen_source,
         "alternatives": [
             {"value": a.value, "source_url": a.source_url,
              "source_label": a.source_label,
              "document_date": a.document_date.isoformat() if a.document_date else None,
              "raw_quote": a.raw_quote}
             for a in c.alternatives
         ]}
        for c in merge.conflicts
    ] or None
    return await _persist_classification(
        session, cls_row, flag,
        target_classification_id=job.target_classification_id,
    )
