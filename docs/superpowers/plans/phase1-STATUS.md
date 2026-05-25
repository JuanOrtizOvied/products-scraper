# Phase 1 — Status

**Completed:** 2026-04-17
**Tests passing:** 33 across 7 files
**Productos importados:** 128 unique (110 active, 18 incomplete)
**Split:** 91 training / 19 validation (ratio 17.3%, stratified by dominant macro class)

## Hallazgos importantes del dataset

### 1. Duplicados en el Excel (8 productos)
El Excel original tiene 8 nombres de producto duplicados. La segunda aparición de cada uno tiene todos los atributos en NaN. Los afectados:
- iShares 7–10 Year Treasury Bond ETF – IEF
- iShares iBoxx $ Investment Grade Corporate Bond ETF – LQD
- SPDR Bloomberg 1–3 Month T-Bill ETF – BIL
- UBS (Lux) Bond SICAV – Short Term USD – MFUBCN
- SPDR Gold Shares ETF – GLD
- iShares Silver Trust ETF – SLV
- JPM Global Macro Fund – MFLJEU
- Pictet PTR Atlas Fund – MFVXDA

El seeder dedupea por nombre (primera ocurrencia gana), así que el count real es 128.

**Acción para el equipo Sabbi:** revisar el Excel original y limpiar los duplicados si es intencional eliminarlos, o poblar los datos de las segundas ocurrencias si son registros distintos que comparten nombre.

### 2. Productos incompletos (18)
Productos con nombre pero sin atributos (NaN en foco/clase/subyacente). Ej: Sabbi Dividendos, Sabbi Vision Largo Plazo. Se importan con `status='incomplete'` y se excluyen del split.

### 3. Variantes ortográficas en `clase_activo`
El Excel usa variantes como "Mercados publicos variable", "mercado publico variable", "Club deal" en vez de los nombres canónicos ("Mercados Públicos - Variable", "Club deals"). Hay ~14 variantes documentadas en `tests/unit/test_phase1_smoke.py::excel_variants_to_canonical`.

**Acción para Phase 2:** mover este mapping a un módulo `scraper/taxonomies/normalizer.py` y usar en el Extractor.

### 4. Cells compuestos (whitespace como separador)
Algunas celdas del Excel usan whitespace largo como separador en vez de coma/newline. Ej: `"Mercados publicos variable 62.44%    Mercados publicos fijo 21.78%"` queda como una sola clave en el JSON parseado.

**Acción para Phase 2:** extender `parse_percentages` para soportar runs de 3+ espacios como separador, O pre-procesar estas celdas antes del parser.

## Estructura del código al cerrar Phase 1

```
scraper/
├── pyproject.toml, .env.example, .gitignore, README.md
├── alembic.ini, alembic/ (env.py + initial migration)
├── src/scraper/
│   ├── config.py                 (Settings pydantic-settings)
│   ├── db/                       (base, models, session)
│   ├── taxonomies/               (3 YAMLs + loader + 3 dataclasses)
│   ├── parsers/                  (percentage_parser)
│   └── scripts/                  (seed_from_excel, split_train_validation)
├── tests/
│   └── unit/                     (7 test files, 33 tests)
└── data/
    └── local.db                  (128 productos seeded, split aplicado)
```

## Lo que queda para Phase 2

1. Extractor (HTML + PDF texto + PDF vision con Claude)
2. Clasificador (Claude Sonnet 4.6) con taxonomías como lista cerrada
3. Revisor (Claude Opus 4.7)
4. Rules v1.md a partir de training_set (colaboración humano-agente)
5. Regression test contra validation_set (threshold ≥85% accuracy por atributo)
6. Normalizer para variantes ortográficas (acción #3)
7. Parser mejorado para celdas compuestas (acción #4)
8. CLI: `poetry run python -m scraper.scripts.classify_one "NombreProducto"`
