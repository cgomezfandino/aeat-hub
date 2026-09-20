"""Layout del directorio de datos (fuera del repositorio)."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_DATA_DIR = Path("/Volumes/SSDCX9/data/aeat-hub")
ENV_DATA_DIR = "AEAT_HUB_DATA_DIR"


class DataLayout:
    """Carpetas inbox/processed/db/exports bajo un raíz configurable."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.inbox = self.root / "inbox"
        self.processed = self.root / "processed"
        self.rejected = self.root / "rejected"
        self.db_dir = self.root / "db"
        self.db_path = self.db_dir / "ledger.sqlite"
        self.exports = self.root / "exports"
        self.models = self.root / "models"
        self.config_path = self.root / "config.json"

    def ensure(self) -> None:
        for path in (
            self.inbox,
            self.processed,
            self.rejected,
            self.db_dir,
            self.exports,
            self.models,
        ):
            path.mkdir(parents=True, exist_ok=True)

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
