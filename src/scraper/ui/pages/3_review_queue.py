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
    # All widget keys below are scoped to this review via `p` prefix
    p = f"r{rid}_"

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
        if "nombre" not in attrs or not attrs.get("nombre", {}).get("value"):
            product_name = (
                cls.classifier_output.get("producto")
                if isinstance(cls.classifier_output, dict)
                else None
            ) or cls.product_name_input
            attrs["nombre"] = {
                "value": product_name,
                "confidence": 1.0,
                "reasoning": "Nombre del producto (input)",
            }

        conflicts_list = cls.field_conflicts or []
        conflicts_by_attr = {c["attribute"]: c for c in conflicts_list}

        from scraper.overlay import apply_overlay_defaults, load_sabbi_overlay
        overlay = load_sabbi_overlay()
        if overlay.via_sabbi_brokerage and st.button("Aplicar defaults Sabbi (via Credicorp)", key=f"{p}overlay"):
            preview = {k: attrs.get(k, {}).get("value") for k in ("administrador", "gestor", "comision")}
            preview = apply_overlay_defaults(preview, overlay, choice="via_sabbi_brokerage")
            for k in ("administrador", "gestor", "comision"):
                if k in attrs:
                    attrs[k]["value"] = preview.get(k)
            st.success("Defaults aplicados.")

        from scraper.ui.components.class_selector import render_class_selector
        from scraper.ui.components.dict_editor import edit_attribute

        class_options = (
            cls.classifier_output.get("class_options")
            if isinstance(cls.classifier_output, dict)
            else None
        )
        selected_class = None
        if class_options:
            selected_class = render_class_selector(class_options, key_prefix=p)
            class_tag = ""
            if selected_class:
                class_tag = selected_class.get("clase", "").replace(" ", "")
                if selected_class.get("comision") is not None:
                    attrs.setdefault("comision", {})
                    attrs["comision"]["value"] = selected_class["comision"]
                    attrs["comision"]["confidence"] = 0.90
                    attrs["comision"]["reasoning"] = f"Seleccionado: {selected_class.get('clase', '?')} — {selected_class.get('comision_raw', '')}"
                if selected_class.get("minimo_inversion"):
                    attrs.setdefault("minimo_inversion", {})
                    attrs["minimo_inversion"]["value"] = selected_class["minimo_inversion"]
                    attrs["minimo_inversion"]["confidence"] = 0.90
                    attrs["minimo_inversion"]["reasoning"] = f"Seleccionado: {selected_class.get('clase', '?')}"
            st.markdown("---")

        st.markdown("### Atributos")
        edited: dict = {}
        class_bound = {"comision", "minimo_inversion"} if class_options else set()
        for attr_key in [
            "nombre", "foco_geografico", "clase_activo", "subyacente",
            "moneda", "liquidez", "administrador", "gestor",
            "comision", "minimo_inversion",
        ]:
            a = attrs.get(attr_key, {})
            conflict = conflicts_by_attr.get(attr_key)

            if conflict:
                st.markdown(f"**⚠ CONFLICTO** en {attr_key.replace('_', ' ').title()}")

            widget_key = f"{p}{attr_key}"
            if attr_key in class_bound and class_tag:
                widget_key = f"{p}{attr_key}_{class_tag}"

            edited[attr_key] = edit_attribute(
                key=widget_key,
                attr_name=attr_key,
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
            if st.button("✅ Aprobar", type="primary", key=f"{p}approve"):
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
            reject_notes = st.text_input("Motivo de rechazo (opcional)", key=f"{p}reject_notes")
            if st.button("❌ Rechazar", key=f"{p}reject"):
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
        st.markdown("#### Subir PDF más reciente (actualiza esta clasificación)")
        upload = st.file_uploader("PDF de la ficha", type=["pdf"], key=f"{p}upload")
        if upload and st.button("Re-procesar con PDF", key=f"{p}reprocess"):
            from scraper.ui.upload_ops import reclassify_with_pdf

            async def _reclassify():
                async with get_session() as s:
                    return await reclassify_with_pdf(
                        s, nombre=cls.product_name_input, pdf_bytes=upload.read(),
                        operator="local_user",
                        target_classification_id=cls.id,
                    )

            new_job_id = run_async(_reclassify())
            st.success(
                f"Job #{new_job_id} encolado. Cuando el worker lo procese, "
                f"actualizará la clasificación #{cls.id} (sin crear una nueva).\n\n"
                "```bash\npoetry run python -m scraper.scripts.worker\n```"
            )
