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
    assert result.engine == "pdf-native"
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
    assert result.engine == "pdf-native"


def test_scan_engine_choice_linux_usa_rapid(monkeypatch):
    monkeypatch.setattr("aeat_hub.ocr.cascade.platform.system", lambda: "Linux")
    name, _reason = scan_engine_choice()
    assert name == "rapidocr"
    monkeypatch.setenv("AEAT_HUB_UNLIMITED_OCR_URL", "http://127.0.0.1:9/v1/chat/completions")
    ok, reason = UnlimitedOCRProvider().available()
    assert ok is True
    assert reason.startswith("http://")
    os.environ.pop("AEAT_HUB_UNLIMITED_OCR_URL", None)
