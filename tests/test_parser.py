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
