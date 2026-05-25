# Phase 2a — Agentes (Clasificador + Revisor) + Calibración contra validation_set

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el Clasificador (Claude Sonnet 4.6) + Revisor (Claude Opus 4.7), redactar rules v1, correr calibración contra los 19 productos de validation_set, y reportar accuracy por atributo. Sin scraping, sin UI, sin DB de classifications todavía — solo el core del razonamiento.

**Architecture:** Pipeline offline. Toma los 91 productos de training_set como few-shot examples, las 3 taxonomías canónicas como vocabulario cerrado, y `rules/v1.md` como filosofía escrita. El clasificador produce output JSON estructurado con confidence + reasoning + rule_applied por atributo. El revisor critica. El orchestrator calcula flags (auto_approvable/needs_review/low_quality). El validation runner corre sobre los 19, computa accuracy por atributo, y escribe reporte a `rules_versions.validation_accuracy`. CLI `calibrate` orquesta todo.

**Tech Stack:** Anthropic Python SDK (`anthropic`), tenacity (retry), Claude Sonnet 4.6 + Opus 4.7, prompt caching, structlog, pytest, `rapidfuzz` (ya instalado) para normalizer, `responses`/`httpx_mock` para tests integración.

**Spec de referencia:** `docs/superpowers/specs/2026-04-17-buscador-clasificador-productos-inversion-design.md`
**Phase 1 status:** `docs/superpowers/plans/phase1-STATUS.md`

**Entregable al final de Phase 2a:**
- `rules/v1.md` redactado (reglas + filosofía)
- `poetry run python -m scraper.scripts.classify_one "Credicorp Crecimiento"` → output JSON con clasificación + reasoning + confidence
- `poetry run python -m scraper.scripts.calibrate` → corre los 19 de validation, imprime accuracy por atributo, guarda reporte en DB
- **Score por atributo**: accuracy de foco_geografico, clase_activo, subyacente, comision, moneda, administrador, gestor, liquidez, minimo_inversion contra ground truth
- Threshold meta: ≥85% por atributo. Si <85%, iteramos rules → v2, v3, ... hasta lograrlo

---

## File structure que se crea en Phase 2a

```
scraper/
├── rules/
│   └── v1.md                                # Reglas iniciales
├── src/scraper/
│   ├── logging_config.py                    # structlog setup (tech debt Phase 1)
│   ├── taxonomies/
│   │   ├── normalizer.py                    # variants → canonical
│   │   └── normalizer_variants.yaml         # mapping observado en Phase 1
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py                        # AsyncAnthropic wrapper + cost tracking
│   │   ├── cost.py                          # Calcula costo USD por llamada
│   │   └── retry.py                         # tenacity wrapper
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── types.py                         # ClassificationResult, ReviewResult dataclasses
│   │   ├── prompts/
│   │   │   ├── classifier_system.md         # Template + placeholders
│   │   │   ├── reviewer_system.md
│   │   │   └── builder.py                   # Arma prompts con rules+taxonomies+few-shot
│   │   ├── classifier.py                    # classify() → ClassificationResult
│   │   ├── reviewer.py                      # review() → ReviewResult
│   │   └── orchestrator.py                  # decide_flag() + run_classification_pipeline
│   ├── metrics/
│   │   ├── __init__.py
│   │   └── accuracy.py                      # Compare vs ground truth
│   └── scripts/
│       ├── classify_one.py                  # CLI: clasifica 1 producto
│       ├── calibrate.py                     # CLI: validation loop + reporte
│       └── bootstrap_rules_v1.py            # Helper: analiza training y sugiere reglas
└── tests/
    ├── unit/
    │   ├── test_normalizer.py
    │   ├── test_logging_config.py
    │   ├── test_llm_cost.py
    │   ├── test_agent_types.py
    │   ├── test_prompt_builder.py
    │   ├── test_accuracy.py
    │   └── test_orchestrator.py
    └── integration/
        ├── __init__.py
        ├── conftest.py                      # anthropic mocked fixture
        ├── test_classifier_mocked.py
        ├── test_reviewer_mocked.py
        └── test_calibrate_smoke.py          # --no-api mode
```

---

## Task 1: Tech debt Phase 1 (structlog + mypy stubs + named Excel columns)

Quick pre-work: las 3 deudas técnicas que el reviewer final de Phase 1 flaggeó y que conviene limpiar antes de agregar código nuevo encima.

**Files:**
- Create: `src/scraper/logging_config.py`
- Create: `tests/unit/test_logging_config.py`
- Modify: `src/scraper/scripts/seed_from_excel.py` (usar nombres de columna)
- Modify: `pyproject.toml` (agregar stubs)

- [ ] **Step 1: Test de logging_config**

`tests/unit/test_logging_config.py`:

```python
import logging
import structlog


def test_configure_logging_sets_json_processor_by_default():
    from scraper.logging_config import configure_logging

    configure_logging(level="INFO", json_logs=True)
    logger = structlog.get_logger("test_logger")

    # Confirma que structlog está configurado (no lanza)
    logger.info("test_event", foo="bar")


def test_configure_logging_respects_level():
    from scraper.logging_config import configure_logging

    configure_logging(level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG
```

- [ ] **Step 2: Run test — falla con ImportError**

```bash
poetry run pytest tests/unit/test_logging_config.py -v
```

- [ ] **Step 3: Implementar logging_config**

`src/scraper/logging_config.py`:

```python
"""Central structlog configuration. Call configure_logging() at app startup."""
from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """Configure structlog globally.

    Call once at app startup (CLI entry points, FastAPI startup, tests).
    """
    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level, format="%(message)s")
```

- [ ] **Step 4: Test passes**

```bash
poetry run pytest tests/unit/test_logging_config.py -v
```

- [ ] **Step 5: Add mypy stubs to pyproject.toml**

En `pyproject.toml`, dentro de `[dependency-groups]` o `[tool.poetry.group.dev.dependencies]`, agregar:

```toml
# dev group — agregar al listado existente
"types-PyYAML>=6.0",
"pandas-stubs>=2.2",
```

Luego:

```bash
poetry lock
poetry install
```

- [ ] **Step 6: Refactor seed_from_excel a usar nombres de columna**

En `src/scraper/scripts/seed_from_excel.py`, reemplazar el bloque `col_map = {...}` actual por:

```python
# Expected column names in sheet "Base" after header=2
EXPECTED_COLUMNS = {
    "nombre": "Nombre de Producto",
    "foco": "Foco Geografico (porcentaje)",
    "clase": "Clase de Activo (porcentaje)",
    "subyacente": "Subyacente (porcentaje)",
    "comision": "Comision (sin IGV)",
    "moneda": "moneda (USD o Soles)",
    "admin": "Nombre Administrador",
    "gestor": "Nombre Gestor",
    "liquidez": "Liquidez ",  # Nota: trailing space in real Excel header
}


def _validate_columns(df) -> None:
    """Raise if any expected column is missing."""
    missing = [
        name for key, name in EXPECTED_COLUMNS.items() if name not in df.columns
    ]
    if missing:
        raise ValueError(
            f"Excel 'Base' sheet missing expected columns: {missing}. "
            f"Actual columns: {list(df.columns)}"
        )
```

En la función `seed_products()`, después de `df = df.dropna(...)`:

```python
_validate_columns(df)
col_map = EXPECTED_COLUMNS  # alias para resto del código
```

Y reemplazar usos como `row[col_map["nombre"]]` que ahora resuelven vía nombre en vez de posición.

**Importante:** confirmar el nombre exacto de cada columna ejecutando primero:

```bash
poetry run python -c "import pandas as pd; df = pd.read_excel('BD_Productos Sabbi.xlsx', sheet_name='Base', header=2); print(list(df.columns))"
```

Si algún nombre tiene trailing space (común en "Liquidez "), reflejarlo literalmente.

- [ ] **Step 7: Run all tests, confirm no regression**

```bash
poetry run pytest -v 2>&1 | tail -5
```

Esperado: 34 tests still passing (seed tests still work by name-based resolution).

- [ ] **Step 8: Lint**

```bash
poetry run ruff check src/ tests/
```

- [ ] **Step 9: Commit**

```bash
git add src/scraper/logging_config.py tests/unit/test_logging_config.py src/scraper/scripts/seed_from_excel.py pyproject.toml poetry.lock
git commit -m "refactor: add logging_config, named Excel columns, mypy stubs"
```

---

## Task 2: Taxonomy normalizer (variantes → canónico)

El Excel tiene ~14 variantes ortográficas de las 6 clases macro ("Club deal" en vez de "Club deals", "mercados publicos Variable" en vez de "Mercados Públicos - Variable"). El normalizer traduce variantes a canónico usando (1) un diccionario de variantes conocidas, (2) rapidfuzz como fallback con threshold 85.

**Files:**
- Create: `src/scraper/taxonomies/normalizer.py`
- Create: `src/scraper/taxonomies/normalizer_variants.yaml`
- Create: `tests/unit/test_normalizer.py`

- [ ] **Step 1: Crear normalizer_variants.yaml**

`src/scraper/taxonomies/normalizer_variants.yaml`:

```yaml
# Mapeo de variantes observadas (en el Excel + scrapings futuros) → canónico.
# Ampliar cada vez que aparezca una nueva variante.
asset_class_variants:
  "mercados publicos variable": "Mercados Públicos - Variable"
  "mercados publicos fijo": "Mercados Públicos - Fijo"
  "mercado publico variable": "Mercados Públicos - Variable"
  "mercado publico fijo": "Mercados Públicos - Fijo"
  "mercados publicos - variable": "Mercados Públicos - Variable"
  "mercados publicos - fijo": "Mercados Públicos - Fijo"
  "mercados privados": "Mercados Privados"
  "cash y otros": "Cash y Otros"
  "efectivo": "Cash y Otros"
  "otros": "Cash y Otros"
  "club deal": "Club deals"
  "club deals": "Club deals"
  "inmobiliario directo": "Inmobiliario Directo"
  "inmobiliario": "Inmobiliario Directo"

region_variants:
  "peru": "Perú"
  "perú": "Perú"
  "eeuu": "EEUU"
  "usa": "EEUU"
  "estados unidos": "EEUU"
  "desarrollados ex-us": "Desarrollados ex-US"
  "desarrollados ex us": "Desarrollados ex-US"
  "emergentes ex-perú": "Emergentes ex-Perú"
  "emergentes ex-peru": "Emergentes ex-Perú"
  "latam ex-perú": "Latam ex-Perú"
  "latam ex-peru": "Latam ex-Perú"
```

- [ ] **Step 2: Write failing tests**

`tests/unit/test_normalizer.py`:

```python
import pytest


def test_normalize_asset_class_exact_canonical_passes_through():
    from scraper.taxonomies.normalizer import normalize_asset_class
    assert normalize_asset_class("Mercados Públicos - Variable") == "Mercados Públicos - Variable"


def test_normalize_asset_class_known_variant():
    from scraper.taxonomies.normalizer import normalize_asset_class
    assert normalize_asset_class("Club deal") == "Club deals"
    assert normalize_asset_class("mercados publicos variable") == "Mercados Públicos - Variable"
    assert normalize_asset_class("Efectivo") == "Cash y Otros"


def test_normalize_asset_class_case_insensitive():
    from scraper.taxonomies.normalizer import normalize_asset_class
    assert normalize_asset_class("MERCADOS PUBLICOS FIJO") == "Mercados Públicos - Fijo"


def test_normalize_asset_class_fuzzy_match_above_threshold():
    from scraper.taxonomies.normalizer import normalize_asset_class
    # 'Mercados Publicos Variables' (typo extra 's') debería matchear
    assert normalize_asset_class("Mercados Publicos Variables") == "Mercados Públicos - Variable"


def test_normalize_asset_class_unknown_returns_none():
    from scraper.taxonomies.normalizer import normalize_asset_class
    assert normalize_asset_class("Crypto Kingdom Nonsense") is None


def test_normalize_region_variants():
    from scraper.taxonomies.normalizer import normalize_region
    assert normalize_region("Peru") == "Perú"
    assert normalize_region("USA") == "EEUU"
    assert normalize_region("Latam ex-Peru") == "Latam ex-Perú"


def test_normalize_percentage_dict_asset_class():
    from scraper.taxonomies.normalizer import normalize_percentage_dict_asset_class
    raw = {"Club deal": 50.0, "Efectivo": 30.0, "Unknown Stuff": 20.0}
    result = normalize_percentage_dict_asset_class(raw)
    # Club deal → Club deals, Efectivo → Cash y Otros, Unknown → descartado
    assert result == {"Club deals": 50.0, "Cash y Otros": 30.0}


def test_normalize_percentage_dict_merges_duplicate_keys():
    from scraper.taxonomies.normalizer import normalize_percentage_dict_asset_class
    # Dos variantes que mapean a la misma canónica deben sumarse
    raw = {"Efectivo": 15.0, "Otros": 5.0, "cash y otros": 10.0}
    result = normalize_percentage_dict_asset_class(raw)
    assert result == {"Cash y Otros": 30.0}
```

