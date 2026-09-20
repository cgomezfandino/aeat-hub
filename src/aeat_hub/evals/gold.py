"""Casos de oro para EVALS. El oro real vive fuera de git (data-dir)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field


SCORED_FIELDS = (
    "nif_emisor",
    "nif_receptor",
    "numero",
    "fecha",
    "base",
    "iva_cuota",
    "total",
)


class GoldFields(BaseModel):
    emisor_contains: list[str] = Field(default_factory=list)
    nif_emisor: str | None = None
    nif_receptor: str | None = None
    numero: str | None = None
    fecha: date | None = None
    base: Decimal | None = None
    iva_cuota: Decimal | None = None
    total: Decimal | None = None
    iva_tipo: Decimal | None = None


class GoldCase(BaseModel):
    id: str
    path: Path
    kind: str
    fields: GoldFields
    must_tokens: list[str] = Field(default_factory=list)
    notes: str = ""

    def scored_fields(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        data = self.fields
        for name in SCORED_FIELDS:
            value = getattr(data, name)
            if value is None or value == "":
                continue
            payload[name] = value.isoformat() if isinstance(value, date) else str(value)
        return payload


class GoldSuite(BaseModel):
    version: int = 1
    cases: list[GoldCase] = Field(default_factory=list)


def load_gold(path: Path, *, root: Path | None = None) -> list[GoldCase]:
    suite = GoldSuite.model_validate_json(path.read_text(encoding="utf-8"))
    resolved: list[GoldCase] = []
    for case in suite.cases:
        file_path = case.path
        if not file_path.is_absolute():
            candidates = []
            if root is not None:
                candidates.append((Path(root) / case.path).resolve())
            candidates.append((path.parent / case.path).resolve())
            file_path = next((item for item in candidates if item.is_file()), candidates[0])
        resolved.append(case.model_copy(update={"path": file_path}))
    return resolved


def dump_gold(path: Path, cases: list[GoldCase], *, root: Path | None = None) -> None:
    serializable: list[GoldCase] = []
    for case in cases:
        stored = case.path
        if root is not None:
            try:
                stored = case.path.resolve().relative_to(root.resolve())
            except ValueError:
                stored = case.path
        serializable.append(case.model_copy(update={"path": stored}))
    path.parent.mkdir(parents=True, exist_ok=True)
    suite = GoldSuite(cases=serializable)
    path.write_text(suite.model_dump_json(indent=2) + "\n", encoding="utf-8")
