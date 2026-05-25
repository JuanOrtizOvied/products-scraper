# Phase 3 — HITL UI + Review Workflow — Design

**Fecha:** 2026-04-19
**Autor:** Sabbi + Claude
**Status:** Design aprobado, pendiente de plan detallado
**Predecesor:** Phase 2b (`phase2b-complete` tag `afa8fa4`) — pipeline name-only web search

## 1. Goal

Construir la capa HITL (Human In The Loop) sobre el pipeline de Phase 2b. Permitir a los 3 operadores de Sabbi:

1. Subir batches de productos (CSV) y hacer que el pipeline los clasifique en background
2. Clasificar productos individuales on-demand
3. Revisar, editar y aprobar clasificaciones antes de persistirlas en `products` table
4. Subir PDFs como fallback cuando el pipeline no encuentra data online
5. Aplicar defaults operacionales de Sabbi (admin / gestor / custody fee) via overlay YAML

**Deliverable clave:** herramienta Streamlit local que cubre el ciclo completo "nombre(s) → clasificación pipeline → review humano → approved en DB" para los operadores de Sabbi.

## 2. Non-goals

Explícitamente fuera de Phase 3:

- ❌ **Entry C (cliente self-service)** — diferido a Phase 4. Requiere auth + cloud deployment
- ❌ **FastAPI backend** — Streamlit lee DB directo; no API separada
- ❌ **Autenticación / users / roles** — local = implicit single user. Se agrega al migrar a server interno (Phase 3.5)
- ❌ **Notifications por email / Slack** — operator refresca UI
- ❌ **WebSocket / realtime** — polling cada 3s cubre UX
- ❌ **Dashboard analytics avanzadas** — mostrar total cost mensual es suficiente MVP
- ❌ **Auto-approve de `auto_approvable`** — todo pasa por queue para MVP; agregar después si se valida
- ❌ **Multi-broker overlay complex** — MVP solo default Credicorp; más brokers via edits al YAML
- ❌ **Integraciones externas** (CRM, portfolio management, etc.)

## 3. Arquitectura

### 3.1 Componentes

```
┌─────────────────────────────────────────────────────────┐
│                    Streamlit UI                          │
│  (corre local: `poetry run streamlit run src/scraper/ui/app.py`) │
├──────────────┬──────────────┬──────────────┬───────────┤
│  Upload CSV  │ Single input │ Review Queue │  Settings │
│  (entry A)   │  (entry B)   │   (core)     │  (config) │
└──────┬───────┴──────┬───────┴──────┬───────┴───────────┘
       │              │              │
       ▼              ▼              ▼
       ────────┬──────────────────┬──────
               │                  │
               ▼                  ▼
    ┌──────────────────┐   ┌──────────────────┐
    │  job_queue DB    │   │  products table  │
    │  (pending/in_    │   │  (approved final)│
    │   progress/done) │   │                  │
    └────────┬─────────┘   └──────────────────┘
             │                      ▲
             ▼                      │ approve event
    ┌──────────────────────────────┤
    │  Worker script               │
    │  `scraper.scripts.worker`    │
    │  corre en terminal aparte:   │
    │    - Claim 3-5 pending       │
    │    - find_and_classify       │
    │    - Save classification +   │
    │      review_queue entry      │
    │    - Mark done               │
    └──────────────────────────────┘
```

### 3.2 Entry points (por prioridad de implementación)

| Entry | Modo | Flujo | Timeline |
|---|---|---|---|
| **A** | Batch CSV upload | CSV → N jobs en queue → worker procesa async → review queue | Phase 3 MVP |
| **B** | Single input en UI | Tipea nombre (+ opcional URL/PDF) → 1 job en queue → review | Phase 3 MVP |
| **C** | Self-service cliente | Form público en server → auth → pipeline → HITL interno | Phase 4 |

### 3.3 Flujo de review (todos los productos)

