# Buscador / Clasificador automático de productos de inversión

**Fecha:** 2026-04-17
**Estado:** Diseño aprobado, pendiente de plan de implementación
**Autor:** Sabbi (informatica@ccastrovirreyna.com) + Claude

---

## 1. Contexto y problema

Actualmente mantenemos una base de datos de productos de inversión en Excel (`BD_Productos Sabbi.xlsx`, 136 productos) con una taxonomía propia: 6 clases de activo macro, ~30 subyacentes canónicos con score de performance, 5 regiones geográficas, y atributos como comisión, moneda, administrador, gestor, liquidez y mínimo de inversión.

Hoy clasificar un producto nuevo requiere:
1. Encontrar su ficha técnica manualmente (web, PDF, prospecto)
2. Leerla y extraer atributos
3. Mapear a nuestra taxonomía aplicando criterios propios (ej. "fondo cerrado con pocos inversionistas → Club deal, no Mercados Privados")

El objetivo es automatizar este proceso con un sistema robusto que:
- Busca el producto primero en nuestra BD interna
- Si no está, lo scrapea de la web (sitios conocidos → búsqueda general → Deep Research)
- Extrae atributos y los clasifica usando nuestra filosofía
- Si no encuentra nada, pide ficha técnica manual
- **Siempre pasa por validación humana** antes de entrar a la DB final (HITL mandatorio)
- Se audita de punta a punta, con reglas versionadas y confidence scores

Equipo: 3 usuarios. Local con SQLite primero, migración a server + PostgreSQL en producción sin refactor de código.

---

## 2. Alcance

**Dentro del alcance:**
- UI web (Streamlit) con 3 pantallas: búsqueda, cola de revisión, reglas/métricas
- Backend FastAPI + SQLAlchemy + Alembic
- Dos agentes LLM: Clasificador (Claude Sonnet 4.6) + Revisor (Claude Opus 4.7)
- Extractor de fichas técnicas (HTML, PDF texto, PDF imagen/escaneado vía Claude vision)
- Search cascade en 4 niveles: DB → targets conocidos → Tavily → OpenAI Deep Research
- Fallback manual con upload de PDF
- Calibración inicial contra train/validation split 80/20 estratificado
- Tests de regresión que bloquean cambios de reglas si bajan accuracy
- Audit log inmutable, reglas versionadas, confidence por atributo + global (umbral 90%)
- Cache de búsquedas, retry con backoff, circuit breaker, kill switches
- Backups automáticos (litestream → S3 o disco)
- Deployment local vía docker-compose, diseño listo para migrar a VPS/cloud

**Fuera del alcance (explícito):**
- Auto-actualización de reglas por el agente (siempre requiere aprobación humana)
- Entrenamiento/fine-tuning de modelos propios
- Formulario manual en lugar del upload de PDF (se decidió upload de PDF obligatorio en el fallback)
- Multi-tenant o auth empresarial (3 usuarios hardcodeados con bcrypt para la v1)
- Integraciones con Bloomberg/Refinitiv/otros data providers pagos
- Mobile app

---

## 3. Principios de diseño

1. **Nunca perder un producto.** Cualquier fallo técnico (timeout, API caída, PDF corrupto) resulta en el item entrando a una cola con contexto suficiente para reintentarlo, no se pierde silenciosamente.
2. **HITL mandatorio.** Ningún producto entra a la DB final sin aprobación humana. El agente solo decide qué tan rápido se puede aprobar (auto_approvable vs needs_review).
3. **Auditable de punta a punta.** Cada clasificación loguea: versión de reglas usada, reasoning del clasificador, veredicto del revisor, decisión humana, timestamp y actor.
4. **Diferencia modelos entre clasificador y revisor.** Sonnet clasifica, Opus revisa. Si ambos fueran idénticos, fallarían en los mismos casos.
5. **Separar extracción de clasificación.** El extractor dice "qué está en la ficha"; el clasificador dice "cómo lo categorizamos". Dos responsabilidades, dos componentes, dos puntos de debug.
6. **Vocabulario cerrado.** Las taxonomías son listas cerradas. El agente no puede inventar clases de activo ni subyacentes — solo usar las que existen. Prevención estructural de alucinaciones.
7. **Local-first, cloud-ready.** Todo funciona en una laptop sin conexión a server. Migración a producción = cambiar connection string.

