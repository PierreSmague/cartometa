from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from shapely.geometry import Point, mapping, shape
from skimage.measure import label, regionprops

from cartometa.atomic_write import write_json_atomic
from cartometa.config import Config, load_config
from cartometa.geo.calibrate import Calibration, fit_calibration, load_calibration, save_calibration
from cartometa.geo.confidence import evaluate
from cartometa.geo.reference import country_geometry, main_landmass
from cartometa.geo.silhouette import find_inset
from cartometa.geo.vectorize import buffer_km, mask_to_geometry, zone_mask


def _load_rgba(path: str) -> np.ndarray:
    return np.array(Image.open(path).convert("RGBA"))


def _existing_statuses(path: Path) -> dict[str, dict]:
    """Préserve les décisions de revue déjà prises."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text("utf-8"))
    return {
        f["properties"]["id"]: f
        for f in data.get("features", [])
        if f["properties"].get("status") in ("validé", "corrigé", "rejeté")
    }


def _calibration_for(country: str, metas: list[dict], data_dir: Path, cfg: Config) -> Calibration | None:
    """Calibre une fois par pays, à partir d'une méta dont la silhouette est intacte."""
    path = data_dir / "calib" / f"{country}.json"
    if path.exists():
        return load_calibration(path)

    # Calibrer sur la masse principale : les territoires distants faussent
    # l'alignement sans jamais apparaître sur la carte Plonk It.
    reference = main_landmass(country_geometry(country, data_dir / "cache"))
    # Une méta `spot` est préférée : son pin n'ampute pas la silhouette.
    ordered = sorted(metas, key=lambda m: 0 if m["tier"] == "spot" else 1)
    for meta in ordered:
        if not meta.get("image"):
            continue
        inset = find_inset(_load_rgba(meta["image"]), cfg)
        if inset is None:
            continue
        calib = fit_calibration(inset.mask, reference, cfg)
        save_calibration(path, calib)
        return calib
    return None


