"""PaddleOCR-VL opcional. Pesado en M1 16 GB; solo si AEAT_HUB_PADDLEOCR_VL=1."""

from __future__ import annotations

import os
from pathlib import Path

from aeat_hub.ocr.base import OCRResult, ProviderUnavailable

ENV_FLAG = "AEAT_HUB_PADDLEOCR_VL"


class PaddleVLProvider:
    name = "paddleocr-vl"

    def available(self) -> tuple[bool, str]:
        flag = os.environ.get(ENV_FLAG, "").strip().lower()
        if flag not in {"1", "true", "yes", "on"}:
            return False, f"activa {ENV_FLAG}=1 para intentar PaddleOCR-VL"
        try:
            import paddleocr  # noqa: F401
        except ImportError:
            return False, "paddleocr no está instalado (no forma parte del extra por defecto)"
        return True, "paddleocr"

    def transcribe(self, path: Path) -> OCRResult:
        ok, reason = self.available()
        if not ok:
            raise ProviderUnavailable(self.name, reason)
        try:
            from paddleocr import PaddleOCRVL
        except ImportError:
            try:
                from paddleocr import PaddleOCR as PaddleOCRVL
            except ImportError as exc:
                raise ProviderUnavailable(self.name, str(exc)) from exc
        try:
            pipeline = PaddleOCRVL()
            output = pipeline.predict(str(path))
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, str(exc)) from exc
        text = _as_text(output)
        if not text:
            raise ProviderUnavailable(self.name, "PaddleOCR-VL no devolvió texto")
        return OCRResult(text=text, engine=self.name, confidence=0.8, pages=1)


def _as_text(output: object) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("rec_texts", "text", "markdown", "result"):
            if key in output:
                return _as_text(output[key])
        return json_fallback(output)
    if isinstance(output, list):
        return "\n".join(_as_text(item) for item in output if item)
    return str(output)


def json_fallback(value: object) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)
