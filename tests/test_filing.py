from datetime import date
from pathlib import Path

from sqlalchemy import select

from aeat_hub.classify import reclassify
from aeat_hub.filing import archivo_path, ordenar_asientos, rubro_slug
from aeat_hub.ingest import ingest_file
from aeat_hub.models import Actividad, Asiento, Cuenta, Documento
from tests.samples import FACTURA_LUZ, FACTURA_PVC, write_pdf
from tests.test_ingest import FakeRapid


def test_rubro_slug_luz_y_mano_de_obra():
    assert rubro_slug("CI.GAS.LUZ") == "luz"
    assert rubro_slug("CI.MEJ.MO") == "mano-de-obra"
    assert rubro_slug(None) == "sin-cuenta"


def test_archivo_path_anio_mes_tipo_rubro(layout):
    dest = archivo_path(
        layout,
        actividad_codigo="CI-VA-001",
        fecha=date(2026, 3, 10),
        tipo="gasto",
        cuenta_codigo="CI.GAS.LUZ",
        estado="confirmado",
        sha256="abcdef1234567890",
        nombre_original="luz.pdf",
    )
    assert dest == layout.archivo / "CI-VA-001" / "2026" / "03" / "gasto" / "luz" / "abcdef123456_luz.pdf"


def test_archivo_path_sin_fecha_y_sin_cuenta(layout):
    dest = archivo_path(
        layout,
        actividad_codigo="CI-VA-001",
        fecha=None,
        tipo="gasto",
        cuenta_codigo=None,
        estado="pendiente",
        sha256="aa" * 32,
        nombre_original="ticket.jpg",
    )
    assert dest == layout.archivo / "CI-VA-001" / "sin_fecha" / "00" / "pendiente" / "sin-cuenta" / f"{'aa'*6}_ticket.jpg"


def test_ingest_ordena_factura_luz_en_finder(session, layout):
    pdf = write_pdf(layout.inbox / "luz.pdf", FACTURA_LUZ)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    item = ingest_file(session, layout, pdf, actividad, rapid=FakeRapid())
    session.commit()
    asiento = session.get(Asiento, item.asiento_id)
    doc = session.get(Documento, asiento.documento_id)
    stored = Path(doc.ruta_almacenada)
    assert stored.is_file()
    assert stored.parts[-5:] == ("2026", "03", "gasto", "luz", stored.name)
    assert not pdf.exists()
    assert item.path == stored


def test_ingest_mejora_pvc_no_va_a_gasto(session, layout):
    pdf = write_pdf(layout.inbox / "ventanas.pdf", FACTURA_PVC)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    item = ingest_file(session, layout, pdf, actividad, rapid=FakeRapid())
    session.commit()
    doc = session.get(Documento, session.get(Asiento, item.asiento_id).documento_id)
    stored = Path(doc.ruta_almacenada)
    assert stored.parts[-4:-1] == ("02", "mejora", "pvc")


def test_reclasificar_mueve_el_fichero(session, layout):
    pdf = write_pdf(layout.inbox / "luz.pdf", FACTURA_LUZ)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    item = ingest_file(session, layout, pdf, actividad, rapid=FakeRapid())
    session.commit()
    asiento = session.get(Asiento, item.asiento_id)
    old = Path(asiento.documento.ruta_almacenada)
    assert old.parent.name == "luz"
    hogar = session.get(Cuenta, "CI.GAS.HOGAR")
    reclassify(session, asiento, hogar, layout=layout)
    session.commit()
    new = Path(asiento.documento.ruta_almacenada)
    assert new.is_file()
    assert new.parent.name == "hogar"
    assert not old.exists()


def test_ordenar_reubica_lo_que_quedo_en_processed(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    stale = layout.processed / "old_luz.pdf"
    write_pdf(stale, FACTURA_LUZ)
    doc = Documento(
        sha256="bb" * 32,
        nombre_original="old_luz.pdf",
        ruta_almacenada=str(stale),
        texto_crudo=FACTURA_LUZ,
    )
    session.add(doc)
    session.flush()
    session.add(
        Asiento(
            actividad_id=actividad.id,
            documento_id=doc.id,
            tipo="gasto",
            cuenta_codigo="CI.GAS.LUZ",
            fecha=date(2026, 3, 10),
            ejercicio=2026,
            estado="confirmado",
        )
    )
    session.commit()
    moved = ordenar_asientos(session, layout, actividad)
    session.commit()
    assert moved == 1
    assert not stale.exists()
    assert "gasto/luz" in Path(doc.ruta_almacenada).as_posix()
