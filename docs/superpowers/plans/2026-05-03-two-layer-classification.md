# Two-Layer Classification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the single-layer classification (9 flat attributes) into a two-layer model (product intrinsics + distribution/intermediary) with an intelligent distribution agent, fix overly-strict metrics, and update the calibration pipeline to report both layers separately.

**Architecture:** Pass 1 runs the existing cascade + classifier for product-level attributes. Pass 2 runs a new distribution agent (Claude with web_search) that reasons about where to find the Peruvian intermediary. A merge step combines both layers. The DB model, ground truth, metrics, and rules are all updated to support two layers.

**Tech Stack:** Python 3.11+, SQLAlchemy/Alembic (SQLite), Claude Sonnet 4.6 (web_search tool), existing Scrapling/httpx fetch stack, pytest/pytest-asyncio.

---

## File Map

| Layer | File | Action | Responsibility |
|-------|------|--------|----------------|
| Metrics | `src/scraper/metrics/accuracy.py` | Modify | Fix percentage_dict_match, add None-skip, add two-layer comparison |
| Metrics tests | `tests/unit/test_accuracy_v8.py` | Create | Tests for metric fixes |
| DB model | `src/scraper/db/models.py` | Modify | Add two-layer columns to Product |
| Migration | `alembic/versions/xxxx_add_two_layer_columns.py` | Create | Alembic migration for new columns |
| Ground truth | `src/scraper/scripts/split_validation_gt.py` | Create | Semi-auto script to split 19 products |
| Ground truth helper | `src/scraper/scripts/calibrate.py` | Modify | Update `_product_to_ground_truth` for two layers |
| Rules | `rules/v8.md` | Create | v7 + R-DCAP rules |
| Types | `src/scraper/agents/types.py` | Modify | Add DistributionResult dataclass |
| Types tests | `tests/unit/test_distribution_types.py` | Create | Tests for DistributionResult |
| Distribution agent | `src/scraper/agents/distributor.py` | Create | New agent: find intermediary via web_search |
| Distribution prompt | `src/scraper/agents/prompts/distributor_system.md` | Create | System prompt for distribution agent |
| Distribution tests | `tests/unit/test_distributor.py` | Create | Tests for distribution agent |
| Classifier prompt | `src/scraper/agents/prompts/classifier_system.md` | Modify | Request product-layer attributes explicitly |
| Few-shot builder | `src/scraper/agents/prompts/builder.py` | Modify | Update examples for two-layer model |
| Pipeline | `src/scraper/scripts/find_and_classify.py` | Modify | Orchestrate Pass 1 → Pass 2 �� Merge |
| Calibration | `src/scraper/scripts/calibrate_pipeline.py` | Modify | Two-layer comparison + separate reporting |

---

## Phase 1: Foundations

### Task 1: Fix Metric — Percentage Dict Tolerance

**Files:**
- Create: `tests/unit/test_accuracy_v8.py`
- Modify: `src/scraper/metrics/accuracy.py`

- [ ] **Step 1: Write failing tests for percentage dict tolerance**

Create `tests/unit/test_accuracy_v8.py`:

```python
"""Tests for v8 accuracy metric fixes."""
from scraper.metrics.accuracy import percentage_dict_match


def test_pct_dict_ignores_small_keys_in_predicted():
    """Predicted {'Variable': 98, 'Cash': 2} should match gt {'Variable': 100}."""
    gt = {"Mercados Públicos - Variable": 100.0}
    pred = {"Mercados Públicos - Variable": 98.0, "Cash y Otros": 2.0}
    assert percentage_dict_match(gt, pred) is True


def test_pct_dict_does_not_ignore_large_keys():
    """Predicted {'Variable': 80, 'Fijo': 20} should NOT match gt {'Variable': 100}."""
    gt = {"Mercados Públicos - Variable": 100.0}
    pred = {"Mercados Públicos - Variable": 80.0, "Mercados Públicos - Fijo": 20.0}
    assert percentage_dict_match(gt, pred) is False


def test_pct_dict_exact_match_still_works():
    gt = {"Perú": 65.0, "EEUU": 35.0}
    pred = {"Perú": 63.0, "EEUU": 37.0}
    assert percentage_dict_match(gt, pred) is True


def test_pct_dict_both_empty():
    assert percentage_dict_match({}, {}) is True


def test_pct_dict_both_none():
    assert percentage_dict_match(None, None) is True


def test_pct_dict_ignores_small_keys_in_gt_too():
    """GT has a small key that predicted omits — should still match."""
    gt = {"Emergentes ex-Perú": 98.0, "Cash": 2.0}
    pred = {"Emergentes ex-Perú": 100.0}
    assert percentage_dict_match(gt, pred) is True
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `poetry run pytest tests/unit/test_accuracy_v8.py -v`
Expected: `test_pct_dict_ignores_small_keys_in_predicted` and `test_pct_dict_ignores_small_keys_in_gt_too` FAIL.

- [ ] **Step 3: Implement percentage dict tolerance fix**

In `src/scraper/metrics/accuracy.py`, replace the `percentage_dict_match` function (lines 123-137):

```python
def _filter_small_keys(d: dict[str, float], threshold: float = 5.0) -> dict[str, float]:
    """Remove keys with value < threshold and renormalize remaining to 100."""
    filtered = {k: v for k, v in d.items() if v >= threshold}
    total = sum(filtered.values())
    if total > 0 and abs(total - 100.0) > 0.01:
        factor = 100.0 / total
        filtered = {k: v * factor for k, v in filtered.items()}
    return filtered


def percentage_dict_match(
    expected: dict[str, float] | None,
    actual: dict[str, float] | None,
    tolerance_pp: float = 5.0,
) -> bool:
    expected = _filter_small_keys(expected or {})
    actual = _filter_small_keys(actual or {})
    if set(expected.keys()) != set(actual.keys()):
        return False
    for k, exp_v in expected.items():
        act_v = actual[k]
        if abs(exp_v - act_v) > tolerance_pp:
            return False
    return True
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `poetry run pytest tests/unit/test_accuracy_v8.py -v`
Expected: All 7 PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed, 1 known failure (kill-switch).

- [ ] **Step 6: Commit**

```bash
git add src/scraper/metrics/accuracy.py tests/unit/test_accuracy_v8.py
git commit -m "fix(metrics): tolerate small percentage dict keys (<5%) in accuracy comparison"
```

---

### Task 2: Fix Metric — None Ground Truth Skip for minimo_inversion

**Files:**
- Modify: `tests/unit/test_accuracy_v8.py`
- Modify: `src/scraper/metrics/accuracy.py`

- [ ] **Step 1: Write failing tests for None-skip**

Append to `tests/unit/test_accuracy_v8.py`:

