import os
from pathlib import Path

from aeat_hub.ocr.base import ProviderUnavailable
from aeat_hub.ocr.cascade import scan_engine_choice, transcribe
from aeat_hub.ocr.ollama_deepseek import OllamaOCRProvider
from aeat_hub.ocr.paddle_vl import PaddleVLProvider
from aeat_hub.ocr.unlimited import UnlimitedOCRProvider
from tests.samples import FACTURA_LUZ, write_pdf
from tests.test_ingest import FakeRapid


def test_unlimited_no_disponible_por_defecto():
    provider = UnlimitedOCRProvider()
    ok, reason = provider.available()
    assert ok is False
    assert "AEAT_HUB_UNLIMITED_OCR" in reason


def test_paddle_apagado_por_defecto():
    provider = PaddleVLProvider()
    ok, _reason = provider.available()
    assert ok is False


def test_prefer_unlimited_cae_a_cascada_local(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("AEAT_HUB_UNLIMITED_OCR_URL", raising=False)
    monkeypatch.delenv("AEAT_HUB_UNLIMITED_OCR_GGUF", raising=False)
    pdf = write_pdf(tmp_path / "luz.pdf", FACTURA_LUZ)
    warnings: list[str] = []
    result = transcribe(pdf, prefer="unlimited", warnings=warnings, rapid=FakeRapid())
    assert any("unlimited" in item.lower() or "Unlimited" in item for item in warnings) or any(
        "no disponible" in item for item in warnings
    )
    assert result.engine == "rapidocr"
    assert "IBERDROLA" in result.text.upper()


def test_unlimited_transcribe_falla_si_no_hay_backend():
    provider = UnlimitedOCRProvider()
    try:
        provider.transcribe(Path("nope.pdf"))
        assert False, "debía lanzar ProviderUnavailable"
    except ProviderUnavailable as exc:
        assert exc.name == "unlimited-ocr"


def test_deepseek_no_disponible_si_ollama_no_corre(monkeypatch):
    monkeypatch.setenv("AEAT_HUB_OLLAMA_URL", "http://127.0.0.1:9")
    ok, reason = OllamaOCRProvider().available()
    assert ok is False
    assert "Ollama" in reason


def test_prefer_deepseek_cae_a_cascada_local(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AEAT_HUB_OLLAMA_URL", "http://127.0.0.1:9")
    pdf = write_pdf(tmp_path / "luz.pdf", FACTURA_LUZ)
    warnings: list[str] = []
    result = transcribe(pdf, prefer="deepseek", warnings=warnings, rapid=FakeRapid())
    assert any("deepseek" in item.lower() or "no disponible" in item for item in warnings)
    assert result.engine == "rapidocr"


def test_scan_engine_choice_linux_usa_rapid(monkeypatch):
    monkeypatch.setattr("aeat_hub.ocr.cascade.platform.system", lambda: "Linux")
    name, _reason = scan_engine_choice()
    assert name == "rapidocr"
    monkeypatch.setenv("AEAT_HUB_UNLIMITED_OCR_URL", "http://127.0.0.1:9/v1/chat/completions")
    ok, reason = UnlimitedOCRProvider().available()
    assert ok is True
    assert reason.startswith("http://")
    os.environ.pop("AEAT_HUB_UNLIMITED_OCR_URL", None)


def test_gemini_no_disponible_si_no_hay_key(monkeypatch):
    from aeat_hub.ocr.gemini import GeminiOCRProvider

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    ok, reason = GeminiOCRProvider().available()
    assert ok is False
    assert "GEMINI_API_KEY" in reason


def test_prefer_gemini_cae_a_cascada_si_no_hay_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    pdf = write_pdf(tmp_path / "luz.pdf", FACTURA_LUZ)
    warnings: list[str] = []
    result = transcribe(pdf, prefer="gemini", warnings=warnings, rapid=FakeRapid())
    assert any("gemini" in item.lower() or "no disponible" in item for item in warnings)
    assert result.engine == "rapidocr"


def test_parse_invoice_json_directo():
    from aeat_hub.extract.parser import parse_invoice

    raw_json = """{
        "emisor": "FONTANERIA DEMO SL",
        "nif_emisor": "B12345674",
        "numero": "FAC-99",
        "fecha": "2026-05-10",
        "base": 100.0,
        "iva_tipo": 21,
        "iva_cuota": 21.0,
        "total": 121.0,
        "lineas": [
            {"codigo": "TUB-01", "descripcion": "Tubo de cobre", "cantidad": 2, "importe": 121.0}
        ]
    }"""
    extract = parse_invoice(raw_json, motor="gemini-2.5-flash")
    assert extract.emisor == "FONTANERIA DEMO SL"
    assert extract.nif_emisor == "B12345674"
    assert extract.total == 121.0
    assert len(extract.lineas) == 1
    assert extract.lineas[0].codigo == "TUB-01"
    assert extract.confianza >= 0.90


def test_gemini_transcribe_guarda_usage_metadata(tmp_path: Path, monkeypatch):
    import json as jsonlib

    from PIL import Image

    from aeat_hub.ocr.gemini import GeminiOCRProvider

    monkeypatch.setenv("GEMINI_API_KEY", "TESTKEY")
    monkeypatch.setattr(
        "aeat_hub.ocr.gemini.iter_page_images",
        lambda path, dpi=180: iter([Image.new("RGB", (16, 16))]),
    )
    body = jsonlib.dumps(
        {
            "candidates": [
                {"content": {"parts": [{"text": '{"emisor": "X", "total": 1}'}]}}
            ],
            "usageMetadata": {
                "promptTokenCount": 1266,
                "candidatesTokenCount": 100,
                "totalTokenCount": 1366,
            },
        }
    ).encode("utf-8")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return body

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=75: _Resp())
    pdf = write_pdf(tmp_path / "x.pdf", FACTURA_LUZ)
    result = GeminiOCRProvider().transcribe(pdf)
    assert result.usage.get("totalTokenCount") == 1366
    assert '"emisor"' in result.text
