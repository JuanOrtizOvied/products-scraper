# Sabbi — Buscador y Clasificador de Productos de Inversión

Sistema interno de Sabbi para buscar, extraer y clasificar productos de inversión desde múltiples fuentes (web, PDF, bases de datos). Incluye un pipeline de procesamiento automático con revisión humana obligatoria (HITL).

---

## Arquitectura

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐     ┌──────────┐
│  Streamlit   │────▶│  Job Queue   │────▶│   Worker   │────▶│ Review   │
│     UI       │     │   (SQLite)   │     │  Pipeline  │     │  Queue   │
└─────────────┘     └──────────────┘     └────────────┘     └──────────┘
                                               │
                          ┌────────────────────┼────────────────────┐
                          ▼                    ▼                    ▼
                    ┌───────────┐      ┌──────────────┐     ┌────────────┐
                    │ Extractor │      │  Classifier  │     │  Reviewer  │
                    │  (Sonnet) │      │   (Sonnet)   │     │   (Opus)   │
                    └───────────┘      └──────────────┘     └────────────┘
```

### Pipeline de procesamiento

1. **Búsqueda en cascada** (4 niveles):
   - N0: Lookup en base de datos local
   - N1: Scrapers específicos (BBVA, Credicorp, etc.)
   - N2: Búsqueda web + extracción HTML/PDF
   - N3: Búsqueda intensiva (deshabilitada por defecto)

2. **Extracción**: Toma texto + tablas de HTML o PDF y produce una ficha estructurada con 9 atributos canónicos (foco geográfico, clase de activo, subyacente, comisión, moneda, administrador, gestor, liquidez, mínimo inversión).

3. **Clasificación**: Normaliza los atributos extraídos usando taxonomías canónicas y reglas de negocio (rules/v8.md).

4. **Revisión**: Un segundo modelo critica la clasificación y asigna un flag de calidad (auto_approvable, needs_review, low_quality).

5. **HITL**: Un operador humano revisa, edita y aprueba/rechaza desde la UI.

### Funcionalidades clave

- **Inferencia geográfica deductiva (R-GEO-DEDUCT)**: Cuando un PDF no indica explícitamente el foco geográfico pero incluye una tabla de emisores/holdings, el sistema deduce la distribución geográfica analizando el país de operación de cada emisor.

- **Detección de múltiples clases/series**: Para fondos con Clase A, B (o Serie A, B) con diferentes comisiones y mínimos, el sistema detecta todas las opciones y presenta un selector en la UI para que el operador elija.

- **Merge inteligente de fuentes**: Cuando se sube un PDF complementario a una clasificación existente (por ejemplo, tras una búsqueda web), el sistema combina las fuentes y mantiene el valor de mayor confianza por atributo en vez de reemplazar.

- **Extracción inteligente de PDFs largos**: Para documentos de más de 40 páginas, prioriza las primeras páginas + detecta automáticamente páginas con datos financieros clave (comisiones, mínimos, estructura de costos).

---

## Setup local

### Requisitos

- Python 3.12+
- [Poetry](https://python-poetry.org/)
- API key de Anthropic (variable `ANTHROPIC_API_KEY`)

### Instalación

```bash
poetry install
cp .env.example .env   # completar con API keys
poetry run alembic upgrade head
```

### Carga inicial de datos

```bash
poetry run python -m scraper.scripts.seed_from_excel "BD_Productos Sabbi.xlsx"
poetry run python -m scraper.scripts.split_train_validation
```

### Dependencias opcionales

```bash
# Scrapling (fetching con Playwright para páginas JS-rendered)
poetry run playwright install chromium

# Poppler (OCR para PDFs escaneados)
#   Windows: descargar desde github.com/oschwartz10612/poppler-windows
#   macOS:   brew install poppler
#   Linux:   apt-get install poppler-utils
```

---

## Uso

### UI + Worker (modo normal)

Abrir dos terminales:

```bash
# Terminal 1: Interfaz web
poetry run streamlit run src/scraper/ui/app.py

# Terminal 2: Worker de procesamiento
poetry run python -m scraper.scripts.worker
```

La UI se abre en `http://localhost:8501` con 4 páginas:

| Página | Función |
|--------|---------|
| **Batch Upload** | Subir CSV con columna `nombre` (y opcionales `pdf_path`, `url`) |
| **Single Input** | Clasificar un producto individual, con opción de subir PDF o URL específica |
| **Review Queue** | Revisar clasificaciones pendientes, seleccionar clase, editar atributos, aprobar/rechazar |
| **Settings** | Ver overlay de Sabbi, seleccionar versión de reglas, tracking de costos |

### Review Queue — flujo de trabajo

1. El worker procesa los jobs y los deposita en la Review Queue con un flag de calidad.
2. El operador revisa cada producto:
   - Si hay múltiples clases/series, selecciona la que corresponde (comisión y mínimo se actualizan automáticamente).
   - Si hay conflictos entre fuentes, elige el valor correcto desde un selector.
   - Puede editar cualquier atributo manualmente.
3. Si el pipeline no encontró buena info, puede subir un PDF directamente. El sistema combina la nueva info con la existente (merge inteligente).
4. Aprueba o rechaza. Los productos aprobados pasan a la tabla `products`.

### Línea de comandos

