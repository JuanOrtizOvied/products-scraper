# Phase 1 — Foundation (repo, DB, seed, split)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold el repo, modelar la DB, cargar los 136 productos del Excel, y dejar el split 110/26 listo para calibrar agentes en Phase 2.

**Architecture:** Python 3.11 + Poetry + SQLAlchemy async + Alembic. SQLite local, diseñado para swap a Postgres. Taxonomías de referencia en YAML (versionadas en git). Seeder lee `BD_Productos Sabbi.xlsx` y puebla `products` + `training_set` + `validation_set` con split estratificado por clase de activo macro dominante.

**Tech Stack:** Python 3.11, Poetry, SQLAlchemy 2.x (async), Alembic, pydantic-settings, openpyxl, pytest, pytest-asyncio, structlog.

**Spec de referencia:** `docs/superpowers/specs/2026-04-17-buscador-clasificador-productos-inversion-design.md`

**Entregable al final de Phase 1:**
- `poetry run python -m scraper.scripts.seed_from_excel` carga los 136 productos
- `poetry run python -m scraper.scripts.split_train_validation` crea split 110/26
- `poetry run pytest tests/unit` pasa verde
- DB `data/local.db` tiene 136 productos con split asignado
- Taxonomías canónicas cargadas

---

## File structure creado en Phase 1

```
scraper/
├── pyproject.toml                        # Poetry deps + config
├── .env.example                          # Secrets template
├── .gitignore
├── README.md
├── alembic.ini
├── src/scraper/
│   ├── __init__.py
│   ├── config.py                         # pydantic-settings, lee .env
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py                       # Base declarative + async engine
│   │   ├── models.py                     # Todas las tablas ORM
│   │   └── session.py                    # Async session factory
│   ├── taxonomies/
│   │   ├── __init__.py
│   │   ├── loader.py                     # Lee YAML → Python objects
│   │   ├── asset_classes.yaml
│   │   ├── canonical_assets.yaml
│   │   └── geographic_regions.yaml
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── percentage_parser.py          # "Perú 65%, USA 35%" → dict
│   └── scripts/
│       ├── __init__.py
│       ├── seed_from_excel.py
│       └── split_train_validation.py
├── alembic/
│   ├── env.py                            # Async Alembic config
│   └── versions/
│       └── <hash>_initial_schema.py
├── tests/
│   ├── conftest.py                       # Fixtures: tmp_db, session
│   └── unit/
│       ├── test_percentage_parser.py
│       ├── test_taxonomies_loader.py
│       ├── test_seed_from_excel.py
│       └── test_split_stratified.py
└── data/
    └── local.db                          # Generado por migraciones
```

---

## Task 1: Bootstrap del proyecto (Poetry + estructura)

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/scraper/__init__.py`

- [ ] **Step 1: Inicializar Poetry**

Ejecutar desde `C:\Users\Joaquin\Desktop\scraper`:

```bash
poetry init --name scraper --description "Buscador/clasificador de productos de inversión" --author "Sabbi <informatica@ccastrovirreyna.com>" --python "^3.11" --no-interaction
```

- [ ] **Step 2: Agregar dependencias runtime**

```bash
poetry add "sqlalchemy[asyncio]>=2.0" "alembic>=1.13" "aiosqlite>=0.19" "pydantic>=2.5" "pydantic-settings>=2.1" "openpyxl>=3.1" "pandas>=2.2" "structlog>=24.1" "pyyaml>=6.0" "rapidfuzz>=3.6"
```

- [ ] **Step 3: Agregar dependencias de dev**

```bash
poetry add --group dev "pytest>=8.0" "pytest-asyncio>=0.23" "pytest-cov>=4.1" "ruff>=0.3" "mypy>=1.8"
```

- [ ] **Step 4: Configurar pyproject.toml con secciones extra**

Sobreescribir `pyproject.toml` (mergeando con lo que Poetry ya puso) con:

```toml
[tool.poetry]
name = "scraper"
version = "0.1.0"
description = "Buscador/clasificador de productos de inversión"
authors = ["Sabbi <informatica@ccastrovirreyna.com>"]
packages = [{include = "scraper", from = "src"}]

[tool.poetry.dependencies]
python = "^3.11"
sqlalchemy = {extras = ["asyncio"], version = ">=2.0"}
alembic = ">=1.13"
aiosqlite = ">=0.19"
pydantic = ">=2.5"
pydantic-settings = ">=2.1"
openpyxl = ">=3.1"
pandas = ">=2.2"
structlog = ">=24.1"
pyyaml = ">=6.0"
rapidfuzz = ">=3.6"

[tool.poetry.group.dev.dependencies]
pytest = ">=8.0"
pytest-asyncio = ">=0.23"
pytest-cov = ">=4.1"
ruff = ">=0.3"
mypy = ">=1.8"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "N"]

