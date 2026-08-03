from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from cartometa.build.assets import write_hashed
from cartometa.build.dataset import build_dataset
from cartometa.build.geometry import DEFAULT_TOLERANCE
from cartometa.build.image_cache import ImageCache
from cartometa.build.images import MissingImageError, render_image_pair

# Cloudflare Pages refuse un déploiement au-delà de 20 000 fichiers. On
# prévient bien avant pour que le mur soit vu venir des mois à l'avance : la
# parade (déplacer les images vers R2) demande une à deux heures, pas cinq
# minutes de panique.
FILE_COUNT_LIMIT = 20_000
FILE_COUNT_WARNING = 15_000

IMAGE_BASE = "img/"

# Actifs copiés depuis `viewer/` sous un nom empreinté, et le marqueur qu'ils
# remplacent dans les gabarits HTML. Les ajouter ici suffit : la boucle de
# copie, la substitution et la vérification d'intégrité en dérivent toutes.
ACTIFS_STATIQUES = (
    ("style.css", "__CSS__"),
    ("app.js", "__JS__"),
    ("favicon.svg", "__ICON_SVG__"),
    ("favicon.png", "__ICON_PNG__"),
    ("og.png", "__OG_IMAGE__"),
    # Greffon Leaflet du fond Google. Publié et empreinté comme les autres,
    # mais délibérément absent des gabarits : le front va le chercher par le
    # manifeste, et seulement si le visiteur demande ce fond. Une balise
    # `<script>` le ferait télécharger par tout le monde, y compris par
    # l'immense majorité qui ne quittera jamais OpenStreetMap.
    ("googleMutant.js", "__GOOGLE_MUTANT__"),
)

# Origine canonique du site, substituée à `__SITE_URL__` dans les gabarits.
# Les balises Open Graph exigent des URL absolues : un chemin relatif est
# ignoré par la plupart des robots d'aperçu, et la vignette reste vide. Le site
# répond aujourd'hui sur trois origines (le domaine, son `www`, et
# `cartometa.pages.dev`) — d'où un réglage explicite plutôt qu'un domaine
# codé en dur dans un gabarit servi depuis les trois.
SITE_URL = "https://cartometa.com"

# Les fichiers empreintés vivent sous `data/h/`, jamais directement sous
# `data/` où réside `manifest.json`. Un motif `/data/*` recouvrirait aussi le
# manifeste, et rien dans le dépôt ne fixe lequel des deux régimes (no-cache
# ou immutable) Cloudflare appliquerait alors : un chevauchement dont l'issue
# est invérifiable gèlerait silencieusement le site sur un manifeste
# périmé. On supprime la question en s'assurant qu'aucun motif ne peut
# jamais matcher les deux chemins à la fois.
#
# Les pages HTML sont déclarées sous leurs DEUX formes. Cloudflare Pages sert
# des URL propres : il redirige `/index.html` vers `/` et `/licence.html` vers
# `/licence`. Vérifié en production, une règle écrite sur le seul nom de
# fichier ne s'applique donc qu'à une adresse que personne ne visite, et la
# vraie page retombe sur le défaut de l'hébergeur. Celui-ci se trouve être
# équivalent (`max-age=0, must-revalidate`), mais dépendre du défaut d'un
# tiers pour une garantie qu'on croit avoir écrite est exactement le piège
# qu'on a déjà rencontré sur le manifeste.
#
# `/404.html` n'est déclarée que sous son nom de fichier, et c'est assumé :
# Cloudflare sert cette page sous l'adresse inconnue demandée, qu'on ne peut
# pas énumérer. Le motif fourre-tout `/*` qui les couvrirait toutes
# recouvrirait aussi `/data/h/*` et `/*.js` — on retomberait exactement dans le
# chevauchement décrit ci-dessus, en pire. On préfère donc ne rien promettre
# pour ces adresses plutôt que de mettre en péril le cache immuable.
HEADERS = """\
/
  Cache-Control: no-cache
/index.html
  Cache-Control: no-cache
/licence
  Cache-Control: no-cache
/licence.html
  Cache-Control: no-cache
/404
  Cache-Control: no-cache
/404.html
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
/*.svg
  Cache-Control: public, max-age=31536000, immutable
/*.png
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


class ResultatVerification(NamedTuple):
    """Résultat de `verifier_integrite` : ce qui manque, et si les images
    ont seulement été mises de côté parce qu'elles vivent ailleurs."""

    manquants: list[str]
    images_ignorees: bool


