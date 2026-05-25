# Phase 2b — Extract + Search Cascade — Design

**Fecha:** 2026-04-18
**Autor:** Sabbi + Claude
**Status:** Design aprobado, pendiente de plan detallado
**Predecesor:** Phase 2a (`phase2a-complete` tag `77fafe5`) — classifier + reviewer + calibración con rules v3

## 1. Goal

Extender el sistema de Phase 2a (que clasifica productos ya conocidos) a un pipeline end-to-end que acepta el **nombre de un producto** (sin URL, sin PDF) y devuelve una clasificación canónica completa, apoyado por:

1. DB cache de productos previamente clasificados
2. Parsers específicos para 7 sitios conocidos (SMV, SBS, Credicorp, BCP, Core Capital, Sabbi, BVL)
3. Web search con Claude nativo (`web_search_20250305` tool)
4. Intensive Claude search con kill switch (fallback de última instancia)
5. CLI `extract_one` para extracción directa desde URL o PDF (sin cascada)

**Deliverable clave:** `poetry run python -m scraper.scripts.find_and_classify "Credicorp Crecimiento"` devuelve clasificación completa con trazabilidad a fuentes.

## 2. Non-goals

Explícitamente fuera de Phase 2b:

- ❌ OpenAI Deep Research (usamos Claude intensive en su lugar; Deep Research queda para un eventual Phase 2c si la calibración indica insuficiencia)
- ❌ UI de upload manual de PDF (Phase 5 — UI Streamlit)
- ❌ FastAPI wrapping (Phase 3)
- ❌ Streamlit frontend completo (Phase 5)
- ❌ ReviewQueue persistence / workflow HITL completo (Phase 3)
- ❌ Audit log completo con `audit_log` table (Phase 3)
- ❌ Multi-idioma: fichas asumidas en español o inglés estándar

## 3. Arquitectura

### 3.1 Flujo de datos

```
Input: nombre | --url X | --pdf ficha.pdf
                    │
     ┌──────────────┼──────────────┐
     ▼              ▼              ▼
  name-path      url-path       pdf-path
     │              │              │
     ▼              ▼              ▼
┌─────────┐    ┌─────────┐    ┌─────────┐
│Cascade  │    │Extract  │    │Extract  │
│N0→N1→   │    │HTML     │    │PDF text │
│N2→N3    │    │(httpx+  │    │+vision  │
└────┬────┘    │Playwright│   │fallback │
     │         │+Claude) │    │         │
     │         └────┬────┘    └────┬────┘
     │              │              │
     │         ┌────▼────┐         │
     └─────────► Extracted◄─────────┘
               │  Ficha   │
               │ (thick, │
               │ canonic-│
               │ best-   │
               │ effort) │
               └────┬────┘
                    ▼
          Phase 2a classifier (refina)
                    ▼
          Phase 2a reviewer → decide_flag
                    ▼
          Save to `classifications` table
                    ▼
          Print / return to user
```

### 3.2 Principios

- **3 entry points, 1 output format.** Name/url/pdf convergen en `ExtractedFicha`.
- **No pre-merge de múltiples fuentes.** Cada fuente produce su `ExtractedFicha`; el classifier recibe todas como "evidence blocks" y aplica rules.
- **Thick extractor.** El extractor intenta canonizar a taxonomías. El classifier después refina y valida. Duplicación mínima del prompt de taxonomías; separación limpia de responsabilidades (extractor cita fuente, classifier aplica reglas).
- **Kill switches y cost tracking** por nivel. Ningún API costoso se activa sin opt-in explícito.

## 4. Search cascade

### N0 — DB local

Fuzzy lookup sobre `products.nombre` usando `rapidfuzz.fuzz.ratio ≥85`. Hit = short-circuit (no más levels).

```python
async def lookup_db(nombre: str) -> ExtractedFicha | None:
    # SELECT all product names; compute ratio; pick top if ≥85
```

### N1 — Targets conocidos

7 parsers Python, uno por sitio. Protocolo común `SiteParser`:

```python
class SiteParser(Protocol):
    domain: str
    async def search_by_name(self, nombre: str) -> list[str]:  # candidate URLs
    async def parse_ficha(self, url: str) -> ExtractedFicha:
```

Registry:

