"""Extracción con Gemini: esquema, campos legales nuevos y salvaguardas."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from aeat_hub.extract.parser import parse_invoice
from aeat_hub.ingest import avisos_documento, ingest_file
from aeat_hub.models import Actividad, Asiento
from aeat_hub.ocr.base import OCRResult
from tests.samples import write_pdf


def _json(**data) -> str:
    return json.dumps(data)


def test_peticion_lleva_esquema_y_temperatura_cero(monkeypatch, tmp_path):
    from aeat_hub.ocr.gemini import GeminiOCRProvider
    from tests.samples import FACTURA_LUZ

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(
        "aeat_hub.ocr.gemini.iter_page_images",
        lambda path, dpi=180: iter([Image.new("RGB", (8, 8))]),
    )
    enviado = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}]}
            ).encode()

    def _urlopen(req, timeout=75):
        enviado.update(json.loads(req.data))
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    GeminiOCRProvider().transcribe(write_pdf(tmp_path / "x.pdf", FACTURA_LUZ))
    config = enviado["generationConfig"]
    assert config["temperature"] == 0.0
    esquema = config["responseSchema"]["properties"]
    assert esquema["tipo_documento"]["enum"] == ["completa", "simplificada", "rectificativa", "no_factura"]
    assert "recargo_cuota" in esquema["desglose_iva"]["items"]["properties"]
    assert "campos_dudosos" in esquema


def test_campos_legales_nuevos_del_json():
    extract = parse_invoice(
        _json(
            tipo_documento="completa",
            emisor="ASESORIA",
            nif_emisor="B12345674",
            serie="A",
            numero="2026-0001",
            fecha="2026-03-31",
            fecha_operacion="2026-03-31",
            moneda="eur",
            base=100,
            iva_cuota=21,
            total=121,
            mencion_legal="criterio_caja",
        )
    )
    assert extract.serie == "A"
    assert extract.fecha_operacion is None  # igual que la de expedición: no se duplica
    assert extract.moneda == "EUR"
    assert extract.mencion_legal == "criterio_caja"
    assert extract.confianza >= 0.9


def test_recargo_de_equivalencia_cuadra_y_suma_al_total():
    extract = parse_invoice(
        _json(
            tipo_documento="completa",
            emisor="MAYORISTA SA",
            nif_emisor="A28812618",
            numero="M-1",
            fecha="2026-04-01",
            base=100,
            iva_tipo=21,
            total=126.2,
            desglose_iva=[
                {"base": 100, "iva_tipo": 21, "iva_cuota": 21, "recargo_tipo": 5.2, "recargo_cuota": 5.2}
            ],
        )
    )
    # la cuota sale del total descontando el recargo, no se lo come el IVA
    assert extract.iva_cuota == Decimal("21.00")
    assert extract.confianza >= 0.9


def test_abono_multitipo_suma_bases_negativas():
    extract = parse_invoice(
        _json(
            tipo_documento="rectificativa",
            nif_emisor="B12345674",
            total=-33,
            desglose_iva=[
                {"base": -10, "iva_tipo": 21, "iva_cuota": -2.1},
                {"base": -19, "iva_tipo": 10, "iva_cuota": -1.9},
            ],
        )
    )
    assert extract.base == Decimal("-29.00")
    assert extract.iva_cuota == Decimal("-4.00")


def test_linea_sin_tipo_no_hereda_el_de_cabecera_si_hay_varios():
    extract = parse_invoice(
        _json(
            nif_emisor="B12345674",
            total=33,
            iva_tipo=21,
            desglose_iva=[
                {"base": 10, "iva_tipo": 21, "iva_cuota": 2.1},
                {"base": 19, "iva_tipo": 10, "iva_cuota": 1.9},
            ],
            lineas=[{"descripcion": "Libro", "importe": 20.9, "cantidad": 0}],
        )
    )
    linea = extract.lineas[0]
    assert linea.iva_tipo is None
    assert linea.cantidad == Decimal("0.00")  # cantidad 0 no se convierte en 1


def test_confianza_baja_si_no_cuadra_o_hay_dudas():
    buena = parse_invoice(
        _json(tipo_documento="completa", emisor="X SL", nif_emisor="B12345674", numero="1",
              fecha="2026-01-01", base=100, iva_cuota=21, total=121)
    )
    descuadrada = parse_invoice(
        _json(tipo_documento="completa", emisor="X SL", nif_emisor="B12345674", numero="1",
              fecha="2026-01-01", base=100, iva_cuota=21, total=150)
    )
    dudosa = parse_invoice(
        _json(tipo_documento="completa", emisor="X SL", nif_emisor="B12345674", numero="1",
              fecha="2026-01-01", base=100, iva_cuota=21, total=121,
              campos_dudosos=["numero", "fecha"])
    )
    assert buena.confianza > dudosa.confianza > descuadrada.confianza


@pytest.mark.parametrize(
    "datos, fragmento",
    [
        ({"tipo_documento": "no_factura", "total": 50}, "no parece una factura"),
        ({"tipo_documento": "completa", "moneda": "USD", "total": 50}, "Factura en USD"),
        ({"tipo_documento": "completa", "total": 50, "campos_dudosos": ["total"]}, "poco legibles"),
    ],
)
def test_avisos_documento(datos, fragmento):
    avisos = avisos_documento(parse_invoice(_json(**datos)))
    assert any(fragmento in aviso for aviso in avisos)


class _FakeJSON:
    """OCR falso que devuelve el JSON de Gemini para cualquier fichero."""

    name = "rapidocr"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def available(self):
        return True, "fake"

    def transcribe(self, path: Path) -> OCRResult:
        return OCRResult(text=json.dumps(self.payload), engine="rapidocr", confidence=0.98)


def _factura_luz(tipo: str) -> dict:
    return {
        "tipo_documento": tipo,
        "emisor": "IBERDROLA CLIENTES SAU",
        "nif_emisor": "A95758389",
        "numero": f"FL-{tipo}",
        "fecha": "2026-03-10",
        "base": 40,
        "iva_tipo": 21,
        "iva_cuota": 8.4,
        "total": 48.4,
    }


def test_no_factura_nunca_se_consolida_sola(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    control = ingest_file(
        session, layout, write_pdf(layout.inbox / "a.pdf", "factura luz"), actividad,
        rapid=_FakeJSON(_factura_luz("completa")),
    )
    presupuesto = ingest_file(
        session, layout, write_pdf(layout.inbox / "b.pdf", "presupuesto luz"), actividad,
        rapid=_FakeJSON(_factura_luz("no_factura")),
    )
    session.commit()
    assert control.estado == "confirmado"  # el control sí se consolida: la diferencia es el tipo
    assert presupuesto.estado == "pendiente"
    assert any("no parece una factura" in aviso for aviso in presupuesto.warnings)
    fila = session.get(Asiento, presupuesto.asiento_id)
    assert fila.tipo_factura == "no_factura"


def test_foto_con_rotacion_exif_se_endereza(tmp_path):
    from aeat_hub.ocr.render import open_image

    foto = Image.new("RGB", (40, 20))
    exif = foto.getexif()
    exif[0x0112] = 6  # Orientation: girar 90° a la derecha
    ruta = tmp_path / "ticket.jpg"
    foto.save(ruta, exif=exif)
    assert open_image(ruta).size == (20, 40)


def test_eval_numero_exige_igualdad_no_subcadena():
    from aeat_hub.evals.metrics import _numero_equal

    assert _numero_equal("F-2026-0123", "F20260123")
    assert not _numero_equal("F-2026-0123", "0123")
