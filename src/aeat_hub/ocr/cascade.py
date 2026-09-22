"""Cascada OCR: siempre imagen. Vision en macOS, RapidOCR si no hay Vision.

No se usa la capa de texto que incrusta Adobe Scan ni otro programa.
`--ocr native` sigue disponible solo si se pide a mano.
"""

from __future__ import annotations

import platform
from pathlib import Path

from aeat_hub.ocr.apple_vision import AppleVisionProvider
from aeat_hub.ocr.base import OCRResult, OCRProvider, ProviderUnavailable
from aeat_hub.ocr.ollama_deepseek import OllamaOCRProvider
from aeat_hub.ocr.paddle_vl import PaddleVLProvider
from aeat_hub.ocr.pdf_native import PdfNativeProvider
from aeat_hub.ocr.rapid import RapidOCRProvider
from aeat_hub.ocr.tesseract import TesseractProvider
from aeat_hub.ocr.unlimited import UnlimitedOCRProvider

OPTIONAL = {
    "unlimited": UnlimitedOCRProvider,
    "paddle": PaddleVLProvider,
    "vision": AppleVisionProvider,
    "tesseract": TesseractProvider,
    "deepseek": OllamaOCRProvider,
}


def describe_auto() -> str:
    """Qué haría `--ocr auto` en esta máquina."""
    name, reason = scan_engine_choice()
    return f"Siempre OCR de imagen: {name} ({reason}). No usa el texto incrustado del PDF."


def scan_engine_choice() -> tuple[str, str]:
    """Motor de imagen por defecto: Vision en Mac, RapidOCR en el resto."""
    if platform.system() == "Darwin":
        ok, reason = AppleVisionProvider().available()
        if ok:
            return "apple-vision", f"{reason}; RapidOCR si Vision falla"
    ok, reason = RapidOCRProvider().available()
    if ok:
        return "rapidocr", reason
    return "ninguno", reason


def transcribe(
    path: Path,
    *,
    prefer: str = "auto",
    warnings: list[str] | None = None,
    rapid: OCRProvider | None = None,
) -> OCRResult:
    """Devuelve texto. `prefer` = auto|native|rapid|vision|deepseek|unlimited|paddle|tesseract."""
    notes = warnings if warnings is not None else []
    path = Path(path)
    if prefer in OPTIONAL:
        provider = OPTIONAL[prefer]()
        try:
            return provider.transcribe(path)
        except ProviderUnavailable as exc:
            notes.append(f"{exc.name} no disponible ({exc.reason}); se usa la cascada local.")
            prefer = "auto"

    if path.suffix.lower() == ".pdf" and prefer == "native":
        return PdfNativeProvider().transcribe(path)

    return _scan(path, prefer=prefer, notes=notes, rapid=rapid)


def _scan(
    path: Path,
    *,
    prefer: str,
    notes: list[str],
    rapid: OCRProvider | None,
) -> OCRResult:
    rapid_provider = rapid or RapidOCRProvider()
    # Los tests inyectan FakeRapid: no saltar a Vision.
    use_vision = (
        rapid is None
        and prefer in {"auto", "vision"}
        and platform.system() == "Darwin"
    )
    if use_vision:
        vision = AppleVisionProvider()
        ok, reason = vision.available()
        if ok:
            try:
                return vision.transcribe(path)
            except ProviderUnavailable as exc:
                notes.append(f"{exc}; se usa RapidOCR.")
        else:
            notes.append(f"Apple Vision no disponible ({reason}); se usa RapidOCR.")

    try:
        return rapid_provider.transcribe(path)
    except ProviderUnavailable as exc:
        notes.append(str(exc))
        if path.suffix.lower() == ".pdf":
            native = PdfNativeProvider().transcribe(path)
            if native.text.strip():
                return native
        return OCRResult(text="", engine="none", confidence=0.0, pages=1)
