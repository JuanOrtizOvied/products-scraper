# Source Traceability, Conflict Resolution & UI Overhaul

**Fecha:** 2026-04-30
**Autor:** Sabbi + Claude
**Status:** Aprobado, pendiente implementación
**Base:** Phase 3 HITL UI + rules v5

---

## Motivación

El pipeline actual clasifica productos pero pierde trazabilidad: el humano no sabe de qué documento o página salió cada valor. Cuando hay múltiples fuentes con datos diferentes, el sistema elige silenciosamente por confianza sin informar del conflicto. La UI es funcional pero requiere conocimiento técnico (edición JSON, sin indicadores visuales).

---

## Objetivos

1. **Trazabilidad completa**: cada atributo clasificado cita su fuente (URL/PDF + fragmento textual)
2. **Prioridad por recencia**: ante múltiples fuentes, preferir la de fecha de documento más reciente
3. **Detección de conflictos**: cuando dos fuentes discrepan, merge automático + flag para revisión humana
4. **UI intuitiva**: un no-programador puede revisar y aprobar productos sin ayuda

---

## Diseño Técnico

### 1. Cambios en Tipos (`agents/types.py`)

#### `ExtractedFicha` — campo nuevo

```python
document_date: datetime | None  # extraída del contenido ("Vigente al 31/03/2026")
```

El extractor Claude recibe instrucción de buscar patrones de fecha en el documento: "Fecha de actualización", "Vigente al", "As of", footers con fecha, metadata PDF. Si no la encuentra → `None`.

#### `AttributeClassification` — campos nuevos

```python
source_url: str | None     # URL o path del PDF de donde salió el valor
source_label: str | None   # nombre legible: "Ficha BBVA Agresivo (Mar 2026)"
raw_quote: str | None      # cita textual directa, max 200 chars
```

#### Nuevo dataclass: `ConflictEntry`

```python
@dataclass(frozen=True)
class ConflictEntry:
    value: Any                    # el valor de esta fuente
    source_url: str               # URL o path
    source_label: str             # nombre legible
    document_date: datetime | None
    raw_quote: str | None         # evidencia textual
```

#### Nuevo dataclass: `FieldConflict`

```python
@dataclass
class FieldConflict:
    attribute: str                  # "comision", "clase_activo", etc.
    chosen_value: Any               # valor elegido (fuente más reciente)
    chosen_source: str              # URL de la fuente elegida
    alternatives: list[ConflictEntry]  # otras fuentes con valores distintos
```

### 2. Pipeline de Merge y Conflictos

#### Ubicación: `scripts/worker_pipeline.py`

Hoy `_top_ficha(fichas)` elige una sola ficha por `source_confidence`. Se reemplaza con:

#### Nuevo dataclass: `SourceSummary`

```python
@dataclass(frozen=True)
class SourceSummary:
    url: str                       # URL o path del PDF
    label: str                     # nombre legible ("Ficha BBVA Agresivo Mar 2026")
    document_date: datetime | None # fecha del documento
    source_type: str               # "pdf_text" | "html" | "pdf_vision" | "websearch" | "db"
```

#### Nuevo: `merge_fichas(fichas: list[ExtractedFicha]) -> MergeResult`

```python
@dataclass
class MergeResult:
    primary: ExtractedFicha           # la más reciente
    all_sources: list[SourceSummary]  # resumen de cada fuente
    conflicts: list[FieldConflict]    # campos con discrepancia
    merged_context: str               # texto combinado para el clasificador
```

**Algoritmo:**

1. Ordenar fichas por `document_date` desc (nulls al final), fallback `fetched_at`
2. `primary` = primera (más reciente)
3. Para cada atributo en `primary.attributes`:
   - Comparar con el mismo atributo en las demás fichas
   - Conflicto si: valores categóricos difieren, o dicts difieren >5pp en cualquier componente
   - NO conflicto si: solo difieren en formato ("1.50%" vs "1.5%")
4. Construir `merged_context`: incluir datos de TODAS las fichas con labels de fuente

#### Contexto al clasificador

El prompt del clasificador se modifica para incluir:

```
Fuentes disponibles (ordenadas por fecha, más reciente primero):

[Fuente 1: Ficha BBVA Agresivo — Mar 2026 — PDF]
<contenido relevante>

[Fuente 2: bbva.pe/fondos/agresivo — Ene 2026 — Web]
<contenido relevante>

INSTRUCCIONES DE FUENTES:
- Prioriza la fuente más reciente por fecha del documento.
- Para cada atributo, incluye source_url y raw_quote de la fuente que usaste.
- Si dos fuentes difieren en un valor, usa la más reciente y menciona la discrepancia en reasoning.
```

### 3. Cambios en DB (`Classification` model)

