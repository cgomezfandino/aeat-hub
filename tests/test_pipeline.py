from pathlib import Path

from sqlalchemy import select

from aeat_hub.ingest import ingest_inbox
from aeat_hub.logutil import setup_run_log
from aeat_hub.models import Actividad, Asiento
from aeat_hub.ocr.base import OCRResult
from tests.samples import FACTURA_LUZ, write_pdf


class SelectiveRapid:
    name = "rapidocr"

    def available(self):
        return True, "fake"

    def transcribe(self, path: Path) -> OCRResult:
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            raise RuntimeError("ocr boom de prueba")
        return OCRResult(text="foto ocr", engine="rapidocr", confidence=0.7)


def test_lote_sigue_si_un_fichero_peta(session, layout):
    write_pdf(layout.inbox / "luz.pdf", FACTURA_LUZ)
    (layout.inbox / "ticket.jpg").write_bytes(b"not-a-real-jpeg")
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    items = ingest_inbox(session, layout, actividad, rapid=SelectiveRapid())
    estados = {item.path.name: item.estado for item in items}
    assert "confirmado" in estados.values() or any(i.asiento_id for i in items)
    assert any(i.estado == "error" for i in items)
    error = next(i for i in items if i.estado == "error")
    assert error.path.parent.name == "error"
    assert session.scalar(select(Asiento).where(Asiento.cuenta_codigo == "CI.GAS.LUZ")) is not None


def test_setup_run_log_escribe_etapas(layout):
    log_path = setup_run_log(layout, comando="prueba")
    assert log_path.is_file()
    text = log_path.read_text(encoding="utf-8")
    assert "log de esta corrida" in text
    assert str(log_path) in text
