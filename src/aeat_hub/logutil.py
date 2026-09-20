"""Logs de ejecución: consola + fichero en el data-dir (nunca en git)."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from aeat_hub.paths import DataLayout

LOGGER_NAME = "aeat_hub"


def setup_run_log(layout: DataLayout, *, comando: str = "ingest") -> Path:
    """Configura el logger raíz del paquete. Devuelve la ruta del .log de esta corrida."""
    layout.ensure()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = layout.logs / f"{comando}-{stamp}.log"
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(etapa)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_EtapaFilter())

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(_EtapaFilter())

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.info("log de esta corrida: %s", log_path, extra={"etapa": "log"})
    return log_path


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-5s [%(etapa)s] %(message)s",
        )
    return logger


class _EtapaFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "etapa"):
            record.etapa = "-"
        return True
