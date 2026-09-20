"""Layout del directorio de datos (fuera del repositorio)."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_DATA_DIR = Path("/Volumes/SSDCX9/data/aeat-hub")
ENV_DATA_DIR = "AEAT_HUB_DATA_DIR"


class DataLayout:
    """Carpetas inbox/archivo/db/exports bajo un raíz configurable."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.inbox = self.root / "inbox"
        self.archivo = self.root / "archivo"
        self.processed = self.root / "processed"
        self.rejected = self.root / "rejected"
        self.db_dir = self.root / "db"
        self.db_path = self.db_dir / "ledger.sqlite"
        self.exports = self.root / "exports"
        self.models = self.root / "models"
        self.logs = self.root / "logs"
        self.evals = self.root / "evals"
        self.config_path = self.root / "config.json"

    def ensure(self) -> None:
        for path in (
            self.inbox,
            self.archivo,
            self.processed,
            self.rejected,
            self.db_dir,
            self.exports,
            self.models,
            self.logs,
            self.evals,
        ):
            path.mkdir(parents=True, exist_ok=True)
        readme = self.inbox / "DEJAR_AQUI.txt"
        if not readme.exists():
            readme.write_text(
                "Deja aquí PDF, JPG, PNG, WEBP o HEIC.\n"
                "Luego: aeat-hub ingest --actividad CI-VA-001\n"
                "El sistema los ordena en ../archivo/<expediente>/<año>/<mes>/"
                "<gasto|ingreso|mejora>/<rubro>/\n",
                encoding="utf-8",
            )

    def is_initialized(self) -> bool:
        return self.db_path.is_file()

    def write_config(self, extra: dict | None = None) -> None:
        payload = {"data_dir": str(self.root), **(extra or {})}
        self.config_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def resolve_layout(data_dir: Path | str | None = None) -> DataLayout:
    if data_dir:
        return DataLayout(Path(data_dir))
    env = os.environ.get(ENV_DATA_DIR)
    if env:
        return DataLayout(Path(env))
    return DataLayout(DEFAULT_DATA_DIR)
