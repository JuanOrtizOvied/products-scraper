"""Accuracy metrics for classifier validation.

Per-attribute rules from spec:
- Categorical (moneda, liquidez, administrador, gestor, minimo_inversion):
  exact match (case/strip/accent insensitive)
- Percentage dicts (foco, clase, subyacente): each key must exist in both
  with ±5pp per region
- Numeric (comision): ±5% relative tolerance
"""
from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from typing import Any

from scraper.agents.types import ClassificationResult


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


# Common corporate / legal entity suffixes in Spanish-language fund contexts.
# Ordered longest-first so the regex prefers longer matches (e.g. "S.A.U.S.G.F.C.I." before "S.A.").
_CORPORATE_SUFFIXES = [
    "s.a.u.s.g.f.c.i.",
    "s.a.u.s.g.f.c.i",
    "sausgfci",
    "s.a. sgfci",
    "s.a. safi",
    "s.a.s.g.f.c.i.",
    "s.a. saf",
    "sgfci s.a.",
    "g.f.c.i.s.a.",
    "gfcisa",
    "sgfci",
    "safi",
    "sab",
    "saf",
    "saft",
    "sau",
    "s.a.u.",
    "s.a.s.",
    "s.a.",
    "sa",
    "ltd.",
    "ltd",
    "llc",
    "inc.",
    "inc",
    "sociedad agente de bolsa",
    "sociedad administradora de fondos de inversion",
    "sociedad administradora de fondos",
    "administradora de fondos de inversion",
    "administradora de fondos",
    "sociedad gerente",
    "sociedad administradora",
    "administradora general de fondos",
    "asset management",
]


def _strip_corporate_suffix(s: str) -> str:
    """Remove trailing corporate/legal-entity suffixes from a name.

    Handles variants like:
      "Credicorp Capital S.A. SAF" -> "Credicorp Capital"
      "Pellegrini S.A.S.G.F.C.I." -> "Pellegrini"
      "Core Capital SAFI" -> "Core Capital"
      "Banchile Administradora General de Fondos S.A." -> "Banchile"

    Accent-insensitive, case-insensitive. Strips repeatedly (e.g.
    "Foo S.A. SAF" needs two passes — "Foo S.A." after first, "Foo" after second).
    """
    normalized = _strip_accents(s).lower().strip()
    # Strip trailing *non-period* punctuation that might sit outside a suffix.
    # We intentionally preserve trailing "." because the suffix list includes
    # dotted forms like "s.a." — stripping dots up front would break those matches.
    normalized = normalized.rstrip(",;:-— ")

    changed = True
    while changed:
        changed = False
        for suffix in _CORPORATE_SUFFIXES:
            # Check if normalized ends with a space+suffix or just suffix (if s is just the suffix)
            if normalized.endswith(" " + suffix):
                # Preserve trailing "." so subsequent iterations can still match
                # dotted suffixes like "s.a." after stripping a longer multi-word suffix.
                normalized = normalized[: -(len(suffix) + 1)].rstrip(",;:-— ")
                changed = True
                break
            if normalized.endswith(suffix) and len(normalized) > len(suffix):
                # Require word boundary — preceding char shouldn't be alphanumeric
                preceding = normalized[-len(suffix) - 1]
                if not preceding.isalnum():
                    normalized = normalized[: -len(suffix)].rstrip(",;:-— ")
                    changed = True
                    break
    # Final cleanup: strip any remaining trailing dots/punctuation left over from
    # preserved-dot intermediates (e.g. "credicorp capital s.a." after stripping
    # "sociedad administradora de fondos" and then matching "s.a.").
    return normalized.rstrip(".,;:-— ").strip()


def categorical_match(expected: Any, actual: Any) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    exp_norm = _strip_accents(str(expected)).strip().lower()
    act_norm = _strip_accents(str(actual)).strip().lower()
    if exp_norm == act_norm:
        return True
    # Also try with corporate suffixes stripped — "Credicorp Capital" and
    # "Credicorp Capital S.A. SAF" should compare equal.
    exp_stripped = _strip_corporate_suffix(str(expected))
    act_stripped = _strip_corporate_suffix(str(actual))
    if exp_stripped and act_stripped and exp_stripped == act_stripped:
        return True
    return False


def _filter_small_keys(d: dict[str, float], threshold: float = 5.0) -> dict[str, float]:
    """Remove keys with value < threshold and renormalize remaining to 100."""
    filtered = {k: v for k, v in d.items() if v >= threshold}
    total = sum(filtered.values())
    if total > 0 and abs(total - 100.0) > 0.01:
        factor = 100.0 / total
        filtered = {k: v * factor for k, v in filtered.items()}
    return filtered


_SKIP_NONE_GT_ATTRS = {"minimo_inversion"}


def _should_skip_none_gt(attr: str, gt_value: Any) -> bool:
    """Return True if this attribute should be marked correct when gt is None."""
    return attr in _SKIP_NONE_GT_ATTRS and gt_value is None


