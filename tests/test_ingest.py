from pathlib import Path
from decimal import Decimal

from sqlalchemy import select

from aeat_hub.ingest import _quarantine, ingest_file, ingest_inbox, reparse_asientos
from aeat_hub.models import Actividad, Asiento, Documento, Factura
from aeat_hub.ocr.base import OCRResult
from aeat_hub.ocr.cascade import transcribe
from aeat_hub.ocr.pdf_native import PdfNativeProvider
from tests.samples import FACTURA_LUZ, write_pdf


class FakeRapid:
    name = "rapidocr"

    def available(self):
        return True, "fake"

    def transcribe(self, path: Path) -> OCRResult:
        if path.suffix.lower() == ".pdf":
            native = PdfNativeProvider().transcribe(path)
            return OCRResult(text=native.text, engine="rapidocr", confidence=0.9)
        return OCRResult(text="foto ocr", engine="rapidocr", confidence=0.7)


def test_pdf_nativo_tiene_alta_confianza(tmp_path: Path):
    pdf = write_pdf(tmp_path / "luz.pdf", FACTURA_LUZ)
    result = PdfNativeProvider().transcribe(pdf)
    assert "IBERDROLA" in result.text.upper()
    assert result.confidence >= 0.65


def test_ingest_pdf_texto_crea_asiento_luz(session, layout):
    pdf = write_pdf(layout.inbox / "luz.pdf", FACTURA_LUZ)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    item = ingest_file(session, layout, pdf, actividad, rapid=FakeRapid())
    session.commit()
    assert item.asiento_id is not None
    asiento = session.get(Asiento, item.asiento_id)
    assert asiento.cuenta_codigo == "CI.GAS.LUZ"
    assert asiento.estado == "confirmado"
    assert asiento.total is not None
    assert not pdf.exists()
    assert session.scalar(select(Documento.id)) is not None


def test_ingest_mismo_fichero_es_duplicado_hash(session, layout):
    pdf = write_pdf(layout.inbox / "luz.pdf", FACTURA_LUZ)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    ingest_file(session, layout, pdf, actividad, rapid=FakeRapid())
    session.commit()
    copy = write_pdf(layout.inbox / "luz-copia.pdf", FACTURA_LUZ)
    original = Path(session.scalar(select(Documento.ruta_almacenada)))
    copy.write_bytes(original.read_bytes())
    item = ingest_file(session, layout, copy, actividad, rapid=FakeRapid())
    assert item.estado == "duplicado"
    assert item.asiento_id is None


def test_cascade_auto_no_usa_texto_incrustado(tmp_path: Path):
    pdf = write_pdf(tmp_path / "luz.pdf", FACTURA_LUZ)
    result = transcribe(pdf, prefer="auto", rapid=FakeRapid())
    assert result.engine == "rapidocr"
    assert result.engine != "pdf-native"
    assert "F2026-000123" in result.text


def test_reparse_no_pisa_asiento_validado(session, layout):
    from aeat_hub.classify import validar_asiento
    from aeat_hub.ingest import reparse_asientos

    pdf = write_pdf(layout.inbox / "luz.pdf", FACTURA_LUZ)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    item = ingest_file(session, layout, pdf, actividad, rapid=FakeRapid())
    session.commit()
    asiento = session.get(Asiento, item.asiento_id)
    asiento.emisor = "NO TOCAR"
    asiento.total = None
    validar_asiento(asiento)
    session.commit()
    n = reparse_asientos(session, actividad)
    session.commit()
    asiento = session.get(Asiento, item.asiento_id)
    assert n == 0
    assert asiento.emisor == "NO TOCAR"
    assert asiento.validado


def test_auto_con_rapid_inyectado_no_salta_a_vision(tmp_path: Path):
    from PIL import Image

    image = tmp_path / "blank.png"
    Image.new("RGB", (16, 16), "white").save(image)
    result = transcribe(image, prefer="auto", rapid=FakeRapid())
    assert result.engine == "rapidocr"
    assert result.text == "foto ocr"


def test_descuadre_lineas_senala_el_importe_que_falta():
    from decimal import Decimal

    from aeat_hub.extract.schema import InvoiceExtract, InvoiceLine
    from aeat_hub.ingest import _descuadre_lineas

    extract = InvoiceExtract(
        total=Decimal("13.86"),
        lineas=[
            InvoiceLine(descripcion="A", importe=Decimal("5.14")),
            InvoiceLine(descripcion="B", importe=Decimal("4.11")),
            InvoiceLine(descripcion="C", importe=Decimal("3.15")),
        ],
    )
    assert _descuadre_lineas(extract) == Decimal("1.46")


