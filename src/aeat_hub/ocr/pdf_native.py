"""Texto nativo de PDF (sin OCR) cuando la capa de texto es usable."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from aeat_hub.ocr.base import OCRResult, ProviderUnavailable

MIN_CHARS = 40


class PdfNativeProvider:
    name = "pdf-native"

    def available(self) -> tuple[bool, str]:
        return True, "pymupdf"

    def transcribe(self, path: Path) -> OCRResult:
        if path.suffix.lower() != ".pdf":
            raise ProviderUnavailable(self.name, "solo PDF")
        try:
            doc = pymupdf.open(path)
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, str(exc)) from exc
        parts: list[str] = []
        try:
            for page in doc:
                parts.append(page.get_text("text") or "")
        finally:
            doc.close()
        text = "\n".join(parts).strip()
        return OCRResult(
            text=text,
            engine=self.name,
            confidence=_native_quality(text),
            pages=max(len(parts), 1),
        )


def _native_quality(text: str) -> float:
    stripped = text.strip()
    if len(stripped) < MIN_CHARS:
        return 0.1
    letters = sum(char.isalpha() for char in stripped)
    ratio = letters / max(len(stripped), 1)
    if ratio < 0.12:
        return 0.2
    score = 0.45
    upper = stripped.upper()
    if any(token in upper for token in ("NIF", "CIF", "IVA", "FACTURA", "TOTAL")):
        score += 0.25
    if any(char.isdigit() for char in stripped):
        score += 0.15
    if "€" in stripped or "EUR" in upper:
        score += 0.1
    return min(round(score, 3), 0.99)