```
1. Pipeline termina → guarda en classifications table + crea review_queue entry
2. Operator abre Review Queue tab en Streamlit
3. Lista ordenada por priority: low_quality primero, needs_review, auto_approvable
4. Click → review detail:
    - Pipeline pobló 6 atributos públicos (nombre, foco, clase, subyacente, moneda, liquidez)
    - Sabbi overlay pre-llena admin/gestor/comision con defaults (Credicorp + 0.65%)
    - Operator edita inline si hace falta
    - Para low_quality + sin PDF: botón "Subir PDF" → re-procesa ese producto
5. Click "Aprobar":
    - INSERT en products table (valores editados)
    - INSERT audit_log (actor, before=classification_output, after=product_row)
    - UPDATE review_queue.human_decision="approved", final_product_id=products.id
    - UPDATE job_queue.status="approved"
```

## 4. Data model

### 4.1 Tablas existentes (Phase 1 — se reutilizan)

- **`products`** → clasificaciones aprobadas (estado final)
- **`classifications`** → raw output del pipeline (draft pre-approval)
- **`review_queue`** → classification_id + flag + human_decision
- **`audit_log`** → eventos de aprobación/edición (who/when/before/after)
- **`uploaded_documents`** → PDFs subidos via UI
- **`rules_versions`** → snapshot de rules/v5.md en DB
- **`search_cache`** → cache de cascade (Phase 2b)
- **`users`** → para cuando migre a server (MVP: implícito)

### 4.2 Tabla nueva: `job_queue`

```python
class JobQueue(Base):
    __tablename__ = "job_queue"
    id: Mapped[int] = primary_key
    batch_id: Mapped[str | None]            # UUID que agrupa jobs de un CSV
    nombre: Mapped[str]                     # producto a clasificar
    pdf_path: Mapped[str | None]            # si viene del CSV column
    url: Mapped[str | None]                 # si viene de single input con URL
    status: Mapped[str]                     # "pending" | "in_progress" | "done"
                                            # | "failed" | "approved" | "rejected"
    classification_id: Mapped[int | None]   # FK → classifications.id (set on done)
    error: Mapped[str | None]               # stacktrace if failed
    created_at: Mapped[datetime]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    created_by: Mapped[int | None]          # FK → users.id (nullable pre-auth)
```

**Alembic migration:** crear tabla `job_queue` + indices en `(status, created_at)` para el worker query.

### 4.3 Flujo de estados en DB

```
CSV upload (entry A)
   ↓
job_queue: N rows con batch_id=<uuid>, status="pending"
   ↓
Worker claim (UPDATE status="in_progress", started_at=NOW())
   ↓
Worker llama find_and_classify
   ↓
classifications: INSERT output del pipeline
   ↓
review_queue: INSERT (classification_id, flag, priority)
   ↓
job_queue: UPDATE status="done", classification_id=<id>, completed_at=NOW()
   ↓
Operator revisa desde UI → aprueba
   ↓
products: INSERT con valores editados
audit_log: INSERT event=approval, before=classifier_output, after=product
review_queue: UPDATE human_decision="approved", final_product_id=<id>
job_queue: UPDATE status="approved"
```

## 5. Sabbi overlay YAML

Archivo `config/sabbi_overlay.yaml` en repo root:

```yaml
# Sabbi operational defaults — atributos que el pipeline NO encuentra en web
# (son estructura de custodia de Sabbi, no data del emisor).
# La UI de review ofrece "Apply Sabbi defaults" que pre-llena estos campos.

via_sabbi_brokerage:
  # Productos que clientes Sabbi tienen via Credicorp Capital custody
  # (la estructura estándar — ~95% de productos)
  administrador: "Credicorp Capital"
  gestor: "Credicorp Capital"
  comision: 0.0065  # 0.65% custody fee Credicorp

  # Opcional: matcheo automático por patrón (futuro)
  auto_apply_when:
    - nombre_matches_regex: "^[A-Z]{4,}I1$"  # BVL I1 tickers
    - clase_activo_dominant_is: "Mercados Públicos - Variable"
    - subyacente_contains: ["US Large Cap", "Acciones Peru"]

# Futuro: agregar otras secciones si Sabbi onboardea otro custodio
# via_bcp_capital:
#   administrador: "BCP Capital"
#   gestor: "BCP Capital"
#   comision: 0.0050
```