```bash
# Clasificar un producto (extractor + classifier + reviewer)
poetry run python -m scraper.scripts.classify_one "Credicorp Crecimiento"

# Búsqueda + clasificación desde solo el nombre
poetry run python -m scraper.scripts.find_and_classify "Credicorp Crecimiento"

# Extracción directa desde URL o PDF
poetry run python -m scraper.scripts.extract_one --url https://example.com/fondo
poetry run python -m scraper.scripts.extract_one --pdf path/to/ficha.pdf

# Calibrar contra validation set (costo ~$0.50–2.00 USD)
poetry run python -m scraper.scripts.calibrate
```

---

## Reglas de clasificación

Las reglas están versionadas en `rules/v1.md` a `rules/v8.md`. El worker usa `v8` por defecto.

### v8 incluye:

- **Doble capa**: distingue atributos intrínsecos del producto (administrador real, expense ratio) vs. atributos de distribución (intermediario peruano, fee de custodia).
- **Trazabilidad obligatoria**: cada atributo debe incluir `source_url`, `raw_quote` y `document_date`.
- **Prioridad de fuentes**: Ficha técnica > Prospecto > Web del administrador > Fuente tercera.
- **Detección de conflictos**: cuando dos fuentes discrepan en >5pp, se marca como conflicto y baja la confianza.
- **Inferencia geográfica**: análisis de tabla de emisores para deducir distribución geográfica.
- **Detección de clases**: fondos con Serie A/B o Clase A/B se reportan como opciones separadas.

---

## Configuración

### Variables de entorno (.env)

| Variable | Descripción |
|----------|-------------|
| `ANTHROPIC_API_KEY` | API key de Anthropic |
| `DATABASE_URL` | URL de la base de datos (default: SQLite local) |
| `SKIP_INTENSIVE_SEARCH` | `true` para deshabilitar N3 (default: `true`) |
| `FETCHER_BACKEND` | `scrapling` o `legacy` (default: `scrapling`) |
| `WORKER_MAX_CONCURRENT` | Jobs en paralelo (default: 3) |
| `WORKER_POLL_INTERVAL_S` | Segundos entre polls (default: 5) |

### Sabbi overlay

Editar `config/sabbi_overlay.yaml` para configurar defaults operacionales (administrador, gestor, fee de custodia). Se puede recargar desde la pestaña Settings sin reiniciar.

---

## Taxonomías

Archivos YAML en `src/scraper/taxonomies/`:

- **`asset_classes.yaml`**: 6 macro clases de activo
- **`canonical_assets.yaml`**: ~32 subyacentes canónicos con scores
- **`geographic_regions.yaml`**: 5 regiones (Perú, EEUU, Latam ex-Perú, Emergentes ex-Perú, Desarrollados ex-EEUU)
- **`normalizer_variants.yaml`**: mapeo de variantes ortográficas a valores canónicos

---

## Base de datos

SQLite por defecto, migraciones con Alembic. Tablas principales:

| Tabla | Función |
|-------|---------|
| `products` | Productos aprobados (output final) |
| `classifications` | Output de cada run del clasificador |
| `review_queue` | Cola de revisión humana |
| `job_queue` | Cola de procesamiento del worker |
| `training_set` / `validation_set` | Split para calibración |
| `rules_versions` | Historial de versiones de reglas |
| `audit_log` | Registro de aprobaciones/rechazos |

---

## Tests

```bash
poetry run pytest
```

267 tests (unit + integration). Un test pre-existente requiere `SKIP_INTENSIVE_SEARCH=true` en `.env`.

---

## Estructura del proyecto

```
src/scraper/
├── agents/                  # Agentes de clasificación
│   ├── classifier.py        # Clasificador (Sonnet)
│   ├── extractor.py         # Extractor de fichas (Sonnet)
│   ├── reviewer.py          # Revisor crítico (Opus)
│   ├── distributor.py       # Agente de distribución (capa 2)
│   ├── orchestrator.py      # Lógica de flags de calidad
│   ├── parsing.py           # Parseo robusto de JSON
│   ├── types.py             # Dataclasses compartidos
│   └── prompts/             # System prompts + builder
├── db/                      # Modelos SQLAlchemy + session
├── extract/                 # Extracción de HTML, PDF, OCR
│   ├── html.py              # Fetch + limpieza HTML
│   ├── pdf.py               # Extracción de texto + tablas (smart truncation)
│   ├── fetch.py             # Backend de fetching (Scrapling/legacy)
│   └── vision.py            # OCR para PDFs escaneados
├── search/                  # Cascada de búsqueda (N0–N3)
│   ├── cascade.py           # Orquestador de niveles
│   ├── merge.py             # Merge de múltiples fichas + conflictos
│   ├── level0_db.py         # Lookup en DB
│   ├── level1_scrapers/     # Parsers específicos por sitio
│   ├── level2_websearch.py  # Búsqueda web (Tavily)
│   └── level3_intensive.py  # Búsqueda intensiva
├── taxonomies/              # Taxonomías canónicas + normalización
├── metrics/                 # Métricas de accuracy para calibración
├── overlay/                 # Sabbi overlay config
├── scripts/                 # CLI scripts
│   ├── worker.py            # Worker de background
│   ├── worker_pipeline.py   # Pipeline: cascade → extract → classify → review → persist
│   ├── calibrate.py         # Calibración contra validation set
│   └── ...
└── ui/                      # Streamlit HITL UI
    ├── app.py               # Entry point
    ├── pages/               # 4 páginas (batch, single, review, settings)
    ├── components/          # Widgets (confidence bar, dict editor, class selector, etc.)
    ├── review_logic.py      # Aprobación/rechazo
    └── upload_ops.py        # Re-upload de PDFs con merge
```
