"""CLI local: init, ingest, pendientes, reclasificar, duplicados, export."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from aeat_hub import __version__
from aeat_hub.classify import reclassify
from aeat_hub.db import make_engine, session_factory, session_scope
from aeat_hub.export import export_xlsx
from aeat_hub.fiscal.accounts import REGIMEN_AE, REGIMEN_CI
from aeat_hub.ingest import ingest_file, ingest_inbox
from aeat_hub.models import Actividad, Asiento, Cuenta
from aeat_hub.ocr.unlimited import UnlimitedOCRProvider
from aeat_hub.ocr.paddle_vl import PaddleVLProvider
from aeat_hub.paths import DataLayout, resolve_layout
from aeat_hub.services import (
    alta_actividad,
    get_actividad,
    get_cuenta,
    initialize,
    require_layout,
)

app = typer.Typer(
    no_args_is_help=True,
    help="AEAT Hub — libros locales de ingresos y gastos (no es software oficial de la AEAT).",
)
actividad_app = typer.Typer(no_args_is_help=True, help="Expedientes / razones sociales.")
app.add_typer(actividad_app, name="actividad")
console = Console()


def _layout(data_dir: Optional[Path]) -> DataLayout:
    return resolve_layout(data_dir)


def _session_factory(layout: DataLayout):
    require_layout(layout)
    return session_factory(make_engine(layout))


@app.callback()
def _version_callback(
    version: bool = typer.Option(False, "--version", help="Muestra la versión y sale."),
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()


@app.command()
def init(
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
    titular: str = typer.Option("Titular local", "--titular"),
    nif: str = typer.Option("00000000T", "--nif", help="NIF del titular. 00000000T es un marcador."),
) -> None:
    """Crea carpetas, SQLite, plan de cuentas y el expediente Alquiler Valladolid."""
    layout = _layout(data_dir)
    initialize(layout, titular_nombre=titular, titular_nif=nif)
    console.print(f"Libro inicializado en [bold]{layout.root}[/bold]")
    console.print(f"Inbox: {layout.inbox}")
    console.print("Actividad semilla: CI-VA-001 · Alquiler Valladolid (capital inmobiliario)")
    if nif == "00000000T":
        console.print("[yellow]NIF marcador. Cámbialo cuando configures el titular real (solo en el data-dir).[/yellow]")


@actividad_app.command("alta")
def actividad_alta(
    nombre: str = typer.Option(..., "--nombre"),
    regimen: str = typer.Option(..., "--regimen", help=f"{REGIMEN_CI} | {REGIMEN_AE}"),
    codigo: Optional[str] = typer.Option(None, "--codigo"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Da de alta un expediente (alquiler o actividad económica)."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        actividad = alta_actividad(session, nombre=nombre, regimen=regimen, codigo=codigo)
        console.print(f"Creada {actividad.codigo} · {actividad.nombre} · {actividad.regimen}")


@actividad_app.command("listar")
def actividad_listar(
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with factory() as session:
        rows = session.scalars(select(Actividad).order_by(Actividad.codigo)).all()
        table = Table(title="Actividades")
        table.add_column("codigo")
        table.add_column("nombre")
        table.add_column("regimen")
        for row in rows:
            table.add_row(row.codigo, row.nombre, row.regimen)
        console.print(table)


@app.command()
def cuentas(
    regimen: Optional[str] = typer.Option(None, "--regimen"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Lista el plan de cuentas."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with factory() as session:
        query = select(Cuenta).order_by(Cuenta.codigo)
        if regimen:
            query = query.where(Cuenta.regimen == regimen)
        table = Table(title="Cuentas")
        table.add_column("codigo")
        table.add_column("tipo")
        table.add_column("regimen")
        table.add_column("nombre")
        for row in session.scalars(query):
            table.add_row(row.codigo, row.tipo, row.regimen, row.nombre)
        console.print(table)


@app.command()
def ingest(
    actividad: str = typer.Option(..., "--actividad", help="Código de expediente, p.ej. CI-VA-001"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
    ocr: str = typer.Option("auto", "--ocr", help="auto|native|rapid|unlimited|paddle"),
    path: Optional[Path] = typer.Option(None, "--path", help="Un fichero concreto (si no, el inbox)"),
) -> None:
    """Lee PDF/fotos, extrae, deduplica y clasifica."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        act = get_actividad(session, actividad)
        if path:
            items = [
                ingest_file(
                    session,
                    layout,
                    path,
                    act,
                    ocr_prefer=ocr,
                    from_inbox=path.parent.resolve() == layout.inbox.resolve(),
                )
            ]
        else:
            items = ingest_inbox(session, layout, act, ocr_prefer=ocr)
        if not items:
            console.print(f"Inbox vacío: {layout.inbox}")
            return
        table = Table(title=f"Ingest {act.codigo}")
        table.add_column("asiento")
        table.add_column("estado")
        table.add_column("detalle")
        table.add_column("avisos")
        for item in items:
            table.add_row(
                str(item.asiento_id or "—"),
                item.estado,
                item.detalle,
                "; ".join(item.warnings) if item.warnings else "",
            )
        console.print(table)