```python
TARGETS: list[SiteParser] = [
    SMVGobPeParser(), SBSGobPeParser(),
    CredicorpCapitalParser(), BCPCapitalParser(),
    CoreCapitalParser(), SabbiPeParser(),
    BVLComPeParser(),
]
```

Ejecución: `asyncio.gather` con timeout 30s individual. **NO hay short-circuit** entre parsers — agrega todos los hits (pueden ser fichas parciales complementarias).

### N2 — Claude web_search

1 API call a Claude Sonnet 4.6 con tool `web_search_20250305`:

```python
response = await client.messages.create(
    model="claude-sonnet-4-6",
    system=[extract_system_blocks(), cached],
    messages=[{"role": "user", "content": f"Find fact sheet for: {nombre}"}],
    tools=[{"type": "web_search_20250305"}],
    max_tokens=4096,
)
```

Returns: 0-3 `ExtractedFicha` candidatos con citations a URLs descubiertas.

**Skip si** N1 produjo ≥1 hit con `confidence ≥0.85`.

### N3 — Claude intensive

Misma stack que N2 pero con instrucción "search until you find or run out" y max 10 web_search iterations. Se activa con `SKIP_INTENSIVE_SEARCH=false` en `.env` (default `true` = desactivado).

Costo estimado: ~$0.50-1.00 por query. Reservado para productos obscuros que N0-N2 no encuentran.

### N4 — No se corre en cascada

Solo se accede directamente vía `extract_one --pdf ficha.pdf` o `extract_one --url X`. El usuario invoca explícitamente. Integración UI en Phase 5.

### Orquestador

`scraper.search.cascade.run_cascade(nombre, config) -> CascadeResult`:

```python
async def run_cascade(nombre: str) -> CascadeResult:
    # N0
    db_hit = await lookup_db(nombre)
    if db_hit:
        return CascadeResult(level=0, fichas=[db_hit])

    # N1 parallel
    n1 = await run_n1_parsers(nombre)
    if best_confidence(n1) >= 0.85:
        return CascadeResult(level=1, fichas=n1)

    # N2
    n2 = await run_claude_websearch(nombre)
    combined = merge_candidates(n1, n2)
    if best_confidence(combined) >= 0.70:
        return CascadeResult(level=2, fichas=combined)

    # N3 (opt-in)
    if settings.skip_intensive_search:
        return CascadeResult(level=2, fichas=combined, low_quality=True)
    n3 = await run_claude_intensive(nombre)
    return CascadeResult(level=3, fichas=merge_candidates(combined, n3))
```

### Umbrales

- **N1→N2 skip:** `best_confidence ≥ 0.85`
- **N2→N3 skip:** `best_confidence ≥ 0.70`

Definición: `best_confidence(fichas) = max(f.source_confidence for f in fichas, default=0.0)`. `source_confidence` de cada `ExtractedFicha` se setea al generarla según el nivel y la robustez del match (parser N1 exitoso → 0.95; web_search con citas convergentes → 0.80; sin citas → 0.60). Ambos umbrales ajustables post-calibración.

### Merge de candidatos

`merge_candidates(a, b) = [*a, *b]` dedupe-ado por `(source_url, source_type)`. NO se fusionan atributos entre fichas — cada `ExtractedFicha` se pasa como evidence block independiente al classifier, que decide con rules.

### Caching

`search_cache` table existente. Key = `sha256(normalize(nombre))`. TTL:
- N0 miss: no cachear
- N1 hits: 7 días
- N2 hits: 30 días
- N3 hits: sin cache hasta calibrar (cambios de rules invalidan)

### Circuit breaker

Por parser N1: si falla >5 veces en 10 min → desactivado 15 min. Singleton `CircuitBreaker` en `scraper.search.circuit_breaker`.

## 5. Extractores

### 5.1 `ExtractedFicha` schema

```python
@dataclass(frozen=True)
class AttributeExtraction:
    value: Any | None
    confidence: float
    reasoning: str
    raw_quote: str | None


@dataclass(frozen=True)
class ExtractedFicha:
    source_url: str | None           # None si PDF upload
    source_type: str                 # html|pdf_text|pdf_vision|db|websearch
    source_confidence: float
    fetched_at: datetime

    raw_text: str
    tables: list[list[list[str]]]

    attributes: dict[str, AttributeExtraction]
    # keys: nombre, foco_geografico, clase_activo, subyacente,
    #       comision, moneda, administrador, gestor, liquidez, minimo_inversion

    citations: list[str]
    extraction_cost_usd: float
    extraction_duration_ms: int
```

