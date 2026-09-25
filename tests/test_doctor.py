"""Doctor del libro: integridad referencial y cuadres."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from aeat_hub.doctor import revisar
from aeat_hub.fiscal.cuadres import avisos_cuadre, cuadra_total, iva_tipo_conocido
from aeat_hub.models import Actividad, Asiento, Documento, Relacion


def _asiento(session, actividad, **kwargs):
    row = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 9),
        ejercicio=2026,
        emisor="TIENDA DEMO S.L.",
        nif_emisor="B12345674",
        estado="pendiente",
        **kwargs,
    )
    session.add(row)
    session.commit()
    return row


def test_cuadres_utilitarios():
    assert cuadra_total(Decimal("10.00"), Decimal("2.10"), Decimal("12.10")) is True
    assert cuadra_total(Decimal("10.00"), Decimal("2.10"), Decimal("12.50")) is False
    assert cuadra_total(None, Decimal("2.10"), Decimal("12.10")) is None
    assert iva_tipo_conocido(Decimal("21")) and iva_tipo_conocido(None)
    assert not iva_tipo_conocido(Decimal("16.38"))
    avisos = avisos_cuadre(
        base=Decimal("10.00"), iva_cuota=Decimal("2.10"),
        iva_tipo=Decimal("16.38"), total=Decimal("13.00"),
    )
    assert len(avisos) == 2
    assert "no cuadra" in avisos[0]
    assert "no es un tipo español" in avisos[1]


def test_doctor_libro_sano(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    hallazgos = revisar(session, layout, actividad)
    categorias = {h.categoria for h in hallazgos}
    assert "relación huérfana" not in categorias
    assert "fichero perdido" not in categorias


def test_doctor_caza_relacion_huerfana(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    session.add(
        Relacion(
            origen_tipo="documento",
            origen_id=99999,
            destino_tipo="factura",
            destino_id=88888,
            tipo="evidencia",
        )
    )
    session.commit()
    hallazgos = revisar(session, layout, actividad)
    huerfanas = [h for h in hallazgos if h.categoria == "relación huérfana"]
    assert len(huerfanas) == 1
    assert huerfanas[0].severidad == "error"
    assert "99999" in huerfanas[0].detalle


def test_doctor_caza_fichero_perdido_y_descuadre(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    doc = Documento(
        sha256="f" * 64,
        nombre_original="perdido.pdf",
        ruta_almacenada=str(layout.archivo / "no-existe.pdf"),
        texto_crudo="",
    )
    session.add(doc)
    session.flush()
    _asiento(
        session,
        actividad,
        documento_id=doc.id,
        base=Decimal("10.00"),
        iva_cuota=Decimal("2.10"),
        iva_tipo=Decimal("21"),
        total=Decimal("13.00"),  # no cuadra
    )
    session.commit()
    hallazgos = revisar(session, layout, actividad)
    categorias = [h.categoria for h in hallazgos]
    assert "fichero perdido" in categorias
    assert "cuadre" in categorias
    cuadre = next(h for h in hallazgos if h.categoria == "cuadre")
    assert "no cuadra" in cuadre.detalle