@app.command()
def pendientes(
    actividad: str = typer.Option(..., "--actividad"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Asientos que hay que revisar o reclasificar."""
    _print_asientos(data_dir, actividad, estados=("pendiente",))


@app.command()
def duplicados(
    actividad: str = typer.Option(..., "--actividad"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Muestra duplicados de fichero, fiscales y sospechosos."""
    _print_asientos(data_dir, actividad, estados=("duplicado",))


@app.command()
def reclasificar(
    asiento_id: int = typer.Argument(..., help="Id del asiento"),
    cuenta: str = typer.Argument(..., help="Código de cuenta, p.ej. CI.MEJ.PVC"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
    solo_este: bool = typer.Option(False, "--solo-este", help="No aplicar a pendientes del mismo NIF"),
) -> None:
    """Cambia la cuenta y enseña al sistema (regla por NIF emisor)."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        asiento = session.get(Asiento, asiento_id)
        if asiento is None:
            raise typer.BadParameter(f"No existe el asiento {asiento_id}")
        dest = get_cuenta(session, cuenta)
        n = reclassify(session, asiento, dest, aplicar_similares=not solo_este)
        console.print(
            f"Asiento {asiento.id} → {dest.codigo} ({dest.nombre}). "
            f"Regla aprendida. Actualizados: {n}."
        )


@app.command("export")
def export_cmd(
    actividad: str = typer.Option(..., "--actividad"),
    year: int = typer.Option(..., "--year"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
    xlsx: bool = typer.Option(True, "--xlsx/--no-xlsx"),
) -> None:
    """Exporta el libro Excel del ejercicio (no es el maestro; el maestro es SQLite)."""
    if not xlsx:
        raise typer.BadParameter("De momento solo hay exportador XLSX.")
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        act = get_actividad(session, actividad)
        dest = export_xlsx(session, layout, act, year)
        console.print(f"Escrito {dest}")


@app.command("ocr-status")
def ocr_status() -> None:
    """Muestra qué motores OCR opcionales están disponibles en esta máquina."""
    unlimited = UnlimitedOCRProvider()
    paddle = PaddleVLProvider()
    ok_u, reason_u = unlimited.available()
    ok_p, reason_p = paddle.available()
    console.print("Cascada por defecto: PDF nativo → RapidOCR (ONNX)")
    console.print(f"Unlimited-OCR: {'sí' if ok_u else 'no'} — {reason_u}")
    console.print(f"PaddleOCR-VL: {'sí' if ok_p else 'no'} — {reason_p}")
    console.print(
        "En Mac M1 16 GB Unlimited-OCR no es el default: requiere CUDA oficial "
        "o GGUF experimental. Úsalo con --ocr unlimited si lo tienes levantado."
    )


def _print_asientos(data_dir: Optional[Path], actividad: str, estados: tuple[str, ...]) -> None:
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with factory() as session:
        act = get_actividad(session, actividad)
        rows = session.scalars(
            select(Asiento)
            .where(Asiento.actividad_id == act.id, Asiento.estado.in_(estados))
            .order_by(Asiento.fecha, Asiento.id)
        ).all()
        table = Table(title=f"{act.codigo} · {', '.join(estados)}")
        for col in ("id", "fecha", "emisor", "nif", "numero", "total", "cuenta", "estado"):
            table.add_column(col)
        for row in rows:
            table.add_row(
                str(row.id),
                row.fecha.isoformat() if row.fecha else "",
                (row.emisor or "")[:32],
                row.nif_emisor or "",
                row.numero_factura or "",
                str(row.total) if row.total is not None else "",
                row.cuenta_codigo or "",
                row.estado,
            )
        if not rows:
            console.print("No hay asientos en este estado.")
            return
        console.print(table)
