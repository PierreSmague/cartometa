from cartometa.build.assets import HASH_LENGTH, content_hash, hashed_name, write_hashed


def test_l_empreinte_fait_huit_caracteres_hexadecimaux():
    empreinte = content_hash(b"peu importe")

    assert len(empreinte) == HASH_LENGTH == 8
    assert all(c in "0123456789abcdef" for c in empreinte)


def test_le_meme_contenu_donne_la_meme_empreinte():
    assert content_hash(b"identique") == content_hash(b"identique")


def test_un_contenu_different_donne_une_empreinte_differente():
    assert content_hash(b"un") != content_hash(b"deux")


def test_le_nom_insere_l_empreinte_entre_la_base_et_l_extension():
    nom = hashed_name("index", ".json", b"contenu")

    assert nom.startswith("index.")
    assert nom.endswith(".json")
    assert nom == f"index.{content_hash(b'contenu')}.json"


def test_write_hashed_ecrit_le_fichier_et_renvoie_son_nom(tmp_path):
    nom = write_hashed(tmp_path / "data", "index", ".json", b'{"a":1}')

    assert (tmp_path / "data" / nom).read_bytes() == b'{"a":1}'
    assert "/" not in nom


def test_deux_ecritures_du_meme_contenu_donnent_le_meme_nom(tmp_path):
    premier = write_hashed(tmp_path, "c", ".json", b"pareil")
    second = write_hashed(tmp_path, "c", ".json", b"pareil")

    assert premier == second


def test_modifier_le_contenu_change_le_nom(tmp_path):
    premier = write_hashed(tmp_path, "c", ".json", b"avant")
    second = write_hashed(tmp_path, "c", ".json", b"apres")

    assert premier != second
