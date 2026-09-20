"""Render de PDF/fotos a imágenes PIL para OCR y perceptual hash."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from PIL import Image

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
HEIC_SUFFIXES = {".heic", ".heif"}
PDF_SUFFIX = ".pdf"


def iter_page_images(path: Path, dpi: int = 200) -> Iterator[Image.Image]:
    suffix = path.suffix.lower()
    if suffix == PDF_SUFFIX:
        yield from _pdf_pages(path, dpi=dpi)
        return
    yield open_image(path)


def open_image(path: Path) -> Image.Image:
    suffix = path.suffix.lower()
    if suffix in HEIC_SUFFIXES:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except ImportError as exc:
            raise RuntimeError(
                "Esta foto es HEIC. Instala el extra: uv sync --extra heic"
            ) from exc
    image = Image.open(path)
    return image.convert("RGB")


def _pdf_pages(path: Path, dpi: int) -> Iterator[Image.Image]:
    import pymupdf

    zoom = dpi / 72
    matrix = pymupdf.Matrix(zoom, zoom)
    doc = pymupdf.open(path)
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
