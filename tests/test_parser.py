from decimal import Decimal

from aeat_hub.extract.parser import parse_invoice
from aeat_hub.fiscal.money import parse_amount
from tests.samples import FACTURA_LUZ, FACTURA_PVC


def test_parse_amount_espanol():
    assert parse_amount("1.234,56 €") == Decimal("1234.56")
    assert parse_amount("40,00") == Decimal("40.00")


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