- [ ] **Step 3: Run — 8 fail**

```bash
poetry run pytest tests/unit/test_normalizer.py -v
```

- [ ] **Step 4: Implement normalizer**

`src/scraper/taxonomies/normalizer.py`:

```python
"""Normalize taxonomy variants to canonical values.

Strategy:
1. Try exact match against canonical taxonomy (case-insensitive, accent-insensitive)
2. Try known variants dict
3. Try rapidfuzz fuzzy match above threshold 85
4. Return None if no match
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from scraper.taxonomies.loader import load_asset_classes, load_regions

_THIS_DIR = Path(__file__).parent
_VARIANTS_FILE = _THIS_DIR / "normalizer_variants.yaml"
_FUZZY_THRESHOLD = 85.0


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _normalize_key(s: str) -> str:
    return _strip_accents(s.lower().strip())


@lru_cache(maxsize=1)
def _load_variants() -> dict:
    with open(_VARIANTS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_canonical_lookup(canonical_names: list[str]) -> dict[str, str]:
    """Index from normalized key → original canonical form."""
    return {_normalize_key(n): n for n in canonical_names}


def _normalize_via_table(
    raw: str,
    canonical_names: list[str],
    variants: dict[str, str],
) -> str | None:
    """1. exact-normalized match, 2. known variants, 3. fuzzy match."""
    if not raw:
        return None

    key = _normalize_key(raw)
    canon_lookup = _build_canonical_lookup(canonical_names)

    # 1. Exact canonical
    if key in canon_lookup:
        return canon_lookup[key]

    # 2. Known variants
    if key in variants:
        return variants[key]

    # 3. Fuzzy against canonical + variants
    candidates = list(canon_lookup.keys()) + list(variants.keys())
    match = process.extractOne(key, candidates, scorer=fuzz.ratio)
    if match is None:
        return None
    matched_key, score, _ = match
    if score < _FUZZY_THRESHOLD:
        return None
    if matched_key in canon_lookup:
        return canon_lookup[matched_key]
    return variants[matched_key]


def normalize_asset_class(raw: str) -> str | None:
    variants_all = _load_variants()
    variants = {_normalize_key(k): v for k, v in variants_all["asset_class_variants"].items()}
    canonical_names = [c.name for c in load_asset_classes()]
    return _normalize_via_table(raw, canonical_names, variants)


def normalize_region(raw: str) -> str | None:
    variants_all = _load_variants()
    variants = {_normalize_key(k): v for k, v in variants_all["region_variants"].items()}
    canonical_names = [r.name for r in load_regions()]
    return _normalize_via_table(raw, canonical_names, variants)


def normalize_percentage_dict_asset_class(raw: dict[str, float]) -> dict[str, float]:
    """Normalize keys to canonical asset class names. Drop unknowns. Merge duplicates."""
    result: dict[str, float] = {}
    for k, v in raw.items():
        canonical = normalize_asset_class(k)
        if canonical is None:
            continue
        result[canonical] = result.get(canonical, 0.0) + v
    return result


def normalize_percentage_dict_region(raw: dict[str, float]) -> dict[str, float]:
    """Normalize keys to canonical region names. Drop unknowns. Merge duplicates."""
    result: dict[str, float] = {}
    for k, v in raw.items():
        canonical = normalize_region(k)
        if canonical is None:
            continue
        result[canonical] = result.get(canonical, 0.0) + v
    return result
```

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/unit/test_normalizer.py -v
```

Esperado: 8 passed.

- [ ] **Step 6: Lint + commit**

```bash
poetry run ruff check src/scraper/taxonomies/normalizer.py tests/unit/test_normalizer.py
git add src/scraper/taxonomies/normalizer.py src/scraper/taxonomies/normalizer_variants.yaml tests/unit/test_normalizer.py
git commit -m "feat: add taxonomy normalizer (variants → canonical with fuzzy fallback)"
```

---

## Task 3: LLM client wrapper + cost tracking

Wraps `AsyncAnthropic` con: (1) cost tracking por llamada, (2) retry con tenacity, (3) helper para prompt caching. Separa la infraestructura LLM de la lógica de los agentes — facilita mocking en tests.

**Files:**
- Create: `src/scraper/llm/__init__.py`
- Create: `src/scraper/llm/cost.py`
- Create: `src/scraper/llm/client.py`
- Create: `src/scraper/llm/retry.py`
- Create: `tests/unit/test_llm_cost.py`

**Step 1: Agregar anthropic + tenacity a deps**

```bash
poetry add "anthropic>=0.40" "tenacity>=8.2"
```

- [ ] **Step 2: Test cost calculator**

`tests/unit/test_llm_cost.py`:

```python
import pytest


def test_cost_sonnet_46_calculation():
    # Claude Sonnet 4.6: input $3/MTok, output $15/MTok
    from scraper.llm.cost import ClaudeCost, Usage, calculate_cost

    usage = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=0, cache_write_tokens=0)
    cost = calculate_cost("claude-sonnet-4-6", usage)
    # 1000/1e6 * 3 + 500/1e6 * 15 = 0.003 + 0.0075 = 0.0105
    assert cost.total_usd == pytest.approx(0.0105, rel=1e-3)


def test_cost_opus_47_higher_than_sonnet():
    from scraper.llm.cost import Usage, calculate_cost

    usage = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=0, cache_write_tokens=0)
    sonnet = calculate_cost("claude-sonnet-4-6", usage)
    opus = calculate_cost("claude-opus-4-7", usage)
    assert opus.total_usd > sonnet.total_usd


def test_cost_cache_read_is_90_percent_discount():
    # Cache reads cost 10% of input rate
    from scraper.llm.cost import Usage, calculate_cost

    # Sonnet: input $3/MTok → cache read $0.30/MTok
    usage_normal = Usage(input_tokens=1_000_000, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0)
    usage_cached = Usage(input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000, cache_write_tokens=0)

    normal_cost = calculate_cost("claude-sonnet-4-6", usage_normal)
    cached_cost = calculate_cost("claude-sonnet-4-6", usage_cached)

    assert cached_cost.total_usd == pytest.approx(normal_cost.total_usd * 0.10, rel=0.01)


def test_cost_unknown_model_raises():
    from scraper.llm.cost import Usage, calculate_cost

    with pytest.raises(ValueError, match="Unknown model"):
        calculate_cost("claude-fictional-99", Usage(1, 1, 0, 0))
```

- [ ] **Step 3: Run — fail**

```bash
poetry run pytest tests/unit/test_llm_cost.py -v
```

- [ ] **Step 4: Implement cost module**

`src/scraper/llm/cost.py`:

```python
"""Claude pricing — input/output tokens per 1M with cache discounts.

Reference prices as of 2026 (update if Anthropic changes):
- Claude Sonnet 4.6: $3/MTok input, $15/MTok output
- Claude Opus 4.7: $15/MTok input, $75/MTok output
- Cache reads: 10% of input rate
- Cache writes: 125% of input rate (5min TTL) or 200% (1h TTL) — we use 5min default
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


@dataclass(frozen=True)
class ClaudeCost:
    input_usd: float
    output_usd: float
    cache_read_usd: float
    cache_write_usd: float

    @property
    def total_usd(self) -> float:
        return self.input_usd + self.output_usd + self.cache_read_usd + self.cache_write_usd


_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    # (input_usd_per_mtok, output_usd_per_mtok)
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (15.0, 75.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),
}


def calculate_cost(model: str, usage: Usage) -> ClaudeCost:
    if model not in _PRICING_PER_MTOK:
        raise ValueError(f"Unknown model: {model}")
    input_rate, output_rate = _PRICING_PER_MTOK[model]
    cache_read_rate = input_rate * 0.10  # 10% of input
    cache_write_rate = input_rate * 1.25  # 125% of input (5min TTL)

    return ClaudeCost(
        input_usd=usage.input_tokens / 1_000_000 * input_rate,
        output_usd=usage.output_tokens / 1_000_000 * output_rate,
        cache_read_usd=usage.cache_read_tokens / 1_000_000 * cache_read_rate,
        cache_write_usd=usage.cache_write_tokens / 1_000_000 * cache_write_rate,
    )
```

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/unit/test_llm_cost.py -v
```

Esperado: 4 passed.

- [ ] **Step 6: Implement retry helper**

`src/scraper/llm/retry.py`:

```python
"""Retry helper for Anthropic API calls with exponential backoff."""
from __future__ import annotations

from anthropic import APIConnectionError, APIStatusError, RateLimitError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def make_retry() -> AsyncRetrying:
    """Standard retry policy: 3 attempts, 2s-4s-8s backoff, transient errors only."""
    return AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=8),
        retry=retry_if_exception_type((APIConnectionError, RateLimitError, APIStatusError)),
        reraise=True,
    )
```

- [ ] **Step 7: Implement client**

`src/scraper/llm/client.py`:

```python
"""AsyncAnthropic wrapper with cost tracking, retry, and prompt caching support."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam

from scraper.config import get_settings
from scraper.llm.cost import ClaudeCost, Usage, calculate_cost
from scraper.llm.retry import make_retry

log = structlog.get_logger()


@dataclass
class CallResult:
    """Outcome of a single Claude API call."""

    model: str
    response_text: str
    raw_message: Message
    cost: ClaudeCost
    duration_ms: int


@dataclass
class CostAccumulator:
    total_usd: float = 0.0
    call_count: int = 0
    by_model: dict[str, float] = field(default_factory=dict)

    def add(self, model: str, cost: ClaudeCost) -> None:
        self.total_usd += cost.total_usd
        self.call_count += 1
        self.by_model[model] = self.by_model.get(model, 0.0) + cost.total_usd


class LLMClient:
    """Wraps AsyncAnthropic with cost tracking + retry."""

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.cost = CostAccumulator()

    async def call(
        self,
        *,
        model: str,
        system: str | list[dict[str, Any]],
        messages: list[MessageParam],
        max_tokens: int = 4096,
        temperature: float = 0.0,
        extra_headers: dict[str, str] | None = None,
    ) -> CallResult:
        """Make a Claude call with retry + cost tracking."""
        import time

        start = time.monotonic()
        retryer = make_retry()
        async for attempt in retryer:
            with attempt:
                msg = await self._client.messages.create(
                    model=model,
                    system=system,  # type: ignore[arg-type]
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    extra_headers=extra_headers or {},
                )
        duration_ms = int((time.monotonic() - start) * 1000)

        # Extract usage
        u = msg.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        cost = calculate_cost(model, usage)
        self.cost.add(model, cost)
        log.info(
            "llm_call",
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read=usage.cache_read_tokens,
            cache_write=usage.cache_write_tokens,
            cost_usd=round(cost.total_usd, 4),
            duration_ms=duration_ms,
        )

        # Extract text
        text_parts = [b.text for b in msg.content if b.type == "text"]  # type: ignore[attr-defined]
        response_text = "\n".join(text_parts)

        return CallResult(
            model=model,
            response_text=response_text,
            raw_message=msg,
            cost=cost,
            duration_ms=duration_ms,
        )
```

- [ ] **Step 8: Init module**

`src/scraper/llm/__init__.py`:

```python
from scraper.llm.client import CallResult, CostAccumulator, LLMClient
from scraper.llm.cost import ClaudeCost, Usage, calculate_cost

__all__ = [
    "CallResult",
    "ClaudeCost",
    "CostAccumulator",
    "LLMClient",
    "Usage",
    "calculate_cost",
]
```

- [ ] **Step 9: Lint + commit**

```bash
poetry run ruff check src/scraper/llm/ tests/unit/test_llm_cost.py
git add src/scraper/llm/ tests/unit/test_llm_cost.py pyproject.toml poetry.lock
git commit -m "feat: add Anthropic client wrapper with cost tracking and retry"
```

---

## Task 4: Agent types + orchestrator decision logic

Dataclasses para los outputs del clasificador y revisor + la lógica pura de decisión del orchestrator (el if/elif de `low_quality > needs_review > auto_approvable`). Sin llamar a LLM todavía — solo tipos y lógica testeable aislada.

**Files:**
- Create: `src/scraper/agents/__init__.py`
- Create: `src/scraper/agents/types.py`
- Create: `src/scraper/agents/orchestrator.py` (solo la función pura `decide_flag`)
- Create: `tests/unit/test_agent_types.py`
- Create: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: Tests**

`tests/unit/test_agent_types.py`:

```python
import pytest


def test_classification_result_roundtrip_json():
    from scraper.agents.types import AttributeClassification, ClassificationResult

    r = ClassificationResult(
        producto="Test",
        attributes={
            "foco_geografico": AttributeClassification(
                value={"Perú": 100.0},
                confidence=0.95,
                reasoning="Ficha dice Perú 100%",
                rule_applied="regla_geografica_explicita",
            ),
        },
        global_confidence=0.95,
        unknowns=[],
    )
    j = r.to_json()
    r2 = ClassificationResult.from_json(j)
    assert r2.producto == r.producto
    assert r2.attributes["foco_geografico"].value == {"Perú": 100.0}


