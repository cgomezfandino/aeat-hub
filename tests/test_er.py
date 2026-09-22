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
        if path.suffix.lower() == ".pdf":
            from aeat_hub.ocr.pdf_native import PdfNativeProvider

            native = PdfNativeProvider().transcribe(path)
            return OCRResult(text=native.text, engine="rapidocr", confidence=0.9)
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


def test_corregir_numero_y_unir_mismo_id(session, layout):
    from aeat_hub.er import corregir_numero, count_evidencias

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    a = write_pdf(layout.inbox / "luz-ok.pdf", FACTURA_LUZ)
    b = write_pdf(
        layout.inbox / "luz-mal.pdf",
        FACTURA_LUZ.replace("F2026-000123", "F2026-000999") + "\nOCR malo\n",
    )
    first = ingest_file(session, layout, a, actividad, rapid=FakeRapid())
    second = ingest_file(session, layout, b, actividad, rapid=FakeRapid())
    session.commit()
    assert first.asiento_id != second.asiento_id
    asiento_mal = session.get(Asiento, second.asiento_id)
    resultado = corregir_numero(session, asiento_mal, "F2026-000123")
    session.commit()
    vivos = session.scalars(select(Asiento).where(Asiento.estado != "duplicado")).all()
    assert len(vivos) == 1
    assert vivos[0].id == first.asiento_id
    assert vivos[0].numero_factura == "F2026-000123"
    assert resultado.unido_a is not None
    assert resultado.unido_a.id == first.asiento_id
    duplicado = session.get(Asiento, second.asiento_id)
    assert duplicado.estado == "duplicado"
    assert duplicado.duplicado_de_id == first.asiento_id
    assert count_evidencias(session, vivos[0].factura_id) == 2


def test_corregir_numero_conflicto_si_el_total_no_cuadra(session, layout):
    from aeat_hub.er import corregir_numero

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    a = write_pdf(layout.inbox / "obr-a.pdf", OBRAMAT.replace("010-000043-004-4843-NFS: 055610", "010-000043-004-4843-NFS: 055611"))
    b = write_pdf(layout.inbox / "obr-b.pdf", OBRAMAT_OTRO_TOTAL)
    first = ingest_file(session, layout, a, actividad, rapid=FakeRapid())
    second = ingest_file(session, layout, b, actividad, rapid=FakeRapid())
    session.commit()
    asiento_b = session.get(Asiento, second.asiento_id)
    resultado = corregir_numero(session, asiento_b, "010-000043-004-4843-NFS:055611")
    session.commit()
    assert resultado.conflicto_con is not None
    assert resultado.conflicto_con.id == first.asiento_id
    assert session.scalar(select(func.count()).select_from(Asiento).where(Asiento.estado != "duplicado")) == 2