def test_quarantine_rescata_fichero_movido_a_archivo(layout):
    sha = "ab" * 32
    stored = (
        layout.archivo
        / "CI-VA-001"
        / "2026"
        / "01"
        / "gasto"
        / "luz"
        / f"{sha[:12]}_luz.pdf"
    )
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(b"%PDF-1.4 demo")

    dest = _quarantine(layout, layout.inbox / "luz.pdf", sha)

    assert dest == layout.rejected / "error" / "luz.pdf"
    assert dest.is_file()
    assert not stored.exists()


def test_ingest_lote_error_tras_archivar_rescata_fichero(session, layout, monkeypatch):
    pdf = write_pdf(layout.inbox / "luz.pdf", FACTURA_LUZ)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))

    def commit_bloqueado():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(session, "commit", commit_bloqueado)
    items = ingest_inbox(session, layout, actividad, rapid=FakeRapid())
    monkeypatch.undo()

    assert len(items) == 1
    assert items[0].estado == "error"
    assert not pdf.exists()
    assert (layout.rejected / "error" / "luz.pdf").is_file()
    assert not list(layout.archivo.rglob("*.pdf"))
    assert not session.scalars(select(Documento.id)).all()


def test_reparse_sincroniza_factura_salvo_divergencias(session, layout):
    pdf = write_pdf(layout.inbox / "luz.pdf", FACTURA_LUZ)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    item = ingest_file(session, layout, pdf, actividad, rapid=FakeRapid())
    session.commit()
    asiento = session.get(Asiento, item.asiento_id)
    factura = session.get(Factura, asiento.factura_id)
    emisor_ocr = asiento.emisor
    assert emisor_ocr

    # emisor idéntico en ambos (sin divergencia) y total divergente:
    # el reparse debe refrescar el primero y respetar el segundo.
    asiento.emisor = "VIEJO SA"
    factura.emisor = "VIEJO SA"
    factura.total = Decimal("1.00")
    session.commit()

    n = reparse_asientos(session, actividad)
    session.commit()

    asiento = session.get(Asiento, item.asiento_id)
    factura = session.get(Factura, asiento.factura_id)
    assert n == 1
    assert asiento.emisor == emisor_ocr
    assert factura.emisor == emisor_ocr
    assert factura.total == Decimal("1.00")


def test_reparse_refresca_las_lineas_de_la_tabla(session, layout):
    from aeat_hub.edits import lineas_de_asiento, patch_asiento

    pdf = write_pdf(layout.inbox / "luz.pdf", FACTURA_LUZ)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    item = ingest_file(session, layout, pdf, actividad, rapid=FakeRapid())
    session.commit()
    asiento = session.get(Asiento, item.asiento_id)

    # edición humana de líneas sin validar (mantener_estado evita el validado)
    patch_asiento(
        session,
        asiento.id,
        {"lineas": [{"descripcion": "EDITADA", "importe": "1,00"}], "mantener_estado": True},
    )
    session.commit()
    assert [i["descripcion"] for i in lineas_de_asiento(asiento)] == ["EDITADA"]

    n = reparse_asientos(session, actividad)
    session.commit()
    assert n == 1
    descripciones = [i["descripcion"] for i in lineas_de_asiento(asiento)]
    assert "EDITADA" not in descripciones


def test_ingest_misma_factura_con_numero_distinto_queda_sospechoso(session, layout):
    """El caso IKEA real: misma compra con número de factura y de servicio."""
    from aeat_hub.ingest import _apply_duplicate_and_state

    pdf1 = write_pdf(layout.inbox / "factura.pdf", FACTURA_LUZ)
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    item1 = ingest_file(session, layout, pdf1, actividad, rapid=FakeRapid())
    session.commit()
    assert item1.estado == "confirmado"

    variante = FACTURA_LUZ.replace("F2026-000123", "SERV-2026-555")
    pdf2 = write_pdf(layout.inbox / "servicio.pdf", variante)
    item2 = ingest_file(session, layout, pdf2, actividad, rapid=FakeRapid())
    session.commit()

    # NIF+total+fecha coinciden (nivel 3) y hay número parseado: sospechoso,
    # no duplicado automático.
    assert item2.estado == "pendiente"
    asiento2 = session.get(Asiento, item2.asiento_id)
    assert asiento2.duplicado_nivel == 3
    assert asiento2.duplicado_de_id == item1.asiento_id

    # sin número parseado, el nivel 3 sigue marcando duplicado directamente
    from decimal import Decimal as _D

    from aeat_hub.ingest import DuplicateHit

    row = Asiento(actividad_id=actividad.id, tipo="gasto", estado="pendiente")
    _apply_duplicate_and_state(
        row, DuplicateHit(3, 99, None, "mismo NIF+importe±3 días"), _D("0.9"), con_numero=False
    )
    assert row.estado == "duplicado"
    assert row.duplicado_de_id == 99