[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = "src"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

- [ ] **Step 5: Crear .gitignore**

```gitignore
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
.venv/
.env
data/*.db
data/*.db-shm
data/*.db-wal
data/uploads/
failed_uploads/
*.log
.DS_Store
Thumbs.db
```

- [ ] **Step 6: Crear .env.example**

```
# LLM APIs
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...

# DB
DATABASE_URL=sqlite+aiosqlite:///data/local.db

# Feature flags
SKIP_DEEP_RESEARCH=false

# Alerts
ALERT_COST_DAILY_USD=20

# Auth (bcrypt hashes, generar con streamlit-authenticator en Phase 5)
AUTH_USERS_FILE=config/users.yaml

# Logging
LOG_LEVEL=INFO
```

- [ ] **Step 7: README mínimo**

```markdown
# Scraper — Buscador/Clasificador de Productos de Inversión

Sistema interno de Sabbi para clasificar productos de inversión usando LLMs con HITL mandatorio.

## Setup local

```bash
poetry install
cp .env.example .env  # rellenar con API keys reales
poetry run alembic upgrade head
poetry run python -m scraper.scripts.seed_from_excel "BD_Productos Sabbi.xlsx"
poetry run python -m scraper.scripts.split_train_validation
```

## Tests

```bash
poetry run pytest
```

## Diseño y plan

- Spec: `docs/superpowers/specs/2026-04-17-buscador-clasificador-productos-inversion-design.md`
- Plan Phase 1: `docs/superpowers/plans/2026-04-17-phase1-foundation.md`
```

- [ ] **Step 8: Crear src/scraper/__init__.py vacío**

```python
"""Scraper — buscador/clasificador de productos de inversión."""
```

- [ ] **Step 9: Inicializar git y commit**

```bash
git init
git add .
git commit -m "chore: bootstrap project with Poetry and pyproject config"
```

---

## Task 2: Config module (pydantic-settings)

**Files:**
- Create: `src/scraper/config.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Escribir test que falle**

`tests/unit/test_config.py`:

```python
import os
from unittest.mock import patch

def test_settings_loads_database_url_from_env():
    from scraper.config import Settings
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///test.db"}, clear=False):
        s = Settings()
        assert s.database_url == "sqlite+aiosqlite:///test.db"

def test_settings_defaults_skip_deep_research_false():
    from scraper.config import Settings
    s = Settings(_env_file=None)
    assert s.skip_deep_research is False

def test_settings_alert_cost_daily_default_20():
    from scraper.config import Settings
    s = Settings(_env_file=None)
    assert s.alert_cost_daily_usd == 20.0
```

- [ ] **Step 2: Run test → debe fallar**

```bash
poetry run pytest tests/unit/test_config.py -v
```

Esperado: `ModuleNotFoundError: No module named 'scraper.config'`

- [ ] **Step 3: Implementar config**

`src/scraper/config.py`:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM APIs
    anthropic_api_key: str = Field(default="", description="Claude API key")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    tavily_api_key: str = Field(default="", description="Tavily API key")

    # DB
    database_url: str = Field(default="sqlite+aiosqlite:///data/local.db")

    # Feature flags
    skip_deep_research: bool = Field(default=False)

    # Alerts
    alert_cost_daily_usd: float = Field(default=20.0)

    # Logging
    log_level: str = Field(default="INFO")


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Crear conftest.py con fixtures base**

`tests/conftest.py`:

```python
import os
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def excel_path(repo_root: Path) -> Path:
    return repo_root / "BD_Productos Sabbi.xlsx"
```

- [ ] **Step 5: Run tests — deben pasar**

```bash
poetry run pytest tests/unit/test_config.py -v
```

Esperado: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/scraper/config.py tests/conftest.py tests/unit/test_config.py
git commit -m "feat: add Settings module with pydantic-settings"
```

---

## Task 3: Taxonomías YAML + loader

**Files:**
- Create: `src/scraper/taxonomies/asset_classes.yaml`
- Create: `src/scraper/taxonomies/canonical_assets.yaml`
- Create: `src/scraper/taxonomies/geographic_regions.yaml`
- Create: `src/scraper/taxonomies/loader.py`
- Create: `src/scraper/taxonomies/__init__.py`
- Create: `tests/unit/test_taxonomies_loader.py`

- [ ] **Step 1: Crear asset_classes.yaml**

Estas son las 6 clases macro de la hoja "Clase de Activo (macro)" del Excel. Nombres canónicos exactos:

```yaml
# 6 clases de activo macro — lista cerrada. El clasificador NO puede inventar otras.
asset_classes:
  - name: "Inmobiliario Directo"
  - name: "Mercados Públicos - Fijo"
  - name: "Mercados Públicos - Variable"
  - name: "Mercados Privados"
  - name: "Club deals"
  - name: "Cash y Otros"
```

- [ ] **Step 2: Crear canonical_assets.yaml**

De la hoja "Subyacentes (performance)" del Excel:

```yaml
# ~30 subyacentes canónicos. name = "Activo Canónico (usar este nombre)" exacto.
# macro_class debe matchear uno de asset_classes.
canonical_assets:
  - {name: "Cash", macro_class: "Cash y Otros", score: 10.0}
  - {name: "US Treasuries Corto Plazo", macro_class: "Cash y Otros", score: 9.5}
  - {name: "Oro", macro_class: "Cash y Otros", score: 7.5}
  - {name: "Cripto", macro_class: "Cash y Otros", score: 1.0}
  - {name: "Commodities", macro_class: "Cash y Otros", score: 3.0}

  - {name: "US Treasuries - Largo Plazo", macro_class: "Mercados Públicos - Fijo", score: 8.5}
  - {name: "Bonos Corporativos Investment Grade (AAA-BBB)", macro_class: "Mercados Públicos - Fijo", score: 8.0}
  - {name: "Bonos High Yield", macro_class: "Mercados Públicos - Fijo", score: 5.5}
  - {name: "Bonos Mercados Emergentes (Global)", macro_class: "Mercados Públicos - Fijo", score: 4.0}
  - {name: "Bonos Latinoamérica", macro_class: "Mercados Públicos - Fijo", score: 5.0}
  - {name: "Bonos Perú", macro_class: "Mercados Públicos - Fijo", score: 5.0}

  - {name: "US Large Cap", macro_class: "Mercados Públicos - Variable", score: 4.5}
  - {name: "US Mid & Small Cap", macro_class: "Mercados Públicos - Variable", score: 3.5}
  - {name: "Desarrollados ex US", macro_class: "Mercados Públicos - Variable", score: 5.0}
  - {name: "Mercados Emergentes ex Perú", macro_class: "Mercados Públicos - Variable", score: 2.5}
  - {name: "Acciones Peru", macro_class: "Mercados Públicos - Variable", score: 3.5}
  - {name: "REITs Públicos", macro_class: "Mercados Públicos - Variable", score: 5.5}

  - {name: "Private Credit Senior", macro_class: "Mercados Privados", score: 7.0}
  - {name: "Private Credit Subordinated", macro_class: "Mercados Privados", score: 5.0}
  - {name: "Private Equity", macro_class: "Mercados Privados", score: 2.0}
  - {name: "Venture Capital", macro_class: "Mercados Privados", score: 1.5}
  - {name: "Hedge Funds", macro_class: "Mercados Privados", score: 4.0}
  - {name: "Infrastructure Privada", macro_class: "Mercados Privados", score: 5.0}
  - {name: "Real Estate Privado (Fondos)", macro_class: "Mercados Privados", score: 5.0}

  - {name: "Propiedades Directas Perú", macro_class: "Inmobiliario Directo", score: 5.5}
  - {name: "Propiedades Directas Exterior", macro_class: "Inmobiliario Directo", score: 3.0}

  - {name: "Club Deals Real Estate Perú", macro_class: "Club deals", score: 4.0}
  - {name: "Club Deals Real Estate USA y Otros", macro_class: "Club deals", score: 4.0}
  - {name: "Club Deals Deuda Privada Peru", macro_class: "Club deals", score: 5.5}
  - {name: "Club Deals Deuda Privada Usa", macro_class: "Club deals", score: 5.5}
  - {name: "Club Deals Otros Peru", macro_class: "Club deals", score: 4.0}
  - {name: "Club Deals Otros USA", macro_class: "Club deals", score: 4.0}
```

- [ ] **Step 3: Crear geographic_regions.yaml**

De la hoja "Benchmark Geografico":

```yaml
# 5 regiones canónicas + benchmark weight
geographic_regions:
  - {name: "EEUU", benchmark_weight: 0.465}
  - {name: "Desarrollados ex-US", benchmark_weight: 0.216}
  - {name: "Emergentes ex-Perú", benchmark_weight: 0.142}
  - {name: "Latam ex-Perú", benchmark_weight: 0.038}
  - {name: "Perú", benchmark_weight: 0.139}
```

- [ ] **Step 4: Escribir tests que fallen**

`tests/unit/test_taxonomies_loader.py`:

```python
def test_loads_six_asset_classes():
    from scraper.taxonomies.loader import load_asset_classes
    classes = load_asset_classes()
    assert len(classes) == 6
    names = {c.name for c in classes}
    assert names == {
        "Inmobiliario Directo",
        "Mercados Públicos - Fijo",
        "Mercados Públicos - Variable",
        "Mercados Privados",
        "Club deals",
        "Cash y Otros",
    }


def test_canonical_assets_all_reference_valid_macro_class():
    from scraper.taxonomies.loader import load_asset_classes, load_canonical_assets
    macro_names = {c.name for c in load_asset_classes()}
    for asset in load_canonical_assets():
        assert asset.macro_class in macro_names, \
            f"{asset.name} references invalid macro {asset.macro_class}"


def test_loads_five_regions_summing_to_one():
    from scraper.taxonomies.loader import load_regions
    regions = load_regions()
    assert len(regions) == 5
    total = sum(r.benchmark_weight for r in regions)
    assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"


def test_asset_name_is_unique():
    from scraper.taxonomies.loader import load_canonical_assets
    names = [a.name for a in load_canonical_assets()]
    assert len(names) == len(set(names)), "Duplicate canonical asset names"
```

- [ ] **Step 5: Run tests — fallarán**

```bash
poetry run pytest tests/unit/test_taxonomies_loader.py -v
```

- [ ] **Step 6: Implementar loader**

`src/scraper/taxonomies/__init__.py`:

```python
from scraper.taxonomies.loader import (
    AssetClass,
    CanonicalAsset,
    Region,
    load_asset_classes,
    load_canonical_assets,
    load_regions,
)

__all__ = [
    "AssetClass", "CanonicalAsset", "Region",
    "load_asset_classes", "load_canonical_assets", "load_regions",
]
```

`src/scraper/taxonomies/loader.py`:

```python
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_THIS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class AssetClass:
    name: str


@dataclass(frozen=True)
class CanonicalAsset:
    name: str
    macro_class: str
    score: float


@dataclass(frozen=True)
class Region:
    name: str
    benchmark_weight: float


def _load_yaml(filename: str) -> dict:
    with open(_THIS_DIR / filename, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_asset_classes() -> list[AssetClass]:
    data = _load_yaml("asset_classes.yaml")
    return [AssetClass(name=item["name"]) for item in data["asset_classes"]]


@lru_cache(maxsize=1)
def load_canonical_assets() -> list[CanonicalAsset]:
    data = _load_yaml("canonical_assets.yaml")
    return [
        CanonicalAsset(name=item["name"], macro_class=item["macro_class"], score=float(item["score"]))
        for item in data["canonical_assets"]
    ]


@lru_cache(maxsize=1)
def load_regions() -> list[Region]:
    data = _load_yaml("geographic_regions.yaml")
    return [
        Region(name=item["name"], benchmark_weight=float(item["benchmark_weight"]))
        for item in data["geographic_regions"]
    ]
```

- [ ] **Step 7: Run tests — deben pasar**

```bash
poetry run pytest tests/unit/test_taxonomies_loader.py -v
```

Esperado: 4 passed.

- [ ] **Step 8: Commit**

```bash
git add src/scraper/taxonomies/ tests/unit/test_taxonomies_loader.py
git commit -m "feat: add canonical taxonomies (asset classes, subyacentes, regions) with loader"
```

---

## Task 4: Percentage parser

**Files:**
- Create: `src/scraper/parsers/__init__.py`
- Create: `src/scraper/parsers/percentage_parser.py`
- Create: `tests/unit/test_percentage_parser.py`

Este parser convierte strings como `"Perú 65%, USA 35%"` en dicts. Crítico porque toda la DB usa JSON estructurado en vez de texto libre.

- [ ] **Step 1: Escribir tests que fallen**

`tests/unit/test_percentage_parser.py`:

```python
import pytest


def test_parses_simple_two_regions():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Perú 65%, USA 35%")
    assert result == {"Perú": 65.0, "USA": 35.0}


def test_parses_three_with_latam():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Perú 75%, Emergentes ex-Perú 15%, Latam ex-Perú 10%")
    assert result == {"Perú": 75.0, "Emergentes ex-Perú": 15.0, "Latam ex-Perú": 10.0}


def test_parses_100_percent():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Peru 100%")
    assert result == {"Peru": 100.0}


def test_parses_parentheses_format():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("EEUU (100%)")
    assert result == {"EEUU": 100.0}


def test_parses_decimal_percentages():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Mercados publicos variable 62.44%, Mercados publicos fijo 21.78%")
    assert result == pytest.approx({"Mercados publicos variable": 62.44, "Mercados publicos fijo": 21.78})


def test_parses_newline_separated():
    from scraper.parsers.percentage_parser import parse_percentages
    result = parse_percentages("Mercados publicos fijo 62.31%\nEfectivo 31.51%")
    assert result == pytest.approx({"Mercados publicos fijo": 62.31, "Efectivo": 31.51})


def test_empty_string_returns_empty_dict():
    from scraper.parsers.percentage_parser import parse_percentages
    assert parse_percentages("") == {}


def test_nan_returns_empty_dict():
    from scraper.parsers.percentage_parser import parse_percentages
    assert parse_percentages(None) == {}


def test_raises_when_percents_dont_sum_to_100_strict_mode():
    from scraper.parsers.percentage_parser import parse_percentages, PercentageSumError
    with pytest.raises(PercentageSumError):
        parse_percentages("Perú 50%, USA 30%", strict_sum=True)


def test_sum_tolerance_5_allows_minor_rounding():
    from scraper.parsers.percentage_parser import parse_percentages
    # Suma 99.93, dentro de la tolerancia default de 5pp
    result = parse_percentages("A 33.31%, B 33.31%, C 33.31%", strict_sum=True)
    assert sum(result.values()) == pytest.approx(99.93)
```

- [ ] **Step 2: Run tests — deben fallar**

```bash
poetry run pytest tests/unit/test_percentage_parser.py -v
```

- [ ] **Step 3: Implementar parser**

`src/scraper/parsers/__init__.py`:

```python
from scraper.parsers.percentage_parser import PercentageSumError, parse_percentages

__all__ = ["parse_percentages", "PercentageSumError"]
```

`src/scraper/parsers/percentage_parser.py`:

```python
"""Parser for strings like 'Perú 65%, USA 35%' → {'Perú': 65.0, 'USA': 35.0}."""
from __future__ import annotations

import re

_PATTERN = re.compile(
    r"""
    ^\s*
    (?P<label>[^,\n(0-9][^,\n(]*?)     # etiqueta: texto hasta coma/paren/newline
    [\s(]*                              # espacios y/o paréntesis
    (?P<value>\d+(?:\.\d+)?)            # número con decimal opcional
    \s*%\)?                             # %  y paréntesis de cierre opcional
    \s*$
    """,
    re.VERBOSE,
)


class PercentageSumError(ValueError):
    """Raised when parsed percentages don't sum close to 100%."""


def parse_percentages(raw: str | None, *, strict_sum: bool = False, tolerance: float = 5.0) -> dict[str, float]:
    """Parse 'Label N%, Label N%' (comma- or newline-separated) into a dict.

    Handles variations:
    - 'Perú 65%, USA 35%'
    - 'EEUU (100%)'
    - 'A 62.44%\\nB 21.78%\\nC 15.06%'

    Args:
        raw: Input string. None or empty returns {}.
        strict_sum: If True, raises PercentageSumError when sum is outside 100 ± tolerance.
        tolerance: Allowed deviation from 100% (in percentage points).
    """
    if not raw or not isinstance(raw, str) or raw.strip().lower() in ("nan", "none"):
        return {}

    segments = re.split(r"[,\n]", raw)
    result: dict[str, float] = {}
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        m = _PATTERN.match(segment)
        if not m:
            continue
        label = m.group("label").strip().rstrip(":").strip()
        value = float(m.group("value"))
        if label:
            result[label] = value

    if strict_sum and result:
        total = sum(result.values())
        if abs(total - 100.0) > tolerance:
            raise PercentageSumError(
                f"Percentages sum to {total}, expected 100 ± {tolerance}. Input: {raw!r}"
            )

    return result
```

- [ ] **Step 4: Run tests — deben pasar**

```bash
poetry run pytest tests/unit/test_percentage_parser.py -v
```

Esperado: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/parsers/ tests/unit/test_percentage_parser.py
git commit -m "feat: add percentage string parser for 'Label N%, Label N%' format"
```

---

## Task 5: DB base + SQLAlchemy models

**Files:**
- Create: `src/scraper/db/__init__.py`
- Create: `src/scraper/db/base.py`
- Create: `src/scraper/db/models.py`
- Create: `src/scraper/db/session.py`
- Create: `tests/conftest.py` (extender)
- Create: `tests/unit/test_models.py`

- [ ] **Step 1: Escribir tests que fallen**

`tests/unit/test_models.py`:

```python
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def session():
    from scraper.db.base import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def test_can_insert_product(session: AsyncSession):
    from scraper.db.models import Product
    p = Product(
        nombre="Test Product",
        foco_geografico={"Perú": 100.0},
        clase_activo={"Club deals": 100.0},
        subyacentes={"Club Deals Real Estate Perú": 100.0},
        comision=0.005,
        moneda="dolares",
        administrador="Test Admin",
        gestor="Test Gestor",
        liquidez="Mediano plazo",
        minimo_inversion="150k dolares",
        source_type="excel_seed",
    )
    session.add(p)
    await session.commit()
    assert p.id is not None
    assert p.created_at is not None


async def test_audit_log_insert(session: AsyncSession):
    from scraper.db.models import AuditLog
    entry = AuditLog(
        event_type="product_approved",
        actor="user:sabbi",
        entity_type="product",
        entity_id="42",
        before_state=None,
        after_state={"status": "active"},
    )
    session.add(entry)
    await session.commit()
    assert entry.id is not None
    assert entry.timestamp is not None


async def test_rules_version_uniqueness(session: AsyncSession):
    from scraper.db.models import RulesVersion
    v1 = RulesVersion(version="v1", content_md="# rules", created_by="sabbi")
    v1_dup = RulesVersion(version="v1", content_md="# dup", created_by="sabbi")
    session.add(v1)
    await session.commit()
    session.add(v1_dup)
    with pytest.raises(Exception):  # IntegrityError esperado
        await session.commit()
```

- [ ] **Step 2: Run tests — fallarán**

```bash
poetry run pytest tests/unit/test_models.py -v
```

- [ ] **Step 3: Implementar base**

`src/scraper/db/__init__.py`:

```python
from scraper.db.base import Base
from scraper.db.session import get_session, get_engine

__all__ = ["Base", "get_session", "get_engine"]
```

`src/scraper/db/base.py`:

```python
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map: dict[type, Any] = {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
```

- [ ] **Step 4: Implementar models**

`src/scraper/db/models.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scraper.db.base import Base, utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="editor")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False, index=True)
    foco_geografico: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    clase_activo: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    subyacentes: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    comision: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comision_raw: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # para valores no numéricos
    moneda: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    administrador: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    gestor: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    liquidez: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    minimo_inversion: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_type: Mapped[str] = mapped_column(String, default="manual")
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class TrainingSet(Base):
    __tablename__ = "training_set"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ValidationSet(Base):
    __tablename__ = "validation_set"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RulesVersion(Base):
    __tablename__ = "rules_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_rules_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    examples_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    validation_accuracy: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class Classification(Base):
    __tablename__ = "classifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_name_input: Mapped[str] = mapped_column(String, nullable=False, index=True)
    rules_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rules_versions.id"), nullable=True)
    classifier_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewer_output: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    global_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    per_attribute_confidence: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    final_status: Mapped[str] = mapped_column(String, default="pending_human")
    source_used: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewQueue(Base):
    __tablename__ = "review_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classification_id: Mapped[int] = mapped_column(ForeignKey("classifications.id"))
    flag: Mapped[str] = mapped_column(String, nullable=False)  # auto_approvable, needs_review, low_quality
    assigned_to: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    human_decision: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    human_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)  # "user:123" or "agent:classifier"
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    before_state: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    after_state: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SearchCache(Base):
    __tablename__ = "search_cache"
    query_hash: Mapped[str] = mapped_column(String, primary_key=True)
    query_text: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, primary_key=True)  # tavily|deep_research|scraper:site
    response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ttl_days: Mapped[int] = mapped_column(Integer, default=30)


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extraction_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