**Diferencias con `ClassificationResult` (Phase 2a):**
- `raw_quote` por atributo (trazabilidad)
- `tables`, `raw_text`, `citations` (contexto)
- `ClassificationResult` es output limpio final; `ExtractedFicha` es input intermedio.

### 5.2 Extractor HTML

```python
async def extract_from_url(url: str) -> ExtractedFicha:
    html = await fetch_url(url)                          # httpx
    if is_js_rendered(html):
        html = await fetch_with_playwright(url)           # fallback

    soup = BeautifulSoup(html, 'lxml')
    for tag in ['script', 'style', 'nav', 'footer', 'aside']:
        for el in soup.find_all(tag): el.decompose()
    main = soup.find('main') or soup.find('article') or soup
    raw_text = main.get_text('\n', strip=True)
    tables = extract_tables(soup)

    return await extract_with_claude(
        source_url=url,
        source_type="html",
        raw_text=raw_text,
        tables=tables,
    )
```

`is_js_rendered` heuristic: body text <500 chars OR `<noscript>` tag with "enable JavaScript" message.

### 5.3 Extractor PDF

```python
async def extract_from_pdf(path: Path) -> ExtractedFicha:
    text = pypdf.extract_text(path)
    tables = pdfplumber.extract_tables(path)

    if len(text.strip()) < 200:                          # probably scanned
        return await extract_with_claude_vision(path)

    return await extract_with_claude(
        source_url=None,
        source_type="pdf_text",
        raw_text=text,
        tables=tables,
    )
```

Vision fallback: render pages como imágenes (pypdf or pdf2image), send a Claude con formato image block.

### 5.4 Extractor agent

`src/scraper/agents/extractor.py`:

```python
async def extract_with_claude(
    *,
    llm: LLMClient,
    source_url: str | None,
    source_type: str,
    raw_text: str,
    tables: list[list[list[str]]],
) -> ExtractedFicha:
    system_blocks = build_extractor_system_blocks()  # cached
    user_message = render_source(raw_text, tables, source_url)
    result = await llm.call(
        model="claude-sonnet-4-6",
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=4096,
    )
    return parse_extraction(result)
```

**Prompt separado** del classifier:
- `src/scraper/agents/prompts/extractor_system.md`
- Incluye taxonomías canónicas (cached, mismas que classifier)
- **NO** incluye rules de clasificación (extractor no aplica rules; solo extrae)
- Instrucción: "para cada atributo, dame value + raw_quote del texto fuente"

**Modelo:** Claude Sonnet 4.6 (suficiente para extracción; Opus reservado para reviewer).

## 6. File structure

```
src/scraper/
├── extract/                            # NEW
│   ├── __init__.py
│   ├── html.py                         # fetch + clean + Claude
│   ├── pdf.py                          # pypdf + pdfplumber + Claude
│   ├── vision.py                       # Claude vision fallback
│   └── fetch.py                        # httpx + Playwright wrapper
├── search/                             # NEW
│   ├── __init__.py
│   ├── cascade.py                      # orchestrator
│   ├── level0_db.py                    # rapidfuzz lookup
│   ├── level1_scrapers/
│   │   ├── __init__.py
│   │   ├── base.py                     # SiteParser protocol
│   │   ├── registry.py                 # TARGETS = [...]
│   │   ├── smv_gob_pe.py
│   │   ├── sbs_gob_pe.py
│   │   ├── credicorpcapital_com.py
│   │   ├── bcpcapital_com.py
│   │   ├── corecapital_pe.py
│   │   ├── sabbi_pe.py
│   │   └── bvl_com_pe.py
│   ├── level2_websearch.py
│   ├── level3_intensive.py
│   ├── cache.py                        # search_cache integration
│   └── circuit_breaker.py
├── agents/
│   ├── extractor.py                    # NEW: extract() async
│   ├── prompts/
│   │   └── extractor_system.md         # NEW
│   └── types.py                        # + ExtractedFicha, AttributeExtraction
└── scripts/
    ├── extract_one.py                  # NEW CLI (--url, --pdf)
    ├── find_and_classify.py            # NEW CLI — end-to-end pipeline
    └── (existing)
```