---

## 4. Arquitectura

```
┌──────────────────────────────────────────────────────────┐
│                   STREAMLIT UI (3 users)                 │
│  [Buscar producto]  [Revisar pendientes]  [Reglas]       │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP
┌────────────────────────▼─────────────────────────────────┐
│                    FASTAPI BACKEND                       │
│  ┌────────────┬──────────────┬───────────┬───────────┐   │
│  │ Orquestador│ Clasificador │  Revisor  │ Extractor │   │
│  │            │ (Sonnet 4.6) │(Opus 4.7) │ (Sonnet)  │   │
│  └─────┬──────┴──────┬───────┴─────┬─────┴─────┬─────┘   │
│        │             │             │           │         │
│  ┌─────▼─────┐ ┌─────▼──────┐ ┌────▼─────┐ ┌───▼─────┐   │
│  │  Search   │ │  Scraper   │ │  Deep    │ │  PDF    │   │
│  │  cascade  │ │ (Playwright│ │ Research │ │ Reader  │   │
│  │           │ │ + Tavily)  │ │ (OpenAI) │ │(vision) │   │
│  └─────┬─────┘ └──────┬─────┘ └──────────┘ └─────────┘   │
└────────┼──────────────┼──────────────────────────────────┘
         │              │
┌────────▼──────────────▼──────────────────────────────────┐
│  SQLite (local) → PostgreSQL (prod)                      │
└──────────────────────────────────────────────────────────┘
```

### 4.1 Stack tecnológico

| Capa | Tecnología | Motivo |
|---|---|---|
| Frontend | Streamlit + streamlit-authenticator | Velocidad de build, Python puro, aceptable para equipo interno de 3 |
| Backend | FastAPI + SQLAlchemy + Alembic | Async, tipado, migraciones, portable SQLite → Postgres |
| DB local | SQLite | Cero config, un archivo |
| DB producción | PostgreSQL | Swap via env var `DATABASE_URL` |
| Clasificador | Claude Sonnet 4.6 | Rule-following, español, prompt caching |
| Revisor | Claude Opus 4.7 | Razonamiento crítico superior, diferencia al clasificador |
| Deep Research | OpenAI `o4-mini-deep-research` | Producto nativo con browsing agéntico |
| Extracción PDF/HTML | Claude Sonnet 4.6 (texto + vision) | Maneja PDFs escaneados |
| Búsqueda web rápida | Tavily API | Servicio dedicado, económico |
| Scraping dirigido | Playwright async | Sitios con JS (SMV, administradoras) |
| PDF parsing | pypdf + pdfplumber + Claude vision | Texto + tablas + imágenes |
| Tests | pytest + httpx_mock + responses | Unit + integration + regression |
| Logging | structlog (JSON) | Correlation IDs atravesando el stack |
| Backups | litestream | Replicación continua SQLite |
| Deployment | docker-compose + Caddy (prod) | Mismos contenedores en dev y prod |

---

## 5. Flujo principal (golden path)

1. Usuario ingresa nombre de producto en Streamlit
2. Backend busca en `products` con ILIKE + rapidfuzz threshold 85
3. **Si hit:** devolver producto, fin.
4. **Si miss:** arranca search cascade
5. Extractor convierte HTML/PDF crudo en "ficha estructurada" (texto + tablas)
6. Clasificador (Sonnet) asigna atributos con confidence por campo
7. Revisor (Opus) critica la clasificación, emite veredicto
8. Orquestador decide flag (`auto_approvable` | `needs_review` | `low_quality`)
9. Item entra a `review_queue`
10. Humano aprueba/edita/rechaza desde UI
11. Al aprobar: inserta en `products`, loguea en `audit_log` con rules_version

---

## 6. Search cascade

### Nivel 0 — DB local
Búsqueda exact + fuzzy (`rapidfuzz.fuzz.ratio` ≥85). Si hit, devolver producto existente.

### Nivel 1 — Targets conocidos (scraping directo)
Módulo Python por sitio, cada uno con selectores dedicados. Paralelos, timeout 30s.
- smv.gob.pe (SMV Perú)
- sbs.gob.pe
- credicorpcapital.com, bcpcapital.com
- corecapital.pe, sabbi.pe
- bvl.com.pe
- (extensible vía registro de parsers)

