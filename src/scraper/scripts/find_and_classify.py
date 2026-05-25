"""CLI: search cascade + extract + classify + review + save.

Usage:
    poetry run python -m scraper.scripts.find_and_classify "Credicorp Crecimiento"
    poetry run python -m scraper.scripts.find_and_classify "X" --rules rules/v3.md
    poetry run python -m scraper.scripts.find_and_classify "X" --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.agents.classifier import classify
from scraper.agents.distributor import find_distribution
from scraper.agents.orchestrator import decide_flag
from scraper.agents.prompts.builder import build_few_shot_from_db
from scraper.agents.reviewer import review
from scraper.agents.types import ExtractedFicha
from scraper.config import get_settings
from scraper.db.models import Classification
from scraper.db.session import get_session
from scraper.extract.html import extract_from_url
from scraper.extract.pdf import extract_from_pdf
from scraper.llm import LLMClient
from scraper.logging_config import configure_logging
from scraper.search.cascade import run_cascade

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

log = structlog.get_logger()


def _top_ficha(fichas: list[ExtractedFicha]) -> ExtractedFicha | None:
    if not fichas:
        return None
    return max(fichas, key=lambda f: f.source_confidence)


def _render_evidence(fichas: list[ExtractedFicha]) -> str:
    lines: list[str] = []
    for i, f in enumerate(fichas, 1):
        lines.append(f"=== Fuente {i} ({f.source_type}, conf={f.source_confidence:.2f}) ===")
        if f.source_url:
            lines.append(f"URL: {f.source_url}")
        for attr, ae in f.attributes.items():
            lines.append(
                f"  {attr}: {ae.value!r}  ({ae.confidence:.2f})  quote: {ae.raw_quote!r}"
            )
        if f.raw_text:
            lines.append(f"  raw_text: {f.raw_text[:500]}")
    return "\n".join(lines)


def _context_from_top(top: ExtractedFicha | None, fichas: list[ExtractedFicha]) -> dict:
    def _v(name: str):
        if top is None or name not in top.attributes:
            return None
        return top.attributes[name].value

    return {
        "administrador": _v("administrador"),
        "gestor": _v("gestor"),
        "moneda": _v("moneda"),
        "liquidez": _v("liquidez"),
        "extra": _render_evidence(fichas),
    }


def _source_label(
    url: str | None, pdf: str | None, cascade_level: int | None
) -> str:
    """String to persist in classifications.source_used."""
    if url is not None:
        return "direct_url"
    if pdf is not None:
        return "direct_pdf"
    return f"cascade_level_{cascade_level}"


async def _save_classification(
    session: AsyncSession,
    nombre: str,
    cls_result,
    rev_result,
    flag: str,
    cost_usd: float,
    duration_ms: int,
    source_used: str,
) -> int:
    classifier_payload = (
        cls_result.to_json() if hasattr(cls_result, "to_json") else {}
    )
    # to_json may return dict (Phase 2a) — keep dict, don't json.dumps twice
    if isinstance(classifier_payload, str):
        import json as _j
        classifier_payload = _j.loads(classifier_payload)

    row = Classification(
        product_name_input=nombre,
        classifier_output=classifier_payload,
        reviewer_output={
            "veredicto": rev_result.veredicto,
            "global_verdict": rev_result.global_verdict,
            "reviewer_confidence": rev_result.reviewer_confidence,
        },
        global_confidence=cls_result.global_confidence,
        per_attribute_confidence={
            k: v.confidence for k, v in cls_result.attributes.items()
        },
        final_status=flag,
        source_used=source_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row.id


async def _main(
    nombre: str,
    rules_path: Path,
    dry_run: bool,
    url: str | None,
    pdf: str | None,
) -> int:
    configure_logging(level="INFO", json_logs=False)

    if url is not None and pdf is not None:
        print("ERROR: --url and --pdf are mutually exclusive", file=sys.stderr)
        return 2

    settings = get_settings()
    if not dry_run and not settings.anthropic_api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY no configurada. Use --dry-run para smoke test.",
            file=sys.stderr,
        )
        return 2

    if dry_run:
        where = f"url={url}" if url else (f"pdf={pdf}" if pdf else "cascade")
        print(f"dry-run: would classify '{nombre}' via {where} with rules={rules_path}")
        return 0

    rules_md = rules_path.read_text(encoding="utf-8")
    llm = LLMClient()
    start = time.monotonic()
    cascade_level: int | None = None

    async with get_session() as s:
        few_shot = await build_few_shot_from_db(s, limit=20)

        # Decide source of fichas
        if url is not None:
            fichas = await extract_from_url(url=url, llm=llm, nombre=nombre)
            if not fichas:
                print(f"ERROR: no pudimos extraer nada de {url}", file=sys.stderr)
                return 1
        elif pdf is not None:
            ficha = await extract_from_pdf(path=Path(pdf), llm=llm, nombre=nombre)
            fichas = [ficha]
        else:
            cascade_result = await run_cascade(nombre=nombre, session=s, llm=llm)
            cascade_level = cascade_result.level
            if not cascade_result.fichas:
                print(
                    f"No se encontro ficha para '{nombre}' en ningun nivel.",
                    file=sys.stderr,
                )
                return 1
            fichas = cascade_result.fichas

        top = _top_ficha(fichas)
        context = _context_from_top(top, fichas)

        cls_result = await classify(
            llm=llm,
            producto_nombre=nombre,
            product_context=context,
            rules_md=rules_md,
            few_shot_examples=few_shot,
        )

        # Pass 2: Distribution agent
        admin_attr = cls_result.attributes.get("administrador")
        admin_prod = admin_attr.value if admin_attr else None
        comision_attr = cls_result.attributes.get("comision")
        comision_prod = comision_attr.value if comision_attr and isinstance(comision_attr.value, (int, float)) else None
        clase_attr = cls_result.attributes.get("clase_activo")
        clase_activo_val = clase_attr.value if clase_attr and isinstance(clase_attr.value, dict) else None
        liq_attr = cls_result.attributes.get("liquidez")
        liq_prod = liq_attr.value if liq_attr else None
        min_attr = cls_result.attributes.get("minimo_inversion")
        min_prod = min_attr.value if min_attr else None

        dist_result = await find_distribution(
            llm=llm,
            nombre=nombre,
            administrador_producto=admin_prod,
            comision_producto=comision_prod,
            clase_activo=clase_activo_val,
            liquidez_producto=liq_prod,
            minimo_producto=min_prod,
        )

        rev_result = await review(
            llm=llm,
            producto_nombre=nombre,
            product_context=context,
            classifier_output=cls_result,
            rules_md=rules_md,
        )
        flag = decide_flag(cls_result, rev_result)

        duration_ms = int((time.monotonic() - start) * 1000)
        cost_usd = llm.cost.total_usd
        source_used = _source_label(url, pdf, cascade_level)

        classification_id = await _save_classification(
            s, nombre, cls_result, rev_result, flag, cost_usd, duration_ms, source_used
        )

    print(f"\n=== {nombre} ===")
    if url is not None:
        print(f"Source: direct URL ({url})  — {len(fichas)} ficha(s) extracted")
    elif pdf is not None:
        print(f"Source: direct PDF ({pdf})")
    else:
        print(
            f"Cascade level: {cascade_level}  "
            f"(fichas: {len(fichas)})"
        )
    print(
        f"Flag: {flag}  Reviewer: {rev_result.global_verdict}  "
        f"Conf: {cls_result.global_confidence:.2f}"
    )
    print(f"Cost: ${cost_usd:.4f}  Duration: {duration_ms}ms")
    print(f"Classification id: {classification_id}")
    print("\nClasificacion:")
    print(cls_result.to_json() if hasattr(cls_result, "to_json") else str(cls_result))

    if dist_result and dist_result.intermediario:
        print(f"\nDistribución:")
        print(f"  Intermediario: {dist_result.intermediario} ({dist_result.tipo_intermediario})")
        if dist_result.comision_distribucion is not None:
            print(f"  Comisión distribución: {dist_result.comision_distribucion:.4f}")
        print(f"  Confianza distribución: {dist_result.confidence:.2f}")

    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Search + extract + classify a product by name. "
            "Optionally skip search with --url or --pdf."
        ),
    )
    parser.add_argument("nombre", help="Product name (e.g. 'Credicorp Crecimiento')")
    parser.add_argument(
        "--rules", default="rules/v5.md", help="Path to rules markdown (default v5)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip all API calls, print plan only",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--url",
        help="Skip cascade; extract directly from this URL (includes linked PDFs)",
    )
    source.add_argument(
        "--pdf",
        help="Skip cascade; extract directly from this local PDF file",
    )
    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            _main(args.nombre, Path(args.rules), args.dry_run, args.url, args.pdf)
        )
    )


if __name__ == "__main__":
    cli()