```python
# Nuevas columnas (nullable, backwards compatible)
sources_used = Column(JSON, nullable=True)
# [{url: str, label: str, document_date: str|null, source_type: str}]

field_conflicts = Column(JSON, nullable=True)
# [{attribute: str, chosen_value: any, chosen_source: str,
#   alternatives: [{value, source_url, source_label, document_date, raw_quote}]}]
```

Migración Alembic: una sola migración con 2 `ADD COLUMN`.

### 4. Prompts del Extractor

El system prompt del extractor (`extractor_system.md`) se modifica para incluir:

```
Además de los atributos de inversión, extrae:
- document_date: fecha de publicación o última actualización del documento.
  Busca: "Fecha de actualización", "Vigente al", "As of", "Fecha:", footer con fecha,
  metadata del documento. Formato: YYYY-MM-DD. Si no encuentras ninguna fecha → null.
```

### 5. Prompts del Clasificador

El system prompt (`classifier_system.md`) se modifica para que el output JSON incluya:

```json
{
  "comision": {
    "value": 0.015,
    "confidence": 0.92,
    "reasoning": "Ficha técnica indica comisión de gestión anual 1.50%",
    "rule_applied": "comision-annual-fee",
    "source_url": "https://bbva.pe/fondos/ficha-agresivo.pdf",
    "source_label": "Ficha BBVA Agresivo (Mar 2026)",
    "raw_quote": "Comisión de administración: 1.50% anual sobre patrimonio neto"
  }
}
```

---

## Diseño de UI

### Review Queue — Vista de Lista

Reemplazar tabla plana con cards:

```
┌─────────────────────────────────────────────────────┐
│ 🔍 [Buscar por nombre...]  [Flag ▼]  [Ordenar ▼]   │
├─────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🟡 needs_review  Confianza: ████████░░ 0.82    │ │
│ │ BBVA Agresivo Soles                             │ │
│ │ 📄 2 fuentes · ⚠ 1 conflicto · $0.03           │ │
│ └─────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🔴 low_quality   Confianza: ████░░░░░░ 0.45    │ │
│ │ Fondo Renta Mixta Peru                          │ │
│ │ 📄 3 fuentes · ⚠ 2 conflictos · $0.05          │ │
│ └─────────────────────────────────────────────────┘ │
```

**Filtros:**
- Búsqueda por nombre (text input)
- Flag: todos / low_quality / needs_review / auto_approvable
- Orden: fecha (desc) / confianza (asc) / conflictos (desc)

### Review Queue — Vista de Detalle

Cada campo muestra:

```
┌──────────────────────────────────────────────────────┐
│ BBVA Agresivo Soles                                  │
│ Fuentes: 📄 Ficha Mar 2026 (link) · 🌐 bbva.pe/... │
├──────────────────────────────────────────────────────┤
│                                                      │
│ Administrador          Confianza: ██████████ 0.95    │
│ ┌──────────────────────────────────────┐             │
│ │ BBVA Asset Management SAF           │             │
│ └──────────────────────────────────────┘             │
│ 📄 Ficha BBVA Agresivo (Mar 2026)                   │
│ ▶ Ver evidencia                                      │
│                                                      │
│ Comisión  ⚠ CONFLICTO   Confianza: ████████░░ 0.78  │
│ ┌──────────────────────────────────────┐             │
│ │ 1.50                                │ ← elegido   │
│ └──────────────────────────────────────┘             │
│ 📄 Ficha Mar 2026: "Comisión 1.50% anual"           │
│ ┌ Alternativa ──────────────────────────┐            │
│ │ 🌐 bbva.pe (Ene 2026): "1.75% anual" │            │
│ │        [Usar este valor]              │            │
│ └───────────────────────────────────────┘            │
│                                                      │
│ Clase de Activo        Confianza: ██████████ 0.93    │
│ ┌──────────────────────────────────────┐             │
│ │ Renta Variable  │  70%  │ [-] [+]   │             │
│ │ Renta Fija      │  30%  │ [-] [+]   │             │
│ │           [+ Agregar fila]           │             │
│ └──────────────────────────────────────┘             │
│ 📄 Ficha BBVA Agresivo (Mar 2026)                   │
│ ▶ Ver evidencia                                      │
│                                                      │
│ ┌────────────┐  ┌────────────┐                       │
│ │ ✅ Aprobar  │  │ ❌ Rechazar │                      │
│ └────────────┘  └────────────┘                       │
└──────────────────────────────────────────────────────┘
```

### Componentes Nuevos