```python
from scraper.metrics.accuracy import categorical_match, compute_product_accuracy
from scraper.agents.types import AttributeClassification, ClassificationResult


def test_categorical_none_gt_skips():
    """When ground truth is None for minimo_inversion, any prediction should count as correct."""
    from scraper.metrics.accuracy import _should_skip_none_gt
    assert _should_skip_none_gt("minimo_inversion", None) is True
    assert _should_skip_none_gt("minimo_inversion", "5000 USD") is False
    assert _should_skip_none_gt("moneda", None) is False  # only minimo_inversion skips


def test_compute_accuracy_skips_none_gt_minimo():
    """Full accuracy computation should skip minimo_inversion when gt is None."""
    gt = {
        "foco_geografico": {"EEUU": 100.0},
        "clase_activo": {"Mercados Públicos - Variable": 100.0},
        "subyacentes": {"US Large Cap": 100.0},
        "comision": 0.0065,
        "moneda": "dolares",
        "administrador": "BlackRock",
        "gestor": "BlackRock",
        "liquidez": "Inmediata",
        "minimo_inversion": None,
    }
    pred = ClassificationResult(
        producto="test",
        global_confidence=0.9,
        attributes={
            "foco_geografico": AttributeClassification(value={"EEUU": 100.0}, confidence=0.9, reasoning="", rule_applied=""),
            "clase_activo": AttributeClassification(value={"Mercados Públicos - Variable": 100.0}, confidence=0.9, reasoning="", rule_applied=""),
            "subyacente": AttributeClassification(value={"US Large Cap": 100.0}, confidence=0.9, reasoning="", rule_applied=""),
            "comision": AttributeClassification(value=0.0065, confidence=0.9, reasoning="", rule_applied=""),
            "moneda": AttributeClassification(value="dolares", confidence=0.9, reasoning="", rule_applied=""),
            "administrador": AttributeClassification(value="BlackRock", confidence=0.9, reasoning="", rule_applied=""),
            "gestor": AttributeClassification(value="BlackRock", confidence=0.9, reasoning="", rule_applied=""),
            "liquidez": AttributeClassification(value="Inmediata", confidence=0.9, reasoning="", rule_applied=""),
            "minimo_inversion": AttributeClassification(value="1 acción (~$82 USD)", confidence=0.9, reasoning="", rule_applied=""),
        },
    )
    report = compute_product_accuracy(gt, pred)
    assert report["minimo_inversion"] is True  # skipped because gt is None
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `poetry run pytest tests/unit/test_accuracy_v8.py::test_categorical_none_gt_skips -v`
Expected: FAIL — `_should_skip_none_gt` not defined.

- [ ] **Step 3: Implement None-skip logic**

In `src/scraper/metrics/accuracy.py`, add after the `_filter_small_keys` function:

```python
_SKIP_NONE_GT_ATTRS = {"minimo_inversion"}


def _should_skip_none_gt(attr: str, gt_value: Any) -> bool:
    """Return True if this attribute should be marked correct when gt is None."""
    return attr in _SKIP_NONE_GT_ATTRS and gt_value is None
```

Then update `compute_product_accuracy` (around line 176) to use it. Replace the loop body:

```python
def compute_product_accuracy(
    ground_truth: dict[str, Any],
    predicted: ClassificationResult,
) -> dict[str, bool]:
    """Compare predicted classification against ground truth Product row dict."""
    report: dict[str, bool] = {}
    for attr, (kind, gt_key) in _ATTR_MAPPING.items():
        gt_value = ground_truth.get(gt_key)
        predicted_attr = predicted.attributes.get(attr)
        pred_value = predicted_attr.value if predicted_attr else None

        if _should_skip_none_gt(attr, gt_value):
            report[attr] = True
            continue

        if kind == "percentage_dict":
            report[attr] = percentage_dict_match(gt_value, pred_value)
        elif kind == "numeric":
            report[attr] = numeric_match(gt_value, pred_value)
        else:
            report[attr] = categorical_match(gt_value, pred_value)
    return report
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `poetry run pytest tests/unit/test_accuracy_v8.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full suite**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed.

- [ ] **Step 6: Commit**

```bash
git add src/scraper/metrics/accuracy.py tests/unit/test_accuracy_v8.py
git commit -m "fix(metrics): skip minimo_inversion comparison when ground truth is None"
```

---

### Task 3: DB Migration — Add Two-Layer Columns to Product

**Files:**
- Modify: `src/scraper/db/models.py`
- Create: `alembic/versions/xxxx_add_two_layer_columns.py`

- [ ] **Step 1: Add new columns to Product model**

In `src/scraper/db/models.py`, add after `minimo_inversion` (line 43), before `source_url`:

```python
    # Two-layer: product-level attributes (the asset itself)
    administrador_producto: Mapped[str | None] = mapped_column(String, nullable=True)
    gestor_producto: Mapped[str | None] = mapped_column(String, nullable=True)
    comision_producto: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimo_inversion_producto: Mapped[str | None] = mapped_column(String, nullable=True)
    liquidez_producto: Mapped[str | None] = mapped_column(String, nullable=True)
    # Two-layer: distribution attributes (how Sabbi accesses it)
    intermediario: Mapped[str | None] = mapped_column(String, nullable=True)
    tipo_intermediario: Mapped[str | None] = mapped_column(String, nullable=True)
    comision_distribucion: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimo_via_intermediario: Mapped[str | None] = mapped_column(String, nullable=True)
    liquidez_via_intermediario: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 2: Generate Alembic migration**

Run: `poetry run alembic revision --autogenerate -m "add two-layer classification columns to products"`

Verify the generated migration has the correct `add_column` calls for all 10 new columns.

- [ ] **Step 3: Run migration**

Run: `poetry run alembic upgrade head`
Expected: No errors.

- [ ] **Step 4: Verify columns exist**

Run: `poetry run python -c "from scraper.db.models import Product; print([c.name for c in Product.__table__.columns if 'producto' in c.name or 'intermediario' in c.name or 'distribucion' in c.name])"`
Expected: List of 10 new column names.

- [ ] **Step 5: Run full suite**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed.

- [ ] **Step 6: Commit**

```bash
git add src/scraper/db/models.py alembic/versions/
git commit -m "feat(db): add two-layer classification columns to Product model"
```

---

### Task 4: Split Validation Set Ground Truth

**Files:**
- Create: `src/scraper/scripts/split_validation_gt.py`

This script reads the current 19 validation products and splits them into two layers. The existing `administrador`/`gestor`/`comision`/`minimo_inversion` values become the distribution layer. The product layer is populated with known correct values based on product type.

- [ ] **Step 1: Create the split script**

