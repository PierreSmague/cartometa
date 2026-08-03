import fnmatch
import json
from pathlib import Path

import pytest
from PIL import Image

from cartometa.build.site import (
    FILE_COUNT_LIMIT,
    FILE_COUNT_WARNING,
    _dumps,
    build_site,
    verifier_integrite,
)


def _carre(x: float, y: float, cote: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [x, y], [x + cote, y], [x + cote, y + cote], [x, y + cote], [x, y],
    ]]}


@pytest.fixture
def projet(tmp_path, monkeypatch):
    """Un projet minimal mais complet : données, images sources, gabarits.

    Les métas stockent le chemin de leur image relatif à la racine du projet
    (convention déjà en place dans `cartometa.extract` et `cartometa.review`),
    donc on se place dans `tmp_path` pour que cette racine soit celle du
    projet jetable et non celle du dépôt réel.
    """
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    (data / "metas").mkdir(parents=True)
    (data / "geo").mkdir(parents=True)
    images = tmp_path / "input"
    images.mkdir()
    Image.new("RGB", (1000, 500), (10, 20, 30)).save(images / "pl1.png")
    (data / "metas" / "PL.json").write_text(json.dumps([{
        "id": "pl1", "tier": "regional", "title": "titre", "description": "desc",
        "category": "autre", "image": "input/pl1.png",
        "source_url": "https://www.plonkit.net/poland#pl1",
    }]), "utf-8")
    (data / "geo" / "PL.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "pl1", "status": "validé", "pieces": []},
                      "geometry": _carre(14.0, 49.0, 5.0)}],
    }), "utf-8")

    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_text("<!doctype html><body>__CSS__ __JS__</body>", "utf-8")
    (viewer / "licence.html").write_text("<!doctype html><body>__CSS__</body>", "utf-8")
    (viewer / "style.css").write_text("body{margin:0}", "utf-8")
    (viewer / "app.js").write_text("console.log('x')", "utf-8")
    return tmp_path


def _manifeste(dist: Path) -> dict:
    return json.loads((dist / "data" / "manifest.json").read_text("utf-8"))


def _regles(headers: str) -> list[tuple[str, dict[str, str]]]:
    """Découpe un fichier `_headers` en (motif, en-têtes), dans l'ordre.

    Une ligne non indentée ouvre un nouveau motif ; les lignes indentées qui
    suivent sont ses en-têtes.
    """
    regles: list[tuple[str, dict[str, str]]] = []
    for ligne in headers.splitlines():
        if not ligne.strip():
            continue
        if not ligne[0].isspace():
            regles.append((ligne.strip(), {}))
        else:
            cle, _, valeur = ligne.strip().partition(":")
            regles[-1][1][cle.strip()] = valeur.strip()
    return regles


