from aeat_hub.fiscal.nif import find_nifs, is_valid_nif, normalize_nif, pick_emisor_receptor


def test_dni_nie_cif_validos():
    assert is_valid_nif("12345678Z")
    assert is_valid_nif("X1234567L")
    assert is_valid_nif("B12345674")
    assert is_valid_nif("H12345674")


def test_nif_invalido_y_normalizacion():
    assert not is_valid_nif("B12345670")
    assert not is_valid_nif("12345678A")
    assert normalize_nif("b-1234567-4") == "B12345674"
    assert normalize_nif("ES A-28812618") == "A28812618"
    assert is_valid_nif("ES A-28812618")


def test_find_nifs_en_texto():
    text = "Emisor B12345674 Cliente 12345678Z basura 1234"
    assert find_nifs(text) == ["B12345674", "12345678Z"]


def test_cif_con_guion():
    assert find_nifs("CIF B-12345674 destinatario 12345678Z") == ["B12345674", "12345678Z"]


def test_pick_excluye_titular_si_es_unico_candidato():
    assert pick_emisor_receptor(["12345678Z"], excluir="12345678Z") == (None, None)
    assert pick_emisor_receptor(["12345678Z"], excluir=" 12345678z ") == (None, None)


def test_pick_no_toca_varios_candidatos_aunque_este_el_titular():
    # Sin dirección conocida (emitida vs recibida), con varios NIF se mantiene el criterio actual.
    assert pick_emisor_receptor(["B12345674", "12345678Z"], excluir="12345678Z") == (
        "B12345674",
        "12345678Z",
    )