def build_country(country: str, data_dir: Path, cfg: Config) -> dict:
    metas = json.loads((data_dir / "metas" / f"{country}.json").read_text("utf-8"))
    reference = country_geometry(country, data_dir / "cache")
    out_path = data_dir / "geo" / f"{country}.geojson"
    preserved = _existing_statuses(out_path)

    calib = _calibration_for(country, metas, data_dir, cfg)
    radii = cfg.get("spot.radius_by_category", {})
    features, stats = [], {"country": 0, "spot": 0, "regional": 0, "failed": 0}

    for meta in metas:
        if meta["id"] in preserved:
            features.append(preserved[meta["id"]])
            continue

        geometry, warnings, component_count = None, [], 0
        touches_border, area_fraction, iou = False, None, calib.iou if calib else None

        if meta["tier"] == "country":
            geometry = reference
            stats["country"] += 1

        elif meta["tier"] == "spot":
            if meta.get("maps_latlon"):
                lat, lon = meta["maps_latlon"]
                radius = radii.get(meta["category"], cfg.get("spot.default_radius_km"))
                geometry = buffer_km(Point(lon, lat), radius)
                stats["spot"] += 1
            elif meta.get("maps_url"):
                # Un `maps_url` présent mais sans `maps_latlon` signifie que la
                # résolution a échoué (souvent un throttling passager côté
                # Google) — pas que la méta soit dépourvue de lien. Rejouer
                # `cartometa-extract --retry-failed-links` peut suffire.
                warnings.append("lien Maps présent mais non résolu")
            else:
                warnings.append("méta ponctuelle sans lien Maps, position inconnue")

        elif meta["tier"] == "regional":
            if not meta.get("image"):
                warnings.append("image absente")
            elif calib is None:
                warnings.append("aucune calibration disponible pour ce pays")
            else:
                rgba = _load_rgba(meta["image"])
                inset = find_inset(rgba, cfg)
                if inset is None:
                    warnings.append("aucun encart cartographique détecté")
                else:
                    mask = zone_mask(rgba, inset, cfg)
                    component_count = sum(
                        1 for r in regionprops(label(mask))
                        if r.area >= cfg.get("vectorize.min_component_px")
                    )
                    # NOTE (correction, relecture finale) : ce test mesure le
                    # bord de `inset.bbox`, qui est la boîte englobante de la
                    # SILHOUETTE DU PAYS détectée par `find_inset` — pas le
                    # cadre de l'image composite. C'est une mesure honnête de
                    # « la zone atteint l'extrémité du pays », rien de plus.
                    #
                    # Une tentative de mesurer plutôt le vrai bord physique de
                    # l'image (`rgba.shape`) a été essayée et abandonnée : les
                    # fermetures/ouvertures morphologiques de `find_inset` et
                    # `zone_mask` (bruit poivre-et-sel, anti-aliasing) érodent
                    # systématiquement le masque de plusieurs pixels près des
                    # bords de l'array — un test vérifié à la main montre un
                    # masque réellement collé au bord réel de l'image (rangée 0)
                    # ressortir décalé à la rangée 4 après traitement. Un simple
                    # test d'égalité au bord literal aurait donc raté les vrais
                    # cas de troncature, ce qui est pire que le statu quo. Fixer
                    # une marge de tolérance en pixels serait possible mais
                    # introduirait une constante non mesurée sur données réelles
                    # (contraire à la règle du §3 : aucun seuil arbitraire non
                    # justifié). On choisit donc d'assumer que ce signal n'est
                    # pas mesurable de façon fiable ici, et de reformuler
                    # l'avertissement (et retirer son malus, cf. confidence.py)
                    # plutôt que de prétendre détecter une troncature réelle.
                    x0, y0, x1, y1 = inset.bbox
                    edge = mask[y0:y1, x0:x1]
                    if edge.size:
                        touches_border = bool(
                            edge[0].any() or edge[-1].any() or edge[:, 0].any() or edge[:, -1].any()
                        )
                    geometry = mask_to_geometry(mask, calib, cfg)
                    if geometry is None:
                        warnings.append(
                            "encart détecté mais aucun pixel rouge dans la silhouette"
                        )
                    elif reference.area > 0:
                        area_fraction = geometry.intersection(reference).area / reference.area
                    stats["regional"] += 1

        score, auto_warnings = evaluate(
            geometry, tier=meta["tier"], calib_iou=iou, latlon=meta.get("maps_latlon"),
            component_count=component_count, touches_border=touches_border,
            area_fraction_of_country=area_fraction, cfg=cfg,
        )
        warnings = warnings + auto_warnings
        if geometry is None:
            stats["failed"] += 1

        features.append({
            "type": "Feature",
            "geometry": mapping(geometry) if geometry is not None else None,
            "properties": {
                "id": meta["id"], "confidence": round(score, 3),
                "warnings": warnings, "status": "auto",
            },
        })

    # Écriture atomique : ce fichier porte les décisions de revue humaine une
    # fois la revue commencée (cf. cartometa/review/server.py) — une
    # interruption en plein `cartometa-geo` ne doit jamais pouvoir le
    # tronquer ou le corrompre.
    write_json_atomic(out_path, {"type": "FeatureCollection", "features": features})
    stats["total"] = len(features)
    stats["output"] = str(out_path)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Construit les géométries des métas")
    parser.add_argument("country", nargs="?", default="PL")
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args()
    # Un code pays saisi en minuscules produisait un fichier `gh.geojson` à
    # côté de `GH.json` : invisible sous Windows (système de fichiers
    # insensible à la casse), cassant partout ailleurs.
    country = args.country.upper()
    stats = build_country(country, args.data, load_config())
    print(f"{country}: {stats['total']} métas — "
          f"national {stats['country']}, ponctuel {stats['spot']}, régional {stats['regional']}, "
          f"échecs {stats['failed']}")
    print(f"  écrit: {stats['output']}")


if __name__ == "__main__":
    main()
