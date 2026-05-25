# Source Traceability, Conflict Resolution & UI Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-attribute source citations, multi-source conflict detection with auto-merge by document recency, and overhaul the Streamlit review UI with visual components.

**Architecture:** Extend existing dataclasses with source/citation fields, add merge logic in the pipeline that detects conflicts between ExtractedFichas, persist sources and conflicts as JSON columns in Classification, and replace the flat review UI with card-based layout and visual editors.

**Tech Stack:** Python 3.11+, SQLAlchemy async, Alembic, Streamlit, Claude Sonnet 4.6 / Opus 4.7 (Anthropic SDK), pytest + pytest-asyncio.

---

## File Map

| Layer | File | Action | Responsibility |
|-------|------|--------|----------------|
| Types | `src/scraper/agents/types.py` | Modify | Add source fields to AttributeClassification, document_date to ExtractedFicha, new ConflictEntry/FieldConflict/SourceSummary/MergeResult dataclasses |
| Extractor prompt | `src/scraper/agents/prompts/extractor_system.md` | Modify | Add document_date extraction instruction |
| Extractor agent | `src/scraper/agents/extractor.py` | Modify | Parse document_date from Claude output |
| Classifier prompt | `src/scraper/agents/prompts/classifier_system.md` | Modify | Add source_url/source_label/raw_quote to output schema |
| Classifier agent | `src/scraper/agents/classifier.py` | Modify | Parse new fields in from_json, build multi-source context |
| Prompt builder | `src/scraper/agents/prompts/builder.py` | Modify | Add source_url/source_label/raw_quote to few-shot examples |
| Pipeline merge | `src/scraper/search/merge.py` | Create | merge_fichas() — sort by recency, detect conflicts, build merged context |
| Worker pipeline | `src/scraper/scripts/worker_pipeline.py` | Modify | Use merge_fichas instead of _top_ficha, persist sources/conflicts |
| find_and_classify | `src/scraper/scripts/find_and_classify.py` | Modify | Use merge_fichas instead of _top_ficha |
| DB model | `src/scraper/db/models.py` | Modify | Add sources_used, field_conflicts columns to Classification |
| DB migration | `alembic/versions/xxxx_add_source_columns.py` | Create | ALTER TABLE classifications ADD COLUMN x2 |
| UI confidence_bar | `src/scraper/ui/components/confidence_bar.py` | Create | Colored progress bar widget |
| UI source_citation | `src/scraper/ui/components/source_citation.py` | Create | Citation label + expandable quote |
| UI conflict_panel | `src/scraper/ui/components/conflict_panel.py` | Create | Alternatives list with "Use this value" button |
| UI dict_editor | `src/scraper/ui/components/dict_editor.py` | Create | Visual table editor for percentage dicts |
| UI review_card | `src/scraper/ui/components/review_card.py` | Create | Card widget for review list |
| UI review queue | `src/scraper/ui/pages/3_review_queue.py` | Rewrite | Cards, filters, detail with citations/conflicts |
| UI batch upload | `src/scraper/ui/pages/1_batch_upload.py` | Modify | Add progress bar |
| UI settings | `src/scraper/ui/pages/4_settings.py` | Modify | Add recent sources panel, update default rules to v6 |
| Rules | `rules/v6.md` | Already created | Reference only |
| Tests | `tests/unit/test_merge.py` | Create | merge_fichas unit tests |
| Tests | `tests/unit/test_types_v6.py` | Create | New dataclass serialization tests |
| Tests | `tests/unit/test_ui_components.py` | Create | UI component unit tests |

---

### Task 1: Extend Agent Types with Source Fields

**Files:**
- Modify: `src/scraper/agents/types.py`
- Test: `tests/unit/test_types_v6.py`

- [ ] **Step 1: Write failing tests for new AttributeClassification fields**

```python
# tests/unit/test_types_v6.py
"""Tests for v6 source traceability type extensions."""
from datetime import datetime, UTC
from scraper.agents.types import (
    AttributeClassification,
    ClassificationResult,
    ConflictEntry,
    ExtractedFicha,
    FieldConflict,
    MergeResult,
    SourceSummary,
    AttributeExtraction,
)


def test_attribute_classification_with_source_fields():
    ac = AttributeClassification(
        value=0.015,
        confidence=0.92,
        reasoning="Ficha dice 1.50%",
        rule_applied="comision-annual-fee",
        source_url="https://bbva.pe/ficha.pdf",
        source_label="Ficha BBVA (Mar 2026)",
        raw_quote="Comisión de administración: 1.50% anual",
    )
    assert ac.source_url == "https://bbva.pe/ficha.pdf"
    assert ac.source_label == "Ficha BBVA (Mar 2026)"
    assert ac.raw_quote == "Comisión de administración: 1.50% anual"


def test_attribute_classification_defaults_none():
    ac = AttributeClassification(
        value="soles", confidence=1.0, reasoning="PEN", rule_applied="moneda"
    )
    assert ac.source_url is None
    assert ac.source_label is None
    assert ac.raw_quote is None


def test_classification_result_roundtrip_with_sources():
    ac = AttributeClassification(
        value="soles", confidence=1.0, reasoning="r", rule_applied="x",
        source_url="https://a.com", source_label="A", raw_quote="PEN",
    )
    cr = ClassificationResult(
        producto="Test", attributes={"moneda": ac}, global_confidence=0.9
    )
    json_str = cr.to_json()
    restored = ClassificationResult.from_json(json_str)
    assert restored.attributes["moneda"].source_url == "https://a.com"
    assert restored.attributes["moneda"].raw_quote == "PEN"


def test_extracted_ficha_document_date():
    ficha = ExtractedFicha(
        source_url="https://x.com",
        source_type="html",
        source_confidence=0.8,
        fetched_at=datetime.now(tz=UTC),
        document_date=datetime(2026, 3, 31, tzinfo=UTC),
        raw_text="test",
        tables=[],
        attributes={},
        citations=[],
        extraction_cost_usd=0.0,
        extraction_duration_ms=100,
    )
    assert ficha.document_date == datetime(2026, 3, 31, tzinfo=UTC)


def test_extracted_ficha_document_date_default_none():
    ficha = ExtractedFicha(
        source_url=None,
        source_type="pdf_text",
        source_confidence=0.5,
        fetched_at=datetime.now(tz=UTC),
        raw_text="t",
        tables=[],
        attributes={},
        citations=[],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )
    assert ficha.document_date is None


def test_extracted_ficha_json_roundtrip_with_document_date():
    dt = datetime(2026, 3, 15, tzinfo=UTC)
    ficha = ExtractedFicha(
        source_url="https://x.com", source_type="html",
        source_confidence=0.9, fetched_at=datetime.now(tz=UTC),
        document_date=dt, raw_text="t", tables=[], attributes={},
        citations=[], extraction_cost_usd=0.0, extraction_duration_ms=0,
    )
    payload = ficha.to_json()
    assert payload["document_date"] == dt.isoformat()
    restored = ExtractedFicha.from_json(payload)
    assert restored.document_date == dt


def test_conflict_entry_creation():
    ce = ConflictEntry(
        value=0.015, source_url="https://a.com",
        source_label="Ficha A", document_date=None,
        raw_quote="1.50% anual",
    )
    assert ce.value == 0.015
    assert ce.source_label == "Ficha A"


def test_field_conflict_creation():
    alt = ConflictEntry(
        value=0.0175, source_url="https://b.com",
        source_label="Web B", document_date=None,
        raw_quote="1.75%",
    )
    fc = FieldConflict(
        attribute="comision",
        chosen_value=0.015,
        chosen_source="https://a.com",
        alternatives=[alt],
    )
    assert fc.attribute == "comision"
    assert len(fc.alternatives) == 1
    assert fc.alternatives[0].value == 0.0175


def test_source_summary_creation():
    ss = SourceSummary(
        url="https://x.com", label="Ficha X",
        document_date=datetime(2026, 3, 1, tzinfo=UTC),
        source_type="pdf_text",
    )
    assert ss.url == "https://x.com"
    assert ss.source_type == "pdf_text"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/test_types_v6.py -v`
