"""Limpieza y similitud de nombres de emisor; unificación por NIF."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from aeat_hub.emisores import nombre_canonico_para, unificar_emisores
from aeat_hub.extract.nombres import (
    limpiar_nombre,
    nombre_canonico,
    similitud_nombre,
)
from aeat_hub.models import Actividad, Asiento, Cambio, Factura


def test_limpiar_nombre_quita_formas_societarias():
    assert limpiar_nombre("IKEA IBÉRICA S.A., A28812618,") == "IKEA IBÉRICA"
    assert limpiar_nombre("BRICOLAJE BRICOMAN,S.L.U.") == "BRICOLAJE BRICOMAN"
    assert limpiar_nombre("CARPINTERIA VALLADOLID S.L.") == "CARPINTERIA VALLADOLID"
    assert (
        limpiar_nombre("MUEBLES DEL SUR SOCIEDAD LIMITADA UNIPERSONAL") == "MUEBLES DEL SUR"
    )
    assert limpiar_nombre("ACME GmbH") == "ACME"  # base internacional
    assert limpiar_nombre("LEROY MERLIN ARROYO") == "LEROY MERLIN ARROYO"
    assert limpiar_nombre(None) == ""


def test_similitud_nombre_tolerante_con_variantes():
    assert similitud_nombre("IKEA Ibérica S.A.", "IKEA IBÉRICA S.A., A28812618,") >= 0.99
    assert similitud_nombre("IBERDROLA CLIENTES", "IBERDROLA CLIENTES, S.A.") >= 0.99
    assert similitud_nombre("IKEA Ibérica S.A.", "LEROY MERLIN ARROYO") < 0.5
    assert similitud_nombre("IKEA Ibérica S.A.", "") == 0.0


def test_nombre_canonico_prefiere_la_mas_frecuente():
    variantes = [
        "IKEA IBÉRICA S.A., A28812618,",
        "IKEA Ibérica S.A.",
        "IKEA Ibérica S.A.",
    ]
    assert nombre_canonico(variantes) == "IKEA Ibérica S.A."
    assert nombre_canonico([]) is None


def _asiento(session, actividad, **kwargs):
    row = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 9, 9),
        ejercicio=2026,
        base=Decimal("10.00"),
        iva_cuota=Decimal("2.10"),
        total=Decimal("12.10"),
        estado="pendiente",
        **kwargs,
    )
    session.add(row)
    session.commit()
    return row


def test_unificar_emisores_dry_run_y_aplicar(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    a1 = _asiento(session, actividad, emisor="IKEA IBÉRICA S.A., A28812618,", nif_emisor="A28812618")
    a2 = _asiento(session, actividad, emisor="IKEA Ibérica S.A.", nif_emisor="A28812618")
    a3 = _asiento(session, actividad, emisor="LEROY MERLIN ARROYO", nif_emisor="B84818442")

    propuestas = unificar_emisores(session, actividad.id)
    assert len(propuestas) == 1
    p = propuestas[0]
    assert p.antes == "IKEA IBÉRICA S.A., A28812618,"
    assert p.canonico == "IKEA Ibérica S.A."
    assert p.similitud >= 0.99
    assert p.aplica is True
    assert p.asientos == [a1.id]
    # dry-run: no toca nada
    session.expire_all()
    assert session.get(Asiento, a1.id).emisor == "IKEA IBÉRICA S.A., A28812618,"

    unificar_emisores(session, actividad.id, aplicar=True)
    session.expire_all()
    assert session.get(Asiento, a1.id).emisor == "IKEA Ibérica S.A."
    assert session.get(Asiento, a2.id).emisor == "IKEA Ibérica S.A."
    assert session.get(Asiento, a3.id).emisor == "LEROY MERLIN ARROYO"
    logs = session.scalars(select(Cambio).where(Cambio.asiento_id == a1.id)).all()
    assert any(
        log.campo == "emisor"
        and log.despues == "IKEA Ibérica S.A."
        and log.fuente == "modelo"
        for log in logs
    )

    # idempotente
    assert unificar_emisores(session, actividad.id) == []


def test_unificar_emisores_respeta_el_umbral(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    _asiento(session, actividad, emisor="IKEA IBÉRICA S.A.", nif_emisor="A28812618")
    _asiento(session, actividad, emisor="TALLERES ISMAR SL", nif_emisor="A28812618")

    propuestas = unificar_emisores(session, actividad.id, aplicar=True)
    assert len(propuestas) == 1
    assert propuestas[0].aplica is False
    rows = session.scalars(
        select(Asiento).where(Asiento.nif_emisor == "A28812618")
    ).all()
    assert sorted(row.emisor for row in rows) == [
        "IKEA IBÉRICA S.A.",
        "TALLERES ISMAR SL",
    ]


def test_unificar_emisores_sincroniza_factura(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    factura = Factura(
        actividad_id=actividad.id,
        nif_emisor="A28812618",
        emisor="IKEA IBÉRICA S.A., A28812618,",
        emisor_norm="IKEA IBÉRICA S.A., A28812618,",
        numero_norm="X1",
        numero_visible="X-1",
        total=Decimal("12.10"),
    )
    session.add(factura)
    session.flush()
    _asiento(
        session, actividad, emisor="IKEA Ibérica S.A.", nif_emisor="A28812618", factura_id=factura.id
    )
    _asiento(
        session, actividad, emisor="IKEA IBÉRICA S.A., A28812618,", nif_emisor="A28812618"
    )
    unificar_emisores(session, actividad.id, aplicar=True)
    session.expire_all()
    assert factura.emisor == "IKEA Ibérica S.A."
    assert factura.emisor_norm == "IKEA IBÉRICA S.A."


def test_nombre_canonico_para_el_ingest(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    _asiento(session, actividad, emisor="IKEA IBÉRICA S.A.", nif_emisor="A28812618")
    _asiento(session, actividad, emisor="IKEA Ibérica S.A.", nif_emisor="A28812618")

    canonico = nombre_canonico_para(
        session, actividad.id, "A28812618", "IKEA IBÉRICA S.A., A28812618,"
    )
    assert canonico == "IKEA Ibérica S.A."
    # otro emisor con el mismo NIF no arrastra el canónico
    assert nombre_canonico_para(session, actividad.id, "A28812618", "TALLERES ISMAR SL") is None
    assert nombre_canonico_para(session, actividad.id, "", "IKEA S.A.") is None


def test_score_fellegi_sunter_por_nif_y_nombre():
    """NIF igual domina; el nombre es el double-check que baja a revisar."""
    from aeat_hub.extract.nombres import probabilidad_mismo_emisor

    # NIF igual + nombre coincide (y errata de OCR) → auto
    auto = probabilidad_mismo_emisor(
        "A28812618", "A28812618", "IKEA Ibérica S.A.", "IKEA IBÉRICA S.A., A28812618,"
    )
    assert auto.probabilidad >= 0.99
    assert auto.banda == "auto"
    errata = probabilidad_mismo_emisor(
        "B84818442", "B84818442", "LEROY MERLIN ARROYO", "LEROY MERLIN ARROYC"
    )
    assert errata.probabilidad >= 0.99
    assert errata.banda == "auto"

    # NIF igual + nombre que no casa (texto legal) → revisar, no auto
    revisar = probabilidad_mismo_emisor(
        "A28812618",
        "A28812618",
        "IKEA Ibérica S.A.",
        "Información básica sobre protección de datos: Responsable: IKEA",
    )
    assert 0.50 <= revisar.probabilidad < 0.90
    assert revisar.banda == "revisar"

    # sin NIF, el nombre solo no basta para auto
    sin_nif = probabilidad_mismo_emisor(
        None, "A28812618", "IKEA Ibérica S.A.", "IKEA Ibérica S.A."
    )
    assert sin_nif.banda == "revisar"

    # NIF distinto → rechazar aunque el nombre coincida
    distinto = probabilidad_mismo_emisor(
        "B12345674", "B84818442", "IKEA Ibérica S.A.", "IKEA Ibérica S.A."
    )
    assert distinto.probabilidad < 0.01
    assert distinto.banda == "rechazar"

    # el desglose suma el intercepto, el NIF y el tramo del nombre
    assert len(auto.desglose) == 3
    assert auto.desglose[1] == ("NIF igual", 18.0)


def test_score_splink_mismas_bandas_que_el_modelo_a_mano():
    """El scorer Splink reproduce las bandas del modelo a mano (fallback)."""
    from aeat_hub.linkage import score_emisor

    auto = score_emisor(
        "A28812618", "A28812618", "IKEA Ibérica S.A.", "IKEA IBÉRICA S.A., A28812618,"
    )
    assert auto.probabilidad >= 0.99
    assert auto.banda == "auto"
    concepto_nif = [c for c, _b in auto.desglose if c.startswith("nif")]
    assert concepto_nif == ["nif igual"]

    errata = score_emisor(
        "B84818442", "B84818442", "LEROY MERLIN ARROYO", "LEROY MERLIN ARROYC"
    )
    assert errata.banda == "auto"

    revisar = score_emisor(
        "A28812618",
        "A28812618",
        "IKEA Ibérica S.A.",
        "Información básica sobre protección de datos: Responsable: IKEA",
    )
    assert 0.50 <= revisar.probabilidad < 0.90
    assert revisar.banda == "revisar"

    sin_nif = score_emisor(None, "A28812618", "IKEA Ibérica S.A.", "IKEA Ibérica S.A.")
    assert sin_nif.banda == "revisar"
    assert ("nif ausente", 0.0) in sin_nif.desglose

    distinto = score_emisor(
        "B12345674", "B84818442", "IKEA Ibérica S.A.", "IKEA Ibérica S.A."
    )
    assert distinto.probabilidad < 0.01
    assert distinto.banda == "rechazar"


def test_score_splink_cae_al_modelo_a_mano_si_falla(monkeypatch):
    import aeat_hub.linkage as linkage

    def _explota():
        raise RuntimeError("duckdb no disponible")

    monkeypatch.setattr(linkage, "_linker", _explota)
    score = linkage.score_emisor(
        "A28812618", "A28812618", "IKEA Ibérica S.A.", "IKEA IBÉRICA S.A., A28812618,"
    )
    assert score.probabilidad >= 0.99
    assert score.banda == "auto"


def test_reparse_no_pisa_el_nombre_canonico(session, layout):
    """El reparse relee el OCR, pero el canónico del NIF gana (regresión IKEA)."""
    from datetime import date as _date
    from decimal import Decimal as _D

    from aeat_hub.ingest import reparse_asientos
    from aeat_hub.models import Documento

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    texto_variante = (
        "IKEA IBÉRICA S.A., A28812618,\n"
        "NIF: A28812618\n"
        "Factura: BORD_030_2026 / 0003196\n"
        "Fecha: 09/09/2026\n"
        "Base imponible: 10,00 €\n"
        "IVA 21%: 2,10 €\n"
        "Total factura: 12,10 €\n"
    )
    doc = Documento(
        sha256="e" * 64,
        nombre_original="ikea.pdf",
        ruta_almacenada="/tmp/ikea.pdf",
        texto_crudo=texto_variante,
    )
    session.add(doc)
    session.flush()
    buenos = _asiento(session, actividad, emisor="IKEA Ibérica S.A.", nif_emisor="A28812618")
    variante = _asiento(
        session, actividad, emisor="IKEA Ibérica S.A.", nif_emisor="A28812618", documento_id=doc.id
    )
    session.commit()

    n = reparse_asientos(session, actividad)
    session.commit()
    session.expire_all()
    assert n >= 1
    fresh = session.get(Asiento, variante.id)
    assert fresh.emisor == "IKEA Ibérica S.A.", fresh.emisor
