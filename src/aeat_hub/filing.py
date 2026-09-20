"""Archivo en disco: año / mes / gasto|ingreso|mejora / rubro."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.models import Actividad, Asiento, Documento
from aeat_hub.paths import DataLayout

SLUG_OVERRIDE = {
    "CI.MEJ.MO": "mano-de-obra",
    "CI.MEJ.OTROS": "otras-mejoras",
    "CI.AMO.INMUEBLE": "amortizacion",
    "CI.GAS.REPARACION": "reparacion",
    "CI.GAS.INTERES": "interes",
    "CI.GAS.ADMIN": "administracion",
    "AE.GAS.SS": "seguridad-social",
    "AE.INV.BIENES": "bienes-inversion",
}


def rubro_slug(cuenta_codigo: str | None) -> str:
    if not cuenta_codigo:
        return "sin-cuenta"
    if cuenta_codigo in SLUG_OVERRIDE:
        return SLUG_OVERRIDE[cuenta_codigo]
    return cuenta_codigo.rsplit(".", 1)[-1].lower().replace("_", "-")


def tipo_carpeta(tipo: str | None, estado: str, cuenta_codigo: str | None) -> str:
    if estado == "duplicado":
        return "duplicado"
    if not cuenta_codigo and estado == "pendiente":
        return "pendiente"
    if tipo in {"ingreso", "gasto", "mejora", "amortizacion"}:
        return tipo
    return "gasto"


def archivo_relativo(
    *,
    actividad_codigo: str,
    fecha: date | None,
    tipo: str | None,
    cuenta_codigo: str | None,
    estado: str,
) -> Path:
    year = str(fecha.year) if fecha else "sin_fecha"
    month = f"{fecha.month:02d}" if fecha else "00"
    kind = tipo_carpeta(tipo, estado, cuenta_codigo)
    return Path(actividad_codigo) / year / month / kind / rubro_slug(cuenta_codigo)


def archivo_path(
    layout: DataLayout,
    *,
    actividad_codigo: str,
    fecha: date | None,
    tipo: str | None,
    cuenta_codigo: str | None,
    estado: str,
    sha256: str,
    nombre_original: str,
) -> Path:
    folder = layout.archivo / archivo_relativo(
        actividad_codigo=actividad_codigo,
        fecha=fecha,
        tipo=tipo,
        cuenta_codigo=cuenta_codigo,
        estado=estado,
    )
    return folder / f"{sha256[:12]}_{nombre_original}"


def place_file(src: Path, dest: Path, *, move: bool) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dest.resolve():
        return dest
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}_{src.stat().st_size}{dest.suffix}")
    if move:
        shutil.move(str(src), str(dest))
    else:
        shutil.copy2(src, dest)
    return dest


def prune_empty(start: Path, stop_at: Path) -> None:
    current = start
    stop = stop_at.resolve()
    while current.resolve() != stop and current.is_dir():
        try:
            next(current.iterdir())
            break
        except StopIteration:
            parent = current.parent
            current.rmdir()
            current = parent


def relocate_asiento(
    session: Session,
    layout: DataLayout,
    asiento: Asiento,
    *,
    move: bool = True,
) -> Path | None:
    if not asiento.documento_id:
        return None
    documento = asiento.documento or session.get(Documento, asiento.documento_id)
    if documento is None:
        return None
    actividad = asiento.actividad or session.get(Actividad, asiento.actividad_id)
    if actividad is None:
        return None
    src = Path(documento.ruta_almacenada)
    dest = archivo_path(
        layout,
        actividad_codigo=actividad.codigo,
        fecha=asiento.fecha,
        tipo=asiento.tipo,
        cuenta_codigo=asiento.cuenta_codigo,
        estado=asiento.estado,
        sha256=documento.sha256,
        nombre_original=documento.nombre_original,
    )
    if src.is_file():
        old_parent = src.parent
        dest = place_file(src, dest, move=move)
        if move:
            prune_empty(old_parent, _prune_root(old_parent, layout))
    elif not dest.is_file():
        return None
    documento.ruta_almacenada = str(dest)
    return dest


def _prune_root(path: Path, layout: DataLayout) -> Path:
    resolved = path.resolve()
    for root in (layout.archivo, layout.processed, layout.rejected, layout.inbox):
        try:
            resolved.relative_to(root.resolve())
            return root
        except ValueError:
            continue
    return path


def ordenar_asientos(session: Session, layout: DataLayout, actividad: Actividad) -> int:
    rows = session.scalars(
        select(Asiento).where(
            Asiento.actividad_id == actividad.id,
            Asiento.documento_id.is_not(None),
        )
    ).all()
    moved = 0
    for asiento in rows:
        before = asiento.documento.ruta_almacenada if asiento.documento else None
        dest = relocate_asiento(session, layout, asiento)
        if dest is not None and before and Path(before).resolve() != dest.resolve():
            moved += 1
        elif dest is not None and before is None:
            moved += 1
    return moved