def test_classification_result_min_attribute_confidence():
    from scraper.agents.types import AttributeClassification, ClassificationResult

    r = ClassificationResult(
        producto="X",
        attributes={
            "a": AttributeClassification(value="a", confidence=0.95, reasoning="", rule_applied=""),
            "b": AttributeClassification(value="b", confidence=0.70, reasoning="", rule_applied=""),
        },
        global_confidence=0.80,
        unknowns=[],
    )
    assert r.min_attribute_confidence() == 0.70


def test_review_result_from_json():
    from scraper.agents.types import ReviewResult

    payload = {
        "veredicto": "disagree",
        "attribute_reviews": {
            "clase_activo": {
                "verdict": "disagree",
                "reason": "should be Club deals",
                "suggested_value": {"Club deals": 100.0},
            },
        },
        "global_verdict": "needs_review",
        "reviewer_confidence": 0.88,
    }
    import json
    r = ReviewResult.from_json(json.dumps(payload))
    assert r.global_verdict == "needs_review"
    assert r.has_disagreement() is True
```

`tests/unit/test_orchestrator.py`:

```python
def _cls(attr_confs: dict, global_conf: float):
    from scraper.agents.types import AttributeClassification, ClassificationResult
    attrs = {
        k: AttributeClassification(value=None, confidence=c, reasoning="", rule_applied="")
        for k, c in attr_confs.items()
    }
    return ClassificationResult(
        producto="x", attributes=attrs, global_confidence=global_conf, unknowns=[]
    )


def _rev(verdict: str, has_disagreement: bool):
    from scraper.agents.types import ReviewResult
    return ReviewResult(
        veredicto="disagree" if has_disagreement else "agree",
        attribute_reviews={},
        global_verdict=verdict,
        reviewer_confidence=0.9,
    )


def test_decide_flag_low_quality_when_global_below_70():
    from scraper.agents.orchestrator import decide_flag
    c = _cls({"a": 0.95}, global_conf=0.65)
    r = _rev(verdict="low_quality", has_disagreement=False)
    assert decide_flag(c, r) == "low_quality"


def test_decide_flag_needs_review_on_disagreement():
    from scraper.agents.orchestrator import decide_flag
    c = _cls({"a": 0.95, "b": 0.95}, global_conf=0.95)
    r = _rev(verdict="needs_review", has_disagreement=True)
    assert decide_flag(c, r) == "needs_review"


def test_decide_flag_needs_review_on_low_attribute_confidence():
    from scraper.agents.orchestrator import decide_flag
    c = _cls({"a": 0.95, "b": 0.80}, global_conf=0.87)
    r = _rev(verdict="agree", has_disagreement=False)
    assert decide_flag(c, r) == "needs_review"


def test_decide_flag_auto_approvable_when_all_clean():
    from scraper.agents.orchestrator import decide_flag
    c = _cls({"a": 0.95, "b": 0.92}, global_conf=0.94)
    r = _rev(verdict="agree", has_disagreement=False)
    assert decide_flag(c, r) == "auto_approvable"


def test_decide_flag_priority_low_quality_over_needs_review():
    """Si hay disagreement Y global_confidence < 0.70, low_quality gana."""
    from scraper.agents.orchestrator import decide_flag
    c = _cls({"a": 0.95}, global_conf=0.60)
    r = _rev(verdict="low_quality", has_disagreement=True)
    assert decide_flag(c, r) == "low_quality"
```

- [ ] **Step 2: Fail**

```bash
poetry run pytest tests/unit/test_agent_types.py tests/unit/test_orchestrator.py -v
```

- [ ] **Step 3: Implement types**

`src/scraper/agents/types.py`:

```python
"""Dataclasses for classifier and reviewer outputs."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AttributeClassification:
    value: Any
    confidence: float
    reasoning: str
    rule_applied: str


@dataclass(frozen=True)
class ClassificationResult:
    producto: str
    attributes: dict[str, AttributeClassification]
    global_confidence: float
    unknowns: list[str] = field(default_factory=list)

    def min_attribute_confidence(self) -> float:
        if not self.attributes:
            return 0.0
        return min(a.confidence for a in self.attributes.values())

    def to_json(self) -> str:
        payload = {
            "producto": self.producto,
            "global_confidence": self.global_confidence,
            "unknowns": list(self.unknowns),
            "attributes": {
                k: asdict(v) for k, v in self.attributes.items()
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str | dict) -> ClassificationResult:
        p = json.loads(data) if isinstance(data, str) else data
        attrs = {
            k: AttributeClassification(
                value=v["value"],
                confidence=float(v["confidence"]),
                reasoning=str(v.get("reasoning", "")),
                rule_applied=str(v.get("rule_applied", "")),
            )
            for k, v in p.get("attributes", {}).items()
        }
        return cls(
            producto=str(p["producto"]),
            attributes=attrs,
            global_confidence=float(p.get("global_confidence", 0.0)),
            unknowns=list(p.get("unknowns", [])),
        )


@dataclass(frozen=True)
class AttributeReview:
    verdict: str  # agree | disagree | partial
    reason: str = ""
    suggested_value: Any = None


@dataclass(frozen=True)
class ReviewResult:
    veredicto: str  # agree | disagree | partial (overall)
    attribute_reviews: dict[str, AttributeReview]
    global_verdict: str  # auto_approvable | needs_review | low_quality
    reviewer_confidence: float

    def has_disagreement(self) -> bool:
        if self.veredicto == "disagree":
            return True
        return any(a.verdict == "disagree" for a in self.attribute_reviews.values())

    @classmethod
    def from_json(cls, data: str | dict) -> ReviewResult:
        p = json.loads(data) if isinstance(data, str) else data
        reviews = {
            k: AttributeReview(
                verdict=str(v["verdict"]),
                reason=str(v.get("reason", "")),
                suggested_value=v.get("suggested_value"),
            )
            for k, v in p.get("attribute_reviews", {}).items()
        }
        return cls(
            veredicto=str(p["veredicto"]),
            attribute_reviews=reviews,
            global_verdict=str(p.get("global_verdict", "needs_review")),
            reviewer_confidence=float(p.get("reviewer_confidence", 0.0)),
        )
```

- [ ] **Step 4: Implement orchestrator decision**

`src/scraper/agents/orchestrator.py`:

```python
"""Pure decision logic for classification flag assignment.

Priority: low_quality > needs_review > auto_approvable.
"""
from __future__ import annotations

from scraper.agents.types import ClassificationResult, ReviewResult

GLOBAL_CONFIDENCE_THRESHOLD = 0.70
PER_ATTRIBUTE_THRESHOLD = 0.90


def decide_flag(classifier: ClassificationResult, reviewer: ReviewResult) -> str:
    """Return one of: low_quality, needs_review, auto_approvable."""
    # 1. Low quality if either global confidence is too low or reviewer says so
    if (
        classifier.global_confidence < GLOBAL_CONFIDENCE_THRESHOLD
        or reviewer.global_verdict == "low_quality"
    ):
        return "low_quality"

    # 2. Needs review if any disagreement or low attribute confidence
    if reviewer.has_disagreement():
        return "needs_review"
    if classifier.min_attribute_confidence() < PER_ATTRIBUTE_THRESHOLD:
        return "needs_review"

    # 3. Everything clean
    return "auto_approvable"
```

- [ ] **Step 5: Init**

`src/scraper/agents/__init__.py`:

```python
from scraper.agents.orchestrator import decide_flag
from scraper.agents.types import (
    AttributeClassification,
    AttributeReview,
    ClassificationResult,
    ReviewResult,
)

__all__ = [
    "AttributeClassification",
    "AttributeReview",
    "ClassificationResult",
    "ReviewResult",
    "decide_flag",
]
```

- [ ] **Step 6: Tests pass**

```bash
poetry run pytest tests/unit/test_agent_types.py tests/unit/test_orchestrator.py -v
```

Esperado: 8 passed (3 types + 5 orchestrator).

- [ ] **Step 7: Lint + commit**

```bash
poetry run ruff check src/scraper/agents/ tests/unit/test_agent_types.py tests/unit/test_orchestrator.py
git add src/scraper/agents/ tests/unit/test_agent_types.py tests/unit/test_orchestrator.py
git commit -m "feat: add agent types (ClassificationResult, ReviewResult) and orchestrator flag logic"
```

---

## Task 5: Rules v1.md — reglas iniciales escritas

Crear `rules/v1.md` con la filosofía de clasificación inicial, basada en inspección de los 91 productos de training. Este doc va en el prompt system del clasificador. Se refina iterativamente.

**Files:**
- Create: `rules/v1.md`
- Create: `src/scraper/scripts/bootstrap_rules_v1.py` (helper para inspeccionar training)

Este es un trabajo semi-manual. Las reglas las escribes tú (Sabbi) basándote en tu lógica de clasificación + inspección de patrones del training_set.

- [ ] **Step 1: Bootstrap helper — analyze training_set**

`src/scraper/scripts/bootstrap_rules_v1.py`:

```python
"""Analyze training_set and print patterns to inform rules v1 drafting.

