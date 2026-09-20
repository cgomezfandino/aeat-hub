"""Cascada OCR: PDF nativo → RapidOCR → proveedores opcionales si se piden."""

from __future__ import annotations

from pathlib import Path

from aeat_hub.ocr.base import OCRResult, OCRProvider, ProviderUnavailable
from aeat_hub.ocr.paddle_vl import PaddleVLProvider
from aeat_hub.ocr.pdf_native import PdfNativeProvider
from aeat_hub.ocr.rapid import RapidOCRProvider
from aeat_hub.ocr.unlimited import UnlimitedOCRProvider

NATIVE_THRESHOLD = 0.65
OPTIONAL = {"unlimited": UnlimitedOCRProvider, "paddle": PaddleVLProvider}


def transcribe(
    path: Path,
    *,
    prefer: str = "auto",
    warnings: list[str] | None = None,
    rapid: OCRProvider | None = None,
) -> OCRResult:
    """Devuelve texto. `prefer` = auto|native|rapid|unlimited|paddle."""
    notes = warnings if warnings is not None else []
    path = Path(path)
    if prefer in OPTIONAL:
        provider = OPTIONAL[prefer]()
        try:
            return provider.transcribe(path)
        except ProviderUnavailable as exc:
            notes.append(f"{exc.name} no disponible ({exc.reason}); se usa la cascada local.")
            prefer = "auto"

    if path.suffix.lower() == ".pdf" and prefer in {"auto", "native"}:
        native = PdfNativeProvider().transcribe(path)
        if native.confidence >= NATIVE_THRESHOLD or prefer == "native":
            return native
        notes.append("PDF sin capa de texto usable; se pasa a RapidOCR.")

    rapid_provider = rapid or RapidOCRProvider()
    try:
        return rapid_provider.transcribe(path)
    except ProviderUnavailable as exc:
        notes.append(str(exc))
        if path.suffix.lower() == ".pdf":
            native = PdfNativeProvider().transcribe(path)
            if native.text.strip():
                return native
        return OCRResult(text="", engine="none", confidence=0.0, pages=1)
