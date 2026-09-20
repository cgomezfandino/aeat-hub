"""Pipeline de ingest por etapas: si una peta, se registra y no tumba el lote."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from aeat_hub.logutil import get_logger

STAGES = (
    "recibir",
    "hash",
    "duplicado-fichero",
    "ocr",
    "parsear",
    "duplicado-fiscal",
    "clasificar",
    "guardar",
    "archivar",
)


@contextmanager
def etapa(nombre: str, fichero: str) -> Iterator[None]:
    log = get_logger()
    extra = {"etapa": nombre}
    log.info("→ %s", fichero, extra=extra)
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        elapsed = time.perf_counter() - started
        log.exception(
            "✗ PETÓ en '%s' (%.2fs): %s",
            fichero,
            elapsed,
            exc,
            extra=extra,
        )
        raise
    else:
        elapsed = time.perf_counter() - started
        log.info("✓ %s (%.2fs)", fichero, elapsed, extra=extra)


def log_detalle(nombre: str, mensaje: str, *args: object) -> None:
    get_logger().info(mensaje, *args, extra={"etapa": nombre})
