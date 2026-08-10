from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

TIER_COUNTRY = "country"
TIER_REGIONAL = "regional"
TIER_SPOT = "spot"
# A hand-entered meta comes from no Plonk It section: its tier is only a
# display label, no logic depends on it.
TIER_MANUAL = "manual"

ORIGIN_PLONKIT = "plonkit"
ORIGIN_MANUAL = "manual"
ORIGIN_RMRG = "rmrg"

# Two DECISION statuses: a geometry that exists was drawn by hand by
# construction. `proposé` is not a decision but a pre-drawn footprint waiting
# for one (cartometa-import-tagged): it stays in the review queue and is never
# published. `STATUSES` deliberately keeps only the decisions — that is what
# gates set_decision and the build's EXPORTABLE filter.
STATUS_TRACED = "validé"
STATUS_REJECTED = "rejeté"
STATUS_PROPOSED = "proposé"
STATUSES = (STATUS_TRACED, STATUS_REJECTED)


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
    origin: str = ORIGIN_PLONKIT
    image: str | None = None
    maps_url: str | None = None
    maps_latlon: tuple[float, float] | None = None
    # RMRG only: the guide's region mini-map (SVG), shown next to the photo in
    # the review UI. Never published by the site build.
    overlay: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GeoRecord:
    """The human decision on a meta: its footprint, and what it takes to reopen it.

    `pieces` holds the descriptors exactly as the human laid them down. That is
    what makes it possible to reopen an already drawn meta and remove one piece
    from it without redrawing everything — the geometry alone cannot be
    decomposed.
    """

    id: str
    geometry: dict[str, Any] | None = None
    pieces: list[dict[str, Any]] = field(default_factory=list)
    status: str = STATUS_TRACED

    def to_feature(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": self.geometry,
            "properties": {"id": self.id, "status": self.status, "pieces": self.pieces},
        }

    @classmethod
    def from_feature(cls, feature: dict[str, Any]) -> "GeoRecord":
        props = feature["properties"]
        return cls(
            id=props["id"],
            geometry=feature["geometry"],
            pieces=props.get("pieces", []),
            status=props["status"],
        )
