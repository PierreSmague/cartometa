import hashlib
import json
from pathlib import Path

import pytest
from shapely.geometry import shape

from cartometa.atomic_write import write_json_atomic
from cartometa.build.geometry import (
    COORD_PRECISION,
    DEFAULT_TOLERANCE,
    SIZE_DIVISOR,
    THIN_DIVISOR,
    THIN_FLOOR_DIVISOR,
    area_ratio,
    effective_tolerance,
    hausdorff,
    simplify_geometry,
)
from cartometa.review.store import CountryPaths, load_geo

pytestmark = pytest.mark.real_data

DATA_DIR = Path("data")
GEO_DIR = DATA_DIR / "geo"
STATUTS = {"validé", "rejeté"}
# Les verdicts memorises ne valent que pour ces parametres : les changer
# invalide tout le cache d'un coup, sans etat ambigu.
CACHE_VERSION = (
    f"tolerance={DEFAULT_TOLERANCE}:divisor={SIZE_DIVISOR}"
    f":thin={THIN_DIVISOR}:floor={THIN_FLOOR_DIVISOR}:coord={COORD_PRECISION}"
)
CACHE_PATH = DATA_DIR / "cache" / "simplification_checks.json"


@pytest.fixture(scope="module")
def features():
    """Every country's features, resolved, parsed ONCE for the whole module.

    Before this fixture each of the five tests re-parsed the 99 files itself
    (~6 s each); the geometry work below is what must dominate, not json.
    Skips when there is not a single feature: walking zero features would give
    the four structural tests an undeserved green.
    """
    tout: list[tuple[str, dict]] = []
    for chemin in sorted(GEO_DIR.glob("*.geojson")):
        paths = CountryPaths(DATA_DIR, chemin.stem)
        for record in load_geo(paths, resolve=True).values():
            tout.append((chemin.name, record.to_feature()))
    if not tout:
        pytest.skip("no geometry: run cartometa-review")
    return tout


@pytest.fixture(scope="module")
def geometries_distinctes(features):
    """One representative per distinct geometry.

    37 US metas share the byte-identical national silhouette: checking it 37
    times multiplies the most expensive step (hausdorff, 46 s on the Canadian
    coastline) for no additional signal.
    """
    distinctes: dict[str, tuple[str, dict]] = {}
    for nom, feature in features:
        geometrie = feature["geometry"]
        if feature["properties"]["status"] != "validé" or geometrie is None:
            continue
        empreinte = hashlib.md5(
            json.dumps(geometrie, separators=(",", ":")).encode()
        ).hexdigest()
        identifiant = f"{nom}: {feature['properties']['id']}"
        distinctes.setdefault(empreinte, (identifiant, geometrie))
    return distinctes


def test_every_saved_geometry_is_valid(geometries_distinctes):
    for identifiant, geometrie in geometries_distinctes.values():
        geom = shape(geometrie)
        assert geom.is_valid, identifiant
        assert not geom.is_empty, identifiant


def test_only_the_two_expected_statuses_exist(features):
    for nom, feature in features:
        statut = feature["properties"]["status"]
        assert statut in STATUTS, f"{nom}: unexpected status {statut!r}"


def test_a_drawn_meta_always_has_a_geometry_and_its_pieces(features):
    for nom, feature in features:
        props = feature["properties"]
        if props["status"] != "validé":
            continue
        assert feature["geometry"] is not None, f"{nom}: {props['id']}"
        assert props["pieces"], f"{nom}: {props['id']} has no piece"


def test_a_rejected_meta_carries_no_geometry(features):
    for nom, feature in features:
        props = feature["properties"]
        if props["status"] == "rejeté":
            assert feature["geometry"] is None, f"{nom}: {props['id']}"


def _verdicts_connus() -> set[str]:
    """The geometry hashes already verified with the current parameters.

    Only successes are remembered: a failure must reappear at every run until
    the data is fixed. Deleting the file forces a full re-check (e.g. after a
    change to simplify_geometry itself).
    """
    if not CACHE_PATH.exists():
        return set()
    try:
        contenu = json.loads(CACHE_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return set()
    return set(contenu.get(CACHE_VERSION, []))


def test_simplification_meets_the_three_criteria_of_section_6_on_real_data(
    geometries_distinctes,
):
    """Acceptance criterion 5 (spec §14): the three checks of §6 — Hausdorff, area
    drift, validity — must pass on the real data, not only on synthetic geometries.

    The ×2 factor on the tolerance follows the convention already in place in
    `tests/test_build_geometry.py::test_the_hausdorff_distance_stays_under_the_effective_tolerance`:
    Douglas-Peucker guarantees a local deviation bounded by the tolerance, but the
    overall Hausdorff distance can accumulate two such deviations on either side of
    one segment.

    If this test fails, do not loosen the thresholds: a published geometry that
    drifts more than the spec promises is a substantive problem, not a test problem.
    """
    verifies = _verdicts_connus()
    violations: list[str] = []
    valides: list[str] = []
    pires = {"hausdorff_sur_tolerance": 0.0, "derive_aire": 0.0}

    for empreinte, (identifiant, original) in geometries_distinctes.items():
        if empreinte in verifies:
            continue
        simplifiee = simplify_geometry(original, DEFAULT_TOLERANCE)

        geom_simplifiee = shape(simplifiee)
        if not geom_simplifiee.is_valid:
            violations.append(f"{identifiant}: invalid geometry")
            continue
        if geom_simplifiee.is_empty:
            violations.append(f"{identifiant}: empty geometry")
            continue

        tolerance = effective_tolerance(original, DEFAULT_TOLERANCE)
        distance = hausdorff(original, simplifiee)
        ratio_tolerance = distance / tolerance if tolerance else 0.0
        conforme = True
        if distance > tolerance * 2:
            conforme = False
            violations.append(
                f"{identifiant}: Hausdorff {distance:.6f}° > "
                f"{tolerance * 2:.6f}° (2x effective tolerance {tolerance:.6f}°, "
                f"i.e. {ratio_tolerance:.2f}x)"
            )

        # Empirical threshold: at SIZE_DIVISOR = 500 the worst drift measured on
        # the real data is 3.3 %; 5 % keeps a deliberate margin above it.
        ratio = area_ratio(original, simplifiee)
        derive = abs(1.0 - ratio)
        if derive > 0.05:
            conforme = False
            violations.append(f"{identifiant}: area drift {derive * 100:.3f}% > 5%")

        if conforme:
            valides.append(empreinte)
        pires["hausdorff_sur_tolerance"] = max(
            pires["hausdorff_sur_tolerance"], ratio_tolerance
        )
        pires["derive_aire"] = max(pires["derive_aire"], derive)

    if valides:
        write_json_atomic(
            CACHE_PATH, {CACHE_VERSION: sorted(verifies | set(valides))}, indent=None
        )

    print(
        f"\n{len(verifies)} geometry(ies) already verified (cache), "
        f"{len(valides)} newly verified"
        f"\nworst Hausdorff / effective tolerance: {pires['hausdorff_sur_tolerance']:.3f}"
        f"\nworst area drift: {pires['derive_aire'] * 100:.4f}%"
    )
    assert not violations, (
        f"{len(violations)} geometry(ies) outside the §6 thresholds:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
