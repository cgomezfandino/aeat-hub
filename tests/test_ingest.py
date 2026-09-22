from pathlib import Path

from sqlalchemy import select

from aeat_hub.ingest import ingest_file
from aeat_hub.models import Actividad, Asiento, Documento
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
