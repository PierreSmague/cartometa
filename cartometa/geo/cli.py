from __future__ import annotations
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from shapely.geometry import Point, box, mapping, shape
from skimage.measure import label, regionprops

from dataclasses import replace

from cartometa.atomic_write import write_json_atomic
from cartometa.config import Config, load_config
from cartometa.geo.calibrate import (
    Calibration,
    fit_calibration,
    load_calibration,
    save_calibration,
    warn_if_below_threshold,
)
from cartometa.geo.confidence import evaluate
from cartometa.geo.reference import country_geometry, main_landmass
from cartometa.geo.silhouette import inset_variants, touches_image_edge
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


def _calibration_reference(country: str, data_dir: Path, cfg: Config):
    """Référence géographique à laquelle aligner la silhouette dessinée.

    Deux corrections par rapport au contour Natural Earth brut, parce que la
    référence doit représenter ce que Plonk It DESSINE, pas le pays légal :

    - `calibration.reference_bbox_clip` (config) rogne les pays dont le
      template omet une partie du territoire (l'Indonésie est dessinée sans
      la Papouasie, faute de couverture Street View) ;
    - sinon, `main_landmass` écarte les territoires distants négligeables
      (îles du Prince-Édouard de l'Afrique du Sud).

    N'affecte que la calibration : la géométrie publiée reste le pays complet.
    """
    geometry = country_geometry(country, data_dir / "cache")
    clip = (cfg.get("calibration.reference_bbox_clip") or {}).get(country)
    if clip:
        return geometry.intersection(box(*clip))
    return main_landmass(geometry)


def _calibration_for(country: str, metas: list[dict], data_dir: Path, cfg: Config) -> Calibration | None:
    """Calibre une fois par pays, en tournoi : le meilleur IoU gagne.

    Prendre la première image venue s'est avéré être la principale cause de
    calibrations médiocres (mesuré : Namibie 0,79 sur une carte rognée alors
    qu'une autre image du même pays donne 0,98 ; Indonésie 0,26 sur une
    carte régionale de Bali). On essaie donc jusqu'à `calibration.max_images`
    images, chacune sous ses variantes de silhouette (plus grande composante,
    et union des composantes pour les archipels), plus un fit « hors-cadre
    exclu » quand la silhouette touche le bord physique de l'image (carte
    rognée par la capture). Arrêt anticipé dès `calibration.target_iou` :
    un pays au template propre ne paie qu'un fit, comme avant.
    """
    path = data_dir / "calib" / f"{country}.json"
    if path.exists():
        return load_calibration(path)

    reference = _calibration_reference(country, data_dir, cfg)
    # Une méta `spot` est préférée : son pin n'ampute pas la silhouette.
    ordered = sorted(metas, key=lambda m: 0 if m["tier"] == "spot" else 1)
    target_iou = cfg.get("calibration.target_iou", 0.95)
    max_images = int(cfg.get("calibration.max_images", 15))
    visible_min = cfg.get("calibration.edge_visible_min", 0.75)

    best: Calibration | None = None
    tried = 0
    for meta in ordered:
        if not meta.get("image"):
            continue
        variants = inset_variants(_load_rgba(meta["image"]), cfg)
        if not variants:
            continue
        tried += 1
        for inset in variants:
            candidates = [fit_calibration(inset.mask, reference, cfg, warn=False)]
            if touches_image_edge(inset.mask):
                candidates.append(
                    fit_calibration(inset.mask, reference, cfg, edge_aware=True, warn=False)
                )
            for calib in candidates:
                if calib.visible < visible_min:
                    continue
                if best is None or calib.iou > best.iou:
                    best = replace(calib, variant=inset.variant, meta_id=meta["id"])
        if best is not None and best.iou >= target_iou:
            break
        if tried >= max_images:
            break

    if best is None:
        return None
    warn_if_below_threshold(best, cfg)
    save_calibration(path, best)
    return best


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
                # La même variante de silhouette que la calibration retenue :
                # si le pays est un archipel calé sur toutes ses îles, une
                # zone rouge sur une île secondaire doit compter aussi.
                variants = inset_variants(rgba, cfg)
                inset = next(
                    (i for i in variants if i.variant == calib.variant),
                    variants[0] if variants else None,
                )
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
