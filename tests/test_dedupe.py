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


def test_dedupe_emisor_usa_la_normalizacion_unica(session):
    """Un emisor de 61 caracteres que difiere al final ya no cruza por truncado."""
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    largo = "E" * 70
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            fecha=date(2026, 9, 18),
            ejercicio=2026,
            emisor=largo,
            total=Decimal("13.86"),
            estado="confirmado",
        )
    )
    session.flush()
    extract = InvoiceExtract(
        emisor=f"{largo}  ",
        fecha=date(2026, 9, 19),
        total=Decimal("13.86"),
    )
    hit = find_duplicate(session, actividad_id=actividad.id, extract=extract, phash=None)
    assert hit is not None
    assert hit.nivel == 3
    assert "emisor" in hit.motivo

    casi = "E" * 60
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            fecha=date(2026, 9, 20),
            ejercicio=2026,
            emisor=f"{casi}X",
            total=Decimal("99.00"),
            estado="confirmado",
        )
    )
    session.flush()
    distinto = InvoiceExtract(
        emisor=f"{casi}Y",
        fecha=date(2026, 9, 21),
        total=Decimal("99.00"),
    )
    assert find_duplicate(session, actividad_id=actividad.id, extract=distinto, phash=None) is None


def test_candidatos_duplicado_sugiere_el_gemelo_evidente(session):
    from aeat_hub.dedupe import candidatos_duplicado

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    bueno = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 9),
        ejercicio=2026,
        emisor="IKEA IBÉRICA S.A.",
        nif_emisor="A28812618",
        numero_factura="ESCINV-1",
        total=Decimal("190.75"),
        estado="confirmado",
    )
    gemelo = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 9),
        ejercicio=2026,
        emisor="IKEA Ibérica S.A.",
        numero_factura="ESSIM-1",
        total=Decimal("190.75"),
        estado="pendiente",
    )
    session.add_all([bueno, gemelo])
    session.commit()

    sugeridos = candidatos_duplicado(session, gemelo)
    assert len(sugeridos) == 1
    assert sugeridos[0]["id"] == bueno.id
    assert "emisor" in sugeridos[0]["motivo"]

    # comprado con total distinto no es gemelo
    otro = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 10),
        ejercicio=2026,
        emisor="IKEA IBÉRICA S.A.",
        nif_emisor="A28812618",
        total=Decimal("55.00"),
        estado="confirmado",
    )
    session.add(otro)
    session.commit()
    assert candidatos_duplicado(session, otro) == []
