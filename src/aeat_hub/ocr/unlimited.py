"""Unlimited-OCR opcional (GGUF / servidor OpenAI-compatible). No bloquea el ingest."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from aeat_hub.ocr.base import OCRResult, ProviderUnavailable
from aeat_hub.ocr.render import iter_page_images

ENV_URL = "AEAT_HUB_UNLIMITED_OCR_URL"
ENV_GGUF = "AEAT_HUB_UNLIMITED_OCR_GGUF"
ENV_MMPROJ = "AEAT_HUB_UNLIMITED_OCR_MMPROJ"


class UnlimitedOCRProvider:
    name = "unlimited-ocr"

    def available(self) -> tuple[bool, str]:
        url = os.environ.get(ENV_URL, "").strip()
        if url:
            return True, url
        gguf = os.environ.get(ENV_GGUF, "").strip()
        if gguf and Path(gguf).is_file():
            if shutil.which("llama-mtmd-cli") or shutil.which("llama-cli"):
                return True, gguf
            return False, "hay GGUF pero falta llama-mtmd-cli en PATH"
        return False, f"define {ENV_URL} o {ENV_GGUF} (experimental en Apple Silicon 16 GB)"

    def transcribe(self, path: Path) -> OCRResult:
        ok, reason = self.available()
        if not ok:
            raise ProviderUnavailable(self.name, reason)
        url = os.environ.get(ENV_URL, "").strip()
        if url:
            return self._via_http(path, url)
        return self._via_cli(path)

    def _via_http(self, path: Path, url: str) -> OCRResult:
        images = list(iter_page_images(path, dpi=200))
        if not images:
            raise ProviderUnavailable(self.name, "no se pudo renderizar el documento")
        content: list[dict] = [{"type": "text", "text": "document parsing."}]
        with tempfile.TemporaryDirectory(prefix="uocr_") as tmp:
            tmp_path = Path(tmp)
            for idx, image in enumerate(images[:8], start=1):
                file = tmp_path / f"page_{idx:02d}.png"
                image.save(file, "PNG")
                encoded = base64.b64encode(file.read_bytes()).decode("ascii")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    }
                )
        payload = {
            "model": "Unlimited-OCR",
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": 4096,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(self.name, f"servidor no disponible: {exc}") from exc
        text = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not text:
            raise ProviderUnavailable(self.name, "respuesta vacía del servidor")
        return OCRResult(text=str(text), engine=self.name, confidence=0.8, pages=len(images))

    def _via_cli(self, path: Path) -> OCRResult:
        binary = shutil.which("llama-mtmd-cli") or shutil.which("llama-cli")
        gguf = os.environ.get(ENV_GGUF, "")
        mmproj = os.environ.get(ENV_MMPROJ, "")
        cmd = [binary, "-m", gguf, "-p", "document parsing."]
        if mmproj:
            cmd.extend(["--mmproj", mmproj])
        with tempfile.TemporaryDirectory(prefix="uocr_") as tmp:
            image_path = Path(tmp) / "page.png"
            page = next(iter_page_images(path, dpi=200), None)
            if page is None:
                raise ProviderUnavailable(self.name, "sin páginas")
            page.save(image_path, "PNG")
            cmd.extend(["--image", str(image_path)])
            try:
                completed = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ProviderUnavailable(self.name, str(exc)) from exc
        if completed.returncode != 0:
            raise ProviderUnavailable(self.name, completed.stderr.strip() or "llama-cli falló")
        text = (completed.stdout or "").strip()
        if not text:
            raise ProviderUnavailable(self.name, "salida vacía de llama-mtmd-cli")
        return OCRResult(text=text, engine=self.name, confidence=0.75, pages=1)