def test_la_page_de_licence_est_publiee(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert (dist / "licence.html").exists()


def test_le_manifeste_reference_des_fichiers_qui_existent(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    assert (dist / "data" / manifeste["index"]).exists()
    for entree in manifeste["countries"].values():
        assert (dist / "data" / entree["file"]).exists()


def test_toute_image_referencee_existe(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    base = manifeste["image_base"]
    for entree in manifeste["countries"].values():
        pays = json.loads((dist / "data" / entree["file"]).read_text("utf-8"))
        for meta in pays["metas"].values():
            assert (dist / base / meta["thumb"]).exists()
            assert (dist / base / meta["full"]).exists()


def test_la_meta_ne_porte_plus_le_chemin_source_apres_le_build(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    manifeste = _manifeste(dist)
    pays = json.loads(
        (dist / "data" / manifeste["countries"]["PL"]["file"]).read_text("utf-8")
    )
    assert "image_source" not in pays["metas"]["pl1"]


def test_image_base_est_dans_le_manifeste(projet):
    """La parade au plafond de fichiers : déplacer les images ne touche que ça."""
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert _manifeste(dist)["image_base"] == "img/"


def test_image_base_personnalise_ne_deplace_pas_les_images_sur_le_disque(projet):
    """L'échappatoire au plafond de fichiers : changer `image_base` ne doit
    changer que le préfixe inscrit au manifeste. Les images restent
    toujours écrites sous `out_dir / IMAGE_BASE`, prêtes à être synchronisées
    vers un bucket sans que le code n'ait besoin de changer."""
    dist = projet / "dist"

    build_site(
        projet / "data", dist, projet / "viewer", ["PL"],
        image_base="https://cdn.example/i/",
    )

    assert _manifeste(dist)["image_base"] == "https://cdn.example/i/"
    assert (dist / "img" / "PL").exists()


def test_les_gabarits_recoivent_les_noms_empreintes(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    page = (dist / "index.html").read_text("utf-8")
    assert "__CSS__" not in page and "__JS__" not in page
    assert "style." in page and ".css" in page


def test_le_fichier_headers_est_produit_avec_les_deux_regimes(projet):
    """Le manifeste doit être revalidé à chaque visite, et lui seul.

    Un motif qui matcherait aussi `/data/manifest.json` en plus de la règle
    dédiée rendrait le régime appliqué dépendant d'une priorité Cloudflare
    non documentée dans ce dépôt — potentiellement `immutable`, ce qui
    gèlerait le site sur un manifeste périmé pour toujours.
    """
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    regles = _regles((dist / "_headers").read_text("utf-8"))

    correspondances = [
        (motif, entetes) for motif, entetes in regles
        if fnmatch.fnmatchcase("/data/manifest.json", motif)
    ]
    assert len(correspondances) == 1, (
        f"un seul motif doit matcher le manifeste : {correspondances}"
    )
    motif, entetes = correspondances[0]
    assert motif == "/data/manifest.json"
    assert entetes["Cache-Control"] == "no-cache"

    # Les fichiers empreintés, eux, doivent rester en cache immuable un an.
    empreinte = [
        (motif, entetes) for motif, entetes in regles
        if fnmatch.fnmatchcase("/data/h/index.a1b2c3d4.json", motif)
    ]
    assert len(empreinte) == 1
    assert "immutable" in empreinte[0][1]["Cache-Control"]


def test_dumps_est_independant_de_l_ordre_des_cles():
    """Le tri des clés rend l'empreinte reproductible.

    Sans lui, l'ordre d'insertion suffirait à changer le nom du fichier —
    et donc à vider le cache de tous les visiteurs — sans qu'aucun contenu
    n'ait changé.
    """
    assert _dumps({"b": 1, "a": 2}) == _dumps({"a": 2, "b": 1})


def test_deux_builds_identiques_donnent_les_memes_noms(projet):
    build_site(projet / "data", projet / "d1", projet / "viewer", ["PL"])
    build_site(projet / "data", projet / "d2", projet / "viewer", ["PL"])

    m1, m2 = _manifeste(projet / "d1"), _manifeste(projet / "d2")
    assert m1["index"] == m2["index"]
    # `countries` est le seul payload empreinté qui porte des dictionnaires
    # (`metas`, `geometries`) plutôt que de simples listes — le seul endroit
    # où un tri de clés manquant pourrait se voir.
    assert m1["countries"] == m2["countries"]


def test_skip_images_ne_produit_aucune_image(projet):
    dist = projet / "dist"

    build_site(projet / "data", dist, projet / "viewer", ["PL"], skip_images=True)

    assert not (dist / "img").exists()


def test_le_resultat_compte_les_fichiers_produits(projet):
    resultat = build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert resultat["metas"] == 1
    assert resultat["files"] > 0
    assert FILE_COUNT_WARNING < FILE_COUNT_LIMIT


def test_une_image_source_absente_leve_avec_le_nom_de_la_meta(projet):
    (projet / "input" / "pl1.png").unlink()

    with pytest.raises(SystemExit, match="pl1"):
        build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])


def test_un_build_relance_ecrase_sans_laisser_de_residu(projet):
    dist = projet / "dist"
    build_site(projet / "data", dist, projet / "viewer", ["PL"])
    (dist / "data" / "vieux.json").write_text("{}", "utf-8")

    build_site(projet / "data", dist, projet / "viewer", ["PL"])

    assert not (dist / "data" / "vieux.json").exists()
    # Une vraie sortie de build précédente est toujours remplacée sans que
    # le garde-fou d'écrasement (voir plus bas) ne s'y oppose.
    assert (dist / "_headers").exists()


def test_le_build_refuse_d_ecraser_un_dossier_qui_ne_ressemble_pas_a_une_sortie(projet):
    """`--out` pointant par erreur vers `viewer/` ou vers `data/` (une
    transposition avec `--data`) ne doit jamais être rasé : seul un dossier
    qui porte déjà la marque d'un build précédent (`_headers`) l'est."""
    cible = projet / "cible"
    cible.mkdir()
    (cible / "important.txt").write_text("travail irremplaçable", "utf-8")

    with pytest.raises(SystemExit, match="_headers"):
        build_site(projet / "data", cible, projet / "viewer", ["PL"])

    assert (cible / "important.txt").exists()


# --- Vérification d'intégrité du dist/ (contrôle de non-régression sur la
# panne réelle : un `dist/` tronqué qui se déclare pourtant complet) --------

def _arbre_complet(out_dir: Path) -> dict:
    """Construit à la main un `dist/` minimal mais complet, avec son
    manifeste, sans passer par `build_site` : la fonction pure doit pouvoir
    être testée sur n'importe quel arbre, pas seulement sur sa propre sortie.
    """
    (out_dir / "data" / "h" / "c").mkdir(parents=True)
    (out_dir / "data" / "h" / "index.json").write_text("{}", "utf-8")
    (out_dir / "img" / "PL").mkdir(parents=True)
    (out_dir / "img" / "PL" / "m1.thumb.avif").write_bytes(b"x")
    (out_dir / "img" / "PL" / "m1.full.avif").write_bytes(b"x")
    pays = {
        "metas": {"m1": {"thumb": "PL/m1.thumb.avif", "full": "PL/m1.full.avif"}},
        "geometries": {},
    }
    (out_dir / "data" / "h" / "c" / "PL.json").write_text(json.dumps(pays), "utf-8")
    (out_dir / "index.html").write_text("<!doctype html>", "utf-8")
    (out_dir / "_headers").write_text("", "utf-8")
    (out_dir / "app.a1b2c3d4.js").write_text("", "utf-8")
    (out_dir / "style.a1b2c3d4.css").write_text("", "utf-8")
    return {
        "index": "h/index.json",
        "image_base": "img/",
        "countries": {"PL": {"file": "h/c/PL.json", "count": 1}},
    }


def test_un_arbre_complet_ne_rapporte_rien_de_manquant(tmp_path):
    manifeste = _arbre_complet(tmp_path)

    resultat = verifier_integrite(tmp_path, manifeste)

    assert resultat.manquants == []
    assert resultat.images_ignorees is False


def test_un_fichier_pays_manquant_est_signale(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "data" / "h" / "c" / "PL.json").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("PL.json" in chemin for chemin in resultat.manquants)


def test_une_image_manquante_est_signalee(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "img" / "PL" / "m1.thumb.avif").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("m1.thumb.avif" in chemin for chemin in resultat.manquants)


def test_le_fichier_index_manquant_est_signale(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "data" / "h" / "index.json").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("index.json" in chemin for chemin in resultat.manquants)


def test_un_fichier_pays_corrompu_est_signale_sans_lever(tmp_path):
    """Le cas motivant le contrôle : un disque plein tronque un fichier qui
    continue d'exister (il passe le test `.exists()`) mais dont le JSON est
    invalide. Ça doit rester un diagnostic dans `manquants`, jamais une
    exception qui remonte — sinon le contrôle échoue précisément sur le cas
    qu'il a été construit pour couvrir."""
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "data" / "h" / "c" / "PL.json").write_text("{tronqu", "utf-8")

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("PL.json" in chemin for chemin in resultat.manquants)


def test_un_manifeste_sans_cle_index_est_signale_sans_lever(tmp_path):
    """Rejouable après-coup signifie aussi robuste à un manifeste qu'on n'a
    pas soi-même produit : une clé requise absente doit être diagnostiquée,
    pas lever un `KeyError`."""
    manifeste = _arbre_complet(tmp_path)
    del manifeste["index"]

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("index" in chemin for chemin in resultat.manquants)


def test_un_pays_sans_cle_file_est_signale_sans_lever(tmp_path):
    """Même garde-fou que pour la clé 'index' manquante, mais sur une entrée
    de pays : un `entree["file"]` non protégé lèverait un `KeyError` au lieu
    de rapporter l'absence, contredisant la docstring de la fonction."""
    manifeste = _arbre_complet(tmp_path)
    del manifeste["countries"]["PL"]["file"]

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("PL" in chemin and "file" in chemin for chemin in resultat.manquants)


def test_un_image_base_absolu_ignore_les_images(tmp_path):
    """L'échappatoire objet-storage : quand `image_base` est une URL absolue,
    les images ne vivent plus sous `out_dir` — les vérifier y produirait
    des milliers de faux positifs. Le pays et l'index restent, eux, toujours
    vérifiés : ils sont toujours locaux, quel que soit `image_base`."""
    (tmp_path / "data" / "h" / "c").mkdir(parents=True)
    (tmp_path / "data" / "h" / "index.json").write_text("{}", "utf-8")
    pays = {
        "metas": {"m1": {"thumb": "PL/m1.thumb.avif", "full": "PL/m1.full.avif"}},
        "geometries": {},
    }
    (tmp_path / "data" / "h" / "c" / "PL.json").write_text(json.dumps(pays), "utf-8")
    (tmp_path / "index.html").write_text("<!doctype html>", "utf-8")
    (tmp_path / "_headers").write_text("", "utf-8")
    (tmp_path / "app.a1b2c3d4.js").write_text("", "utf-8")
    (tmp_path / "style.a1b2c3d4.css").write_text("", "utf-8")
    manifeste = {
        "index": "h/index.json",
        "image_base": "https://cdn.example/i/",
        "countries": {"PL": {"file": "h/c/PL.json", "count": 1}},
    }

    resultat = verifier_integrite(tmp_path, manifeste)

    assert resultat.manquants == []
    assert resultat.images_ignorees is True


# --- Le volet « page » du contrôle (item 4 de la revue finale) : l'index.html,
# les _headers et les deux actifs statiques empreintés sont désormais couverts,
# pas seulement les chemins référencés par le manifeste. -------------------

def test_index_html_manquant_est_signale(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "index.html").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("index.html" in chemin for chemin in resultat.manquants)


def test_headers_manquant_est_signale(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "_headers").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("_headers" in chemin for chemin in resultat.manquants)


def test_actif_js_empreinte_manquant_est_signale(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "app.a1b2c3d4.js").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("app" in chemin for chemin in resultat.manquants)


def test_actif_css_empreinte_manquant_est_signale(tmp_path):
    manifeste = _arbre_complet(tmp_path)
    (tmp_path / "style.a1b2c3d4.css").unlink()

    resultat = verifier_integrite(tmp_path, manifeste)

    assert any("style" in chemin for chemin in resultat.manquants)


def test_build_site_reussit_toujours_avec_la_verification_integree(projet):
    """La vérification tourne à chaque build ; sur un projet sain elle ne
    doit jamais faire échouer un build par ailleurs correct."""
    resultat = build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert resultat["metas"] == 1


def test_build_site_leve_systemexit_quand_la_verification_echoue(monkeypatch, projet):
    """Prouve que `build_site` appelle bien la vérification (et pas
    seulement que la fonction fonctionne isolément) : on la remplace par un
    faux qui rapporte un chemin manquant, et on vérifie que `build_site`
    relaie l'échec en `SystemExit` plutôt que de rendre un succès muet."""
    import cartometa.build.site as site

    appels = []

    def faux_verifier(out_dir, manifeste):
        appels.append((out_dir, manifeste))
        return site.ResultatVerification(["dist/fantome.json"], False)

    monkeypatch.setattr(site, "verifier_integrite", faux_verifier)

    with pytest.raises(SystemExit, match="fantome"):
        build_site(projet / "data", projet / "dist", projet / "viewer", ["PL"])

    assert appels, "build_site n'a pas appelé verifier_integrite"