```python
"""Split validation set ground truth into product + distribution layers.

Reads the 19 validation products and populates the new two-layer columns:
- Existing administrador/gestor/comision become distribution layer
- Product layer gets correct intrinsic values

Usage:
    poetry run python -m scraper.scripts.split_validation_gt --dry-run
    poetry run python -m scraper.scripts.split_validation_gt
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from scraper.db.models import Product, ValidationSet
from scraper.db.session import get_session

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Known product-level data for validation set products.
# Key = product nombre. Values = product-layer overrides.
# Products not listed here: product layer = same as current (SAFI-managed funds).
_PRODUCT_LAYER_OVERRIDES: dict[str, dict] = {
    "INVCENC1 - Credicorp Capital": {
        "administrador_producto": "Cementos Pacasmayo S.A.A.",
        "gestor_producto": "Cementos Pacasmayo S.A.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "IPCHBC1 - Credicorp Capital": {
        "administrador_producto": "Inversiones Portuarias Chancay S.A.A.",
        "gestor_producto": "Inversiones Portuarias Chancay S.A.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "LUSURC1 - Credicorp Capital": {
        "administrador_producto": "Luz del Sur S.A.A.",
        "gestor_producto": "Luz del Sur S.A.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "MINSURI1 - Credicorp Capital": {
        "administrador_producto": "Compañía Minera Minsur S.A.",
        "gestor_producto": "Compañía Minera Minsur S.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "BACKUSI1 - Credicorp Capital": {
        "administrador_producto": "Unión de Cervecerías Peruanas Backus y Johnston S.A.A.",
        "gestor_producto": "Unión de Cervecerías Peruanas Backus y Johnston S.A.A.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "AMERICAN EXPRESS CO - AXP": {
        "administrador_producto": "American Express Company",
        "gestor_producto": "American Express Company",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "CITIGROUP INC - C": {
        "administrador_producto": "Citigroup Inc.",
        "gestor_producto": "Citigroup Inc.",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "JPM NASDAQ EQUITY PREMIUM": {
        "administrador_producto": "J.P. Morgan Asset Management",
        "gestor_producto": "J.P. Morgan Asset Management",
        "comision_producto": 0.0035,
        "tipo_intermediario": "broker",
    },
    "PROCTER & GAMBLE CO/THE - PG": {
        "administrador_producto": "The Procter & Gamble Company",
        "gestor_producto": "The Procter & Gamble Company",
        "comision_producto": 0.0,
        "tipo_intermediario": "broker",
    },
    "JPM Emerging Markets Equity Fund – MFLJEA": {
        "administrador_producto": "JPMorgan Funds (Asia) Limited",
        "gestor_producto": "J.P. Morgan Asset Management",
        "comision_producto": 0.015,
        "tipo_intermediario": "custodio",
    },
    "Lord Abbett Innovation Fund – MFXJCE": {
        "administrador_producto": "Lord Abbett Global Funds I plc",
        "gestor_producto": "Lord Abbett",
        "comision_producto": 0.018,
        "tipo_intermediario": "custodio",
    },
    "Alibaba Group Holding ADR – BABA": {
        "administrador_producto": "Alibaba Group Holding Limited",
        "gestor_producto": "Alibaba Group Holding Limited",
        "comision_producto": 0.0,
        "tipo_intermediario": "custodio",
    },
    "Petrobras ADR – PBR": {
        "administrador_producto": "Petrobras",
        "gestor_producto": "Petrobras",
        "comision_producto": 0.0,
        "tipo_intermediario": "custodio",
    },
    "iShares 1–3 Year Treasury Bond ETF – SHY": {
        "administrador_producto": "BlackRock",
        "gestor_producto": "BlackRock Fund Advisors",
        "comision_producto": 0.0015,
        "tipo_intermediario": "custodio",
    },
    "JPM US Aggregate Bond Fund – MFLJEH": {
        "administrador_producto": "JPMorgan Asset Management (Europe) S.à r.l.",
        "gestor_producto": "J.P. Morgan Asset Management",
        "comision_producto": 0.009,
        "tipo_intermediario": "custodio",
    },
}


async def _main(dry_run: bool) -> int:
    async with get_session() as s:
        r = await s.execute(
            select(Product).join(ValidationSet, Product.id == ValidationSet.product_id)
        )
        products = list(r.scalars().all())

    print(f"Processing {len(products)} validation products\n")

    for p in products:
        overrides = _PRODUCT_LAYER_OVERRIDES.get(p.nombre)

        if overrides:
            admin_prod = overrides["administrador_producto"]
            gestor_prod = overrides["gestor_producto"]
            comision_prod = overrides["comision_producto"]
            tipo = overrides["tipo_intermediario"]
            intermediario = p.administrador
            comision_dist = p.comision
        else:
            # SAFI-managed fund or club deal: product = distribution
            admin_prod = p.administrador
            gestor_prod = p.gestor
            comision_prod = p.comision
            tipo = "safi"
            intermediario = p.administrador
            comision_dist = p.comision

        print(f"{'[DRY-RUN] ' if dry_run else ''}  {p.nombre}")
        print(f"    PRODUCT:  admin={admin_prod}, gestor={gestor_prod}, comision={comision_prod}")
        print(f"    DISTRIB:  intermediario={intermediario}, tipo={tipo}, comision={comision_dist}")
        print()

        if not dry_run:
            async with get_session() as s2:
                r = await s2.execute(select(Product).where(Product.id == p.id))
                prod = r.scalar_one()
                prod.administrador_producto = admin_prod
                prod.gestor_producto = gestor_prod
                prod.comision_producto = comision_prod
                prod.minimo_inversion_producto = p.minimo_inversion
                prod.liquidez_producto = p.liquidez
                prod.intermediario = intermediario
                prod.tipo_intermediario = tipo
                prod.comision_distribucion = comision_dist
                prod.minimo_via_intermediario = p.minimo_inversion
                prod.liquidez_via_intermediario = p.liquidez
                await s2.commit()

    action = "Would update" if dry_run else "Updated"
    print(f"\n{action} {len(products)} products.")
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="Split validation GT into two layers.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.dry_run)))


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Run dry-run to verify**

Run: `poetry run python -m scraper.scripts.split_validation_gt --dry-run`
Expected: Prints 19 products with proposed two-layer values.

- [ ] **Step 3: Run actual migration**

Run: `poetry run python -m scraper.scripts.split_validation_gt`
Expected: "Updated 19 products."

- [ ] **Step 4: Verify data in DB**

Run: `poetry run python -c "
import asyncio
from sqlalchemy import select
from scraper.db.models import Product, ValidationSet
from scraper.db.session import get_session

async def check():
    async with get_session() as s:
        r = await s.execute(select(Product).join(ValidationSet, Product.id == ValidationSet.product_id))
        for p in r.scalars():
            if p.intermediario:
                print(f'{p.nombre[:40]:40s} admin_prod={p.administrador_producto}, inter={p.intermediario}')
asyncio.run(check())
"`
Expected: Shows two-layer data for all 19 products.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/scripts/split_validation_gt.py
git commit -m "feat(data): split validation set ground truth into product + distribution layers"
```

---

### Task 5: Update Ground Truth Function for Two Layers

**Files:**
- Modify: `src/scraper/scripts/calibrate.py`

- [ ] **Step 1: Update `_product_to_ground_truth` to return two-layer dict**

In `src/scraper/scripts/calibrate.py`, replace the `_product_to_ground_truth` function (lines 43-57):

```python
def _product_to_ground_truth(p: Product) -> dict:
    """Build ground truth dict from a Product row.

    Returns a dict with both product-layer and distribution-layer keys.
    If two-layer columns are populated, uses those. Otherwise falls back
    to the original single-layer columns (backwards compatible).
    """
    gt = {
        "foco_geografico": normalize_percentage_dict_region(p.foco_geografico or {}),
        "clase_activo": normalize_percentage_dict_asset_class(p.clase_activo or {}),
        "subyacentes": normalize_percentage_dict_subyacente(p.subyacentes or {}),
        "moneda": p.moneda,
    }
    # Product layer
    gt["administrador_producto"] = p.administrador_producto or p.administrador
    gt["gestor_producto"] = p.gestor_producto or p.gestor
    gt["comision_producto"] = p.comision_producto if p.comision_producto is not None else p.comision
    gt["minimo_inversion_producto"] = p.minimo_inversion_producto or p.minimo_inversion
    gt["liquidez_producto"] = p.liquidez_producto or p.liquidez
    # Distribution layer
    gt["intermediario"] = p.intermediario
    gt["tipo_intermediario"] = p.tipo_intermediario
    gt["comision_distribucion"] = p.comision_distribucion if p.comision_distribucion is not None else p.comision
    gt["minimo_via_intermediario"] = p.minimo_via_intermediario or p.minimo_inversion
    gt["liquidez_via_intermediario"] = p.liquidez_via_intermediario or p.liquidez
    # Legacy keys (for backwards compat with old calibrate.py consumers)
    gt["comision"] = p.comision
    gt["administrador"] = p.administrador
    gt["gestor"] = p.gestor
    gt["liquidez"] = p.liquidez
    gt["minimo_inversion"] = p.minimo_inversion
    return gt