### 5.1 Loader

`src/scraper/overlay/loader.py`:

```python
@lru_cache(maxsize=1)
def load_sabbi_overlay() -> SabbiOverlay:
    """Parse config/sabbi_overlay.yaml into pydantic model."""
    ...

def apply_overlay_defaults(
    pipeline_output: ClassificationResult,
    overlay_choice: str,  # "via_sabbi_brokerage" or None
) -> dict:
    """Return pre-fill dict for the review UI — only fills Sabbi-operational
    attributes (admin/gestor/comision) when pipeline output was null/low-conf.
    Does NOT override high-confidence public attributes."""
    ...
```

### 5.2 UI integration

En review detail, cada campo Sabbi-operacional muestra:
- Valor actual del pipeline (editable)
- Botón "Apply Sabbi default: Credicorp Capital" debajo (si el default difiere del valor actual)
- Click aplica el default al campo. Operator siempre puede re-editar.

Botón global "Apply Sabbi defaults" pre-llena admin + gestor + comision de una vez.

### 5.3 Hot reload

Settings tab tiene "Reload overlay" button que invalida el `lru_cache`. Para cambios en YAML sin reiniciar Streamlit.

## 6. UI Screens

### 6.1 Tab "Batch Upload" (entry A)

- Upload CSV con columnas: `nombre` (required), `pdf_path` (optional), `url` (optional)
- Preview del CSV + validación (no nombres vacíos, paths existen)
- Click "Submit batch" → genera `batch_id` UUID + insert N rows en job_queue
- Lista de "últimos batches" con progress (23/50 done, etc.)

### 6.2 Tab "Single input" (entry B)

- Campo: nombre del producto (required)
- Opciones avanzadas: URL específica (skip cascade) o PDF upload
- Submit → 1 row en job_queue + "Ver en review queue en ~5 min"

### 6.3 Tab "Review Queue" (core)

- Lista filtrada: [All | needs_review | low_quality | auto_approvable] × [last 7d | 30d | all]
- Sort: priority (low_quality primero) luego timestamp
- Cada card: nombre, flag badge, confidence, source_used, botón "Revisar"
- Click → Review Detail (no es nueva tab, es dentro de la misma página)

### 6.4 Review Detail (dentro de tab 3)

**PUBLIC DATA section** (del pipeline):
- nombre, foco_geografico, clase_activo, subyacente, moneda, liquidez
- Cada uno editable inline con confidence mostrada
- Link a reasoning y rule_applied (colapsable)

**SABBI OPERATIONAL section** (overlay):
- administrador, gestor, comision, minimo_inversion
- Valor actual + botón "Apply Sabbi default" debajo de cada uno
- Botón global "Apply Sabbi defaults" arriba

**EVIDENCIA section** (fichas del pipeline):
- Lista de ExtractedFicha usadas (source_url + source_type + source_confidence)
- Click para ver raw JSON de cada una

**Botones de acción:**
- ✓ Aprobar → INSERT products + audit_log + update review_queue
- 📎 Subir PDF faltante → abre modal, re-procesa con extract_from_pdf
- 🗑 Rechazar → UPDATE review_queue con nota, no crea Product

### 6.5 Tab "Settings"

- Sabbi overlay viewer + reload button
- Rules version selector (v4, v5, custom)
- Cost tracking: total $ del mes, N productos procesados
- Stats simples: approval rate, median time to review, etc.

## 7. Worker script

`src/scraper/scripts/worker.py`:

