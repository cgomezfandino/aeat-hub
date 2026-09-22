from decimal import Decimal

from aeat_hub.extract.parser import parse_invoice
from aeat_hub.fiscal.money import format_euro, parse_amount
from tests.samples import FACTURA_LUZ, FACTURA_PVC


def test_parse_amount_espanol():
    assert parse_amount("1.234,56 €") == Decimal("1234.56")
    assert parse_amount("40,00") == Decimal("40.00")
    assert format_euro(Decimal("1234.56")) == "1.234,56 €"
    assert format_euro(Decimal("-45.31")) == "-45,31 €"
    assert format_euro(None) == "—"


def test_parse_factura_luz():
    extract = parse_invoice(FACTURA_LUZ)
    assert extract.nif_emisor == "B12345674"
    assert extract.nif_emisor_valido
    assert extract.numero == "F2026-000123"
    assert extract.fecha.isoformat() == "2026-03-10"
    assert extract.base == Decimal("40.00")
    assert extract.iva_tipo == Decimal("21")
    assert extract.iva_cuota == Decimal("8.40")
    assert extract.total == Decimal("48.40")
    assert extract.confianza >= 0.8
    assert "IBERDROLA" in (extract.emisor or "").upper()
    assert all("total" not in (linea.descripcion or "").lower() for linea in extract.lineas)


def test_parse_factura_pvc_miles():
    extract = parse_invoice(FACTURA_PVC)
    assert extract.total == Decimal("1452.00")
    assert extract.base == Decimal("1200.00")


def test_parse_factura_leroy_estilo():
    foto = """
LEROY MERLIN ARROYO
FACTURA 064-0009-720394
ORIGINAL
B-84818442
Numero NIF 12345678Z
Fecha de venta 18/09/2026
Total SI (EUR)
11,45
Total IVA/IGIC/IPSI
2,41
Total TII (EUR)
13,86
"""
    extract = parse_invoice(foto)
    assert extract.nif_emisor == "B84818442"
    assert extract.numero == "064-0009-720394"
    assert extract.fecha.isoformat() == "2026-09-18"
    assert extract.total == Decimal("13.86")
    assert extract.base == Decimal("11.45")
    assert extract.iva_cuota == Decimal("2.41")
    assert "LEROY" in (extract.emisor or "").upper()

    scan = """
IFICATIVA 064-0009-R194007
LEROY MERLIN ARROYO
B-84818442
05/09/2026
Total SI (EUR)
Total 111 (EUR)
25,99
5,46
31,45
"""
    extract = parse_invoice(scan)
    assert extract.numero == "064-0009-R194007"
    assert extract.nif_emisor == "B84818442"
    assert extract.total == Decimal("31.45")
    assert extract.base == Decimal("25.99")
    assert extract.iva_cuota == Decimal("5.46")
    text = """
LEROY MERLIN DEMO
B-12345674
Cliente 12345678Z
Factura nº: 064-0009-R194007
Fecha: 05/09/2026
Total TII (EUR)
13,86
"""
    extract = parse_invoice(text)
    assert extract.nif_emisor == "B12345674"
    assert extract.nif_receptor == "12345678Z"
    assert extract.numero == "064-0009-R194007"
    assert extract.total == Decimal("13.86")
    assert "LEROY" in (extract.emisor or "").upper()


def test_parse_ticket_obrama_nfs_y_paginacion():
    texto = """
OBRAMAT
BRICOMAN S.L.U
NIF: B12345674
Ticket de caja
010-000043-004-4843-NFS: 055610 15/08/2026 13:48 - Venta -
Pag. 1 / 2
Adobe Scan 1 / 3
Total SI (EUR)
94,21
Total IVA
19,78
Total TTI (EUR)
113,99
"""
    extract = parse_invoice(texto)
    assert extract.numero == "010-000043-004-4843-NFS:055610"
    assert extract.numero_norm == "0100000430044843NFS055610"
    assert extract.pagina_ticket == 1
    assert extract.paginas_ticket == 2
    assert extract.fecha.isoformat() == "2026-08-15"
    assert extract.total == Decimal("113.99")
    assert extract.base == Decimal("94.21")


def test_si_hay_factura_y_nfs_se_guarda_el_numero_de_factura():
    texto = """
FACTURA 010-0009-220356
OBRAMAT
BRICOLAJE BRICOMAN,S.L.U
Ticket de caja
010-000011-004-1227-NFS: 061936 17/09/2026 14:03 - Venta -
Total TTI (EUR)
21,44
"""
    extract = parse_invoice(texto)
    assert extract.numero == "010-0009-220356"
    assert "BRICOMAN" in (extract.emisor or "").upper()
    assert extract.total == Decimal("21.44")


