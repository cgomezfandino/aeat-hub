from datetime import date
from decimal import Decimal

from sqlalchemy import select

from aeat_hub.dedupe import find_duplicate, fiscal_key
from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.models import Actividad, Asiento


def test_fiscal_key_normaliza():
    key = fiscal_key("b-1234567-4", "F-2026/001", date(2026, 3, 10), Decimal("48.40"))
    assert key == "B12345674|F2026001|2026-03-10|4840"


def test_duplicado_fiscal_nivel_2(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            fecha=date(2026, 3, 10),
            ejercicio=2026,
            nif_emisor="B12345674",
            numero_factura="F2026-000123",
            total=Decimal("48.40"),
            estado="confirmado",
        )
    )
    session.flush()
    extract = InvoiceExtract(
        nif_emisor="B12345674",
        numero="F2026-000123",
        fecha=date(2026, 3, 10),
        total=Decimal("48.40"),
    )
    hit = find_duplicate(session, actividad_id=actividad.id, extract=extract, phash=None)
    assert hit is not None
    assert hit.nivel == 2


def test_duplicado_sospechoso_nivel_3(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            fecha=date(2026, 3, 10),
            ejercicio=2026,
            nif_emisor="B12345674",
            numero_factura="OTRA",
            total=Decimal("48.40"),
            estado="confirmado",
        )
    )
    session.flush()
    extract = InvoiceExtract(
        nif_emisor="B12345674",
        numero="NUEVA-9",
        fecha=date(2026, 3, 12),
        total=Decimal("48.40"),
    )
    hit = find_duplicate(session, actividad_id=actividad.id, extract=extract, phash=None)
    assert hit is not None
    assert hit.nivel == 3


def test_duplicado_por_numero_fecha_total_sin_nif(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            fecha=date(2026, 9, 5),
            ejercicio=2026,
            emisor="LEROY MERLIN ARROYO",
            numero_factura="064-0009-R194007",
            total=Decimal("31.45"),
            estado="confirmado",
            validado=True,
        )
    )
    session.flush()
    extract = InvoiceExtract(
        emisor="LEROY MERLIN ARROYO",
        numero="064-0009-R194007",
        fecha=date(2026, 9, 5),
        total=Decimal("31.45"),
    )
    hit = find_duplicate(session, actividad_id=actividad.id, extract=extract, phash=None)
    assert hit is not None
    assert hit.nivel == 2
    assert "número" in hit.motivo


def test_duplicado_por_emisor_importe_ventana(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            fecha=date(2026, 9, 18),
            ejercicio=2026,
            emisor="LEROY MERLIN ARROYO",
            numero_factura="A",
            total=Decimal("13.86"),
            estado="confirmado",
        )
    )
    session.flush()
    extract = InvoiceExtract(
        emisor="Leroy Merlin Arroyo",
        numero="B-OTRA",
        fecha=date(2026, 9, 19),
        total=Decimal("13.86"),
    )
    hit = find_duplicate(session, actividad_id=actividad.id, extract=extract, phash=None)
    assert hit is not None
    assert hit.nivel == 3
