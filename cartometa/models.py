from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

TIER_COUNTRY = "country"
TIER_REGIONAL = "regional"
TIER_SPOT = "spot"
# Une méta saisie à la main ne vient d'aucune section Plonk It : son tier
# n'est qu'un libellé d'affichage, aucune logique n'en dépend.
TIER_MANUAL = "manual"

ORIGIN_PLONKIT = "plonkit"
ORIGIN_MANUAL = "manual"

# Deux statuts, pas quatre : une géométrie présente est par construction
# tracée à la main, il n'y a plus rien d'automatique à distinguer.
STATUS_TRACED = "validé"
STATUS_REJECTED = "rejeté"
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GeoRecord:
    """Décision humaine sur une méta : son emprise, et de quoi la rouvrir.

    `pieces` porte les descripteurs tels que l'humain les a posés. C'est ce
    qui permet de rouvrir une méta déjà tracée et d'en retirer un morceau
    sans tout redessiner — la géométrie seule ne se décompose pas.
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
