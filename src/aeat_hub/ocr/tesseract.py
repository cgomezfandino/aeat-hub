"""Tesseract CLI opcional. No forma parte de la cascada por defecto."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from aeat_hub.ocr.base import OCRResult, ProviderUnavailable
from aeat_hub.ocr.render import iter_page_images


class TesseractProvider:
    name = "tesseract"

    def available(self) -> tuple[bool, str]:
        binary = shutil.which("tesseract")
        if not binary:
            return False, "tesseract no está en PATH (brew install tesseract tesseract-lang)"
        langs = _languages(binary)
        if "spa" in langs:
            return True, f"{binary} spa+eng"
        if "eng" in langs:
            return True, f"{binary} eng (sin spa)"
        return True, binary

    def transcribe(self, path: Path) -> OCRResult:
        ok, reason = self.available()
        if not ok:
            raise ProviderUnavailable(self.name, reason)
        binary = shutil.which("tesseract")
        assert binary is not None
        langs = _languages(binary)
        lang = "spa+eng" if "spa" in langs and "eng" in langs else ("spa" if "spa" in langs else "eng")
        texts: list[str] = []
        pages = 0
        try:
            for image in iter_page_images(path, dpi=200):
                pages += 1
                with tempfile.NamedTemporaryFile(prefix="aeat_tes_", suffix=".png", delete=False) as handle:
                    tmp = Path(handle.name)
                try:
                    image.convert("RGB").save(tmp, "PNG")
                    texts.append(_run(binary, tmp, lang))
                finally:
                    tmp.unlink(missing_ok=True)
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, str(exc)) from exc
        text = "\n".join(part for part in texts if part).strip()
        conf = 0.7 if len(text) >= 40 else 0.3 if text else 0.05
        return OCRResult(text=text, engine=self.name, confidence=conf, pages=max(pages, 1))


def _languages(binary: str) -> set[str]:
    try:
        completed = subprocess.run(
            [binary, "--list-langs"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {line.strip() for line in (completed.stdout or "").splitlines() if line.strip()}


def _run(binary: str, image: Path, lang: str) -> str:
    try:
        completed = subprocess.run(
            [binary, str(image), "stdout", "-l", lang, "--psm", "6"],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProviderUnavailable("tesseract", str(exc)) from exc
    if completed.returncode != 0:
        raise ProviderUnavailable(
            "tesseract",
            (completed.stderr or "tesseract falló").strip()[:500],
        )
    return (completed.stdout or "").strip()