### Nivel 2 — Búsqueda web rápida (Tavily)
Query: `"{producto} ficha técnica OR fact sheet OR prospecto filetype:pdf"`.
Filtrar por dominios confiables, descargar top 3 candidatos. Timeout 15s.

### Nivel 3 — Deep Research (OpenAI)
Prompt específico pidiendo los 9 atributos con citas de fuente. 5-15 min, ~$2-5 USD por búsqueda. Job asíncrono, usuario puede cerrar la pestaña y volver. Timeout 20 min.

### Nivel 4 — Fallback manual
UI muestra botón "Subir PDF". Usuario sube ficha técnica. Va al Extractor (vision para escaneados) → Clasificador → Revisor.

**Caching:** `search_cache` indexado por `sha256(normalize(input_name))`. TTL por nivel: N1=7d, N2=30d, N3=90d.

**Resiliencia:** retry con backoff (tenacity, 3 intentos, 2/4/8s). Circuit breaker si una fuente falla >5 veces en 10 min, desactivada 15 min. Kill switch `SKIP_DEEP_RESEARCH=true` para controlar presupuesto.

---

## 7. Agentes LLM

### 7.1 Clasificador (Claude Sonnet 4.6)

System prompt estructurado en bloques, todos cacheados excepto el input del caso:

**Bloque 1 — Filosofía de clasificación (reglas en Markdown).** Construidas en la calibración inicial a partir de los 110 productos de training_set. Ejemplos:
- "Si el producto es fondo cerrado con pocos inversionistas (<50) y subyacente es real estate → `clase_activo = Club deals`, no Mercados Privados."
- "Si el subyacente es un ETF que replica S&P 500 → `US Large Cap`, no Mercados Emergentes ni Desarrollados ex-US."

**Bloque 2 — Taxonomías canónicas.** Listas cerradas:
- 6 clases de activo macro
- ~30 subyacentes canónicos con su clase macro asociada
- 5 regiones geográficas

**Bloque 3 — Few-shot examples.** Los 110 productos del training_set formateados como pares `{input_ficha_estructurada, expected_output}` usando exactamente el mismo schema JSON que el output del clasificador. El agente aprende por analogía directa.

**Bloque 4 — Input del caso** (no cacheado).

**Output (JSON estructurado):**
```json
{
  "producto": "...",
  "foco_geografico": {
    "value": {"Peru": 65, "USA": 35},
    "confidence": 0.93,
    "reasoning": "La ficha dice 'Perú 65%, USA 35%' explícitamente",
    "rule_applied": "regla_geografica_explicita"
  },
  "clase_activo": { "value": {...}, "confidence": 0.88, "reasoning": "...", "rule_applied": "..." },
  "subyacente": { ... },
  "comision": { ... },
  "moneda": { ... },
  "administrador": { ... },
  "gestor": { ... },
  "liquidez": { ... },
  "minimo_inversion": { ... },
  "global_confidence": 0.88,
  "unknowns": ["no encontré la comisión en la ficha"]
}
```

Cada atributo lleva `confidence` + `reasoning` + `rule_applied`. El agente solo puede usar valores del vocabulario canónico (validación estructural post-response).

### 7.2 Revisor (Claude Opus 4.7)

Recibe: ficha técnica original + output del clasificador + reglas/taxonomías.

**Job: criticar, no re-clasificar.** Verifica:
1. ¿Cada `rule_applied` existe y aplica al caso?
2. ¿Cada `value` usa vocabulario canónico?
3. ¿El `reasoning` es consistente con la ficha?
4. ¿Porcentajes suman 100% donde corresponde?
5. ¿Hay inconsistencias internas?

**Output:**
```json
{
  "veredicto": "agree|disagree|partial",
  "attribute_reviews": {
    "foco_geografico": {"verdict": "agree", "notes": ""},
    "clase_activo": {"verdict": "disagree",
                     "reason": "El clasificador dijo Mercados Privados, pero la estructura indica Club deal (fondo cerrado, <50 inversionistas)",
                     "suggested_value": {"Club deals": 100}},
    ...
  },
  "global_verdict": "needs_review",
  "reviewer_confidence": 0.92
}
```

### 7.3 Orquestador (lógica de decisión)

Evaluada en orden de prioridad (if/elif), la primera que matchea gana:

```
1. si global_confidence < 0.70:
    → flag = "low_quality"  (peor escenario, sugerir Deep Research o manual upload)

2. sino si revisor.veredicto == "disagree" en algún atributo:
    → flag = "needs_review"  (muestra conflicto al humano)

3. sino si min(confidence por atributo) < 0.90:
    → flag = "needs_review"  (muestra atributo dudoso)

4. sino (revisor agree + todos los atributos >= 0.90 + global >= 0.70):
    → flag = "auto_approvable"
```

Prioridad: `low_quality` > `needs_review` > `auto_approvable`. Si un item cae en low_quality, nunca se etiqueta también como needs_review.

SIEMPRE termina en humano (HITL mandatorio). El flag solo indica qué tan rápido el humano puede aprobar.

### 7.4 Extractor

Recibe HTML o PDF, devuelve ficha estructurada sin clasificar.
- HTML → BeautifulSoup + Claude (resume y extrae campos relevantes)
- PDF texto → pypdf + Claude
- PDF escaneado/imagen → Claude vision directamente sobre las páginas
- Tablas en PDF → pdfplumber

No clasifica, solo extrae. Separación de responsabilidades crítica para debuggability.

---

## 8. Calibración inicial (dev-time, one-time)

1. Split estratificado 80/20 sobre los 136 productos → ~110 training / ~26 validation.
   - Estratificación por **clase de activo macro dominante** (la clase con mayor % en cada producto). Así ambos sets contienen productos de las 6 clases macro proporcionalmente.
   - Productos con data incompleta (NaN en la hoja Base) se excluyen del split hasta que tengan datos completos.
2. Tú (Sabbi) + Claude redactan `rules/v1.md` a partir de los 110 productos training.
3. Ejecutar clasificador + revisor sobre los 26 de validation.
4. Medir accuracy por atributo contra ground truth:
   - Campos categóricos (moneda, administrador, liquidez, etc.): match exacto.
   - Campos de porcentajes (foco geográfico, clase activo, subyacentes): correcto si **cada región/clase** del ground truth existe en el output **y** su % está dentro de ±5 puntos porcentuales.
   - Campos numéricos (comisión, mínimo inversión): correcto si ±5% relativo del valor ground truth.
5. Discrepancias → refinar reglas manualmente → v2.
6. Repetir hasta alcanzar ≥85% por atributo en validation_set.
7. Congelar como versión de producción, registrar `rules_versions.validation_accuracy`.

Esta calibración es **gate** para salir a producción. Sin accuracy >=85%, no se despliega.

---

## 9. Modelo de datos

```sql
products (
  id, nombre, foco_geografico (JSON), clase_activo (JSON),
  subyacentes (JSON), comision, moneda, administrador, gestor,
  liquidez, minimo_inversion, currency_min,
  source_url, source_type (scraped|pdf|manual|excel_seed),
  created_at, updated_at, created_by, status (active|deprecated)
)

training_set (product_id, split='training')
validation_set (product_id, split='validation')
-- classified_count y correct_count viven en rules_versions.validation_accuracy
-- (JSON con accuracy por atributo y total, se actualiza cada vez que se corre
--  el regression test contra esa versión de reglas)

rules_versions (
  version, content_md, examples_json,
  created_at, created_by, notes,
  validation_accuracy
)

classifications (
  id, product_name_input, rules_version_used,
  classifier_output (JSON), reviewer_output (JSON),
  global_confidence, per_attribute_confidence (JSON),
  final_status (auto_approved|needs_review|rejected|pending_human),
  source_used (db|scraper|tavily|deep_research|manual_pdf),
  duration_ms, cost_usd, created_at
)

review_queue (
  id, classification_id, assigned_to, priority,
  human_decision (approve|edit|reject), human_notes,
  final_product_id, resolved_at
)

audit_log (
  id, event_type, actor (user|classifier|reviewer|scraper),
  entity_type, entity_id, before_state (JSON), after_state (JSON),
  timestamp
)
-- Append-only: nunca UPDATE, nunca DELETE.

search_cache (
  query_hash, query_text, source (tavily|deep_research|scraper),
  response (JSON), fetched_at, ttl_days
)

uploaded_documents (
  id, product_name, file_path, mime_type, uploaded_by,
  ocr_text, extraction_result (JSON), uploaded_at
)

users (id, email, name, role)  -- 3 usuarios
```