```

- [ ] **Step 2: Run full suite to verify no regressions**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed.

- [ ] **Step 3: Commit**

```bash
git add src/scraper/scripts/calibrate.py
git commit -m "feat(calibrate): update ground truth function for two-layer model"
```

---

### Task 6: Rules v8

**Files:**
- Create: `rules/v8.md`

- [ ] **Step 1: Create rules/v8.md**

Copy `rules/v7.md` as base. Make these changes:

**Replace the header:**
```markdown
# Sabbi — Filosofía de Clasificación de Productos de Inversión — v8

**Fecha:** 2026-05-03
**Autor:** Sabbi + Claude
**Status:** Two-layer classification — product intrinsics + distribution
**Base:** v7 + reglas de doble capa (R-DCAP)
```

**Add "Cambios vs v7" section after the header:**
```markdown
## Cambios vs v7

1. **Doble capa (R-DCAP-1/2/3).** El clasificador ahora distingue entre atributos intrínsecos del producto (quién realmente lo administra, su expense ratio) y atributos de distribución (intermediario peruano, fee de custodia).
2. **Métricas relajadas.** Percentage dicts toleran posiciones menores a 5%. minimo_inversion con ground truth None se omite del cálculo.
```

**Add new rule sections before "## Proceso cuando hay duda":**
```markdown
## NUEVO: Reglas de Doble Capa

### R-DCAP-1: Atributos del producto son intrínsecos

`administrador_producto`, `gestor_producto`, `comision_producto` y `minimo_inversion_producto` reflejan al ASSET MANAGER real del producto, no al intermediario peruano que da acceso.

Ejemplos:
- SHY → administrador_producto = "BlackRock", NO "UBS"
- BACKUSI1 → administrador_producto = "Backus y Johnston S.A.A.", NO "Credicorp Capital"
- JPM NASDAQ EQUITY PREMIUM → administrador_producto = "J.P. Morgan Asset Management"

### R-DCAP-2: Intermediario es quién da acceso en Perú

`intermediario` refleja la SAFI, broker o custodio peruano a través del cual Sabbi accede al producto:
- Fondos peruanos (Core Capital, Credicorp, etc.): intermediario = la SAFI misma
- Acciones BVL (INVCENC1, BACKUSI1, etc.): intermediario = el broker (Credicorp Capital)
- Assets internacionales (SHY, BABA, etc.): intermediario = custodio (UBS, Credicorp Capital)

`tipo_intermediario` puede ser: "safi", "broker", "custodio", "directo".

### R-DCAP-3: Fondos peruanos = capa única

Si `administrador_producto` es una SAFI peruana (Core Capital SAFI, Credicorp Capital SAF, etc.), copiar directamente:
- intermediario = administrador_producto
- tipo_intermediario = "safi"
- comision_distribucion = comision_producto
NO ejecutar búsqueda de intermediario por separado.
```

**Update the Versionado section at the end:**
```markdown
- **v8** (2026-05-03): Two-layer classification — product intrinsics + distribution (R-DCAP).
```

- [ ] **Step 2: Verify file**

Run: `poetry run python -c "from pathlib import Path; t = Path('rules/v8.md').read_text(encoding='utf-8'); print(len(t), 'chars'); assert 'R-DCAP' in t"`
Expected: File size > v7.md, assertion passes.

- [ ] **Step 3: Commit**

```bash
git add rules/v8.md
git commit -m "docs: rules v8 with R-DCAP two-layer classification rules"
```

---

## Phase 2: Pipeline Two Layers

### Task 7: Add DistributionResult Type

**Files:**
- Create: `tests/unit/test_distribution_types.py`
- Modify: `src/scraper/agents/types.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_distribution_types.py`:

```python
"""Tests for DistributionResult dataclass."""
import json

from scraper.agents.types import DistributionResult


def test_distribution_result_creation():
    dr = DistributionResult(
        producto="iShares SHY",
        intermediario="UBS",
        tipo_intermediario="custodio",
        comision_distribucion=0.0065,
        minimo_via_intermediario="USD 70,000",
        liquidez_via_intermediario="Mediano plazo",
        confidence=0.85,
        reasoning="Found on UBS Peru catalog",
        source_url="https://ubs.com/pe/funds",
    )
    assert dr.intermediario == "UBS"
    assert dr.tipo_intermediario == "custodio"
    assert dr.comision_distribucion == 0.0065


def test_distribution_result_from_json():
    data = {
        "producto": "SHY",
        "intermediario": "UBS",
        "tipo_intermediario": "custodio",
        "comision_distribucion": 0.0065,
        "minimo_via_intermediario": None,
        "liquidez_via_intermediario": None,
        "confidence": 0.8,
        "reasoning": "test",
        "source_url": None,
    }
    dr = DistributionResult.from_json(data)
    assert dr.intermediario == "UBS"
    assert dr.confidence == 0.8


def test_distribution_result_to_json():
    dr = DistributionResult(
        producto="SHY",
        intermediario="UBS",
        tipo_intermediario="custodio",
        comision_distribucion=0.0065,
        confidence=0.8,
        reasoning="test",
    )
    payload = dr.to_json()
    assert isinstance(payload, dict)
    assert payload["intermediario"] == "UBS"
    assert payload["tipo_intermediario"] == "custodio"


def test_distribution_result_safi_shortcut():
    """SAFI-managed funds copy product layer directly."""
    dr = DistributionResult.from_product_layer(
        producto="Fondo Habilitador",
        administrador_producto="Core Capital SAFI",
        comision_producto=0.005,
        liquidez_producto="Mediano plazo",
        minimo_producto=None,
    )
    assert dr.intermediario == "Core Capital SAFI"
    assert dr.tipo_intermediario == "safi"
    assert dr.comision_distribucion == 0.005
    assert dr.confidence == 1.0
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `poetry run pytest tests/unit/test_distribution_types.py -v`
Expected: FAIL — `DistributionResult` not found.

- [ ] **Step 3: Implement DistributionResult**

In `src/scraper/agents/types.py`, add after the `MergeResult` class at the end of the file:

