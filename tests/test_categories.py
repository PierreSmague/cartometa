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


def test_substring_of_unrelated_word_does_not_match():
    # "tree" is a substring of "street": must not trigger vegetation.
    assert infer_category("Street architecture", "Nothing about plants here") == "autre"


def test_word_boundary_still_matches_real_keyword_in_context():
    assert infer_category("Street signs in Poznań are mainly black", "") == "signalisation"


def test_multi_word_expression_is_still_recognized():
    assert infer_category("The Google car is visible in the distance", "") == "vehicule"
