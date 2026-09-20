"""Exportación de libros Excel por ejercicio."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.models import Actividad, Asiento, Inmueble
from aeat_hub.paths import DataLayout

SHEET_COLUMNS = [
    "id",
    "fecha",
    "ejercicio",
    "actividad",
    "inmueble",
    "tipo",
    "cuenta",
    "emisor",
    "nif_emisor",
    "numero",
    "descripcion",
    "base",
    "iva_tipo",
    "iva_cuota",
    "total",
    "estado",
    "origen",
    "duplicado_nivel",
    "duplicado_de",
]


def export_xlsx(
    session: Session,
    layout: DataLayout,
    actividad: Actividad,
    year: int,
) -> Path:
    rows = session.scalars(
        select(Asiento)
        .where(Asiento.actividad_id == actividad.id, Asiento.ejercicio == year)
        .order_by(Asiento.fecha, Asiento.id)
    ).all()
    inmuebles = {
        item.id: item.alias
        for item in session.scalars(select(Inmueble).where(Inmueble.actividad_id == actividad.id))
    }
    wb = Workbook()
    _write_sheet(wb.active, "Gastos", [r for r in rows if r.tipo == "gasto"], actividad, inmuebles)
    _write_sheet(wb.create_sheet("Ingresos"), "Ingresos", [r for r in rows if r.tipo == "ingreso"], actividad, inmuebles)
    _write_sheet(wb.create_sheet("Mejoras"), "Mejoras", [r for r in rows if r.tipo == "mejora"], actividad, inmuebles)
    _write_sheet(
        wb.create_sheet("Duplicados"),
        "Duplicados",
        [r for r in rows if r.estado == "duplicado"],
        actividad,
        inmuebles,
    )
    _write_sheet(
        wb.create_sheet("Reclasificar"),
        "Reclasificar",
        [r for r in rows if r.estado == "pendiente"],
        actividad,
        inmuebles,
    )
    _write_summary_rubro(wb.create_sheet("Resumen_rubro"), rows)
    _write_summary_inmueble(wb.create_sheet("Resumen_inmueble"), rows, inmuebles)

    layout.exports.mkdir(parents=True, exist_ok=True)
    dest = layout.exports / f"libro_{actividad.codigo}_{year}.xlsx"
    wb.save(dest)
    return dest


def _as_row(asiento: Asiento, actividad: Actividad, inmuebles: dict[int, str]) -> list[object]:
    return [
        asiento.id,
        asiento.fecha.isoformat() if asiento.fecha else "",
        asiento.ejercicio,
        actividad.codigo,
        inmuebles.get(asiento.inmueble_id or 0, ""),
        asiento.tipo,
        asiento.cuenta_codigo or "",
        asiento.emisor or "",
        asiento.nif_emisor or "",
        asiento.numero_factura or "",
        asiento.descripcion,
        _num(asiento.base),
        _num(asiento.iva_tipo),
        _num(asiento.iva_cuota),
        _num(asiento.total),
        asiento.estado,
        asiento.origen_clasificacion,
        asiento.duplicado_nivel,
        asiento.duplicado_de_id,
    ]


def _write_sheet(
    ws,
    title: str,
    rows: list[Asiento],
    actividad: Actividad,
    inmuebles: dict[int, str],
) -> None:
    ws.title = title
    ws.append(SHEET_COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for asiento in rows:
        ws.append(_as_row(asiento, actividad, inmuebles))
    _autosize(ws)


def _write_summary_rubro(ws, rows: list[Asiento]) -> None:
    ws.title = "Resumen_rubro"
    ws.append(["cuenta", "tipo", "n_asientos", "base", "iva", "total"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    buckets: dict[tuple[str, str], dict[str, Decimal | int]] = defaultdict(
        lambda: {"n": 0, "base": Decimal("0"), "iva": Decimal("0"), "total": Decimal("0")}
    )
    for asiento in rows:
        if asiento.estado == "duplicado":
            continue
        key = (asiento.cuenta_codigo or "(sin cuenta)", asiento.tipo)
        buckets[key]["n"] += 1
        buckets[key]["base"] += asiento.base or Decimal("0")
        buckets[key]["iva"] += asiento.iva_cuota or Decimal("0")
        buckets[key]["total"] += asiento.total or Decimal("0")
    for (cuenta, tipo), agg in sorted(buckets.items()):
        ws.append([cuenta, tipo, agg["n"], float(agg["base"]), float(agg["iva"]), float(agg["total"])])
    _autosize(ws)


def _write_summary_inmueble(ws, rows: list[Asiento], inmuebles: dict[int, str]) -> None:
    ws.title = "Resumen_inmueble"
    ws.append(["inmueble", "tipo", "total"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    buckets: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for asiento in rows:
        if asiento.estado == "duplicado":
            continue
        alias = inmuebles.get(asiento.inmueble_id or 0, "(sin inmueble)")
        buckets[(alias, asiento.tipo)] += asiento.total or Decimal("0")
    for (alias, tipo), total in sorted(buckets.items()):
        ws.append([alias, tipo, float(total)])
    _autosize(ws)


def _num(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _autosize(ws) -> None:
    for idx, column in enumerate(ws.columns, start=1):
        width = max((len(str(cell.value or "")) for cell in column), default=8)
        ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 10), 40)
