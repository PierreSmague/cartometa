import json
import re
from pathlib import Path

import pytest

from cartometa.extract.categories import CATEGORIES
from cartometa.build.dataset import (
    DIFFICULTIES,
    SCOPE_NATIONAL,
    SCOPE_REGIONAL,
    build_dataset,
    discover_countries,
    scope_de,
)
from cartometa.geo.reference import DATASET_NAME


def _carre(x: float, y: float, cote: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [x, y], [x + cote, y], [x + cote, y + cote], [x, y + cote], [x, y],
    ]]}


def _meta(meta_id: str) -> dict:
    return {
        "id": meta_id, "tier": "regional", "title": f"titre {meta_id}",
        "description": "description", "category": "autre",
        "image": f"input/{meta_id}.webp",
        "source_url": f"https://www.plonkit.net/x#{meta_id}",
    }


def _ecrire_pays(data_dir: Path, pays: str, entrees: list[tuple[str, str, float]]) -> None:
    (data_dir / "metas").mkdir(parents=True, exist_ok=True)
    (data_dir / "geo").mkdir(parents=True, exist_ok=True)
    (data_dir / "metas" / f"{pays}.json").write_text(
        json.dumps([_meta(i) for i, _, _ in entrees]), "utf-8"
    )
    (data_dir / "geo" / f"{pays}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"id": i, "status": statut, "pieces": []},
             "geometry": _carre(0.0, 0.0, cote) if statut == "validé" else None}
            for i, statut, cote in entrees
        ],
    }), "utf-8")


def _ecrire_pays_un_meta(data_dir: Path, **champs) -> None:
    """One drawn meta in PL, with `champs` merged into it.

    `_ecrire_pays` builds its metas through `_meta`, which sets the required fields
    only: this is the way to give a single meta an optional one — or, by passing
    nothing, to assert what the build does when that field is absent.
    """
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])
    (data_dir / "metas" / "PL.json").write_text(
        json.dumps([{**_meta("pl1"), **champs}]), "utf-8"
    )


def _ecrire_pays_pieces(
    data_dir: Path, pays: str, entrees: list[tuple[str, list[dict], float]]
) -> None:
    """Like `_ecrire_pays`, but setting each footprint's `pieces`.

    `_ecrire_pays` leaves them empty, which makes it impossible to tell a national
    footprint from a regional one.
    """
    (data_dir / "metas").mkdir(parents=True, exist_ok=True)
    (data_dir / "geo").mkdir(parents=True, exist_ok=True)
    (data_dir / "metas" / f"{pays}.json").write_text(
        json.dumps([_meta(i) for i, _, _ in entrees]), "utf-8"
    )
    (data_dir / "geo" / f"{pays}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "properties": {"id": i, "status": "validé", "pieces": pieces},
             "geometry": _carre(0.0, 0.0, cote)}
            for i, pieces, cote in entrees
        ],
    }), "utf-8")


@pytest.mark.parametrize("pieces,attendu", [
    ([{"kind": "country"}], "national"),
    ([{"kind": "country"}, {"kind": "country"}], "national"),
    ([{"kind": "polygon"}], "regional"),
    ([{"kind": "rect"}], "regional"),
    ([{"kind": "admin1"}], "regional"),
    ([{"kind": "clip"}, {"kind": "polygon"}], "regional"),
    # A clipped country is no longer the whole country: that is what strict equality
    # captures and what a `"country" in kinds` would miss.
    ([{"kind": "country"}, {"kind": "clip"}], "regional"),
    # No published footprint has empty pieces; the fallback guarantees such a
    # footprint would stay visible under "All".
    ([], "regional"),
])
def test_the_scope_is_derived_from_the_drawing(pieces, attendu):
    assert scope_de(pieces) == attendu


def test_the_scope_is_published_for_every_meta(tmp_path):
    """Without this field in the payload, the site has nothing to filter on."""
    _ecrire_pays_pieces(tmp_path / "data", "PL", [
        ("pl1", [{"kind": "country"}], 3.0),
        ("pl2", [{"kind": "polygon"}], 1.0),
    ])

    jeu = build_dataset(tmp_path / "data", ["PL"])

    metas = jeu.countries["PL"]["metas"]
    assert metas["pl1"]["scope"] == "national"
    assert metas["pl2"]["scope"] == "regional"