```python
"""Background worker that polls job_queue and processes pending jobs.

Usage:
    poetry run python -m scraper.scripts.worker

Processes up to MAX_CONCURRENT (default 3) jobs in parallel using asyncio.gather.
Run in a separate terminal from the Streamlit UI.
"""

MAX_CONCURRENT = 3  # configurable via env var
POLL_INTERVAL = 5.0  # seconds between queue polls


async def _main() -> None:
    while True:
        async with get_session() as s:
            pending = await claim_pending_jobs(s, limit=MAX_CONCURRENT)
        if not pending:
            await asyncio.sleep(POLL_INTERVAL)
            continue

        tasks = [_process_job(job) for job in pending]
        await asyncio.gather(*tasks, return_exceptions=True)


async def _process_job(job: JobQueue) -> None:
    """Route to appropriate pipeline call based on pdf_path / url / nombre."""
    try:
        if job.pdf_path:
            ficha = await extract_from_pdf(path=Path(job.pdf_path), llm=llm, nombre=job.nombre)
            cls_result = await classify(... based on ficha)
        elif job.url:
            fichas = await extract_from_url(url=job.url, llm=llm, nombre=job.nombre)
            cls_result = await classify(... based on fichas)
        else:
            # Standard cascade
            cls_result, rev_result, flag = await run_full_pipeline(job.nombre)

        # Save classification + review_queue entry
        await save_classification_and_review_entry(...)
        await mark_job_done(job.id, classification_id)
    except Exception as e:
        await mark_job_failed(job.id, error=str(e))
```

### 7.1 Graceful shutdown

Worker handles SIGINT cleanly: finish in-progress jobs, then exit. Jobs stuck in "in_progress" at restart (due to crash) get re-queued automatically after 30 min timeout check.

### 7.2 Rate limiting

`MAX_CONCURRENT=3` evita hit rate limits de Anthropic (5 req/s sustained). Configurable via `WORKER_MAX_CONCURRENT` env var si Sabbi tiene quota mayor.

## 8. File structure

```
scraper/
├── src/scraper/
│   ├── ui/                          # NEW
│   │   ├── app.py                   # Streamlit entry + sidebar nav
│   │   ├── pages/
│   │   │   ├── 1_batch_upload.py
│   │   │   ├── 2_single_input.py
│   │   │   ├── 3_review_queue.py
│   │   │   └── 4_settings.py
│   │   ├── components/
│   │   │   ├── field_editor.py
│   │   │   ├── overlay_apply.py
│   │   │   └── ficha_viewer.py
│   │   └── state.py
│   │
│   ├── overlay/                     # NEW
│   │   ├── __init__.py
│   │   └── loader.py
│   │
│   ├── scripts/
│   │   ├── worker.py                # NEW
│   │   └── (existing)
│   │
│   └── db/
│       └── models.py                # MODIFIED: + JobQueue
│
├── config/
│   └── sabbi_overlay.yaml           # NEW (starter)
│
├── alembic/versions/
│   └── YYYY_add_job_queue.py        # NEW migration
│
└── tests/
    ├── unit/
    │   ├── test_overlay_loader.py
    │   ├── test_job_queue_ops.py
    │   └── test_approval_logic.py
    └── integration/
        └── test_worker_pipeline.py
```

## 9. Tasks breakdown

**Grupo A — Foundation (3 tasks)**
1. `JobQueue` model + Alembic migration
2. Sabbi overlay loader (YAML → pydantic)
3. Worker skeleton (polling loop, claim jobs)

**Grupo B — Worker logic (4 tasks)**
4. Worker: procesa single job via `find_and_classify` (cascade path)
5. Worker: routing para `pdf_path` → `extract_from_pdf`
6. Worker: routing para `url` directo → `extract_from_url`
7. Worker: concurrency con `asyncio.gather` (3 jobs a la vez configurable)

**Grupo C — UI Foundation (2 tasks)**
8. Streamlit app skeleton + sidebar nav + page routing
9. State helpers + DB session wrapping + common widgets

**Grupo D — Entry A: Batch CSV (2 tasks)**
10. Upload CSV page: validate + parse + insert al job_queue
11. Batch progress view + "mis últimos batches"

**Grupo E — Entry B: Single input (1 task)**
12. Single input page: nombre + opcional URL + opcional PDF → job_queue entry

**Grupo F — Review queue (3 tasks)**
13. Review queue list (filtros, sort por priority)
14. Review detail page — editor + secciones (público / Sabbi)
15. Apply Sabbi defaults component (1-click pre-fill)

