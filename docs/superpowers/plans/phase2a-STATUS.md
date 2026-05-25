# Phase 2a — Status

**Completed:** 2026-04-18
**Tag:** `phase2a-complete` (moved to include calibration results + rules v3)
**Rules version shipped:** v3 (tercera iteración, calibrada contra validation_set)

## Criterios de éxito — cumplidos

- [x] `rules/vN.md` redactado con filosofía de Sabbi codificada (v1 → v2 → v3)
- [x] `poetry run python -m scraper.scripts.classify_one "X"` funciona end-to-end
- [x] `poetry run python -m scraper.scripts.calibrate` corre los 19 validation y reporta accuracy per-attribute
- [x] **Los 9 atributos ≥85% accuracy en validation_set** (min = 94.7%)
- [x] Taxonomy normalizer maneja las ~14 variantes documentadas + subyacentes + accent-insensitive moneda
- [x] Cost tracking funciona (cada run imprime total USD; runs típicos $1.7–2.1)
- [x] Prompt caching aplicado (cache hit después del primer producto: ~$0.03/llamada vs $0.23 primera)
- [x] 75 tests passing (unit + integration)
- [x] Orchestrator `decide_flag` con prioridad correcta
- [x] Mocked integration tests cubren classifier + reviewer sin pegar a LLM real

## Accuracy por atributo (rules v3 vs validation_set, 19 productos)

| Atributo | v1 | v2 | v3 |
|---|---|---|---|
| administrador | 100.0% | 100.0% | **100.0%** |
| clase_activo | 94.7% | 100.0% | **100.0%** |
| comision | 94.7% | 84.2% | **94.7%** |
| foco_geografico | 94.7% | 89.5% | **94.7%** |
| gestor | 100.0% | 100.0% | **100.0%** |
| liquidez | 100.0% | 100.0% | **100.0%** |
| minimo_inversion | 100.0% | 100.0% | **100.0%** |
| moneda | 100.0% | 89.5% | **100.0%** |
| subyacente | 84.2% | 89.5% | **100.0%** |
| **min** | 84.2 | 84.2 | **94.7** |

**Costo total de calibración:** ~$6 USD (3 corridas × ~$2). Tiempo de wall clock: ~5 min por corrida.

## Iteración de reglas — resumen

- **v1** (`41a2a28`): primer borrador basado en inspección manual de training_set. Min 84.2% en subyacente.
- **v2** (`db54585`): agregó convención ADR por market listing, USD money market split, Peruvian BVL tickers, Bloomberg US Aggregate = 100% IG. El BVL y Bloomberg funcionaron; ADR y money market rompieron. Min 84.2% (subió comision y bajó moneda).
- **v3** (`843bc60`): revirtió ADR (ahora por país del emisor: Alibaba → Emergentes ex-Perú, Petrobras → Latam ex-Perú) y eliminó split USD money market. `categorical_match` ahora accent-insensitive (arregló `dólares` vs `dolares`). Min 94.7%.

## Hallazgos de calibración

- **La variance run-a-run del LLM es ~5-10pp por atributo** con `temperature` omitido (Opus 4.7 / Sonnet 4.6 lo deprecaron). Varias corridas seguidas no son determinísticas en casos borderline.
- **Ground truth tiene inconsistencias por producto.** Ej. ADRs: Sabbi clasifica `foco_geografico` por emisor (Alibaba/BABA = Emergentes), pero `subyacente` de NYSE mega-caps lo bucketa como `US Large Cap`. Asimétrico por atributo.
- **Casos "sin comisión" (0.0 vs None)** siguen siendo sensibles a variance del LLM aun con prompt explícito.
- **Normalización a canónico (variantes → lista cerrada)** fue el mayor unlock: clase_activo pasó de 0% (raw string match) a 100% solo normalizando. Mismo patrón para subyacente y region.
- **Producto con clase_activo concatenada del seed** (ej. "Mercados publicos variable 62.44% ... Mercados publicos fijo") — flag de Phase 1 resuelto vía normalizer (termina en cualquiera de las 6 macro canónicas o se descarta).

## Commits (Phase 2a)

### Código (Tasks 1-13)
- `09139ae` refactor: logging_config, named Excel columns, mypy stubs
- `82e4b35` feat: taxonomy normalizer (variants → canonical with fuzzy fallback)
- `6f53910` feat: Anthropic client wrapper with cost tracking and retry
- `323ca6e` feat: agent types + orchestrator flag logic
- `41a2a28` feat: rules v1.md + bootstrap analyzer
- `b3635ed` feat: prompt builder (classifier + reviewer) with caching blocks
- `310dd82` feat: classifier agent (Claude Sonnet 4.6) with vocab normalization
- `35511d4` feat: reviewer agent (Claude Opus 4.7) with criticism prompt
- `82733c1` feat: accuracy metrics per attribute
- `934650b` feat: classify_one CLI + fix builder parents[3]→[4] bug
- `26b4d02` feat: calibrate CLI
- `33979d5` docs: initial phase2a-STATUS (pre-calibration)

### Fixes post-closure
- `9797373` fix: omit temperature param (deprecated in Opus 4.7 / Sonnet 4.6)
- `d2cf049` fix(calibrate): normalize ground truth to canonical before comparing
- `6f456d1` feat: subyacente normalizer + apply to gt + classifier output
- `5256a09` chore(calibrate): print gt vs predicted on per-product attribute miss
- `db54585` feat: rules/v2.md (ADR + BVL + Bloomberg IG + USD MM)
- `843bc60` feat(rules,accuracy): v3 revierte v2 ADR+USDMM; accent-insensitive moneda

## Queda para Phase 2b

- Extractor HTML (BeautifulSoup + Claude)
- Extractor PDF texto (pypdf + Claude)
- Extractor PDF vision (Claude vision para escaneados)
- CLI `extract_one` que toma URL/PDF y devuelve ficha estructurada

Con Phase 2a + 2b funcionando, Phase 3 es integrar ambos vía FastAPI.
