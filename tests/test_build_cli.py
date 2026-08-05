import pytest

from cartometa.build.cli import verifier_cle_google

CLE_PLAUSIBLE = "AIza" + "B" * 35


def test_a_google_shaped_key_passes():
    verifier_cle_google(CLE_PLAUSIBLE)


def test_an_absent_key_passes():
    """Building without a key is a normal case: the site only loses its base map
    switch, and a contributor does not have to own a key."""
    verifier_cle_google("")


@pytest.mark.parametrize("valeur, what_it_is", [
    # The case actually lived through: a 40-character hex fingerprint found in a
    # file named api_key.txt, published as a key. The build succeeded, and only
    # Google refused — in production.
    ("2f8a38d1211a1623d61b68935c60344e5a37b74c", "hex fingerprint"),
    ("AIzaSyFausseCle", "too short"),
    ("AIza" + "B" * 36, "too long"),
    ("BIza" + "B" * 35, "wrong prefix"),
    ("AIza" + "B" * 34 + "!", "forbidden character"),
    ("  " + CLE_PLAUSIBLE + "  ", "surrounding spaces"),
])
def test_what_cannot_be_a_key_stops_the_build(valeur, what_it_is):
    with pytest.raises(SystemExit) as echec:
        verifier_cle_google(valeur)
    # The message must name the length: that is what was missing the day the mistake
    # was made, when nothing told the two strings apart by eye.
    assert str(len(valeur)) in str(echec.value)
