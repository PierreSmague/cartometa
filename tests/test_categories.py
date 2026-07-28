import pytest
from cartometa.extract.categories import infer_category


@pytest.mark.parametrize("text,expected", [
    ("Bollards are white with a red stripe", "bollards"),
    ("Utility poles have a yellow band", "poteaux"),
    ("The Google car is a white Subaru", "vehicule"),
    ("Orchards are concentrated around Grojec", "vegetation"),
    ("Direction signs are yellow", "signalisation"),
    ("Something entirely unrelated", "autre"),
])
def test_infer_category(text, expected):
    assert infer_category(text, "") == expected


def test_title_takes_precedence_over_description():
    assert infer_category("Bollards", "seen near many trees and orchards") == "bollards"
