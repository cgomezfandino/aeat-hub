"""Lectura del esquema base congelado (`baseline_0001.sql`)."""

from __future__ import annotations

import re
from pathlib import Path

BASELINE = Path(__file__).resolve().parent / "baseline_0001.sql"
_TABLA = re.compile(r"^CREATE (?:UNIQUE )?(?:TABLE|INDEX \w+ ON) (\w+)", re.IGNORECASE)


def statements() -> list[str]:
    sql = "\n".join(
        line for line in BASELINE.read_text(encoding="utf-8").splitlines() if not line.startswith("--")
    )
    return [item.strip() for item in sql.split(";") if item.strip()]


def por_tabla() -> dict[str, list[str]]:
    """CREATE TABLE + sus índices, agrupados por tabla y en orden de dependencias."""
    tablas: dict[str, list[str]] = {}
    for sentencia in statements():
        match = _TABLA.match(sentencia)
        if match:
            tablas.setdefault(match.group(1), []).append(sentencia)
    return tablas