def test_ticket_obrama_asigna_el_importe_a_cada_articulo():
    texto = """
OBRAMAT
N°
1
BROCA MADERA PALA 20MM
10447983
UNID.
1,64
0,00
1,64
21.00
1,99
1,99
2
EXTRACTOR TORNILLOS M3-M18
10835440
UNID.
10,70
0,00
10,70
21.00
12,95
12,95
3
CONDENA ZAMAK SET WC 35MM
25034037
UNID.
5,37
0,00
5,37
21.00
6,50
6,50
Total SI (EUR)
17,72
Total IVA
3,72
Total TTI (EUR)
21,44
"""
    extract = parse_invoice(texto)
    assert [(item.descripcion, item.importe) for item in extract.lineas] == [
        ("BROCA MADERA PALA 20MM", Decimal("1.99")),
        ("EXTRACTOR TORNILLOS M3-M18", Decimal("12.95")),
        ("CONDENA ZAMAK SET WC 35MM", Decimal("6.50")),
    ]
    assert sum(item.importe for item in extract.lineas) == extract.total


def test_recupera_importes_tti_aunque_no_esten_junto_al_nombre():
    texto = """
OBRAMAT
Designacion y Referencia articulo
1
PROLONGADOR 3X1.5MM
10134110
2
ADAPTADOR 2T
25049368
Total TTI (EUR)
113,99
Importe
TTI (EUR)
6,30
1,90
4,80
1,40
1,53
1,25
8,15
11,90
Importe
TTI (EUR)
4,25
8,50
4,75
4,75
1,95
1,95
4,78
9,56
16,00
16,00
4,90
19,60
5,60
11,20
5,20
5,20
"""
    extract = parse_invoice(texto)
    importes = [item.importe for item in extract.lineas if item.importe is not None]
    assert sum(importes, Decimal("0")) == Decimal("113.99")
    assert Decimal("6.30") in importes
    assert Decimal("8.50") in importes
    assert Decimal("4.25") not in importes


def test_empareja_cada_articulo_con_su_importe_tti():
    texto = """
OBRAMAT
Designacion y Referencia articulo
PROLONGADOR 3X1.5MM 3M BCO
10134110
ADAPTADOR 2T 16A FRONTAL BCO
25049368
Contribucion al SCRAP
: 0,01
TAPA GARRA P/CAJA 100X100MM
10016265
TACO DE LIJA GRANO MEDIO
4. 10757292
Importe
TTI (EUR)
6,30
1,90
Importe
TTI (EUR)
0,60
4,80
0,70
1,40
Total TTI (EUR)
14,40
"""
    extract = parse_invoice(texto)
    assert [(item.codigo, item.descripcion, item.importe) for item in extract.lineas] == [
        ("10134110", "PROLONGADOR 3X1.5MM 3M BCO", Decimal("6.30")),
        ("25049368", "ADAPTADOR 2T 16A FRONTAL BCO", Decimal("1.90")),
        ("10016265", "TAPA GARRA P/CAJA 100X100MM", Decimal("4.80")),
        ("10757292", "TACO DE LIJA GRANO MEDIO", Decimal("1.40")),
    ]
    assert all(item.descripcion for item in extract.lineas)


def test_sello_adobe_no_es_pagina_de_ticket():
    texto = """
IBERDROLA CLIENTES DEMO S.A.
NIF: B12345674
Factura nº: F2026-000123
Fecha: 10/03/2026
1 / 3
Total factura: 48,40 €
"""
    extract = parse_invoice(texto)
    assert extract.numero == "F2026-000123"
    assert extract.pagina_ticket is None
    assert extract.paginas_ticket is None


def test_parse_lineas_de_ticket():
    texto = """
LEROY MERLIN ARROYO
B-84818442
Fecha de venta 18/09/2026
FACTURA 064-0009-720394
Tornillo DIN 4x40          2,50
Pintura plástica 4L        8,95
Total SI (EUR)
11,45
Total IVA
2,41
Total TII (EUR)
13,86
"""
    extract = parse_invoice(texto)
    descripciones = [linea.descripcion for linea in extract.lineas]
    importes = [linea.importe for linea in extract.lineas]
    assert "Tornillo DIN 4x40" in descripciones
    assert "Pintura plástica 4L" in descripciones
    assert Decimal("2.50") in [linea.base for linea in extract.lineas]
    assert Decimal("8.95") in [linea.base for linea in extract.lineas]
    assert Decimal("3.03") in importes
    assert Decimal("10.83") in importes
    assert extract.total == Decimal("13.86")
    assert extract.base == Decimal("11.45")


def test_codigo_con_punto_final_lleva_el_importe_de_la_linea():
    texto = """
OBRAMAT
FACTURA 010-0009-216464
Designacion y Referencia articulo
HIDROTUBO BARRA 40MM 1M
10110884.
UNID.
1,99
0,00
1,99
21.00
2,41
2,41
2
CODO 87° 40MM H-H PVC
10539431
UNID.
0,18
0,00
0,18
21.00
0,22
0,22
Modos de pago
Total SI (EUR)
2,17
Total IVA
0,46
Total TTI (EUR)
2,63
RAZON SOCIAL Calle Margarita
"""
    extract = parse_invoice(texto)
    assert [(linea.codigo, linea.descripcion, linea.importe) for linea in extract.lineas] == [
        ("10110884", "HIDROTUBO BARRA 40MM 1M", Decimal("2.41")),
        ("10539431", "CODO 87° 40MM H-H PVC", Decimal("0.22")),
    ]
    assert extract.lineas[0].base == Decimal("1.99")
    assert extract.lineas[1].base == Decimal("0.18")


