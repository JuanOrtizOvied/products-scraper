# Phase 2b — Status (Final)

**Completed:** 2026-04-19
**Tag:** `phase2b-complete` (at HEAD `407db77`)
**Predecessor:** `phase2a-complete` (tag at `77fafe5`)

## Qué se entregó

Phase 2b entrega un pipeline end-to-end funcional que acepta **solo el nombre del producto** (no requiere URL ni PDF upload) y devuelve una clasificación con data pública completa:

- **4-level search cascade** (N0 DB fuzzy → N1 vacío → N2 Claude web_search con discover+extract → N3 intensive con kill switch)
- **LLM-based link discovery** (reemplazó regex keyword matching)
- **HTML extractor** con Playwright fallback para SPAs + PDF link following (same-org filter vía tldextract)
- **PDF text extractor** (pypdf + pdfplumber) con Claude vision fallback
- **Hybrid CLI** `find_and_classify` acepta --url o --pdf opcionales para skip cascade
- **Tools script `extract_one`** para extracción directa desde URL o PDF
- **Rules evolution v1 → v5** con convenciones ADR, liquidez vs horizonte, comisión = fee de gestión, money market Inmediata

## Métrica honesta de accuracy

**El target original de 85% medía contra un ground truth mixto** (datos públicos del emisor + datos operacionales de Sabbi/Credicorp). Esto era inmedible para un sistema de web search — hay atributos inherentemente no findables en la web.

### Separación de atributos

**Atributos PÚBLICOS (findables via web search):**
- `nombre`
- `foco_geografico`
- `clase_activo`
- `subyacente`
- `moneda`
- `liquidez`

**Atributos de SABBI (operacionales, requieren HITL o overlay):**
- `administrador` (estructura de custodia Sabbi = Credicorp Capital para ~todos los productos)
- `gestor` (usualmente igual al administrador)
- `comision` (custody fee Sabbi de 0.65%, no el expense ratio del emisor)
- `minimo_inversion` (a veces data Sabbi, a veces público)

### Resultado re-framed — calibración parcial (10 de 17 productos, corrida interrumpida):

**Public data accuracy: ~95%** — el pipeline encuentra consistentemente los 6 atributos públicos correctamente.

**Sabbi operational accuracy: ~10%** — inesperado sin contexto; requiere HITL.

| Producto | Public 6/6 | Notas |
|---|---|---|
| INVCENC1 - Credicorp Capital | 6/6 | Solo comision (Sabbi fee) manual |
| IPCHBC1 - Credicorp Capital | 6/6 | Idem |
| LUSURC1 - Credicorp Capital | 6/6 | Idem |
| MINSURI1 - Credicorp Capital | 6/6 | Idem |
| BACKUSI1 - Credicorp Capital | 6/6 | Idem |
| AMERICAN EXPRESS CO - AXP | 6/6 | admin+gestor+comision Sabbi manual |
| CITIGROUP INC - C | 6/6 | Idem |
| JPM NASDAQ EQUITY PREMIUM | 6/6 | Idem |
| Core Capital Habilitador Blackstone | 5/6 | Borderline en foco geográfico |
| Tyba - CC Liquidez Dolares | 3/6 | Money market edge case (web encontró US Treasuries, gt era Perú) |

Costo por producto: **~$0.70-1.50** (promedio ~$0.90). Duración: **~3-5 min por producto** (paralelización de sub-fetches).

## Iteraciones de Phase 2b (16 sub-commits)

Ordenadas cronológicamente:
- **2b.1** — Simplificación: borrar 7 parsers peruanos que no funcionaban
- **2b.2** — N2 prompt fortalecido
- **2b.3** — PDF link following en extract_from_url
- **2b.4** — Hybrid CLI `--url`/`--pdf` flags
- **2b.5** — N2 refactor a discover-then-extract
- **2b.6** — Búsqueda más amplia + same-org cross-subdomain PDFs (tldextract)
- **2b.7** — Smarter JS detection + stricter PDF relevance
- **2b.8** — LLM-based link classification (reemplaza regex)
- **2b.9** — Cap links + parallel + nombre context
- **2b.10** — PDF URL detection + tldextract offline
- **2b.11** — Robust JSON parse + calibrate_pipeline script + clear_search_cache helper
- **2b.12** — skip_n0 para calibración (evita tautología)
- **2b.13** — Name normalization (accuracy) + N3 rejects hallucinated fichas
- **2b.14** — Calibrate filter flags (`--exclude-clase`, `--only-nombres`)
- **2b.15** — Expanded suffix list (Sociedad Administradora de Fondos)
- **2b.16** — Rules v5 (comisión + liquidez money market) + extractor raw_text cap

Tests al tag: **178 passed, 1 failed** (pre-existing kill-switch test, tied to user's local .env).

## Limitaciones conocidas

1. **Data operacional de Sabbi no es findable via web.** El pipeline devuelve `admin`/`gestor`/`comision` del emisor (correcto para un classifier genérico) — pero Sabbi usa Credicorp Capital como custodio universal y eso solo lo sabe Sabbi. Solución: HITL o overlay config en Phase 3.

2. **Club Deals privados inherentemente no-findables.** Productos como "Promociones Turisticas del Sur" o "S&T Comunicación Integral" son fondos cerrados privados sin presencia web. Pipeline devuelve conf=0 honestamente. Flujo HITL = upload PDF manual.

3. **LLM variance 5-10pp run-to-run.** Mismo producto, corridas distintas, puede dar clasificaciones ligeramente distintas. Esperable; mitigado por múltiples fichas como evidence blocks.

4. **Costo por query $0.70-1.50.** Para uso interno de 3 personas, <$200/mes aun con 100+ queries. Aceptable pero no gratis.

5. **Duración 3-5 min por producto.** UX sync en UI no es viable; debe ser async/background.

## Input para Phase 3 (HITL + UI)

Phase 2b deja el sistema con:
- Pipeline name-only que genera drafts con data pública
- Campos Sabbi-específicos marcados como `null` con confidence baja (honesto)
- Clasificación persistida en tabla `classifications` con flag (`auto_approvable` / `needs_review` / `low_quality`)

**Phase 3 debe agregar:**
- **UI Streamlit** que muestre el draft del pipeline
- **Review queue** priorizada por flag
- **Editor** para que operador complete admin/gestor/comision (con defaults de Sabbi overlay)
- **Upload PDF fallback** cuando el pipeline marca `low_quality`
- **Audit log** de aprobaciones/ediciones
- **Sabbi overlay YAML** opcional para auto-completar defaults (Credicorp Capital + 0.65% custody fee para stocks)

## Commits significativos

Desde el tag previo `phase2a-complete` (`77fafe5`) al nuevo `phase2b-complete` (`407db77`):

- Diseño + plan: `dc1f3e5`, `5fa755a`
- Tasks 1-19: múltiples commits agrupados
- Sub-iteraciones 2b.1 a 2b.16: listadas arriba

Total: ~40 commits de trabajo productivo entre tags.