**Grupo G — Approve/reject/reclassify (3 tasks)**
16. Approve logic: create Product + audit_log + link a job_queue
17. Reject logic: review_queue.human_decision + notes
18. Reactive PDF upload: re-procesa job con extract_from_pdf

**Grupo H — Settings (1 task)**
19. Settings page: overlay viewer + reload + rules version + cost tracker

**Grupo I — Closure (3 tasks)**
20. Integration tests end-to-end (CSV → worker → review → approve)
21. README update + run-book docs
22. `phase3-STATUS.md` + tag `phase3-complete`

## 10. Criterios de éxito

**Funcional:**
- [ ] Subir CSV de 20 productos → worker procesa → todos aparecen en review queue → operator aprueba 20 → `products` table tiene 20 rows nuevas
- [ ] Single input funciona: tipear nombre → job se crea → draft aparece en queue en ~5 min
- [ ] PDF upload reactivo: low_quality producto → subir PDF → re-procesa → review card actualizada
- [ ] Sabbi overlay aplica correctamente al approve (admin/gestor/comision con defaults)
- [ ] Audit log registra cada approval con before/after diff
- [ ] Worker maneja crash graceful: si se corta, al reiniciar retoma pending jobs

**No-funcional:**
- [ ] Streamlit UI responsive (no freezes) con queue de 50+ jobs in_progress
- [ ] Worker procesa 3-5 concurrent sin hit rate limits de Anthropic
- [ ] SQLite OK para 3 operadores simultáneos local; sin locking issues

**Tests:**
- [ ] ~200 tests total (178 Phase 2b + ~22 nuevos)
- [ ] Unit: overlay loader, job_queue ops, approval logic
- [ ] Integration: worker + queue + review cycle end-to-end (mocked LLM)
- [ ] Manual UI verification en Chrome/Edge

## 11. Timeline y costo

- **Dev:** ~2-3 semanas trabajo subagent-driven (similar a Phase 2b)
- **Costo API durante testing:** ~$20-30 (ocasional real runs para verificar)
- **Costo operacional post-ship (infra):** $0 local; $15-20/mes cuando migre a server interno

## 12. Migración a server interno (Phase 3.5)

Cuando Sabbi quiera mover de local a server:

1. Swap SQLite → Postgres: cambiar `DATABASE_URL` env var (SQLAlchemy ya soporta)
2. Add Streamlit basic auth: ~10 líneas, config en `.streamlit/secrets.toml`
3. Systemd service para worker + streamlit: archivos ejemplo en docs
4. Expose via Nginx reverse proxy: standard setup
5. Backup SQLite → Postgres via `pgloader` o script custom

**Cero cambios de código del MVP Phase 3.** Todo está listo para migrar con config solamente.

## 13. Riesgos conocidos

| Riesgo | Mitigación |
|---|---|
| Streamlit rerun causa pérdida de estado del formulario al navegar | Usar `st.session_state` para persistir inputs de user |
| Worker crash mid-batch deja jobs en "in_progress" forever | Auto-timeout: si `started_at` > 30 min sin `completed_at`, reset a "pending" |
| Sabbi overlay edits no se reflejan sin reload | Settings tab tiene botón explícito "Reload overlay" |
| Multi-operator concurrent approves de mismo product | Check fuzzy match antes de INSERT; UI advierte si conflicto |
| SQLite locking en 3 operadores simultáneos | SQLite 3.40+ con WAL mode lo maneja fine para este uso |
| LLM cost acumula sin visibilidad | Settings tab muestra cost tracking mensual |
| CSV con nombres mal formateados (encoding, espacios) | Validator en upload: strip whitespace, normalize unicode, reject empty |
| PDF uploads sin sanitizar podrían ser problemas de seguridad | Solo aceptar extensión `.pdf`, guardar con filename sanitized, no ejecutar |

## 14. Execution handoff

Siguiente paso: ejecutar `writing-plans` para convertir este design en plan task-by-task (estilo Phase 2a/2b plans) con pasos bite-sized para ejecución subagent-driven.
