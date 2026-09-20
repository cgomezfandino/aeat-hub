from aeat_hub.fiscal.nif import find_nifs, is_valid_nif, normalize_nif


def test_dni_nie_cif_validos():
    assert is_valid_nif("12345678Z")
    assert is_valid_nif("X1234567L")
    assert is_valid_nif("B12345674")
    assert is_valid_nif("H12345674")


def test_nif_invalido_y_normalizacion():
    assert not is_valid_nif("B12345670")
    assert not is_valid_nif("12345678A")
    assert normalize_nif("b-1234567-4") == "B12345674"


def test_find_nifs_en_texto():
    text = "Emisor B12345674 Cliente 12345678Z basura 1234"
    assert find_nifs(text) == ["B12345674", "12345678Z"]
