from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_THIS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class AssetClass:
    name: str


@dataclass(frozen=True)
class CanonicalAsset:
    name: str
    macro_class: str
    score: float


@dataclass(frozen=True)
class Region:
    name: str
    benchmark_weight: float


def _load_yaml(filename: str) -> dict:
    with open(_THIS_DIR / filename, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_asset_classes() -> list[AssetClass]:
    data = _load_yaml("asset_classes.yaml")
    return [AssetClass(name=item["name"]) for item in data["asset_classes"]]


@lru_cache(maxsize=1)
def load_canonical_assets() -> list[CanonicalAsset]:
    data = _load_yaml("canonical_assets.yaml")
    return [
        CanonicalAsset(
            name=item["name"],
            macro_class=item["macro_class"],
            score=float(item["score"]),
        )
        for item in data["canonical_assets"]
    ]


@lru_cache(maxsize=1)
def load_regions() -> list[Region]:
    data = _load_yaml("geographic_regions.yaml")
    return [
        Region(name=item["name"], benchmark_weight=float(item["benchmark_weight"]))
        for item in data["geographic_regions"]
    ]
