"""Dataclasses for classifier and reviewer outputs."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AttributeClassification:
    value: Any
    confidence: float
    reasoning: str
    rule_applied: str
    source_url: str | None = None
    source_label: str | None = None
    raw_quote: str | None = None


@dataclass(frozen=True)
class ClassificationResult:
    producto: str
    attributes: dict[str, AttributeClassification]
    global_confidence: float
    unknowns: list[str] = field(default_factory=list)
    class_options: list[dict[str, Any]] | None = None

    def min_attribute_confidence(self) -> float:
        if not self.attributes:
            return 0.0
        return min(a.confidence for a in self.attributes.values())

    def to_json(self) -> str:
        payload = {
            "producto": self.producto,
            "global_confidence": self.global_confidence,
            "unknowns": list(self.unknowns),
            "attributes": {
                k: asdict(v) for k, v in self.attributes.items()
            },
        }
        if self.class_options:
            payload["class_options"] = self.class_options
        return json.dumps(payload, ensure_ascii=False)

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
            class_options=p.get("class_options"),
        )


@dataclass(frozen=True)
class AttributeReview:
    verdict: str  # agree | disagree | partial
    reason: str = ""
    suggested_value: Any = None


@dataclass(frozen=True)
class ReviewResult:
    veredicto: str
    attribute_reviews: dict[str, AttributeReview]
    global_verdict: str
    reviewer_confidence: float

    def has_disagreement(self) -> bool:
        if self.veredicto == "disagree":
            return True
        return any(a.verdict == "disagree" for a in self.attribute_reviews.values())

    @classmethod
    def from_json(cls, data: str | dict) -> ReviewResult:
        p = json.loads(data) if isinstance(data, str) else data
        reviews = {
            k: AttributeReview(
                verdict=str(v["verdict"]),
                reason=str(v.get("reason", "")),
                suggested_value=v.get("suggested_value"),
            )
            for k, v in p.get("attribute_reviews", {}).items()
        }
        return cls(
            veredicto=str(p["veredicto"]),
            attribute_reviews=reviews,
            global_verdict=str(p.get("global_verdict", "needs_review")),
            reviewer_confidence=float(p.get("reviewer_confidence", 0.0)),
        )


@dataclass(frozen=True)
class AttributeExtraction:
    """One attribute as extracted from a raw source.

    Different from AttributeClassification: includes raw_quote for traceability
    to the source text/table cell. No rule_applied (extractor doesn't apply
    classification rules — that's the classifier's job).
    """
    value: Any | None
    confidence: float
    reasoning: str
    raw_quote: str | None


@dataclass(frozen=True)
class ExtractedFicha:
    """Output of the Extractor agent. Input to the Classifier agent.

    One ExtractedFicha = one source (one URL, one PDF, one DB row). Multiple
    fichas may be combined as evidence blocks when feeding the classifier.
    """
    source_url: str | None           # None when source is a PDF file
    source_type: str                 # "html" | "pdf_text" | "pdf_vision" | "db" | "websearch"
    source_confidence: float         # 0.0–1.0; set by the cascade level
    fetched_at: datetime

    raw_text: str
    tables: list[list[list[str]]]

    attributes: dict[str, AttributeExtraction]
    citations: list[str]
    extraction_cost_usd: float
    extraction_duration_ms: int
    document_date: datetime | None = None
    class_options: list[dict[str, Any]] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "source_type": self.source_type,
            "source_confidence": self.source_confidence,
            "fetched_at": self.fetched_at.isoformat(),
            "raw_text": self.raw_text,
            "tables": self.tables,
            "attributes": {
                k: {
                    "value": v.value,
                    "confidence": v.confidence,
                    "reasoning": v.reasoning,
                    "raw_quote": v.raw_quote,
                }
                for k, v in self.attributes.items()
            },
            "citations": list(self.citations),
            "extraction_cost_usd": self.extraction_cost_usd,
            "extraction_duration_ms": self.extraction_duration_ms,
            "document_date": self.document_date.isoformat() if self.document_date else None,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> ExtractedFicha:
        return cls(
            source_url=payload.get("source_url"),
            source_type=payload["source_type"],
            source_confidence=float(payload.get("source_confidence", 0.0)),
            fetched_at=datetime.fromisoformat(payload["fetched_at"]),
            raw_text=payload.get("raw_text", ""),
            tables=list(payload.get("tables", [])),
            attributes={
                k: AttributeExtraction(
                    value=v.get("value"),
                    confidence=float(v.get("confidence", 0.0)),
                    reasoning=v.get("reasoning", ""),
                    raw_quote=v.get("raw_quote"),
                )
                for k, v in payload.get("attributes", {}).items()
            },
            citations=list(payload.get("citations", [])),
            extraction_cost_usd=float(payload.get("extraction_cost_usd", 0.0)),
            extraction_duration_ms=int(payload.get("extraction_duration_ms", 0)),
            document_date=(
                datetime.fromisoformat(payload["document_date"])
                if payload.get("document_date")
                else None
            ),
        )


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


@dataclass(frozen=True)
class DistributionResult:
    """Output of the distribution agent (Pass 2)."""
    producto: str
    intermediario: str | None = None
    tipo_intermediario: str | None = None
    comision_distribucion: float | None = None
    minimo_via_intermediario: str | None = None
    liquidez_via_intermediario: str | None = None
    confidence: float = 0.0
    reasoning: str = ""
    source_url: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "producto": self.producto,
            "intermediario": self.intermediario,
            "tipo_intermediario": self.tipo_intermediario,
            "comision_distribucion": self.comision_distribucion,
            "minimo_via_intermediario": self.minimo_via_intermediario,
            "liquidez_via_intermediario": self.liquidez_via_intermediario,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "source_url": self.source_url,
        }

    @classmethod
    def from_json(cls, data: str | dict) -> DistributionResult:
        p = json.loads(data) if isinstance(data, str) else data
        return cls(
            producto=str(p.get("producto", "")),
            intermediario=p.get("intermediario"),
            tipo_intermediario=p.get("tipo_intermediario"),
            comision_distribucion=(
                float(p["comision_distribucion"])
                if p.get("comision_distribucion") is not None
                else None
            ),
            minimo_via_intermediario=p.get("minimo_via_intermediario"),
            liquidez_via_intermediario=p.get("liquidez_via_intermediario"),
            confidence=float(p.get("confidence", 0.0)),
            reasoning=str(p.get("reasoning", "")),
            source_url=p.get("source_url"),
        )

    @classmethod
    def from_product_layer(
        cls,
        producto: str,
        administrador_producto: str,
        comision_producto: float | None,
        liquidez_producto: str | None = None,
        minimo_producto: str | None = None,
    ) -> DistributionResult:
        """Shortcut for SAFI-managed funds where intermediary = product manager."""
        return cls(
            producto=producto,
            intermediario=administrador_producto,
            tipo_intermediario="safi",
            comision_distribucion=comision_producto,
            minimo_via_intermediario=minimo_producto,
            liquidez_via_intermediario=liquidez_producto,
            confidence=1.0,
            reasoning="SAFI-managed fund — intermediary is the product manager itself",
        )