def test_parse_lineas_nombres_sin_importe_en_la_misma_linea():
    texto = """
LEROY MERLIN ARROYO
B-84818442
Fecha de venta 05/09/2026
FACTURA 064-0009-R194007
Designacion y Referencia articulo
SIERRA DE CALAR PRACTYL 400W
TORNILLERIA A GRANEL
CONDENA CERRADURA PICAPORTE
Total SI (EUR)
25,99
Total IVA
5,46
Total TII (EUR)
31,45
"""
    extract = parse_invoice(texto)
    descripciones = [linea.descripcion for linea in extract.lineas]
    assert "SIERRA DE CALAR PRACTYL 400W" in descripciones
    assert "TORNILLERIA A GRANEL" in descripciones
    assert "CONDENA CERRADURA PICAPORTE" in descripciones
    assert extract.total == Decimal("31.45")


def test_parse_lineas_numeradas_con_ref_e_importe():
    texto = """
LEROY MERLIN ARROYO
B-12345674
Fecha de venta 05/09/2026
FACTURA 064-0009-R194007
CARLOS EDUARDO GOMEZ
Designacion y Referencia articulo
1
SIERRA DE CALAR PRACTYL 400W
11223344
2
TORNILLERIA A GRANEL
13597836
Importe
TI (EUR)
10,83
2,62
Total SI (EUR)
11,12
Total IVA
2,33
Total TII (EUR)
13,45
"""
    extract = parse_invoice(texto)
    assert [(item.posicion, item.codigo, item.descripcion, item.importe) for item in extract.lineas] == [
        (1, "11223344", "SIERRA DE CALAR PRACTYL 400W", Decimal("10.83")),
        (2, "13597836", "TORNILLERIA A GRANEL", Decimal("2.62")),
    ]
    assert [item.base for item in extract.lineas] == [Decimal("8.95"), Decimal("2.17")]
    assert [item.iva_cuota for item in extract.lineas] == [Decimal("1.88"), Decimal("0.45")]
    assert extract.lineas[0].iva_tipo == Decimal("21.00")
    assert all(item.descripcion != "CARLOS EDUARDO GOMEZ" for item in extract.lineas)
    assert extract.total == Decimal("13.45")


def test_parse_lineas_columnas_ocr_con_ids():
    texto = """
Importe
TI (EUR)
5,14
1,46
4,11
3,15
Total TII (EUR)
13,86
Total SI (EUR)
11,45
LEROY MERLIN ARROYO
B-12345674
Designacion y Referencia articulo
MARCO DOBLE NILOE BLANCO
TIJERA ELECTRICISTA DEXTER
C/ME FALTA UN TORNILLO, S/N
17921323
15841434
85207734
83684269
"""
    extract = parse_invoice(texto)
    assert extract.total == Decimal("13.86")
    assert [item.codigo for item in extract.lineas] == [
        "17921323",
        "15841434",
        "85207734",
        "83684269",
    ]
    assert [item.importe for item in extract.lineas] == [
        Decimal("5.14"),
        Decimal("1.46"),
        Decimal("4.11"),
        Decimal("3.15"),
    ]
    assert extract.lineas[0].descripcion == "MARCO DOBLE NILOE BLANCO"
    assert extract.lineas[1].descripcion == "TIJERA ELECTRICISTA DEXTER"
    assert extract.lineas[2].descripcion in {None, ""}
    assert extract.lineas[3].descripcion in {None, ""}
    assert [item.base for item in extract.lineas] == [
        Decimal("4.25"),
        Decimal("1.21"),
        Decimal("3.40"),
        Decimal("2.59"),
    ]
    assert extract.lineas[0].iva_cuota == Decimal("0.89")
    assert extract.lineas[0].iva_tipo == Decimal("21.00")


def test_emisor_sale_de_la_cabecera_y_no_guarda_la_direccion():
    text = """
OBRAMAT
BRICOLAJE BRICOMAN,S.L.U
C/ NIQUEL 2,4
SR CARLOS EDUARDO GOMEZ FANDINO
MAYORAZGO DE CUARTE 25 5-A
Ticket 010-000011-004-1227-NFS:061936
Fecha: 17/09/2026
Total 21,44 €
Salas,
C.I.F. B84406289
"""
    extract = parse_invoice(text)
    assert "BRICOMAN" in (extract.emisor or "").upper()
    assert all("mayorazgo" not in (linea.descripcion or "").lower() for linea in extract.lineas)
    assert all("salas" not in (linea.descripcion or "").lower() for linea in extract.lineas)