## 7. Tasks

### Grupo A — Foundation
1. `ExtractedFicha` + `AttributeExtraction` dataclasses en `agents/types.py`
2. `scraper.extract.fetch` — httpx wrapper + Playwright fallback + timeouts + retry
3. Extractor agent: prompt template + `extract_with_claude()` + tests mocked

### Grupo B — Extractores
4. HTML extractor: BeautifulSoup cleaner + table extraction + fixture real
5. PDF text extractor: pypdf + pdfplumber + scanned detection
6. PDF vision extractor: Claude vision fallback

### Grupo C — Search cascade
7. `CascadeResult`, orchestrator skeleton
8. N0: DB fuzzy lookup
9. N1: SiteParser protocol + registry + 1 parser (credicorpcapital.com)
10. N1: los otros 6 parsers (smv, sbs, bcp, corecapital, sabbi, bvl) — 1 commit por parser
11. N1: circuit breaker
12. N2: Claude web_search wrapper
13. N3: Claude intensive (kill switch `SKIP_INTENSIVE_SEARCH=true` default)
14. search_cache integration con TTL por nivel

### Grupo D — CLI + E2E
15. `extract_one` CLI (--url, --pdf)
16. `find_and_classify` CLI — cascade + classifier + reviewer + DB save
17. Integration test end-to-end (mocked LLM + mocked HTTP)

### Grupo E — Cierre
18. Calibración vs validation_set: nombre → find_and_classify. Medir accuracy end-to-end vs v3 baseline
19. README + `phase2b-STATUS.md` + tag `phase2b-complete`

## 8. Criterios de éxito

- [ ] `poetry run python -m scraper.scripts.find_and_classify "Credicorp Crecimiento"` retorna clasificación completa
- [ ] `poetry run python -m scraper.scripts.extract_one --pdf ficha.pdf` extrae ficha estructurada
- [ ] `poetry run python -m scraper.scripts.extract_one --url https://...` idem para URL
- [ ] 7 parsers N1 funcionando con fixtures de HTML real versionadas
- [ ] Accuracy vs validation_set (nombre → cascade → extract → classify con rules v3) ≥85% por atributo
- [ ] Cost promedio: ≤$0.30 per query con caching activo y N3 off
- [ ] Circuit breakers + timeouts + retry documentados por nivel
- [ ] Kill switch `SKIP_INTENSIVE_SEARCH` probado
- [ ] ~100 tests totales (75 Phase 2a + ~25 nuevos)

## 9. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| N1 parsers se rompen al cambiar HTML de un sitio | Fixtures versionadas en `tests/fixtures/html/<dominio>/*.html`; tests CI con captura de HTML real; alertas vía structured logging cuando un parser devuelve 0 hits |
| Claude web_search costs scale unexpectedly | Cost tracking per-query + daily budget circuit breaker (skip N2/N3 si `cost_today_usd > budget`) |
| PDFs escaneados dan texto vacío y vision falla | Heurística `len(text) < 200` explícita + fallback documentado + tests con ambos tipos de PDF |
| Playwright Chromium pesa ~300MB en CI | Instalación lazy: solo se instala cuando httpx detecta contenido JS-rendered; documentar en `README.md` setup |
| Cambio de taxonomías canónicas requiere re-extraer | Versioning en `extractor_system.md`; `ExtractedFicha.source_type` permite invalidar caches selectivamente |
| `search_cache` crece sin límite | TTL por nivel + cleanup job documentado (aunque no implementado en 2b — Phase 3) |

## 10. Tiempo y costo estimado

- **Dev:** 2-3 semanas (~19 tasks × 1h promedio con subagent-driven workflow)
- **Calibración API:** ~$10-20 total (múltiples corridas end-to-end)
- **Runtime per query:**
  - Cache hit (N0): ~$0
  - N1 hit: ~$0.03-0.08 (solo extraction)
  - N2 hit: ~$0.15-0.30 (web_search + extraction + classify + review)
  - N3: ~$0.50-1.00 (intensive + extraction + classify + review)

## 11. Execution handoff

Siguiente paso: ejecutar `writing-plans` para convertir este design en un plan task-by-task (estilo Phase 2a `2026-04-17-phase2a-agents-calibration.md`) con pasos bite-sized para ejecución subagent-driven.
