# src/scraper/scripts/compare_calibrations.py
"""Compare two calibration JSON result files and produce a report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean


def compare(v6: dict, v7: dict) -> dict[str, dict]:
    all_attrs = set(v6.get("per_attribute_accuracy", {})) | set(v7.get("per_attribute_accuracy", {}))
    result = {}
    for attr in sorted(all_attrs):
        acc_v6 = v6.get("per_attribute_accuracy", {}).get(attr, 0.0)
        acc_v7 = v7.get("per_attribute_accuracy", {}).get(attr, 0.0)
        delta = acc_v7 - acc_v6
        if abs(delta) < 0.001:
            status = "unchanged"
        elif delta > 0:
            status = "improved"
        else:
            status = "regressed"
        result[attr] = {"v6": acc_v6, "v7": acc_v7, "delta": delta, "status": status}
    return result


def _avg_confidence(data: dict) -> float:
    details = data.get("details", [])
    confs = [d.get("global_confidence", 0) for d in details if d.get("global_confidence") is not None]
    return mean(confs) if confs else 0.0


def _avg_duration(data: dict) -> float:
    details = data.get("details", [])
    durs = [d.get("elapsed_s", 0) for d in details]
    return mean(durs) if durs else 0.0


def format_report(v6: dict, v7: dict) -> str:
    comp = compare(v6, v7)
    lines = [
        f"=== CALIBRATION COMPARISON v6 ({v6.get('fetcher_backend', '?')}) vs v7 ({v7.get('fetcher_backend', '?')}) ===",
        "",
        f"{'Attribute':<22s} | {'v6 acc':>8s} | {'v7 acc':>8s} | {'Delta':>8s} | Status",
        "-" * 70,
    ]
    for attr, d in comp.items():
        status_icon = {"improved": "improved", "regressed": "REGRESSED", "unchanged": "-"}.get(d["status"], "?")
        lines.append(
            f"{attr:<22s} | {d['v6']:>7.1%} | {d['v7']:>7.1%} | {d['delta']:>+7.1%} | {status_icon}"
        )
    lines.append("")
    n6 = max(v6.get("n_products", 1), 1)
    n7 = max(v7.get("n_products", 1), 1)
    lines.append(f"{'Global confidence':<22s} | {_avg_confidence(v6):>8.2f} | {_avg_confidence(v7):>8.2f}")
    lines.append(f"{'Avg cost USD':<22s} | ${v6.get('total_cost_usd', 0) / n6:>7.3f} | ${v7.get('total_cost_usd', 0) / n7:>7.3f}")
    lines.append(f"{'Avg duration (s)':<22s} | {_avg_duration(v6):>8.1f} | {_avg_duration(v7):>8.1f}")
    return "\n".join(lines)


def cli() -> None:
    parser = argparse.ArgumentParser(description="Compare two calibration JSON results.")
    parser.add_argument("v6_path", help="Path to v6 results JSON")
    parser.add_argument("v7_path", help="Path to v7 results JSON")
    args = parser.parse_args()
    v6 = json.loads(Path(args.v6_path).read_text(encoding="utf-8"))
    v7 = json.loads(Path(args.v7_path).read_text(encoding="utf-8"))
    print(format_report(v6, v7))


if __name__ == "__main__":
    cli()