This does NOT auto-generate rules — it surfaces patterns for human drafting.
"""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict

from sqlalchemy import select

from scraper.db.models import Product, TrainingSet
from scraper.db.session import get_session
from scraper.taxonomies.normalizer import normalize_asset_class


async def _main() -> None:
    async with get_session() as s:
        r = await s.execute(
            select(Product).join(TrainingSet, Product.id == TrainingSet.product_id)
        )
        products = list(r.scalars().all())

    print(f"\n=== Training set: {len(products)} productos ===\n")

    # 1. Distribución por dominant macro class
    dominant = Counter()
    for p in products:
        if not p.clase_activo:
            continue
        dom = max(p.clase_activo.items(), key=lambda kv: kv[1])[0]
        dominant[normalize_asset_class(dom) or dom] += 1
    print("Distribución por clase macro dominante:")
    for k, v in dominant.most_common():
        print(f"  {k}: {v}")

    # 2. Subyacentes canónicos más usados
    subyacente_counts: Counter = Counter()
    for p in products:
        for k in p.subyacentes.keys():
            subyacente_counts[k] += 1
    print("\nTop 15 subyacentes más frecuentes:")
    for k, v in subyacente_counts.most_common(15):
        print(f"  {k}: {v}")

    # 3. Patrones administrador → clase macro
    admin_to_classes: dict[str, Counter] = defaultdict(Counter)
    for p in products:
        if not p.administrador or not p.clase_activo:
            continue
        dom = max(p.clase_activo.items(), key=lambda kv: kv[1])[0]
        admin_to_classes[p.administrador][normalize_asset_class(dom) or dom] += 1
    print("\nAdministradores y clases típicas:")
    for admin, classes in sorted(admin_to_classes.items()):
        top = ", ".join(f"{c}:{n}" for c, n in classes.most_common(3))
        print(f"  {admin}: {top}")

    # 4. Liquidez × clase macro
    liq_to_class: dict[str, Counter] = defaultdict(Counter)
    for p in products:
        if not p.liquidez or not p.clase_activo:
            continue
        dom = max(p.clase_activo.items(), key=lambda kv: kv[1])[0]
        liq_to_class[p.liquidez.lower()][normalize_asset_class(dom) or dom] += 1
    print("\nLiquidez → clase típica:")
    for liq, cs in sorted(liq_to_class.items()):
        top = ", ".join(f"{c}:{n}" for c, n in cs.most_common(2))
        print(f"  {liq}: {top}")


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 2: Correr el helper y copiar output**

```bash
poetry run python -m scraper.scripts.bootstrap_rules_v1
```

Guardar el output. Lo vas a usar para redactar las reglas en `rules/v1.md`.

- [ ] **Step 3: Crear rules/v1.md**

`rules/v1.md`:

```markdown
# Sabbi — Filosofía de Clasificación de Productos de Inversión — v1

**Fecha:** 2026-04-17
**Autor:** Sabbi + Claude

Este documento codifica cómo el equipo de Sabbi clasifica productos de inversión en las taxonomías canónicas. El agente clasificador lo recibe como system prompt. Las reglas se iteran con cada ronda de calibración contra `validation_set`.

---

## Principios generales

1. **Solo valores canónicos.** Las claves de `foco_geografico` vienen de las 5 regiones (EEUU, Desarrollados ex-US, Emergentes ex-Perú, Latam ex-Perú, Perú). Las claves de `clase_activo` vienen de las 6 macro. Las de `subyacentes`, de los ~32 canónicos. NO inventar.

2. **Porcentajes suman 100%.** En `foco_geografico`, `clase_activo`, y `subyacentes` individualmente — cada dict suma 100% ± 2pp (tolerancia por redondeo).

3. **Consistencia subyacente ↔ clase macro.** Cada subyacente pertenece a UNA clase macro (ver `canonical_assets.yaml`). Si un producto tiene 60% subyacente X y X pertenece a macro Y, entonces macro Y debe tener ≥60% en `clase_activo`.

4. **Reglas explícitas > inferencia del nombre.** Si la ficha dice "Club deal 100%" literalmente, clasificar "Club deals" aunque el nombre suene a mercado privado. La ficha gana.

5. **Confianza honesta.** Si la ficha no menciona un atributo (ej. comisión) → `value=null, confidence=0.0, reasoning="no encontrado"`. No inventar ni default.

---

## Reglas específicas por atributo

### Clase de Activo

- **Club deal vs Mercados Privados.** Ambos invierten en activos privados. La diferencia está en la estructura:
  - **Club deal:** fondo cerrado, pocos inversionistas (típicamente <50), co-inversión directa en un único activo o proyecto, sin liquidez secundaria.
  - **Mercados Privados:** fondo abierto/cerrado con muchos inversionistas, diversificado en múltiples activos privados (private equity, venture, private credit, real estate fondos de fondos).
  - Señales: si la ficha menciona "deal único", "co-inversión", "fondo cerrado con X participantes" → Club deal. Si es "fund of funds" o "estrategia diversificada de private equity" → Mercados Privados.

- **ETFs que replican índices amplios.** Siempre clasificar por el índice:
  - S&P 500 → US Large Cap (Mercados Públicos - Variable)
  - Russell 2000 → US Mid & Small Cap (Mercados Públicos - Variable)
  - MSCI EAFE → Desarrollados ex US (Mercados Públicos - Variable)
  - MSCI Emerging Markets → Mercados Emergentes ex Perú (Mercados Públicos - Variable)
  - Bloomberg Aggregate Bond → mix de Bonos Corporativos IG + US Treasuries
  - LQD iShares → Bonos Corporativos Investment Grade (AAA-BBB)
  - IEF iShares → US Treasuries - Largo Plazo
  - BIL SPDR → US Treasuries Corto Plazo (Cash y Otros)

- **Fondos mixtos.** Si el producto combina renta fija y variable, desglosar `clase_activo` en sus componentes con sus pesos. Ej: 60/40 balanced → `{"Mercados Públicos - Variable": 60, "Mercados Públicos - Fijo": 40}`.

- **Ahorro / Money Market.** Si es cuenta de ahorro o fondo money market en moneda local o USD → `Cash y Otros: 100`, subyacente `Cash: 100`. Liquidez = `Inmediata`.

- **Factoring / Deuda privada peruana.** Ej: Finsmart. Subyacente `Private Credit Senior` → Mercados Privados o Club deals según estructura (con pocos inversionistas → Club deal).

### Foco Geográfico

- Si la ficha dice "100% Perú" → `{"Perú": 100}`.
- Si dice "Global" sin desglose, NO inventar — marcar unknown y confidence baja.
- Si dice "Latam" sin especificar Perú, asumir `{"Latam ex-Perú": 70, "Perú": 30}` como heurística, pero bajar confidence a ≤0.70 y notar el assumption en reasoning.
- Productos de Credicorp/BCP típicamente son Perú + Emergentes ex-Perú mix. Productos de Sabadell = USA 100%.

### Subyacentes

- Usar `canonical_assets.yaml` como vocabulario obligatorio.
- Si la ficha lista varios ETFs/fondos subyacentes, mapear cada uno a su canónico y sumar pesos.
- Ej: ficha dice "70% VTI, 30% BND" → `{"US Large Cap": 70, "Bonos Corporativos Investment Grade (AAA-BBB)": 30}` (aunque BND tiene mix, aproximar al dominante).

### Comisión

- Extraer como decimal (0.0325 = 3.25%).
- Si hay múltiples clases (A, B, C) con comisiones distintas, devolver como string: `"Clase A 1.75%, Clase B 1.05%"`. Campo numeric comision = null, comision_raw = string.
- Si la ficha dice "sin comisión" o "0%" → comision = 0.0.

### Moneda

- Valores canónicos: `"soles"` o `"dolares"`. Lower case. Sin tildes. Si la ficha dice "PEN" o "S/." → soles. Si dice "USD" o "$" → dolares.

### Liquidez

- Canónicos: `Inmediata`, `Corto plazo`, `Mediano plazo`, `Largo plazo` (capitalizado, con espacio).
- Money market / ahorro → Inmediata.
- Bonos a vencimiento < 1 año → Corto plazo.
- Fondos públicos con redemption diario pero horizonte 1-3 años → Mediano plazo.
- Fondos cerrados, Club deals, Private Equity → Largo plazo.

### Administrador vs Gestor

- **Administrador:** la entidad legal que administra el fondo (ej. Credicorp Capital SAF).
- **Gestor:** quien toma decisiones de inversión (puede ser el mismo que administrador, o un tercero como Sabbi cuando Core Capital es administrador).
- Si no está claro quién es cuál, admin = gestor (mismo valor).

### Mínimo inversión

- Extraer como string original (ej. `"150k dolares"`, `"5,000 soles"`). No convertir a número — los formatos varían.
- Si no se menciona → `null`.

---

## Proceso cuando hay duda

1. Aplicar la regla más específica primero (ej. "fondo cerrado con pocos inversionistas" gana sobre "invierte en real estate").
2. Si dos reglas compiten, preferir la de mayor `confidence` en el reasoning.
3. Si la data es ambigua, bajar confidence del atributo afectado a ≤0.70 y explicar en reasoning.
4. NO inventar. Mejor decir "no encontrado" con confidence 0 que poblar con un guess.

---

## Versionado

- v1: inicial (2026-04-17). Basado en inspección manual de 91 productos training.
- v2, v3, ...: se refinan después de cada ronda de calibración. Ver `rules_versions.validation_accuracy` en DB para métricas por versión.
```

**Nota al ejecutar este task:** las reglas de arriba son un PRIMER BORRADOR. El implementador debe:
1. Correr `bootstrap_rules_v1.py` y capturar output
2. Compartirlo con Sabbi (o dejarlo en un comentario) para que revise si las reglas reflejan su lógica real
3. **No asumir que las reglas de arriba son correctas.** Sabbi debe revisarlas.

Si el implementador es un subagente autónomo, debe reportar DONE_WITH_CONCERNS pidiendo review humano del contenido de v1.md antes de seguir.

- [ ] **Step 4: Lint + commit (el archivo de reglas no se lintea, pero el script sí)**

```bash
poetry run ruff check src/scraper/scripts/bootstrap_rules_v1.py
git add rules/v1.md src/scraper/scripts/bootstrap_rules_v1.py
git commit -m "feat: add rules v1.md (initial classification philosophy) + bootstrap analyzer"
```

---

## Task 6: Prompt builder — arma el system prompt del clasificador

Construye el system prompt combinando: (a) rules v1.md, (b) taxonomías canónicas, (c) few-shot examples del training_set, (d) instrucciones de output JSON. Usa prompt caching.

**Files:**
- Create: `src/scraper/agents/prompts/__init__.py`
- Create: `src/scraper/agents/prompts/classifier_system.md`
- Create: `src/scraper/agents/prompts/builder.py`
- Create: `tests/unit/test_prompt_builder.py`

- [ ] **Step 1: Crear template system.md**

`src/scraper/agents/prompts/classifier_system.md`:

```markdown
Eres el Clasificador de Productos de Inversión de Sabbi. Tu trabajo es clasificar un producto de inversión en las taxonomías canónicas de Sabbi, aplicando las reglas explícitas y los ejemplos de entrenamiento que te doy.

## REGLAS DE CLASIFICACIÓN (v1)

{{RULES_MD}}

## TAXONOMÍAS CANÓNICAS (lista cerrada — NO inventes valores)

### Clases de Activo Macro (exactamente 6)
{{ASSET_CLASSES}}

### Subyacentes Canónicos (exactamente {{N_CANONICAL_ASSETS}})
{{CANONICAL_ASSETS}}

### Regiones Geográficas (exactamente 5)
{{REGIONS}}

## EJEMPLOS DE ENTRENAMIENTO (ya clasificados por el equipo humano)

{{FEW_SHOT_EXAMPLES}}

## OUTPUT — formato obligatorio

Responde EXACTAMENTE con un objeto JSON válido con esta estructura:

```json
{
  "producto": "nombre del producto que clasificas",
  "attributes": {
    "foco_geografico": {
      "value": { "Perú": 65.0, "EEUU": 35.0 },
      "confidence": 0.95,
      "reasoning": "breve justificación (1-2 oraciones)",
      "rule_applied": "nombre de regla o patrón aplicado"
    },
    "clase_activo": { "value": { "Mercados Públicos - Variable": 100.0 }, "confidence": 0.92, "reasoning": "...", "rule_applied": "..." },
    "subyacente": { "value": { "US Large Cap": 100.0 }, "confidence": 0.95, "reasoning": "...", "rule_applied": "..." },
    "comision": { "value": 0.0325, "confidence": 1.0, "reasoning": "...", "rule_applied": "..." },
    "moneda": { "value": "soles", "confidence": 1.0, "reasoning": "...", "rule_applied": "..." },
    "administrador": { "value": "Credicorp Capital", "confidence": 1.0, "reasoning": "...", "rule_applied": "..." },
    "gestor": { "value": "Credicorp Capital", "confidence": 1.0, "reasoning": "...", "rule_applied": "..." },
    "liquidez": { "value": "Mediano plazo", "confidence": 0.90, "reasoning": "...", "rule_applied": "..." },
    "minimo_inversion": { "value": "5000 soles", "confidence": 0.80, "reasoning": "...", "rule_applied": "..." }
  },
  "global_confidence": 0.92,
  "unknowns": ["lista de atributos que no pudiste determinar"]
}
```

Reglas de output:
- Si un atributo es desconocido: `value: null, confidence: 0.0, reasoning: "no encontrado", rule_applied: ""` y agregarlo a `unknowns`.
- `foco_geografico`, `clase_activo`, `subyacente` son dicts donde las claves son nombres canónicos y los valores son porcentajes que suman 100%.
- `global_confidence` es tu confianza general (0.0 a 1.0) de que la clasificación completa es correcta. Promedio ponderado aproximado de confidences individuales.
- Responde SOLO el JSON. Sin texto antes ni después. Sin ```json ``` fences.

## INPUT QUE VAS A RECIBIR

El mensaje `user` contendrá el producto a clasificar en el siguiente formato:

```
Producto: "Nombre del Producto"
Administrador: XYZ (si se conoce)
Gestor: ABC (si se conoce)
Moneda: soles|dolares (si se conoce)
Liquidez: ... (si se conoce)
Otra información adicional: ...
```

Clasifica basándote en esa info + tu conocimiento del producto + las reglas + los ejemplos.
```

- [ ] **Step 2: Tests prompt builder**

`tests/unit/test_prompt_builder.py`:

```python
import pytest


def test_build_classifier_system_prompt_includes_rules_and_taxonomies():
    from scraper.agents.prompts.builder import build_classifier_system_prompt

    prompt = build_classifier_system_prompt(
        rules_md="# My Rules\n- rule 1",
        few_shot_examples=[],
    )
    assert "# My Rules" in prompt
    assert "Mercados Públicos - Variable" in prompt  # taxonomía incluida
    assert "Perú" in prompt  # región incluida
    assert "US Large Cap" in prompt  # subyacente incluido


def test_build_classifier_system_prompt_includes_few_shot():
    from scraper.agents.prompts.builder import build_classifier_system_prompt

    example = {
        "producto": "Test Fondo",
        "input_text": "Producto: Test Fondo\nAdministrador: X",
        "expected_output": {"producto": "Test Fondo", "attributes": {}, "global_confidence": 1.0, "unknowns": []},
    }
    prompt = build_classifier_system_prompt(
        rules_md="# Rules",
        few_shot_examples=[example],
    )
    assert "Test Fondo" in prompt


def test_build_classifier_cache_blocks():
    """Verifica que build_classifier_system_blocks devuelve lista de blocks con cache_control."""
    from scraper.agents.prompts.builder import build_classifier_system_blocks

    blocks = build_classifier_system_blocks(rules_md="# Rules", few_shot_examples=[])
    assert isinstance(blocks, list)
    assert all("type" in b and b["type"] == "text" for b in blocks)
    # El último block debe tener cache_control para cachear todo hasta ahí
    assert any("cache_control" in b for b in blocks)


async def test_build_few_shot_from_db(seeded_and_split_session):
    """Should produce few-shot entries from training_set products."""
    from scraper.agents.prompts.builder import build_few_shot_from_db

    examples = await build_few_shot_from_db(seeded_and_split_session, limit=5)
    assert len(examples) == 5
    assert all("producto" in e for e in examples)
    assert all("input_text" in e for e in examples)
    assert all("expected_output" in e for e in examples)
```

Para la fixture `seeded_and_split_session`, extender conftest. Agregar a `tests/conftest.py`:

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def seeded_and_split_session(excel_path):
    from scraper.db.base import Base
    from scraper.db import models  # noqa: F401
    from scraper.scripts.seed_from_excel import seed_products
    from scraper.scripts.split_train_validation import run_split

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with session_local() as s:
        await seed_products(s, excel_path)
        await run_split(s, validation_ratio=0.2, seed=42)
        yield s
    await engine.dispose()
```

- [ ] **Step 3: Run — fail**

```bash
poetry run pytest tests/unit/test_prompt_builder.py -v
```

- [ ] **Step 4: Implement builder**

`src/scraper/agents/prompts/__init__.py`:

```python
from scraper.agents.prompts.builder import (
    build_classifier_system_blocks,
    build_classifier_system_prompt,
    build_few_shot_from_db,
    build_reviewer_system_blocks,
)

__all__ = [
    "build_classifier_system_blocks",
    "build_classifier_system_prompt",
    "build_few_shot_from_db",
    "build_reviewer_system_blocks",
]
```

`src/scraper/agents/prompts/builder.py`:

```python
"""Assemble system prompts for classifier and reviewer agents."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import Product, TrainingSet
from scraper.taxonomies import load_asset_classes, load_canonical_assets, load_regions

