from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from cartometa.build.assets import write_hashed
from cartometa.build.dataset import build_dataset
from cartometa.build.geometry import DEFAULT_TOLERANCE
from cartometa.build.images import MissingImageError, render_image_pair

# Cloudflare Pages refuse un déploiement au-delà de 20 000 fichiers. On
# prévient bien avant pour que le mur soit vu venir des mois à l'avance : la
# parade (déplacer les images vers R2) demande une à deux heures, pas cinq
# minutes de panique.
FILE_COUNT_LIMIT = 20_000
FILE_COUNT_WARNING = 15_000

IMAGE_BASE = "img/"

# Les fichiers empreintés vivent sous `data/h/`, jamais directement sous
# `data/` où réside `manifest.json`. Un motif `/data/*` recouvrirait aussi le
# manifeste, et rien dans le dépôt ne fixe lequel des deux régimes (no-cache
# ou immutable) Cloudflare appliquerait alors : un chevauchement dont l'issue
# est invérifiable gèlerait silencieusement le site sur un manifeste
# périmé. On supprime la question en s'assurant qu'aucun motif ne peut
# jamais matcher les deux chemins à la fois.
HEADERS = """\
/index.html
  Cache-Control: no-cache
/licence.html
  Cache-Control: no-cache
/data/manifest.json
  Cache-Control: no-cache
/data/h/*
  Cache-Control: public, max-age=31536000, immutable
/img/*
  Cache-Control: public, max-age=31536000, immutable
/*.js
  Cache-Control: public, max-age=31536000, immutable
/*.css
  Cache-Control: public, max-age=31536000, immutable
"""


def _dumps(payload) -> bytes:
    """JSON compact et déterministe : sans espaces, clés triées.

    Le tri des clés est ce qui rend l'empreinte reproductible d'un build à
    l'autre — sans lui, l'ordre d'insertion suffirait à renouveler le nom du
    fichier et à vider le cache des visiteurs pour rien.
    """
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def build_site(
    data_dir: Path,
    out_dir: Path,
    viewer_dir: Path,
    countries: list[str],
    tolerance: float = DEFAULT_TOLERANCE,
    skip_images: bool = False,
    image_base: str = IMAGE_BASE,
) -> dict:
    """Produit un `dist/` complet et autonome.

    Table rase à chaque appel : un pays retiré des sources doit disparaître
    du site, pas survivre en fichier orphelin que le déploiement republierait.
    """
    jeu = build_dataset(data_dir, countries, tolerance)

    # Garde-fou : `--out` pointant par erreur vers `viewer/` (ancien défaut du
    # binaire supprimé par cette même migration) ou vers `data/` (une simple
    # transposition avec `--data`) effacerait respectivement le viewer source
    # ou des mois de traçage manuel irremplaçable. On ne rase que ce qui
    # ressemble déjà à une sortie de ce même build.
    if (
        out_dir.exists()
        and any(out_dir.iterdir())
        and not (out_dir / "_headers").exists()
    ):
        raise SystemExit(
            f"{out_dir} n'est pas vide et ne ressemble pas à une sortie de build "
            f"(pas de _headers) — refus de l'effacer."
        )
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    manifeste_pays: dict[str, dict] = {}
    for pays, contenu in sorted(jeu.countries.items()):
        for identifiant, meta in contenu["metas"].items():
            source = meta.pop("image_source", None)
            if skip_images or not source:
                continue
            try:
                noms = render_image_pair(
                    Path(source), out_dir / IMAGE_BASE / pays, identifiant
                )
            except MissingImageError as erreur:
                raise SystemExit(
                    f"{pays}/{identifiant} : {erreur}\n"
                    f"Les pages sources ne sont pas versionnées : vérifie input/."
                ) from erreur
            meta["thumb"] = f"{pays}/{noms['thumb']}"
            meta["full"] = f"{pays}/{noms['full']}"
        nom = write_hashed(out_dir / "data" / "h" / "c", pays, ".json", _dumps(contenu))
        manifeste_pays[pays] = {
            "file": f"h/c/{nom}", "count": len(contenu["geometries"])
        }

    nom_index = "h/" + write_hashed(
        out_dir / "data" / "h", "index", ".json", _dumps(jeu.index)
    )

    noms_statiques = {}
    for fichier, marqueur in (("style.css", "__CSS__"), ("app.js", "__JS__")):
        chemin = viewer_dir / fichier
        octets = chemin.read_bytes()
        tige, suffixe = chemin.stem, chemin.suffix
        noms_statiques[marqueur] = write_hashed(out_dir, tige, suffixe, octets)

    for page in ("index.html", "licence.html"):
        source = viewer_dir / page
        if not source.exists():
            continue
        texte = source.read_text("utf-8")
        for marqueur, nom in noms_statiques.items():
            texte = texte.replace(marqueur, nom)
        (out_dir / page).write_text(texte, "utf-8")

    (out_dir / "_headers").write_text(HEADERS, "utf-8")

    (out_dir / "data" / "manifest.json").write_text(json.dumps({
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta_count": len(jeu.index),
        # Lu par le front, jamais codé en dur : basculer les images vers un
        # bucket R2 se fait en changeant cette seule valeur.
        "image_base": image_base,
        "index": nom_index,
        "countries": manifeste_pays,
    }, ensure_ascii=False), "utf-8")

    fichiers = sum(1 for p in out_dir.rglob("*") if p.is_file())
    return {
        "metas": len(jeu.index),
        "countries": {p: e["count"] for p, e in manifeste_pays.items()},
        "files": fichiers,
        "legacy_statuses": jeu.legacy_statuses,
        "output": str(out_dir),
    }
