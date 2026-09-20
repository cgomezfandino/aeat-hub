"""OCR via Vision.framework de macOS. Opcional; no requiere pesos descargados."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import tempfile
from pathlib import Path

from aeat_hub.ocr.base import OCRResult, ProviderUnavailable
from aeat_hub.ocr.render import iter_page_images

_SWIFT_SRC = r"""
import Foundation
import AppKit
import Vision

guard CommandLine.arguments.count >= 2 else {
    fputs("uso: apple-vision-ocr <imagen>\n", stderr)
    exit(2)
}
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: url) else {
    fputs("no se pudo abrir la imagen\n", stderr)
    exit(3)
}
var rect = NSRect(origin: .zero, size: image.size)
guard let cgImage = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
    fputs("no hay CGImage\n", stderr)
    exit(4)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["es-ES", "en-US"]

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("Vision falló: \(error)\n", stderr)
    exit(5)
}
let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
print(lines.joined(separator: "\n"))
"""


class AppleVisionProvider:
    name = "apple-vision"

    def available(self) -> tuple[bool, str]:
        if platform.system() != "Darwin":
            return False, "solo macOS (Vision.framework)"
        if not _swiftc():
            return False, "swiftc no está en PATH"
        return True, "Vision.framework accurate es-ES"

    def transcribe(self, path: Path) -> OCRResult:
        ok, reason = self.available()
        if not ok:
            raise ProviderUnavailable(self.name, reason)
        binary = _ensure_binary()
        texts: list[str] = []
        pages = 0
        try:
            for image in iter_page_images(path, dpi=180):
                pages += 1
                with tempfile.NamedTemporaryFile(prefix="aeat_vis_", suffix=".png", delete=False) as handle:
                    tmp = Path(handle.name)
                try:
                    _fit(image.convert("RGB")).save(tmp, "PNG")
                    texts.append(_run_binary(binary, tmp))
                finally:
                    tmp.unlink(missing_ok=True)
        except ProviderUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailable(self.name, str(exc)) from exc
        text = "\n".join(part for part in texts if part).strip()
        conf = 0.8 if len(text) >= 40 else 0.4 if text else 0.05
        return OCRResult(text=text, engine=self.name, confidence=conf, pages=max(pages, 1))


MAX_SIDE = 2200


def _fit(image):
    width, height = image.size
    longest = max(width, height)
    if longest <= MAX_SIDE:
        return image
    scale = MAX_SIDE / longest
    return image.resize((max(int(width * scale), 1), max(int(height * scale), 1)))


def _swiftc() -> str | None:
    for candidate in ("/usr/bin/swiftc", "swiftc"):
        path = candidate if candidate.startswith("/") else _which(candidate)
        if path and Path(path).is_file():
            return path
    return None


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def _cache_dir() -> Path:
    override = os.environ.get("AEAT_HUB_CACHE_DIR", "").strip()
    if override:
        root = Path(override)
    else:
        root = Path.home() / "Library" / "Caches" / "aeat-hub"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ensure_binary() -> Path:
    digest = hashlib.sha256(_SWIFT_SRC.encode("utf-8")).hexdigest()[:16]
    dest = _cache_dir() / f"apple-vision-ocr-{digest}"
    if dest.is_file() and os.access(dest, os.X_OK):
        return dest
    compiler = _swiftc()
    if not compiler:
        raise ProviderUnavailable("apple-vision", "swiftc no está en PATH")
    with tempfile.TemporaryDirectory(prefix="aeat_swift_") as tmp:
        src = Path(tmp) / "main.swift"
        src.write_text(_SWIFT_SRC, encoding="utf-8")
        compiled = Path(tmp) / "apple-vision-ocr"
        completed = subprocess.run(
            [compiler, "-o", str(compiled), str(src)],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0 or not compiled.is_file():
            detail = (completed.stderr or completed.stdout or "swiftc falló").strip()
            raise ProviderUnavailable("apple-vision", detail[:500])
        dest.write_bytes(compiled.read_bytes())
        dest.chmod(0o755)
    return dest


def _run_binary(binary: Path, image: Path) -> str:
    try:
        completed = subprocess.run(
            [str(binary), str(image)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProviderUnavailable("apple-vision", str(exc)) from exc
    if completed.returncode != 0:
        raise ProviderUnavailable(
            "apple-vision",
            (completed.stderr or completed.stdout or "Vision devolvió error").strip()[:500],
        )
    return (completed.stdout or "").strip()