def _base_est_absolue(image_base: str) -> bool:
    """Vrai quand `image_base` désigne un stockage externe plutôt qu'un
    chemin sous `out_dir` : un schéma (`https://`, `s3://`...) ou un préfixe
    protocole-relatif (`//cdn.example/...`). Dans les deux cas les images ne
    sont plus écrites là où le manifeste les cherche — les vérifier sous
    `out_dir` produirait des milliers de faux positifs.
    """
    a_un_schema = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", image_base)
    return bool(a_un_schema) or image_base.startswith("//")


def verifier_integrite(out_dir: Path, manifeste: dict) -> ResultatVerification:
    """Vérifie que tout chemin référencé par le manifeste existe réellement
    sur le disque : l'index global, chaque fichier pays, et — sauf quand
    `image_base` pointe vers un stockage externe — la vignette (`thumb`) et
    l'image pleine taille (`full`) de chaque méta. Vérifie aussi la page
    elle-même : `index.html`, `_headers`, et chaque actif empreinté déclaré
    dans `ACTIFS_STATIQUES` (script, feuille de style, favicons).
    `licence.html` reste optionnelle : sa présence n'est pas requise ici.

    Fonction pure, sans effet de bord : elle ne fait qu'inspecter `out_dir`
    et le `manifeste` déjà écrit, ce qui la rend testable sans construire un
    site complet et rejouable après-coup sur un `dist/` déjà déployé — y
    compris sur un manifeste qu'on n'a pas soi-même produit, donc qui peut
    être incomplet ou tronqué : un fichier absent, illisible ou une clé
    manquante sont chacun signalés, jamais laissés remonter en exception.

    Sans ce volet page, l'incident qui a motivé ce contrôle (un `rmtree`
    concurrent vidant `dist/` en cours d'écriture) pouvait toujours produire
    un build qui se déclare réussi alors que la page déployée n'a plus de
    script ni de feuille de style — un site qui rend blanc, sans la moindre
    erreur au build.
    """
    manquants: list[str] = []

    if not (out_dir / "index.html").exists():
        manquants.append(str(out_dir / "index.html"))
    if not (out_dir / "_headers").exists():
        manquants.append(str(out_dir / "_headers"))
    # Le nom exact est empreinté (hash de contenu) et n'est pas repris dans le
    # manifeste : on vérifie donc le motif plutôt qu'un nom précis, ce qui
    # marche aussi bien juste après ce build que rejoué plus tard sur un
    # `dist/` produit ailleurs.
    # Dérivé de ACTIFS_STATIQUES : ajouter un actif là-bas suffit à ce qu'il
    # soit vérifié ici, sans risquer d'oublier une des deux listes.
    for fichier, _ in ACTIFS_STATIQUES:
        tige, suffixe = Path(fichier).stem, Path(fichier).suffix
        motif = f"{tige}.*{suffixe}"
        if not any(out_dir.glob(motif)):
            manquants.append(f"{out_dir / motif} (aucun fichier empreinté trouvé)")

    index_rel = manifeste.get("index")
    if index_rel is None:
        manquants.append("manifeste : clé 'index' absente")
    else:
        chemin_index = out_dir / "data" / index_rel
        if not chemin_index.exists():
            manquants.append(str(chemin_index))

    image_base = manifeste.get("image_base", IMAGE_BASE)
    images_ignorees = _base_est_absolue(image_base)

    for code, entree in manifeste.get("countries", {}).items():
        fichier_rel = entree.get("file")
        if fichier_rel is None:
            manquants.append(f"manifeste : pays '{code}' sans clé 'file'")
            continue
        chemin_pays = out_dir / "data" / fichier_rel
        if not chemin_pays.exists():
            manquants.append(str(chemin_pays))
            continue  # pas de fichier à lire pour en tirer les métas

        if images_ignorees:
            continue

        try:
            contenu = json.loads(chemin_pays.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as erreur:
            # Un disque plein tronque un fichier qui existe toujours : il
            # passe le test .exists() ci-dessus mais son JSON est invalide.
            # C'est un diagnostic distinct d'une absence, pas une exception
            # à laisser remonter — la fonction doit rester la source fiable
            # même sur le cas dégradé qui l'a motivée.
            manquants.append(f"{chemin_pays} (illisible : {erreur})")
            continue

        for meta in contenu.get("metas", {}).values():
            for cle in ("thumb", "full"):
                relatif = meta.get(cle)
                if relatif is None:
                    continue
                chemin_image = out_dir / image_base / relatif
                if not chemin_image.exists():
                    manquants.append(str(chemin_image))

    return ResultatVerification(manquants, images_ignorees)


def build_site(
    data_dir: Path,
    out_dir: Path,
    viewer_dir: Path,
    countries: list[str],
    tolerance: float = DEFAULT_TOLERANCE,
    skip_images: bool = False,
    image_base: str = IMAGE_BASE,
    site_url: str = SITE_URL,
    google_key: str = "",
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

    # Hors de `out_dir`, qui vient d'être rasé : le cache doit survivre au
    # build qu'il accélère. `data/cache/` est déjà gitignoré.
    cache_images = ImageCache(data_dir / "cache" / "images")

    manifeste_pays: dict[str, dict] = {}
    for pays, contenu in sorted(jeu.countries.items()):
        for identifiant, meta in contenu["metas"].items():
            source = meta.pop("image_source", None)
            if skip_images or not source:
                continue
            try:
                noms = render_image_pair(
                    Path(source), out_dir / IMAGE_BASE / pays, identifiant, cache_images
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
    for fichier, marqueur in ACTIFS_STATIQUES:
        chemin = viewer_dir / fichier
        octets = chemin.read_bytes()
        tige, suffixe = chemin.stem, chemin.suffix
        noms_statiques[marqueur] = write_hashed(out_dir, tige, suffixe, octets)

    for page in ("index.html", "licence.html", "404.html"):
        source = viewer_dir / page
        if not source.exists():
            continue
        texte = source.read_text("utf-8")
        for marqueur, nom in noms_statiques.items():
            texte = texte.replace(marqueur, nom)
        # Après les noms empreintés : `__SITE_URL__/__OG_IMAGE__` doit d'abord
        # devenir `__SITE_URL__/og.<hash>.png`, puis l'origine se substitue.
        texte = texte.replace("__SITE_URL__", site_url.rstrip("/"))
        (out_dir / page).write_text(texte, "utf-8")

    (out_dir / "_headers").write_text(HEADERS, "utf-8")

    manifeste = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta_count": len(jeu.index),
        # Lu par le front, jamais codé en dur : basculer les images vers un
        # bucket R2 se fait en changeant cette seule valeur.
        "image_base": image_base,
        "index": nom_index,
        # Nom empreinté du greffon, que le front charge à la demande.
        "google_mutant": noms_statiques["__GOOGLE_MUTANT__"],
        "countries": manifeste_pays,
    }
    # Absente et non vide quand aucune clé n'est fournie : le front n'affiche
    # le sélecteur de fond que si la clé existe. Un contributeur construit
    # sans clé et obtient un site entier, simplement sans fond Google.
    #
    # La clé transite par le build plutôt que par le dépôt. Elle finira de
    # toute façon lisible dans ce manifeste — une clé de navigateur est
    # publique par nature, c'est la restriction par référent qui la protège,
    # pas le secret. Mais elle n'a aucune raison d'entrer dans l'historique
    # git, où elle resterait après toute rotation.
    if google_key:
        manifeste["google_key"] = google_key
    (out_dir / "data" / "manifest.json").write_text(
        json.dumps(manifeste, ensure_ascii=False), "utf-8"
    )

    # Contrôle d'intégrité final : un `dist/` tronqué (disque plein, build
    # interrompu, écriture concurrente qui l'a écrasé en cours de route) ne
    # doit jamais se déclarer complet. Vécu une fois pour de vrai — un build
    # survivant avait rapporté 1710 métas sur 45 pays alors que 11 fichiers
    # pays seulement existaient encore sur le disque.
    verification = verifier_integrite(out_dir, manifeste)
    if verification.manquants:
        n = len(verification.manquants)
        apercu = "\n".join(f"  - {chemin}" for chemin in verification.manquants[:5])
        raise SystemExit(
            f"Build corrompu : {n} chemin(s) référencé(s) par le manifeste "
            f"sont absents de {out_dir} — ce dist/ ne doit pas être déployé.\n"
            f"{apercu}"
        )

    fichiers = sum(1 for p in out_dir.rglob("*") if p.is_file())
    return {
        "metas": len(jeu.index),
        "countries": {p: e["count"] for p, e in manifeste_pays.items()},
        "files": fichiers,
        "legacy_statuses": jeu.legacy_statuses,
        "output": str(out_dir),
    }