```python
@dataclass(frozen=True)
class DistributionResult:
    """Output of the distribution agent (Pass 2)."""
    producto: str
    intermediario: str | None = None
    tipo_intermediario: str | None = None  # "safi" | "broker" | "custodio" | "directo"
    comision_distribucion: float | None = None
    minimo_via_intermediario: str | None = None
    liquidez_via_intermediario: str | None = None
    confidence: float = 0.0
    reasoning: str = ""
    source_url: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "producto": self.producto,
            "intermediario": self.intermediario,
            "tipo_intermediario": self.tipo_intermediario,
            "comision_distribucion": self.comision_distribucion,
            "minimo_via_intermediario": self.minimo_via_intermediario,
            "liquidez_via_intermediario": self.liquidez_via_intermediario,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "source_url": self.source_url,
        }

    @classmethod
    def from_json(cls, data: str | dict) -> DistributionResult:
        p = json.loads(data) if isinstance(data, str) else data
        return cls(
            producto=str(p.get("producto", "")),
            intermediario=p.get("intermediario"),
            tipo_intermediario=p.get("tipo_intermediario"),
            comision_distribucion=(
                float(p["comision_distribucion"])
                if p.get("comision_distribucion") is not None
                else None
            ),
            minimo_via_intermediario=p.get("minimo_via_intermediario"),
            liquidez_via_intermediario=p.get("liquidez_via_intermediario"),
            confidence=float(p.get("confidence", 0.0)),
            reasoning=str(p.get("reasoning", "")),
            source_url=p.get("source_url"),
        )

    @classmethod
    def from_product_layer(
        cls,
        producto: str,
        administrador_producto: str,
        comision_producto: float | None,
        liquidez_producto: str | None = None,
        minimo_producto: str | None = None,
    ) -> DistributionResult:
        """Shortcut for SAFI-managed funds where intermediary = product manager."""
        return cls(
            producto=producto,
            intermediario=administrador_producto,
            tipo_intermediario="safi",
            comision_distribucion=comision_producto,
            minimo_via_intermediario=minimo_producto,
            liquidez_via_intermediario=liquidez_producto,
            confidence=1.0,
            reasoning="SAFI-managed fund — intermediary is the product manager itself",
        )
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `poetry run pytest tests/unit/test_distribution_types.py -v`
Expected: All 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/agents/types.py tests/unit/test_distribution_types.py
git commit -m "feat(types): add DistributionResult dataclass for two-layer pipeline"
```

---

### Task 8: Distribution Agent

**Files:**
- Create: `src/scraper/agents/prompts/distributor_system.md`
- Create: `src/scraper/agents/distributor.py`
- Create: `tests/unit/test_distributor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_distributor.py`:

```python
"""Tests for distribution agent."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from scraper.agents.distributor import (
    _is_peruvian_safi,
    _build_distribution_user_message,
    find_distribution,
)
from scraper.agents.types import DistributionResult


def test_is_peruvian_safi_positive():
    assert _is_peruvian_safi("Core Capital SAFI") is True
    assert _is_peruvian_safi("Credicorp Capital S.A. SAF") is True
    assert _is_peruvian_safi("Credicorp Capital SAF") is True


def test_is_peruvian_safi_negative():
    assert _is_peruvian_safi("BlackRock") is False
    assert _is_peruvian_safi("J.P. Morgan Asset Management") is False
    assert _is_peruvian_safi(None) is False


def test_build_distribution_user_message():
    msg = _build_distribution_user_message(
        nombre="iShares SHY",
        administrador_producto="BlackRock",
        clase_activo={"Mercados Públicos - Fijo": 100.0},
    )
    assert "iShares SHY" in msg
    assert "BlackRock" in msg


@pytest.mark.asyncio
async def test_find_distribution_safi_shortcut():
    """When product is SAFI-managed, skip web search and return directly."""
    llm = MagicMock()
    result = await find_distribution(
        llm=llm,
        nombre="Fondo Habilitador",
        administrador_producto="Core Capital SAFI",
        comision_producto=0.005,
        clase_activo={"Mercados Privados - Deuda": 100.0},
    )
    assert isinstance(result, DistributionResult)
    assert result.intermediario == "Core Capital SAFI"
    assert result.tipo_intermediario == "safi"
    assert result.confidence == 1.0
    llm.call.assert_not_called()
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `poetry run pytest tests/unit/test_distributor.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create distributor system prompt**

Create `src/scraper/agents/prompts/distributor_system.md`:

```markdown
Sos un agente especializado en el mercado financiero peruano. Tu tarea: dado un producto de inversión y su administrador real (capa producto), encontrar QUIÉN lo distribuye o da acceso en Perú y bajo qué condiciones.

## Estrategia de búsqueda

Razoná paso a paso según el tipo de producto:

1. **Acciones BVL** (ticker peruano como BACKUSI1, INVCENC1): El intermediario es el broker. Buscá "sociedad agente de bolsa" + nombre. Los principales: Credicorp Capital, Inteligo, Scotia Bolsa, BBVA Bolsa.

2. **Acciones/ETFs internacionales** (NYSE, NASDAQ — AXP, SHY, BABA): Buscá qué brokers peruanos ofrecen acceso a mercados internacionales. Los principales: Credicorp Capital (vía BVL o directo), UBS (para clientes wealth management).

3. **Fondos internacionales** (JPM, Lord Abbett, etc. con código MFLXXX): Buscá en catálogos de distribuidores de fondos mutuos internacionales en Perú. Buscar en SMV, SBS, o "distribuidor [nombre fondo] Peru".

4. **Fondos peruanos** (SAFI peruana): NO deberías llegar acá — el pipeline usa shortcut. Si llegás, el intermediario = la SAFI misma.

## Límite de búsquedas

Máximo 5 búsquedas web. Si después de 5 no encontrás el intermediario, respondé con confidence 0 y intermediario null.

## OUTPUT — formato obligatorio

Respondé EXACTAMENTE con un JSON:

```json
{
  "producto": "nombre del producto",
  "intermediario": "nombre del intermediario peruano",
  "tipo_intermediario": "broker|custodio|safi|directo",
  "comision_distribucion": 0.0065,
  "minimo_via_intermediario": "USD 70,000 o null",
  "liquidez_via_intermediario": "Mediano plazo o null",
  "confidence": 0.85,
  "reasoning": "explicación breve de cómo encontraste el intermediario",
  "source_url": "URL de la fuente principal"
}
```

- Si no encontrás intermediario: `"intermediario": null, "confidence": 0.0`
- `comision_distribucion` es el fee del intermediario (no el expense ratio del fondo)
- Respondé SOLO el JSON. Sin texto antes ni después.
```

- [ ] **Step 4: Create distributor agent**

Create `src/scraper/agents/distributor.py`:

