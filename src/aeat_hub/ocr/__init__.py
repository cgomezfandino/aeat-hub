"""Proveedores OCR."""

from aeat_hub.ocr.base import OCRResult, ProviderUnavailable
from aeat_hub.ocr.cascade import transcribe

__all__ = ["OCRResult", "ProviderUnavailable", "transcribe"]
