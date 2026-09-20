"""DeepSeek-OCR (y otros VLM OCR) vía Ollama local. Opcional; no es el default."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from aeat_hub.ocr.base import OCRResult, ProviderUnavailable
from aeat_hub.ocr.render import iter_page_images

ENV_URL = "AEAT_HUB_OLLAMA_URL"
ENV_MODEL = "AEAT_HUB_OLLAMA_OCR_MODEL"
DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "deepseek-ocr"
PROMPT = "<|grounding|>Convert the document to markdown."
MAX_SIDE = 1920
SPECIAL = (
    "<|im_end|>",
    "<|im_start|>",
    "<|endoftext|>",
)


class OllamaOCRProvider:
    """Cliente de Ollama. El nombre del motor refleja el modelo configurado."""

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self.model = (model or os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get(ENV_URL, "").strip() or DEFAULT_URL).rstrip("/")
        self.name = _engine_name(self.model)

    def available(self) -> tuple[bool, str]:
        tags = _list_models(self.base_url)
        if tags is None:
            return False, f"Ollama no responde en {self.base_url} (arranca `ollama serve`)"
        if not _model_present(tags, self.model):
            return False, f"falta el modelo; `ollama pull {self.model}`"
        return True, f"{self.base_url} · {self.model}"

    def transcribe(self, path: Path) -> OCRResult:
        ok, reason = self.available()
        if not ok:
            raise ProviderUnavailable(self.name, reason)
        texts: list[str] = []
        pages = 0
        try:
            for image in iter_page_images(path, dpi=180):
                pages += 1
                with tempfile.NamedTemporaryFile(prefix="aeat_ollama_", suffix=".png", delete=False) as handle:
                    tmp = Path(handle.name)
                try:
                    _fit(image.convert("RGB")).save(tmp, "PNG")
                    texts.append(self._one_image(tmp))
                finally:
                    tmp.unlink(missing_ok=True)
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, str(exc)) from exc
        text = "\n".join(part for part in texts if part).strip()
        if not text:
            raise ProviderUnavailable(self.name, "Ollama devolvió texto vacío")
        conf = 0.8 if len(text) >= 40 else 0.4
        return OCRResult(text=text, engine=self.name, confidence=conf, pages=max(pages, 1))

    def _one_image(self, image: Path) -> str:
        encoded = base64.b64encode(image.read_bytes()).decode("ascii")
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": PROMPT,
                    "images": [encoded],
                }
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(self.name, f"Ollama falló: {exc}") from exc
        text = (body.get("message") or {}).get("content") or ""
        return _clean(str(text))


def _fit(image):
    width, height = image.size
    longest = max(width, height)
    if longest <= MAX_SIDE:
        return image
    scale = MAX_SIDE / longest
    return image.resize((max(int(width * scale), 1), max(int(height * scale), 1)))


def _clean(text: str) -> str:
    cleaned = text
    for token in SPECIAL:
        cleaned = cleaned.replace(token, "\n")
    # El chat template a veces intercala "User"/"assistant" entre palabras.
    lines = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped.lower() in {"user", "assistant", "system"}:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _engine_name(model: str) -> str:
    slug = model.split(":")[0].split("/")[-1]
    if "deepseek" in slug.lower():
        return "deepseek-ocr"
    return f"ollama-{slug}"


def _list_models(base_url: str) -> list[str] | None:
    request = urllib.request.Request(f"{base_url}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    names: list[str] = []
    for item in body.get("models") or []:
        name = item.get("name") or item.get("model") or ""
        if name:
            names.append(str(name))
    return names


def _model_present(tags: list[str], model: str) -> bool:
    wanted = model.lower()
    for tag in tags:
        low = tag.lower()
        if low == wanted or low.startswith(wanted + ":"):
            return True
    return False
