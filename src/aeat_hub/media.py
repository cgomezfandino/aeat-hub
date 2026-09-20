"""Huellas de fichero y perceptual hash para duplicados de foto."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from aeat_hub.ocr.render import IMAGE_SUFFIXES, HEIC_SUFFIXES, PDF_SUFFIX, iter_page_images

HASH_SIZE = 16


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def average_hash(image: Image.Image, size: int = HASH_SIZE) -> str:
    gray = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pixels = list(gray.tobytes())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= avg else "0" for pixel in pixels)
    width = (size * size) // 4
    return f"{int(bits, 2):0{width}x}"


def hamming_distance(left: str, right: str) -> int:
    if not left or not right or len(left) != len(right):
        return 999
    return (int(left, 16) ^ int(right, 16)).bit_count()


def file_phash(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix not in IMAGE_SUFFIXES | HEIC_SUFFIXES | {PDF_SUFFIX}:
        return None
    try:
        page = next(iter_page_images(path, dpi=72), None)
    except Exception:  # noqa: BLE001
        return None
    if page is None:
        return None
    return average_hash(page)
