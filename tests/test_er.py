from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from aeat_hub.dashboard import write_dashboard
from aeat_hub.er import REL_CONFLICTO, REL_CONTINUACION, REL_EVIDENCIA, backfill_asientos, count_evidencias
from aeat_hub.ingest import ingest_file
from aeat_hub.models import Actividad, Asiento, Documento, Factura, Relacion
from aeat_hub.ocr.base import OCRResult
from tests.samples import FACTURA_LUZ, write_pdf


class FakeRapid:
    name = "rapidocr"

    def available(self):
        return True, "fake"

    def transcribe(self, path: Path) -> OCRResult:
        return OCRResult(text="foto ocr", engine="rapidocr", confidence=0.7)


OBRAMAT = """\
OBRAMAT
BRICOMAN S.L.U
NIF: B12345674
Ticket de caja
010-000043-004-4843-NFS: 055610 15/08/2026 13:48 - Venta -
Pag. 1 / 2
Total SI (EUR)
94,21
Total IVA
19,78
Total TTI (EUR)
113,99
"""

OBRAMAT_PAG2 = """\
OBRAMAT
BRICOMAN S.L.U
NIF: B12345674
Ticket de caja
010-000043-004-4843-NFS: 055610 15/08/2026 13:48 - Venta -
Pag. 2 / 2
"""

OBRAMAT_OTRO_TOTAL = """\
OBRAMAT
BRICOMAN S.L.U
NIF: B12345674
Ticket de caja
010-000043-004-4843-NFS: 055610 15/08/2026 13:48 - Venta -
Pag. 1 / 1
Total SI (EUR)
10,00
Total IVA
2,10
Total TTI (EUR)
12,10
"""


def test_dos_ficheros_mismo_id_un_asiento(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    a = write_pdf(layout.inbox / "luz-a.pdf", FACTURA_LUZ)
    b = write_pdf(layout.inbox / "luz-b.pdf", FACTURA_LUZ + "\nCopia de escaneo\n")
    first = ingest_file(session, layout, a, actividad, rapid=FakeRapid())
    second = ingest_file(session, layout, b, actividad, rapid=FakeRapid())
    session.commit()
    assert first.asiento_id == second.asiento_id
    assert session.scalar(select(func.count()).select_from(Asiento)) == 1
    assert session.scalar(select(func.count()).select_from(Documento)) == 2
    assert session.scalar(select(func.count()).select_from(Factura)) == 1
    factura = session.scalar(select(Factura))
    assert count_evidencias(session, factura.id) == 2
    evidencias = session.scalars(
        select(Relacion).where(Relacion.tipo == REL_EVIDENCIA)
    ).all()
    assert len(evidencias) == 2


def test_continuacion_sin_total_no_crea_asiento(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    p1 = write_pdf(layout.inbox / "obr-1.pdf", OBRAMAT)
    p2 = write_pdf(layout.inbox / "obr-2.pdf", OBRAMAT_PAG2)
    first = ingest_file(session, layout, p1, actividad, rapid=FakeRapid())
    second = ingest_file(session, layout, p2, actividad, rapid=FakeRapid())
    session.commit()
    assert first.asiento_id == second.asiento_id
    assert session.scalar(select(func.count()).select_from(Asiento)) == 1
    asiento = session.get(Asiento, first.asiento_id)
    assert asiento.total == Decimal("113.99")
    cont = session.scalars(select(Relacion).where(Relacion.tipo == REL_CONTINUACION)).all()
    assert len(cont) == 1


def test_mismo_id_total_distinto_es_conflicto(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    a = write_pdf(layout.inbox / "obr-a.pdf", OBRAMAT)
    b = write_pdf(layout.inbox / "obr-b.pdf", OBRAMAT_OTRO_TOTAL)
    ingest_file(session, layout, a, actividad, rapid=FakeRapid())
    ingest_file(session, layout, b, actividad, rapid=FakeRapid())
    session.commit()
    facturas = session.scalars(select(Factura)).all()
    assert len(facturas) == 2
    assert {item.estado_er for item in facturas} == {"conflicto"}
    assert session.scalar(select(func.count()).select_from(Asiento)) == 2
    assert session.scalar(select(func.count()).select_from(Relacion).where(Relacion.tipo == REL_CONFLICTO)) == 1


def test_backfill_asientos_sin_factura(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    asiento = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        fecha=date(2026, 3, 10),
        ejercicio=2026,
        emisor="IBERDROLA DEMO",
        nif_emisor="B12345674",
        numero_factura="F-BACKFILL",
        total=Decimal("10.00"),
        estado="confirmado",
    )
    session.add(asiento)
    session.flush()
    assert asiento.factura_id is None
    n = backfill_asientos(session)
    session.flush()
    assert n == 1
    assert asiento.factura_id is not None
    factura = session.get(Factura, asiento.factura_id)
    assert factura.numero_norm == "FBACKFILL"


def test_dashboard_chip_n_docs(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    a = write_pdf(layout.inbox / "luz-a.pdf", FACTURA_LUZ)
    b = write_pdf(layout.inbox / "luz-b.pdf", FACTURA_LUZ + "\nOtra foto\n")
    ingest_file(session, layout, a, actividad, rapid=FakeRapid())
    ingest_file(session, layout, b, actividad, rapid=FakeRapid())
    session.commit()
    html = write_dashboard(session, layout, actividad, 2026).read_text(encoding="utf-8")
    assert "2 docs" in html
    assert "docs-chip" in html
