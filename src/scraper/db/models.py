from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scraper.db.base import Base, utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="editor")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False, index=True)
    foco_geografico: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    clase_activo: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    subyacentes: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    comision: Mapped[float | None] = mapped_column(Float, nullable=True)
    comision_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    moneda: Mapped[str | None] = mapped_column(String, nullable=True)
    administrador: Mapped[str | None] = mapped_column(String, nullable=True)
    gestor: Mapped[str | None] = mapped_column(String, nullable=True)
    liquidez: Mapped[str | None] = mapped_column(String, nullable=True)
    minimo_inversion: Mapped[str | None] = mapped_column(String, nullable=True)
    # Two-layer: product-level attributes (the asset itself)
    administrador_producto: Mapped[str | None] = mapped_column(String, nullable=True)
    gestor_producto: Mapped[str | None] = mapped_column(String, nullable=True)
    comision_producto: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimo_inversion_producto: Mapped[str | None] = mapped_column(String, nullable=True)
    liquidez_producto: Mapped[str | None] = mapped_column(String, nullable=True)
    # Two-layer: distribution attributes (how Sabbi accesses it)
    intermediario: Mapped[str | None] = mapped_column(String, nullable=True)
    tipo_intermediario: Mapped[str | None] = mapped_column(String, nullable=True)
    comision_distribucion: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimo_via_intermediario: Mapped[str | None] = mapped_column(String, nullable=True)
    liquidez_via_intermediario: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_type: Mapped[str] = mapped_column(String, default="manual")
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class TrainingSet(Base):
    __tablename__ = "training_set"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ValidationSet(Base):
    __tablename__ = "validation_set"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RulesVersion(Base):
    __tablename__ = "rules_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_rules_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    examples_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_accuracy: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Classification(Base):
    __tablename__ = "classifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_name_input: Mapped[str] = mapped_column(String, nullable=False, index=True)
    rules_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("rules_versions.id"), nullable=True
    )
    classifier_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewer_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    global_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    per_attribute_confidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    final_status: Mapped[str] = mapped_column(String, default="pending_human")
    source_used: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    sources_used: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    field_conflicts: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewQueue(Base):
    __tablename__ = "review_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classification_id: Mapped[int] = mapped_column(ForeignKey("classifications.id"), index=True)
    classification: Mapped[Classification] = relationship(
        "Classification", foreign_keys=[classification_id], lazy="joined"
    )
    flag: Mapped[str] = mapped_column(String, nullable=False)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    human_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    human_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class SearchCache(Base):
    __tablename__ = "search_cache"
    query_hash: Mapped[str] = mapped_column(String, primary_key=True)
    query_text: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, primary_key=True)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    ttl_days: Mapped[int] = mapped_column(Integer, default=30)


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobQueue(Base):
    __tablename__ = "job_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False, index=True)
    pdf_path: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", index=True
    )
    classification_id: Mapped[int | None] = mapped_column(
        ForeignKey("classifications.id"), nullable=True
    )
    target_classification_id: Mapped[int | None] = mapped_column(
        ForeignKey("classifications.id"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
