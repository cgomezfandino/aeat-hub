from decimal import Decimal

from sqlalchemy import select

from aeat_hub.classify import classify, reclassify
from aeat_hub.extract.parser import parse_invoice
from aeat_hub.models import Actividad, Asiento, Cuenta, ReglaAprendida
from tests.samples import FACTURA_LUZ, FACTURA_PVC


def test_clasifica_luz_por_proveedor(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    extract = parse_invoice(FACTURA_LUZ)
    result = classify(session, actividad, extract, FACTURA_LUZ)
    assert result.cuenta_codigo == "CI.GAS.LUZ"
    assert result.confianza >= Decimal("0.8")


def test_clasifica_pvc_como_mejora_no_gasto(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    extract = parse_invoice(FACTURA_PVC)
    result = classify(session, actividad, extract, FACTURA_PVC)
    assert result.cuenta_codigo == "CI.MEJ.PVC"
    assert result.tipo == "mejora"


def test_mano_de_obra_sin_contexto_queda_pendiente(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    text = "Factura nº: 1 Fecha: 01/01/2026 NIF: B12345674 Mano de obra varias 100,00 Total: 100,00"
    extract = parse_invoice(text)
    result = classify(session, actividad, extract, text)
    assert result.cuenta_codigo is None
    assert result.origen == "pendiente"


def test_reclasificar_aprende_por_nif(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    extract = parse_invoice(FACTURA_LUZ)
    asiento = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=extract.fecha,
        ejercicio=2026,
        emisor=extract.emisor,
        nif_emisor=extract.nif_emisor,
        numero_factura=extract.numero,
        total=extract.total,
        estado="pendiente",
    )
    session.add(asiento)
    session.flush()
    cuenta = session.get(Cuenta, "CI.GAS.HOGAR")
    n = reclassify(session, asiento, cuenta)
    assert n == 1
    assert asiento.cuenta_codigo == "CI.GAS.HOGAR"
    assert asiento.estado == "confirmado"
    rule = session.scalar(select(ReglaAprendida))
    assert rule.nif_emisor == "B12345674"
    assert rule.cuenta_codigo == "CI.GAS.HOGAR"

    learned = classify(session, actividad, extract, FACTURA_LUZ)
    assert learned.cuenta_codigo == "CI.GAS.HOGAR"
    assert learned.origen == "aprendida"
