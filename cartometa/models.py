from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

TIER_COUNTRY = "country"
TIER_REGIONAL = "regional"
TIER_SPOT = "spot"


@dataclass
class MetaRecord:
    id: str
    country: str
    tier: str
    title: str
    description: str
    category: str
    source_url: str
    extracted_at: str
    description_origin: str = "imported"
    image: str | None = None
    maps_url: str | None = None
    maps_latlon: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GeoRecord:
    id: str
    geometry: dict[str, Any]
    confidence: float
    warnings: list[str] = field(default_factory=list)
    status: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