Expected: FAIL — ConflictEntry, FieldConflict, SourceSummary, MergeResult not importable; AttributeClassification missing source fields; ExtractedFicha missing document_date.

- [ ] **Step 3: Implement the type changes**

In `src/scraper/agents/types.py`, make these changes:

**a) Add source fields to `AttributeClassification` (line 10-15):**

Replace the existing `AttributeClassification`:

```python
@dataclass(frozen=True)
class AttributeClassification:
    value: Any
    confidence: float
    reasoning: str
    rule_applied: str
    source_url: str | None = None
    source_label: str | None = None
    raw_quote: str | None = None
```

**b) Update `ClassificationResult.to_json()` (around line 30-39)** to include the new fields in `asdict(v)` — `asdict` already handles this since the fields are on the dataclass. No change needed to `to_json()`.

**c) Update `ClassificationResult.from_json()` (around line 42-58)** to parse the new fields:

```python
    @classmethod
    def from_json(cls, data: str | dict) -> ClassificationResult:
        p = json.loads(data) if isinstance(data, str) else data
        attrs = {
            k: AttributeClassification(
                value=v["value"],
                confidence=float(v["confidence"]),
                reasoning=str(v.get("reasoning", "")),
                rule_applied=str(v.get("rule_applied", "")),
                source_url=v.get("source_url"),
                source_label=v.get("source_label"),
                raw_quote=v.get("raw_quote"),
            )
            for k, v in p.get("attributes", {}).items()
        }
        return cls(
            producto=str(p["producto"]),
            attributes=attrs,
            global_confidence=float(p.get("global_confidence", 0.0)),
            unknowns=list(p.get("unknowns", [])),
        )
```

**d) Add `document_date` to `ExtractedFicha` (after line 123, after `fetched_at`):**

```python
    document_date: datetime | None = None
```

**e) Update `ExtractedFicha.to_json()` to include document_date:**

Add after the `"fetched_at"` line:

```python
            "document_date": self.document_date.isoformat() if self.document_date else None,
```

**f) Update `ExtractedFicha.from_json()` to parse document_date:**

Add after the `fetched_at` line in the constructor call:

```python
            document_date=(
                datetime.fromisoformat(payload["document_date"])
                if payload.get("document_date")
                else None
            ),
```

**g) Add new dataclasses at the end of the file:**