```python
"""Distribution agent — finds the Peruvian intermediary for a product."""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from scraper.agents.classifier import _strip_fences
from scraper.agents.types import DistributionResult
from scraper.llm import LLMClient

log = structlog.get_logger()

DISTRIBUTOR_MODEL = "claude-sonnet-4-6"
_WEBSEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}
_PROMPT_PATH = __import__("pathlib").Path(__file__).parent / "prompts" / "distributor_system.md"

_SAFI_PATTERNS = re.compile(
    r"\b(safi|saf|sgfci|s\.a\.f\.i\.|s\.a\.f\.|sociedad administradora de fondos)\b",
    re.IGNORECASE,
)


def _is_peruvian_safi(name: str | None) -> bool:
    """Check if a name looks like a Peruvian SAFI."""
    if not name:
        return False
    return bool(_SAFI_PATTERNS.search(name))


def _build_distribution_user_message(
    nombre: str,
    administrador_producto: str | None,
    clase_activo: dict[str, float] | None = None,
) -> str:
    parts = [f'Producto: "{nombre}"']
    if administrador_producto:
        parts.append(f"Administrador real del producto: {administrador_producto}")
    if clase_activo:
        dominant = max(clase_activo.items(), key=lambda kv: kv[1])[0] if clase_activo else None
        if dominant:
            parts.append(f"Clase de activo: {dominant}")
    parts.append("Encontrá quién distribuye este producto en Perú.")
    return "\n".join(parts)


async def find_distribution(
    *,
    llm: LLMClient,
    nombre: str,
    administrador_producto: str | None,
    comision_producto: float | None = None,
    clase_activo: dict[str, float] | None = None,
    liquidez_producto: str | None = None,
    minimo_producto: str | None = None,
) -> DistributionResult:
    """Find the Peruvian intermediary for a product.

    If the product is managed by a Peruvian SAFI, returns immediately
    without making any API calls (R-DCAP-3 shortcut).
    """
    if _is_peruvian_safi(administrador_producto):
        return DistributionResult.from_product_layer(
            producto=nombre,
            administrador_producto=administrador_producto,
            comision_producto=comision_producto,
            liquidez_producto=liquidez_producto,
            minimo_producto=minimo_producto,
        )

    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    user_msg = _build_distribution_user_message(nombre, administrador_producto, clase_activo)

    try:
        result = await llm.call(
            model=DISTRIBUTOR_MODEL,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=4096,
            tools=[_WEBSEARCH_TOOL],
        )
    except Exception as e:
        log.warning("distribution_agent_failed", error=str(e), nombre=nombre)
        return DistributionResult(producto=nombre, confidence=0.0, reasoning=f"Agent error: {e}")

    clean = _strip_fences(result.response_text)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        log.warning("distribution_parse_failed", output=clean[:200], nombre=nombre)
        return DistributionResult(producto=nombre, confidence=0.0, reasoning="Parse error")

    return DistributionResult.from_json(payload)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `poetry run pytest tests/unit/test_distributor.py -v`
Expected: All 4 PASS.

- [ ] **Step 6: Run full suite**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed.

- [ ] **Step 7: Commit**

```bash
git add src/scraper/agents/distributor.py src/scraper/agents/prompts/distributor_system.md tests/unit/test_distributor.py
git commit -m "feat(agents): add distribution agent for intermediary discovery"
```

---

### Task 9: Update Classifier Prompt for Product Layer

**Files:**
- Modify: `src/scraper/agents/prompts/classifier_system.md`

- [ ] **Step 1: Update the classifier system prompt**

In `src/scraper/agents/prompts/classifier_system.md`, replace the first line:

Old:
```
Eres el Clasificador de Productos de Inversión de Sabbi. Tu trabajo es clasificar un producto de inversión en las taxonomías canónicas de Sabbi, aplicando las reglas explícitas y los ejemplos de entrenamiento que te doy.
```

New:
```
Eres el Clasificador de Productos de Inversión de Sabbi. Tu trabajo es clasificar los ATRIBUTOS INTRÍNSECOS de un producto de inversión en las taxonomías canónicas de Sabbi.

IMPORTANTE — Doble capa:
- Reportá el administrador/gestor REAL del fondo o activo, NO el intermediario o distribuidor peruano.
- Reportá el expense ratio REAL del producto, NO el fee de custodia del intermediario.
- Ejemplo: para "iShares 1-3 Year Treasury Bond ETF – SHY":
  - administrador: "BlackRock" (NO "UBS" o "Credicorp Capital")
  - comision: 0.0015 (expense ratio del ETF, NO 0.0065 fee de custodia)
