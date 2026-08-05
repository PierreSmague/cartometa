from cartometa.build.assets import HASH_LENGTH, content_hash, hashed_name, write_hashed


def test_the_fingerprint_is_eight_hex_characters():
    empreinte = content_hash(b"peu importe")

    assert len(empreinte) == HASH_LENGTH == 8
    assert all(c in "0123456789abcdef" for c in empreinte)


def test_the_same_content_gives_the_same_fingerprint():
    assert content_hash(b"identique") == content_hash(b"identique")


def test_different_content_gives_a_different_fingerprint():
    assert content_hash(b"un") != content_hash(b"deux")


def test_the_name_inserts_the_fingerprint_between_stem_and_extension():
    nom = hashed_name("index", ".json", b"contenu")

    assert nom.startswith("index.")
    assert nom.endswith(".json")
    assert nom == f"index.{content_hash(b'contenu')}.json"


def test_write_hashed_writes_the_file_and_returns_its_name(tmp_path):
    nom = write_hashed(tmp_path / "data", "index", ".json", b'{"a":1}')

    assert (tmp_path / "data" / nom).read_bytes() == b'{"a":1}'
    assert "/" not in nom


def test_two_writes_of_the_same_content_give_the_same_name(tmp_path):
    premier = write_hashed(tmp_path, "c", ".json", b"pareil")
    second = write_hashed(tmp_path, "c", ".json", b"pareil")

    assert premier == second


def test_changing_the_content_changes_the_name(tmp_path):
    premier = write_hashed(tmp_path, "c", ".json", b"avant")
    second = write_hashed(tmp_path, "c", ".json", b"apres")

    assert premier != second