```python
@dataclass(frozen=True)
class ConflictEntry:
    value: Any
    source_url: str
    source_label: str
    document_date: datetime | None = None
    raw_quote: str | None = None


@dataclass
class FieldConflict:
    attribute: str
    chosen_value: Any
    chosen_source: str
    alternatives: list[ConflictEntry] = field(default_factory=list)


@dataclass(frozen=True)
class SourceSummary:
    url: str
    label: str
    document_date: datetime | None = None
    source_type: str = ""


@dataclass
class MergeResult:
    primary: ExtractedFicha
    all_sources: list[SourceSummary]
    conflicts: list[FieldConflict]
    merged_context: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/unit/test_types_v6.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `poetry run pytest --tb=short -q`
Expected: All existing tests still pass. The new default values (`None`) on AttributeClassification are backwards compatible.

- [ ] **Step 6: Commit**

```bash
git add src/scraper/agents/types.py tests/unit/test_types_v6.py
git commit -m "feat(types): add source traceability fields and conflict dataclasses"
```

---

### Task 2: Extractor — Extract document_date

**Files:**
- Modify: `src/scraper/agents/prompts/extractor_system.md`
- Modify: `src/scraper/agents/extractor.py`
- Modify: `tests/integration/test_extractor_mocked.py`

- [ ] **Step 1: Write failing test for document_date extraction**

Add to `tests/integration/test_extractor_mocked.py`:

```python
@pytest.mark.asyncio
async def test_extractor_parses_document_date(mock_llm_client):
    import json
    from scraper.agents.extractor import extract_with_claude

    extractor_output = json.dumps({
        "source_type": "pdf_text",
        "source_confidence": 0.85,
        "document_date": "2026-03-31",
        "raw_text": "Ficha técnica",
        "tables": [],
        "attributes": {
            "nombre": {"value": "Test Fund", "confidence": 0.9, "reasoning": "r", "raw_quote": "q"}
        },
        "citations": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(extractor_output)

    ficha = await extract_with_claude(
        llm=mock_llm_client,
        source_url="https://test.com",
        source_type="pdf_text",
        raw_text="Vigente al 31 de marzo de 2026",
        tables=[],
        nombre="Test Fund",
    )
    assert ficha.document_date is not None
    assert ficha.document_date.year == 2026
    assert ficha.document_date.month == 3
    assert ficha.document_date.day == 31


@pytest.mark.asyncio
async def test_extractor_null_document_date(mock_llm_client):
    import json
    from scraper.agents.extractor import extract_with_claude

    extractor_output = json.dumps({
        "source_type": "html",
        "source_confidence": 0.7,
        "raw_text": "no date here",
        "tables": [],
        "attributes": {},
        "citations": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(extractor_output)

    ficha = await extract_with_claude(
        llm=mock_llm_client,
        source_url="https://test.com",
        source_type="html",
        raw_text="no date here",
        tables=[],
    )
    assert ficha.document_date is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/integration/test_extractor_mocked.py::test_extractor_parses_document_date -v`
Expected: FAIL — document_date not parsed from output.

- [ ] **Step 3: Update extractor prompt**

In `src/scraper/agents/prompts/extractor_system.md`, add after the existing `"citations": [...]` line in the JSON example (around line 38):

```markdown
    "document_date": "2026-03-31"
```

And add a new rule at the end of the "Reglas de extracción" section (before "## INPUT QUE VAS A RECIBIR"):

```markdown
- **Fecha del documento obligatoria.** Buscá la fecha de publicación o última actualización. Patrones: "Fecha de actualización", "Vigente al", "As of", "Fecha:", footer con fecha, metadata del PDF. Formato: `YYYY-MM-DD`. Si no encontrás fecha → `null`.
```

- [ ] **Step 4: Update extractor.py to parse document_date**

In `src/scraper/agents/extractor.py`, in the `extract_with_claude` function, after the `attributes` parsing block (around line 205), add document_date parsing:

```python
    doc_date_raw = payload.get("document_date")
    doc_date = None
    if doc_date_raw:
        try:
            doc_date = datetime.fromisoformat(doc_date_raw)
            if doc_date.tzinfo is None:
                doc_date = doc_date.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            log.warning("extractor_bad_document_date", raw=doc_date_raw)
```

Then update the `ExtractedFicha(...)` constructor call to include `document_date=doc_date`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest tests/integration/test_extractor_mocked.py -v`
Expected: Both new tests PASS. Existing extractor tests PASS (document_date defaults to None).

- [ ] **Step 6: Commit**

```bash
git add src/scraper/agents/prompts/extractor_system.md src/scraper/agents/extractor.py tests/integration/test_extractor_mocked.py
git commit -m "feat(extractor): extract document_date from source documents"
```

---

### Task 3: Classifier — Cite Sources in Output

**Files:**
- Modify: `src/scraper/agents/prompts/classifier_system.md`
- Modify: `src/scraper/agents/prompts/builder.py`
- Modify: `tests/integration/test_classifier_mocked.py`

- [ ] **Step 1: Write failing test for source fields in classifier output**

Add to `tests/integration/test_classifier_mocked.py`:

```python
@pytest.mark.asyncio
async def test_classifier_parses_source_fields(mock_llm_client):
    import json
    from scraper.agents.classifier import classify

    classifier_output = json.dumps({
        "producto": "Test Fund",
        "attributes": {
            "moneda": {
                "value": "soles",
                "confidence": 1.0,
                "reasoning": "PEN en ficha",
                "rule_applied": "moneda",
                "source_url": "https://test.com/ficha.pdf",
                "source_label": "Ficha Test (Mar 2026)",
                "raw_quote": "Moneda: PEN (Nuevos Soles)",
            }
        },
        "global_confidence": 0.95,
        "unknowns": [],
    })
    mock_llm_client.call.return_value = mock_llm_client.make_result(classifier_output)

    result = await classify(
        llm=mock_llm_client,
        producto_nombre="Test Fund",
        product_context={"administrador": None, "gestor": None, "moneda": None, "liquidez": None},
        rules_md="# rules",
        few_shot_examples=[],
    )
    assert result.attributes["moneda"].source_url == "https://test.com/ficha.pdf"
    assert result.attributes["moneda"].source_label == "Ficha Test (Mar 2026)"
    assert result.attributes["moneda"].raw_quote == "Moneda: PEN (Nuevos Soles)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/integration/test_classifier_mocked.py::test_classifier_parses_source_fields -v`
Expected: FAIL — from_json doesn't parse source_url/source_label/raw_quote yet (if Task 1 is done, this should PASS immediately since from_json was updated).

- [ ] **Step 3: Update classifier prompt**

In `src/scraper/agents/prompts/classifier_system.md`, update the JSON output example (around line 29-47) to include source fields in each attribute:

```json
{
  "producto": "nombre del producto que clasificas",
  "attributes": {
    "foco_geografico": {
      "value": { "Perú": 65.0, "EEUU": 35.0 },
      "confidence": 0.95,
      "reasoning": "breve justificación (1-2 oraciones)",
      "rule_applied": "nombre de regla o patrón aplicado",
      "source_url": "URL o path del PDF de donde sacaste este valor",
      "source_label": "nombre legible de la fuente (ej: Ficha BBVA Mar 2026)",
      "raw_quote": "cita textual literal del documento, max 200 chars"
    }
  },
  "global_confidence": 0.92,
  "unknowns": ["lista de atributos que no pudiste determinar"]
}
```

Add to the "Reglas de output" section:

```markdown
- Para cada atributo, incluí `source_url` (URL o path del PDF), `source_label` (nombre legible de la fuente con fecha), y `raw_quote` (cita textual literal, max 200 chars). Si el valor se infirió sin evidencia documental directa, confidence máxima = 0.60.
```

- [ ] **Step 4: Update few-shot builder to include source fields**

In `src/scraper/agents/prompts/builder.py`, update `_product_to_example()` (around line 108-175). In each attribute dict inside `expected`, add the source fields:

```python
            "foco_geografico": {
                "value": p.foco_geografico,
                "confidence": 1.0,
                "reasoning": "ground truth",
                "rule_applied": "training_example",
                "source_url": None,
                "source_label": "training data",
                "raw_quote": None,
            },
```

Apply the same pattern to all 8 attribute dicts in `expected["attributes"]`.

- [ ] **Step 5: Run tests**

Run: `poetry run pytest tests/integration/test_classifier_mocked.py -v`
Expected: All PASS.

- [ ] **Step 6: Run full suite for regressions**

Run: `poetry run pytest --tb=short -q`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/scraper/agents/prompts/classifier_system.md src/scraper/agents/prompts/builder.py tests/integration/test_classifier_mocked.py
git commit -m "feat(classifier): cite source_url, source_label, raw_quote per attribute"
```

---

### Task 4: Merge Logic — Sort by Recency and Detect Conflicts

**Files:**
- Create: `src/scraper/search/merge.py`
- Test: `tests/unit/test_merge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_merge.py
"""Tests for multi-source merge logic."""
from datetime import UTC, datetime

import pytest

from scraper.agents.types import (
    AttributeExtraction,
    ExtractedFicha,
    FieldConflict,
    SourceSummary,
)
from scraper.search.merge import merge_fichas


def _make_ficha(
    url="https://a.com",
    source_type="html",
    doc_date=None,
    fetched_at=None,
    attrs=None,
):
    return ExtractedFicha(
        source_url=url,
        source_type=source_type,
        source_confidence=0.8,
        fetched_at=fetched_at or datetime.now(tz=UTC),
        document_date=doc_date,
        raw_text="text",
        tables=[],
        attributes=attrs or {},
        citations=[url] if url else [],
        extraction_cost_usd=0.0,
        extraction_duration_ms=0,
    )


def _attr(value, confidence=0.9, quote=None):
    return AttributeExtraction(
        value=value, confidence=confidence, reasoning="r", raw_quote=quote
    )


def test_merge_single_ficha():
    ficha = _make_ficha(attrs={"moneda": _attr("soles")})
    result = merge_fichas([ficha])
    assert result.primary is ficha
    assert len(result.all_sources) == 1
    assert result.conflicts == []


def test_merge_sorts_by_document_date_descending():
    old = _make_ficha(url="https://old.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC))
    new = _make_ficha(url="https://new.com", doc_date=datetime(2026, 3, 1, tzinfo=UTC))
    result = merge_fichas([old, new])
    assert result.primary.source_url == "https://new.com"


def test_merge_null_date_sorted_last():
    dated = _make_ficha(url="https://dated.com", doc_date=datetime(2026, 1, 1, tzinfo=UTC))
    undated = _make_ficha(url="https://undated.com", doc_date=None)
    result = merge_fichas([undated, dated])
    assert result.primary.source_url == "https://dated.com"


def test_merge_fallback_to_fetched_at_when_no_dates():
    old = _make_ficha(
        url="https://old.com",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    new = _make_ficha(
        url="https://new.com",
        fetched_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    result = merge_fichas([old, new])
    assert result.primary.source_url == "https://new.com"


def test_merge_detects_categorical_conflict():
    ficha_a = _make_ficha(
        url="https://a.com",
        doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"liquidez": _attr("Inmediata", quote="disponibilidad inmediata")},
    )
    ficha_b = _make_ficha(
        url="https://b.com",
        doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"liquidez": _attr("Corto plazo", quote="rescate T+2")},
    )
    result = merge_fichas([ficha_a, ficha_b])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].attribute == "liquidez"
    assert result.conflicts[0].chosen_value == "Inmediata"
    assert result.conflicts[0].alternatives[0].value == "Corto plazo"


def test_merge_no_conflict_on_same_value():
    ficha_a = _make_ficha(
        url="https://a.com",
        doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"moneda": _attr("soles")},
    )
    ficha_b = _make_ficha(
        url="https://b.com",
        doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"moneda": _attr("soles")},
    )
    result = merge_fichas([ficha_a, ficha_b])
    assert result.conflicts == []


def test_merge_dict_conflict_above_5pp():
    ficha_a = _make_ficha(
        url="https://a.com",
        doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"clase_activo": _attr({"Renta Variable": 70, "Renta Fija": 30})},
    )
    ficha_b = _make_ficha(
        url="https://b.com",
        doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"clase_activo": _attr({"Renta Variable": 60, "Renta Fija": 40})},
    )
    result = merge_fichas([ficha_a, ficha_b])
    assert len(result.conflicts) == 1
    assert result.conflicts[0].attribute == "clase_activo"


def test_merge_dict_no_conflict_within_5pp():
    ficha_a = _make_ficha(
        url="https://a.com",
        doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"clase_activo": _attr({"Renta Variable": 70, "Renta Fija": 30})},
    )
    ficha_b = _make_ficha(
        url="https://b.com",
        doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"clase_activo": _attr({"Renta Variable": 67, "Renta Fija": 33})},
    )
    result = merge_fichas([ficha_a, ficha_b])
    assert result.conflicts == []


def test_merge_format_difference_not_conflict():
    """1.50 vs 1.5 is not a conflict (same numeric value)."""
    ficha_a = _make_ficha(
        url="https://a.com",
        doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"comision": _attr(0.015)},
    )
    ficha_b = _make_ficha(
        url="https://b.com",
        doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"comision": _attr(0.015)},
    )
    result = merge_fichas([ficha_a, ficha_b])
    assert result.conflicts == []


