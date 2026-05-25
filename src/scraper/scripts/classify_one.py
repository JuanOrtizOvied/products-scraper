"""CLI: classify a single product by name.

Usage:
    poetry run python -m scraper.scripts.classify_one "Credicorp Crecimiento"
    # dry-run, imprime prompt (no llama al LLM):
    poetry run python -m scraper.scripts.classify_one --no-api "Credicorp Crecimiento"

Needs ANTHROPIC_API_KEY in .env.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

# Windows default console is cp1252 and our prompts contain characters like
# "Pú", "→", "á" that raise UnicodeEncodeError when printed. Reconfigure stdout
# to utf-8 (same pattern used in scraper.scripts.bootstrap_rules_v1).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import structlog
from sqlalchemy import select

from scraper.agents.classifier import classify
from scraper.agents.orchestrator import decide_flag
from scraper.agents.prompts.builder import build_few_shot_from_db, load_rules_md
from scraper.agents.reviewer import review
from scraper.config import get_settings
from scraper.db.models import Product
from scraper.db.session import get_session
from scraper.llm import LLMClient
from scraper.logging_config import configure_logging

log = structlog.get_logger()


async def _main(producto_nombre: str, no_api: bool = False) -> int:
    configure_logging(level="INFO", json_logs=False)

    settings = get_settings()
    if not no_api and not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY no configurada en .env", file=sys.stderr)
        return 2

    async with get_session() as s:
        # 1. Load product context from DB (for known products)
        r = await s.execute(select(Product).where(Product.nombre == producto_nombre))
        p = r.scalar_one_or_none()
        context = {
            "administrador": p.administrador if p else None,
            "gestor": p.gestor if p else None,
            "moneda": p.moneda if p else None,
            "liquidez": p.liquidez if p else None,
        }
        few_shot = await build_few_shot_from_db(s, limit=20)  # subset for speed

    rules_md = load_rules_md()

    if no_api:
        from scraper.agents.prompts.builder import build_classifier_system_prompt

        prompt = build_classifier_system_prompt(rules_md, few_shot)
        # Truncate at 4000 chars — enough to show rules header AND the taxonomies
        # block (which starts around char ~2500 after the rules doc). Useful as
        # a sanity check that the template + taxonomies + rules all rendered.
        preview_limit = 4000
        print("--- System prompt (dry run, NO LLM CALL) ---")
        print(
            prompt[:preview_limit],
            "...[TRUNCATED]" if len(prompt) > preview_limit else "",
        )
        return 0

    llm = LLMClient()
    cls_result = await classify(
        llm=llm,
        producto_nombre=producto_nombre,
        product_context=context,
        rules_md=rules_md,
        few_shot_examples=few_shot,
    )
    rev_result = await review(
        llm=llm,
        producto_nombre=producto_nombre,
        product_context=context,
        classifier_output=cls_result,
        rules_md=rules_md,
    )
    flag = decide_flag(cls_result, rev_result)

    print("\n=== CLASIFICACIÓN ===")
    print(cls_result.to_json())
    print("\n=== REVISIÓN ===")
    import json as _json

    print(
        _json.dumps(
            {
                "veredicto": rev_result.veredicto,
                "global_verdict": rev_result.global_verdict,
                "attribute_reviews": {
                    k: {"verdict": v.verdict, "reason": v.reason}
                    for k, v in rev_result.attribute_reviews.items()
                },
                "reviewer_confidence": rev_result.reviewer_confidence,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n=== FLAG: {flag} ===")
    print(f"Costo total: ${llm.cost.total_usd:.4f}")
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("producto", help="Nombre del producto a clasificar")
    parser.add_argument(
        "--no-api", action="store_true", help="No llamar a LLM, solo imprime el prompt"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.producto, no_api=args.no_api)))


if __name__ == "__main__":
    cli()
