"""RapidOCR (ONNX) como motor por defecto para fotos y PDF escaneados."""

from __future__ import annotations

from pathlib import Path

from aeat_hub.ocr.base import OCRResult, ProviderUnavailable
from aeat_hub.ocr.render import iter_page_images

_ENGINE = None


class RapidOCRProvider:
    name = "rapidocr"

    def available(self) -> tuple[bool, str]:
        try:
            import rapidocr  # noqa: F401
        except ImportError:
            return False, "paquete rapidocr no instalado"
        return True, "rapidocr+onnxruntime"

    def transcribe(self, path: Path) -> OCRResult:
        ok, reason = self.available()
        if not ok:
            raise ProviderUnavailable(self.name, reason)
        engine = _get_engine()
        texts: list[str] = []
        pages = 0
        try:
            for image in iter_page_images(path):
                pages += 1
                texts.append(_run_engine(engine, image))
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, str(exc)) from exc
        text = "\n".join(part for part in texts if part).strip()
        conf = 0.75 if len(text) >= 40 else 0.35 if text else 0.05
        return OCRResult(text=text, engine=self.name, confidence=conf, pages=max(pages, 1))


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _run_engine(engine, image) -> str:
    import numpy as np

    result = engine(np.array(image.convert("RGB")))
    if result is None:
        return ""
    if hasattr(result, "txts") and result.txts:
        return "\n".join(str(t) for t in result.txts)
    if isinstance(result, tuple) and result and isinstance(result[0], list):
        lines = []
        for item in result[0]:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                lines.append(str(item[1]))
            else:
                lines.append(str(item))
        return "\n".join(lines)
    return str(result)