_THIS_DIR = Path(__file__).parent
_CLASSIFIER_TEMPLATE = _THIS_DIR / "classifier_system.md"
_REVIEWER_TEMPLATE = _THIS_DIR / "reviewer_system.md"
_RULES_PATH = Path(__file__).resolve().parents[3] / "rules" / "v1.md"


def _render_taxonomies() -> dict[str, str]:
    classes = load_asset_classes()
    assets = load_canonical_assets()
    regions = load_regions()

    asset_classes_md = "\n".join(f"- {c.name}" for c in classes)
    canonical_assets_md = "\n".join(
        f"- **{a.name}** → macro: {a.macro_class} (score {a.score})" for a in assets
    )
    regions_md = "\n".join(f"- {r.name} (benchmark weight: {r.benchmark_weight:.3f})" for r in regions)

    return {
        "ASSET_CLASSES": asset_classes_md,
        "N_CANONICAL_ASSETS": str(len(assets)),
        "CANONICAL_ASSETS": canonical_assets_md,
        "REGIONS": regions_md,
    }


def _render_few_shot(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return "_(sin ejemplos en este run — clasifica usando solo las reglas)_"
    blocks: list[str] = []
    for i, ex in enumerate(examples, 1):
        blocks.append(
            f"### Ejemplo {i}\n\n"
            f"**Input:**\n```\n{ex['input_text']}\n```\n\n"
            f"**Output esperado:**\n```json\n{json.dumps(ex['expected_output'], ensure_ascii=False, indent=2)}\n```"
        )
    return "\n\n".join(blocks)


def load_rules_md() -> str:
    if not _RULES_PATH.exists():
        raise FileNotFoundError(f"Rules file not found: {_RULES_PATH}")
    return _RULES_PATH.read_text(encoding="utf-8")


def build_classifier_system_prompt(rules_md: str, few_shot_examples: list[dict[str, Any]]) -> str:
    """Single-string system prompt. Useful for non-caching contexts."""
    template = _CLASSIFIER_TEMPLATE.read_text(encoding="utf-8")
    tax = _render_taxonomies()
    prompt = (
        template.replace("{{RULES_MD}}", rules_md)
        .replace("{{ASSET_CLASSES}}", tax["ASSET_CLASSES"])
        .replace("{{N_CANONICAL_ASSETS}}", tax["N_CANONICAL_ASSETS"])
        .replace("{{CANONICAL_ASSETS}}", tax["CANONICAL_ASSETS"])
        .replace("{{REGIONS}}", tax["REGIONS"])
        .replace("{{FEW_SHOT_EXAMPLES}}", _render_few_shot(few_shot_examples))
    )
    return prompt


def build_classifier_system_blocks(
    rules_md: str,
    few_shot_examples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return Anthropic messages API system blocks with prompt caching.

    Strategy: cache everything up to the last block. The whole system prompt
    is identical across calls (rules + taxonomies + few-shot), only the
    user message changes per product.
    """
    full_prompt = build_classifier_system_prompt(rules_md, few_shot_examples)
    return [
        {
            "type": "text",
            "text": full_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_reviewer_system_blocks(rules_md: str) -> list[dict[str, Any]]:
    template = _REVIEWER_TEMPLATE.read_text(encoding="utf-8")
    tax = _render_taxonomies()
    prompt = (
        template.replace("{{RULES_MD}}", rules_md)
        .replace("{{ASSET_CLASSES}}", tax["ASSET_CLASSES"])
        .replace("{{N_CANONICAL_ASSETS}}", tax["N_CANONICAL_ASSETS"])
        .replace("{{CANONICAL_ASSETS}}", tax["CANONICAL_ASSETS"])
        .replace("{{REGIONS}}", tax["REGIONS"])
    )
    return [
        {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}
    ]


def _product_to_example(p: Product) -> dict[str, Any]:
    """Convert a Product to a few-shot example. input = name + basic metadata.
    expected_output = the structured ground truth classification."""
    input_parts = [f'Producto: "{p.nombre}"']
    if p.administrador:
        input_parts.append(f"Administrador: {p.administrador}")
    if p.gestor:
        input_parts.append(f"Gestor: {p.gestor}")
    if p.moneda:
        input_parts.append(f"Moneda: {p.moneda}")
    if p.liquidez:
        input_parts.append(f"Liquidez: {p.liquidez}")
    input_text = "\n".join(input_parts)

    expected = {
        "producto": p.nombre,
        "attributes": {
            "foco_geografico": {
                "value": p.foco_geografico,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
            },
            "clase_activo": {
                "value": p.clase_activo,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
            },
            "subyacente": {
                "value": p.subyacentes,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
            },
            "comision": {
                "value": p.comision if p.comision is not None else p.comision_raw,
                "confidence": 1.0 if p.comision is not None else 0.8,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
            },
            "moneda": {
                "value": p.moneda,
                "confidence": 1.0 if p.moneda else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
            },
            "administrador": {
                "value": p.administrador,
                "confidence": 1.0 if p.administrador else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
            },
            "gestor": {
                "value": p.gestor,
                "confidence": 1.0 if p.gestor else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
            },
            "liquidez": {
                "value": p.liquidez,
                "confidence": 1.0 if p.liquidez else 0.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
            },
        },
        "global_confidence": 1.0,
        "unknowns": [],
    }
    return {"producto": p.nombre, "input_text": input_text, "expected_output": expected}


async def build_few_shot_from_db(
    session: AsyncSession,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch training_set products and format as few-shot examples."""
    q = select(Product).join(TrainingSet, Product.id == TrainingSet.product_id)
    if limit is not None:
        q = q.limit(limit)
    r = await session.execute(q)
    products = list(r.scalars().all())
    return [_product_to_example(p) for p in products]
```

- [ ] **Step 5: Crear reviewer_system.md placeholder**

Este archivo lo completamos en Task 8. Por ahora, crear un stub:

`src/scraper/agents/prompts/reviewer_system.md`:

```markdown
Eres el Revisor del Clasificador. Tu trabajo es CRITICAR una clasificación hecha por otro agente, verificando consistencia con las reglas y taxonomías.

## REGLAS (v1)

{{RULES_MD}}

## TAXONOMÍAS CANÓNICAS

### Clases macro
{{ASSET_CLASSES}}

### Subyacentes ({{N_CANONICAL_ASSETS}})
{{CANONICAL_ASSETS}}

### Regiones
{{REGIONS}}

## Tu job

Recibirás la ficha técnica original y la clasificación del Clasificador. Debes verificar:

1. ¿Cada valor usa vocabulario canónico?
2. ¿El reasoning es consistente con la ficha?
3. ¿Los porcentajes suman 100%?
4. ¿La regla citada (`rule_applied`) existe y aplica?

Responde SOLO un JSON:

```json
{
  "veredicto": "agree|disagree|partial",
  "attribute_reviews": {
    "nombre_atributo": {
      "verdict": "agree|disagree",
      "reason": "breve",
      "suggested_value": null
    }
  },
  "global_verdict": "auto_approvable|needs_review|low_quality",
  "reviewer_confidence": 0.90
}
```
```

- [ ] **Step 6: Tests pass**

```bash
poetry run pytest tests/unit/test_prompt_builder.py -v
```

Esperado: 4 passed.

- [ ] **Step 7: Lint + commit**

```bash
poetry run ruff check src/scraper/agents/prompts/ tests/unit/test_prompt_builder.py tests/conftest.py
git add src/scraper/agents/prompts/ tests/unit/test_prompt_builder.py tests/conftest.py
git commit -m "feat: add prompt builder (classifier + reviewer) with prompt caching blocks"
```

---

## Task 7: Classifier agent (Claude Sonnet 4.6)

Usa el LLMClient + prompt builder para ejecutar clasificaciones reales (con mocks en tests).

**Files:**
- Create: `src/scraper/agents/classifier.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_classifier_mocked.py`

- [ ] **Step 1: Integration test fixture (LLM mocked)**

`tests/integration/__init__.py`: vacío.

`tests/integration/conftest.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_llm_client():
    """LLMClient mock that returns a pre-configured response."""
    from scraper.llm.client import CallResult
    from scraper.llm.cost import ClaudeCost

    client = MagicMock()
    client.call = AsyncMock()
    client.cost = MagicMock()

    def make_result(response_text: str, model: str = "claude-sonnet-4-6") -> CallResult:
        msg = MagicMock()
        msg.usage.input_tokens = 100
        msg.usage.output_tokens = 50
        return CallResult(
            model=model,
            response_text=response_text,
            raw_message=msg,
            cost=ClaudeCost(input_usd=0.0003, output_usd=0.00075, cache_read_usd=0.0, cache_write_usd=0.0),
            duration_ms=1234,
        )

    client.make_result = make_result  # helper for tests
    return client
```

`tests/integration/test_classifier_mocked.py`:

```python
import json

import pytest


async def test_classify_parses_valid_json_output(mock_llm_client):
    from scraper.agents.classifier import classify

    output_json = json.dumps({
        "producto": "Test Fondo",
        "attributes": {
            "foco_geografico": {
                "value": {"Perú": 100.0},
                "confidence": 0.95,
                "reasoning": "ficha dice Perú",
                "rule_applied": "regla_geografica_explicita",
            },
            "clase_activo": {
                "value": {"Mercados Públicos - Variable": 100.0},
                "confidence": 0.90,
                "reasoning": "acciones Peru",
                "rule_applied": "etf_replica_indice",
            },
        },
        "global_confidence": 0.92,
        "unknowns": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output_json)

    result = await classify(
        llm=mock_llm_client,
        producto_nombre="Test Fondo",
        product_context={"administrador": "X"},
        rules_md="# rules",
        few_shot_examples=[],
    )
    assert result.producto == "Test Fondo"
    assert result.attributes["foco_geografico"].value == {"Perú": 100.0}
    assert result.global_confidence == 0.92


async def test_classify_strips_markdown_fences(mock_llm_client):
    from scraper.agents.classifier import classify

    fenced = '```json\n{"producto": "X", "attributes": {}, "global_confidence": 0.5, "unknowns": []}\n```'
    mock_llm_client.call.return_value = mock_llm_client.make_result(fenced)

    result = await classify(
        llm=mock_llm_client,
        producto_nombre="X",
        product_context={},
        rules_md="# r",
        few_shot_examples=[],
    )
    assert result.producto == "X"


async def test_classify_raises_on_invalid_json(mock_llm_client):
    from scraper.agents.classifier import ClassifierParseError, classify

    mock_llm_client.call.return_value = mock_llm_client.make_result("not json at all")

    with pytest.raises(ClassifierParseError):
        await classify(
            llm=mock_llm_client,
            producto_nombre="X",
            product_context={},
            rules_md="#",
            few_shot_examples=[],
        )


async def test_classify_validates_canonical_vocabulary(mock_llm_client):
    """Si el LLM devuelve un valor no canónico en clase_activo, debe rechazarlo o normalizar."""
    from scraper.agents.classifier import classify

    output = json.dumps({
        "producto": "X",
        "attributes": {
            "clase_activo": {
                "value": {"Club deal": 100.0},  # variante, no canónica
                "confidence": 0.9,
                "reasoning": "...",
                "rule_applied": "...",
            },
        },
        "global_confidence": 0.9,
        "unknowns": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(output)

    result = await classify(
        llm=mock_llm_client,
        producto_nombre="X",
        product_context={},
        rules_md="#",
        few_shot_examples=[],
    )
    # El classifier normaliza: "Club deal" → "Club deals"
    assert "Club deals" in result.attributes["clase_activo"].value
```

- [ ] **Step 2: Run — fail**

```bash
poetry run pytest tests/integration/test_classifier_mocked.py -v
```

- [ ] **Step 3: Implement classifier**

`src/scraper/agents/classifier.py`:

```python
"""Classifier agent — uses Claude Sonnet 4.6."""
from __future__ import annotations

import json
import re
from typing import Any

import structlog

from scraper.agents.prompts.builder import build_classifier_system_blocks
from scraper.agents.types import AttributeClassification, ClassificationResult
from scraper.llm import LLMClient
from scraper.taxonomies.normalizer import (
    normalize_percentage_dict_asset_class,
    normalize_percentage_dict_region,
)

log = structlog.get_logger()

CLASSIFIER_MODEL = "claude-sonnet-4-6"


class ClassifierParseError(ValueError):
    """Raised when classifier output can't be parsed as valid ClassificationResult."""


def _strip_fences(text: str) -> str:
    """Remove ```json...``` fences if present."""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()


def _build_user_message(nombre: str, context: dict[str, Any]) -> str:
    parts = [f'Producto: "{nombre}"']
    for key in ("administrador", "gestor", "moneda", "liquidez"):
        if context.get(key):
            parts.append(f"{key.capitalize()}: {context[key]}")
    if "extra" in context and context["extra"]:
        parts.append(f"Información adicional: {context['extra']}")
    return "\n".join(parts)


def _normalize_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize non-canonical values in output."""
    attrs = payload.get("attributes", {})

    # Normalize clase_activo dict keys
    clase = attrs.get("clase_activo", {}).get("value")
    if isinstance(clase, dict):
        attrs["clase_activo"]["value"] = normalize_percentage_dict_asset_class(clase)

    # Normalize foco_geografico dict keys
    foco = attrs.get("foco_geografico", {}).get("value")
    if isinstance(foco, dict):
        attrs["foco_geografico"]["value"] = normalize_percentage_dict_region(foco)

    return payload


async def classify(
    *,
    llm: LLMClient,
    producto_nombre: str,
    product_context: dict[str, Any],
    rules_md: str,
    few_shot_examples: list[dict[str, Any]],
) -> ClassificationResult:
    """Classify a single product using Claude Sonnet 4.6."""
    system_blocks = build_classifier_system_blocks(rules_md, few_shot_examples)
    user_message = _build_user_message(producto_nombre, product_context)

    result = await llm.call(
        model=CLASSIFIER_MODEL,
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=4096,
        temperature=0.0,
    )

    clean = _strip_fences(result.response_text)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as e:
        raise ClassifierParseError(
            f"Model output is not valid JSON: {e}\nOutput: {clean[:500]}"
        ) from e

    payload = _normalize_output(payload)

    try:
        return ClassificationResult.from_json(payload)
    except (KeyError, ValueError, TypeError) as e:
        raise ClassifierParseError(f"JSON doesn't match ClassificationResult schema: {e}") from e
```

- [ ] **Step 4: Tests pass**

```bash
poetry run pytest tests/integration/test_classifier_mocked.py -v
```

Esperado: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
poetry run ruff check src/scraper/agents/classifier.py tests/integration/
git add src/scraper/agents/classifier.py tests/integration/
git commit -m "feat: add classifier agent (Claude Sonnet 4.6) with vocab normalization"
```

---

## Task 8: Reviewer agent (Claude Opus 4.7)

Similar al clasificador pero con prompt de crítica + modelo Opus.

**Files:**
- Modify: `src/scraper/agents/prompts/reviewer_system.md` (completar)
- Create: `src/scraper/agents/reviewer.py`
- Create: `tests/integration/test_reviewer_mocked.py`

- [ ] **Step 1: Completar reviewer_system.md**

Reemplazar el stub en `src/scraper/agents/prompts/reviewer_system.md` con:

```markdown
Eres el Revisor Crítico del Clasificador de Productos de Inversión de Sabbi. Tu job NO es re-clasificar — es auditar la clasificación que hizo otro agente (Claude Sonnet) y marcar inconsistencias o errores.

## REGLAS DE CLASIFICACIÓN (v1)

{{RULES_MD}}

## TAXONOMÍAS CANÓNICAS (lista cerrada)

### Clases macro
{{ASSET_CLASSES}}

### Subyacentes ({{N_CANONICAL_ASSETS}})
{{CANONICAL_ASSETS}}

### Regiones
{{REGIONS}}

## Tu proceso de revisión

Recibirás en el mensaje user:
1. El input original (nombre del producto + contexto)
2. El output del Clasificador (JSON con su clasificación)

Verifica, atributo por atributo:

1. **Vocabulario canónico:** ¿todos los valores (keys de dicts, strings de categorías) vienen de las listas canónicas arriba? Si no, mark disagree y suggested_value con la versión canónica.

2. **Porcentajes suman 100%:** en `foco_geografico`, `clase_activo`, `subyacente` — cada dict debe sumar 100% ± 2pp.

3. **Consistencia subyacente ↔ clase_activo:** si un subyacente pertenece a macro X, la macro X debe estar en `clase_activo` con peso ≥ el del subyacente.

4. **Reasoning consistente con reglas:** la `rule_applied` citada debe existir en las reglas Y aplicar al caso.

5. **Confidence honesta:** si el reasoning es débil ("asumí que..."), confidence no debería ser >0.85.

## Output — formato obligatorio

Responde EXACTAMENTE con este JSON:

```json
{
  "veredicto": "agree|disagree|partial",
  "attribute_reviews": {
    "foco_geografico": {"verdict": "agree", "reason": "", "suggested_value": null},
    "clase_activo": {"verdict": "disagree", "reason": "El clasificador dijo Club deal (variante) en vez de Club deals canónico", "suggested_value": {"Club deals": 100.0}},
    "subyacente": {"verdict": "agree", "reason": "", "suggested_value": null},
    "comision": {"verdict": "agree", "reason": "", "suggested_value": null},
    "moneda": {"verdict": "agree", "reason": "", "suggested_value": null},
    "administrador": {"verdict": "agree", "reason": "", "suggested_value": null},
    "gestor": {"verdict": "agree", "reason": "", "suggested_value": null},
    "liquidez": {"verdict": "agree", "reason": "", "suggested_value": null},
    "minimo_inversion": {"verdict": "agree", "reason": "", "suggested_value": null}
  },
  "global_verdict": "auto_approvable|needs_review|low_quality",
  "reviewer_confidence": 0.92
}
```

Reglas:
- `veredicto` = "agree" si TODOS los attribute_reviews son agree, "disagree" si alguno es disagree, "partial" si hay mix.
- `global_verdict`:
  - `low_quality` si la clasificación es tan mala que recomiendas re-hacerla con más info (ej. muchos "no encontrado" o valores inventados)
  - `needs_review` si hay disagreements pero la clasificación es recuperable con edición humana
  - `auto_approvable` si todos los atributos están bien
- Responde SOLO el JSON. Sin markdown fences.
```

- [ ] **Step 2: Tests**

`tests/integration/test_reviewer_mocked.py`:

```python
import json


async def test_reviewer_agrees(mock_llm_client):
    from scraper.agents.reviewer import review
    from scraper.agents.types import AttributeClassification, ClassificationResult

    output = json.dumps({
        "veredicto": "agree",
        "attribute_reviews": {
            "foco_geografico": {"verdict": "agree", "reason": "", "suggested_value": None},
        },
        "global_verdict": "auto_approvable",
        "reviewer_confidence": 0.95,
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(
        output, model="claude-opus-4-7"
    )

    classifier_output = ClassificationResult(
        producto="X",
        attributes={
            "foco_geografico": AttributeClassification(
                value={"Perú": 100.0}, confidence=0.95, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.95,
        unknowns=[],
    )
    result = await review(
        llm=mock_llm_client,
        producto_nombre="X",
        product_context={},
        classifier_output=classifier_output,
        rules_md="#",
    )
    assert result.global_verdict == "auto_approvable"
    assert result.has_disagreement() is False


async def test_reviewer_disagrees(mock_llm_client):
    from scraper.agents.reviewer import review
    from scraper.agents.types import AttributeClassification, ClassificationResult

    output = json.dumps({
        "veredicto": "disagree",
        "attribute_reviews": {
            "clase_activo": {
                "verdict": "disagree",
                "reason": "debería ser Club deals, no Mercados Privados",
                "suggested_value": {"Club deals": 100.0},
            },
        },
        "global_verdict": "needs_review",
        "reviewer_confidence": 0.88,
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(
        output, model="claude-opus-4-7"
    )

    classifier_output = ClassificationResult(
        producto="X",
        attributes={
            "clase_activo": AttributeClassification(
                value={"Mercados Privados": 100.0}, confidence=0.88, reasoning="", rule_applied=""
            ),
        },
        global_confidence=0.88,
        unknowns=[],
    )
    result = await review(
        llm=mock_llm_client,
        producto_nombre="X",
        product_context={},
        classifier_output=classifier_output,
        rules_md="#",
    )
    assert result.has_disagreement() is True
    assert result.global_verdict == "needs_review"
```

- [ ] **Step 3: Run — fail**

```bash
poetry run pytest tests/integration/test_reviewer_mocked.py -v
```

- [ ] **Step 4: Implement reviewer**

`src/scraper/agents/reviewer.py`:

```python
"""Reviewer agent — uses Claude Opus 4.7 to critique classifier output."""
from __future__ import annotations

import json
from typing import Any

import structlog

from scraper.agents.classifier import ClassifierParseError, _strip_fences
from scraper.agents.prompts.builder import build_reviewer_system_blocks
from scraper.agents.types import ClassificationResult, ReviewResult
from scraper.llm import LLMClient

log = structlog.get_logger()

REVIEWER_MODEL = "claude-opus-4-7"


async def review(
    *,
    llm: LLMClient,
    producto_nombre: str,
    product_context: dict[str, Any],
    classifier_output: ClassificationResult,
    rules_md: str,
) -> ReviewResult:
    """Critique a classifier output using Claude Opus 4.7."""
    system_blocks = build_reviewer_system_blocks(rules_md)

    user_parts = [
        f"# Input original",
        f'Producto: "{producto_nombre}"',
    ]
    for key in ("administrador", "gestor", "moneda", "liquidez"):
        if product_context.get(key):
            user_parts.append(f"{key.capitalize()}: {product_context[key]}")

    user_parts.append("\n# Clasificación a revisar")
    user_parts.append(f"```json\n{classifier_output.to_json()}\n```")
    user_parts.append("\nRevisa la clasificación y responde con el JSON de veredicto.")

    user_message = "\n".join(user_parts)

    result = await llm.call(
        model=REVIEWER_MODEL,
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=2048,
        temperature=0.0,
    )

    clean = _strip_fences(result.response_text)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as e:
        raise ClassifierParseError(
            f"Reviewer output is not valid JSON: {e}\nOutput: {clean[:500]}"
        ) from e

    return ReviewResult.from_json(payload)
```

- [ ] **Step 5: Tests pass**

```bash
poetry run pytest tests/integration/test_reviewer_mocked.py -v
```

Esperado: 2 passed.

- [ ] **Step 6: Lint + commit**

```bash
poetry run ruff check src/scraper/agents/reviewer.py tests/integration/test_reviewer_mocked.py src/scraper/agents/prompts/reviewer_system.md
git add src/scraper/agents/reviewer.py src/scraper/agents/prompts/reviewer_system.md tests/integration/test_reviewer_mocked.py
git commit -m "feat: add reviewer agent (Claude Opus 4.7) with criticism prompt"
```

---

## Task 9: Accuracy metric calculator

Compara una clasificación (output del agente) contra un Product ground truth, produce accuracy per-attribute.

**Files:**
- Create: `src/scraper/metrics/__init__.py`
- Create: `src/scraper/metrics/accuracy.py`
- Create: `tests/unit/test_accuracy.py`

- [ ] **Step 1: Tests**

`tests/unit/test_accuracy.py`:

```python
import pytest


def test_accuracy_categorical_exact_match():
    from scraper.metrics.accuracy import categorical_match

    assert categorical_match("soles", "soles") is True
    assert categorical_match("SOLES", "soles") is True  # case insensitive
    assert categorical_match("soles ", "soles") is True  # strip
    assert categorical_match("dolares", "soles") is False
    assert categorical_match(None, None) is True
    assert categorical_match(None, "soles") is False


def test_accuracy_percentage_dict_exact():
    from scraper.metrics.accuracy import percentage_dict_match

    # Exact match passes
    assert percentage_dict_match({"Perú": 100.0}, {"Perú": 100.0}, tolerance_pp=5.0) is True


def test_accuracy_percentage_dict_within_tolerance():
    from scraper.metrics.accuracy import percentage_dict_match

    expected = {"Perú": 65.0, "USA": 35.0}
    actual = {"Perú": 63.0, "USA": 37.0}  # ±2pp each — within tolerance
    assert percentage_dict_match(expected, actual, tolerance_pp=5.0) is True


def test_accuracy_percentage_dict_outside_tolerance():
    from scraper.metrics.accuracy import percentage_dict_match

    expected = {"Perú": 65.0, "USA": 35.0}
    actual = {"Perú": 50.0, "USA": 50.0}  # 15pp off — out of tolerance
    assert percentage_dict_match(expected, actual, tolerance_pp=5.0) is False


def test_accuracy_percentage_dict_missing_key():
    from scraper.metrics.accuracy import percentage_dict_match

    expected = {"Perú": 50.0, "USA": 50.0}
    actual = {"Perú": 50.0}  # missing USA entirely
    assert percentage_dict_match(expected, actual, tolerance_pp=5.0) is False


def test_accuracy_numeric_relative_within_5pct():
    from scraper.metrics.accuracy import numeric_match

    assert numeric_match(0.0325, 0.033, rel_tolerance=0.05) is True
    assert numeric_match(0.0325, 0.04, rel_tolerance=0.05) is False
    assert numeric_match(None, None, rel_tolerance=0.05) is True
    assert numeric_match(0.0325, None, rel_tolerance=0.05) is False


def test_compute_product_accuracy_all_correct():
    from scraper.agents.types import AttributeClassification, ClassificationResult
    from scraper.metrics.accuracy import compute_product_accuracy

    ground_truth = {
        "foco_geografico": {"Perú": 100.0},
        "clase_activo": {"Mercados Públicos - Variable": 100.0},
        "subyacentes": {"Acciones Peru": 100.0},
        "comision": 0.0325,
        "moneda": "soles",
    }
    predicted = ClassificationResult(
        producto="X",
        attributes={
            "foco_geografico": AttributeClassification(value={"Perú": 100.0}, confidence=1.0, reasoning="", rule_applied=""),
            "clase_activo": AttributeClassification(value={"Mercados Públicos - Variable": 100.0}, confidence=1.0, reasoning="", rule_applied=""),
            "subyacente": AttributeClassification(value={"Acciones Peru": 100.0}, confidence=1.0, reasoning="", rule_applied=""),
            "comision": AttributeClassification(value=0.0325, confidence=1.0, reasoning="", rule_applied=""),
            "moneda": AttributeClassification(value="soles", confidence=1.0, reasoning="", rule_applied=""),
        },
        global_confidence=1.0,
        unknowns=[],
    )
    report = compute_product_accuracy(ground_truth, predicted)
    assert report["foco_geografico"] is True
    assert report["clase_activo"] is True
    assert report["subyacente"] is True
    assert report["comision"] is True
    assert report["moneda"] is True
```

- [ ] **Step 2: Fail**

```bash
poetry run pytest tests/unit/test_accuracy.py -v
```

- [ ] **Step 3: Implement**

`src/scraper/metrics/__init__.py`:

```python
from scraper.metrics.accuracy import (
    aggregate_accuracy,
    categorical_match,
    compute_product_accuracy,
    numeric_match,
    percentage_dict_match,
)

__all__ = [
    "aggregate_accuracy",
    "categorical_match",
    "compute_product_accuracy",
    "numeric_match",
    "percentage_dict_match",
]
```

`src/scraper/metrics/accuracy.py`:

```python
"""Accuracy metrics for classifier validation.

Per-attribute rules from spec:
- Categorical (moneda, liquidez, administrador, gestor, minimo_inversion): exact match (case/strip insensitive)
- Percentage dicts (foco, clase, subyacente): each key must exist in both with ±5pp per region
- Numeric (comision): ±5% relative tolerance
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from scraper.agents.types import ClassificationResult


def categorical_match(expected: Any, actual: Any) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    return str(expected).strip().lower() == str(actual).strip().lower()


def percentage_dict_match(
    expected: dict[str, float] | None,
    actual: dict[str, float] | None,
    tolerance_pp: float = 5.0,
) -> bool:
    expected = expected or {}
    actual = actual or {}
    # Same set of keys (exact match — case sensitive because they're canonical)
    if set(expected.keys()) != set(actual.keys()):
        return False
    for k, exp_v in expected.items():
        act_v = actual[k]
        if abs(exp_v - act_v) > tolerance_pp:
            return False
    return True


def numeric_match(expected: float | None, actual: float | None, rel_tolerance: float = 0.05) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if expected == 0:
        return abs(actual) < rel_tolerance
    return abs(expected - actual) / abs(expected) <= rel_tolerance


_ATTR_MAPPING = {
    "foco_geografico": ("percentage_dict", "foco_geografico"),
    "clase_activo": ("percentage_dict", "clase_activo"),
    "subyacente": ("percentage_dict", "subyacentes"),  # expected key differs
    "comision": ("numeric", "comision"),
    "moneda": ("categorical", "moneda"),
    "administrador": ("categorical", "administrador"),
    "gestor": ("categorical", "gestor"),
    "liquidez": ("categorical", "liquidez"),
    "minimo_inversion": ("categorical", "minimo_inversion"),
}


def compute_product_accuracy(
    ground_truth: dict[str, Any],
    predicted: ClassificationResult,
) -> dict[str, bool]:
    """Compare predicted classification against ground truth Product row dict.

    Returns dict of attribute → correct (bool).
    """
    report: dict[str, bool] = {}
    for attr, (kind, gt_key) in _ATTR_MAPPING.items():
        gt_value = ground_truth.get(gt_key)
        predicted_attr = predicted.attributes.get(attr)
        pred_value = predicted_attr.value if predicted_attr else None

        if kind == "percentage_dict":
            report[attr] = percentage_dict_match(gt_value, pred_value)
        elif kind == "numeric":
            report[attr] = numeric_match(gt_value, pred_value)
        else:
            report[attr] = categorical_match(gt_value, pred_value)
    return report


def aggregate_accuracy(per_product_reports: Iterable[dict[str, bool]]) -> dict[str, float]:
    """Average accuracy per attribute across N products.

    Returns dict of attribute → fraction correct (0.0 to 1.0).
    """
    reports = list(per_product_reports)
    if not reports:
        return {}
    attrs = reports[0].keys()
    out: dict[str, float] = {}
    for a in attrs:
        correct = sum(1 for r in reports if r.get(a) is True)
        out[a] = correct / len(reports)
    return out
```

- [ ] **Step 4: Tests pass**

```bash
poetry run pytest tests/unit/test_accuracy.py -v
```

Esperado: 7 passed.

- [ ] **Step 5: Commit**

```bash
poetry run ruff check src/scraper/metrics/ tests/unit/test_accuracy.py
git add src/scraper/metrics/ tests/unit/test_accuracy.py
git commit -m "feat: add accuracy metrics per attribute (categorical/percentage/numeric)"
```

---

## Task 10: CLI `classify_one` — clasifica un producto real

Endpoint manual para probar el agente con un producto específico (no contra validation_set todavía — eso es Task 11).

**Files:**
- Create: `src/scraper/scripts/classify_one.py`
- Create: `tests/integration/test_classify_one_smoke.py`

- [ ] **Step 1: Implement classify_one**

`src/scraper/scripts/classify_one.py`:

```python
"""CLI: classify a single product by name.

Usage:
    poetry run python -m scraper.scripts.classify_one "Credicorp Crecimiento"
    poetry run python -m scraper.scripts.classify_one --no-api "Credicorp Crecimiento"  # dry-run, imprime prompt

Needs ANTHROPIC_API_KEY in .env.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import structlog
from sqlalchemy import select

from scraper.agents.classifier import classify
from scraper.agents.prompts.builder import build_few_shot_from_db, load_rules_md
from scraper.agents.reviewer import review
from scraper.agents.orchestrator import decide_flag
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
        print("--- System prompt (dry run, NO LLM CALL) ---")
        print(prompt[:2000], "...[TRUNCATED]" if len(prompt) > 2000 else "")
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
    print(_json.dumps(
        {
            "veredicto": rev_result.veredicto,
            "global_verdict": rev_result.global_verdict,
            "attribute_reviews": {k: {"verdict": v.verdict, "reason": v.reason} for k, v in rev_result.attribute_reviews.items()},
            "reviewer_confidence": rev_result.reviewer_confidence,
        },
        ensure_ascii=False,
        indent=2,
    ))
    print(f"\n=== FLAG: {flag} ===")
    print(f"Costo total: ${llm.cost.total_usd:.4f}")
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("producto", help="Nombre del producto a clasificar")
    parser.add_argument("--no-api", action="store_true", help="No llamar a LLM, solo imprime el prompt")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.producto, no_api=args.no_api)))


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Smoke test (no API)**

`tests/integration/test_classify_one_smoke.py`:

```python
import subprocess
import sys


def test_classify_one_dry_run_works():
    """--no-api mode should print prompt preview without calling LLM."""
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.classify_one", "--no-api", "Credicorp Crecimiento"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "System prompt" in result.stdout
    assert "Mercados Públicos" in result.stdout  # taxonomías presentes
```

- [ ] **Step 3: Run smoke test**

```bash
poetry run pytest tests/integration/test_classify_one_smoke.py -v
```

Esperado: 1 passed.

- [ ] **Step 4: Manual real-API run (requires ANTHROPIC_API_KEY)**

```bash
poetry run python -m scraper.scripts.classify_one "Credicorp Crecimiento"
```

Expected output: JSON clasificación + revisión + flag + costo (~$0.01-0.05 por producto).

**Nota:** si no tienes API key configurada, este paso salta el output real — solo verifica que `--no-api` funciona.

- [ ] **Step 5: Commit**

```bash
poetry run ruff check src/scraper/scripts/classify_one.py tests/integration/test_classify_one_smoke.py
git add src/scraper/scripts/classify_one.py tests/integration/test_classify_one_smoke.py
git commit -m "feat: add classify_one CLI (classifies single product end-to-end)"
```

---

## Task 11: CLI `calibrate` — corre validation_set, reporta accuracy

El task que **entrega el score**. Corre el clasificador+revisor sobre los 19 productos de validation_set, calcula accuracy por atributo, y guarda el reporte en `rules_versions.validation_accuracy`.

**Files:**
- Create: `src/scraper/scripts/calibrate.py`
- Create: `tests/integration/test_calibrate_smoke.py`

- [ ] **Step 1: Implement calibrate**

`src/scraper/scripts/calibrate.py`:

```python
"""CLI: run classifier over validation_set, compute accuracy, save report.

Usage:
    poetry run python -m scraper.scripts.calibrate                      # use rules/v1.md
    poetry run python -m scraper.scripts.calibrate --rules rules/v2.md  # specify version
    poetry run python -m scraper.scripts.calibrate --dry-run            # no LLM calls (uses dummy 100% for ground truth test)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog
from sqlalchemy import select

from scraper.agents.classifier import ClassifierParseError, classify
from scraper.agents.prompts.builder import build_few_shot_from_db
from scraper.agents.reviewer import review
from scraper.agents.orchestrator import decide_flag
from scraper.config import get_settings
from scraper.db.models import Product, RulesVersion, ValidationSet
from scraper.db.session import get_session
from scraper.llm import LLMClient
from scraper.logging_config import configure_logging
from scraper.metrics import aggregate_accuracy, compute_product_accuracy

log = structlog.get_logger()


def _product_to_ground_truth(p: Product) -> dict:
    return {
        "foco_geografico": p.foco_geografico,
        "clase_activo": p.clase_activo,
        "subyacentes": p.subyacentes,
        "comision": p.comision,
        "moneda": p.moneda,
        "administrador": p.administrador,
        "gestor": p.gestor,
        "liquidez": p.liquidez,
        "minimo_inversion": p.minimo_inversion,
    }


async def _main(rules_path: Path, dry_run: bool = False) -> int:
    configure_logging(level="INFO", json_logs=False)

    rules_md = rules_path.read_text(encoding="utf-8")
    version = rules_path.stem  # e.g., "v1"

    settings = get_settings()
    if not dry_run and not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY no configurada. Use --dry-run para smoke test.", file=sys.stderr)
        return 2

    async with get_session() as s:
        # Fetch validation products
        r = await s.execute(
            select(Product).join(ValidationSet, Product.id == ValidationSet.product_id)
        )
        validation = list(r.scalars().all())
        few_shot = await build_few_shot_from_db(s, limit=None)

    print(f"\n=== Calibración {version} — {len(validation)} productos ===\n")

    llm = None if dry_run else LLMClient()
    reports: list[dict[str, bool]] = []
    per_product_details: list[dict] = []

    for i, p in enumerate(validation, 1):
        context = {
            "administrador": p.administrador,
            "gestor": p.gestor,
            "moneda": p.moneda,
            "liquidez": p.liquidez,
        }
        ground_truth = _product_to_ground_truth(p)

        if dry_run:
            # Produce a fake "all correct" result to test the pipeline end-to-end
            from scraper.agents.types import AttributeClassification, ClassificationResult
            fake = ClassificationResult(
                producto=p.nombre,
                attributes={
                    attr: AttributeClassification(value=val, confidence=1.0, reasoning="dry-run", rule_applied="dry-run")
                    for attr, val in [
                        ("foco_geografico", p.foco_geografico),
                        ("clase_activo", p.clase_activo),
                        ("subyacente", p.subyacentes),
                        ("comision", p.comision),
                        ("moneda", p.moneda),
                        ("administrador", p.administrador),
                        ("gestor", p.gestor),
                        ("liquidez", p.liquidez),
                        ("minimo_inversion", p.minimo_inversion),
                    ]
                },
                global_confidence=1.0,
                unknowns=[],
            )
            report = compute_product_accuracy(ground_truth, fake)
            reports.append(report)
            print(f"[{i:2d}/{len(validation)}] {p.nombre[:50]:50s} DRY-RUN {report}")
            continue

        try:
            cls_result = await classify(
                llm=llm,
                producto_nombre=p.nombre,
                product_context=context,
                rules_md=rules_md,
                few_shot_examples=few_shot,
            )
            rev_result = await review(
                llm=llm,
                producto_nombre=p.nombre,
                product_context=context,
                classifier_output=cls_result,
                rules_md=rules_md,
            )
            flag = decide_flag(cls_result, rev_result)
            report = compute_product_accuracy(ground_truth, cls_result)
            reports.append(report)

            correct_count = sum(1 for v in report.values() if v)
            total_attrs = len(report)
            print(
                f"[{i:2d}/{len(validation)}] {p.nombre[:50]:50s} "
                f"{correct_count}/{total_attrs} atr · flag={flag} · conf={cls_result.global_confidence:.2f}"
            )
            per_product_details.append({
                "nombre": p.nombre,
                "accuracy": report,
                "global_confidence": cls_result.global_confidence,
                "flag": flag,
                "reviewer_verdict": rev_result.global_verdict,
            })
        except ClassifierParseError as e:
            log.warning("classifier_parse_error", producto=p.nombre, error=str(e))
            reports.append({attr: False for attr in [
                "foco_geografico", "clase_activo", "subyacente", "comision",
                "moneda", "administrador", "gestor", "liquidez", "minimo_inversion",
            ]})

    # Aggregate accuracy
    accuracy = aggregate_accuracy(reports)
    print(f"\n=== Resultado ({version}) ===")
    print(f"Productos evaluados: {len(reports)}")
    for attr, acc in sorted(accuracy.items()):
        bar = "█" * int(acc * 20) + "░" * (20 - int(acc * 20))
        flag = "✓" if acc >= 0.85 else "✗"
        print(f"  {flag} {attr:20s} [{bar}] {acc:.1%}")
    if llm:
        print(f"\nCosto total: ${llm.cost.total_usd:.3f}")

    # Save to DB
    async with get_session() as s:
        r = await s.execute(select(RulesVersion).where(RulesVersion.version == version))
        rv = r.scalar_one_or_none()
        if rv is None:
            rv = RulesVersion(
                version=version,
                content_md=rules_md,
                notes=f"Calibración automática {'(dry-run)' if dry_run else ''}",
            )
            s.add(rv)
        rv.validation_accuracy = {
            "per_attribute": accuracy,
            "n_products": len(reports),
            "dry_run": dry_run,
            "details": per_product_details[:5],  # save first 5 for inspection, not all
        }
        await s.commit()
        print(f"\nGuardado en rules_versions.{version}.validation_accuracy")

    min_attr_accuracy = min(accuracy.values()) if accuracy else 0.0
    return 0 if min_attr_accuracy >= 0.85 else 1  # exit 1 if any attr below threshold


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", default="rules/v1.md", help="Path to rules markdown")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls (pipeline smoke test)")
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(Path(args.rules), dry_run=args.dry_run)))


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Smoke test**

`tests/integration/test_calibrate_smoke.py`:

```python
import subprocess
import sys


def test_calibrate_dry_run_completes():
    """Dry-run mode should execute pipeline without API, producing 100% accuracy
    (because dry-run feeds ground truth as prediction)."""
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.calibrate", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Calibración v1" in result.stdout
    assert "100.0%" in result.stdout  # all attrs 100% in dry-run
```

- [ ] **Step 3: Run smoke test**

```bash
poetry run pytest tests/integration/test_calibrate_smoke.py -v
```

Esperado: 1 passed.

- [ ] **Step 4: Manual real-API calibration run**

Este es el MOMENTO que genera el score real.

```bash
poetry run python -m scraper.scripts.calibrate
```

Esto corre el clasificador+revisor sobre los 19 de validation. Toma ~3-5 min. Costo estimado: ~$0.50-2.00.

Output esperado:
```
=== Calibración v1 — 19 productos ===

[ 1/19] Finsmart Factoring                              7/9 atr · flag=needs_review · conf=0.85
[ 2/19] BCP Ahorro soles                                9/9 atr · flag=auto_approvable · conf=0.98
...

=== Resultado (v1) ===
Productos evaluados: 19
  ✓ administrador        [████████████████████] 100.0%
  ✓ gestor               [████████████████████] 100.0%
  ✓ moneda               [████████████████████] 100.0%
  ✓ liquidez             [██████████████████░░]  90.0%
  ✗ foco_geografico      [████████████░░░░░░░░]  63.0%
  ✗ clase_activo         [███████████░░░░░░░░░]  58.0%
  ✗ subyacente           [████░░░░░░░░░░░░░░░░]  25.0%
  ✗ comision             [██████████████░░░░░░]  73.0%
  ✗ minimo_inversion     [██████░░░░░░░░░░░░░░]  30.0%

Costo total: $1.234

Guardado en rules_versions.v1.validation_accuracy
```

El goal es tener TODOS los atributos con ✓ (≥85%). Si algunos están ✗, hay que iterar: editar `rules/v2.md` con reglas más específicas + re-correr.

**Esto es normal.** La primera ronda casi nunca llega a 85% porque las reglas v1 son un primer borrador. La iteración es parte del proceso.

- [ ] **Step 5: Commit CLI**

```bash
poetry run ruff check src/scraper/scripts/calibrate.py tests/integration/test_calibrate_smoke.py
git add src/scraper/scripts/calibrate.py tests/integration/test_calibrate_smoke.py
git commit -m "feat: add calibrate CLI — runs validation_set and reports per-attr accuracy"
```

---

## Task 12: Iterate rules v1 → vN based on first calibration

**Este task es colaborativo humano-agente.**

Cuando se corra `calibrate` por primera vez con rules v1, los atributos con <85% accuracy necesitan reglas más específicas. Esta iteración es creativa — el agente puede proponer cambios, pero **Sabbi valida**.

**Files:**
- Create: `rules/v2.md`, `rules/v3.md`, ... (según iteraciones)

- [ ] **Step 1: Analizar los fallos de v1**

Del output de calibrate, identificar:
- Qué atributos están debajo del 85%
- Qué productos específicos fallaron para cada atributo
- Patrones en los fallos (ej. "todos los subyacentes de ETFs internacionales fallan")

- [ ] **Step 2: Redactar rules/v2.md**

Copiar `rules/v1.md` a `rules/v2.md`. Agregar reglas más específicas para los atributos que fallaron. Ejemplos de mejoras típicas:

- Si `subyacente` falla mucho: agregar tabla explícita de mapeo ticker→canónico (VTI→US Large Cap, BND→Bonos Corporativos IG, etc.).
- Si `clase_activo` falla: agregar ejemplos concretos de la distinción Club deal vs Mercados Privados con cotizaciones de fichas reales.
- Si `foco_geografico` falla: agregar lista de heurísticas (ej. "si administrador es Sabadell → 100% USA por default").
- Si `comision` falla: clarificar el formato numérico (decimal vs porcentaje vs texto para clases múltiples).

**Importante:** cada regla que agregas debería estar justificada por un fallo específico en validation. No agregar reglas por "por si acaso".

- [ ] **Step 3: Re-calibrar con v2**

```bash
poetry run python -m scraper.scripts.calibrate --rules rules/v2.md
```

Comparar accuracy vs v1. Si algún atributo bajó → la regla nueva introdujo ambigüedad. Revertir o ajustar.

- [ ] **Step 4: Iterar hasta converger**

Repetir v3, v4, ... hasta que TODOS los atributos estén ≥85%. En la práctica, 3-5 iteraciones suelen bastar.

- [ ] **Step 5: Commit versiones cuando convergen**

```bash
git add rules/v2.md
git commit -m "rules: v2 — improved subyacente mapping with ETF ticker table (accuracy 78%→89%)"
```

Un commit por versión, con el mensaje incluyendo el cambio de accuracy.

**Esta task NO tiene un "done" fijo** — termina cuando todos los atributos pasan 85%. Si después de 5 iteraciones sigue algún atributo debajo, reportar como DONE_WITH_CONCERNS y discutir con Sabbi si las reglas capturan su lógica real o si la data tiene problemas.

---

## Task 13: Cerrar Phase 2a (docs + tag)

**Files:**
- Modify: `README.md`
- Create: `docs/superpowers/plans/phase2a-STATUS.md`

- [ ] **Step 1: Update README**

Marcar Phase 2a como completa en el checklist:

```markdown
- [x] Phase 1: Foundation (DB + seed desde Excel + split 80/20)
- [x] Phase 2a: Agentes + Calibración (Clasificador + Revisor + rules vN con ≥85% accuracy)
- [ ] Phase 2b: Extractor (HTML + PDF)
- [ ] Phase 3: Orchestrator + FastAPI
- [ ] Phase 4: Search cascade
- [ ] Phase 5: Streamlit UI
- [ ] Phase 6: Robustez + deploy
```

Agregar comandos nuevos:

```bash
# Calibrar agente contra validation_set
poetry run python -m scraper.scripts.calibrate

# Clasificar un producto específico
poetry run python -m scraper.scripts.classify_one "Credicorp Crecimiento"
```

- [ ] **Step 2: Crear phase2a-STATUS.md**

```markdown
# Phase 2a — Status

**Completed:** <fecha>
**Rules version final:** vN (con score final)
**Accuracy por atributo (vN vs validation_set):**
- foco_geografico: XX.X%
- clase_activo: XX.X%
- subyacente: XX.X%
- comision: XX.X%
- moneda: XX.X%
- administrador: XX.X%
- gestor: XX.X%
- liquidez: XX.X%
- minimo_inversion: XX.X%

**Costo de calibración:** ~$X.XX USD (N iteraciones de rules)

## Hallazgos de calibración

- [Qué atributos fueron más difíciles]
- [Qué tipo de productos fallaron más]
- [Reglas específicas que movieron la aguja]

## Queda para Phase 2b

- Extractor HTML (BeautifulSoup + Claude)
- Extractor PDF texto (pypdf + Claude)
- Extractor PDF vision (Claude vision para escaneados)
- CLI `extract_one` que toma URL/PDF y devuelve ficha estructurada

Con Phase 2a + 2b funcionando, Phase 3 es integrar ambos vía FastAPI.
```

Llenar los XX con números reales de la última calibración.

- [ ] **Step 3: Final full test run**

```bash
poetry run pytest -v 2>&1 | tail -10
```

Todos pasan. Contar aproximado: ~50-55 tests.

- [ ] **Step 4: Commit + tag**

```bash
git add README.md docs/superpowers/plans/phase2a-STATUS.md
git commit -m "docs: close Phase 2a — agents + calibration complete (vN rules, YY% min accuracy)"
git tag phase2a-complete
git log --oneline | head -20
```

---

## Criterios de éxito Phase 2a

- [ ] `rules/v1.md` (o vN final) redactado con filosofía de Sabbi codificada
- [ ] `poetry run python -m scraper.scripts.classify_one "X"` funciona end-to-end
- [ ] `poetry run python -m scraper.scripts.calibrate` corre los 19 validation, reporta accuracy per-attribute
- [ ] Todos los 9 atributos ≥85% accuracy en validation_set (o, si no, documentado por qué no)
- [ ] Taxonomy normalizer maneja las ~14 variantes documentadas
- [ ] Cost tracking funciona — cada run imprime total en USD
- [ ] Prompt caching aplicado — segunda clasificación consecutiva más barata que primera
- [ ] ~50+ tests passing (unit + integration)
- [ ] Orchestrator decide_flag con prioridad correcta: low_quality > needs_review > auto_approvable
- [ ] Mocked integration tests cubren classifier, reviewer, sin pegar a LLM real
- [ ] Commit por task, tag `phase2a-complete`

---

## Execution handoff

Dos opciones:

**1. Subagent-Driven (recomendado)** — un subagente fresh por cada task (Tasks 1-11 son bien automatizables), reviews entre tasks.

**2. Inline Execution** — tú y yo en la misma sesión con checkpoints.

**Nota especial sobre Task 12 (iterar reglas):** este es un loop colaborativo donde **Sabbi tiene que revisar las reglas**. No es mecanizable al 100%. Recomiendo: tasks 1-11 via subagent, y Task 12 juntos (yo sugiero cambios, tú validas que reflejan tu lógica real).