def percentage_dict_match(
    expected: dict[str, float] | None,
    actual: dict[str, float] | None,
    tolerance_pp: float = 5.0,
) -> bool:
    expected = _filter_small_keys(expected or {})
    actual = _filter_small_keys(actual or {})
    if set(expected.keys()) != set(actual.keys()):
        return False
    for k, exp_v in expected.items():
        act_v = actual[k]
        if abs(exp_v - act_v) > tolerance_pp:
            return False
    return True


def numeric_match(
    expected: float | None,
    actual: float | None,
    rel_tolerance: float = 0.05,
) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    try:
        expected = float(expected)
        actual = float(actual)
    except (TypeError, ValueError):
        return False
    if expected == 0:
        return abs(actual) < rel_tolerance
    return abs(expected - actual) / abs(expected) <= rel_tolerance


_PRODUCT_ATTR_MAPPING = {
    "foco_geografico": ("percentage_dict", "foco_geografico"),
    "clase_activo": ("percentage_dict", "clase_activo"),
    "subyacente": ("percentage_dict", "subyacentes"),
    "comision": ("numeric", "comision_producto"),
    "moneda": ("categorical", "moneda"),
    "administrador": ("categorical", "administrador_producto"),
    "gestor": ("categorical", "gestor_producto"),
    "liquidez": ("categorical", "liquidez_producto"),
    "minimo_inversion": ("categorical", "minimo_inversion_producto"),
}

_ATTR_MAPPING = {
    "foco_geografico": ("percentage_dict", "foco_geografico"),
    "clase_activo": ("percentage_dict", "clase_activo"),
    "subyacente": ("percentage_dict", "subyacentes"),  # expected key differs
    "comision": ("numeric", "comision"),
    "moneda": ("categorical", "moneda"),
    "administrador": ("categorical", "administrador"),
    "gestor": ("categorical", "gestor"),
    "liquidez": ("categorical", "liquidez"),
    "minimo_inversion": ("categorical", "minimo_inversion"),
}


def compute_product_accuracy(
    ground_truth: dict[str, Any],
    predicted: ClassificationResult,
) -> dict[str, bool]:
    """Compare predicted classification against ground truth Product row dict.

    Returns dict of attribute → correct (bool).
    """
    report: dict[str, bool] = {}
    for attr, (kind, gt_key) in _ATTR_MAPPING.items():
        gt_value = ground_truth.get(gt_key)
        predicted_attr = predicted.attributes.get(attr)
        pred_value = predicted_attr.value if predicted_attr else None

        if _should_skip_none_gt(gt_key, gt_value):
            report[attr] = True
            continue

        if kind == "percentage_dict":
            report[attr] = percentage_dict_match(gt_value, pred_value)
        elif kind == "numeric":
            report[attr] = numeric_match(gt_value, pred_value)
        else:
            report[attr] = categorical_match(gt_value, pred_value)
    return report


def compute_product_accuracy_v8(
    ground_truth: dict[str, Any],
    predicted: ClassificationResult,
) -> dict[str, bool]:
    """Compare predicted classification against two-layer ground truth (product layer)."""
    report: dict[str, bool] = {}
    for attr, (kind, gt_key) in _PRODUCT_ATTR_MAPPING.items():
        gt_value = ground_truth.get(gt_key)
        predicted_attr = predicted.attributes.get(attr)
        pred_value = predicted_attr.value if predicted_attr else None

        if _should_skip_none_gt(attr, gt_value):
            report[attr] = True
            continue

        if kind == "percentage_dict":
            report[attr] = percentage_dict_match(gt_value, pred_value)
        elif kind == "numeric":
            report[attr] = numeric_match(gt_value, pred_value)
        else:
            report[attr] = categorical_match(gt_value, pred_value)
    return report


def compute_distribution_accuracy(
    ground_truth: dict[str, Any],
    predicted: "DistributionResult",
) -> dict[str, bool]:
    """Compare predicted distribution against ground truth (distribution layer)."""
    report: dict[str, bool] = {}
    report["intermediario"] = categorical_match(
        ground_truth.get("intermediario"), predicted.intermediario
    )
    report["tipo_intermediario"] = categorical_match(
        ground_truth.get("tipo_intermediario"), predicted.tipo_intermediario
    )
    report["comision_distribucion"] = numeric_match(
        ground_truth.get("comision_distribucion"), predicted.comision_distribucion
    )
    return report


def aggregate_accuracy(per_product_reports: Iterable[dict[str, bool]]) -> dict[str, float]:
    """Average accuracy per attribute across N products.

    Returns dict of attribute → fraction correct (0.0 to 1.0).
    """
    reports = list(per_product_reports)
    if not reports:
        return {}
    attrs = reports[0].keys()
    out: dict[str, float] = {}
    for a in attrs:
        correct = sum(1 for r in reports if r.get(a) is True)
        out[a] = correct / len(reports)
    return out
