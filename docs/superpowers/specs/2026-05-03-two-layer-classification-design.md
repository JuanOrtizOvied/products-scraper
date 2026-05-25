# Two-Layer Classification: Product + Distribution — Design Spec

**Fecha:** 2026-05-03
**Autor:** Sabbi + Claude
**Status:** Aprobado — pendiente de implementación

## Problema

El pipeline end-to-end de clasificación tiene accuracy baja (26-73%) porque el ground truth mezcla dos capas de información:
- **Capa producto**: atributos intrínsecos del activo (quién lo administra realmente, su expense ratio)
- **Capa distribución**: cómo Sabbi accede al producto (intermediario peruano, fee de custodia)

El cascade web descubre correctamente la capa producto (BlackRock administra SHY, expense ratio 0.15%), pero la métrica lo marca como error porque el ground truth dice "UBS" y "0.65%" (que son el intermediario y su fee).

Además, las métricas de comparación son demasiado estrictas:
- Percentage dicts requieren key-set idéntico (2% cash penaliza)
- `None` en ground truth vs valor real = error
- `comision` mezcla expense ratio con fee de custodia

## Arquitectura

### Modelo de Datos — Dos Capas

```
Capa Producto (atributos intrínsecos del activo):
  administrador_producto      → "BlackRock", "JPMorgan AM", "Core Capital SAFI"
  gestor_producto             → "BlackRock Fund Advisors"
  comision_producto           → 0.0015 (expense ratio real del fondo/ETF)
  minimo_inversion_producto   → "1 acción", "$1000 USD"
  moneda                      → "dolares" (compartido, no cambia entre capas)
  liquidez_producto           → "Inmediata"
  clase_activo                → {"Mercados Públicos - Fijo": 100} (compartido)
  foco_geografico             → {"EEUU": 100} (compartido)
  subyacente                  → {"US Treasuries Corto Plazo": 100} (compartido)

Capa Distribución (cómo Sabbi accede al producto):
  intermediario               → "UBS", "Credicorp Capital"
  tipo_intermediario          → "custodio" | "broker" | "safi" | "directo"
  comision_distribucion       → 0.0065 (fee del intermediario)
  minimo_via_intermediario    → "USD 70,000"
  liquidez_via_intermediario  → "Mediano plazo" (si difiere del producto)
```

Atributos compartidos (no se desdoblan): moneda, clase_activo, foco_geografico, subyacente.

Atributos desdoblados: administrador, gestor, comision, minimo_inversion, liquidez.

### Pipeline — Dos Pasadas con Agente Inteligente

```
Input: nombre del producto
            │
            ▼
    ┌───────────────┐
    │  PASADA 1     │  Cascade existente (N0→N1→N2→N3)
    │  Producto     │  Busca: ficha técnica, fact sheet,
    │               │  Bloomberg, Morningstar, reguladores
    └───────┬───────┘
            │ fichas[] con atributos del producto
            ▼
    ┌───────────────┐
    │  CLASIFICADOR │  Produce capa producto:
    │  PRODUCTO     │  administrador_producto, gestor_producto,
    │  (existente)  │  comision_producto, etc.
    └───────┬───────┘
            │ ClassificationResult (capa producto)
            ▼
    ┌───────────────┐
    │  PASADA 2     │  Agente Claude con web_search que RAZONA:
    │  Distribución │  - "Es acción BVL → buscar en BVL quién opera"
    │  (NUEVO)      │  - "Es fondo internacional → buscar en SMV,
    │               │    catálogos SAFIs peruanas, UBS Peru"
    │               │  - "Es fondo peruano → la SAFI es el intermediario"
    │               │  Hasta N búsquedas, decide solo dónde buscar
    └───────┬───────┘
            │ DistributionResult (capa distribución)
            ▼
    ┌───────────────┐
    │  MERGE        │  Combina ambas capas en resultado final
    └───────────────┘
```

### Agente de Distribución (Pasada 2)

Agente Claude con `web_search` tool (mismo patrón que Level 3 intensive) que recibe:
- Nombre del producto
- Resultado de Pasada 1 (tipo de producto, administrador real, etc.)
- Instrucciones para razonar sobre dónde buscar el intermediario peruano

