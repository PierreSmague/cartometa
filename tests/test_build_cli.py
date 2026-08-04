import pytest

from cartometa.build.cli import verifier_cle_google

CLE_PLAUSIBLE = "AIza" + "B" * 35


def test_une_cle_de_forme_google_passe():
    verifier_cle_google(CLE_PLAUSIBLE)


def test_une_cle_absente_passe():
    """Construire sans clé est un cas normal : le site perd seulement son
    sélecteur de fond, et un contributeur n'a pas à posséder de clé."""
    verifier_cle_google("")


@pytest.mark.parametrize("valeur, ce_que_c_est", [
    # Le cas réellement vécu : une empreinte hexadécimale de 40 caractères
    # trouvée dans un fichier nommé api_key.txt, publiée pour une clé. Le
    # build réussissait, et seul Google refusait — en production.
    ("2f8a38d1211a1623d61b68935c60344e5a37b74c", "empreinte hexadécimale"),
    ("AIzaSyFausseCle", "trop courte"),
    ("AIza" + "B" * 36, "trop longue"),
    ("BIza" + "B" * 35, "mauvais préfixe"),
    ("AIza" + "B" * 34 + "!", "caractère interdit"),
    ("  " + CLE_PLAUSIBLE + "  ", "espaces autour"),
])
def test_ce_qui_ne_peut_pas_etre_une_cle_arrete_le_build(valeur, ce_que_c_est):
    with pytest.raises(SystemExit) as echec:
        verifier_cle_google(valeur)
    # Le message doit nommer la longueur : c'est ce qui a manqué le jour où
    # l'erreur a été commise, où rien ne distinguait les deux chaînes à l'œil.
    assert str(len(valeur)) in str(echec.value)