| Componente | Archivo | Función |
|------------|---------|---------|
| `confidence_bar` | `ui/components/confidence_bar.py` | Barra coloreada (verde ≥0.90, amarillo ≥0.70, rojo <0.70) |
| `source_citation` | `ui/components/source_citation.py` | Cita mínima + expander "Ver evidencia" con raw_quote |
| `conflict_panel` | `ui/components/conflict_panel.py` | Muestra alternativas con botón "Usar este valor" |
| `dict_editor` | `ui/components/dict_editor.py` | Tabla editable nombre/porcentaje reemplaza JSON crudo |
| `review_card` | `ui/components/review_card.py` | Card con badge de flag, barra confianza, conteo fuentes/conflictos |

### Campos editados por humano

Cuando el humano modifica un valor (ya sea manualmente o via "Usar este valor" en conflicto), el campo se marca visualmente con borde azul para distinguir ediciones humanas de valores del agente.

### Batch Upload — Mejora

Agregar barra de progreso visual:
```
Batch #12 — 45 productos
████████████████░░░░░░░░░░ 64%
✅ 25 completados · ⏳ 4 en proceso · 📋 12 pendientes · ❌ 4 fallidos
```

### Settings — Mejora

Agregar panel "Fuentes recientes": lista de últimos PDFs/URLs procesados con fecha y estado.

---

## Rules v6

Archivo: `rules/v6.md`

Cambios sobre v5:

### Reglas nuevas — Trazabilidad y Citación

- **R-SRC-1**: Todo atributo clasificado DEBE incluir `source_url` y `raw_quote`. Sin evidencia textual directa → confidence máxima = 0.60.
- **R-SRC-2**: `raw_quote` debe ser cita literal del documento (copiar/pegar), no parafraseo. Máximo 200 caracteres.
- **R-SRC-3**: Cada fuente debe tener `document_date` extraída del contenido. Patrones: "Fecha de actualización", "Vigente al", "As of", footer con fecha. Si no se encuentra → null.

### Reglas nuevas — Prioridad de Fuentes

- **R-PRI-1**: Prioridad de tipo: Ficha técnica oficial > Prospecto/Reglamento > Página web del administrador > Fuente tercera (Morningstar, Bloomberg, etc.)
- **R-PRI-2**: A igualdad de tipo, preferir el más reciente por `document_date`.
- **R-PRI-3**: Si dos fuentes del mismo tipo y fecha discrepan, usar la del administrador/emisor directo.

### Reglas nuevas — Detección de Conflictos

- **R-CON-1**: Conflicto = dos fuentes con valores semánticamente distintos para el mismo atributo. Diferencia de formato ("1.50%" vs "1.5%") NO es conflicto; diferencia de valor ("1.50%" vs "1.75%") SÍ.
- **R-CON-2**: Para dicts (subyacente, clase_activo, foco_geografico), conflicto = diferencia >5pp en cualquier componente.
- **R-CON-3**: Campos en conflicto → confidence máxima = 0.80 (fuerza `needs_review` por umbral <0.90).

### Ajustes a reglas existentes

- **Comisión**: si hay múltiples clases de participación, reportar la clase más accesible (menor mínimo de inversión), no la más baja.
- **Liquidez**: "T+N" del documento es preferible a inferir de la categoría del fondo.
- **ADRs**: agregar ejemplos VALE=Brasil, MELI=Argentina, TSM=Taiwán.

---

## Migración y Compatibilidad

- Una sola migración Alembic: 2 columnas nullable en `Classification`
- Datos existentes no se rompen (nullable = backwards compatible)
- `classifier_output` JSON existente sigue siendo legible (campos nuevos son opcionales en el parser)
- UI maneja gracefully clasificaciones antiguas sin fuentes/conflictos (no muestra citas ni panel de conflicto)

---

## Archivos Impactados

| Capa | Archivos | Cambio |
|------|----------|--------|
| Tipos | `agents/types.py` | +3 campos en AttributeClassification, +2 dataclasses nuevas, +1 campo ExtractedFicha |
| Extractor | `agents/extractor.py`, `agents/prompts/extractor_system.md` | Extraer document_date |
| Clasificador | `agents/classifier.py`, `agents/prompts/classifier_system.md` | Citar fuentes en output |
| Pipeline | `scripts/worker_pipeline.py` | Merge por recencia + detección de conflictos |
| DB | `db/models.py`, nueva migración Alembic | +2 columnas JSON |
| UI - Componentes | `ui/components/` (5 archivos nuevos) | confidence_bar, source_citation, conflict_panel, dict_editor, review_card |
| UI - Review | `ui/pages/3_review_queue.py` | Overhaul completo: cards, filtros, detalle con citas y conflictos |
| UI - Batch | `ui/pages/1_batch_upload.py` | Barra de progreso visual |
| UI - Settings | `ui/pages/4_settings.py` | Panel fuentes recientes |
| UI - Logic | `ui/review_logic.py` | Persistir campo editado + source de la elección humana |
| Rules | `rules/v6.md` | 6 reglas nuevas + ajustes |
| Tests | Nuevos + modificados | Merge logic, conflict detection, UI components |