El agente decide su propia estrategia de búsqueda. No se hardcodean fuentes — razona según el tipo de producto.

**Cortocircuito para fondos peruanos:** Si Pasada 1 identifica que el administrador es una SAFI peruana, no se ejecuta Pasada 2. Se copia directamente:
```
intermediario = administrador_producto
tipo_intermediario = "safi"
comision_distribucion = comision_producto
```

### Reglas v8

Extienden v7 con reglas de doble capa (R-DCAP):

**R-DCAP-1: Atributos del producto son intrínsecos.** administrador_producto, gestor_producto, comision_producto y minimo_inversion_producto reflejan al ASSET MANAGER real del producto, no al intermediario peruano. SHY → administrador_producto = "BlackRock", NO "UBS".

**R-DCAP-2: Intermediario es quién da acceso en Perú.** intermediario refleja la SAFI, broker o custodio peruano a través del cual Sabbi accede al producto. Fondos peruanos: intermediario = la SAFI. Acciones BVL: intermediario = el broker. Assets internacionales: intermediario = custodio.

**R-DCAP-3: Fondos peruanos = capa única.** Si administrador_producto es una SAFI peruana, copiar directamente sin búsqueda adicional.

### Correcciones a Métricas

**Fix 1: Percentage dict — tolerancia a posiciones menores.** Ignorar keys con valor < 5% en el predicted antes de comparar key-sets. Renormalizar a 100%.

**Fix 2: minimo_inversion — None ground truth = skip.** Si ground truth es None, no penalizar al clasificador por dar un valor.

**Fix 3: Comparación por capa.** comision_producto se compara contra expense ratio real. comision_distribucion contra fee del intermediario. Se reportan por separado.

### Migración del Validation Set

Script semi-automático que:
1. Corre Pasada 1 sobre los 19 productos
2. Propone valores para capa producto basado en lo que el cascade encuentra
3. Mantiene los valores actuales como capa distribución
4. Genera output para revisión manual
5. Aplica la migración a la DB

### Productos No Buscables

Los club deals privados (Promociones Turísticas, S&T Comunicación) se reportan en categoría separada:
```
=== Resultado ===
Buscables (17 productos):
  administrador_producto  [████████████████░░░░] 82%
  intermediario           [██████████░░░░░░░░░░] 53%
  ...
No buscables (2 productos):
  Promociones Turisticas del Sur — club deal privado
  S&T COMUNICACIÓN INTEGRAL SAC — club deal privado
```

## Scope

### Se construye

| Componente | Acción |
|---|---|
| DB: modelo Product | Agregar campos dos capas + migración Alembic |
| DB: validation set | Script semi-auto para desdoblar 19 productos |
| Agente distribución | Nuevo agente Claude con web_search |
| Clasificador producto | Actualizar prompt para atributos intrínsecos |
| Types | DistributionResult dataclass + merge |
| Pipeline | Orquestar Pasada 1 → Pasada 2 → Merge |
| Métricas | Fix percentage dict, None handling, dos capas |
| Rules v8 | Reglas R-DCAP + todo v7 |
| calibrate_pipeline.py | Comparar ambas capas, reporte separado |
| Tests | ~10 tests nuevos |

### NO se hace

- No se cambia el cascade (N0→N3) — funciona bien para capa producto
- No se cambia el extractor HTML/PDF
- No se toca la UI de Streamlit (paso posterior)
- No se hardcodean fuentes de intermediarios — el agente decide

## Criterio de Éxito

Calibración con rules v8 sobre 17 productos buscables:
- **Capa producto**: >80% accuracy promedio
- **Capa distribución**: >50% accuracy promedio (es nuevo, se itera)
- **Costo**: <$0.60 por producto promedio

## Orden de Ejecución

**Fase 1: Fundamentos** — Fix métricas, migración DB, desdoblar validation set, rules v8

**Fase 2: Pipeline dos capas** — Types, agente distribución, actualizar clasificador, orquestación, actualizar calibrate_pipeline.py

**Fase 3: Calibración** — Benchmark, iterar prompts según resultados
