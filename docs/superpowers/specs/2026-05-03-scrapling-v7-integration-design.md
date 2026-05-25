# Scrapling Integration + Rules v7 + Calibration Benchmark

**Fecha:** 2026-05-03
**Autor:** Sabbi + Claude
**Status:** Aprobado, pendiente implementación
**Base:** Phase 4 (post source traceability v6)

---

## Motivación

El pipeline actual usa httpx + Playwright para fetching. Esto falla silenciosamente en sitios con Cloudflare Turnstile u otras protecciones anti-bot, resultando en fichas vacías y classifications con `low_quality`. Scrapling (github.com/D4Vinci/Scrapling) ofrece StealthyFetcher con bypass anti-bot out-of-the-box, adaptive CSS selectors que sobreviven rediseños, y un MCP server que permite a Claude controlar el scraping directamente.

---

## Objetivos

1. **Anti-bot bypass**: StealthyFetcher reemplaza httpx + Playwright para obtener contenido de sitios protegidos
2. **Mejor extracción**: más contenido fetcheado → más datos para el clasificador → mayor confidence
3. **Claude con scraping directo**: Level 3 intensive gana acceso a Scrapling MCP como tool
4. **Benchmark cuantitativo**: comparar v6 (legacy fetcher) vs v7 (Scrapling) con el validation set de 19 productos
5. **Rules v7**: reglas que aprovechan el mejor scraping (retry stealth, calibración obligatoria)

---

## Diseño Técnico

### 1. Reemplazo de Fetcher (`src/scraper/extract/fetch.py`)

#### Feature flag

Variable de entorno `FETCHER_BACKEND` con dos valores:
- `legacy` — httpx + Playwright (comportamiento actual, default durante transición)
- `scrapling` — StealthyFetcher + Fetcher de Scrapling

Se lee en `src/scraper/config.py` como campo del Settings model:

```python
fetcher_backend: str = "scrapling"  # "legacy" | "scrapling"
```

#### Implementación Scrapling

Reemplazar las 3 funciones actuales en `fetch.py`:

**`fetch_url(url) → str`** (HTML):
```python
# Legacy: httpx.AsyncClient + retry
# Scrapling: StealthyFetcher con anti-bot bypass
from scrapling.fetchers import StealthyFetcher

page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
html = page.html  # o page.prettify() para HTML limpio
```

**`fetch_url_bytes(url) → bytes`** (PDFs):
```python
# Legacy: httpx get con .content
# Scrapling: Fetcher básico (no necesita stealth para PDFs)
from scrapling.fetchers import Fetcher

response = Fetcher.get(url)
return response.content  # bytes crudos
```

**`fetch_with_playwright(url) → str`** → eliminada:
- StealthyFetcher maneja JS rendering internamente
- La heurística `is_js_rendered()` ya no es necesaria
- Se mantiene como fallback interno de Scrapling

#### Session reuse para multi-fetch

Cuando el pipeline fetchea múltiples URLs del mismo dominio (ej: en `extract_from_url` con link following), usar sessions:

```python
from scrapling.fetchers import AsyncStealthySession

async with AsyncStealthySession(headless=True) as session:
    results = await asyncio.gather(*[session.fetch(url) for url in urls])
```

Esto reemplaza la lógica actual de `asyncio.gather` con httpx requests individuales.

#### Backward compatibility

- `is_js_rendered()` se mantiene como función pero no se usa en el path Scrapling
- `FetchError` sigue siendo la excepción custom — se wrappea sobre errores de Scrapling
- El flag `FETCHER_BACKEND=legacy` permite revertir sin cambiar código

### 2. Adaptive Selectors para Level 1 (segundo paso)

Hoy `src/scraper/search/level1_scrapers/registry.py` tiene `TARGETS = []`. Con Scrapling, se pueden re-activar scrapers para administradoras conocidas:

```python
class CredicorpParser:
    domain = "credicorpcapital.com"
    
    async def parse_ficha(self, url, llm):
        page = StealthyFetcher.fetch(url, headless=True)
        # Primera vez: guarda fingerprint de selectors
        ficha_data = page.css('.fund-details', auto_save=True)
        # Próximas veces: re-localiza si el sitio cambió
        ficha_data = page.css('.fund-details', adaptive=True)
```

Esto es un paso posterior — no parte del MVP de esta integración. Se documenta aquí como roadmap.

### 3. Scrapling MCP para Claude Level 3

#### Arquitectura

Scrapling MCP corre como servicio HTTP local:

```bash
scrapling mcp --http --host 127.0.0.1 --port 8765
```

Se configura como MCP server en `.claude/settings.local.json` o el entorno de Claude Code.

#### Integración en Level 3

`level3_intensive.py` hoy usa solo `web_search` tool. Con Scrapling MCP, Claude gana herramientas adicionales:

| Tool MCP | Uso en Level 3 |
|----------|----------------|
| `stealthy_fetch(url)` | Fetchear página protegida y ver contenido |
| `bulk_stealthy_fetch(urls)` | Fetchear múltiples URLs en paralelo |
| `screenshot(session_id)` | Capturar screenshot para vision analysis |
| `open_session()` | Navegar sitio multi-página (buscador interno) |
| `close_session(session_id)` | Liberar recursos del browser |

Claude decide cuándo usar cada tool basándose en el contexto. El prompt de Level 3 se actualiza para informar a Claude de las herramientas disponibles.

#### Cuándo se usa cada fetcher

| Contexto | Fetcher |
|----------|---------|
| Pipeline automático (Level 0-2, worker) | Scrapling librería directa (rápido, sin overhead de red) |
| Level 3 intensive (Claude iterando) | Scrapling MCP (Claude controla qué y cómo fetchear) |
| Debug / shell interactivo | Scrapling MCP o CLI (`scrapling shell`) |

### 4. Rules v7

Archivo: `rules/v7.md`

Cambios sobre v6:

#### Reglas nuevas — Fetching Mejorado

- **R-FETCH-1**: Si el primer intento de fetch devuelve contenido vacío o error de protección, re-intentar automáticamente con StealthyFetcher antes de marcar como `low_quality`.
- **R-FETCH-2**: Documentos que antes se clasificaban con `confidence=0.0` por falta de acceso al contenido deben re-intentarse con stealth. Solo marcar `confidence=0.0` si el stealth fetch también falla.
- **R-FETCH-3**: Cuando Scrapling obtiene más contenido que el fetch básico (medido en chars de raw_text), usar la versión con más contenido como fuente primaria.

#### Reglas de calibración

- **R-CAL-1**: Todo cambio de fetcher o reglas debe ir acompañado de un run de `calibrate_pipeline.py` sobre el validation set completo. El reporte debe mostrar delta por atributo vs la versión anterior.
- **R-CAL-2**: Un cambio se considera mejora solo si: (a) ningún atributo baja más de 2pp, Y (b) al menos un atributo sube más de 3pp, O (c) el promedio global sube más de 1pp.

#### Ajustes a reglas v6 existentes

Todas las reglas de v6 (trazabilidad R-SRC, prioridad R-PRI, conflictos R-CON) se mantienen sin cambios. v7 es aditiva sobre v6.

### 5. Benchmark: Calibración Comparativa

#### Feature flag para A/B

```bash
# Run 1: baseline v6 con legacy fetcher
FETCHER_BACKEND=legacy poetry run python -m scraper.scripts.calibrate_pipeline --rules rules/v6.md --output results_v6.json

# Run 2: v7 con Scrapling
FETCHER_BACKEND=scrapling poetry run python -m scraper.scripts.calibrate_pipeline --rules rules/v7.md --output results_v7.json

# Run 3: comparación
poetry run python -m scraper.scripts.compare_calibrations results_v6.json results_v7.json
```

#### Nuevo script: `compare_calibrations.py`

Toma dos archivos de resultados y genera tabla comparativa:

```
=== CALIBRATION COMPARISON v6 (legacy) vs v7 (scrapling) ===

Attribute         | v6 acc  | v7 acc  | Δ      | Status
administrador     | 100.0%  | 100.0%  | +0.0   | —
comision          | 89.5%   | 94.7%   | +5.2   | ✓ improved
foco_geografico   | 94.7%   | 100.0%  | +5.3   | ✓ improved
...

Global confidence | 0.82    | 0.89    | +0.07  | ✓ improved
Low quality rate  | 15.8%   | 5.3%    | -10.5  | ✓ improved
Sources found avg | 1.2     | 2.1     | +0.9   | ✓ improved
Avg cost USD      | $0.04   | $0.06   | +$0.02 | ⚠ higher
Avg duration ms   | 12,000  | 18,000  | +6,000 | ⚠ slower
```

#### Métricas capturadas

| Métrica | Qué mide |
|---------|----------|
| Accuracy por atributo (9 campos) | ¿Scrapling mejora la clasificación? |
| Global confidence promedio | ¿Más datos → más confianza? |
| Tasa de `low_quality` flags | ¿Menos productos sin datos? |
| Fuentes encontradas promedio | ¿Scrapling encuentra más fichas/PDFs? |
| Conflictos detectados promedio | ¿Más fuentes → más conflictos? |
| Costo USD promedio por producto | ¿Más texto → más tokens → más costo? |
| Duración promedio por producto | ¿StealthyFetcher más lento que httpx? |

---

## Dependencias

### Agregar

```
scrapling[all]   # Incluye fetchers, MCP server, shell, browsers
```

### Posiblemente remover (después de validar)

```
httpx            # Reemplazado por Scrapling Fetcher (mantener si algo más lo usa)
playwright       # Reemplazado por Scrapling StealthyFetcher/DynamicFetcher
```

### Instalación post-install

```bash
poetry add "scrapling[all]"
scrapling install          # Instala browsers y dependencias del sistema
```

---

## Archivos Impactados

| Capa | Archivos | Cambio |
|------|----------|--------|
| Config | `src/scraper/config.py` | Agregar `fetcher_backend` field |
| Fetcher | `src/scraper/extract/fetch.py` | Rewrite con Scrapling + feature flag |
| HTML extract | `src/scraper/extract/html.py` | Usar session-based fetching para link following |
| Level 3 | `src/scraper/search/level3_intensive.py` | Actualizar prompt con herramientas MCP disponibles |
| Settings | `.claude/settings.local.json` | Agregar Scrapling MCP server config |
| Rules | `rules/v7.md` | Crear con reglas R-FETCH + R-CAL |
| Scripts | `src/scraper/scripts/compare_calibrations.py` | Crear: comparación de resultados |
| Scripts | `src/scraper/scripts/calibrate_pipeline.py` | Agregar `--output` flag para JSON |
| Dependencies | `pyproject.toml` | Agregar scrapling[all] |
| Tests | `tests/unit/test_fetch_scrapling.py` | Tests para nuevo fetcher |
| Tests | `tests/unit/test_compare_calibrations.py` | Tests para script de comparación |

---

## Migración y Rollback

- Feature flag `FETCHER_BACKEND=legacy` permite revertir instantáneamente sin deploy
- httpx y playwright se mantienen como dependencias hasta que el benchmark confirme que Scrapling es superior
- Si Scrapling falla en producción, cambiar el env var es suficiente
- El MCP server es opcional — Level 3 sigue funcionando con solo `web_search` si MCP no está corriendo

---

## Fases de implementación

1. **Fase A — Fetcher swap**: Instalar Scrapling, rewrite fetch.py con feature flag, tests
2. **Fase B — Rules v7**: Crear rules/v7.md, actualizar calibrate_pipeline con --output
3. **Fase C — Benchmark**: Correr calibración v6 vs v7, crear compare_calibrations.py
4. **Fase D — MCP Level 3**: Configurar Scrapling MCP, actualizar Level 3 prompt
5. **Fase E — Validación**: Correr benchmark completo, decidir si Scrapling es default
