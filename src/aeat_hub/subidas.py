"""Nombres de fichero subidos por el navegador: nunca deciden dónde se escribe."""

from __future__ import annotations

from pathlib import Path

TAMANO_MAXIMO = 25 * 1024 * 1024  # 25 MB: un PDF de factura escaneada cabe sobrado


def nombre_seguro(raw: str) -> str | None:
    """Solo el nombre (sin rutas) y solo extensiones que el ingest sabe leer."""
    from aeat_hub.ingest import INGEST_SUFFIXES

    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."} or name.startswith("."):
        return None
    if Path(name).suffix.lower() not in INGEST_SUFFIXES:
        return None
    return name


def destino_libre(carpeta: Path, nombre: str) -> Path:
    """Ruta dentro de `carpeta` que no pisa otro fichero."""
    raiz = carpeta.resolve()
    destino = raiz / nombre
    stem, suffix = Path(nombre).stem, Path(nombre).suffix
    contador = 1
    while destino.exists():
        destino = raiz / f"{stem}_{contador}{suffix}"
        contador += 1
    if destino.resolve().parent != raiz:
        raise ValueError("Ruta de subida no válida.")
    return destino