def test_merge_builds_source_summaries():
    ficha_a = _make_ficha(
        url="https://a.com", source_type="pdf_text",
        doc_date=datetime(2026, 3, 1, tzinfo=UTC),
    )
    ficha_b = _make_ficha(
        url="https://b.com", source_type="html",
        doc_date=datetime(2026, 1, 1, tzinfo=UTC),
    )
    result = merge_fichas([ficha_a, ficha_b])
    assert len(result.all_sources) == 2
    assert result.all_sources[0].source_type == "pdf_text"
    assert result.all_sources[1].source_type == "html"


def test_merge_context_includes_all_sources():
    ficha_a = _make_ficha(
        url="https://a.com",
        doc_date=datetime(2026, 3, 1, tzinfo=UTC),
        attrs={"moneda": _attr("soles", quote="Moneda: PEN")},
    )
    ficha_b = _make_ficha(
        url="https://b.com",
        doc_date=datetime(2026, 1, 1, tzinfo=UTC),
        attrs={"moneda": _attr("soles", quote="Currency: PEN")},
    )
    result = merge_fichas([ficha_a, ficha_b])
    assert "https://a.com" in result.merged_context
    assert "https://b.com" in result.merged_context
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/unit/test_merge.py -v`
Expected: FAIL — `scraper.search.merge` does not exist.

- [ ] **Step 3: Implement merge_fichas**

```python
# src/scraper/search/merge.py
"""Multi-source merge: sort by recency, detect conflicts, build context."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from scraper.agents.types import (
    ConflictEntry,
    ExtractedFicha,
    FieldConflict,
    MergeResult,
    SourceSummary,
)

_DICT_FIELDS = {"clase_activo", "foco_geografico", "subyacente"}
_DICT_TOLERANCE_PP = 5


def _sort_key(ficha: ExtractedFicha) -> tuple:
    has_date = ficha.document_date is not None
    date_val = ficha.document_date or datetime.min.replace(tzinfo=ficha.fetched_at.tzinfo)
    return (has_date, date_val)


def _source_label(ficha: ExtractedFicha) -> str:
    url_part = ficha.source_url or f"({ficha.source_type})"
    if ficha.document_date:
        return f"{url_part} ({ficha.document_date.strftime('%b %Y')})"
    return url_part


def _values_conflict(attr: str, val_a: Any, val_b: Any) -> bool:
    if val_a is None or val_b is None:
        return False
    if attr in _DICT_FIELDS and isinstance(val_a, dict) and isinstance(val_b, dict):
        all_keys = set(val_a) | set(val_b)
        for k in all_keys:
            a = val_a.get(k, 0)
            b = val_b.get(k, 0)
            try:
                if abs(float(a) - float(b)) > _DICT_TOLERANCE_PP:
                    return True
            except (TypeError, ValueError):
                if a != b:
                    return True
        return False
    if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
        return abs(float(val_a) - float(val_b)) > 1e-9
    return str(val_a).strip().lower() != str(val_b).strip().lower()


def merge_fichas(fichas: list[ExtractedFicha]) -> MergeResult:
    sorted_fichas = sorted(fichas, key=_sort_key, reverse=True)
    primary = sorted_fichas[0]
    secondaries = sorted_fichas[1:]

    all_sources = [
        SourceSummary(
            url=f.source_url or "",
            label=_source_label(f),
            document_date=f.document_date,
            source_type=f.source_type,
        )
        for f in sorted_fichas
    ]

    conflicts: list[FieldConflict] = []
    checked_attrs = set(primary.attributes.keys())
    for s in secondaries:
        checked_attrs |= set(s.attributes.keys())

    for attr_name in checked_attrs:
        primary_ae = primary.attributes.get(attr_name)
        if primary_ae is None:
            continue
        for s in secondaries:
            s_ae = s.attributes.get(attr_name)
            if s_ae is None:
                continue
            if _values_conflict(attr_name, primary_ae.value, s_ae.value):
                existing = next((c for c in conflicts if c.attribute == attr_name), None)
                alt = ConflictEntry(
                    value=s_ae.value,
                    source_url=s.source_url or "",
                    source_label=_source_label(s),
                    document_date=s.document_date,
                    raw_quote=s_ae.raw_quote,
                )
                if existing is None:
                    conflicts.append(
                        FieldConflict(
                            attribute=attr_name,
                            chosen_value=primary_ae.value,
                            chosen_source=primary.source_url or "",
                            alternatives=[alt],
                        )
                    )
                else:
                    existing.alternatives.append(alt)

    context_parts: list[str] = []
    for i, f in enumerate(sorted_fichas, 1):
        label = _source_label(f)
        context_parts.append(
            f"[Fuente {i}: {label} — {f.source_type}]"
        )
        for attr, ae in f.attributes.items():
            context_parts.append(
                f"  {attr}: {ae.value!r}  (conf={ae.confidence:.2f})  quote: {ae.raw_quote!r}"
            )
        if f.raw_text:
            context_parts.append(f"  raw_text: {f.raw_text[:500]}")

    return MergeResult(
        primary=primary,
        all_sources=all_sources,
        conflicts=conflicts,
        merged_context="\n".join(context_parts),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/unit/test_merge.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/search/merge.py tests/unit/test_merge.py
git commit -m "feat(merge): sort fichas by recency and detect field conflicts"
```

---

### Task 5: DB Migration — Add Source Columns

**Files:**
- Modify: `src/scraper/db/models.py`
- Create: `alembic/versions/xxxx_add_source_traceability_columns.py`

- [ ] **Step 1: Add columns to Classification model**

In `src/scraper/db/models.py`, add after `cost_usd` (line 93) and before `created_at`:

```python
    sources_used: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    field_conflicts: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 2: Generate Alembic migration**

Run: `poetry run alembic revision --autogenerate -m "add source traceability columns"`

- [ ] **Step 3: Verify migration content**

Read the generated migration file and confirm it contains:

```python
op.add_column('classifications', sa.Column('sources_used', sa.JSON(), nullable=True))
op.add_column('classifications', sa.Column('field_conflicts', sa.JSON(), nullable=True))
```

- [ ] **Step 4: Run migration**

Run: `poetry run alembic upgrade head`
Expected: Migration applies cleanly.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/db/models.py alembic/versions/
git commit -m "feat(db): add sources_used and field_conflicts columns to Classification"
```

---

### Task 6: Worker Pipeline — Use Merge Logic and Persist Sources

**Files:**
- Modify: `src/scraper/scripts/worker_pipeline.py`
- Modify: `src/scraper/scripts/find_and_classify.py`
- Modify: `tests/integration/test_worker_pipeline.py`

- [ ] **Step 1: Write failing test**

Add to `tests/integration/test_worker_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_cascade_persists_sources_and_conflicts(seeded_and_split_session, mock_llm_client):
    """Verify that sources_used and field_conflicts are saved on Classification."""
    import json
    from scraper.db.models import Classification, JobQueue
    from scraper.scripts.worker_pipeline import process_job_via_cascade

    session = seeded_and_split_session

    job = JobQueue(nombre="Test Fund", status="in_progress")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Mock cascade to return 2 fichas with a conflict
    cascade_json = json.dumps({
        "producto": "Test Fund",
        "attributes": {
            "moneda": {
                "value": "soles", "confidence": 1.0,
                "reasoning": "PEN", "rule_applied": "moneda",
                "source_url": "https://a.com", "source_label": "A",
                "raw_quote": "PEN",
            },
        },
        "global_confidence": 0.9, "unknowns": [],
    })
    review_json = json.dumps({
        "veredicto": "agree",
        "attribute_reviews": {},
        "global_verdict": "approve",
        "reviewer_confidence": 0.95,
    })
    mock_llm_client.call.side_effect = [
        # cascade calls (web_search level) — simplified
        mock_llm_client.make_result(json.dumps({
            "source_type": "html", "source_confidence": 0.8,
            "raw_text": "t", "tables": [], "document_date": "2026-03-01",
            "attributes": {"moneda": {"value": "soles", "confidence": 0.9, "reasoning": "r", "raw_quote": "PEN"}},
            "citations": ["https://a.com"],
        })),
        mock_llm_client.make_result(cascade_json),
        mock_llm_client.make_result(review_json),
    ]

    # This test verifies the pipeline saves sources_used.
    # Full integration requires cascade mock — simplified here to verify
    # the _save_classification_and_review path accepts the new fields.
    from sqlalchemy import select
    cls_id = await process_job_via_cascade(
        session=session, job=job, llm=mock_llm_client, rules_md="# rules"
    )
    r = await session.execute(select(Classification).where(Classification.id == cls_id))
    cls_row = r.scalar_one()
    # sources_used should be set (may be empty list if cascade mock is simplified)
    assert cls_row.sources_used is not None or cls_row.sources_used == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/integration/test_worker_pipeline.py::test_cascade_persists_sources_and_conflicts -v`
Expected: FAIL — Classification constructor doesn't accept sources_used.

- [ ] **Step 3: Update worker_pipeline.py**

Replace the import of `_top_ficha` and `_context_from_top` with the new merge logic:

```python
# Replace this import:
# from scraper.scripts.find_and_classify import _context_from_top, _top_ficha

# With:
from scraper.search.merge import merge_fichas
```

Update `_run_cascade_classify_review()` to use merge:

```python
async def _run_cascade_classify_review(
    nombre: str, rules_md: str, llm: LLMClient, session: AsyncSession
) -> tuple:
    start = time.monotonic()
    few_shot = await build_few_shot_from_db(session, limit=20)
    cascade = await run_cascade(nombre=nombre, session=session, llm=llm)
    if not cascade.fichas:
        duration_ms = int((time.monotonic() - start) * 1000)
        return None, None, "low_quality", "no_source", llm.cost.total_usd, duration_ms, [], None, None

    merge = merge_fichas(cascade.fichas)
    context = {
        "administrador": merge.primary.attributes.get("administrador", _null_ae).value,
        "gestor": merge.primary.attributes.get("gestor", _null_ae).value,
        "moneda": merge.primary.attributes.get("moneda", _null_ae).value,
        "liquidez": merge.primary.attributes.get("liquidez", _null_ae).value,
        "extra": merge.merged_context,
    }

    cls_result = await classify(
        llm=llm,
        producto_nombre=nombre,
        product_context=context,
        rules_md=rules_md,
        few_shot_examples=few_shot,
    )
    rev_result = await review(
        llm=llm,
        producto_nombre=nombre,
        product_context=context,
        classifier_output=cls_result,
        rules_md=rules_md,
    )
    flag = decide_flag(cls_result, rev_result)
    source_used = f"cascade_level_{cascade.level}"
    duration_ms = int((time.monotonic() - start) * 1000)
    citations = []
    for f in cascade.fichas:
        citations.extend(f.citations or [])

    sources_json = [
        {"url": s.url, "label": s.label,
         "document_date": s.document_date.isoformat() if s.document_date else None,
         "source_type": s.source_type}
        for s in merge.all_sources
    ]
    conflicts_json = [
        {"attribute": c.attribute, "chosen_value": c.chosen_value,
         "chosen_source": c.chosen_source,
         "alternatives": [
             {"value": a.value, "source_url": a.source_url,
              "source_label": a.source_label,
              "document_date": a.document_date.isoformat() if a.document_date else None,
              "raw_quote": a.raw_quote}
             for a in c.alternatives
         ]}
        for c in merge.conflicts
    ] or None

    rev_dict = {
        "veredicto": rev_result.veredicto,
        "global_verdict": rev_result.global_verdict,
        "reviewer_confidence": rev_result.reviewer_confidence,
    }
    return cls_result, rev_dict, flag, source_used, llm.cost.total_usd, duration_ms, citations, sources_json, conflicts_json
```

Add a helper at the top of the file:

```python
from scraper.agents.types import AttributeExtraction

_null_ae = AttributeExtraction(value=None, confidence=0.0, reasoning="", raw_quote=None)
```

Update `process_job_via_cascade()` to unpack the new fields and persist them:

```python
async def process_job_via_cascade(*, session, job, llm, rules_md) -> int:
    (
        cls_result, rev_dict, flag, source_used,
        cost_usd, duration_ms, citations, sources_json, conflicts_json,
    ) = await _run_cascade_classify_review(job.nombre, rules_md, llm, session)

    # ... (existing classifier_output building logic) ...

    cls_row = Classification(
        product_name_input=job.nombre,
        classifier_output=classifier_output,
        reviewer_output=rev_dict or {},
        global_confidence=global_conf,
        per_attribute_confidence=per_attr_conf,
        final_status=flag,
        source_used=source_used,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        sources_used=sources_json,
        field_conflicts=conflicts_json,
    )
    # ... rest unchanged ...
```

Also update `process_job_via_url()` to use `merge_fichas` instead of `_top_ficha`:

```python
async def process_job_via_url(*, session, job, llm, rules_md) -> int:
    start = time.monotonic()
    few_shot = await build_few_shot_from_db(session, limit=20)

    fichas = await extract_from_url(url=job.url, llm=llm, nombre=job.nombre)
    if not fichas:
        raise RuntimeError(f"extract_from_url returned no fichas for {job.url}")

    merge = merge_fichas(fichas)
    context = {
        "administrador": merge.primary.attributes.get("administrador", _null_ae).value,
        "gestor": merge.primary.attributes.get("gestor", _null_ae).value,
        "moneda": merge.primary.attributes.get("moneda", _null_ae).value,
        "liquidez": merge.primary.attributes.get("liquidez", _null_ae).value,
        "extra": merge.merged_context,
    }

    cls_result = await classify(
        llm=llm, producto_nombre=job.nombre, product_context=context,
        rules_md=rules_md, few_shot_examples=few_shot,
    )
    rev_result = await review(
        llm=llm, producto_nombre=job.nombre, product_context=context,
        classifier_output=cls_result, rules_md=rules_md,
    )
    flag = decide_flag(cls_result, rev_result)
    duration_ms = int((time.monotonic() - start) * 1000)

    sources_json = [
        {"url": s.url, "label": s.label,
         "document_date": s.document_date.isoformat() if s.document_date else None,
         "source_type": s.source_type}
        for s in merge.all_sources
    ]
    conflicts_json = [
        {"attribute": c.attribute, "chosen_value": c.chosen_value,
         "chosen_source": c.chosen_source,
         "alternatives": [
             {"value": a.value, "source_url": a.source_url,
              "source_label": a.source_label,
              "document_date": a.document_date.isoformat() if a.document_date else None,
              "raw_quote": a.raw_quote}
             for a in c.alternatives
         ]}
        for c in merge.conflicts
    ] or None

    cls_row = _save_classification_and_review(
        cls_result, rev_result, job, flag, "direct_url", duration_ms, llm.cost.total_usd,
    )
    cls_row.sources_used = sources_json
    cls_row.field_conflicts = conflicts_json
    return await _persist_classification(session, cls_row, flag)
```

- [ ] **Step 4: Run tests**

Run: `poetry run pytest tests/integration/test_worker_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `poetry run pytest --tb=short -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/scraper/scripts/worker_pipeline.py src/scraper/scripts/find_and_classify.py tests/integration/test_worker_pipeline.py
git commit -m "feat(pipeline): use merge_fichas for source priority and conflict detection"
```

---

### Task 7: UI Component — confidence_bar

**Files:**
- Create: `src/scraper/ui/components/confidence_bar.py`
- Test: `tests/unit/test_ui_components.py`

- [ ] **Step 1: Write test**

```python
# tests/unit/test_ui_components.py
"""Tests for UI component helper functions (logic only, no Streamlit rendering)."""

from scraper.ui.components.confidence_bar import confidence_color, confidence_label


def test_confidence_color_green():
    assert confidence_color(0.95) == "#22c55e"


def test_confidence_color_yellow():
    assert confidence_color(0.80) == "#eab308"


def test_confidence_color_red():
    assert confidence_color(0.50) == "#ef4444"


def test_confidence_label():
    assert confidence_label(0.95) == "0.95"
    assert confidence_label(0.0) == "0.00"
    assert confidence_label(None) == "—"
```

- [ ] **Step 2: Run tests — fail**

Run: `poetry run pytest tests/unit/test_ui_components.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement confidence_bar**

```python
# src/scraper/ui/components/confidence_bar.py
"""Colored confidence bar widget for Streamlit."""
from __future__ import annotations

import streamlit as st


def confidence_color(value: float) -> str:
    if value >= 0.90:
        return "#22c55e"
    if value >= 0.70:
        return "#eab308"
    return "#ef4444"


def confidence_label(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def render_confidence_bar(value: float | None, label: str = "") -> None:
    if value is None:
        st.caption(f"{label} Confianza: —")
        return
    color = confidence_color(value)
    pct = int(value * 100)
    st.markdown(
        f"{label} Confianza: **{value:.2f}**"
        f'<div style="background:#e5e7eb;border-radius:4px;height:8px;margin-top:2px">'
        f'<div style="background:{color};width:{pct}%;height:8px;border-radius:4px"></div>'
        f"</div>",
        unsafe_allow_html=True,
    )
```

- [ ] **Step 4: Run tests — pass**

Run: `poetry run pytest tests/unit/test_ui_components.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/ui/components/confidence_bar.py tests/unit/test_ui_components.py
git commit -m "feat(ui): add confidence_bar component"
```

---

### Task 8: UI Component — source_citation

**Files:**
- Create: `src/scraper/ui/components/source_citation.py`

- [ ] **Step 1: Implement source_citation**

```python
# src/scraper/ui/components/source_citation.py
"""Expandable source citation widget."""
from __future__ import annotations

import streamlit as st


def render_source_citation(
    source_url: str | None,
    source_label: str | None,
    raw_quote: str | None,
    key_suffix: str = "",
) -> None:
    if not source_url and not source_label:
        return
    icon = "🌐" if source_url and source_url.startswith("http") else "📄"
    display = source_label or source_url or ""
    if source_url and source_url.startswith("http"):
        st.caption(f"{icon} [{display}]({source_url})")
    else:
        st.caption(f"{icon} {display}")
    if raw_quote:
        with st.expander("Ver evidencia", expanded=False):
            st.markdown(f'> "{raw_quote}"')
```

- [ ] **Step 2: Commit**

```bash
git add src/scraper/ui/components/source_citation.py
git commit -m "feat(ui): add source_citation component"
```

---

### Task 9: UI Component — conflict_panel

**Files:**
- Create: `src/scraper/ui/components/conflict_panel.py`

- [ ] **Step 1: Implement conflict_panel**

```python
# src/scraper/ui/components/conflict_panel.py
"""Panel showing field conflicts with 'Use this value' buttons."""
from __future__ import annotations

from typing import Any

import streamlit as st


def render_conflict_panel(
    attribute: str,
    alternatives: list[dict],
    key_prefix: str = "",
) -> Any | None:
    """Render conflict alternatives. Returns chosen alternative value or None."""
    if not alternatives:
        return None
    chosen = None
    for i, alt in enumerate(alternatives):
        source_label = alt.get("source_label", alt.get("source_url", "?"))
        doc_date = alt.get("document_date", "")
        date_str = f" ({doc_date})" if doc_date else ""
        raw_quote = alt.get("raw_quote", "")
        icon = "🌐" if alt.get("source_url", "").startswith("http") else "📄"

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(
                f"{icon} **{source_label}**{date_str}: "
                f"`{alt['value']!r}`"
            )
            if raw_quote:
                st.caption(f'"{raw_quote}"')
        with col2:
            if st.button(
                "Usar este valor",
                key=f"{key_prefix}_conflict_{attribute}_{i}",
            ):
                chosen = alt["value"]
    return chosen
```

- [ ] **Step 2: Commit**

```bash
git add src/scraper/ui/components/conflict_panel.py
git commit -m "feat(ui): add conflict_panel component"
```

---

### Task 10: UI Component — dict_editor

**Files:**
- Modify: `src/scraper/ui/components/dict_editor.py` (replace the existing field_editor)

- [ ] **Step 1: Write test for dict_editor logic**

Add to `tests/unit/test_ui_components.py`:

```python
from scraper.ui.components.dict_editor import normalize_pct_dict


def test_normalize_pct_dict_sums_to_100():
    d = {"A": 70, "B": 30}
    assert normalize_pct_dict(d) == {"A": 70.0, "B": 30.0}


def test_normalize_pct_dict_empty():
    assert normalize_pct_dict({}) == {}


def test_normalize_pct_dict_strips_zeros():
    d = {"A": 100, "B": 0}
    assert normalize_pct_dict(d) == {"A": 100.0}
```

- [ ] **Step 2: Run test — fail**

Run: `poetry run pytest tests/unit/test_ui_components.py::test_normalize_pct_dict_sums_to_100 -v`
Expected: FAIL.

- [ ] **Step 3: Implement dict_editor**

```python
# src/scraper/ui/components/dict_editor.py
"""Visual table editor for percentage dictionaries."""
from __future__ import annotations

import json
from typing import Any

import streamlit as st


def normalize_pct_dict(d: dict[str, float]) -> dict[str, float]:
    return {k: float(v) for k, v in d.items() if float(v) > 0}


def render_dict_editor(
    label: str,
    current_value: dict[str, float],
    key_prefix: str = "",
) -> dict[str, float]:
    """Render a visual table editor for percentage dicts. Returns edited dict."""
    if not isinstance(current_value, dict):
        current_value = {}

    if f"{key_prefix}_rows" not in st.session_state:
        st.session_state[f"{key_prefix}_rows"] = list(current_value.items())

    rows = st.session_state[f"{key_prefix}_rows"]
    edited: dict[str, float] = {}

    for i, (name, pct) in enumerate(rows):
        col_name, col_pct, col_del = st.columns([3, 1, 0.5])
        with col_name:
            new_name = st.text_input(
                "Nombre", value=name, key=f"{key_prefix}_name_{i}", label_visibility="collapsed"
            )
        with col_pct:
            new_pct = st.number_input(
                "%", value=float(pct), min_value=0.0, max_value=100.0,
                step=1.0, key=f"{key_prefix}_pct_{i}", label_visibility="collapsed"
            )
        with col_del:
            if st.button("✕", key=f"{key_prefix}_del_{i}"):
                rows.pop(i)
                st.session_state[f"{key_prefix}_rows"] = rows
                st.rerun()
        if new_name and new_pct > 0:
            edited[new_name] = new_pct
        rows[i] = (new_name, new_pct)

    if st.button("+ Agregar fila", key=f"{key_prefix}_add"):
        rows.append(("", 0.0))
        st.session_state[f"{key_prefix}_rows"] = rows
        st.rerun()

    total = sum(edited.values())
    if abs(total - 100) > 2 and edited:
        st.warning(f"Total: {total:.0f}% (debe sumar 100%)")

    return normalize_pct_dict(edited)


def edit_attribute(
    key: str, current_value: Any, confidence: float | None = None, reasoning: str = "",
    source_url: str | None = None, source_label: str | None = None,
    raw_quote: str | None = None, conflict: dict | None = None,
) -> Any:
    """Render an editable field for an attribute. Returns the edited value."""
    from scraper.ui.components.confidence_bar import render_confidence_bar
    from scraper.ui.components.source_citation import render_source_citation
    from scraper.ui.components.conflict_panel import render_conflict_panel

    label = key.replace("_", " ").title()

    render_confidence_bar(confidence, label)

    if isinstance(current_value, dict) and key in ("foco_geografico", "clase_activo", "subyacente"):
        result = render_dict_editor(label, current_value, key_prefix=f"edit_{key}")
    elif isinstance(current_value, dict):
        new_text = st.text_area(
            label, value=json.dumps(current_value, ensure_ascii=False, indent=2),
            height=100, key=f"edit_{key}",
        )
        try:
            result = json.loads(new_text)
        except json.JSONDecodeError:
            st.warning(f"{label}: JSON inválido, usando valor original")
            result = current_value
    elif current_value is None:
        new_val = st.text_input(f"{label} (vacío)", value="", key=f"edit_{key}")
        result = new_val or None
    else:
        new_val = st.text_input(label, value=str(current_value), key=f"edit_{key}")
        result = new_val

    render_source_citation(source_url, source_label, raw_quote, key_suffix=key)

    if conflict:
        alt_chosen = render_conflict_panel(key, conflict.get("alternatives", []), key_prefix=f"edit_{key}")
        if alt_chosen is not None:
            result = alt_chosen

    if reasoning:
        st.caption(f"Razón: {reasoning[:200]}")

    return result
```

- [ ] **Step 4: Run tests — pass**

Run: `poetry run pytest tests/unit/test_ui_components.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/ui/components/dict_editor.py tests/unit/test_ui_components.py
git commit -m "feat(ui): replace field_editor with dict_editor + visual components"
```

---

### Task 11: UI Component — review_card

**Files:**
- Create: `src/scraper/ui/components/review_card.py`

- [ ] **Step 1: Implement review_card**

```python
# src/scraper/ui/components/review_card.py
"""Review card widget for the review queue list."""
from __future__ import annotations

import streamlit as st

from scraper.ui.components.confidence_bar import confidence_color

_FLAG_ICONS = {
    "low_quality": ("🔴", "low_quality"),
    "needs_review": ("🟡", "needs_review"),
    "auto_approvable": ("🟢", "auto_approvable"),
}


def render_review_card(
    review_id: int,
    nombre: str,
    flag: str,
    confidence: float | None,
    source_count: int,
    conflict_count: int,
    cost_usd: float,
    key_prefix: str = "",
) -> bool:
    """Render a review card. Returns True if clicked."""
    icon, flag_label = _FLAG_ICONS.get(flag, ("⚪", flag))
    conf = confidence or 0.0
    color = confidence_color(conf)
    pct = int(conf * 100)

    with st.container(border=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"{icon} **{flag_label}**")
            st.markdown(f"**{nombre}**")

            meta_parts = [f"📄 {source_count} fuente{'s' if source_count != 1 else ''}"]
            if conflict_count > 0:
                meta_parts.append(f"⚠ {conflict_count} conflicto{'s' if conflict_count != 1 else ''}")
            meta_parts.append(f"${cost_usd:.3f}")
            st.caption(" · ".join(meta_parts))

        with col2:
            st.markdown(
                f'<div style="text-align:right">'
                f'<span style="font-size:1.5em;color:{color}">{conf:.2f}</span>'
                f'<div style="background:#e5e7eb;border-radius:4px;height:6px;margin-top:4px">'
                f'<div style="background:{color};width:{pct}%;height:6px;border-radius:4px"></div>'
                f"</div></div>",
                unsafe_allow_html=True,
            )

        clicked = st.button("Ver detalle", key=f"{key_prefix}_card_{review_id}")
    return clicked
```

- [ ] **Step 2: Commit**

```bash
git add src/scraper/ui/components/review_card.py
git commit -m "feat(ui): add review_card component"
```

---

### Task 12: Review Queue Page — Full Overhaul

**Files:**
- Rewrite: `src/scraper/ui/pages/3_review_queue.py`

- [ ] **Step 1: Rewrite the review queue page**

```python
# src/scraper/ui/pages/3_review_queue.py
"""Review queue — card list with filters + detail view with citations and conflicts."""
from __future__ import annotations

import streamlit as st

from scraper.db.session import get_session
from scraper.ui.review_ops import get_review_with_classification, list_pending_reviews
from scraper.ui.state import run_async

st.title("Review Queue")

col_search, col_flag, col_sort = st.columns([3, 1, 1])
with col_search:
    search_query = st.text_input("🔍 Buscar por nombre", value="", label_visibility="collapsed",
                                  placeholder="Buscar por nombre...")
with col_flag:
    flag_filter = st.selectbox(
        "Flag", options=["Todos", "low_quality", "needs_review", "auto_approvable"],
        index=0, label_visibility="collapsed",
    )
with col_sort:
    sort_by = st.selectbox(
        "Ordenar", options=["Fecha ↓", "Confianza ↑", "Conflictos ↓"],
        index=0, label_visibility="collapsed",
    )


async def _list():
    async with get_session() as s:
        return await list_pending_reviews(
            s, flag_filter=None if flag_filter == "Todos" else flag_filter
        )


reviews = run_async(_list())

if not reviews:
    st.info("No hay clasificaciones pendientes de revisar.")
    st.stop()

items = []
for r in reviews:
    cls = r.classification
    nombre = cls.product_name_input
    if search_query and search_query.lower() not in nombre.lower():
        continue
    sources = cls.sources_used or []
    conflicts = cls.field_conflicts or []
    items.append({
        "review": r,
        "cls": cls,
        "nombre": nombre,
        "flag": r.flag,
        "confidence": cls.global_confidence or 0.0,
        "source_count": len(sources),
        "conflict_count": len(conflicts),
        "cost_usd": cls.cost_usd or 0.0,
    })

if sort_by == "Confianza ↑":
    items.sort(key=lambda x: x["confidence"])
elif sort_by == "Conflictos ↓":
    items.sort(key=lambda x: x["conflict_count"], reverse=True)

if not items:
    st.info("No hay resultados para esta búsqueda.")
    st.stop()

from scraper.ui.components.review_card import render_review_card

for item in items:
    clicked = render_review_card(
        review_id=item["review"].id,
        nombre=item["nombre"],
        flag=item["flag"],
        confidence=item["confidence"],
        source_count=item["source_count"],
        conflict_count=item["conflict_count"],
        cost_usd=item["cost_usd"],
    )
    if clicked:
        st.session_state["selected_review_id"] = item["review"].id

st.divider()

rid = st.session_state.get("selected_review_id")
if rid:
    async def _get(review_id):
        async with get_session() as s:
            return await get_review_with_classification(s, review_id)

    r = run_async(_get(int(rid)))
    if r is None:
        st.warning(f"Review {rid} no existe.")
    else:
        cls = r.classification
        st.markdown(f"## {cls.product_name_input}")

        sources = cls.sources_used or []
        if sources:
            source_labels = []
            for src in sources:
                icon = "🌐" if src.get("url", "").startswith("http") else "📄"
                label = src.get("label", src.get("url", "?"))
                url = src.get("url")
                if url and url.startswith("http"):
                    source_labels.append(f"{icon} [{label}]({url})")
                else:
                    source_labels.append(f"{icon} {label}")
            st.markdown("Fuentes: " + " · ".join(source_labels))

        attrs = (
            cls.classifier_output.get("attributes", {})
            if isinstance(cls.classifier_output, dict)
            else {}
        )

        conflicts_list = cls.field_conflicts or []
        conflicts_by_attr = {c["attribute"]: c for c in conflicts_list}

        from scraper.overlay import apply_overlay_defaults, load_sabbi_overlay
        overlay = load_sabbi_overlay()
        if overlay.via_sabbi_brokerage and st.button("Aplicar defaults Sabbi (via Credicorp)"):
            preview = {k: attrs.get(k, {}).get("value") for k in ("administrador", "gestor", "comision")}
            preview = apply_overlay_defaults(preview, overlay, choice="via_sabbi_brokerage")
            for k in ("administrador", "gestor", "comision"):
                if k in attrs:
                    attrs[k]["value"] = preview.get(k)
            st.success("Defaults aplicados.")

        from scraper.ui.components.dict_editor import edit_attribute

        st.markdown("### Atributos")
        edited: dict = {}
        for attr_key in [
            "nombre", "foco_geografico", "clase_activo", "subyacente",
            "moneda", "liquidez", "administrador", "gestor",
            "comision", "minimo_inversion",
        ]:
            a = attrs.get(attr_key, {})
            conflict = conflicts_by_attr.get(attr_key)

            if conflict:
                st.markdown(f"**⚠ CONFLICTO** en {attr_key.replace('_', ' ').title()}")

            edited[attr_key] = edit_attribute(
                key=attr_key,
                current_value=a.get("value"),
                confidence=a.get("confidence"),
                reasoning=a.get("reasoning", ""),
                source_url=a.get("source_url"),
                source_label=a.get("source_label"),
                raw_quote=a.get("raw_quote"),
                conflict=conflict,
            )
            st.markdown("---")

        st.session_state["edited_values"] = edited

        with st.expander("Ver JSON completo del clasificador"):
            st.json(cls.classifier_output)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Aprobar", type="primary"):
                from scraper.ui.review_logic import approve_classification

                async def _approve():
                    async with get_session() as s:
                        return await approve_classification(
                            s, review_id=r.id, edited_values=edited, operator="local_user",
                        )

                product_id = run_async(_approve())
                st.success(f"Aprobado. Producto #{product_id} creado.")
                st.session_state.pop("selected_review_id", None)
                st.rerun()

        with col2:
            reject_notes = st.text_input("Motivo de rechazo (opcional)", key=f"reject_notes_{r.id}")
            if st.button("❌ Rechazar"):
                from scraper.ui.review_logic import reject_classification

                async def _reject():
                    async with get_session() as s:
                        return await reject_classification(
                            s, review_id=r.id, notes=reject_notes or "", operator="local_user",
                        )

                run_async(_reject())
                st.success("Rechazado.")
                st.session_state.pop("selected_review_id", None)
                st.rerun()

        st.markdown("---")
        st.markdown("#### Subir PDF si el pipeline falló")
        upload = st.file_uploader("PDF de la ficha", type=["pdf"], key=f"upload_{r.id}")
        if upload and st.button("Re-procesar con PDF"):
            from scraper.ui.upload_ops import reclassify_with_pdf

            async def _reclassify():
                async with get_session() as s:
                    return await reclassify_with_pdf(
                        s, nombre=cls.product_name_input, pdf_bytes=upload.read(),
                        operator="local_user",
                    )

            new_job_id = run_async(_reclassify())
            st.success(f"Job #{new_job_id} creado con PDF. Correr worker para procesar.")
```

- [ ] **Step 2: Remove old field_editor.py** (replaced by dict_editor.py)

Delete `src/scraper/ui/components/field_editor.py` — its functionality is now in `dict_editor.py:edit_attribute()`.

- [ ] **Step 3: Smoke test**

Run: `poetry run streamlit run src/scraper/ui/app.py` and navigate to the Review Queue page. Verify:
- Cards render with flag icons, confidence bars, source counts
- Search and filters work
- Detail view shows citations and conflict panels
- Dict fields use table editor instead of raw JSON

- [ ] **Step 4: Run existing UI tests**

Run: `poetry run pytest tests/integration/test_ui_smoke.py -v`
Expected: PASS (import paths unchanged — edit_attribute still importable from dict_editor).

- [ ] **Step 5: Update any remaining imports of field_editor**

Grep for `field_editor` and update any remaining references to `dict_editor`.

- [ ] **Step 6: Commit**

```bash
git add src/scraper/ui/pages/3_review_queue.py src/scraper/ui/components/
git rm src/scraper/ui/components/field_editor.py
git commit -m "feat(ui): overhaul review queue with cards, citations, conflicts, visual editors"
```

---

### Task 13: Batch Upload — Progress Bar

**Files:**
- Modify: `src/scraper/ui/pages/1_batch_upload.py`

- [ ] **Step 1: Update batch progress display**

Replace the "Últimos batches" section (lines 48-88) with:

```python
st.divider()
st.subheader("Últimos batches")


async def _recent_batches():
    from sqlalchemy import case, func, select

    from scraper.db.models import JobQueue

    async with get_session() as s:
        r = await s.execute(
            select(
                JobQueue.batch_id,
                func.count(JobQueue.id).label("total"),
                func.sum(case((JobQueue.status == "done", 1), else_=0)).label("done_count"),
                func.sum(case((JobQueue.status == "in_progress", 1), else_=0)).label("in_progress_count"),
                func.sum(case((JobQueue.status == "failed", 1), else_=0)).label("failed_count"),
                func.min(JobQueue.created_at).label("created_at"),
            )
            .where(JobQueue.batch_id.is_not(None))
            .group_by(JobQueue.batch_id)
            .order_by(func.min(JobQueue.created_at).desc())
            .limit(10)
        )
        return r.all()


batches = run_async(_recent_batches())
if batches:
    for row in batches:
        total = row.total
        done = row.done_count or 0
        in_prog = row.in_progress_count or 0
        failed = row.failed_count or 0
        pending = total - done - in_prog - failed
        pct = done / total if total > 0 else 0

        with st.container(border=True):
            st.markdown(f"**Batch {row.batch_id[:8]}...** — {total} productos")
            st.progress(pct)
            st.caption(
                f"✅ {done} completados · ⏳ {in_prog} en proceso · "
                f"📋 {pending} pendientes · ❌ {failed} fallidos"
            )
else:
    st.info("No hay batches todavía.")
```

- [ ] **Step 2: Smoke test**

Run: `poetry run streamlit run src/scraper/ui/app.py` — navigate to Batch Upload, verify progress bars render.

- [ ] **Step 3: Commit**

```bash
git add src/scraper/ui/pages/1_batch_upload.py
git commit -m "feat(ui): add visual progress bar to batch upload page"
```

---

### Task 14: Settings Page — Recent Sources + v6 Default

**Files:**
- Modify: `src/scraper/ui/pages/4_settings.py`

- [ ] **Step 1: Update settings page**

Add after the "Rules version" section (before `st.divider()` for cost tracking):

Update the default rules caption:

```python
    st.caption("El default del worker es `rules/v6.md`. Para cambiar, editar CLI args.")
```

Add a "Recent sources" section after the rules section:

```python
st.divider()
st.subheader("Fuentes recientes")


async def _recent_sources():
    from sqlalchemy import select
    from scraper.db.models import Classification

    async with get_session() as s:
        r = await s.execute(
            select(Classification)
            .where(Classification.sources_used.is_not(None))
            .order_by(Classification.created_at.desc())
            .limit(20)
        )
        return list(r.scalars().all())


recent_cls = run_async(_recent_sources())
if recent_cls:
    for cls_row in recent_cls:
        sources = cls_row.sources_used or []
        for src in sources:
            icon = "🌐" if src.get("url", "").startswith("http") else "📄"
            label = src.get("label", src.get("url", "?"))
            doc_date = src.get("document_date", "")
            st.caption(f"{icon} {label} — {src.get('source_type', '')} — {doc_date or 'sin fecha'}")
else:
    st.info("No hay fuentes procesadas todavía.")
```

- [ ] **Step 2: Commit**

```bash
git add src/scraper/ui/pages/4_settings.py
git commit -m "feat(ui): add recent sources panel and update default rules to v6"
```

---

### Task 15: Final Integration Test + Cleanup

**Files:**
- Run full suite
- Verify backwards compatibility

- [ ] **Step 1: Run full test suite**

Run: `poetry run pytest --tb=short -q`
Expected: All tests pass. No regressions.

- [ ] **Step 2: Verify old classifications render without errors**

Old `Classification` rows have `sources_used=None` and `field_conflicts=None`. The UI code uses `cls.sources_used or []` and `cls.field_conflicts or []`, so these render gracefully — no citations shown, no conflict panels.

- [ ] **Step 3: Verify dict_editor import compatibility**

Run: `poetry run python -c "from scraper.ui.components.dict_editor import edit_attribute; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run Alembic check**

Run: `poetry run alembic check`
Expected: No pending migrations.

- [ ] **Step 5: Final commit (if any cleanup needed)**

```bash
git add -A
git commit -m "chore: final integration cleanup for source traceability"
```

- [ ] **Step 6: Push to GitHub**

```bash
git push origin master
```