**Taxonomías de referencia** (tablas propias, versionadas junto con `rules_versions`):
- `asset_classes` — las 6 macro
- `canonical_assets` — ~30 subyacentes + score + clase macro
- `geographic_regions` — 5 regiones + benchmark weight

---

## 10. UI (Streamlit)

### Pantalla 1 — Buscar producto
Input de texto + botón Buscar. Al ejecutar, muestra origen del dato (DB | Scraper | Tavily | Deep Research), confianza global, tabla de atributos con confidence individual, reasoning del clasificador, veredicto del revisor, botones "Enviar a revisión" / "Subir ficha PDF".

Si Deep Research está corriendo: progress bar + "puedes cerrar esta pestaña, te avisamos cuando esté listo". Job asíncrono en backend, status polling.

### Pantalla 2 — Cola de revisión
Tabla filtrable por flag / asignado a / fecha. Click en item abre vista detalle:
- Columna izquierda: atributos editables
- Columna derecha: ficha técnica original (PDF viewer o texto scraped)
- Cada atributo muestra confidence + reasoning + regla aplicada + veredicto del revisor
- Botones: Aprobar / Editar y aprobar / Rechazar

Al editar un atributo → marca como "candidato a ejemplo futuro" para considerar en próxima versión de reglas.

### Pantalla 3 — Reglas + métricas
Tabs:
- **Reglas actuales:** markdown renderizado, read-only. Botón "proponer cambio" crea borrador (nueva versión pendiente de aprobación).
- **Versiones:** diff entre versiones, accuracy de cada una sobre validation_set.
- **Métricas:** accuracy global + por atributo, throughput, tasa auto-aprobables, costo acumulado LLM+Tavily, tiempo promedio por nivel de cascada, top 10 discrepancias clasificador/revisor recurrentes.

**Auth:** streamlit-authenticator con bcrypt + 3 usuarios hardcodeados en config. Migrar a OAuth/SSO en producción.

---

## 11. Robustez operativa

### 11.1 Manejo de errores

| Falla | Comportamiento |
|---|---|
| Claude API 500 | Retry exponencial (tenacity 3 intentos). Si agota, marca como `failed_llm` y va a cola manual |
| Playwright timeout | Saltar al siguiente nivel de cascada |
| Tavily rate limit | Circuit breaker 15 min, saltar al siguiente nivel |
| Deep Research timeout (>20 min) | Cancelar, marcar `deep_research_failed`, ofrecer upload manual |
| PDF corrupto | Mensaje claro al usuario, guardar en `failed_uploads/` para debug |
| DB lock SQLite | Retry con `SQLALCHEMY_POOL_RECYCLE`, fallback read-only si persiste |
| Revisor discrepa del clasificador | NO es error — es el flujo esperado, va a `review_queue needs_review` |

### 11.2 Logging y observabilidad

- `structlog` JSON logs, `correlation_id` atraviesa UI → backend → agentes → DB → audit
- Vista `metrics_daily` agrega classifications por día/status/cost (no Prometheus todavía, overkill para 3 users)
- Alertas diarias por email si:
  - accuracy de validation_set baja >5pp respecto de la versión anterior
  - costo diario > `ALERT_COST_DAILY_USD` (default: $20)
  - items sin asignar en review_queue con antigüedad >48h

### 11.3 Config y secrets
- `.env` local + `.env.example` versionado (sin secrets)
- Secrets: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, `JWT_SECRET`
- `config.yaml` versionado con thresholds (confidence, timeouts, TTLs), swappeable por env

### 11.4 Backups
- SQLite: litestream replica continua a S3 o disco local
- Postgres (futuro): pg_dump diario + WAL archiving

---

## 12. Tests

### Unit tests
- Extractores (HTML, PDF texto, PDF escaneado) con fixtures de fichas reales
- Parsers de porcentajes ("Perú 65%, USA 35%" → `{"Peru": 65, "USA": 35}`)
- Validadores de taxonomía (rechazan valores no canónicos)
- Lógica del orquestador (flags de review_queue correctos)

### Integration tests
- Claude/OpenAI/Tavily mockeados con `httpx_mock` y `responses`
- Corren en CI, no pagan APIs

