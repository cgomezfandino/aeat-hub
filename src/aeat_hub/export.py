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

from aeat_hub.fiscal.irpf import summarize_irpf
from aeat_hub.fiscal.accounts import REGIMEN_CI
from aeat_hub.models import Actividad, Asiento, Inmueble
from aeat_hub.paths import DataLayout

SHEET_COLUMNS = [
    ("fecha", "Fecha compra"),
    ("emisor", "Emisor"),
    ("nif_emisor", "NIF emisor"),
    ("numero", "Nº factura"),
    ("descripcion", "Descripción"),
    ("base", "Base"),
    ("iva_tipo", "IVA %"),
    ("iva_cuota", "Cuota IVA"),
    ("total", "Total"),
    ("cuenta", "Rubro / cuenta"),
    ("tipo", "Tipo"),
    ("estado", "Estado"),
    ("inmueble", "Inmueble"),
    ("actividad", "Expediente"),
    ("id", "Id asiento"),
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
    if actividad.regimen == REGIMEN_CI:
        _write_casillas_irpf(wb.create_sheet("Casillas_IRPF"), rows, year)

    layout.exports.mkdir(parents=True, exist_ok=True)
    dest = layout.exports / f"libro_{actividad.codigo}_{year}.xlsx"
    wb.save(dest)
    return dest


def _as_row(asiento: Asiento, actividad: Actividad, inmuebles: dict[int, str]) -> dict[str, object]:
    return {
        "id": asiento.id,
        "fecha": asiento.fecha.isoformat() if asiento.fecha else "",
        "emisor": asiento.emisor or "",
        "nif_emisor": asiento.nif_emisor or "",
        "numero": asiento.numero_factura or "",
        "descripcion": asiento.descripcion,
        "base": _num(asiento.base),
        "iva_tipo": _num(asiento.iva_tipo),
        "iva_cuota": _num(asiento.iva_cuota),
        "total": _num(asiento.total),
        "cuenta": asiento.cuenta_codigo or "",
        "tipo": asiento.tipo,
        "estado": asiento.estado,
        "inmueble": inmuebles.get(asiento.inmueble_id or 0, ""),
        "actividad": actividad.codigo,
    }


def _write_sheet(
    ws,
    title: str,
    rows: list[Asiento],
    actividad: Actividad,
    inmuebles: dict[int, str],
) -> None:
    ws.title = title
    ws.append([label for _key, label in SHEET_COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for asiento in rows:
        payload = _as_row(asiento, actividad, inmuebles)
        ws.append([payload[key] for key, _label in SHEET_COLUMNS])
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


def _write_casillas_irpf(ws, rows: list[Asiento], year: int) -> None:
    ws.title = "Casillas_IRPF"
    summary = summarize_irpf(rows)
    ws.append(["Borrador IRPF · rendimientos de capital inmobiliario", year])
    ws.append(
        [
            "No presenta el modelo 100. Copia estos totales al anexo del inmueble en la Renta.",
        ]
    )
    ws.append([])
    ws.append(["Concepto", "Asientos", "Importe", "Resta del año", "Nota"])
    for cell in ws[4]:
        cell.font = Font(bold=True)
    for item in summary["filas"]:
        if item["n"] == 0 and item["clave"] not in {"ingresos", "mejoras"}:
            continue
        ws.append(
            [
                item["etiqueta"],
                item["n"],
                float(item["total"]),
                "Sí" if item["resta_del_ano"] else "No",
                item["notas"],
            ]
        )
    ws.append([])
    ws.append(["Ingresos íntegros", float(summary["ingresos"])])
    ws.append(["Gastos deducibles (incl. amortización)", float(summary["gastos_deducibles"])])
    ws.append(["Rendimiento neto", float(summary["rendimiento"])])
    ws.append(["Mejoras (no restan del ejercicio)", float(summary["mejoras"])])
    _autosize(ws)


def _num(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _autosize(ws) -> None:
    for idx, column in enumerate(ws.columns, start=1):
        width = max((len(str(cell.value or "")) for cell in column), default=8)
        ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 10), 40)