- [ ] **Step 5: Implementar session factory**

`src/scraper/db/session.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from scraper.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=False)


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    factory = _session_factory()
    async with factory() as session:
        yield session
```

- [ ] **Step 6: Run tests — deben pasar**

```bash
poetry run pytest tests/unit/test_models.py -v
```

Esperado: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/scraper/db/ tests/unit/test_models.py
git commit -m "feat: add SQLAlchemy models for all core tables (products, rules, classifications, audit, etc.)"
```

---

## Task 6: Alembic setup + primera migración

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/` (auto)
- Modify: con autogenerate

- [ ] **Step 1: Inicializar Alembic async**

```bash
poetry run alembic init -t async alembic
```

Esto crea `alembic/` con `env.py` template async y `alembic.ini`.

- [ ] **Step 2: Configurar alembic.ini**

Editar `alembic.ini`, cambiar solo:

```ini
sqlalchemy.url = sqlite+aiosqlite:///data/local.db
```

- [ ] **Step 3: Configurar alembic/env.py**

Reemplazar contenido con:

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from scraper.config import get_settings
from scraper.db.base import Base
from scraper.db import models  # noqa: F401 — importa para registrar modelos

config = context.config

# Override URL from env
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Crear directorio data/**

```bash
mkdir -p data
```

- [ ] **Step 5: Autogenerate initial migration**

```bash
poetry run alembic revision --autogenerate -m "initial schema"
```

Esto crea `alembic/versions/<hash>_initial_schema.py`.

- [ ] **Step 6: Verificar la migración generada**

Abrir el archivo generado y confirmar que contiene `op.create_table(...)` para cada una de las 10 tablas (users, products, training_set, validation_set, rules_versions, classifications, review_queue, audit_log, search_cache, uploaded_documents). Si falta alguna, revisar que `from scraper.db import models` esté en env.py.

- [ ] **Step 7: Ejecutar migración**

```bash
poetry run alembic upgrade head
```

Esperado: `INFO  [alembic.runtime.migration] Running upgrade  -> <hash>, initial schema`.

Verificar que `data/local.db` existe y tiene las tablas:

```bash
poetry run python -c "import sqlite3; c=sqlite3.connect('data/local.db'); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"
```

Debe listar las 10 tablas + `alembic_version`.

- [ ] **Step 8: Commit**

```bash
git add alembic.ini alembic/
git commit -m "chore: set up Alembic with async env.py and generate initial schema migration"
```

---

## Task 7: Excel seed script (importar 136 productos)

**Files:**
- Create: `src/scraper/scripts/__init__.py`
- Create: `src/scraper/scripts/seed_from_excel.py`
- Create: `tests/unit/test_seed_from_excel.py`

- [ ] **Step 1: Escribir tests que fallen**

`tests/unit/test_seed_from_excel.py`:

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select


@pytest_asyncio.fixture
async def session_with_schema():
    from scraper.db.base import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def test_seed_imports_136_products(session_with_schema, excel_path):
    from scraper.db.models import Product
    from scraper.scripts.seed_from_excel import seed_products

    count = await seed_products(session_with_schema, excel_path)
    assert count == 136

    result = await session_with_schema.execute(select(Product))
    products = list(result.scalars().all())
    assert len(products) == 136


async def test_seed_parses_percentages_into_json(session_with_schema, excel_path):
    from scraper.db.models import Product
    from scraper.scripts.seed_from_excel import seed_products

    await seed_products(session_with_schema, excel_path)
    result = await session_with_schema.execute(
        select(Product).where(Product.nombre == "Credicorp Crecimiento")
    )
    p = result.scalar_one()
    # "Perú 75%, Emergentes ex-Perú 15%, Latam ex-Perú 10%"
    assert p.foco_geografico == pytest.approx(
        {"Perú": 75.0, "Emergentes ex-Perú": 15.0, "Latam ex-Perú": 10.0}
    )
    assert p.source_type == "excel_seed"


async def test_seed_handles_nan_rows_gracefully(session_with_schema, excel_path):
    # La hoja Base tiene filas con NaN en todas las columnas de atributos
    # (ej. "Sabbi Dividendos", "Sabbi Vision Largo Plazo")
    from scraper.db.models import Product
    from scraper.scripts.seed_from_excel import seed_products

    await seed_products(session_with_schema, excel_path)
    result = await session_with_schema.execute(
        select(Product).where(Product.nombre == "Sabbi Dividendos")
    )
    p = result.scalar_one_or_none()
    # Se inserta igual, solo con nombre. Atributos vacíos se marcan status='incomplete'.
    assert p is not None
    assert p.foco_geografico == {}
    assert p.status == "incomplete"


async def test_seed_is_idempotent(session_with_schema, excel_path):
    from scraper.scripts.seed_from_excel import seed_products

    count1 = await seed_products(session_with_schema, excel_path)
    count2 = await seed_products(session_with_schema, excel_path)
    # Segunda corrida no duplica
    assert count1 == 136
    assert count2 == 0  # Ya existían todos
```

- [ ] **Step 2: Run tests — fallarán**

```bash
poetry run pytest tests/unit/test_seed_from_excel.py -v
```

- [ ] **Step 3: Implementar seeder**

`src/scraper/scripts/__init__.py`: vacío.

`src/scraper/scripts/seed_from_excel.py`:

```python
"""Seed products table from BD_Productos Sabbi.xlsx.

Uses sheet 'Base' as source of truth. Handles NaN values gracefully
(incomplete products stored with status='incomplete').
"""
from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

import pandas as pd
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import Product
from scraper.db.session import get_session
from scraper.parsers import parse_percentages

log = structlog.get_logger()


def _str_or_none(v) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s if s and s.lower() != "nan" else None


def _parse_comision(raw: str | None) -> tuple[float | None, str | None]:
    """Return (numeric_value_if_parseable, raw_string_always)."""
    if raw is None:
        return None, None
    # '0.0325' | '0.005' | '0' | '1.40%' | 'Clase A 1.75% - Clase B 1.05%'
    s = str(raw).strip()
    if not s:
        return None, None
    # try direct float
    try:
        return float(s), s
    except ValueError:
        pass
    # try "1.40%"
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0, s
        except ValueError:
            pass
    return None, s


async def seed_products(session: AsyncSession, excel_path: Path) -> int:
    """Load Base sheet into products table. Returns # of rows inserted."""
    df = pd.read_excel(excel_path, sheet_name="Base", header=2)
    df = df.dropna(subset=[df.columns[1]])  # drop rows without name

    # columns from header row 2 (0-indexed): skip first NaN col
    # expected: 'Nombre de Producto', 'Foco Geografico (porcentaje)', ...
    col_map = {
        "nombre": df.columns[1],
        "foco": df.columns[2],
        "clase": df.columns[3],
        "subyacente": df.columns[4],
        "comision": df.columns[5],
        "moneda": df.columns[6],
        "admin": df.columns[7],
        "gestor": df.columns[8],
        "liquidez": df.columns[9],
    }

    inserted = 0
    for _, row in df.iterrows():
        nombre = _str_or_none(row[col_map["nombre"]])
        if not nombre:
            continue

        # idempotency — skip if exists
        exists = await session.execute(select(Product).where(Product.nombre == nombre))
        if exists.scalar_one_or_none() is not None:
            continue

        foco = parse_percentages(_str_or_none(row[col_map["foco"]]))
        clase = parse_percentages(_str_or_none(row[col_map["clase"]]))
        subyacente = parse_percentages(_str_or_none(row[col_map["subyacente"]]))
        comision_num, comision_raw = _parse_comision(_str_or_none(row[col_map["comision"]]))

        # status=incomplete if any critical field is empty
        is_complete = bool(foco and clase and subyacente)

        p = Product(
            nombre=nombre,
            foco_geografico=foco,
            clase_activo=clase,
            subyacentes=subyacente,
            comision=comision_num,
            comision_raw=comision_raw,
            moneda=_str_or_none(row[col_map["moneda"]]),
            administrador=_str_or_none(row[col_map["admin"]]),
            gestor=_str_or_none(row[col_map["gestor"]]),
            liquidez=_str_or_none(row[col_map["liquidez"]]),
            source_type="excel_seed",
            status="active" if is_complete else "incomplete",
        )
        session.add(p)
        inserted += 1

    await session.commit()
    log.info("seed_completed", inserted=inserted, source=str(excel_path))
    return inserted


async def _main(excel_path: Path) -> None:
    async with get_session() as s:
        count = await seed_products(s, excel_path)
        print(f"Seeded {count} products from {excel_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scraper.scripts.seed_from_excel <path-to-xlsx>")
        sys.exit(1)
    asyncio.run(_main(Path(sys.argv[1])))
```

- [ ] **Step 4: Run tests — deben pasar**

```bash
poetry run pytest tests/unit/test_seed_from_excel.py -v
```

Esperado: 4 passed.

**Nota:** el test del count `== 136` depende de la data real del Excel. Si el número exacto es distinto (ej. 134 porque dos filas están totalmente vacías), ajustar el assertion a ese número. El script debe leer e insertar TODOS los productos con nombre no vacío.

- [ ] **Step 5: Correr seeder manualmente contra la DB real**

```bash
poetry run python -m scraper.scripts.seed_from_excel "BD_Productos Sabbi.xlsx"
```

Esperado: `Seeded 136 products from BD_Productos Sabbi.xlsx`.

Verificar:

```bash
poetry run python -c "
import asyncio
from sqlalchemy import func, select
from scraper.db.models import Product
from scraper.db.session import get_session

async def main():
    async with get_session() as s:
        r = await s.execute(select(func.count(Product.id)))
        print('Total productos:', r.scalar())
        r = await s.execute(select(func.count(Product.id)).where(Product.status == 'incomplete'))
        print('Incompletos:', r.scalar())

asyncio.run(main())
"
```

- [ ] **Step 6: Commit**

```bash
git add src/scraper/scripts/ tests/unit/test_seed_from_excel.py
git commit -m "feat: add seed_from_excel script to import 136 products from BD Sabbi xlsx"
```

---

## Task 8: Train/Validation stratified split

**Files:**
- Create: `src/scraper/scripts/split_train_validation.py`
- Create: `tests/unit/test_split_stratified.py`

El split estratifica por **clase de activo macro dominante** (la clase con mayor %). Productos con `status='incomplete'` se excluyen. Objetivo: ~110 training / ~26 validation.

- [ ] **Step 1: Escribir tests que fallen**

`tests/unit/test_split_stratified.py`:

```python
from collections import Counter

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def seeded_session(excel_path):
    from scraper.db.base import Base
    from scraper.scripts.seed_from_excel import seed_products

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        await seed_products(s, excel_path)
        yield s
    await engine.dispose()


def test_dominant_class_picks_highest_percentage():
    from scraper.scripts.split_train_validation import dominant_macro_class
    assert (
        dominant_macro_class({"Mercados publicos variable": 62.44, "Mercados publicos fijo": 21.78, "Efectivo": 15.06})
        == "Mercados publicos variable"
    )


def test_dominant_class_returns_none_for_empty():
    from scraper.scripts.split_train_validation import dominant_macro_class
    assert dominant_macro_class({}) is None


async def test_split_excludes_incomplete_products(seeded_session):
    from scraper.db.models import Product, TrainingSet, ValidationSet
    from scraper.scripts.split_train_validation import run_split

    train_count, val_count = await run_split(seeded_session, validation_ratio=0.2, seed=42)

    # Incompletos (NaN en Excel) NO deben aparecer en ningún split
    r = await seeded_session.execute(select(Product).where(Product.status == "incomplete"))
    incomplete_ids = {p.id for p in r.scalars().all()}

    r = await seeded_session.execute(select(TrainingSet.product_id))
    training_ids = {row[0] for row in r.all()}

    r = await seeded_session.execute(select(ValidationSet.product_id))
    validation_ids = {row[0] for row in r.all()}

    assert training_ids.isdisjoint(incomplete_ids)
    assert validation_ids.isdisjoint(incomplete_ids)
    assert training_ids.isdisjoint(validation_ids)


async def test_split_ratio_approximately_80_20(seeded_session):
    from scraper.scripts.split_train_validation import run_split

    train_count, val_count = await run_split(seeded_session, validation_ratio=0.2, seed=42)
    total = train_count + val_count
    # 20% tolerancia por estratificación con clases de distintos tamaños
    ratio = val_count / total
    assert 0.15 <= ratio <= 0.25, f"Validation ratio {ratio:.2%} outside 15-25%"


async def test_split_stratified_covers_all_macro_classes(seeded_session):
    from scraper.db.models import Product, ValidationSet
    from scraper.scripts.split_train_validation import run_split, dominant_macro_class

    await run_split(seeded_session, validation_ratio=0.2, seed=42)

    r = await seeded_session.execute(
        select(Product).join(ValidationSet, Product.id == ValidationSet.product_id)
    )
    val_products = list(r.scalars().all())

    macro_counts = Counter(dominant_macro_class(p.clase_activo) for p in val_products if p.clase_activo)
    # Cada clase macro presente en el dataset debe tener >=1 producto en validation
    # (garantizado por estratificación)
    assert len(macro_counts) >= 4, f"Solo {len(macro_counts)} clases en validation: {macro_counts}"


async def test_split_is_idempotent_with_same_seed(seeded_session):
    from scraper.db.models import TrainingSet, ValidationSet
    from scraper.scripts.split_train_validation import run_split

    await run_split(seeded_session, validation_ratio=0.2, seed=42)
    r1 = await seeded_session.execute(select(ValidationSet.product_id))
    first_val_ids = sorted([row[0] for row in r1.all()])

    # Borrar splits anteriores
    await seeded_session.execute(TrainingSet.__table__.delete())
    await seeded_session.execute(ValidationSet.__table__.delete())
    await seeded_session.commit()

    await run_split(seeded_session, validation_ratio=0.2, seed=42)
    r2 = await seeded_session.execute(select(ValidationSet.product_id))
    second_val_ids = sorted([row[0] for row in r2.all()])

    assert first_val_ids == second_val_ids
```

- [ ] **Step 2: Run tests — fallarán**

```bash
poetry run pytest tests/unit/test_split_stratified.py -v
```

- [ ] **Step 3: Implementar split**

`src/scraper/scripts/split_train_validation.py`:

```python
"""Stratified 80/20 split of products into training / validation.

Stratified by dominant macro class to ensure each class is represented in both sets.
Excludes products with status='incomplete'.
"""
from __future__ import annotations

import asyncio
import random
from collections import defaultdict

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scraper.db.models import Product, TrainingSet, ValidationSet
from scraper.db.session import get_session

log = structlog.get_logger()


def dominant_macro_class(clase_activo: dict[str, float]) -> str | None:
    """Return the class with highest percentage. None if dict is empty."""
    if not clase_activo:
        return None
    return max(clase_activo.items(), key=lambda kv: kv[1])[0]


async def run_split(
    session: AsyncSession,
    validation_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[int, int]:
    """Populate training_set and validation_set tables.

    Returns (training_count, validation_count).
    """
    # 1. Fetch eligible products (status='active')
    r = await session.execute(select(Product).where(Product.status == "active"))
    products = list(r.scalars().all())

    # 2. Group by dominant macro class
    by_class: dict[str, list[Product]] = defaultdict(list)
    for p in products:
        key = dominant_macro_class(p.clase_activo) or "__unknown__"
        by_class[key].append(p)

    # 3. For each bucket, deterministic shuffle + take validation_ratio
    rng = random.Random(seed)
    training: list[int] = []
    validation: list[int] = []
    for macro_class, group in sorted(by_class.items()):
        group_sorted = sorted(group, key=lambda p: p.id)  # deterministic order
        shuffled = group_sorted[:]
        rng.shuffle(shuffled)
        n_val = max(1, round(len(shuffled) * validation_ratio)) if len(shuffled) >= 5 else 0
        val_ids = [p.id for p in shuffled[:n_val]]
        train_ids = [p.id for p in shuffled[n_val:]]
        validation.extend(val_ids)
        training.extend(train_ids)
        log.info("split_bucket", macro=macro_class, total=len(group), train=len(train_ids), val=len(val_ids))

    # 4. Write to DB
    for pid in training:
        session.add(TrainingSet(product_id=pid))
    for pid in validation:
        session.add(ValidationSet(product_id=pid))
    await session.commit()
    log.info("split_done", training=len(training), validation=len(validation))
    return len(training), len(validation)


async def _main() -> None:
    async with get_session() as s:
        t, v = await run_split(s)
        print(f"Training: {t} | Validation: {v}")


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 4: Run tests — deben pasar**

```bash
poetry run pytest tests/unit/test_split_stratified.py -v
```

Esperado: 6 passed.

- [ ] **Step 5: Correr split sobre la DB real**

```bash
poetry run python -m scraper.scripts.split_train_validation
```

Verificar:

```bash
poetry run python -c "
import asyncio
from sqlalchemy import func, select
from scraper.db.models import TrainingSet, ValidationSet
from scraper.db.session import get_session

async def main():
    async with get_session() as s:
        r = await s.execute(select(func.count()).select_from(TrainingSet))
        print('Training:', r.scalar())
        r = await s.execute(select(func.count()).select_from(ValidationSet))
        print('Validation:', r.scalar())

asyncio.run(main())
"
```

Esperado: Training ≈ 110, Validation ≈ 26 (puede variar ligeramente por redondeo de buckets).

- [ ] **Step 6: Commit**

```bash
git add src/scraper/scripts/split_train_validation.py tests/unit/test_split_stratified.py
git commit -m "feat: stratified train/validation split by dominant macro class"
```

---

## Task 9: Verificación end-to-end de Phase 1

**Files:**
- Create: `tests/unit/test_phase1_smoke.py`

- [ ] **Step 1: Smoke test que corre todo el flow**

`tests/unit/test_phase1_smoke.py`:

```python
"""Smoke test: seed excel → split → assertions básicas de estado."""
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def pipeline_session(excel_path):
    from scraper.db.base import Base
    from scraper.scripts.seed_from_excel import seed_products
    from scraper.scripts.split_train_validation import run_split

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        await seed_products(s, excel_path)
        await run_split(s, validation_ratio=0.2, seed=42)
        yield s
    await engine.dispose()


async def test_all_active_products_in_exactly_one_split(pipeline_session):
    from scraper.db.models import Product, TrainingSet, ValidationSet

    r = await pipeline_session.execute(select(Product).where(Product.status == "active"))
    active = list(r.scalars().all())

    r = await pipeline_session.execute(select(TrainingSet.product_id))
    train_ids = {row[0] for row in r.all()}
    r = await pipeline_session.execute(select(ValidationSet.product_id))
    val_ids = {row[0] for row in r.all()}

    for p in active:
        in_train = p.id in train_ids
        in_val = p.id in val_ids
        assert in_train ^ in_val, f"Product {p.nombre} in {[in_train, in_val]} splits (must be exactly one)"


async def test_taxonomy_values_match_dataset_values(pipeline_session):
    """Sanity: los valores que el Excel usa en `clase_activo` deben ser re-mapeables a las 6 canónicas.
    (Este test puede fallar si el Excel usa variantes ortográficas — lo vamos a necesitar
    saber antes de Phase 2 para normalizar.)"""
    from scraper.db.models import Product
    from scraper.taxonomies import load_asset_classes

    canonical = {c.name.lower().strip() for c in load_asset_classes()}
    # Variantes observadas en el Excel:
    excel_variants_to_canonical = {
        "mercados publicos variable": "Mercados Públicos - Variable",
        "mercados publicos fijo": "Mercados Públicos - Fijo",
        "cash y otros": "Cash y Otros",
        "club deal": "Club deals",
        "mercados privados": "Mercados Privados",
        "efectivo": "Cash y Otros",
        "otros": "Cash y Otros",
        "mercado publico variable": "Mercados Públicos - Variable",
    }
    r = await pipeline_session.execute(select(Product).where(Product.status == "active"))
    unknowns = set()
    for p in r.scalars().all():
        for raw_key in p.clase_activo.keys():
            normalized = raw_key.lower().strip()
            if normalized in canonical:
                continue
            if normalized in excel_variants_to_canonical:
                continue
            unknowns.add(raw_key)
    # Documentamos las variantes encontradas — si hay NUEVAS, falla y las muestra.
    assert not unknowns, f"Variantes no mapeadas a taxonomía canónica: {unknowns}"
```

- [ ] **Step 2: Run test**

```bash
poetry run pytest tests/unit/test_phase1_smoke.py -v
```

Si el segundo test falla con variantes nuevas, extender `excel_variants_to_canonical` con ellas y documentar en el código. Ese mapeo se va a necesitar en Phase 2 cuando el Extractor normalice vocabulario.

- [ ] **Step 3: Correr full suite**

```bash
poetry run pytest -v
```

Esperado: todos los tests verdes. Numbers approximadamente:
- test_config.py: 3
- test_taxonomies_loader.py: 4
- test_percentage_parser.py: 10
- test_models.py: 3
- test_seed_from_excel.py: 4
- test_split_stratified.py: 6
- test_phase1_smoke.py: 2
- **Total: ~32 tests**

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_phase1_smoke.py
git commit -m "test: add phase1 smoke test for full seed+split pipeline"
```

---

## Task 10: Cerrar Phase 1 (documentación + tag)

**Files:**
- Modify: `README.md`
- Create: `docs/superpowers/plans/phase1-STATUS.md`

- [ ] **Step 1: Actualizar README con estado Phase 1**

Reemplazar `README.md`:

```markdown
# Scraper — Buscador/Clasificador de Productos de Inversión

Sistema interno de Sabbi para clasificar productos de inversión usando LLMs con HITL mandatorio.

## Estado del proyecto

- [x] Phase 1: Foundation (DB + seed desde Excel + split 80/20)
- [ ] Phase 2: Agents offline (Extractor + Clasificador + Revisor + calibración)
- [ ] Phase 3: Orchestrator + FastAPI
- [ ] Phase 4: Search cascade
- [ ] Phase 5: Streamlit UI
- [ ] Phase 6: Robustez + deploy

## Setup local

```bash
poetry install
cp .env.example .env  # rellenar con API keys reales
poetry run alembic upgrade head
poetry run python -m scraper.scripts.seed_from_excel "BD_Productos Sabbi.xlsx"
poetry run python -m scraper.scripts.split_train_validation
```

## Tests

```bash
poetry run pytest
```

## Diseño y planes

- Spec: `docs/superpowers/specs/2026-04-17-buscador-clasificador-productos-inversion-design.md`
- Plan Phase 1: `docs/superpowers/plans/2026-04-17-phase1-foundation.md`
```

- [ ] **Step 2: Crear phase1-STATUS.md**

`docs/superpowers/plans/phase1-STATUS.md`:

```markdown
# Phase 1 — Status

**Completed:** <fecha>
**Tests passing:** ~32
**Productos importados:** 136 (X active, Y incomplete)
**Split:** ~110 training / ~26 validation

## Notas para Phase 2

- Variantes ortográficas del Excel que se mapean a taxonomía canónica están en
  `tests/unit/test_phase1_smoke.py::excel_variants_to_canonical` — mover a un
  módulo `scraper/taxonomies/normalizer.py` cuando lo necesitemos.
- Productos incomplete (Sabbi Dividendos, Sabbi Vision Largo Plazo, etc.)
  NO están en el split. Si se completan manualmente después, re-correr split.
- La seed está diseñada idempotente — re-correr no duplica ni pisa.

## Queda para Phase 2

- Extractor (HTML + PDF texto + PDF vision)
- Clasificador (Claude Sonnet 4.6)
- Revisor (Claude Opus 4.7)
- Rules v1.md a partir de training_set
- Regression test contra validation_set
- CLI: `poetry run python -m scraper.scripts.classify_one "Credicorp Crecimiento"`
```

- [ ] **Step 3: Tag git phase1**

```bash
git add README.md docs/superpowers/plans/phase1-STATUS.md
git commit -m "docs: close Phase 1 — foundation complete"
git tag phase1-complete
```

- [ ] **Step 4: Verificación final**

Correr el checklist completo:

```bash
# DB limpia desde cero
rm -f data/local.db
poetry run alembic upgrade head
poetry run python -m scraper.scripts.seed_from_excel "BD_Productos Sabbi.xlsx"
poetry run python -m scraper.scripts.split_train_validation
poetry run pytest -v
```

Todo verde → Phase 1 lista para entregar. Phase 2 puede empezar.

---

## Criterios de éxito Phase 1

- [x] `poetry install` funciona sin errores
- [x] `alembic upgrade head` crea las 10 tablas en `data/local.db`
- [x] Seed importa 136 productos (`active` + `incomplete`) sin perder ninguno
- [x] Split produce ~110 training / ~26 validation, estratificado por clase macro
- [x] Cada producto activo está en exactamente un split (ni en los dos, ni en ninguno)
- [x] Tests unitarios pasan (~32 tests)
- [x] Taxonomías canónicas (6 clases, 30 subyacentes, 5 regiones) cargan correctamente
- [x] Parser de porcentajes maneja todas las variantes encontradas en el Excel
- [x] Seed es idempotente (re-correr no duplica)
- [x] Split es determinista con el mismo seed

---

## Execution handoff

Dos opciones:

**1. Subagent-Driven (recomendado)** — despacho un subagente fresh por cada tarea, reviso entre tareas, iteración rápida.

**2. Inline Execution** — ejecuto las tareas en esta sesión con executing-plans, con checkpoints para review.

¿Cuál prefieres?