- Para acciones individuales (BVL o NYSE): administrador = la empresa emisora, comision = 0.0
```

- [ ] **Step 2: Verify no test breakage**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed.

- [ ] **Step 3: Commit**

```bash
git add src/scraper/agents/prompts/classifier_system.md
git commit -m "feat(classifier): update prompt to request product-layer intrinsic attributes"
```

---

### Task 10: Update Few-Shot Builder for Two Layers

**Files:**
- Modify: `src/scraper/agents/prompts/builder.py`

- [ ] **Step 1: Update `_product_to_example` to use product-layer fields**

In `src/scraper/agents/prompts/builder.py`, update the `_product_to_example` function (lines 108-199). Replace the `input_parts` section and the `expected["attributes"]["administrador"]` / `gestor` values to use product-layer columns when available:

```python
def _product_to_example(p: Product) -> dict[str, Any]:
    input_parts = [f'Producto: "{p.nombre}"']
    admin = p.administrador_producto or p.administrador
    gestor = p.gestor_producto or p.gestor
    if admin:
        input_parts.append(f"Administrador: {admin}")
    if gestor:
        input_parts.append(f"Gestor: {gestor}")
    if p.moneda:
        input_parts.append(f"Moneda: {p.moneda}")
    liq = p.liquidez_producto or p.liquidez
    if liq:
        input_parts.append(f"Liquidez: {liq}")
    input_text = "\n".join(input_parts)

    comision_val = p.comision_producto if p.comision_producto is not None else p.comision
    comision_conf = 1.0 if comision_val is not None else 0.8

    expected = {
        "producto": p.nombre,
        "attributes": {
            "foco_geografico": {
                "value": p.foco_geografico,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "clase_activo": {
                "value": p.clase_activo,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "subyacente": {
                "value": p.subyacentes,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "comision": {
                "value": comision_val if comision_val is not None else (p.comision_raw or None),
                "confidence": comision_conf,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "moneda": {
                "value": p.moneda,
                "confidence": 1.0 if p.moneda else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "administrador": {
                "value": admin,
                "confidence": 1.0 if admin else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "gestor": {
                "value": gestor,
                "confidence": 1.0 if gestor else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
            "liquidez": {
                "value": liq,
                "confidence": 1.0 if liq else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
        },
        "global_confidence": 1.0,
        "unknowns": [],
    }
    return {"producto": p.nombre, "input_text": input_text, "expected_output": expected}
```

- [ ] **Step 2: Run full suite**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed.

- [ ] **Step 3: Commit**

```bash
git add src/scraper/agents/prompts/builder.py
git commit -m "feat(builder): update few-shot examples to use product-layer attributes"
```

---

### Task 11: Update Accuracy Metrics for Two-Layer Comparison

**Files:**
- Modify: `src/scraper/metrics/accuracy.py`
- Modify: `tests/unit/test_accuracy_v8.py`

- [ ] **Step 1: Write failing tests for two-layer accuracy**

Append to `tests/unit/test_accuracy_v8.py`:

```python
from scraper.agents.types import DistributionResult
from scraper.metrics.accuracy import compute_distribution_accuracy


def test_distribution_accuracy_full_match():
    gt = {
        "intermediario": "UBS",
        "tipo_intermediario": "custodio",
        "comision_distribucion": 0.0065,
    }
    pred = DistributionResult(
        producto="SHY",
        intermediario="UBS",
        tipo_intermediario="custodio",
        comision_distribucion=0.0065,
        confidence=0.9,
        reasoning="test",
    )
    report = compute_distribution_accuracy(gt, pred)
    assert report["intermediario"] is True
    assert report["tipo_intermediario"] is True
    assert report["comision_distribucion"] is True


def test_distribution_accuracy_partial():
    gt = {
        "intermediario": "Credicorp Capital",
        "tipo_intermediario": "broker",
        "comision_distribucion": 0.0065,
    }
    pred = DistributionResult(
        producto="BACKUSI1",
        intermediario="Credicorp Capital SAF",
        tipo_intermediario="broker",
        comision_distribucion=None,
        confidence=0.7,
        reasoning="test",
    )
    report = compute_distribution_accuracy(gt, pred)
    assert report["intermediario"] is True  # corporate suffix stripped
    assert report["tipo_intermediario"] is True
    assert report["comision_distribucion"] is False  # None vs 0.0065
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `poetry run pytest tests/unit/test_accuracy_v8.py::test_distribution_accuracy_full_match -v`
Expected: FAIL — `compute_distribution_accuracy` not found.

- [ ] **Step 3: Implement two-layer accuracy**

In `src/scraper/metrics/accuracy.py`, update `_ATTR_MAPPING` and add `compute_distribution_accuracy`. Replace the existing `_ATTR_MAPPING` (lines 154-164):

```python
_PRODUCT_ATTR_MAPPING = {
    "foco_geografico": ("percentage_dict", "foco_geografico"),
    "clase_activo": ("percentage_dict", "clase_activo"),
    "subyacente": ("percentage_dict", "subyacentes"),
    "comision": ("numeric", "comision_producto"),
    "moneda": ("categorical", "moneda"),
    "administrador": ("categorical", "administrador_producto"),
    "gestor": ("categorical", "gestor_producto"),
    "liquidez": ("categorical", "liquidez_producto"),
    "minimo_inversion": ("categorical", "minimo_inversion_producto"),
}

# Legacy mapping for backwards compat with old ground truth format
_ATTR_MAPPING = {
    "foco_geografico": ("percentage_dict", "foco_geografico"),
    "clase_activo": ("percentage_dict", "clase_activo"),
    "subyacente": ("percentage_dict", "subyacentes"),
    "comision": ("numeric", "comision"),
    "moneda": ("categorical", "moneda"),
    "administrador": ("categorical", "administrador"),
    "gestor": ("categorical", "gestor"),
    "liquidez": ("categorical", "liquidez"),
    "minimo_inversion": ("categorical", "minimo_inversion"),
}
```

Then add `compute_product_accuracy_v8` and `compute_distribution_accuracy` after `compute_product_accuracy`:

```python
def compute_product_accuracy_v8(
    ground_truth: dict[str, Any],
    predicted: ClassificationResult,
) -> dict[str, bool]:
    """Compare predicted classification against two-layer ground truth (product layer)."""
    report: dict[str, bool] = {}
    for attr, (kind, gt_key) in _PRODUCT_ATTR_MAPPING.items():
        gt_value = ground_truth.get(gt_key)
        # Fall back to legacy key if two-layer key not present
        if gt_value is None and gt_key != attr:
            legacy_key = _ATTR_MAPPING.get(attr, (None, None))[1]
            if legacy_key:
                gt_value = ground_truth.get(legacy_key)

        predicted_attr = predicted.attributes.get(attr)
        pred_value = predicted_attr.value if predicted_attr else None

        if _should_skip_none_gt(attr, gt_value):
            report[attr] = True
            continue

        if kind == "percentage_dict":
            report[attr] = percentage_dict_match(gt_value, pred_value)
        elif kind == "numeric":
            report[attr] = numeric_match(gt_value, pred_value)
        else:
            report[attr] = categorical_match(gt_value, pred_value)
    return report


def compute_distribution_accuracy(
    ground_truth: dict[str, Any],
    predicted: "DistributionResult",
) -> dict[str, bool]:
    """Compare predicted distribution against ground truth (distribution layer)."""
    from scraper.agents.types import DistributionResult

    report: dict[str, bool] = {}
    report["intermediario"] = categorical_match(
        ground_truth.get("intermediario"), predicted.intermediario
    )
    report["tipo_intermediario"] = categorical_match(
        ground_truth.get("tipo_intermediario"), predicted.tipo_intermediario
    )
    report["comision_distribucion"] = numeric_match(
        ground_truth.get("comision_distribucion"), predicted.comision_distribucion
    )
    return report
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `poetry run pytest tests/unit/test_accuracy_v8.py -v`
Expected: All PASS.

- [ ] **Step 5: Run full suite**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed.

- [ ] **Step 6: Commit**

```bash
git add src/scraper/metrics/accuracy.py tests/unit/test_accuracy_v8.py
git commit -m "feat(metrics): add two-layer accuracy comparison (product + distribution)"
```

---

### Task 12: Orchestrate Two-Pass Pipeline

**Files:**
- Modify: `src/scraper/scripts/find_and_classify.py`

- [ ] **Step 1: Add Pass 2 import and integration**

In `src/scraper/scripts/find_and_classify.py`, add the import at the top (after line 21):

```python
from scraper.agents.distributor import find_distribution
```

Then update `_main` (around line 181-198) to run Pass 2 after Pass 1 classification. After the `cls_result = await classify(...)` call and before `rev_result = await review(...)`, add:

```python
        # Pass 2: Distribution agent
        admin_prod = None
        comision_prod = None
        clase_activo_val = None
        liq_prod = None
        min_prod = None
        admin_attr = cls_result.attributes.get("administrador")
        if admin_attr:
            admin_prod = admin_attr.value
        comision_attr = cls_result.attributes.get("comision")
        if comision_attr:
            comision_prod = comision_attr.value
        clase_attr = cls_result.attributes.get("clase_activo")
        if clase_attr and isinstance(clase_attr.value, dict):
            clase_activo_val = clase_attr.value
        liq_attr = cls_result.attributes.get("liquidez")
        if liq_attr:
            liq_prod = liq_attr.value
        min_attr = cls_result.attributes.get("minimo_inversion")
        if min_attr:
            min_prod = min_attr.value

        dist_result = await find_distribution(
            llm=llm,
            nombre=nombre,
            administrador_producto=admin_prod,
            comision_producto=comision_prod if isinstance(comision_prod, (int, float)) else None,
            clase_activo=clase_activo_val,
            liquidez_producto=liq_prod,
            minimo_producto=min_prod,
        )
```

After the final print section (around line 225), add:

```python
    if dist_result and dist_result.intermediario:
        print(f"\nDistribución:")
        print(f"  Intermediario: {dist_result.intermediario} ({dist_result.tipo_intermediario})")
        if dist_result.comision_distribucion is not None:
            print(f"  Comisión distribución: {dist_result.comision_distribucion:.4f}")
        print(f"  Confianza distribución: {dist_result.confidence:.2f}")
```

- [ ] **Step 2: Run full suite**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed.

- [ ] **Step 3: Commit**

```bash
git add src/scraper/scripts/find_and_classify.py
git commit -m "feat(pipeline): orchestrate two-pass pipeline (product + distribution)"
```

---

### Task 13: Update Calibration Pipeline for Two Layers

**Files:**
- Modify: `src/scraper/scripts/calibrate_pipeline.py`

- [ ] **Step 1: Update imports and add Pass 2**

In `src/scraper/scripts/calibrate_pipeline.py`, add imports after line 48:

```python
from scraper.agents.distributor import find_distribution
from scraper.agents.types import DistributionResult
from scraper.metrics.accuracy import compute_product_accuracy_v8, compute_distribution_accuracy
```

- [ ] **Step 2: Add distribution pass and two-layer reporting**

Inside the `for i, p in enumerate(validation, 1):` loop (around line 152-160), after `cls_result = await classify(...)`, add the Pass 2 call:

```python
            # Pass 2: Distribution
            admin_attr = cls_result.attributes.get("administrador")
            admin_prod = admin_attr.value if admin_attr else None
            comision_attr = cls_result.attributes.get("comision")
            comision_prod = comision_attr.value if comision_attr and isinstance(comision_attr.value, (int, float)) else None
            clase_attr = cls_result.attributes.get("clase_activo")
            clase_val = clase_attr.value if clase_attr and isinstance(clase_attr.value, dict) else None

            dist_result = await find_distribution(
                llm=llm,
                nombre=p.nombre,
                administrador_producto=admin_prod,
                comision_producto=comision_prod,
                clase_activo=clase_val,
            )
```

Replace the `report = compute_product_accuracy(ground_truth, cls_result)` line with:

```python
            report = compute_product_accuracy_v8(ground_truth, cls_result)
            dist_report = compute_distribution_accuracy(ground_truth, dist_result)
```

Update the reporting section. After the product accuracy debug output, add distribution debug output:

```python
            # Debug output for distribution misses
            for attr, ok in dist_report.items():
                if ok:
                    continue
                gt = ground_truth.get(attr)
                pred = getattr(dist_result, attr, None)
                print(f"        ✗ dist.{attr:14s} gt={gt!r}  pred={pred!r}")
```

Store both reports in `per_product_details`:

```python
            per_product_details.append(
                {
                    "nombre": p.nombre,
                    "cascade_level": cascade.level,
                    "fichas": len(cascade.fichas),
                    "product_accuracy": report,
                    "distribution_accuracy": dist_report,
                    "global_confidence": cls_result.global_confidence,
                    "distribution_confidence": dist_result.confidence,
                    "elapsed_s": round(elapsed, 1),
                }
            )
```

Collect distribution reports alongside product reports for aggregation. Add a `dist_reports` list alongside `reports`:

```python
    dist_reports: list[dict[str, bool]] = []
```

Inside the loop, after `reports.append(report)`:
```python
            dist_reports.append(dist_report)
```

In the exception handlers, also append empty dist reports:
```python
            dist_reports.append({"intermediario": False, "tipo_intermediario": False, "comision_distribucion": False})
```

Update the final reporting section to show both layers and separate searchable vs non-searchable products:

```python
    accuracy = aggregate_accuracy(reports)
    dist_accuracy = aggregate_accuracy(dist_reports)

    # Identify non-searchable products (club deals with 0 fichas and 0 confidence)
    searchable_reports = []
    searchable_dist = []
    nonsearchable = []
    for i, detail in enumerate(per_product_details):
        if detail.get("fichas", 0) == 0 and detail.get("global_confidence", 0) < 0.01:
            nonsearchable.append(detail["nombre"])
        else:
            searchable_reports.append(reports[i])
            searchable_dist.append(dist_reports[i])

    searchable_acc = aggregate_accuracy(searchable_reports)
    searchable_dist_acc = aggregate_accuracy(searchable_dist)

    print(f"\n=== Resultado ({version}) ===")
    print(f"Productos evaluados: {len(reports)} ({len(searchable_reports)} buscables, {len(nonsearchable)} no buscables)")

    print(f"\n--- Capa Producto (buscables: {len(searchable_reports)}) ---")
    for attr, acc in sorted(searchable_acc.items()):
        bar = "█" * int(acc * 20) + "░" * (20 - int(acc * 20))
        flag = "✓" if acc >= 0.80 else "✗"
        print(f"  {flag} {attr:20s} [{bar}] {acc:.1%}")

    print(f"\n--- Capa Distribución (buscables: {len(searchable_dist)}) ---")
    for attr, acc in sorted(searchable_dist_acc.items()):
        bar = "█" * int(acc * 20) + "░" * (20 - int(acc * 20))
        flag = "✓" if acc >= 0.50 else "✗"
        print(f"  {flag} {attr:20s} [{bar}] {acc:.1%}")

    if nonsearchable:
        print(f"\n--- No buscables ({len(nonsearchable)}) ---")
        for name in nonsearchable:
            print(f"  ⊘ {name}")
```

- [ ] **Step 2: Update the default --rules argument**

Change the default from `rules/v5.md` to `rules/v8.md` (line 267):

```python
    parser.add_argument("--rules", default="rules/v8.md")
```

- [ ] **Step 3: Run full suite**

Run: `poetry run pytest --tb=short -q`
Expected: 248+ passed.

- [ ] **Step 4: Commit**

```bash
git add src/scraper/scripts/calibrate_pipeline.py
git commit -m "feat(calibrate): two-layer reporting with product + distribution accuracy"
```

---

## Phase 3: Calibration

### Task 14: Run Benchmark and Iterate

This task is manual — run the calibration pipeline and iterate on prompts based on results.

- [ ] **Step 1: Run v8 calibration**

Run:
```powershell
poetry run python -m scraper.scripts.calibrate_pipeline --rules rules/v8.md --output results_v8.json
```

Review the two-layer output. The product layer accuracy should be significantly higher than the old single-layer results because:
- administrador/gestor now compare against the real asset manager
- comision compares against the real expense ratio
- minimo_inversion with None ground truth is skipped
- percentage dicts tolerate <5% keys

- [ ] **Step 2: Compare v8 vs v6**

Run:
```powershell
poetry run python -m scraper.scripts.compare_calibrations results_v6.json results_v8.json
```

Note: The comparison script may need minor updates to handle the new two-layer format in v8 results. If so, update `compare_calibrations.py` to read from `per_attribute_accuracy` which still exists in the output.

- [ ] **Step 3: Iterate on prompts if needed**

Based on the results:
- If distribution accuracy is low, refine `distributor_system.md` prompt
- If product accuracy still has issues, refine `classifier_system.md`
- If specific products fail consistently, add product-type-specific rules to v8

- [ ] **Step 4: Commit final results**

```bash
git add results_v8.json
git commit -m "feat(calibrate): v8 two-layer calibration results"
```
