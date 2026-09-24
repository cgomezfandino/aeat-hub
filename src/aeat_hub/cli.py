"""CLI local: init, ingest, pendientes, reclasificar, duplicados, dashboard."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from aeat_hub import __version__
from aeat_hub.classify import reabrir_asiento, reclassify, validar_asiento
from aeat_hub.db import make_engine, session_factory, session_scope
from aeat_hub.edits import AsientoNoEncontrado, desmarcar_duplicado, marcar_duplicado
from aeat_hub.evals.gold import load_gold
from aeat_hub.evals.runner import ENGINE_ORDER, list_engine_status, run_eval
from aeat_hub.evals.suite import gold_path, load_suite
from aeat_hub.er import CorreccionNumero, corregir_numero
from aeat_hub.dashboard import write_dashboard
from aeat_hub.export import export_xlsx
from aeat_hub.export_dual import write_dual_xlsx
from aeat_hub.filing import ordenar_asientos
from aeat_hub.fiscal.accounts import REGIMEN_AE, REGIMEN_CI
from aeat_hub.ingest import ingest_file, ingest_inbox, list_inbox, reparse_asientos
from aeat_hub.logutil import setup_run_log
from aeat_hub.models import Actividad, Asiento, Cuenta
from aeat_hub.ocr.cascade import describe_auto
from aeat_hub.ocr.dual import run_dual
from aeat_hub.paths import DataLayout, resolve_layout
from aeat_hub.services import (
    alta_actividad,
    alta_cuenta,
    get_actividad,
    get_cuenta_por_nombre,
    initialize,
    patch_expediente,
    require_layout,
)

app = typer.Typer(
    no_args_is_help=True,
    help="AEAT Hub — libros locales de ingresos y gastos (no es software oficial de la AEAT).",
)
actividad_app = typer.Typer(no_args_is_help=True, help="Expedientes / razones sociales.")
app.add_typer(actividad_app, name="actividad")
cuenta_app = typer.Typer(no_args_is_help=True, help="Plan de cuentas / rubros.")
app.add_typer(cuenta_app, name="cuenta")
factura_app = typer.Typer(no_args_is_help=True, help="Factura canónica (número y agrupación).")
app.add_typer(factura_app, name="factura")
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
    console.print(f"Inbox (deja aquí las facturas): {layout.inbox}")
    console.print(f"Archivo ordenado: {layout.archivo}/<expediente>/<año>/<mes>/<gasto|ingreso|mejora>/<rubro>/")
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


@actividad_app.command("titulo")
def actividad_titulo(
    actividad: str = typer.Option(..., "--actividad"),
    nombre: Optional[str] = typer.Option(None, "--nombre", help="Título del expediente (cabecera del libro)"),
    titular: Optional[str] = typer.Option(None, "--titular", help="Nombre del titular"),
    inmueble: Optional[str] = typer.Option(None, "--inmueble", help="Alias del inmueble"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Personaliza los títulos del libro: expediente, titular e inmueble."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    payload: dict = {}
    if nombre is not None:
        payload["nombre"] = nombre
    if titular is not None:
        payload["titular"] = titular
    if inmueble is not None:
        payload["inmueble"] = inmueble
    try:
        with session_scope(factory) as session:
            data = patch_expediente(session, actividad, payload)
    except RuntimeError as err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(1) from err
    bits = [f"{data['codigo']} · {data['nombre']}"]
    if data["titular"]:
        bits.append(data["titular"])
    if data["inmueble"]:
        bits.append(data["inmueble"])
    console.print(" · ".join(bits))
    console.print("Regenera el libro: aeat-hub dashboard --actividad … --year …")


@cuenta_app.command("alta")
def cuenta_alta(
    nombre: str = typer.Option(..., "--nombre"),
    casilla: str = typer.Option(..., "--casilla"),
    regimen: str = typer.Option(REGIMEN_CI, "--regimen"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Crea un rubro propio. Hay que decir a qué casilla de la Renta suma."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        try:
            cuenta = alta_cuenta(session, nombre=nombre, casilla=casilla, regimen=regimen)
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        console.print(f"Creada {cuenta.nombre} · {cuenta.casilla} · {cuenta.tipo}")


@app.command()
def cuentas(
    regimen: Optional[str] = typer.Option(None, "--regimen"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Lista el plan de cuentas."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with factory() as session:
        query = select(Cuenta).order_by(Cuenta.nombre)
        if regimen:
            query = query.where(Cuenta.regimen == regimen)
        table = Table(title="Cuentas")
        table.add_column("nombre")
        table.add_column("tipo")
        table.add_column("casilla")
        table.add_column("origen")
        for row in session.scalars(query):
            origen = "sistema" if row.sistema else "usuario"
            table.add_row(row.nombre, row.tipo, row.casilla, origen)
        console.print(table)


@app.command()
def ingest(
    actividad: str = typer.Option(..., "--actividad", help="Código de expediente, p.ej. CI-VA-001"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
    ocr: str = typer.Option(
        "auto",
        "--ocr",
        help="auto|native|rapid|vision|deepseek|unlimited|paddle|tesseract",
    ),
    path: Optional[Path] = typer.Option(None, "--path", help="Un fichero concreto (si no, el inbox)"),
) -> None:
    """Lee PDF/fotos, extrae, deduplica y clasifica. Escribe un log por corrida."""
    layout = _layout(data_dir)
    log_path = setup_run_log(layout, comando="ingest")
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        act = get_actividad(session, actividad)
        if path:
            try:
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
            except Exception as exc:
                console.print(f"[red]PETÓ[/red] {path.name}: {exc}")
                console.print(f"Log: {log_path}")
                raise typer.Exit(1) from exc
        else:
            items = ingest_inbox(session, layout, act, ocr_prefer=ocr)
        if not items:
            console.print(f"Inbox vacío: {layout.inbox}")
            console.print(f"Log: {log_path}")
            return
        table = Table(title=f"Ingest {act.codigo}")
        table.add_column("fichero")
        table.add_column("asiento")
        table.add_column("estado")
        table.add_column("detalle")
        table.add_column("avisos")
        errors = 0
        for item in items:
            if item.estado == "error":
                errors += 1
            table.add_row(
                item.path.name,
                str(item.asiento_id or "—"),
                item.estado,
                item.detalle,
                "; ".join(item.warnings) if item.warnings else "",
            )
        console.print(table)
        console.print(f"Log: {log_path}")
        if errors:
            console.print(
                f"[red]{errors} fichero(s) petaron.[/red] "
                f"Quedan en {layout.rejected / 'error'} — el resto del lote sí se procesó."
            )
            raise typer.Exit(1)


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
    rubro: str = typer.Argument(..., help="Nombre del rubro, p.ej. Hogar"),
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
        actividad = session.get(Actividad, asiento.actividad_id)
        if actividad is None:
            raise typer.BadParameter(f"No existe la actividad del asiento {asiento_id}")
        try:
            dest = get_cuenta_por_nombre(session, rubro, regimen=actividad.regimen)
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        n = reclassify(session, asiento, dest, aplicar_similares=not solo_este, layout=layout)
        console.print(
            f"Asiento {asiento.id} → {dest.nombre}. "
            f"Validado. Regla aprendida. Actualizados: {n}. Fichero reubicado en el archivo."
        )


@app.command()
def validar(
    asiento_id: int = typer.Argument(..., help="Id del asiento"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Marca el asiento como revisado por ti. El OCR/parser no lo volverá a pisar."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        asiento = session.get(Asiento, asiento_id)
        if asiento is None:
            raise typer.BadParameter(f"No existe el asiento {asiento_id}")
        nombres = {c.codigo: c.nombre for c in session.scalars(select(Cuenta)).all()}
        validar_asiento(asiento)
        rubro = nombres.get(asiento.cuenta_codigo) or "sin cuenta"
        console.print(
            f"Asiento {asiento.id} validado. Rubro {rubro}. "
            "reparse e ingest no tocan este apunte."
        )


@app.command()
def reabrir(
    asiento_id: int = typer.Argument(..., help="Id del asiento"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Devuelve un asiento validado a revisión (por si Validar fue un error)."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        asiento = session.get(Asiento, asiento_id)
        if asiento is None:
            raise typer.BadParameter(f"No existe el asiento {asiento_id}")
        reabrir_asiento(asiento)
        console.print(
            f"Asiento {asiento.id} otra vez pendiente. "
            "Revisa el documento y vuelve a validar cuando encaje."
        )


@factura_app.command("numero")
def factura_numero(
    asiento_id: int = typer.Argument(..., help="Id del asiento"),
    numero: str = typer.Argument(..., help="Número visible, p.ej. F2026-000123"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Corrige el número de factura y vuelve a agrupar por emisor + ID."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        asiento = session.get(Asiento, asiento_id)
        if asiento is None:
            raise typer.BadParameter(f"No existe el asiento {asiento_id}")
        try:
            resultado = corregir_numero(session, asiento, numero)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        _print_correccion(resultado)


def _print_correccion(resultado: CorreccionNumero) -> None:
    if resultado.unido_a is not None:
        console.print(
            f"Asiento {resultado.asiento.id} unido al asiento {resultado.unido_a.id}. "
            f"Número {resultado.numero}."
        )
        return
    if resultado.conflicto_con is not None:
        console.print(
            f"Asiento {resultado.asiento.id} → {resultado.numero}. "
            f"Conflicto con asiento {resultado.conflicto_con.id} (mismo número, total distinto)."
        )
        return
    console.print(f"Asiento {resultado.asiento.id} → número {resultado.numero}.")


@app.command()
def duplicado(
    asiento_id: int = typer.Argument(..., help="Id del asiento duplicado"),
    de_asiento: Optional[int] = typer.Argument(
        None, help="Id del asiento bueno. Solo si no usas --quitar"
    ),
    quitar: bool = typer.Option(False, "--quitar", help="Desmarca el duplicado"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Marca un asiento como duplicado de otro (fusión manual) o lo desmarca."""
    if not quitar and de_asiento is None:
        raise typer.BadParameter("Indica el asiento bueno: aeat-hub duplicado 8 7")
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        asiento = session.get(Asiento, asiento_id)
        if asiento is None:
            raise typer.BadParameter(f"No existe el asiento {asiento_id}")
        try:
            if quitar:
                desmarcar_duplicado(session, asiento_id)
                console.print(f"Asiento {asiento_id} vuelve a estar pendiente de revisión.")
            else:
                assert de_asiento is not None
                marcar_duplicado(session, asiento_id, de_asiento)
                console.print(
                    f"Asiento {asiento_id} marcado duplicado del asiento {de_asiento}. "
                    "Fuera de los totales; corre `aeat-hub ordenar` para reubicar el fichero."
                )
        except (ValueError, AsientoNoEncontrado) as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        actividad = session.get(Actividad, asiento.actividad_id)
        if actividad is not None:
            n = ordenar_asientos(session, layout, actividad)
            if n:
                console.print(f"Reubicados {n} documentos.")