### Regression tests (el crítico)
```python
def test_validation_accuracy_per_attribute():
    results = classify_all(validation_set)
    for attr in ['foco_geografico', 'clase_activo', 'subyacente', ...]:
        accuracy = compare(results[attr], ground_truth[attr])
        assert accuracy >= 0.85, f"{attr} bajó de 85%"
```

Corre cada vez que cambian las reglas. Si una versión nueva baja la accuracy por debajo del threshold, falla el test y no se promueve a producción.

---

## 13. Deployment

### Local (dev)
`docker-compose up` → contenedores: fastapi, streamlit, sqlite volume, litestream sidecar.

### Producción (futuro)
Mismo docker-compose en VPS (DigitalOcean / Hetzner / AWS Lightsail).
- Swap SQLite → Postgres cambiando `DATABASE_URL`
- Caddy como reverse proxy con HTTPS automático
- litestream → pg_dump + WAL archiving
- Migrar streamlit-authenticator → OAuth/SSO cuando haga falta

Diseño apunta a que migrar sea solo variables de entorno + levantar el server. Sin refactor de código de aplicación.

---

## 14. Estructura de repositorio

```
scraper/
├── backend/
│   ├── agents/          (classifier, reviewer, extractor)
│   ├── search/          (cascade, playwright targets, tavily, deep_research)
│   ├── db/              (models, migrations via alembic)
│   ├── api/             (FastAPI routes)
│   ├── orchestrator.py
│   └── config.py
├── frontend/
│   └── streamlit_app.py
├── rules/
│   ├── v1.md            (reglas iniciales)
│   ├── v2.md
│   └── taxonomies.yaml  (6 clases, 30 subyacentes, 5 regiones)
├── tests/
│   ├── unit/
│   ├── integration/
│   └── regression/      (contra validation_set)
├── scripts/
│   ├── seed_from_excel.py       (importa las 136 filas del Excel)
│   ├── split_train_validation.py (stratified 110/26)
│   └── calibrate_rules.py       (loop iterativo v1→v2→...)
├── data/
│   ├── local.db
│   └── uploads/
├── docker-compose.yml
├── .env.example
└── pyproject.toml
```

---

## 15. Criterios de éxito

El sistema está listo para producción cuando:

1. Accuracy del clasificador ≥85% por atributo en validation_set (26 productos)
2. Revisor detecta al menos 80% de los errores conocidos (inyectamos productos mal clasificados a propósito)
3. Golden path (DB hit) responde <1 segundo
4. Nivel 1-2 de cascada responde <60 segundos
5. Nivel 3 (Deep Research) completa dentro de 20 minutos o falla graceful
6. Audit log captura el 100% de eventos (test de integridad)
7. Regression tests pasan verde en CI
8. Los 3 usuarios pueden autenticarse y clasificar un producto end-to-end sin errores
9. Upload de PDF funciona con PDFs texto y escaneados
10. Costo promedio por producto clasificado ≤ $0.50 USD (excluyendo casos que escalan a Deep Research)

---

## 16. Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Deep Research lento bloquea UX | Alta | Medio | Job asíncrono, usuario puede cerrar pestaña |
| Costo de LLMs se dispara | Media | Alto | Cache agresivo, kill switch, dashboard de costo diario |
| Agente alucina subyacentes no canónicos | Media | Alto | Vocabulario cerrado + validación post-response |
| Reglas v_n+1 bajan accuracy | Media | Alto | Regression test bloquea promoción |
| Revisor "colude" con clasificador | Baja | Alto | Modelos diferentes (Sonnet vs Opus) |
| PDF escaneado ilegible | Media | Medio | Claude vision como fallback + cola manual |
| SQLite lock en uso concurrente (3 usuarios + Deep Research async) | Media | Medio | Pool recycle + WAL mode + fallback read-only. Si aparece en la primera semana, migración temprana a Postgres antes de producción |
| Humano aprueba sin revisar bien | Media | Alto | UI obliga a confirmar diff, audit log expone quién aprobó qué |
| Cambio en estructura de site scrapeado | Alta | Bajo | Parsers dedicados, alertas de regresión, fallback a Tavily |

---

## 17. Próximos pasos

1. Usuario revisa este spec y aprueba o solicita cambios
2. Transición a `writing-plans` para generar plan de implementación paso a paso
3. Ejecutar el plan con `executing-plans` o `subagent-driven-development`
