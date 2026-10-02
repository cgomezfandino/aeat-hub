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


def test_candidato_duplicado_por_skus_coincidentes(session):
    from aeat_hub.models import Linea
    from aeat_hub.dedupe import candidatos_duplicado

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    ticket = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 1),
        ejercicio=2026,
        emisor="IKEA",
        total=Decimal("190.75"),
        estado="confirmado",
    )
    # Factura emitida 25 días después (fuera de la ventana de 3 días)
    factura = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 26),
        ejercicio=2026,
        emisor="IKEA",
        total=Decimal("190.75"),
        estado="pendiente",
    )
    session.add_all([ticket, factura])
    session.flush()

    # Añadir mismas líneas / SKUs a ambos
    for a in (ticket, factura):
        a.lineas.append(Linea(posicion=1, codigo="SKU-1", descripcion="Articulo 1", importe=Decimal("100.00")))
        a.lineas.append(Linea(posicion=2, codigo="SKU-2", descripcion="Articulo 2", importe=Decimal("90.75")))
    session.commit()

    sugeridos = candidatos_duplicado(session, factura)
    assert len(sugeridos) == 1
    assert sugeridos[0]["id"] == ticket.id
    assert "artículos coincidentes" in sugeridos[0]["motivo"]


def test_find_duplicate_por_sku_en_ingesta(session):
    from aeat_hub.extract.schema import InvoiceLine
    from aeat_hub.models import Linea

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    asiento = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 1),
        ejercicio=2026,
        emisor="IKEA",
        total=Decimal("190.75"),
        estado="confirmado",
    )
    asiento.lineas.append(Linea(posicion=1, codigo="SKU-A", descripcion="Prod A", importe=Decimal("100.00")))
    asiento.lineas.append(Linea(posicion=2, codigo="SKU-B", descripcion="Prod B", importe=Decimal("90.75")))
    session.add(asiento)
    session.commit()

    extract = InvoiceExtract(
        emisor="IKEA Tienda",
        numero="DISTINTO-123",
        fecha=date(2026, 9, 28),
        total=Decimal("190.75"),
        lineas=[
            InvoiceLine(posicion=1, codigo="SKU-A", descripcion="Prod A", importe=Decimal("100.00")),
            InvoiceLine(posicion=2, codigo="SKU-B", descripcion="Prod B", importe=Decimal("90.75")),
        ],
    )
    hit = find_duplicate(session, actividad_id=actividad.id, extract=extract, phash=None)
    assert hit is not None
    assert hit.nivel == 3
    assert "artículos coincidentes" in hit.motivo
    assert hit.asiento_id == asiento.id


def test_candidato_duplicado_por_ventana_extendida_60_dias(session):
    from aeat_hub.dedupe import candidatos_duplicado

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    ticket = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 1),
        ejercicio=2026,
        nif_emisor="A28812618",
        emisor="IKEA",
        total=Decimal("50.00"),
        estado="confirmado",
    )
    # Factura formal emitida 20 días después con mismo NIF y total pero sin líneas
    factura = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 21),
        ejercicio=2026,
        nif_emisor="A28812618",
        emisor="IKEA",
        total=Decimal("50.00"),
        estado="pendiente",
    )
    session.add_all([ticket, factura])
    session.commit()

    cands = candidatos_duplicado(session, factura)
    assert len(cands) == 1
    assert cands[0]["id"] == ticket.id
    assert "ventana 60 días" in cands[0]["motivo"]


def test_score_par_splink_con_skus(session):
    from aeat_hub.linkage_facturas import score_par_splink
    from aeat_hub.models import Linea

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    ticket = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 9),
        ejercicio=2026,
        nif_emisor="A28812618",
        emisor="IKEA Ibérica S.A.",
        numero_factura="ESSIM-1",
        total=Decimal("190.75"),
        estado="confirmado",
    )
    factura = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 24),
        ejercicio=2026,
        nif_emisor="A28812618",
        emisor="IKEA Ibérica S.A.",
        numero_factura="ESCINV-1",
        total=Decimal("190.75"),
        estado="pendiente",
    )
    for a in (ticket, factura):
        a.lineas.append(Linea(posicion=1, codigo="SKU-1", descripcion="Articulo 1", importe=Decimal("100.00")))
        a.lineas.append(Linea(posicion=2, codigo="SKU-2", descripcion="Articulo 2", importe=Decimal("90.75")))
    session.add_all([ticket, factura])
    session.commit()

    res = score_par_splink(ticket, factura)
    assert res is not None
    prob, peso, desglose = res
    assert prob >= 0.99
    assert peso >= 10.0
    conceptos = dict(desglose)
    assert "skus ≥2 coincidentes" in conceptos
    assert conceptos["skus ≥2 coincidentes"] > 10.0