def test_the_front_end_scope_values_match_the_build_ones():
    """A contract between two languages, hence invisible to the compiler and to anyone
    reviewing a single file.

    The build writes `scope` into the payload, the template declares each collapsible
    section's scope in `data-portee`, and `app.js` splits the metas by comparing the
    two. Renaming one side without the other breaks nothing loudly: both sections
    simply hide themselves as if the point were covered by no meta, without a single
    message.

    Equality, and not inclusion: a scope value with no section of its own would show
    the metas carrying it nowhere, and this test is the only place in the project where
    the two lists meet.
    """
    html = (Path(__file__).resolve().parents[1] / "viewer" / "index.html").read_text("utf-8")

    valeurs = set(re.findall(r'data-portee="([^"]*)"', html))

    assert valeurs == {SCOPE_REGIONAL, SCOPE_NATIONAL}


@pytest.fixture
def data_dir(tmp_path):
    _ecrire_pays(tmp_path / "data", "PL", [("pl1", "validé", 3.0), ("pl2", "rejeté", 1.0)])
    _ecrire_pays(tmp_path / "data", "BW", [("bw1", "validé", 2.0)])
    return tmp_path / "data"


def test_only_validated_metas_enter_the_dataset(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    assert {entree[0] for entree in jeu.index} == {"pl1", "bw1"}


def test_the_index_is_sorted_by_increasing_area(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    assert [entree[0] for entree in jeu.index] == ["bw1", "pl1"]


def test_each_meta_is_in_its_own_country_file_and_nowhere_else(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    assert set(jeu.countries["PL"]["metas"]) == {"pl1"}
    assert set(jeu.countries["BW"]["metas"]) == {"bw1"}


def test_the_index_and_the_country_files_carry_exactly_the_same_ids(data_dir):
    jeu = build_dataset(data_dir, ["PL", "BW"])

    depuis_index = {entree[0] for entree in jeu.index}
    depuis_pays = {i for pays in jeu.countries.values() for i in pays["metas"]}
    assert depuis_index == depuis_pays


def test_each_meta_references_a_published_geometry(data_dir):
    """The deduplication contract: `geom` must always point at an existing entry of
    `geometries`, otherwise the front end has nothing to draw."""
    jeu = build_dataset(data_dir, ["PL", "BW"])

    for pays in jeu.countries.values():
        for meta in pays["metas"].values():
            assert meta["geom"] in pays["geometries"]


def test_the_index_carries_the_bbox_and_the_country(data_dir):
    jeu = build_dataset(data_dir, ["BW"])

    identifiant, pays, min_lon, min_lat, max_lon, max_lat, surface = jeu.index[0]
    assert (identifiant, pays) == ("bw1", "BW")
    assert (min_lon, min_lat, max_lon, max_lat) == (0.0, 0.0, 2.0, 2.0)
    assert surface == pytest.approx(4.0)


def test_the_meta_carries_the_path_of_its_source_image(data_dir):
    jeu = build_dataset(data_dir, ["BW"])

    assert jeu.countries["BW"]["metas"]["bw1"]["image_source"] == "input/bw1.webp"


def test_the_meta_carries_the_path_of_its_rmrg_trace(tmp_path):
    """RMRG metas hold an `overlay` (the guide's region mini-map): the build
    needs its path to bake the trace into the published images."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "BW", [("bw1", "validé", 2.0)])
    metas = json.loads((data_dir / "metas" / "BW.json").read_text("utf-8"))
    metas[0]["overlay"] = "input/bw1-trace.svg"
    (data_dir / "metas" / "BW.json").write_text(json.dumps(metas), "utf-8")

    jeu = build_dataset(data_dir, ["BW"])

    assert jeu.countries["BW"]["metas"]["bw1"]["overlay_source"] == "input/bw1-trace.svg"


def test_a_meta_without_a_trace_carries_none(data_dir):
    jeu = build_dataset(data_dir, ["BW"])

    assert jeu.countries["BW"]["metas"]["bw1"]["overlay_source"] is None


def test_a_country_with_no_validated_meta_is_absent_from_the_result(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])
    (data_dir / "geo" / "BD.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), "utf-8"
    )

    jeu = build_dataset(data_dir, ["BD", "PL"])

    assert set(jeu.countries) == {"PL"}


def test_legacy_statuses_are_counted_and_not_published(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "LG", [("lg1", "validé", 1.0)])
    chemin = data_dir / "geo" / "LG.geojson"
    geo = json.loads(chemin.read_text("utf-8"))
    geo["features"].append({
        "type": "Feature",
        "properties": {"id": "lg2", "status": "auto", "pieces": []},
        "geometry": _carre(5.0, 5.0, 1.0),
    })
    chemin.write_text(json.dumps(geo), "utf-8")
    (data_dir / "metas" / "LG.json").write_text(
        json.dumps([_meta("lg1"), _meta("lg2")]), "utf-8"
    )

    jeu = build_dataset(data_dir, ["LG"])

    assert jeu.legacy_statuses == 1
    assert set(jeu.countries["LG"]["metas"]) == {"lg1"}


def test_a_proposed_footprint_is_neither_published_nor_counted_as_legacy(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "metas").mkdir(parents=True)
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "metas" / "PL.json").write_text(
        json.dumps([_meta("aaaa"), _meta("bbbb")]), "utf-8")
    (data_dir / "geo" / "PL.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _carre(0, 0, 1), "properties": {
                "id": "aaaa", "status": "validé",
                "pieces": [{"kind": "polygon", "ring": [[0, 0], [1, 0], [1, 1]]}]}},
            {"type": "Feature", "geometry": _carre(2, 2, 1), "properties": {
                "id": "bbbb", "status": "proposé",
                "pieces": [{"kind": "polygon", "ring": [[2, 2], [3, 2], [3, 3]]}]}},
        ],
    }), "utf-8")

    jeu = build_dataset(data_dir, ["PL"])

    assert set(jeu.countries["PL"]["metas"]) == {"aaaa"}
    assert jeu.legacy_statuses == 0


def test_a_stripped_reference_geometry_is_resolved_at_build_time(tmp_path):
    """`save_geo` (task 3) strips a footprint whose pieces are entirely reference
    kinds down to `geometry: None`, precisely so the versioned geojson does not carry
    a byte-for-byte copy of the Natural Earth silhouette. The build must not take that
    `None` literally — it has to resolve the pieces through `load_geo(resolve=True)`,
    exactly like the review server does when it reopens the meta, and publish the
    rebuilt geometry rather than drop the footprint."""
    data_dir = tmp_path / "data"
    (data_dir / "metas").mkdir(parents=True)
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "cache").mkdir(parents=True)
    (data_dir / "metas" / "PL.json").write_text(json.dumps([_meta("pl1")]), "utf-8")
    (data_dir / "geo" / "PL.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": None,
            "properties": {"id": "pl1", "status": "validé",
                           "pieces": [{"kind": "country"}]},
        }],
    }), "utf-8")
    (data_dir / "cache" / DATASET_NAME).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"ISO_A2": "PL", "ISO_A2_EH": "PL", "NAME": "Poland"},
            "geometry": _carre(14.0, 49.0, 6.0),
        }],
    }), "utf-8")

    jeu = build_dataset(data_dir, ["PL"])

    empreinte = jeu.countries["PL"]["metas"]["pl1"]["geom"]
    geometrie = jeu.countries["PL"]["geometries"][empreinte]
    assert geometrie is not None and geometrie["coordinates"]


def test_geometries_present_but_no_meta_raises(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "geo" / "ZZ.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "zz1", "status": "validé", "pieces": []},
                      "geometry": _carre(0.0, 0.0, 1.0)}],
    }), "utf-8")

    with pytest.raises(SystemExit, match=r"metas\.json"):
        build_dataset(data_dir, ["ZZ"])


def test_discover_countries_sorts_and_uppercases(data_dir):
    assert discover_countries(data_dir) == ["BW", "PL"]


def test_a_footprint_with_far_apart_parts_gives_several_index_rows(tmp_path):
    """The viewer's prefilter works on the index bboxes: a single bbox for a footprint
    straddling the antimeridian covers the planet and filters nothing any more. Each
    group of parts carries its own row — same id, same area, distinct bbox — and the
    viewer dedupes the ids."""
    data_dir = tmp_path / "data"
    (data_dir / "metas").mkdir(parents=True)
    (data_dir / "geo").mkdir(parents=True)
    (data_dir / "metas" / "RU.json").write_text(json.dumps([_meta("ru1")]), "utf-8")
    (data_dir / "geo" / "RU.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": "ru1", "status": "validé", "pieces": []},
                      "geometry": {"type": "MultiPolygon", "coordinates": [
                          _carre(170.0, 55.0, 9.0)["coordinates"],
                          _carre(-179.0, 55.0, 9.0)["coordinates"],
                      ]}}],
    }), "utf-8")

    jeu = build_dataset(data_dir, ["RU"])

    lignes = [e for e in jeu.index if e[0] == "ru1"]
    assert len(lignes) == 2
    assert all(e[4] - e[2] < 30 for e in lignes)  # no bbox crosses ±180°
    assert len({tuple(e[2:6]) for e in lignes}) == 2
    assert len({e[6] for e in lignes}) == 1  # same area: the sort stays stable


def test_two_metas_with_the_same_footprint_share_a_single_geometry(tmp_path):
    """76 % of the published data/ directory was duplicated byte-identical geometry
    (25.9 MB out of 34.2 measured): each meta carried its own copy of its footprint, and
    RU stored the same 330 KB national outline 19 times over. So geometries are published
    once, indexed by content fingerprint, and each meta references its own via `geom`."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 2.0), ("pl2", "validé", 2.0)])

    jeu = build_dataset(data_dir, ["PL"])

    pays = jeu.countries["PL"]
    assert len(pays["geometries"]) == 1
    empreintes = {pays["metas"][i]["geom"] for i in ("pl1", "pl2")}
    assert empreintes == set(pays["geometries"])


def test_two_metas_with_different_footprints_share_nothing(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 2.0), ("pl2", "validé", 3.0)])

    jeu = build_dataset(data_dir, ["PL"])

    pays = jeu.countries["PL"]
    assert len(pays["geometries"]) == 2
    assert pays["metas"]["pl1"]["geom"] != pays["metas"]["pl2"]["geom"]


def test_a_footprint_without_text_is_counted_as_an_orphan(tmp_path):
    """A drawn geometry whose meta has vanished must not evaporate silently: the build
    has to count it and name it, as it already does for legacy statuses. It happened for
    real: `man-d338` (PH) was ignored without a word while the build announced a
    success."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0), ("pl2", "validé", 1.0)])
    (data_dir / "metas" / "PL.json").write_text(json.dumps([_meta("pl1")]), "utf-8")

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.orphans == [("PL", "pl2")]
    assert set(jeu.countries["PL"]["metas"]) == {"pl1"}


def test_an_orphaned_manual_footprint_fails_the_build(tmp_path):
    """`data/manual/` is versioned precisely because that data is irreplaceable: a
    `man-*` drawing without text is data loss, not a mere regeneration lag. The build has
    to fail hard."""
    data_dir = tmp_path / "data"
    _ecrire_meta_manuelle(data_dir, "XX", "man-1a2b")
    geo_path = data_dir / "geo" / "XX.geojson"
    geo = json.loads(geo_path.read_text("utf-8"))
    geo["features"].append({
        "type": "Feature",
        "properties": {"id": "man-perdu", "status": "validé", "pieces": []},
        "geometry": _carre(5.0, 5.0, 1.0),
    })
    geo_path.write_text(json.dumps(geo), "utf-8")

    with pytest.raises(SystemExit, match=r"man-perdu"):
        build_dataset(data_dir, ["XX"])


def _ecrire_meta_manuelle(data_dir: Path, pays: str, meta_id: str,
                          source_url: str = "") -> None:
    """A meta entered through the reviewer's `N` key.

    Unlike the Plonk It texts, `data/manual/` is versioned: a contributor's image lands
    in the repository along with their drawing. And its `source_url` is optional — such
    metas are often found while exploring a map, with no original page to cite — hence
    the empty string by default, exactly as `cartometa/review/manual.py` writes it.
    """
    manuel = data_dir / "manual" / pays
    (manuel / "images").mkdir(parents=True, exist_ok=True)
    (manuel / "metas.json").write_text(json.dumps([{
        "id": meta_id, "tier": "manual", "title": f"titre {meta_id}",
        "description": "description", "category": "autre", "origin": "manual",
        "image": f"data/manual/{pays}/images/{meta_id}.png",
        "source_url": source_url,
    }]), "utf-8")
    (data_dir / "geo").mkdir(parents=True, exist_ok=True)
    (data_dir / "geo" / f"{pays}.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature",
                      "properties": {"id": meta_id, "status": "validé",
                                     "pieces": []},
                      "geometry": _carre(0.0, 0.0, 1.0)}],
    }), "utf-8")


def test_a_manual_meta_is_published(tmp_path):
    """Coverage restored: the two tests of the manual path lived in
    `tests/test_export.py`, deleted along with the old export command without anyone
    carrying them over here."""
    data_dir = tmp_path / "data"
    _ecrire_meta_manuelle(data_dir, "XX", "man-1a2b")

    jeu = build_dataset(data_dir, ["XX"])

    assert [entree[0] for entree in jeu.index] == ["man-1a2b"]
    meta = jeu.countries["XX"]["metas"]["man-1a2b"]
    assert meta["image_source"] == "data/manual/XX/images/man-1a2b.png"


def test_a_country_without_imported_source_but_with_manual_metas_succeeds(tmp_path):
    """The absence of `data/metas/<CC>.json` must not be fatal: the manual source alone
    is enough. The `metas/` folder is not even created here."""
    data_dir = tmp_path / "data"
    _ecrire_meta_manuelle(data_dir, "YY", "man-only1")

    jeu = build_dataset(data_dir, ["YY"])

    assert not (data_dir / "metas").exists()
    assert [entree[0] for entree in jeu.index] == ["man-only1"]


def test_a_manual_meta_without_source_crosses_the_build_as_an_empty_string(tmp_path):
    """The source field is optional on entry and stays so here: it is the front end that
    must refrain from showing an empty "source" link, not the build that must invent a
    URL. So we check the empty string arrives intact in the country file, with no
    exception and no fabricated value."""
    data_dir = tmp_path / "data"
    _ecrire_meta_manuelle(data_dir, "ZZ", "man-nosrc", source_url="")

    jeu = build_dataset(data_dir, ["ZZ"])

    assert jeu.countries["ZZ"]["metas"]["man-nosrc"]["source_url"] == ""


def _contour_carre(pays: str) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [0.0, 0.0], [6.0, 0.0], [6.0, 6.0], [0.0, 6.0], [0.0, 0.0],
    ]]}


def test_the_country_outline_is_published_when_it_is_provided(tmp_path):
    """The Anki cards' mini-map draws the footprint over the country silhouette: without
    `outline` in the country file, the front end has no background to draw."""
    _ecrire_pays(tmp_path / "data", "PL", [("pl1", "validé", 1.0)])

    jeu = build_dataset(tmp_path / "data", ["PL"], outline_de=_contour_carre)

    contour = jeu.countries["PL"]["outline"]
    assert contour["type"] == "Polygon"


def test_without_an_outline_provider_the_key_is_absent(tmp_path):
    """The absence of the key (and not a null value) is the contract with the front end,
    which tests `pays.outline` for truthiness."""
    _ecrire_pays(tmp_path / "data", "PL", [("pl1", "validé", 1.0)])

    jeu = build_dataset(tmp_path / "data", ["PL"])

    assert "outline" not in jeu.countries["PL"]


def test_a_provider_returning_none_writes_no_outline(tmp_path):
    """`None` is the provider's fallback value (country absent from Natural Earth,
    dataset unreachable): the country is published anyway, without a background."""
    _ecrire_pays(tmp_path / "data", "PL", [("pl1", "validé", 1.0)])

    jeu = build_dataset(tmp_path / "data", ["PL"], outline_de=lambda pays: None)

    assert "outline" not in jeu.countries["PL"]


# --- Category overrides ------------------------------------------------------
# `data/metas/` is gitignored and regenerated by `cartometa-extract`, so a
# category judgement stored there is lost on the next extract. The corrections
# live in a versioned file applied at build time instead.

def _ecrire_overrides(data_dir: Path, contenu: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "categories.json").write_text(json.dumps(contenu), "utf-8")


def test_an_override_replaces_the_inferred_category(tmp_path):
    """The whole point of the file: the human corrects the rules, and the
    correction survives a `cartometa-extract` that rewrites data/metas/."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])
    _ecrire_overrides(data_dir, {"PL": {"pl1": "landscape"}})

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.countries["PL"]["metas"]["pl1"]["category"] == "landscape"