@app.command()
def ordenar(
    actividad: str = typer.Option(..., "--actividad"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Reordena en disco los documentos ya ingeridos: año/mes/tipo/rubro."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        act = get_actividad(session, actividad)
        n = ordenar_asientos(session, layout, act)
        console.print(f"Reubicados {n} documentos bajo {layout.archivo / act.codigo}")


@app.command()
def dashboard(
    actividad: str = typer.Option(..., "--actividad"),
    year: int = typer.Option(..., "--year"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Abre el HTML en el navegador"),
    serve: bool = typer.Option(
        True,
        "--serve/--no-serve",
        help="Sirve el HTML, los documentos y las correcciones en 127.0.0.1",
    ),
    port: int = typer.Option(8765, "--port", help="Puerto del servidor local"),
    reparse: bool = typer.Option(
        False, "--reparse", help="Relee el OCR guardado y actualiza emisor/fecha/importes antes de generar"
    ),
) -> None:
    """Genera el dashboard y, por defecto, lo sirve en local para abrir PDFs y editar asientos."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        act = get_actividad(session, actividad)
        if reparse:
            n = reparse_asientos(session, act)
            console.print(f"Releídos {n} asientos desde el texto OCR guardado.")
        dest = write_dashboard(session, layout, act, year)
        console.print(f"Escrito {dest}")
    if serve:
        from aeat_hub.hub_http import bind_server

        httpd, actual = bind_server(layout, factory, dest.name, port=port)
        url = f"http://127.0.0.1:{actual}/{dest.name}"
        console.print(f"Servidor local {url}  (Ctrl+C para salir)")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            console.print("Servidor detenido.")
            httpd.shutdown()
        return
    if open_browser:
        webbrowser.open(dest.as_uri())


@app.command("export")
def export_cmd(
    actividad: str = typer.Option(..., "--actividad"),
    year: int = typer.Option(..., "--year"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
    xlsx: bool = typer.Option(True, "--xlsx/--no-xlsx"),
    reparse: bool = typer.Option(
        False, "--reparse", help="Relee el OCR guardado y actualiza emisor/fecha/importes antes de exportar"
    ),
) -> None:
    """Exporta un Excel opcional del ejercicio. El maestro es SQLite; la vista habitual es `dashboard`."""
    if not xlsx:
        raise typer.BadParameter("De momento solo hay exportador XLSX.")
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        act = get_actividad(session, actividad)
        if reparse:
            n = reparse_asientos(session, act)
            console.print(f"Releídos {n} asientos desde el texto OCR guardado.")
        dest = export_xlsx(session, layout, act, year)
        console.print(f"Escrito {dest}")


@app.command("reparse")
def reparse_cmd(
    actividad: str = typer.Option(..., "--actividad"),
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
) -> None:
    """Actualiza emisor, fecha, número e importes desde el OCR ya guardado. No vuelve a leer las fotos."""
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with session_scope(factory) as session:
        act = get_actividad(session, actividad)
        n = reparse_asientos(session, act)
        console.print(f"Actualizados {n} asientos en SQLite. Luego: aeat-hub dashboard --actividad {act.codigo} --year …")


@app.command("dual")
def dual_cmd(
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
    path: Optional[Path] = typer.Option(None, "--path", help="Un PDF/foto concreto"),
    inbox: bool = typer.Option(False, "--inbox", help="Usa el inbox en vez del set de oro"),
) -> None:
    """Audita Vision vs RapidOCR. Escribe un Excel de discrepancias. No toca SQLite."""
    layout = _layout(data_dir)
    layout.ensure()
    log_path = setup_run_log(layout, comando="dual")
    targets = _dual_targets(layout, path=path, from_inbox=inbox)
    if not targets:
        console.print(
            "[red]No hay ficheros.[/red] Pasa --path, --inbox, o anota casos en "
            f"{gold_path(layout)}"
        )
        console.print(f"Log: {log_path}")
        raise typer.Exit(1)
    docs = []
    table = Table(title="Dual Vision vs RapidOCR")
    table.add_column("caso")
    table.add_column("recomendacion")
    table.add_column("acuerdos")
    table.add_column("conflictos")
    table.add_column("nif")
    table.add_column("total")
    for case_id, file_path in targets:
        console.print(f"Leyendo {file_path.name} con Vision y RapidOCR…")
        doc = run_dual(file_path, case_id=case_id)
        docs.append(doc)
        by = {item.campo: item for item in doc.votes}
        table.add_row(
            doc.case_id,
            doc.recomendacion,
            str(doc.acuerdos),
            str(doc.conflictos),
            (by.get("nif_emisor").consenso if "nif_emisor" in by else "") or "—",
            (by.get("total").consenso if "total" in by else "") or "—",
        )
    dest = write_dual_xlsx(layout, docs)
    console.print(table)
    console.print(f"Excel: {dest}")
    console.print("SQLite no se ha modificado. El libro fiscal sigue siendo `aeat-hub export`.")
    console.print(f"Log: {log_path}")


def _dual_targets(
    layout: DataLayout,
    *,
    path: Path | None,
    from_inbox: bool,
) -> list[tuple[str, Path]]:
    if path is not None:
        return [(path.stem, path)]
    if from_inbox:
        return [(item.stem, item) for item in list_inbox(layout)]
    gold = gold_path(layout)
    if gold.is_file():
        rows = []
        for case in load_gold(gold, root=layout.root):
            if case.path.is_file():
                rows.append((case.id, case.path))
        if rows:
            return rows
    return [(item.stem, item) for item in list_inbox(layout)]


@app.command("ocr-status")
def ocr_status() -> None:
    """Muestra qué motores OCR están disponibles en esta máquina."""
    console.print(f"Auto en esta máquina: {describe_auto()}")
    table = Table(title="Motores")
    table.add_column("id")
    table.add_column("disponible")
    table.add_column("detalle")
    for name, ok, reason in list_engine_status():
        table.add_row(name, "sí" if ok else "no", reason)
    console.print(table)
    console.print(
        "Auto elige PDF nativo si hay texto; si no, Apple Vision en macOS y "
        "RapidOCR en Windows/Linux (y en Mac si Vision falla). "
        "DeepSeek-OCR vía Ollama: --ocr deepseek. Bake-off: [bold]aeat-hub eval[/bold]."
    )


@app.command("eval")
def eval_cmd(
    data_dir: Optional[Path] = typer.Option(None, "--data-dir", envvar="AEAT_HUB_DATA_DIR"),
    engines: str = typer.Option(
        ",".join(ENGINE_ORDER),
        "--engines",
        help="Lista: native,rapid,vision,deepseek,tesseract,unlimited,paddle",
    ),
    synthetic: bool = typer.Option(
        True, "--synthetic/--no-synthetic", help="Incluye PDF/PNG sintéticos (sin PII)"
    ),
    gold: Optional[Path] = typer.Option(
        None, "--gold", help="JSON de oro. Default: <data-dir>/evals/gold.json"
    ),
) -> None:
    """Compara motores OCR contra un set de oro. No sube facturas ni resultados a git."""
    import json

    layout = _layout(data_dir)
    layout.ensure()
    log_path = setup_run_log(layout, comando="eval")
    selected = [item.strip() for item in engines.split(",") if item.strip()]
    cases = load_suite(layout, include_synthetic=synthetic)
    if gold is not None:
        from aeat_hub.evals.gold import load_gold

        extra = load_gold(gold, root=layout.root)
        extra_ids = {item.id for item in extra}
        cases = extra + [case for case in cases if case.id not in extra_ids]
    if not cases:
        console.print(
            f"[red]No hay casos de oro.[/red] Escribe {gold_path(layout)} "
            "(fuera de git) o usa --synthetic."
        )
        console.print(f"Log: {log_path}")
        raise typer.Exit(1)
    missing = [case.id for case in cases if not case.path.is_file()]
    if missing:
        console.print(f"[yellow]Ficheros ausentes:[/yellow] {', '.join(missing)}")
    report = run_eval(cases, engines=selected, gold_path=str(gold or gold_path(layout)))
    stamp = Path(log_path).name.replace(".log", "")
    json_path = layout.evals / f"{stamp}.json"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = Table(title="EVALS · resumen por motor")
    summary.add_column("motor")
    summary.add_column("disp.")
    summary.add_column("n")
    summary.add_column("tokens")
    summary.add_column("campos OCR")
    summary.add_column("parser")
    summary.add_column("lat. mediana")
    summary.add_column("detalle")
    for item in report.summaries:
        summary.add_row(
            item.engine,
            "sí" if item.available else "no",
            str(item.applicable),
            _pct(item.token_recall),
            _pct(item.ocr_field_recall),
            _pct(item.parser_accuracy),
            f"{item.median_latency_ms} ms" if item.median_latency_ms is not None else "—",
            item.reason if not item.available else f"skip {item.skipped} err {item.errors}",
        )
    console.print(summary)

    detail = Table(title="EVALS · caso × motor")
    detail.add_column("caso")
    detail.add_column("motor")
    detail.add_column("estado")
    detail.add_column("tokens")
    detail.add_column("OCR")
    detail.add_column("parser")
    detail.add_column("ms")
    for run in report.runs:
        detail.add_row(
            run.case_id,
            run.engine,
            run.status,
            _pct(run.token_recall),
            _pct(run.ocr_field_recall),
            _pct(run.parser_accuracy),
            str(run.latency_ms) if run.latency_ms else "—",
        )
    console.print(detail)
    if report.ranking:
        console.print(
            f"Ranking (campos en OCR → tokens → parser → rapidez): {' > '.join(report.ranking)}"
        )
    for note in report.notes:
        console.print(f"[dim]{note}[/dim]")
    console.print(f"JSON: {json_path}")
    console.print(f"Log: {log_path}")


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.0f}%"


def _print_asientos(data_dir: Optional[Path], actividad: str, estados: tuple[str, ...]) -> None:
    layout = _layout(data_dir)
    factory = _session_factory(layout)
    with factory() as session:
        act = get_actividad(session, actividad)
        nombres = {c.codigo: c.nombre for c in session.scalars(select(Cuenta)).all()}
        rows = session.scalars(
            select(Asiento)
            .where(Asiento.actividad_id == act.id, Asiento.estado.in_(estados))
            .order_by(Asiento.fecha, Asiento.id)
        ).all()
        table = Table(title=f"{act.codigo} · {', '.join(estados)}")
        for col in ("id", "fecha", "emisor", "nif", "numero", "total", "rubro", "estado"):
            table.add_column(col)
        for row in rows:
            rubro = nombres.get(row.cuenta_codigo, "") if row.cuenta_codigo else ""
            table.add_row(
                str(row.id),
                row.fecha.isoformat() if row.fecha else "",
                (row.emisor or "")[:32],
                row.nif_emisor or "",
                row.numero_factura or "",
                str(row.total) if row.total is not None else "",
                rubro,
                row.estado,
            )
        if not rows:
            console.print("No hay asientos en este estado.")
            return
        console.print(table)
