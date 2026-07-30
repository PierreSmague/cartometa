import json
from pathlib import Path

import pytest

from cartometa.geo.admin1 import ADMIN1_NAME, country_regions, region_geometry


def _box(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


FAKE = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"adm1_code": "POL-1", "iso_a2": "PL", "name": "Mazowieckie"},
     "geometry": _box(20.0, 51.0, 22.0, 53.0)},
    {"type": "Feature",
     "properties": {"adm1_code": "POL-2", "iso_a2": "pl", "name": None,
                    "name_en": "Malopolskie"},
     "geometry": _box(19.0, 49.0, 21.0, 50.5)},
    {"type": "Feature",
     "properties": {"adm1_code": "FRA-1", "iso_a2": "FR", "name": "Bretagne"},
     "geometry": _box(-5.0, 47.0, -1.0, 49.0)},
]}


@pytest.fixture
def cache_dir(tmp_path):
    (tmp_path / ADMIN1_NAME).write_text(json.dumps(FAKE), "utf-8")
    return tmp_path


def test_seules_les_regions_du_pays_sont_extraites(cache_dir):
    regions = country_regions("PL", cache_dir)

    codes = {f["properties"]["code"] for f in regions["features"]}
    assert codes == {"POL-1", "POL-2"}


def test_le_code_pays_est_compare_sans_tenir_compte_de_la_casse(cache_dir):
    """Natural Earth n'est pas homogene sur la casse de iso_a2."""
    regions = country_regions("pl", cache_dir)

    assert len(regions["features"]) == 2


def test_le_nom_retombe_sur_name_en_quand_name_est_vide(cache_dir):
    regions = country_regions("PL", cache_dir)

    noms = {f["properties"]["code"]: f["properties"]["name"] for f in regions["features"]}
    assert noms["POL-2"] == "Malopolskie"


def test_l_extraction_est_mise_en_cache_par_pays(cache_dir):
    country_regions("PL", cache_dir)

    assert (cache_dir / "admin1" / "PL.geojson").exists()


def test_le_gros_fichier_n_est_plus_relu_apres_extraction(cache_dir):
    country_regions("PL", cache_dir)
    (cache_dir / ADMIN1_NAME).unlink()

    # Le cache par pays doit suffire : c'est tout l'interet de l'extraction.
    assert len(country_regions("PL", cache_dir)["features"]) == 2


def test_pays_sans_region_leve_keyerror_sans_ecrire_de_cache(cache_dir):
    with pytest.raises(KeyError):
        country_regions("ZZ", cache_dir)

    # Un cache vide empecherait pour toujours une nouvelle tentative.
    assert not (cache_dir / "admin1" / "ZZ.geojson").exists()


def test_le_telechargement_est_injectable(tmp_path):
    appels = []

    def downloader(url: str, dest: Path) -> None:
        appels.append(url)
        dest.write_text(json.dumps(FAKE), "utf-8")

    country_regions("PL", tmp_path, downloader=downloader)

    assert len(appels) == 1


def test_region_geometry_par_code(cache_dir):
    geom = region_geometry("PL", "POL-1", cache_dir)

    assert geom.bounds == (20.0, 51.0, 22.0, 53.0)


def test_region_geometry_code_inconnu(cache_dir):
    with pytest.raises(KeyError):
        region_geometry("PL", "POL-99", cache_dir)