def test_a_meta_absent_from_the_overrides_keeps_its_category(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])
    _ecrire_overrides(data_dir, {"PL": {"pl-autre": "landscape"}})

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.countries["PL"]["metas"]["pl1"]["category"] == "autre"


def test_an_override_for_an_unknown_id_is_reported(tmp_path):
    """A typo in a hand-edited file must not leave a meta silently unfixed."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])
    _ecrire_overrides(data_dir, {"PL": {"pl-typo": "landscape"}})

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.unknown_overrides == [("PL", "pl-typo")]


def test_overrides_of_countries_not_being_built_are_not_reported(tmp_path):
    """A contributor running `cartometa-build FR` must not be warned about the
    other 87 countries' overrides."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])
    _ecrire_overrides(data_dir, {"PL": {"pl1": "landscape"}, "BW": {"bw9": "car"}})

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.unknown_overrides == []


def test_a_missing_overrides_file_is_not_an_error(tmp_path):
    """Deleting the file changes categories; it never breaks the build."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.countries["PL"]["metas"]["pl1"]["category"] == "autre"
    assert jeu.unknown_overrides == []


def test_an_override_to_an_unknown_category_is_refused(tmp_path):
    """Typing `landscpae` must fail loudly rather than publish a category the
    site has no pill for: the meta would show under All and be unreachable
    through every category filter."""
    data_dir = tmp_path / "data"
    _ecrire_pays(data_dir, "PL", [("pl1", "validé", 3.0)])
    _ecrire_overrides(data_dir, {"PL": {"pl1": "landscpae"}})

    with pytest.raises(SystemExit, match="landscpae"):
        build_dataset(data_dir, ["PL"])


def test_the_front_end_category_values_match_the_build_ones():
    """A contract between two languages, invisible to the compiler.

    The build writes `category` into the payload, the template declares one pill
    per category in `data-categorie`, and `app.js` filters by comparing the two
    for equality. Renaming one side without the other breaks nothing loudly: the
    pill simply matches no meta and the gallery reads empty.

    The leading empty value is the "All" pill, which filters nothing.
    """
    html = (Path(__file__).resolve().parents[1] / "viewer" / "index.html").read_text("utf-8")

    valeurs = re.findall(r'data-categorie="([^"]*)"', html)

    assert valeurs == ["", *CATEGORIES]


def test_a_meta_with_no_difficulty_is_published_unrated(tmp_path):
    """The field is optional and most metas do not have it. It must not be guessed:
    defaulting to `Beginner` would make the site claim a level nobody has judged, on
    every meta entered before the field existed."""
    data_dir = tmp_path / "data"
    _ecrire_pays_un_meta(data_dir)

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.countries["PL"]["metas"]["pl1"]["difficulty"] is None


def test_a_filled_difficulty_is_published_as_it_stands(tmp_path):
    data_dir = tmp_path / "data"
    _ecrire_pays_un_meta(data_dir, difficulty="Intermediate")

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.countries["PL"]["metas"]["pl1"]["difficulty"] == "Intermediate"


def test_an_empty_difficulty_counts_as_unrated(tmp_path):
    """What an editing form leaves behind when the level is cleared. It means "not
    rated", and must not be taken for an unknown level and stop the build."""
    data_dir = tmp_path / "data"
    _ecrire_pays_un_meta(data_dir, difficulty="")

    jeu = build_dataset(data_dir, ["PL"])

    assert jeu.countries["PL"]["metas"]["pl1"]["difficulty"] is None


def test_an_unknown_difficulty_is_refused(tmp_path):
    """Same reasoning as an unknown category: `Expert` must fail loudly rather than
    be published, since the site has no pill for it — the meta would show under All
    and be unreachable through every difficulty filter."""
    data_dir = tmp_path / "data"
    _ecrire_pays_un_meta(data_dir, difficulty="Expert")

    with pytest.raises(SystemExit, match="Expert"):
        build_dataset(data_dir, ["PL"])


def test_the_front_end_difficulty_values_match_the_build_ones():
    """The same cross-language contract as for the categories above, and just as
    silent when it breaks: `app.js` filters by comparing `data-difficulte` to the
    `difficulty` the build wrote, for equality.

    The leading empty value is the "All" pill, which filters nothing. The trailing
    `none` is the "Not rated" one: a value the build never writes, since it selects
    the metas that carry no difficulty at all.
    """
    html = (Path(__file__).resolve().parents[1] / "viewer" / "index.html").read_text("utf-8")

    valeurs = re.findall(r'data-difficulte="([^"]*)"', html)

    assert valeurs == ["", *DIFFICULTIES, "none"]
