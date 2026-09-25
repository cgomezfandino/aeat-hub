"""Dashboard HTML local: vista del libro. El maestro sigue siendo SQLite."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from html import escape
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from aeat_hub.dedupe import candidatos_duplicado
from aeat_hub.er import counts_por_factura, estados_er_por_factura
from aeat_hub.edits import articulos_label, lineas_de_asiento, parse_money_field
from aeat_hub.fiscal.accounts import (
    REGIMEN_AE,
    REGIMEN_CI,
    TIPO_GASTO,
    TIPO_INGRESO,
    TIPO_MEJORA,
)
from aeat_hub.fiscal.irpf import INDEX_CI, casilla_clave, summarize_irpf
from aeat_hub.fiscal.money import format_euro, q2
from aeat_hub.fiscal.cuadres import TOLERANCIA_TOTAL
from aeat_hub.fiscal.nif import is_placeholder_nif, is_valid_nif, normalize_nif
from aeat_hub.models import Actividad, Asiento, Cambio, Cuenta, Inmueble, Titular
from aeat_hub.paths import DataLayout

MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
MESES_LARGO = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
ZERO = Decimal("0.00")

REGIMEN_LABEL = {
    "capital_inmobiliario": "Rendimientos de capital inmobiliario",
    "actividad_economica": "Actividad económica",
}

ESTADO_LABEL = {
    "pendiente": "Por revisar",
    "confirmado": "Confirmado",
    "duplicado": "Duplicado",
    "rechazado": "Rechazado",
}

CONTACT_NAME = "Carlos Gomez"
CONTACT_MAIL = "cgomezfandino@gmail.com"
REPO_URL = "https://github.com/cgomezfandino/aeat-hub"


def write_dashboard(session: Session, layout: DataLayout, actividad: Actividad, year: int) -> Path:
    from aeat_hub.export import export_xlsx

    layout.exports.mkdir(parents=True, exist_ok=True)
    xlsx = export_xlsx(session, layout, actividad, year)
    data = collect_dashboard(session, actividad, year)
    data["xlsx_name"] = xlsx.name
    dest = layout.exports / f"dashboard_{actividad.codigo}_{year}.html"
    dest.write_text(render_dashboard(data), encoding="utf-8")
    return dest


def collect_dashboard(session: Session, actividad: Actividad, year: int) -> dict:
    rows = (
        session.scalars(
            select(Asiento)
            .where(Asiento.actividad_id == actividad.id, Asiento.ejercicio == year)
            .options(joinedload(Asiento.documento))
            .order_by(Asiento.id)
        )
        .unique()
        .all()
    )
    filas_cuenta = list(session.scalars(select(Cuenta)))
    nombres = {item.codigo: item.nombre for item in filas_cuenta}
    extra_casillas = {item.codigo: item.casilla for item in filas_cuenta if item.casilla}
    inmuebles = {
        item.id: item.alias
        for item in session.scalars(select(Inmueble).where(Inmueble.actividad_id == actividad.id))
    }
    titular = session.get(Titular, actividad.titular_id)
    vivos = [row for row in rows if row.estado not in ("duplicado", "rechazado")]
    factura_ids = [row.factura_id for row in rows if row.factura_id]
    n_docs_map = counts_por_factura(session, factura_ids)
    er_map = estados_er_por_factura(session, factura_ids)
    gastos = _sum_tipo(vivos, TIPO_GASTO)
    ingresos = _sum_tipo(vivos, TIPO_INGRESO)
    mejoras = _sum_tipo(vivos, TIPO_MEJORA)
    pendientes = [row for row in vivos if row.estado == "pendiente"]
    asientos = [
        _asiento_view(
            row,
            nombres,
            extra_casillas,
            inmuebles,
            n_docs=_n_docs(row, n_docs_map),
            er_estado=er_map.get(row.factura_id or 0, ""),
            titular_nif=titular.nif if titular else "",
        )
        for row in rows
    ]
    por_mes = _by_month(vivos)
    irpf = (
        summarize_irpf(vivos, extra_casillas) if actividad.regimen == REGIMEN_CI else None
    )
    sin_fecha = (
        session.scalars(
            select(Asiento)
            .where(
                Asiento.actividad_id == actividad.id,
                Asiento.fecha.is_(None),
                Asiento.estado.notin_(("duplicado", "rechazado")),
            )
            .order_by(Asiento.id)
        )
        .all()
    )
    n_conflictos = len({fid for fid, estado in er_map.items() if estado == "conflicto"})
    return {
        "codigo": actividad.codigo,
        "nombre": actividad.nombre,
        "regimen": actividad.regimen,
        "regimen_label": REGIMEN_LABEL.get(actividad.regimen, actividad.regimen),
        "year": year,
        "titular": titular.nombre if titular else "",
        "inmueble": next(iter(inmuebles.values()), ""),
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "n_asientos": len(vivos),
        "n_duplicados": sum(1 for row in rows if row.estado == "duplicado"),
        "n_pendientes": len(pendientes),
        "gastos": gastos,
        "ingresos": ingresos,
        "mejoras": mejoras,
        "resultado": ingresos - gastos,
        "por_mes": por_mes,
        "iva_tipos": _iva_por_tipo(vivos),
        "sin_fecha": [
            {"id": row.id, "emisor": row.emisor or "sin emisor"} for row in sin_fecha
        ],
        "n_conflictos": n_conflictos,
        "por_naturaleza": _by_nature(
            vivos, extra_casillas, nombres, actividad.regimen
        ),
        "asientos": asientos,
        "pendientes": [item for item in asientos if item["estado"] == "pendiente"],
        "sospechosos": [
            item
            for item in asientos
            if item["estado"] != "duplicado" and item.get("duplicado_nivel")
        ],
        "n_baja": sum(1 for item in asientos if item["baja"]),
        "n_validados": sum(1 for item in asientos if item["validado"]),
        "n_sin_validar": sum(
            1 for item in asientos if not item["validado"] and item["estado"] != "duplicado"
        ),
        "cola_revision": _cola_revision(asientos),
        "irpf": irpf,
        "xlsx_name": "",
        "rubros": sorted(
            {item.nombre for item in filas_cuenta if item.regimen == actividad.regimen}
        ),
    }


def render_dashboard(data: dict) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"<title>Libro {escape(data['codigo'])} · {data['year']}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n"
        f'<body data-default-panel="{"revision" if data["n_pendientes"] else "libro"}" '
        f'data-actividad="{escape(data["codigo"])}" '
        f"data-year=\"{data['year']}\">\n"
        f"{_masthead(data)}\n"
        '<main class="wrap panels">\n'
        f"{_panel_revision(data)}\n"
        f"{_panel_libro(data)}\n"
        f"{_panel_duplicados(data)}\n"
        f"{_panel_insights(data)}\n"
        "</main>\n"
        f"{_site_footer()}\n"
        f"{_edit_dialog(data)}\n"
        f"{_mast_dialog()}\n"
        f"<script>{_JS}</script>\n"
        "</body>\n</html>\n"
    )


def collect_asiento_ficha(session: Session, asiento: Asiento, *, dashboard_name: str) -> dict:
    actividad = session.get(Actividad, asiento.actividad_id)
    filas = list(session.scalars(select(Cuenta)))
    nombres = {item.codigo: item.nombre for item in filas}
    extra = {item.codigo: item.casilla for item in filas if item.casilla}
    inmuebles: dict[int, str] = {}
    if actividad is not None:
        inmuebles = {
            item.id: item.alias
            for item in session.scalars(select(Inmueble).where(Inmueble.actividad_id == actividad.id))
        }
    titular = session.get(Titular, actividad.titular_id) if actividad is not None else None
    view = _asiento_view(
        asiento, nombres, extra, inmuebles, titular_nif=titular.nif if titular else ""
    )
    lineas = lineas_de_asiento(asiento)
    suma = _suma_importes(lineas)
    lineas_ok = _cuadra_con_total(suma, asiento.total)
    logs = session.scalars(
        select(Cambio).where(Cambio.asiento_id == asiento.id).order_by(Cambio.id.desc())
    ).all()
    sugeridos = (
        candidatos_duplicado(session, asiento)
        if asiento.estado != "duplicado"
        else []
    )
    duplicado_conocido = None
    if asiento.estado != "duplicado":
        if asiento.duplicado_de_id:
            duplicado_conocido = asiento.duplicado_de_id
        else:
            duplicado_conocido = session.scalar(
                select(Asiento.id).where(
                    Asiento.duplicado_de_id == asiento.id,
                    Asiento.estado != "duplicado",
                    Asiento.id != asiento.id,
                )
            )
    back = f"/{dashboard_name}" if dashboard_name else "/"
    back = f"{back}#asiento-{asiento.id}"
    return {
        **view,
        "actividad_codigo": actividad.codigo if actividad else "",
        "actividad_nombre": actividad.nombre if actividad else "",
        "year": asiento.ejercicio,
        "lineas": lineas,
        "n_lineas": len(lineas),
        "lineas_suma": suma,
        "lineas_ok": lineas_ok,
        "dashboard_href": back,
        "duplicados_sugeridos": sugeridos,
        "duplicado_conocido": duplicado_conocido,
        "cambios": [
            {
                "campo": item.campo,
                "antes": item.antes,
                "despues": item.despues,
                "cuando": item.created_at.strftime("%d/%m/%Y %H:%M") if item.created_at else "",
            }
            for item in logs
        ],
    }


def render_asiento_page(data: dict) -> str:
    lineas = data["lineas"]
    n_lineas = int(data.get("n_lineas") or len(lineas))
    score = _criterios_html(
        criterios_calidad(
            numero=data.get("numero"),
            fecha=data.get("fecha_label"),
            emisor=data.get("emisor"),
            nif=data.get("nif"),
            base=data.get("base"),
            iva=data.get("iva"),
            total=data.get("total"),
            rubro=data.get("cuenta_nombre"),
            lineas=lineas,
            titular_nif=data.get("titular_nif") or "",
        ),
        total=data.get("total"),
    )
    if lineas:
        rows = _lineas_rows_html(lineas)
    else:
        rows = '<tr><td colspan="9">Sin líneas extraídas. Abre el PDF y contrasta el total a mano.</td></tr>'
    logs = data["cambios"]
    nombres = {
        "lineas": "Líneas",
        "validado": "Validado",
        "base": "Base",
        "iva_cuota": "IVA",
        "total": "Total",
        "emisor": "Emisor",
        "nif_emisor": "NIF emisor",
        "fecha": "Fecha de compra",
        "rubro": "Rubro",
        "iva_tipo": "IVA %",
    }

    def _log_valor(value: str) -> str:
        text = (value or "").strip()
        if text.lower() == "true":
            return "Sí"
        if text.lower() == "false":
            return "No"
        return text or "—"

    if logs:
        filas_log = "".join(
            "<tr>"
            f"<td>{escape(item['cuando'] or '—')}</td>"
            f"<td>{escape(nombres.get(item['campo'], item['campo']))}</td>"
            f"<td>{escape(_log_valor(item['antes'] or ''))}</td>"
            f"<td>{escape(_log_valor(item['despues'] or ''))}</td>"
            "</tr>"
            for item in logs[:40]
        )
    else:
        filas_log = '<tr><td colspan="4">Sin cambios registrados todavía.</td></tr>'
    historial = (
        '<table class="edit-diff log-table"><thead><tr>'
        "<th>Fecha</th><th>Campo</th><th>Antes</th><th>Después</th>"
        f"</tr></thead><tbody>{filas_log}</tbody></table>"
    )
    doc = ""
    if data["has_doc"]:
        name = escape(data.get("doc_name") or "")
        extra = f'<span class="doc-open-name">{name}</span>' if name else ""
        doc = (
            f'<a class="doc-open" href="/doc/{data["id"]}" target="_blank" rel="noopener">'
            f"{_FILE_SVG}<span>Abrir documento</span>{extra}</a>"
        )
    if data.get("estado") == "duplicado":
        dup = (
            '<div class="ficha-dup">'
            f'<p class="hint">Marcado como duplicado del asiento #{escape(str(data.get("duplicado_de_id") or "—"))}. '
            "Fuera de los totales.</p>"
            '<button type="button" class="ghost" id="ficha-dup-quitar">Quitar duplicado</button>'
            "</div>"
        )
    else:
        dup = (
            '<div class="ficha-dup">'
            '<button type="button" class="ghost" id="ficha-dup-marcar">Marcar duplicado de…</button>'
            "</div>"
        )
    sugeridos = data.get("duplicados_sugeridos") or []
    conocido = data.get("duplicado_conocido")
    opciones_dup: list[tuple[str, str]] = []
    if conocido is not None:
        meta = next((i for i in sugeridos if i["id"] == conocido), None)
        etiqueta = f"#{conocido}"
        if meta:
            etiqueta += (
                f" · {meta['emisor']} · {meta['numero']} · {meta['fecha']}"
                f" · {format_euro(meta['total'])}"
            )
        opciones_dup.append(
            (str(conocido), f"{etiqueta} — ya señalado por la app")
        )
    for item in sugeridos:
        if conocido is not None and item["id"] == conocido:
            continue
        opciones_dup.append(
            (
                str(item["id"]),
                f"#{item['id']} · {item['emisor']} · {item['numero']} · "
                f"{item['fecha']} · {format_euro(item['total'])} — {item['motivo']}",
            )
        )
    html_opciones = "".join(
        f'<option value="{escape(value)}"{" selected" if idx == 0 else ""}>'
        f"{escape(label)}</option>"
        for idx, (value, label) in enumerate(opciones_dup)
    )
    solo_manual = not opciones_dup
    dup_dialog = (
        '<dialog class="edit-dialog" id="ficha-dup-dialog" aria-labelledby="ficha-dup-title">'
        f'<h2 id="ficha-dup-title">Marcar duplicado del asiento #{data["id"]}</h2>'
        '<p class="hint">Elige el asiento bueno: este queda como duplicado y sale de los totales. '
        "Puedes deshacerlo después.</p>"
        '<label class="dup-campo">Asiento bueno'
        f'<select id="dup-candidato" class="dup-select">{html_opciones}'
        f'<option value="manual"{" selected" if solo_manual else ""}>Otro id…</option></select></label>'
        f'<label class="dup-campo" id="dup-manual-wrap"{" hidden" if not solo_manual else ""}>Otro id'
        '<input id="dup-manual" type="number" min="1" placeholder="Id" class="dup-manual"></label>'
        '<div class="edit-actions">'
        '<button type="button" class="ghost" id="ficha-dup-cancel">Cancelar</button>'
        '<button type="button" class="export-btn" id="ficha-dup-ok" disabled>Fusionar</button>'
        "</div></dialog>"
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"<title>Factura {escape(str(data['numero']))} · {escape(str(data['emisor']))}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n"
        f"<body class=\"ficha-page\" data-asiento=\"{data['id']}\">\n"
        '<header class="ficha-bar wrap">'
        f'<a class="back-link" href="{escape(data["dashboard_href"])}">{_BACK_SVG} Volver al libro</a>'
        f'<button type="button" class="row-edit" id="ficha-log" '
        f'title="Historial de cambios" aria-haspopup="dialog" aria-label="Historial de cambios">{_CLOCK_SVG}</button>'
        "</header>\n"
        '<main class="wrap ficha">\n'
        '<div class="ficha-head">'
        "<div>"
        f'<p class="ficha-kicker">{escape(data["actividad_codigo"])} · {data["year"]} · asiento #{data["id"]}</p>\n'
        f"<h1>{escape(data['emisor'])}</h1>\n"
        f'<p class="ficha-sub">{escape(data["numero"])} · {escape(data["fecha_label"])} · '
        f'<span class="pill {escape(data["estado"])}">{escape(data["estado_label"])}</span></p>\n'
        "</div>"
        f"{doc}"
        f"{dup}"
        "</div>\n"
        '<div class="kpi-carousel" id="ficha-kpis">'
        '<dl class="ficha-grid">'
        f"<div><dt>NIF emisor</dt><dd class=\"mono\">{escape(data['nif'])}</dd></div>"
        f"<div><dt>Rubro</dt><dd>{escape(data['cuenta_nombre'])}</dd></div>"
        f"<div><dt>Base</dt><dd id=\"kpi-base\">{escape(format_euro(data['base']))}</dd></div>"
        f"<div><dt>IVA</dt><dd id=\"kpi-iva\">{escape(format_euro(data['iva']))}</dd></div>"
        f"<div><dt>Total</dt><dd id=\"kpi-total\">{escape(format_euro(data['total']))}</dd></div>"
        f"<div><dt>Elementos</dt><dd id=\"kpi-elementos\">{escape(articulos_label(lineas))}</dd></div>"
        f"<div><dt>Casilla</dt><dd>{escape(data['casilla_etiqueta'])}</dd></div>"
        "</dl>\n"
        '<div class="kpi-dots" hidden></div>'
        "</div>\n"
        f"{_ficha_kpi_script()}\n"
        '<div id="ficha-lines-editor" class="ledger">'
        f'<h2 class="ficha-h2">{_LIST_SVG} Líneas de la factura'
        f'<span class="ficha-count" id="ficha-count">{escape(_elementos_label(n_lineas))}</span>'
        f'<button type="button" class="row-edit" id="ficha-lines-eye" hidden '
        f'title="Ver líneas eliminadas" aria-pressed="false" aria-label="Ver líneas eliminadas">{_EYE_SVG}</button>'
        "</h2>\n"
        f"{score}"
        '<div class="table-wrap ficha-lines"><table class="ledger-table ficha-ledger">'
        "<colgroup>"
        '<col class="fl-n"><col class="fl-id"><col class="fl-concepto"><col class="fl-uds">'
        '<col class="fl-money"><col class="fl-rate"><col class="fl-money"><col class="fl-money"><col class="fl-act">'
        "</colgroup>"
        f"{_lineas_thead(lineas)}\n"
        f"<tbody id=\"ficha-lines-body\">{rows}</tbody></table></div>\n"
        '<nav class="pager" id="ficha-pager" aria-label="Páginas de las líneas">'
        '<button type="button" class="ghost" id="ficha-prev">Anterior</button>'
        '<span class="pager-pages" id="ficha-pages"></span>'
        '<span class="pager-label" id="ficha-pager-label"></span>'
        '<button type="button" class="ghost" id="ficha-next">Siguiente</button>'
        "</nav>\n"
        '<p class="edit-actions ficha-line-actions">'
        '<button type="button" class="ghost" id="ficha-line-add">Añadir línea</button>'
        "</p>\n"
        '<div id="ficha-line-tools" hidden>'
        '<label class="edit-check"><input id="ficha-ack" type="checkbox"> '
        "Acepto los cambios de esta línea. Base, IVA y total pasan a ser la suma.</label>\n"
        '<div class="edit-actions">'
        '<button type="button" class="ghost" id="ficha-lines-cancel">Cancelar</button>'
        '<button type="button" class="export-btn" id="ficha-lines-save" disabled>Guardar</button>'
        "</div>\n"
        "</div>\n"
        f'<p class="edit-lines-note" id="ficha-lines-note"></p>\n'
        "</div>\n"
        '<dialog class="edit-dialog app-confirm" id="app-confirm" aria-labelledby="app-confirm-title">'
        '<form method="dialog">'
        '<h2 id="app-confirm-title">Confirmar</h2>'
        '<p id="app-confirm-text"></p>'
        '<div class="edit-actions">'
        '<button type="submit" class="ghost" value="cancel">Cancelar</button>'
        '<button type="submit" class="export-btn" id="app-confirm-ok" value="ok">Aceptar</button>'
        "</div></form></dialog>\n"
        f"{dup_dialog}\n"
        f"{_ficha_lines_script()}\n"
        f"{_ficha_filter_script()}\n"
        '<dialog class="edit-dialog ficha-log-dialog" id="ficha-log-dialog" aria-labelledby="ficha-log-title">'
        f'<h2 id="ficha-log-title">{_CLOCK_SVG} Historial de cambios</h2>'
        f"{historial}"
        '<div class="edit-actions"><button type="button" class="ghost" id="ficha-log-close">Cerrar</button></div>'
        "</dialog>\n"
        "<script>(() => {"
        "const log = document.getElementById('ficha-log-dialog');"
        "document.getElementById('ficha-log')?.addEventListener('click', () => log?.showModal());"
        "document.getElementById('ficha-log-close')?.addEventListener('click', () => log?.close());"
        "const qBtn = document.querySelector('.q-i-btn[popovertarget]');"
        "const qPop = document.getElementById('ficha-score-pop');"
        "qPop?.addEventListener('toggle', (event) => {"
        "  if (event.newState !== 'open' || !qBtn) return;"
        "  qBtn.setAttribute('aria-expanded', 'true');"
        "  const rect = qBtn.getBoundingClientRect();"
        "  const left = Math.max(8, Math.min(rect.left, window.innerWidth - qPop.offsetWidth - 8));"
        "  const top = Math.min(rect.bottom + 8, window.innerHeight - qPop.offsetHeight - 8);"
        "  qPop.style.left = `${left}px`;"
        "  qPop.style.top = `${top}px`;"
        "});"
        "qBtn?.addEventListener('click', () => qBtn.setAttribute('aria-expanded', qPop?.open ? 'false' : 'true'));"
        "})();</script>\n"
        '<script>(() => {\n'
        "  const id = document.body.dataset.asiento;\n"
        "  const postDup = async (body) => {\n"
        "    try {\n"
        "      const res = await fetch(`/api/asientos/${id}`, {\n"
        "        method: \"POST\",\n"
        "        headers: { \"Content-Type\": \"application/json\" },\n"
        "        body: JSON.stringify(body),\n"
        "      });\n"
        "      const payload = await res.json().catch(() => ({}));\n"
        "      if (!res.ok || payload.ok === false) throw new Error(payload.error || String(res.status));\n"
        "      window.location.reload();\n"
        "    } catch (err) {\n"
        "      alert(\"No se pudo guardar: \" + err.message);\n"
        "    }\n"
        "  };\n"
        "  const dialog = document.getElementById(\"ficha-dup-dialog\");\n"
        "  const okBtn = document.getElementById(\"ficha-dup-ok\");\n"
        "  const manualEl = document.getElementById(\"dup-manual\");\n"
        "  const selectEl = document.getElementById(\"dup-candidato\");\n"
        "  const manualWrap = document.getElementById(\"dup-manual-wrap\");\n"
        "  const elegido = () => {\n"
        "    if (!selectEl) return \"\";\n"
        "    return selectEl.value === \"manual\" ? (manualEl?.value || \"\").trim() : selectEl.value;\n"
        "  };\n"
        "  const syncOk = () => {\n"
        "    const manual = selectEl?.value === \"manual\";\n"
        "    if (manualWrap) manualWrap.hidden = !manual;\n"
        "    const value = elegido();\n"
        "    if (okBtn) okBtn.disabled = !/^\\d+$/.test(value) || value === id;\n"
        "  };\n"
        "  selectEl?.addEventListener(\"change\", syncOk);\n"
        "  manualEl?.addEventListener(\"input\", syncOk);\n"
        "  document.getElementById(\"ficha-dup-marcar\")?.addEventListener(\"click\", () => {\n"
        "    syncOk();\n"
        "    if (manualWrap && !manualWrap.hidden) manualEl?.focus();\n"
        "    dialog?.showModal();\n"
        "  });\n"
        "  document.getElementById(\"ficha-dup-cancel\")?.addEventListener(\"click\", () => dialog?.close());\n"
        "  okBtn?.addEventListener(\"click\", () => {\n"
        "    const value = elegido();\n"
        "    if (!/^\\d+$/.test(value)) { alert(\"Escribe el id numérico del asiento bueno.\"); return; }\n"
        "    if (value === id) { alert(\"Un asiento no puede ser duplicado de sí mismo.\"); return; }\n"
        "    postDup({ duplicado_de: value, confirmado: true });\n"
        "  });\n"
        "  document.getElementById(\"ficha-dup-quitar\")?.addEventListener(\"click\", () => {\n"
        "    postDup({ quitar_duplicado: true, confirmado: true });\n"
        "  });\n"
        "})();</script>\n"
        "</main>\n"
        f"{_site_footer()}\n"
        "</body>\n</html>\n"
    )


def _ficha_kpi_script() -> str:
    return r"""
<script>
(() => {
  const root = document.getElementById("ficha-kpis");
  const track = root?.querySelector(".ficha-grid");
  const dots = root?.querySelector(".kpi-dots");
  if (!track || !dots) return;
  const metrics = () => {
    const card = track.querySelector(":scope > div");
    const gap = 10;
    const stride = (card?.getBoundingClientRect().width || 160) + gap;
    const fit = Math.max(1, Math.floor((track.clientWidth + gap) / stride));
    const count = track.querySelectorAll(":scope > div").length;
    return { stride, fit, pages: Math.max(1, Math.ceil(count / fit)) };
  };
  const paint = () => {
    const { stride, fit, pages } = metrics();
    const max = Math.max(0, track.scrollWidth - track.clientWidth);
    const current = max <= 1 ? 0 : Math.min(pages - 1, Math.round((track.scrollLeft / max) * (pages - 1)));
    dots.hidden = pages < 2;
    dots.replaceChildren();
    for (let index = 0; index < pages; index += 1) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "kpi-dot" + (index === current ? " is-on" : "");
      button.setAttribute("aria-label", `Indicadores, página ${index + 1} de ${pages}`);
      if (index === current) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => {
        const end = Math.max(0, track.scrollWidth - track.clientWidth);
        const left = index === pages - 1 ? end : index * stride * fit;
        track.scrollTo({ left, behavior: "smooth" });
      });
      dots.appendChild(button);
    }
  };
  track.addEventListener("scroll", paint, { passive: true });
  window.addEventListener("resize", paint);
  let drag = null;
  track.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "mouse" || event.button !== 0) return;
    drag = { x: event.clientX, left: track.scrollLeft, id: event.pointerId, moved: false };
    track.setPointerCapture(event.pointerId);
  });
  track.addEventListener("pointermove", (event) => {
    if (!drag || drag.id !== event.pointerId) return;
    const dx = event.clientX - drag.x;
    if (Math.abs(dx) > 3) drag.moved = true;
    if (!drag.moved) return;
    track.classList.add("is-dragging");
    track.scrollLeft = drag.left - dx;
  });
  const endDrag = (event) => {
    if (!drag || drag.id !== event.pointerId) return;
    drag = null;
    track.classList.remove("is-dragging");
  };
  track.addEventListener("pointerup", endDrag);
  track.addEventListener("pointercancel", endDrag);
  paint();
})();
</script>
"""


def _ficha_lines_script() -> str:
    return r"""
<script>
(() => {
  const body = document.getElementById("ficha-lines-body");
  const tools = document.getElementById("ficha-line-tools");
  const save = document.getElementById("ficha-lines-save");
  const ack = document.getElementById("ficha-ack");
  const note = document.getElementById("ficha-lines-note");
  const asiento = document.body.dataset.asiento;
  const leaveText = "Hay cambios sin guardar. No se guardan solos. ¿Salir de todas formas?";
  const ask = (text, opts = {}) => new Promise((resolve) => {
    const dialog = document.getElementById("app-confirm");
    const msg = document.getElementById("app-confirm-text");
    const title = document.getElementById("app-confirm-title");
    const ok = document.getElementById("app-confirm-ok");
    if (!dialog || typeof dialog.showModal !== "function") {
      resolve(window.confirm(text));
      return;
    }
    title.textContent = opts.title || "Confirmar";
    msg.textContent = text;
    ok.textContent = opts.ok || "Aceptar";
    ok.classList.toggle("is-warn", Boolean(opts.warn));
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    if (!dialog.open) dialog.showModal();
  });
  document.getElementById("app-confirm")?.addEventListener("click", (event) => {
    if (event.target?.id === "app-confirm") event.target.close("cancel");
  });
  let editing = null;
  let removed = false;
  let allowLeave = false;
  const field = (name, label, money) => {
    const kind = money ? ' type="number" min="0" step="0.01"' : "";
    return `<input class="line-edit" disabled data-f="${name}" data-orig=""${kind} aria-label="${label}">`;
  };
  const disk = `<button type="button" class="row-edit line-save" title="Guardar línea" aria-label="Guardar línea">${""
    }<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" d="M3 2.5h7.2L13 5.2V13.5H3z"/><path fill="none" stroke="currentColor" stroke-width="1.4" d="M5 2.8V6h5.2M5 13.2v-3.4h6V13"/></svg></button>`;
  const trash = `<button type="button" class="row-edit line-del" title="Eliminar línea" aria-label="Eliminar línea">${""
    }<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" d="M3.5 4.5h9M6.2 4.5V3.2h3.6v1.3M5 4.5l.5 8h5l.5-8"/></svg></button>`;
  const restore = `<button type="button" class="row-edit line-restore" title="Recuperar línea" aria-label="Recuperar línea">${""
    }<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" d="M3.2 8a4.8 4.8 0 1 0 1.2-3.2M3 3.2V6.2h3"/></svg></button>`;
  const collect = () => [...body.querySelectorAll("tr[data-line]")].map((tr, idx) => ({
    posicion: idx + 1,
    codigo: tr.querySelector("[data-f=codigo]")?.value || "",
    descripcion: tr.querySelector("[data-f=descripcion]")?.value || "",
    cantidad: tr.querySelector("[data-f=cantidad]")?.value || "1",
    base: tr.querySelector("[data-f=base]")?.value || "",
    iva_tipo: tr.querySelector("[data-f=iva_tipo]")?.value || "",
    iva_cuota: tr.querySelector("[data-f=iva_cuota]")?.value || "",
    importe: tr.querySelector("[data-f=importe]")?.value || "",
    eliminada: tr.dataset.deleted === "1",
  })).filter((item) => item.descripcion || item.importe || item.codigo);
  const euro = (value) => new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(value);
  const round2 = (value) => Math.round((value + Number.EPSILON) * 100) / 100;
  const num = (tr, name) => {
    const raw = (tr.querySelector(`[data-f="${name}"]`)?.value || "").trim().replace(",", ".");
    if (!raw) return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  };
  const writeMoney = (tr, name, value) => {
    const input = tr.querySelector(`[data-f="${name}"]`);
    if (!input) return;
    const text = value == null ? "" : round2(value).toFixed(2);
    input.value = text;
    const view = input.parentElement?.querySelector(".line-view");
    if (view) view.textContent = text ? euro(round2(value)) : "—";
    const key = { base: "lineBase", iva_cuota: "lineIva", importe: "lineTotal" }[name];
    if (key) tr.dataset[key] = text;
  };
  const recalc = (tr, source) => {
    const rate = num(tr, "iva_tipo");
    if (rate == null) return;
    let origin = source;
    if (origin === "iva_tipo") origin = tr.dataset.driver || (num(tr, "importe") != null ? "importe" : "base");
    if (origin === "base") {
      const base = num(tr, "base");
      if (base == null) return;
      const iva = round2(base * rate / 100);
      writeMoney(tr, "iva_cuota", iva);
      writeMoney(tr, "importe", round2(base + iva));
      tr.dataset.driver = "base";
    } else if (origin === "importe") {
      const total = num(tr, "importe");
      if (total == null) return;
      const base = round2(total / (1 + rate / 100));
      writeMoney(tr, "base", base);
      writeMoney(tr, "iva_cuota", round2(total - base));
      tr.dataset.driver = "importe";
    }
  };
  const refreshKpis = () => {
    let base = 0;
    let iva = 0;
    let total = 0;
    let nBase = 0;
    let nIva = 0;
    let nTotal = 0;
    const rows = [...body.querySelectorAll("tr[data-line]")].filter((tr) => tr.dataset.deleted !== "1");
    for (const tr of rows) {
      const b = num(tr, "base");
      const i = num(tr, "iva_cuota");
      const t = num(tr, "importe");
      if (b != null) { base += b; nBase += 1; }
      if (i != null) { iva += i; nIva += 1; }
      if (t != null) { total += t; nTotal += 1; }
    }
    const put = (id, amount, has) => {
      const el = document.getElementById(id);
      if (el) el.textContent = has ? euro(round2(amount)) : "—";
    };
    put("kpi-base", base, nBase);
    put("kpi-iva", iva, nIva);
    put("kpi-total", total, nTotal);
    const headingCount = document.getElementById("ficha-count");
    if (headingCount) {
      headingCount.textContent = rows.length === 1 ? "1 elemento" : `${rows.length} elementos`;
    }
    const count = document.getElementById("kpi-elementos");
    if (count) {
      let unidades = 0;
      for (const tr of rows) {
        const desc = (tr.querySelector("[data-f=descripcion]")?.value || "").trim();
        if (!desc) continue;
        const qty = num(tr, "cantidad");
        unidades += qty == null ? 1 : qty;
      }
      const whole = Math.abs(unidades - Math.round(unidades)) < 0.0005;
      count.textContent = whole ? String(Math.round(unidades)) : String(Math.round(unidades * 1000) / 1000);
    }
    paintQuality(rows, total, nTotal);
  };
  const paintQuality = (rows, lineTotal, nTotal) => {
    const root = document.getElementById("ficha-score");
    const list = document.getElementById("ficha-score-list");
    if (!root || !list) return;
    const join = (items) => items.slice(0, 3).join(", ") + (items.length > 3 ? ` y ${items.length - 3} más` : "");
    const names = [];
    const noConcept = [];
    const noMoney = [];
    rows.forEach((tr, idx) => {
      const desc = (tr.querySelector("[data-f=descripcion]")?.value || "").trim();
      const code = (tr.querySelector("[data-f=codigo]")?.value || "").trim();
      const name = desc || `línea ${idx + 1}`;
      if (!code) names.push(name);
      if (!desc) noConcept.push(`línea ${idx + 1}`);
      if (num(tr, "importe") == null) noMoney.push(name);
    });
    const set = (id, ok, detail) => {
      const li = list.querySelector(`[data-check="${id}"]`);
      if (!li) return;
      li.dataset.ok = ok ? "1" : "0";
      li.classList.toggle("is-ok", ok);
      li.classList.toggle("is-bad", !ok);
      const em = li.querySelector("em");
      if (ok) em?.remove();
      else if (em) em.textContent = detail;
      else li.insertAdjacentHTML("beforeend", `<em></em>`), li.querySelector("em").textContent = detail;
    };
    const empty = rows.length === 0;
    set("ids", !empty && names.length === 0, empty ? "No hay líneas, así que no hay ids de artículo." : `Falta el id en ${join(names)}.`);
    set("conceptos", !empty && noConcept.length === 0, empty ? "No hay líneas, así que no hay conceptos." : `Falta el concepto en ${join(noConcept)}.`);
    set("importes", !empty && noMoney.length === 0, empty ? "No hay líneas, así que no hay importes." : `Falta el importe en ${join(noMoney)}.`);
    const book = root.dataset.total === undefined || root.dataset.total === "" ? null : Number(root.dataset.total);
    const suma = round2(lineTotal);
    const cuadra = !empty && book != null && nTotal > 0 && Math.abs(suma - book) <= 0.02;
    const delta = book == null ? null : round2(Math.abs(suma - book));
    set(
      "suma",
      cuadra,
      book == null || empty
        ? "No hay importes que contrastar con el total del libro."
        : `Suma de ${nTotal} importes ${euro(suma)} ≠ total del libro ${euro(book)} (diferencia ${euro(delta)}). Puede faltar un artículo, o un importe se ha mezclado con otra línea.`
    );
    const items = [...list.querySelectorAll("[data-check]")];
    const okN = items.filter((li) => li.dataset.ok === "1").length;
    const pct = items.length ? Math.round((100 * okN) / items.length) : 0;
    const all = items.length > 0 && okN === items.length;
    const label = document.getElementById("ficha-score-label");
    const pctEl = document.getElementById("ficha-score-pct");
    const chip = document.getElementById("ficha-score-chip");
    if (label) label.textContent = all ? "Lista" : "Revisar";
    if (pctEl) pctEl.textContent = `${pct} %`;
    if (chip) {
      chip.classList.remove("q-ok", "q-warn", "q-bad", "q-muted");
      chip.classList.add(all ? "q-ok" : pct >= 80 ? "q-warn" : "q-bad");
    }
    const failsEl = document.getElementById("ficha-score-fails");
    if (failsEl) {
      const malos = items.filter((li) => li.dataset.ok === "0");
      failsEl.innerHTML = malos.map((li) => {
        const nombre = li.querySelector("span")?.textContent || "";
        const detalle = li.querySelector("em")?.textContent || "";
        return `<li class="is-bad"><span>${nombre}</span>${detalle ? `<em>${detalle}</em>` : ""}</li>`;
      }).join("");
      failsEl.hidden = malos.length === 0;
    }
  };
  const pencil = (n) => `<button type="button" class="row-edit line-edit-btn" title="Editar línea" aria-label="Editar línea ${n}">`
    + `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M11.7 1.6c.4-.4 1.1-.4 1.5 0l1.2 1.2c.4.4.4 1.1 0 1.5L6.2 12.5 2 14l1.5-4.2z"/></svg></button>`;
  const rowHtml = (n) => `<td class="num col-sticky">${n}</td>`
    + `<td class="mono cell-nowrap"><span class="line-view">—</span>${field("codigo", "Id", false)}</td>`
    + `<td class="cell-clip"><span class="line-view cell-text">—</span>${field("descripcion", "Concepto", false)}</td>`
    + `<td class="num cell-nowrap"><span class="line-view">1</span><input class="line-edit" data-f="cantidad" data-orig="1" type="number" min="0" step="0.001" value="1" aria-label="Unidades"></td>`
    + `<td class="num cell-nowrap"><span class="line-view">—</span>${field("base", "Subtotal", true)}</td>`
    + `<td class="num cell-nowrap"><span class="line-view">21 %</span><input class="line-edit" data-f="iva_tipo" data-orig="21" type="number" min="0" max="100" step="0.01" value="21" aria-label="IVA %"></td>`
    + `<td class="num cell-nowrap"><span class="line-view">—</span><input class="line-edit line-calc" disabled data-f="iva_cuota" data-orig="" type="number" step="0.01" tabindex="-1" aria-label="IVA"></td>`
    + `<td class="num cell-nowrap"><span class="line-view">—</span>${field("importe", "Total de línea", true)}</td>`
    + `<td class="line-actions cell-estado"><div class="row-actions">${pencil(n)}${disk}${trash}${restore}</div></td>`;
  const rowDirty = (tr) => {
    if (!tr) return false;
    if (tr.dataset.fresh === "1") return true;
    return [...tr.querySelectorAll("input.line-edit")].some((input) => input.value !== (input.dataset.orig || ""));
  };
  const deletionDirty = () => [...body.querySelectorAll("tr[data-line]")]
    .some((tr) => (tr.dataset.deleted || "0") !== (tr.dataset.wasDeleted || "0"));
  const pending = () => deletionDirty() || rowDirty(editing);
  const showTools = (on) => {
    if (tools) tools.hidden = !on;
    if (!on && ack) ack.checked = false;
    if (save) save.disabled = true;
  };
  const closeRow = (tr, revert) => {
    if (!tr) return;
    if (revert) {
      if (tr.dataset.fresh === "1") {
        tr.remove();
      } else {
        tr.querySelectorAll("input.line-edit").forEach((input) => { input.value = input.dataset.orig || ""; });
      }
    }
    tr.classList.remove("is-editing");
    tr.querySelectorAll("input.line-edit").forEach((input) => { input.disabled = true; });
    if (editing === tr) editing = null;
    refreshKpis();
  };
  const openRow = async (tr) => {
    if (editing && editing !== tr) {
      if (rowDirty(editing) && !(await ask(leaveText, { title: "Cambios sin guardar", ok: "Salir" }))) return;
      closeRow(editing, true);
    }
    editing = tr;
    tr.classList.add("is-editing");
    tr.querySelectorAll("input.line-edit").forEach((input) => {
      input.disabled = input.classList.contains("line-calc");
    });
    showTools(true);
    tr.querySelector("input.line-edit")?.focus();
  };
  const syncSave = () => {
    if (save) save.disabled = !(ack?.checked && pending());
  };
  ack?.addEventListener("change", syncSave);
  body?.addEventListener("input", (event) => {
    const input = event.target.closest("input.line-edit");
    const tr = input?.closest("tr");
    if (input && tr && ["base", "importe", "iva_tipo"].includes(input.dataset.f)) recalc(tr, input.dataset.f);
    refreshKpis();
    syncSave();
  });
  document.getElementById("ficha-lines-cancel")?.addEventListener("click", async () => {
    if (pending() && !(await ask(leaveText, { title: "Cambios sin guardar", ok: "Salir" }))) return;
    allowLeave = true;
    if (removed) {
      window.location.reload();
      return;
    }
    closeRow(editing, true);
    showTools(false);
  });
  document.getElementById("ficha-line-add")?.addEventListener("click", async () => {
    if (editing && rowDirty(editing) && !(await ask(leaveText, { title: "Cambios sin guardar", ok: "Salir" }))) return;
    closeRow(editing, true);
    body.querySelector("tr:not([data-line])")?.remove();
    const tr = document.createElement("tr");
    tr.dataset.line = "1";
    tr.dataset.fresh = "1";
    tr.dataset.lineRate = "21";
    tr.dataset.driver = "importe";
    const n = body.querySelectorAll("tr[data-line]").length + 1;
    tr.innerHTML = rowHtml(n);
    body.appendChild(tr);
    openRow(tr);
    refreshKpis();
    body.dispatchEvent(new CustomEvent("ficha-repaginate", { detail: { last: true } }));
  });
  const eye = document.getElementById("ficha-lines-eye");
  const editor = document.getElementById("ficha-lines-editor");
  const updateEye = () => {
    const n = body.querySelectorAll("tr.is-deleted").length;
    if (!eye) return;
    eye.hidden = n === 0;
    eye.title = n ? `Ver ${n} línea${n === 1 ? "" : "s"} eliminada${n === 1 ? "" : "s"}` : "Ver líneas eliminadas";
  };
  const markDeleted = (tr, deleted) => {
    tr.dataset.deleted = deleted ? "1" : "0";
    tr.classList.toggle("is-deleted", deleted);
    if (deleted && editing === tr) closeRow(tr, false);
    updateEye();
    refreshKpis();
    syncSave();
    body?.dispatchEvent(new CustomEvent("ficha-repaginate"));
  };
  const persist = async (opts = {}) => {
    if (!pending()) return;
    allowLeave = true;
    try {
      const res = await fetch(`/api/asientos/${asiento}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lineas: collect(),
          recalcular_total: true,
          confirmado: true,
          ...(opts.mantenerEstado ? { mantener_estado: true } : {}),
        }),
      });
      if (!res.ok) throw new Error(String(res.status));
      window.location.reload();
    } catch {
      allowLeave = false;
      if (note) note.textContent = "No se pudo guardar. Abre el libro con el servidor local.";
      if (save) save.disabled = false;
    }
  };
  body?.addEventListener("click", async (event) => {
    const edit = event.target.closest(".line-edit-btn");
    if (edit) {
      const tr = edit.closest("tr");
      if (tr?.dataset.deleted === "1") return;
      openRow(tr);
      return;
    }
    const saveBtn = event.target.closest(".line-save");
    if (saveBtn) {
      if (!(await ask("Base, IVA y total de la factura pasan a ser la suma de las líneas visibles.", { title: "¿Guardar esta línea?", ok: "Guardar" }))) return;
      persist();
      return;
    }
    const del = event.target.closest(".line-del");
    if (del) {
      const tr = del.closest("tr");
      if (!tr) return;
      const nombre = (tr.querySelector("[data-f=descripcion]")?.value || "esta fila").trim();
      if (!(await ask(`«${nombre}» no se borra del todo: podrás verla y recuperarla con el ojo.`, { title: "¿Eliminar esta línea?", ok: "Eliminar", warn: true }))) return;
      markDeleted(tr, true);
      persist({ mantenerEstado: true });
      return;
    }
    const back = event.target.closest(".line-restore");
    if (back) {
      markDeleted(back.closest("tr"), false);
      persist({ mantenerEstado: true });
    }
  });
  eye?.addEventListener("click", () => {
    const on = editor?.classList.toggle("show-deleted");
    eye.setAttribute("aria-pressed", on ? "true" : "false");
    eye.setAttribute("aria-label", on ? "Ocultar líneas eliminadas" : "Ver líneas eliminadas");
    eye.title = on ? "Solo las líneas eliminadas" : "Ver líneas eliminadas";
    eye.classList.toggle("is-on", Boolean(on));
    body?.dispatchEvent(new CustomEvent("ficha-repaginate"));
  });
  updateEye();
  window.addEventListener("beforeunload", (event) => {
    if (allowLeave || !pending()) return;
    event.preventDefault();
    event.returnValue = "";
  });
  document.addEventListener("click", async (event) => {
    const link = event.target.closest("a[href]");
    if (!link || link.target === "_blank" || allowLeave || !pending()) return;
    event.preventDefault();
    if (await ask(leaveText, { title: "Cambios sin guardar", ok: "Salir" })) {
      allowLeave = true;
      window.location.href = link.href;
    }
  });
  save?.addEventListener("click", async () => {
    if (!ack?.checked || !pending()) return;
    save.disabled = true;
    persist();
  });
})();
</script>
"""


def _ficha_filter_script() -> str:
    return r"""
<script>
(() => {
  const table = document.querySelector(".ficha-ledger");
  const body = document.getElementById("ficha-lines-body");
  if (!table || !body) return;
  const parseAmount = (raw) => {
    const text = (raw || "").trim().replace(",", ".");
    if (!text) return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  };
  const boxesOf = (name) => [...table.querySelectorAll(`input[data-fg="${name}"]`)];
  const selected = (name) => {
    const boxes = boxesOf(name);
    if (!boxes.length) return null;
    const on = boxes.filter((box) => box.checked).map((box) => box.value);
    if (!on.length) return new Set();
    if (on.length === boxes.length) return null;
    return new Set(on);
  };
  const allows = (name, value) => {
    const picked = selected(name);
    if (picked === null) return true;
    return picked.has(value);
  };
  const inRange = (raw, minId, maxId) => {
    if (!raw) return true;
    const amount = Number(raw);
    if (!Number.isFinite(amount)) return true;
    const min = parseAmount(document.getElementById(minId)?.value);
    const max = parseAmount(document.getElementById(maxId)?.value);
    if (min !== null && amount < min) return false;
    if (max !== null && amount > max) return false;
    return true;
  };
  const syncFunnels = () => {
    for (const th of table.querySelectorAll("th.th-filter")) {
      const btn = th.querySelector(".funnel");
      const pop = th.querySelector(".filter-pop");
      if (!btn || !pop) continue;
      const boxes = [...pop.querySelectorAll("input[data-fg]")];
      const boxDirty = boxes.length > 0 && boxes.some((box) => !box.checked);
      const rangeDirty = [...pop.querySelectorAll("input[type=number]")].some((el) => (el.value || "").trim());
      btn.classList.toggle("on", boxDirty || rangeDirty);
    }
  };
  const PAGE_SIZE = 15;
  let page = 1;
  const prev = document.getElementById("ficha-prev");
  const next = document.getElementById("ficha-next");
  const pagesBox = document.getElementById("ficha-pages");
  const pagerLabel = document.getElementById("ficha-pager-label");
  const eyeOn = () => document.getElementById("ficha-lines-editor")?.classList.contains("show-deleted");
  const matchesLine = (tr) => allows("line-id", tr.dataset.lineId || "")
    && allows("line-desc", tr.dataset.lineDesc || "")
    && allows("line-rate", tr.dataset.lineRate || "")
    && inRange(tr.dataset.lineBase, "f-line-base-min", "f-line-base-max")
    && inRange(tr.dataset.lineIva, "f-line-iva-min", "f-line-iva-max")
    && inRange(tr.dataset.lineTotal, "f-line-total-min", "f-line-total-max");
  const paintPager = (pages, matched) => {
    if (pagesBox) {
      pagesBox.replaceChildren();
      for (let i = 1; i <= pages; i += 1) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "pager-num" + (i === page ? " is-on" : "");
        btn.textContent = String(i);
        btn.setAttribute("aria-label", `Página ${i}`);
        if (i === page) btn.setAttribute("aria-current", "page");
        btn.addEventListener("click", () => {
          page = i;
          apply({ keepPage: true });
        });
        pagesBox.appendChild(btn);
      }
    }
    if (pagerLabel) {
      if (!matched) pagerLabel.textContent = "0 de 0";
      else {
        const start = (page - 1) * PAGE_SIZE;
        const end = Math.min(start + PAGE_SIZE, matched);
        pagerLabel.textContent = `${start + 1}–${end} de ${matched}`;
      }
    }
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= pages || matched === 0;
  };
  let apply = (opts = {}) => {
    const rows = [...body.querySelectorAll("tr[data-line]")];
    const showingDeleted = eyeOn();
    const matched = [];
    for (const tr of rows) {
      const deleted = tr.dataset.deleted === "1";
      if (showingDeleted) {
        if (!deleted) {
          tr.hidden = true;
          continue;
        }
      } else if (deleted) {
        tr.hidden = false;
        continue;
      }
      if (!matchesLine(tr)) {
        tr.hidden = true;
        continue;
      }
      matched.push(tr);
    }
    const pages = Math.max(1, Math.ceil(matched.length / PAGE_SIZE) || 1);
    if (opts.last) page = pages;
    else if (!opts.keepPage) page = 1;
    page = Math.min(Math.max(1, page), pages);
    const start = (page - 1) * PAGE_SIZE;
    rows.forEach((tr) => tr.classList.remove("is-band"));
    matched.forEach((tr, index) => {
      const onPage = index >= start && index < start + PAGE_SIZE;
      tr.hidden = !onPage;
      tr.classList.toggle("is-band", onPage && (index - start) % 2 === 1);
    });
    paintPager(pages, matched.length);
    syncFunnels();
  };
  const placePop = (chip, pop) => {
    const width = Math.min(300, window.innerWidth - 24);
    pop.style.inset = "auto";
    pop.style.margin = "0";
    pop.style.width = `${width}px`;
    const box = chip.getBoundingClientRect();
    pop.style.left = `${Math.min(Math.max(12, box.left), window.innerWidth - width - 12)}px`;
    pop.style.top = `${box.bottom + 8}px`;
  };
  body.addEventListener("input", (event) => {
    const input = event.target.closest("input.line-edit");
    const tr = input?.closest("tr");
    if (!input || !tr) return;
    const key = { codigo: "lineId", descripcion: "lineDesc", base: "lineBase", iva_tipo: "lineRate", iva_cuota: "lineIva", importe: "lineTotal" }[input.dataset.f];
    if (key) tr.dataset[key] = input.value;
    apply({ keepPage: true });
  });
  table.addEventListener("change", (event) => {
    if (event.target.matches("input[data-fg], input[type=number]")) apply();
  });
  table.addEventListener("input", (event) => {
    const search = event.target.closest("[data-filter-search]");
    if (search) {
      const q = search.value.trim().toLowerCase();
      const pop = search.closest(".filter-pop");
      for (const opt of pop?.querySelectorAll(".filter-opt") || []) {
        opt.hidden = Boolean(q) && !opt.textContent.toLowerCase().includes(q);
      }
      return;
    }
    if (event.target.matches("input[type=number]")) apply();
  });
  table.addEventListener("click", (event) => {
    const button = event.target.closest("[data-filter-all]");
    if (!button) return;
    const pop = button.closest(".filter-pop");
    const boxes = [...(pop?.querySelectorAll(".filter-opt:not([hidden]) input[data-fg]") || [])];
    const allOn = boxes.length > 0 && boxes.every((box) => box.checked);
    for (const box of boxes) box.checked = !allOn;
    apply();
  });
  for (const chip of table.querySelectorAll(".funnel[popovertarget]")) {
    const pop = document.getElementById(chip.getAttribute("popovertarget"));
    if (!pop) continue;
    pop.addEventListener("toggle", (event) => {
      const open = event.newState === "open";
      chip.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) placePop(chip, pop);
    });
  }
  prev?.addEventListener("click", () => {
    page -= 1;
    apply({ keepPage: true });
  });
  next?.addEventListener("click", () => {
    page += 1;
    apply({ keepPage: true });
  });
  body.addEventListener("ficha-repaginate", (event) => {
    apply({ keepPage: !event.detail?.last, last: Boolean(event.detail?.last) });
  });
  let sortKey = "id";
  let sortDir = 1;
  const lineValue = (tr, key) => {
    if (key === "n") return Number(tr.querySelector("td")?.textContent || 0);
    if (key === "id") return tr.dataset.lineId || "";
    if (key === "desc") return tr.dataset.lineDesc || "";
    if (key === "uds") return Number(tr.querySelector("[data-f=cantidad]")?.value || 0);
    if (key === "base") return Number(tr.dataset.lineBase || 0);
    if (key === "rate") return Number(tr.dataset.lineRate || 0);
    if (key === "iva") return Number(tr.dataset.lineIva || 0);
    if (key === "total") return Number(tr.dataset.lineTotal || 0);
    return "";
  };
  const compareSort = (a, b) => {
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b), "es", { numeric: true, sensitivity: "base" });
  };
  const sortLines = () => {
    const list = [...body.querySelectorAll("tr[data-line]")];
    list.sort((a, b) => sortDir * compareSort(lineValue(a, sortKey), lineValue(b, sortKey)));
    for (const tr of list) body.appendChild(tr);
    table.querySelectorAll("thead th[data-sort]").forEach((th) => {
      const on = th.dataset.sort === sortKey;
      th.classList.toggle("is-sorted", on);
      th.classList.toggle("is-desc", on && sortDir < 0);
    });
  };
  const applySorted = apply;
  apply = (opts = {}) => {
    sortLines();
    applySorted(opts);
  };
  table.querySelectorAll("thead th[data-sort]").forEach((th) => {
    th.addEventListener("click", (event) => {
      if (event.target.closest(".funnel, .filter-pop")) return;
      const key = th.dataset.sort;
      if (!key) return;
      if (sortKey === key) sortDir *= -1;
      else { sortKey = key; sortDir = 1; }
      apply();
    });
  });
  apply();
})();
</script>
"""


def _docs_chip(item: dict) -> str:
    bits: list[str] = []
    n_docs = int(item.get("n_docs") or 0)
    if n_docs > 1:
        bits.append(
            f'<span class="docs-chip" title="Ficheros raw de esta factura">{n_docs} docs</span>'
        )
    if item.get("er_estado") == "conflicto":
        bits.append(
            '<span class="docs-chip warn" title="Mismo número, importes distintos">conflicto</span>'
        )
    if not bits:
        return ""
    return " " + "".join(bits)


def _n_docs(asiento: Asiento, n_docs_map: dict[int, int]) -> int:
    if asiento.factura_id:
        counted = n_docs_map.get(asiento.factura_id, 0)
        if counted:
            return counted
    return 1 if asiento.documento_id else 0


def _asiento_view(
    asiento: Asiento,
    nombres: dict[str, str],
    extra_casillas: dict[str, str],
    inmuebles: dict[int, str],
    *,
    n_docs: int = 0,
    er_estado: str = "",
    titular_nif: str = "",
) -> dict:
    codigo = asiento.cuenta_codigo or ""
    cuenta_nombre = nombres.get(codigo, "Sin clasificar")
    casilla = casilla_clave(codigo, extra_casillas)
    casilla_meta = INDEX_CI.get(casilla)
    casilla_etiqueta = casilla_meta.etiqueta if casilla_meta else "Sin clasificar"
    documento = asiento.documento
    doc_path = ""
    doc_name = ""
    if documento is not None and documento.ruta_almacenada:
        path = Path(documento.ruta_almacenada)
        if path.is_file():
            doc_path = path.as_uri()
        doc_name = documento.nombre_original
    total = q2(asiento.total)
    lineas = lineas_de_asiento(asiento)
    faltas = [
        item["detail"]
        for item in criterios_calidad(
            numero=asiento.numero_factura,
            fecha=asiento.fecha.strftime("%d/%m/%Y") if asiento.fecha else "",
            emisor=asiento.emisor,
            nif=asiento.nif_emisor,
            base=asiento.base,
            iva=asiento.iva_cuota,
            total=total,
            rubro=cuenta_nombre if codigo else "",
            lineas=lineas,
            titular_nif=titular_nif,
        )
        if not item["ok"]
    ]
    conf_ocr = q2(documento.confianza) if documento is not None else None
    conf_class = q2(asiento.confianza_clasificacion)
    baja = (not asiento.validado) and (
        (conf_ocr is not None and conf_ocr < Decimal("0.80"))
        or (conf_class is not None and conf_class < Decimal("0.80"))
        or conf_class is None
        or asiento.estado == "pendiente"
    )
    conf_scores = [value for value in (conf_ocr, conf_class) if value is not None]
    conf_min = min(conf_scores) if conf_scores else None
    return {
        "id": asiento.id,
        "fecha": asiento.fecha.isoformat() if asiento.fecha else "",
        "fecha_label": asiento.fecha.strftime("%d/%m/%Y") if asiento.fecha else "—",
        "emisor": asiento.emisor or "—",
        "nif": asiento.nif_emisor or "—",
        "numero": asiento.numero_factura or "—",
        "base": asiento.base,
        "iva": asiento.iva_cuota,
        "iva_tipo": asiento.iva_tipo,
        "total": total,
        "total_num": float(total) if total is not None else 0.0,
        "cuenta": cuenta_nombre if codigo else "",
        "cuenta_nombre": cuenta_nombre,
        "tipo": asiento.tipo,
        "estado": asiento.estado,
        "estado_label": ESTADO_LABEL.get(asiento.estado, asiento.estado),
        "inmueble": inmuebles.get(asiento.inmueble_id or 0, ""),
        "doc_uri": doc_path,
        "has_doc": bool(doc_path),
        "doc_name": doc_name,
        "casilla": casilla,
        "casilla_etiqueta": casilla_etiqueta,
        "conf_ocr": conf_ocr,
        "conf_class": conf_class,
        "conf_min_pct": _conf_pct(conf_min),
        "conf_ocr_pct": _conf_pct(conf_ocr),
        "conf_class_pct": _conf_pct(conf_class),
        "validado": bool(asiento.validado),
        "baja": baja,
        "motivo_rechazo": asiento.motivo_rechazo or "",
        "duplicado_de_id": asiento.duplicado_de_id,
        "duplicado_nivel": asiento.duplicado_nivel,
        "cmd_confirmar": (
            f'aeat-hub reclasificar {asiento.id} "{cuenta_nombre}"' if codigo else ""
        ),
        "cmd_validar": f"aeat-hub validar {asiento.id}",
        "n_docs": n_docs,
        "er_estado": er_estado,
        "n_articulos": articulos_label(lineas),
        "calidad_faltas": faltas,
    }


def _conf_pct(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 100))


def _iva_col_label(lineas: list[dict]) -> str:
    tipos = {item.get("iva_tipo") for item in lineas if item.get("iva_tipo")}
    if len(tipos) != 1:
        return "IVA"
    tipo = q2(next(iter(tipos)))
    if tipo is None:
        return "IVA"
    label = str(int(tipo)) if tipo == tipo.to_integral_value() else format(tipo, "f").rstrip("0").rstrip(".")
    return f"IVA ({label} %)"


def _sum_lineas(lineas: list[dict], key: str) -> Decimal | None:
    acc = Decimal("0.00")
    n = 0
    for item in lineas:
        parsed = parse_money_field(item.get(key))
        if parsed is not None:
            acc += parsed
            n += 1
    return q2(acc) if n else None


def _suma_importes(lineas: list[dict]) -> Decimal | None:
    return _sum_lineas(lineas, "importe")


def _cuadra_con_total(suma: Decimal | None, total: Decimal | None) -> bool:
    if suma is None or total is None:
        return False
    return abs(q2(suma) - q2(total)) <= TOLERANCIA_TOTAL


def _elementos_label(n: int) -> str:
    return "1 elemento" if n == 1 else f"{n} elementos"


def _hueco(value: object) -> bool:
    return str(value or "").strip() in {"", "—", "-"}


def _lista_corta(items: list[str]) -> str:
    head = ", ".join(items[:3])
    extra = len(items) - 3
    if extra > 0:
        return f"{head} y {extra} más"
    return head


def criterios_calidad(
    *,
    numero: object,
    fecha: object,
    emisor: object,
    nif: object,
    base: object,
    iva: object,
    total: object,
    rubro: object,
    lineas: list[dict],
    titular_nif: str = "",
) -> list[dict]:
    """Mínimo para fiarse de un asiento. Solo el detalle de lo que falta."""
    checks: list[dict] = []

    def add(key: str, ok: bool, label: str, detail: str) -> None:
        checks.append({"id": key, "ok": ok, "label": label, "detail": "" if ok else detail})

    add("numero", not _hueco(numero), "Número", "Falta el número de factura.")
    add("fecha", not _hueco(fecha), "Fecha", "Falta la fecha de compra.")
    add("emisor", not _hueco(emisor), "Emisor", "Falta el nombre del emisor.")
    nif_txt = str(nif or "").strip()
    if _hueco(nif_txt):
        add("nif", False, "NIF", "Falta el NIF del emisor.")
    elif not is_valid_nif(nif_txt):
        add("nif", False, "NIF", "El NIF del emisor no tiene un formato válido.")
    elif (
        titular_nif
        and not is_placeholder_nif(titular_nif)
        and normalize_nif(nif_txt) == normalize_nif(titular_nif)
    ):
        add("nif", False, "NIF", "El NIF es el del titular, no el del emisor.")
    else:
        add("nif", True, "NIF", "")
    add("base", base is not None and not _hueco(base), "Base", "Falta la base imponible.")
    add("iva", iva is not None and not _hueco(iva), "IVA", "Falta la cuota de IVA.")
    add("total", total is not None and not _hueco(total), "Total", "Falta el total de la factura.")
    add(
        "rubro",
        str(rubro or "").strip() not in {"", "—", "Sin clasificar"},
        "Rubro",
        "El rubro sigue sin clasificar.",
    )
    base_q = q2(base) if base is not None else None
    iva_q = q2(iva) if iva is not None else None
    total_q = q2(total) if total is not None else None
    if base_q is not None and iva_q is not None and total_q is not None:
        add(
            "desglose",
            abs(base_q + iva_q - total_q) <= TOLERANCIA_TOTAL,
            "Base+IVA",
            "Base más IVA no da el total de la factura.",
        )

    activas = [item for item in lineas if not item.get("eliminada")]
    if not activas:
        add("ids", False, "Ids", "No hay líneas, así que no hay ids de artículo.")
        add("conceptos", False, "Conceptos", "No hay líneas, así que no hay conceptos.")
        add("importes", False, "Importes", "No hay líneas, así que no hay importes.")
        add("suma", False, "Suma", "No hay importes que contrastar con el total del libro.")
        return checks

    sin_id: list[str] = []
    sin_concepto: list[str] = []
    sin_importe: list[str] = []
    for idx, item in enumerate(activas, start=1):
        nombre = str(item.get("descripcion") or "").strip() or f"línea {idx}"
        if _hueco(item.get("codigo")):
            sin_id.append(nombre)
        if _hueco(item.get("descripcion")):
            sin_concepto.append(f"línea {idx}")
        if parse_money_field(item.get("importe")) is None:
            sin_importe.append(nombre)
    add("ids", not sin_id, "Ids", f"Falta el id en {_lista_corta(sin_id)}.")
    add("conceptos", not sin_concepto, "Conceptos", f"Falta el concepto en {_lista_corta(sin_concepto)}.")
    add("importes", not sin_importe, "Importes", f"Falta el importe en {_lista_corta(sin_importe)}.")
    suma = _suma_importes(activas)
    n = sum(1 for item in activas if parse_money_field(item.get("importe")) is not None)
    if _cuadra_con_total(suma, total_q):
        add("suma", True, "Suma", "")
        checks[-1]["title"] = (
            f"Suma de {_elementos_label(n or len(activas))} {format_euro(suma)} "
            f"= total del libro {format_euro(total_q)}."
        )
    elif suma is None or total_q is None:
        add("suma", False, "Suma", "Falta el total de la factura o el importe de las líneas.")
    else:
        delta = abs(q2(suma) - total_q)
        add(
            "suma",
            False,
            "Suma",
            (
                f"Suma de {_elementos_label(n or len(activas))} {format_euro(suma)} ≠ "
                f"total del libro {format_euro(total_q)} (diferencia {format_euro(delta)}). "
                "Puede faltar un artículo, o un importe se ha mezclado con otra línea."
            ),
        )
    return checks


def _criterios_html(checks: list[dict], *, total: object = None) -> str:
    ok_n = sum(1 for item in checks if item["ok"])
    pct = int(round(100 * ok_n / len(checks))) if checks else 0
    if checks and ok_n == len(checks):
        tone, label = "ok", "Lista"
    elif pct >= 80:
        tone, label = "warn", "Revisar"
    else:
        tone, label = "bad", "Revisar"
    items = []
    for item in checks:
        state = "is-ok" if item["ok"] else "is-bad"
        nota = escape(item.get("title") or "")
        title_attr = f' title="{nota}"' if nota else ""
        detail = f"<em>{escape(item['detail'])}</em>" if item["detail"] else ""
        items.append(
            f'<li data-check="{escape(item["id"])}" data-ok="{"1" if item["ok"] else "0"}" '
            f'class="{state}"><span{title_attr}>{escape(item["label"])}</span>{detail}</li>'
        )
    fallos = [item for item in checks if not item["ok"]]
    fallos_html = "".join(
        f'<li class="is-bad"><span>{escape(item["label"])}</span>'
        f"<em>{escape(item['detail'])}</em></li>"
        for item in fallos
    ) or ""
    fails_hidden = "" if fallos else " hidden"
    quantized = q2(total) if total is not None else None
    total_attr = f' data-total="{quantized:.2f}"' if quantized is not None else ""
    return (
        f'<div class="ficha-score" id="ficha-score"{total_attr}>'
        f'<div class="ficha-score-cab">'
        f'<span class="q-chip q-{tone}" id="ficha-score-chip">'
        f'<i class="q-dot" aria-hidden="true"></i>'
        f'<span id="ficha-score-label">{label}</span>'
        f'<span class="q-score" id="ficha-score-pct">{pct} %</span></span>'
        f'<button type="button" class="q-i-btn" popovertarget="ficha-score-pop" '
        f'aria-label="Qué se comprueba en esta factura" aria-expanded="false">i</button>'
        f"</div>"
        f'<ul class="q-checks q-solo-fallos" id="ficha-score-fails"{fails_hidden}>{fallos_html}</ul>'
        f'<div id="ficha-score-pop" popover="auto" class="q-pop q-pop-score" role="tooltip">'
        f"<strong>Comprobaciones de la factura</strong>"
        f'<ul class="q-checks q-pop-list" id="ficha-score-list">{"".join(items)}</ul>'
        "</div>"
        "</div>"
    )


def _filter_amount(min_id: str, max_id: str) -> str:
    return (
        f'<label class="filter-field">Mínimo'
        f'<input id="{min_id}" type="number" min="0" step="0.01" placeholder="0"></label>'
        f'<label class="filter-field">Máximo'
        f'<input id="{max_id}" type="number" min="0" step="0.01" placeholder="Sin tope"></label>'
    )


def _unique_labels(values: list[str]) -> list[tuple[str, str]]:
    seen: list[str] = []
    for value in values:
        text = value.strip()
        if text and text not in seen:
            seen.append(text)
    return [(item, item) for item in seen]


def _tipo_visible(value: object) -> str:
    if value in (None, ""):
        return ""
    numero = Decimal(str(value).replace(",", "."))
    if numero == numero.to_integral_value():
        return str(int(numero))
    return format(numero, "f").rstrip("0").rstrip(".")


def _tipo_linea(item: dict) -> str:
    raw = item.get("iva_tipo")
    if raw not in (None, ""):
        return _tipo_visible(raw)
    base = parse_money_field(item.get("base"))
    cuota = parse_money_field(item.get("iva_cuota"))
    if base and cuota is not None and base != 0:
        implied = (cuota / base) * Decimal("100")
        for rate in (Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0")):
            if abs(implied - rate) < Decimal("0.8"):
                return str(int(rate))
        return _tipo_visible(q2(implied))
    return "21"


def _lineas_thead(lineas: list[dict]) -> str:
    ids = _unique_labels([str(item.get("codigo") or "") for item in lineas])
    names = _unique_labels([str(item.get("descripcion") or "") for item in lineas])
    return (
        "<thead><tr>"
        '<th class="col-sticky" data-sort="n" data-sort-type="num"><span class="th-label">#</span></th>'
        + _filter_th("Id", "pop-line-id", _filter_checks("line-id", ids), sort="id")
        + _filter_th("Concepto", "pop-line-desc", _filter_checks("line-desc", names), sort="desc")
        + '<th class="num" data-sort="uds" data-sort-type="num"><span class="th-label">Uds.</span></th>'
        + _filter_th("Subtotal", "pop-line-base", _filter_amount("f-line-base-min", "f-line-base-max"), "num", sort="base", sort_type="num")
        + _filter_th("IVA %", "pop-line-rate", _filter_checks("line-rate", _unique_labels([_tipo_linea(item) for item in lineas])), sort="rate", sort_type="num")
        + _filter_th("IVA", "pop-line-iva", _filter_amount("f-line-iva-min", "f-line-iva-max"), "num", sort="iva", sort_type="num")
        + _filter_th("Total", "pop-line-total", _filter_amount("f-line-total-min", "f-line-total-max"), "num", sort="total", sort_type="num")
        + '<th class="line-actions col-estado"><span class="th-label">Acciones</span></th>'
        + "</tr></thead>"
    )


def _line_field(
    field: str,
    value: object,
    label: str,
    *,
    money: bool,
    clip: bool = False,
    rate: bool = False,
    calc: bool = False,
    qty: bool = False,
) -> str:
    if rate:
        raw = _tipo_visible(value) if value not in (None, "") else ""
        shown = f"{raw} %" if raw else "—"
        kind = ' type="number" min="0" max="100" step="0.01"'
    elif qty:
        raw = "1" if value in (None, "") else str(value)
        if "." in raw:
            raw = raw.rstrip("0").rstrip(".")
        shown = raw or "1"
        kind = ' type="number" min="0" step="0.001"'
    else:
        raw = "" if value is None or value == "" else str(value)
        shown = format_euro(value) if money or calc else (raw or "—")
        kind = ' type="number" min="0" step="0.01"' if money or calc else ""
    classes = ["num", "cell-nowrap"] if money or calc or rate or qty else (["cell-clip"] if clip else ["cell-nowrap"])
    if field == "codigo":
        classes = ["mono", "cell-nowrap"]
    view_class = "line-view cell-text" if clip else "line-view"
    title = f' title="{escape(shown)}"' if clip and shown != "—" else ""
    input_class = "line-edit line-calc" if calc else "line-edit"
    klass = f' class="{" ".join(classes)}"'
    return (
        f"<td{klass}>"
        f'<span class="{view_class}"{title}>{escape(shown)}</span>'
        f'<input class="{input_class}" disabled data-f="{field}" data-orig="{escape(raw)}"{kind} '
        f'value="{escape(raw)}" aria-label="{label}">'
        "</td>"
    )


def _lineas_rows_html(lineas: list[dict]) -> str:
    rows = []
    for idx, item in enumerate(lineas, start=1):
        borrada = bool(item.get("eliminada"))
        rows.append(
            f'<tr data-line="1" data-deleted="{"1" if borrada else "0"}" '
            f'data-was-deleted="{"1" if borrada else "0"}" class="{"is-deleted" if borrada else ""}" '
            f'data-line-id="{escape(str(item.get("codigo") or ""))}" '
            f'data-line-desc="{escape(str(item.get("descripcion") or ""))}" '
            f'data-line-base="{escape("" if item.get("base") in (None, "") else str(item.get("base")))}" '
            f'data-line-rate="{escape(_tipo_linea(item))}" '
            f'data-line-iva="{escape("" if item.get("iva_cuota") in (None, "") else str(item.get("iva_cuota")))}" '
            f'data-line-total="{escape("" if item.get("importe") in (None, "") else str(item.get("importe")))}">'
            f'<td class="num col-sticky">{idx}</td>'
            + _line_field("codigo", item.get("codigo"), "Id", money=False)
            + _line_field("descripcion", item.get("descripcion"), "Concepto", money=False, clip=True)
            + _line_field("cantidad", item.get("cantidad") or "1", "Unidades", money=False, qty=True)
            + _line_field("base", item.get("base"), "Subtotal", money=True)
            + _line_field("iva_tipo", _tipo_linea(item), "IVA %", money=False, rate=True)
            + _line_field("iva_cuota", item.get("iva_cuota"), "IVA", money=False, calc=True)
            + _line_field("importe", item.get("importe"), "Total de línea", money=True)
            + '<td class="line-actions cell-estado"><div class="row-actions">'
            + f'<button type="button" class="row-edit line-edit-btn" title="Editar línea" '
            + f'aria-label="Editar línea {idx}">{_PENCIL_SVG}</button>'
            + f'<button type="button" class="row-edit line-save" title="Guardar línea" '
            + f'aria-label="Guardar línea {idx}">{_DISK_SVG}</button>'
            + f'<button type="button" class="row-edit line-del" title="Eliminar línea" '
            + f'aria-label="Eliminar línea {idx}">{_TRASH_SVG}</button>'
            + f'<button type="button" class="row-edit line-restore" title="Recuperar línea" '
            + f'aria-label="Recuperar línea {idx}">{_RESTORE_SVG}</button>'
            + "</div></td></tr>"
        )
    return "".join(rows)


def _lineas_tfoot_html(lineas: list[dict]) -> str:
    if not any(item.get("importe") or item.get("base") for item in lineas):
        return ""
    celdas = (
        ("Subtotal", _sum_lineas(lineas, "base"), ""),
        ("IVA", _sum_lineas(lineas, "iva_cuota"), ""),
        ("Total", _sum_lineas(lineas, "importe"), " is-total"),
    )
    bits = "".join(
        f'<div class="line-total{extra}"><span>{label}</span>'
        f"<strong>{escape(format_euro(valor))}</strong></div>"
        for label, valor, extra in celdas
    )
    return f'<aside class="line-totals" aria-label="Totales de las líneas">{bits}</aside>'


def _cola_revision(asientos: list[dict]) -> list[dict]:
    items = [item for item in asientos if item["estado"] != "duplicado" and not item["validado"]]

    def sort_key(item: dict) -> tuple:
        min_pct = item["conf_min_pct"]
        return (
            0 if item["baja"] else 1,
            0 if item["estado"] == "pendiente" else 1,
            min_pct if min_pct is not None else -1,
            item["id"],
        )

    return sorted(items, key=sort_key)



def _sum_tipo(rows: list[Asiento], tipo: str) -> Decimal:
    total = ZERO
    for row in rows:
        if row.tipo == tipo:
            total += q2(row.total) or ZERO
    return total


def _by_month(rows: list[Asiento]) -> list[dict]:
    buckets = {month: {"gastos": ZERO, "ingresos": ZERO} for month in range(1, 13)}
    for row in rows:
        if row.fecha is None:
            continue
        slot = buckets[row.fecha.month]
        amount = q2(row.total) or ZERO
        if row.tipo == TIPO_INGRESO:
            slot["ingresos"] += amount
        elif row.tipo == TIPO_GASTO:
            slot["gastos"] += amount
    return [
        {
            "mes": MESES[idx - 1],
            "mes_largo": MESES_LARGO[idx - 1],
            "gastos": buckets[idx]["gastos"],
            "ingresos": buckets[idx]["ingresos"],
        }
        for idx in range(1, 13)
    ]


def _etiqueta_emisor(label: str) -> tuple[str, str]:
    text = label.strip() or "Sin emisor"
    if len(text) <= 32:
        return text, text
    return text[:31] + "…", text


IVA_TIPOS_ORDEN = ("21", "10", "4", "0", "otros", "sin")
IVA_TIPOS_LABEL = {
    "21": "21 %",
    "10": "10 %",
    "4": "4 %",
    "0": "0 %",
    "otros": "Otros tipos",
    "sin": "Sin tipo",
}


def _iva_key(tipo: Decimal | None) -> str:
    if tipo is None:
        return "sin"
    for conocido in (Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0")):
        if tipo == conocido:
            return str(int(conocido))
    return "otros"


def _iva_por_tipo(rows: list[Asiento]) -> list[dict]:
    """IVA soportado de gastos y mejoras, agrupado por tipo (21/10/4/0)."""
    buckets: dict[str, dict] = {}
    for row in rows:
        if row.tipo not in {TIPO_GASTO, TIPO_MEJORA}:
            continue
        slot = buckets.setdefault(
            _iva_key(q2(row.iva_tipo)),
            {"base": ZERO, "cuota": ZERO, "total": ZERO},
        )
        slot["base"] += q2(row.base) or ZERO
        slot["cuota"] += q2(row.iva_cuota) or ZERO
        slot["total"] += q2(row.total) or ZERO
    return [
        {"label": IVA_TIPOS_LABEL[key], **buckets[key]}
        for key in IVA_TIPOS_ORDEN
        if key in buckets
    ]


def _rank_emisores(asientos: list[dict]) -> tuple[list[dict], Decimal]:
    buckets: dict[str, dict] = {}
    total = ZERO
    for item in asientos:
        if item["estado"] in ("duplicado", "rechazado") or item["tipo"] != TIPO_GASTO:
            continue
        amount = q2(item["total"]) or ZERO
        if amount <= ZERO:
            continue
        raw = str(item.get("emisor") or "").strip()
        key = raw.casefold() or "sin emisor"
        slot = buckets.get(key)
        if slot is None:
            buckets[key] = {"label": raw or "Sin emisor", "total": amount}
        else:
            slot["total"] += amount
        total += amount
    ranked = sorted(buckets.values(), key=lambda row: (-row["total"], row["label"].casefold()))
    return ranked, total


def _emisores_para_grafico(asientos: list[dict]) -> list[dict]:
    ranked, _total = _rank_emisores(asientos)
    if len(ranked) <= 6:
        return ranked
    resto = sum((row["total"] for row in ranked[6:]), ZERO)
    return [*ranked[:6], {"label": "Resto", "total": resto}]


def _frase_anio(asientos: list[dict], por_mes: list[dict]) -> str:
    ranked, total = _rank_emisores(asientos)
    if total <= ZERO or not ranked:
        return ""
    top = ranked[0]
    share = int(round(float(top["total"] / total * 100)))
    if share >= 50:
        shown, _full = _etiqueta_emisor(top["label"])
        return f"{shown} concentra el {share} % del gasto ({format_euro(top['total'])})."
    peak = max(por_mes, key=lambda item: item["gastos"])
    if peak["gastos"] > ZERO:
        month_share = int(round(float(peak["gastos"] / total * 100)))
        if month_share >= 40:
            return (
                f"El gasto se concentra en {peak['mes_largo']}: "
                f"{format_euro(peak['gastos'])}, el {month_share} % del año."
            )
        last = next(item for item in reversed(por_mes) if item["gastos"] > ZERO)
        return f"Hasta {last['mes_largo']} van {format_euro(total)} en gasto."
    return ""


def _aviso_linea(data: dict) -> str:
    bits: list[str] = []
    pendientes = int(data.get("n_pendientes") or 0)
    if pendientes:
        bits.append("1 asiento por revisar" if pendientes == 1 else f"{pendientes} asientos por revisar")
    if (data.get("ingresos") or ZERO) <= ZERO:
        bits.append("ejercicio sin ingresos")
    duplicados = int(data.get("n_duplicados") or 0)
    if duplicados:
        bits.append(
            "1 duplicado fuera de los totales"
            if duplicados == 1
            else f"{duplicados} duplicados fuera de los totales"
        )
    conflictos = int(data.get("n_conflictos") or 0)
    if conflictos:
        bits.append(
            "1 conflicto de agrupación (mismo número, total distinto)"
            if conflictos == 1
            else f"{conflictos} conflictos de agrupación (mismo número, total distinto)"
        )
    sin_fecha = data.get("sin_fecha") or []
    if sin_fecha:
        enlaces = " ".join(
            f'<a href="/asiento/{item["id"]}">#{item["id"]}</a>' for item in sin_fecha[:5]
        )
        resto = f" y {len(sin_fecha) - 5} más" if len(sin_fecha) > 5 else ""
        bits.append(
            f'{len(sin_fecha)} sin fecha, fuera de todo ejercicio: {enlaces}{resto}'
        )
    if not bits:
        return ""
    return f'<p class="insight-aviso">{" · ".join(bits)}</p>'


def _by_nature(
    rows: list[Asiento],
    extra_casillas: dict[str, str],
    nombres: dict[str, str],
    regimen: str,
) -> list[dict]:
    buckets: dict[str, Decimal] = defaultdict(lambda: ZERO)
    tipos: dict[str, str] = {}
    for row in rows:
        label = _nature_label(row.cuenta_codigo, extra_casillas, nombres, regimen)
        buckets[label] += q2(row.total) or ZERO
        tipos.setdefault(label, row.tipo)
    ordered = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    return [{"label": label, "total": total, "tipo": tipos[label]} for label, total in ordered if total]


def _nature_label(
    codigo: str | None,
    extra_casillas: dict[str, str],
    nombres: dict[str, str],
    regimen: str,
) -> str:
    if not codigo:
        return "Sin clasificar"
    if regimen == REGIMEN_AE:
        return nombres.get(codigo, "Sin clasificar")
    clave = casilla_clave(codigo, extra_casillas)
    meta = INDEX_CI.get(clave)
    return meta.etiqueta if meta else "Sin clasificar"


def _masthead(data: dict) -> str:
    inmueble = data.get("inmueble") or ""
    inmueble_wrap = (
        f'<span id="mast-inmueble-wrap"> · <span id="mast-inmueble">{escape(inmueble)}</span></span>'
        if inmueble
        else '<span id="mast-inmueble-wrap" hidden> · <span id="mast-inmueble"></span></span>'
    )
    badge = ""
    if data["cola_revision"]:
        badge = f'<span class="tab-badge">{len(data["cola_revision"])}</span>'
    dup_badge = ""
    n_dups_tab = int(data.get("n_duplicados") or 0) + len(data.get("sospechosos") or [])
    if n_dups_tab:
        dup_badge = f'<span class="tab-badge">{n_dups_tab}</span>'
    show_inmueble = "1" if (inmueble or data["regimen"] == REGIMEN_CI) else "0"
    return f"""
<header class="mast">
  <div class="wrap mast-grid">
    <div>
      <p class="eyebrow">AEAT Hub · libro auxiliar</p>
      <h1 class="mast-h1">
        <span id="mast-nombre">{escape(data["nombre"])}</span>
        <span id="mast-kicker">{escape(data["codigo"])} · {data["year"]}</span>
        <button type="button" class="row-edit mast-edit" id="mast-edit"
          data-has-inmueble="{show_inmueble}"
          title="Personalizar títulos" aria-label="Personalizar títulos del libro">{_PENCIL_SVG}</button>
      </h1>
      <p class="meta">
        <span id="mast-titular">{escape(data["titular"])}</span>
        · <span id="mast-regimen">{escape(data["regimen_label"])}</span>{inmueble_wrap}
      </p>
      <p class="mast-strip">
        {data["n_pendientes"]} por revisar · {data["n_sin_validar"]} sin validar ·
        neto {escape(format_euro(data["resultado"]))}
      </p>
    </div>
  </div>
  <nav class="tabs" role="tablist" aria-label="Secciones del libro">
    <div class="wrap tabs-row">
      <button type="button" class="tab" role="tab" id="tab-revision" data-panel="revision"
        aria-controls="panel-revision" aria-selected="false" tabindex="-1">Revisar {badge}</button>
      <button type="button" class="tab" role="tab" id="tab-libro" data-panel="libro"
        aria-controls="panel-libro" aria-selected="false" tabindex="-1">Libro</button>
      <button type="button" class="tab" role="tab" id="tab-duplicados" data-panel="duplicados"
        aria-controls="panel-duplicados" aria-selected="false" tabindex="-1">Duplicados {dup_badge}</button>
      <button type="button" class="tab" role="tab" id="tab-insights" data-panel="insights"
        aria-controls="panel-insights" aria-selected="false" tabindex="-1">Insights</button>
    </div>
  </nav>
</header>
"""


def _kpis(data: dict) -> str:
    mejora_note = ""
    if data["regimen"] == REGIMEN_CI:
        mejora_note = (
            '<p class="hint wrap">En capital inmobiliario las <strong>mejoras no restan</strong> '
            "del rendimiento del año: se capitalizan y se amortizan.</p>"
        )
    return f"""
<section class="kpis" aria-label="Resumen del ejercicio">
  <div class="wrap kpi-grid">
    {_kpi_btn("Gastos del ejercicio", data["gastos"], "gasto")}
    {_kpi_btn("Ingresos", data["ingresos"], "ingreso")}
    {_kpi_btn("Mejoras (inversión)", data["mejoras"], "mejora")}
    {_kpi_btn("Rendimiento neto", data["resultado"], "neto")}
    {_kpi_btn_count("Por revisar", data["n_pendientes"], data["n_asientos"], kpi_id="insight-kpi-revisar")}
  </div>
  {mejora_note}
</section>
"""


def _kpi_btn(label: str, value: Decimal, kind: str, *, kpi_id: str = "") -> str:
    id_attr = f' id="{kpi_id}"' if kpi_id else ""
    return (
        f'<div class="kpi kpi-{kind}">'
        f"<span>{escape(label)}</span>"
        f"<strong{id_attr}>{escape(format_euro(value))}</strong></div>"
    )


def _kpi_btn_count(label: str, pendientes: int, total: int, *, kpi_id: str = "") -> str:
    id_attr = f' id="{kpi_id}"' if kpi_id else ""
    return (
        f'<div class="kpi kpi-count"{id_attr} role="button" tabindex="0">'
        f"<span>{escape(label)}</span>"
        f"<strong>{pendientes}</strong>"
        f"<em>de {total} asientos</em></div>"
    )


def _quality_pct_label(pct: int | None) -> str:
    return "—" if pct is None else f"{pct} %"


def _quality_cell(item: dict, *, prefix: str) -> str:
    faltas = item.get("calidad_faltas") or []
    if item["validado"]:
        tone = "ok"
        label = "Validado"
        hint = "Bloqueado: reparse y OCR no pisan fecha, emisor, importes ni rubro."
    elif faltas:
        tone = "warn"
        label = "Revisar"
        hint = "En la ficha: " + " ".join(faltas[:4])
    elif item["baja"]:
        tone = "warn"
        label = "Revisar"
        hint = (
            "El modelo no está seguro. Abre el documento, corrige NIF o importes "
            "si hace falta y pulsa Por validar."
        )
    else:
        tone = "ok"
        label = "Aceptable"
        hint = "Número, fecha, emisor, NIF, importes, ids y suma están rellenos."
    ocr = _quality_pct_label(item["conf_ocr_pct"])
    clasificacion = _quality_pct_label(item["conf_class_pct"])
    rubro = item["cuenta_nombre"]
    casilla = item["casilla_etiqueta"]
    pop_id = f"q-pop-{prefix}-{item['id']}"
    return (
        f'<div class="q-chip-wrap">'
        f'<button type="button" class="q-chip q-{tone}" popovertarget="{pop_id}" '
        f'aria-expanded="false">'
        f'<i class="q-dot" aria-hidden="true"></i>'
        f"<span>{escape(label)}</span>"
        f'<span class="q-i" aria-hidden="true">i</span>'
        f"</button>"
        f'<div id="{pop_id}" popover="auto" class="q-pop" role="tooltip">'
        f"<strong>{escape(label)}</strong>"
        f'<dl><div><dt>OCR</dt><dd>{escape(ocr)}</dd></div>'
        f"<div><dt>Clasificación</dt><dd>{escape(clasificacion)}</dd></div>"
        f"<div><dt>Rubro</dt><dd>{escape(rubro)}</dd></div>"
        f"<div><dt>Casilla</dt><dd>{escape(casilla)}</dd></div></dl>"
        f"<p>{escape(hint)}</p>"
        f"</div></div>"
    )


def _amount_attr(value: Decimal | None) -> str:
    quantized = q2(value)
    return "" if quantized is None else f"{quantized:.2f}"


def _kan_card(item: dict) -> str:
    """Tarjeta de factura para el tablero Kanban."""
    estado = item["estado"]
    total = item.get("total")
    total_label = escape(format_euro(total)) if total is not None else "—"
    if estado == "duplicado":
        chip = f'<span class="pill duplicado">de #{item.get("duplicado_de_id") or "—"}</span>'
    elif estado == "rechazado":
        motivo = (item.get("motivo_rechazo") or "").strip()
        chip = (
            '<span class="pill rechazado">'
            f"{escape(motivo[:40] or 'Rechazada')}</span>"
        )
    elif item["baja"]:
        chip = '<span class="pill pendiente">Confianza baja</span>'
    else:
        pct = item.get("conf_min_pct")
        chip = f'<span class="pill confirmado">{pct if pct is not None else "—"} %</span>'
    acciones = []
    if estado == "pendiente":
        acciones.append(f'<button type="button" class="kan-act" data-kan="validar" data-id="{item["id"]}" title="Consolidar: revisada y buena">✓</button>')
    if estado == "confirmado":
        acciones.append(f'<button type="button" class="kan-act" data-kan="reabrir" data-id="{item["id"]}" title="Devolver a revisión">↩</button>')
    if estado == "duplicado":
        acciones.append(f'<button type="button" class="kan-act" data-kan="quitar-dup" data-id="{item["id"]}" title="Quitar duplicado">↩</button>')
    if estado == "rechazado":
        acciones.append(f'<button type="button" class="kan-act" data-kan="recuperar" data-id="{item["id"]}" title="Recuperar a revisión">↩</button>')
    if estado in ("pendiente", "rechazado"):
        acciones.append(f'<button type="button" class="kan-act" data-kan="rechazar" data-id="{item["id"]}" title="Rechazar: no es una factura">✕</button>')
    return (
        f'<article class="kan-card" draggable="true" data-id="{item["id"]}" '
        f'data-estado="{estado}" data-total="{total_label}" '
        f'data-emisor="{escape(item["emisor"])}" data-numero="{escape(item["numero"])}" '
        f'data-fecha="{escape(item["fecha_label"])}">'
        f'<a class="kan-ref" href="/asiento/{item["id"]}" title="Abrir la ficha">{escape(item["emisor"])}</a>'
        f'<p class="muted kan-datos">{escape(item["numero"])} · {escape(item["fecha_label"])}</p>'
        f"<strong>{total_label}</strong> {chip}"
        f'<div class="kan-acciones">{" ".join(acciones)}</div>'
        "</article>"
    )


def _panel_revision(data: dict) -> str:
    """Tablero Kanban del flujo de revisión manual."""
    pendientes = [item for item in data["asientos"] if item["estado"] == "pendiente"]
    consolidadas = [item for item in data["asientos"] if item["estado"] == "confirmado"]
    duplicadas = [item for item in data["asientos"] if item["estado"] == "duplicado"]
    rechazadas = [item for item in data["asientos"] if item["estado"] == "rechazado"]
    cola = {item["id"]: item for item in data["cola_revision"]}
    pendientes_ordenadas = [cola.get(item["id"], item) for item in pendientes]
    vivas = len(pendientes) + len(consolidadas) + len(duplicadas)
    hechas = vivas - len(pendientes)
    progreso = int(round(100 * hechas / vivas)) if vivas else 100

    TOPE = 12

    def _columna(clave: str, titulo: str, filas: list[dict], vacio: str, soltar: str) -> str:
        visibles = filas[:TOPE]
        cards = "".join(_kan_card(item) for item in visibles)
        resto = len(filas) - len(visibles)
        if resto > 0:
            destino = "tabla" if clave == "pendiente" else clave
            cards += (
                f'<button type="button" class="kan-mas" data-kan-mas="{destino}">'
                f"+{resto} más…</button>"
            )
        cuerpo = cards or f'<p class="kan-vacio">{vacio}</p>'
        return (
            f'<section class="kan-col" data-col="{clave}" data-soltar="{soltar}">'
            f'<header class="kan-col-cab"><span>{titulo}</span><span class="kan-num">{len(filas)}</span></header>'
            f'<div class="kan-cuerpo">{cuerpo}</div></section>'
        )

    def _fila_tabla(item: dict) -> str:
        total = item.get("total")
        total_label = escape(format_euro(total)) if total is not None else "—"
        faltas = " · ".join(item.get("calidad_faltas") or [])[:90] or "—"
        return (
            "<tr>"
            f'<td><a href="/asiento/{item["id"]}">#{item["id"]}</a></td>'
            f"<td>{escape(item['emisor'])}</td>"
            f"<td>{escape(item['numero'])}</td>"
            f"<td>{escape(item['fecha_label'])}</td>"
            f'<td class="num">{total_label}</td>'
            f"<td>{escape(faltas)}</td>"
            f'<td class="kan-celda-act">'
            f'<button type="button" class="kan-act" data-kan="validar" data-id="{item["id"]}" title="Consolidar">✓</button>'
            f'<button type="button" class="kan-act" data-kan="rechazar" data-id="{item["id"]}" title="Rechazar">✕</button>'
            "</td></tr>"
        )

    tabla_rows = "".join(_fila_tabla(item) for item in pendientes_ordenadas) or (
        '<tr><td colspan="7" class="muted">Nada pendiente.</td></tr>'
    )

    return f"""
<div class="panel" role="tabpanel" id="panel-revision" data-panel="revision"
  aria-labelledby="tab-revision">
  <p class="panel-lead">El flujo manual: cada factura pasa por tus manos. Arrastra las tarjetas
  (o usa sus botones) para darles seguimiento; el detalle se trabaja en la ficha.</p>
  <div class="kan-embudo" aria-label="Embudo de revisión">
    <div><span>Por revisar</span><strong>{len(pendientes)}</strong></div>
    <div><span>Consolidadas</span><strong>{len(consolidadas)}</strong></div>
    <div><span>Duplicadas</span><strong>{len(duplicadas)}</strong></div>
    <div><span>Rechazadas</span><strong>{len(rechazadas)}</strong></div>
    <div class="kan-progreso"><span>Seguimiento</span>
      <div class="kan-barra"><i style="width: {progreso}%"></i></div>
      <strong>{progreso} %</strong></div>
  </div>
  <div class="rev-vistas" role="group" aria-label="Vista de revisión">
    <button type="button" class="ghost" id="rev-vista-tablero" aria-pressed="true">Tablero</button>
    <button type="button" class="ghost" id="rev-vista-tabla" aria-pressed="false">Tabla</button>
  </div>
  <div class="kan-board" id="kan-board">
    {_columna("pendiente", "Por revisar", pendientes_ordenadas, "Nada pendiente. Ingresa facturas y vuelve.", "validar|rechazar")}
    {_columna("confirmado", "Consolidadas", consolidadas, "Aquí caen las revisadas y buenas.", "reabrir")}
    {_columna("duplicado", "Duplicadas", duplicadas, "Sin duplicados marcados.", "quitar-dup")}
    {_columna("rechazado", "Rechazadas", rechazadas, "Sin documentos rechazados.", "recuperar")}
  </div>
  <div class="rev-tabla" id="revision-tabla" hidden>
    <div class="table-wrap"><table class="dup-tabla">
      <thead><tr><th>Id</th><th>Emisor</th><th>Nº</th><th>Fecha</th>
      <th class="num">Total</th><th>Por qué revisar</th><th></th></tr></thead>
      <tbody id="rev-tabla-body">{tabla_rows}</tbody></table></div>
    <nav class="pager" aria-label="Páginas de pendientes">
      <button type="button" class="ghost" id="rev-prev">Anterior</button>
      <span class="pager-label" id="rev-paginas"></span>
      <button type="button" class="ghost" id="rev-next">Siguiente</button>
    </nav>
  </div>
  <dialog class="edit-dialog" id="rechazo-dialog" aria-labelledby="rechazo-title">
    <div class="dup-gestor-cuerpo">
      <p class="dup-gestor-eyebrow">Rechazar factura</p>
      <h2 id="rechazo-title">¿Por qué se rechaza?</h2>
      <p class="hint">Queda fuera del libro y del Excel. El motivo alimenta las estadísticas
      de aprendizaje del pipeline.</p>
      <div class="rechazo-opciones">
        <label class="filter-opt"><input type="radio" name="rechazo-motivo" value="No es una factura" checked><span>No es una factura (confirmación, publicidad…)</span></label>
        <label class="filter-opt"><input type="radio" name="rechazo-motivo" value="Calidad de datos (OCR ilegible)"><span>Calidad de datos (OCR ilegible)</span></label>
        <label class="filter-opt"><input type="radio" name="rechazo-motivo" value="Falta información (sin número/fecha/importes)"><span>Falta información (sin número/fecha/importes)</span></label>
        <label class="filter-opt"><input type="radio" name="rechazo-motivo" value="Mal procesamiento del pipeline"><span>Mal procesamiento del pipeline</span></label>
        <label class="filter-opt"><input type="radio" name="rechazo-motivo" value="Otro"><span>Otro</span></label>
      </div>
      <label class="dup-campo">Detalle (opcional)
        <input id="rechazo-detalle" type="text" maxlength="140" placeholder="p. ej. escaneo torcido, página en inglés…"></label>
      <div class="edit-actions" style="border:0; margin:12px 0 0; padding:0;">
        <button type="button" class="ghost" id="rechazo-cancel">Cancelar</button>
        <button type="button" class="export-btn" id="rechazo-ok">Rechazar</button>
      </div>
    </div>
  </dialog>
  {_footer(data)}
</div>
"""


def _panel_libro(data: dict) -> str:
    body = _ledger(data)
    return (
        '<div class="panel" role="tabpanel" id="panel-libro" data-panel="libro" '
        f'aria-labelledby="tab-libro">{body}{_footer(data)}</div>'
    )


def _dup_lado(item: dict | None, rol: str, asiento_id: int | None) -> str:
    """Una de las dos caras de un caso de duplicado (duplicado o gemelo)."""
    if item is None:
        if asiento_id is None:
            return '<div class="dup-lado"><p class="muted">Gemelo no encontrado.</p></div>'
        return (
            '<div class="dup-lado">'
            f'<p class="dup-rol">{escape(rol)}</p>'
            f'<a href="/asiento/{asiento_id}">Asiento #{asiento_id}</a>'
            "<p class=\"muted\">Fuera del ejercicio actual.</p>"
            "</div>"
        )
    total = item.get("total")
    total_label = escape(format_euro(total)) if total is not None else "—"
    return (
        '<div class="dup-lado">'
        f'<p class="dup-rol">{escape(rol)}</p>'
        f'<a href="/asiento/{item["id"]}">Asiento #{item["id"]}</a>'
        f"<p class=\"dup-emisor\">{escape(item['emisor'])}</p>"
        f"<p class=\"muted\">{escape(item['numero'])} · {escape(item['fecha_label'])}</p>"
        f"<strong>{total_label}</strong>"
        "</div>"
    )


MOTIVO_NIVEL = {
    2: "fusión por número o decisión humana",
    3: "mismo NIF o emisor + importe ±3 días, o imagen casi idéntica",
}


def _dup_attrs(item: dict, gemelo_view: dict | None, gemelo_id: int | None) -> str:
    """Data-atributos de la fila para el gestor en pop-up."""
    gemelo = gemelo_view or {}

    def _v(clave):
        valor = gemelo.get(clave)
        if valor is None:
            return ""
        if clave == "total":
            return format_euro(valor)
        return str(valor)

    motivo = MOTIVO_NIVEL.get(item.get("duplicado_nivel"), "sospecha del modelo")
    return " ".join(
        [
            f'data-dup-id="{item["id"]}"',
            f'data-estado="{"duplicado" if item["estado"] == "duplicado" else "sospechoso"}"',
            f'data-emisor="{escape(item["emisor"])}"',
            f'data-nif="{escape(item.get("nif") or "")}"',
            f'data-numero="{escape(item["numero"])}"',
            f'data-fecha="{escape(item["fecha_label"])}"',
            f'data-total="{escape(format_euro(item["total"]) if item["total"] is not None else "—")}"',
            f'data-motivo="{escape(motivo)}"',
            f'data-gemelo="{gemelo_id or ""}"',
            f'data-gemelo-emisor="{escape(_v("emisor"))}"',
            f'data-gemelo-nif="{escape(_v("nif"))}"',
            f'data-gemelo-numero="{escape(_v("numero"))}"',
            f'data-gemelo-fecha="{escape(_v("fecha_label"))}"',
            f'data-gemelo-total="{escape(_v("total"))}"',
        ]
    )


def _dup_card(item: dict, gemelo_view: dict | None, gemelo_id: int | None) -> str:
    gemelo_celda = (
        f'<a href="/asiento/{gemelo_id}">#{gemelo_id}</a>' if gemelo_id else "—"
    )
    total = item.get("total")
    total_label = escape(format_euro(total)) if total is not None else "—"
    return (
        f'<tr tabindex="0" role="button" {_dup_attrs(item, gemelo_view, gemelo_id)}>'
        f'<td><a href="/asiento/{item["id"]}">#{item["id"]}</a></td>'
        f"<td>{escape(item['emisor'])}</td>"
        f"<td>{escape(item['numero'])}</td>"
        f"<td>{escape(item['fecha_label'])}</td>"
        f'<td class="num">{total_label}</td>'
        f"<td>{gemelo_celda}</td>"
        '<td class="dup-abrir" aria-hidden="true">›</td>'
        "</tr>"
    )


def _panel_duplicados(data: dict) -> str:
    por_id = {item["id"]: item for item in data["asientos"]}
    fusionados = [item for item in data["asientos"] if item["estado"] == "duplicado"]
    sospechosos = data.get("sospechosos") or []

    def _tabla(rows: list[dict], aria: str) -> str:
        if not rows:
            return (
                '<p class="dup-vacio">Nada por aquí. Cuando el modelo detecte '
                "la misma compra dos veces, aparecerá aquí para que decidas.</p>"
            )
        filas = []
        for item in rows:
            gemelo_id = item.get("duplicado_de_id") or _gemelo_que_apunta(item["id"], data)
            filas.append(_dup_card(item, por_id.get(gemelo_id) if gemelo_id else None, gemelo_id))
        return (
            f'<div class="table-wrap" aria-label="{escape(aria)}"><table class="dup-tabla">'
            "<thead><tr><th>Id</th><th>Emisor</th><th>Nº</th><th>Fecha</th>"
            '<th class="num">Total</th><th>Gemelo</th><th></th></tr></thead>'
            f'<tbody>{"".join(filas)}</tbody></table></div>'
        )

    resumen = (
        f'{len(fusionados)} fusionado{"s" if len(fusionados) != 1 else ""} · '
        f'{len(sospechosos)} sospechoso{"s" if len(sospechosos) != 1 else ""}'
    )
    return f"""
<div class="panel" role="tabpanel" id="panel-duplicados" data-panel="duplicados"
  aria-labelledby="tab-duplicados">
  <p class="panel-lead">La misma compra más de una vez. {escape(resumen)}.</p>
  <section class="insight-block" aria-labelledby="dup-fusionados">
    <div class="review-head">
      <h2 id="dup-fusionados">Duplicados fusionados</h2>
      <p>Marcados (por el modelo o por ti) y fuera de los totales. Se deshacen desde «Gestionar».</p>
    </div>
    {_tabla(fusionados, "Duplicados fusionados")}
  </section>
  <section class="insight-block" aria-labelledby="dup-sospechosos">
    <div class="review-head">
      <h2 id="dup-sospechosos">Sospechosos pendientes</h2>
      <p>Compara con su gemelo y decide: fusionar o abrir la ficha.</p>
    </div>
    {_tabla(sospechosos, "Sospechosos pendientes")}
  </section>
  <dialog class="edit-dialog" id="dup-gestor" aria-labelledby="dup-gestor-title">
    <div class="dup-gestor-cuerpo">
      <p class="dup-gestor-eyebrow" id="dup-gestor-eyebrow">Duplicado</p>
      <h2 id="dup-gestor-title">Gestionar duplicado</h2>
      <p class="dup-motivo-caja" id="dup-gestor-motivo"></p>
      <div class="dup-par" id="dup-gestor-par"></div>
    </div>
    <footer class="dup-gestor-pie">
      <a class="dup-ficha-link" id="dup-gestor-ficha" target="_blank" rel="noopener">Abrir ficha ↗</a>
      <div class="dup-gestor-acciones">
        <button type="button" class="ghost" id="dup-gestor-cerrar">Cerrar</button>
        <button type="button" class="export-btn" id="dup-gestor-fusionar" hidden>Fusionar</button>
        <button type="button" class="ghost" id="dup-gestor-quitar" hidden>Quitar duplicado</button>
      </div>
    </footer>
  </dialog>
  {_footer(data)}
</div>
"""


def _gemelo_que_apunta(asiento_id: int, data: dict) -> int | None:
    for item in data["asientos"]:
        if item["estado"] != "duplicado" and item.get("duplicado_de_id") == asiento_id:
            return item["id"]
    return None


def _panel_insights(data: dict) -> str:
    mejora_note = ""
    if data["regimen"] == REGIMEN_CI:
        mejora_note = (
            '<p class="hint">En capital inmobiliario las <strong>mejoras no restan</strong> '
            "del rendimiento del año: se capitalizan y se amortizan.</p>"
        )
    return f"""
<section class="panel" role="tabpanel" id="panel-insights" data-panel="insights"
  aria-labelledby="tab-insights">
  <p class="panel-lead">Arriba, cómo va el ejercicio. Abajo, el borrador de la Renta.</p>
  <div class="kpi-grid">
    {_kpi_btn("Gastos", data["gastos"], "gasto", kpi_id="insight-kpi-gastos")}
    {_kpi_btn("Ingresos", data["ingresos"], "ingreso", kpi_id="insight-kpi-ingresos")}
    {_kpi_btn("Mejoras", data["mejoras"], "mejora", kpi_id="insight-kpi-mejoras")}
    {_kpi_btn("Neto", data["resultado"], "neto", kpi_id="insight-kpi-neto")}
    {_kpi_btn_count("Por revisar", data["n_pendientes"], data["n_asientos"], kpi_id="insight-kpi-revisar")}
  </div>
  <p class="hint" id="insight-kpi-hint" hidden>KPIs y tablas siguen el rango de fechas de abajo; la Renta usa el ejercicio completo.</p>
  {mejora_note}
  {_aviso_linea(data)}
  {_insights_html(data)}
  {_irpf_html(data)}
</section>
"""


def _insight_rows_json(asientos: list[dict]) -> str:
    rows = []
    for item in asientos:
        if item.get("estado") in ("duplicado", "rechazado"):
            continue
        if item.get("tipo") not in {TIPO_GASTO, TIPO_INGRESO, TIPO_MEJORA}:
            continue
        emisor = item.get("emisor") or ""
        if emisor == "—":
            emisor = ""
        tipo_iva = item.get("iva_tipo")
        rows.append(
            {
                "fecha": item.get("fecha") or "",
                "emisor": emisor,
                "total": float(q2(item.get("total")) or 0),
                "tipo": item.get("tipo") or "",
                "base": float(q2(item.get("base")) or 0),
                "iva_cuota": float(q2(item.get("iva")) or 0),
                "iva_tipo": float(tipo_iva) if tipo_iva is not None else None,
            }
        )
    return json.dumps(rows, ensure_ascii=True).replace("<", "\\u003c")


def _insights_html(data: dict) -> str:
    frase = _frase_anio(data["asientos"], data["por_mes"])
    frase_html = (
        f'<p class="insight-frase" id="insight-frase">{escape(frase)}</p>' if frase else
        '<p class="insight-frase" id="insight-frase" hidden></p>'
    )
    return f"""
<section class="insights insight-block" id="insights" aria-labelledby="insight-operativo">
  <div class="review-head">
    <h2 id="insight-operativo">Operativo</h2>
    <p>Evolución de gastos e ingresos del ejercicio.</p>
  </div>
  <div class="insight-range" id="insight-range">
    <span class="insight-range-year">Ejercicio {data["year"]}</span>
    <button type="button" class="ghost" id="insight-range-all">Año completo</button>
    <label>Desde <input id="insight-desde" type="date"></label>
    <label>Hasta <input id="insight-hasta" type="date"></label>
    <label>Nombre <input id="insight-range-name" type="text" maxlength="40" placeholder="Agosto" autocomplete="off"></label>
    <button type="button" class="ghost" id="insight-range-save">Guardar rango</button>
    <div class="insight-presets insight-trims" id="insight-trims"></div>
  <div class="insight-presets" id="insight-presets"></div>
  </div>
  {frase_html}
  {_charts(data)}
  {_iva_html(data)}
  <template id="insight-rows">{_insight_rows_json(data["asientos"])}</template>
</section>
"""


def _charts(data: dict) -> str:
    return f"""
<section class="charts" id="charts" aria-label="Gráficos">
  <figure>
    <figcaption>Gasto por mes</figcaption>
    <div class="chart-scroll" id="insight-month">{_svg_months(data["por_mes"])}</div>
  </figure>
  <figure>
    <figcaption>Por emisor</figcaption>
    <div id="insight-emisor">{_svg_emisores(_emisores_para_grafico(data["asientos"]))}</div>
  </figure>
</section>
"""


def _iva_html(data: dict) -> str:
    filas = data.get("iva_tipos") or []
    if filas:
        body = "".join(
            f'<tr><td>{escape(item["label"])}</td>'
            f'<td class="num">{escape(format_euro(item["base"]))}</td>'
            f'<td class="num">{escape(format_euro(item["cuota"]))}</td>'
            f'<td class="num">{escape(format_euro(item["total"]))}</td></tr>'
            for item in filas
        )
    else:
        body = '<tr class="iva-vacia"><td colspan="4">Sin IVA registrado.</td></tr>'
    return f"""
<section class="iva-block insight-block" id="iva-soportado" aria-labelledby="iva-titulo">
  <div class="review-head">
    <h2 id="iva-titulo">IVA soportado</h2>
    <p>Base, cuota y total de gastos y mejoras por tipo de IVA. Apunta al borrador 303.</p>
  </div>
  <div class="table-wrap">
    <table class="iva-tabla" id="iva-tabla">
      <thead>
        <tr>
          <th scope="col"><span class="th-label">Tipo</span></th>
          <th scope="col" class="num"><span class="th-label">Base</span></th>
          <th scope="col" class="num"><span class="th-label">Cuota</span></th>
          <th scope="col" class="num"><span class="th-label">Total</span></th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</section>
"""


def _svg_months(series: list[dict]) -> str:
    width, height = 640, 280
    pad_l, pad_r, pad_t, pad_b = 56, 16, 36, 40
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    show_income = any(item["ingresos"] > ZERO for item in series)
    peak = max(
        (max(item["gastos"], item["ingresos"] if show_income else ZERO) for item in series),
        default=ZERO,
    )
    peak = peak if peak > 0 else Decimal("1")
    slot = inner_w / 12
    bar_w = min(slot * (0.34 if show_income else 0.55), 28)
    ticks = [
        (ZERO, pad_t + inner_h),
        (peak / 2, pad_t + inner_h / 2),
        (peak, pad_t),
    ]
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Gasto de cada mes del año">'
    ]
    for value, y in ticks:
        parts.append(
            f'<line class="grid" x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}"/>'
            f'<text class="tick" x="{pad_l - 8}" y="{y + 4:.1f}">{escape(_compact(value))}</text>'
        )
    for idx, item in enumerate(series):
        pair = bar_w * (2 if show_income else 1) + (4 if show_income else 0)
        x0 = pad_l + slot * idx + (slot - pair) / 2
        h_g = float(item["gastos"] / peak) * inner_h
        y_g = pad_t + inner_h - h_g
        if h_g >= 0.5:
            parts.append(
                f'<rect class="bar-g" x="{x0:.1f}" y="{y_g:.1f}" width="{bar_w:.1f}" height="{h_g:.1f}" rx="3">'
                f"<title>{escape(item['mes_largo'])} gastos {escape(format_euro(item['gastos']))}</title></rect>"
            )
            parts.append(
                f'<text class="bar-label" x="{x0 + bar_w / 2:.1f}" y="{max(y_g - 6, 12):.1f}">'
                f"{escape(_compact(item['gastos']))}</text>"
            )
        if show_income and item["ingresos"] > ZERO:
            h_i = float(item["ingresos"] / peak) * inner_h
            x_i = x0 + bar_w + 4
            y_i = pad_t + inner_h - h_i
            parts.append(
                f'<rect class="bar-i" x="{x_i:.1f}" y="{y_i:.1f}" width="{bar_w:.1f}" height="{h_i:.1f}" rx="3">'
                f"<title>{escape(item['mes_largo'])} ingresos {escape(format_euro(item['ingresos']))}</title></rect>"
            )
            parts.append(
                f'<text class="bar-label" x="{x_i + bar_w / 2:.1f}" y="{max(y_i - 6, 12):.1f}">'
                f"{escape(_compact(item['ingresos']))}</text>"
            )
        label_x = pad_l + slot * idx + slot / 2
        parts.append(
            f'<text class="axis" x="{label_x:.1f}" y="{height - 14}">{item["mes"]}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _svg_emisores(series: list[dict]) -> str:
    if not series:
        return '<p class="empty">Aún no hay gasto que repartir por emisor.</p>'
    width = 640
    row_h = 58
    pad_l, pad_r = 18, 16
    height = 16 + row_h * len(series)
    peak = max((item["total"] for item in series), default=Decimal("1"))
    grand = sum((item["total"] for item in series), ZERO) or Decimal("1")
    inner_w = width - pad_l - pad_r
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Gasto por emisor">'
    ]
    for idx, item in enumerate(series):
        y = 8 + idx * row_h
        bar = float(item["total"] / peak) * inner_w if peak else 0
        pct = int(round(float(item["total"] / grand * 100)))
        shown, full = _etiqueta_emisor(item["label"])
        parts.append(
            f'<text class="axis left" x="{pad_l}" y="{y + 14}">'
            f"<title>{escape(full)}</title>{escape(shown)}</text>"
            f'<rect class="bar-g" x="{pad_l}" y="{y + 22}" width="{max(bar, 8):.1f}" height="16" rx="4">'
            f"<title>{escape(full)} {escape(format_euro(item['total']))} ({pct} %)</title></rect>"
            f'<text class="tick right" x="{pad_l}" y="{y + 52}">'
            f"{escape(format_euro(item['total']))} · {pct} %</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _irpf_html(data: dict) -> str:
    irpf = data.get("irpf")
    if not irpf:
        return ""
    rows = []
    for item in irpf["filas"]:
        if item["n"] == 0 and item["clave"] not in {"ingresos", "mejoras"}:
            continue
        mark = "Sí" if item["resta_del_ano"] else "No"
        rows.append(
            "<tr "
            f'data-irpf-concepto="{escape(item["etiqueta"])}" '
            f'data-irpf-resta="{"si" if item["resta_del_ano"] else "no"}" '
            f'data-irpf-importe="{escape(str(item["total"] or ""))}">'
            f"<td>{escape(item['etiqueta'])}</td>"
            f'<td class="num">{item["n"]}</td>'
            f'<td class="num">{escape(format_euro(item["total"]))}</td>'
            f"<td>{mark}</td>"
            f'<td class="muted">{escape(item["notas"])}</td>'
            "</tr>"
        )
    conceptos = _unique_labels([item["etiqueta"] for item in irpf["filas"] if not (item["n"] == 0 and item["clave"] not in {"ingresos", "mejoras"})])
    resta = [("si", "Sí"), ("no", "No")]
    return f"""
<section class="irpf insight-block" id="irpf" aria-labelledby="insight-renta">
  <div class="review-head">
    <h2 id="insight-renta">Renta</h2>
    <p>Como iría en la Renta con el <strong>ejercicio completo</strong>. Borrador para copiar a la declaración. Hacienda no recibe este HTML.</p>
  </div>
  <div class="irpf-kpis">
    <article><span>Ingresos íntegros</span><strong>{escape(format_euro(irpf["ingresos"]))}</strong></article>
    <article><span>Gastos deducibles</span><strong>{escape(format_euro(irpf["gastos_deducibles"]))}</strong></article>
    <article><span>Rendimiento neto</span><strong>{escape(format_euro(irpf["rendimiento"]))}</strong></article>
    <article><span>Mejoras (fuera del año)</span><strong>{escape(format_euro(irpf["mejoras"]))}</strong></article>
  </div>
  <div class="table-wrap">
    <table class="irpf-table">
      <thead>
        <tr>
          {_filter_th("Concepto", "pop-irpf-concepto", _filter_checks("irpf-concepto", conceptos))}
          <th class="num"><span class="th-label">Asientos</span></th>
          {_filter_th("Importe", "pop-irpf-importe", _filter_amount("f-irpf-min", "f-irpf-max"), "num")}
          {_filter_th("Resta del año", "pop-irpf-resta", _filter_checks("irpf-resta", resta))}
          <th><span class="th-label">Nota</span></th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</section>
"""


def _site_footer() -> str:
    repo_label = REPO_URL.removeprefix("https://")
    return f"""
<footer class="site-foot">
  <div class="wrap">
    <p>{escape(CONTACT_NAME)} ·
      <a href="mailto:{escape(CONTACT_MAIL)}">{escape(CONTACT_MAIL)}</a>
      · <a href="{escape(REPO_URL)}" target="_blank" rel="noopener">{escape(repo_label)}</a></p>
    <p>Código abierto. Issues y pull requests para mejorar el modelo de extracción.</p>
  </div>
</footer>
"""


def _footer(data: dict) -> str:
    xlsx = data.get("xlsx_name") or f"libro_{data['codigo']}_{data['year']}.xlsx"
    return f"""
<footer class="foot">
  <p>Para el gestor o para copiar importes a Hacienda. No es presentación telemática.
     <strong>Exportar visible</strong> respeta los filtros del libro (fecha, rubro, importes).</p>
  <div class="foot-actions">
    <button type="button" class="export-btn" id="export-visible">Exportar visible</button>
    <a class="ghost export-full" href="{escape(xlsx)}" download="{escape(xlsx)}">Libro completo (xlsx)</a>
  </div>
</footer>
"""



def _compact(value: Decimal) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k".replace(".", ",")
    return format_euro(value).replace(" €", "")


_FUNNEL_SVG = (
    '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">'
    '<path fill="currentColor" d="M2 2.5h12l-4.4 5.4V13l-3.2-1.6V7.9z"/>'
    "</svg>"
)
_SEARCH_SVG = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<circle cx="7" cy="7" r="4.2" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" d="M10.2 10.2 13.5 13.5"/>'
    "</svg>"
)
_PENCIL_SVG = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<path fill="currentColor" d="M11.7 1.6c.4-.4 1.1-.4 1.5 0l1.2 1.2c.4.4.4 1.1 0 1.5L6.2 12.5 2 14l1.5-4.2z"/>'
    "</svg>"
)
_DISK_SVG = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" d="M3 2.5h7.2L13 5.2V13.5H3z"/>'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" d="M5 2.8V6h5.2M5 13.2v-3.4h6V13"/>'
    "</svg>"
)
_TRASH_SVG = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" '
    'd="M3.5 4.5h9M6.2 4.5V3.2h3.6v1.3M5 4.5l.5 8h5l.5-8"/>'
    "</svg>"
)
_EYE_SVG = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" d="M1.6 8s2.2-3.6 6.4-3.6S14.4 8 14.4 8s-2.2 3.6-6.4 3.6S1.6 8 1.6 8z"/>'
    '<circle cx="8" cy="8" r="1.6" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    "</svg>"
)
_RESTORE_SVG = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" '
    'stroke-linejoin="round" d="M3.2 8a4.8 4.8 0 1 0 1.2-3.2M3 3.2V6.2h3"/>'
    "</svg>"
)
_BACK_SVG = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
    '<path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
    'stroke-linejoin="round" d="M10.2 3.2 5.5 8l4.7 4.8M5.5 8h5.8"/>'
    "</svg>"
)
_FILE_SVG = (
    '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" '
    'd="M4.2 2.5h5.1L12.3 5.5v8H4.2z"/>'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" d="M9.3 2.5v3h3"/>'
    "</svg>"
)
_LIST_SVG = (
    '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" '
    'd="M6.2 4.2h6.2M6.2 8h6.2M6.2 11.8h6.2"/>'
    '<circle cx="3.6" cy="4.2" r="0.9" fill="currentColor"/>'
    '<circle cx="3.6" cy="8" r="0.9" fill="currentColor"/>'
    '<circle cx="3.6" cy="11.8" r="0.9" fill="currentColor"/>'
    "</svg>"
)
_CLOCK_SVG = (
    '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">'
    '<circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" stroke-width="1.4"/>'
    '<path fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" d="M8 5.2V8l2 1.6"/>'
    "</svg>"
)


def _filter_date_range() -> str:
    return """
<label class="filter-field">Desde
  <input id="f-desde" type="date">
</label>
<label class="filter-field">Hasta
  <input id="f-hasta" type="date">
</label>
<div class="filter-trims" role="group" aria-label="Trimestres del ejercicio">
  <button type="button" class="filter-trim" data-trim="1">T1</button>
  <button type="button" class="filter-trim" data-trim="2">T2</button>
  <button type="button" class="filter-trim" data-trim="3">T3</button>
  <button type="button" class="filter-trim" data-trim="4">T4</button>
</div>
<p class="filter-hint">Un solo lado vale: desde esa fecha, o hasta esa fecha. Vacío = sin tope.
T1–T4 rellenan el trimestre del ejercicio (pulsa otra vez para quitarlo).</p>
"""


def _filter_checks(name: str, pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return '<p class="filter-empty">Sin valores en este ejercicio.</p>'
    items = "".join(
        f'<label class="filter-opt"><input type="checkbox" data-fg="{name}" value="{escape(value)}" checked>'
        f"<span>{escape(label)}</span></label>"
        for value, label in pairs
    )
    return (
        f'<label class="filter-search">{_SEARCH_SVG}'
        f'<input type="search" class="filter-search-input" placeholder="Buscar…" '
        f'data-filter-search="{name}" autocomplete="off"></label>'
        f'<button type="button" class="filter-all" data-filter-all="{name}">Seleccionar todo</button>'
        f'<div class="filter-opts">{items}</div>'
    )


def _edit_dialog(data: dict | None = None) -> str:
    nombres = (data or {}).get("rubros") or []
    opciones = '<option value="">Sin clasificar</option>' + "".join(
        f'<option value="{escape(nombre)}">{escape(nombre)}</option>' for nombre in nombres
    )
    return f"""
<dialog class="edit-dialog" id="edit-dialog" aria-labelledby="edit-title">
  <form method="dialog" id="edit-form">
    <div id="edit-form-pane">
      <h2 id="edit-title">Editar asiento</h2>
      <p class="edit-meta" id="edit-meta"></p>
      <label>Emisor
        <input id="edit-emisor" name="emisor" maxlength="200" autocomplete="organization">
      </label>
      <label>NIF emisor
        <input id="edit-nif" name="nif_emisor" maxlength="12" autocomplete="off">
      </label>
      <label>Fecha de compra
        <input id="edit-fecha" name="fecha" type="date">
      </label>
      <label>Rubro
        <select id="edit-rubro">{opciones}</select>
      </label>
      <p class="edit-hint" id="edit-articulos">Artículos: —</p>
      <p class="edit-hint">Base, IVA y total no se editan aquí. Salen de las líneas de la ficha, y el número de artículos es el de esas líneas.</p>
      <label class="edit-check">
        <input id="edit-validar" type="checkbox">
        Validado (OK). Desmárcalo para volver a revisión.
      </label>
      <p class="edit-log-title">Historial</p>
      <ol class="edit-log" id="edit-log"></ol>
      <div class="edit-actions">
        <button type="button" class="ghost" id="edit-cancel" value="cancel">Cancelar</button>
        <button type="button" class="export-btn" id="edit-review">Revisar cambio</button>
      </div>
    </div>
    <div id="edit-confirm" hidden>
      <h2>¿Seguro que quieres modificar este asiento?</h2>
      <p>Comprueba el antes y el después. Esta acción queda en el log del libro.</p>
      <table class="edit-diff">
        <thead><tr><th>Campo</th><th>Antes</th><th>Después</th></tr></thead>
        <tbody id="edit-diff-body"></tbody>
      </table>
      <label class="edit-check">
        <input id="edit-ack" type="checkbox">
        He revisado el documento y confirmo que los datos son correctos.
      </label>
      <div class="edit-actions">
        <button type="button" class="ghost" id="edit-back">Volver</button>
        <button type="button" class="export-btn" id="edit-commit" disabled>Sí, modificar</button>
      </div>
    </div>
  </form>
</dialog>
"""


def _mast_dialog() -> str:
    return """
<dialog class="edit-dialog" id="mast-dialog" aria-labelledby="mast-title">
  <form method="dialog" id="mast-form">
    <h2 id="mast-title">Títulos del libro</h2>
    <p class="edit-meta">Cabecera de este expediente. El código (CI-VA-001) y el régimen fiscal no se cambian aquí.</p>
    <label>Expediente
      <input id="mast-input-nombre" maxlength="200" autocomplete="off">
    </label>
    <label>Titular
      <input id="mast-input-titular" maxlength="200" autocomplete="off">
    </label>
    <label id="mast-inmueble-field">Inmueble
      <input id="mast-input-inmueble" maxlength="200" autocomplete="off">
    </label>
    <div class="edit-actions">
      <button type="button" class="ghost" id="mast-cancel">Cancelar</button>
      <button type="button" class="export-btn" id="mast-save">Guardar</button>
    </div>
  </form>
</dialog>
"""


def _filter_th(
    label: str,
    pop_id: str,
    inner: str,
    extra: str = "",
    *,
    col: str = "",
    sort: str = "",
    sort_type: str = "text",
    help: str = "",
) -> str:
    cls = f" {extra}" if extra else ""
    col_attr = f' data-col="{col}"' if col else ""
    sort_attr = f' data-sort="{sort}" data-sort-type="{sort_type}"' if sort else ""
    title_attr = f' title="{escape(help)}"' if help else ""
    return (
        f'<th class="th-filter{cls}"{col_attr}{sort_attr}{title_attr}>'
        f'<div class="th-head"><span class="th-label">{label}</span>'
        f'<button type="button" class="funnel" popovertarget="{pop_id}" '
        f'aria-label="Filtrar {label}" aria-expanded="false">{_FUNNEL_SVG}</button></div>'
        f'<div id="{pop_id}" popover="auto" class="filter-pop" role="dialog" '
        f'aria-label="Filtrar {label}">'
        f'<p class="filter-pop-title">Filtrar: {label}</p>{inner}'
        f'<div class="filter-pop-foot">'
        f'<button type="button" class="filter-done" popovertarget="{pop_id}" '
        f'popovertargetaction="hide">Listo</button></div></div></th>'
    )


_COL_TOGGLES: tuple[tuple[str, str], ...] = (
    ("factura", "Nº factura"),
    ("confianza", "Confianza"),
    ("nif", "NIF emisor"),
    ("base", "Base"),
    ("iva", "IVA"),
    ("doc", "Doc"),
)


def _cols_picker() -> str:
    opts = "".join(
        f'<label class="filter-opt"><input type="checkbox" data-col-toggle="{key}" checked>'
        f"<span>{escape(label)}</span></label>"
        for key, label in _COL_TOGGLES
    )
    return f"""
<div id="pop-cols" popover="auto" class="filter-pop cols-pop" role="dialog" aria-label="Columnas visibles">
  <p class="filter-pop-title">Columnas</p>
  <p class="filter-hint">Id, fecha, emisor, total y estado siempre se ven.</p>
  <div class="filter-opts">{opts}</div>
  <div class="filter-pop-foot">
    <button type="button" class="filter-all" id="cols-all">Mostrar todas</button>
    <button type="button" class="filter-done" popovertarget="pop-cols" popovertargetaction="hide">Listo</button>
  </div>
</div>
"""


def _ledger_filter_choices(data: dict) -> dict[str, list[tuple[str, str]]]:
    asientos = data["asientos"]
    emisores = sorted({item["emisor"] for item in asientos if item["emisor"] != "—"})
    nifs = sorted({item["nif"] for item in asientos if item["nif"] != "—"})
    numeros = sorted({item["numero"] for item in asientos if item["numero"] != "—"})
    rubros = sorted(
        {item["cuenta_nombre"] for item in asientos if item["cuenta"]},
    )
    return {
        "emisor": [(item, item) for item in emisores],
        "nif": [(item, item) for item in nifs],
        "factura": [(item, item) for item in numeros],
        "rubro": [(nombre, nombre) for nombre in rubros],
        "confianza": [
            ("baja", "Revisar"),
            ("ok", "Aceptable"),
            ("validado", "Validado"),
        ],
        "estado": [
            ("gasto", "Gastos"),
            ("ingreso", "Ingresos"),
            ("mejora", "Mejoras"),
            ("pendiente", "Por validar"),
            ("confirmado", "Validado"),
            ("duplicado", "Duplicados"),
        ],
    }


def _sum_money(items: list[dict], key: str) -> Decimal:
    total = ZERO
    for item in items:
        value = q2(item.get(key))
        if value is not None:
            total += value
    return total


def _ledger(data: dict) -> str:
    consolidadas = [
        item for item in data["asientos"] if item["estado"] not in ("pendiente", "rechazado")
    ]
    rows = "\n".join(_row_html(item) for item in consolidadas)
    empty = ""
    if not consolidadas:
        if data["n_pendientes"]:
            empty = (
                '<p class="empty">Aún no hay facturas consolidadas: las pendientes están '
                'en la pestaña <a href="#panel-revision" class="kan-ir-revisar">Revisar</a>.</p>'
            )
        else:
            empty = '<p class="empty">No hay asientos en este ejercicio.</p>'
    dup_note = ""
    if data["n_duplicados"]:
        dup_note = (
            f'<p class="hint">{data["n_duplicados"]} duplicado(s) visibles en la tabla; '
            "no entran en los totales.</p>"
        )
    choices = _ledger_filter_choices(data)
    id_inner = (
        f'<label class="filter-search">{_SEARCH_SVG}'
        '<input id="q" type="search" class="filter-search-input" placeholder="Buscar…" autocomplete="off">'
        "</label>"
        '<p class="filter-hint">Emisor, NIF, nº factura o id</p>'
    )
    total_inner = """
<label class="filter-field">Mínimo
  <input id="f-min" type="number" min="0" step="0.01" placeholder="0">
</label>
<label class="filter-field">Máximo
  <input id="f-max" type="number" min="0" step="0.01" placeholder="Sin tope">
</label>
"""
    vivos = [item for item in data["asientos"] if item["estado"] != "duplicado"]
    libro_total = _sum_money(vivos, "total")
    libro_base = _sum_money(vivos, "base")
    libro_iva = _sum_money(vivos, "iva")
    n_facturas = len(data["asientos"])
    return f"""
<section class="ledger" id="ledger">
  <div class="libro-kpis" id="libro-kpis" aria-label="Resumen del libro" aria-live="polite">
    <div><span>Facturas</span><strong id="libro-n">{n_facturas}</strong><em id="libro-n-note"></em></div>
    <div><span>Total</span><strong id="libro-total">{escape(format_euro(libro_total))}</strong></div>
    <div><span>Total visible</span><strong id="libro-visible">{escape(format_euro(libro_total))}</strong></div>
    <div><span>Base visible</span><strong id="libro-base">{escape(format_euro(libro_base))}</strong></div>
    <div><span>IVA visible</span><strong id="libro-iva">{escape(format_euro(libro_iva))}</strong></div>
  </div>
  <div class="ledger-status">
    <p class="status" id="status" hidden></p>
    <button type="button" class="ghost" id="f-clear" hidden>Limpiar filtros</button>
    <div class="ledger-actions">
      <button type="button" class="ghost" id="cols-toggle" popovertarget="pop-cols"
        aria-expanded="false" aria-haspopup="dialog">Columnas</button>
    </div>
  </div>
  {_cols_picker()}
  {dup_note}
  <div class="table-wrap" tabindex="0" aria-label="Tabla de asientos con desplazamiento horizontal">
    <table class="ledger-table">
      <colgroup>
        <col class="col-id">
        <col class="col-factura">
        <col class="col-fecha">
        <col class="col-emisor">
        <col class="col-calidad">
        <col class="col-total">
        <col class="col-articulos">
        <col class="col-nif">
        <col class="col-base">
        <col class="col-iva">
        <col class="col-doc">
        <col class="col-estado">
      </colgroup>
      <thead>
        <tr>
          {_filter_th("Id", "pop-q", id_inner, "col-sticky", col="id", sort="id", sort_type="num", help="Número de asiento en el libro")}
          {_filter_th("Nº factura", "pop-factura", _filter_checks("factura", choices["factura"]), col="factura", sort="factura", help="Número de factura tal como lo leyó el OCR")}
          {_filter_th("Fecha compra", "pop-fecha", _filter_date_range(), col="fecha", sort="fecha", help="Fecha de la compra")}
          {_filter_th("Emisor", "pop-emisor", _filter_checks("emisor", choices["emisor"]), col="emisor", sort="emisor", help="Tienda o empresa que emite la factura")}
          {_filter_th("Confianza", "pop-confianza", _filter_checks("confianza", choices["confianza"]), col="confianza", sort="confianza", help="Calidad de la extracción: Revisar (dudosa), Aceptable o Validado por ti")}
          {_filter_th("Total", "pop-total", total_inner, "num", col="total", sort="total", sort_type="num", help="Total pagado, IVA incluido")}
          <th class="num th-plain" data-col="articulos" data-sort="articulos" data-sort-type="num" title="Artículos con nombre en la factura"><span class="th-label">Artículos</span></th>
          {_filter_th("NIF emisor", "pop-nif", _filter_checks("nif", choices["nif"]), col="nif", sort="nif", help="NIF de la empresa emisora")}
          <th class="num th-plain" data-col="base" data-sort="base" data-sort-type="num" title="Base imponible (sin IVA)"><span class="th-label">Base</span></th>
          <th class="num th-plain" data-col="iva" data-sort="iva" data-sort-type="num" title="Cuota de IVA soportado"><span class="th-label">IVA</span></th>
          <th class="cell-doc th-plain" data-col="doc" data-sort="doc" title="Abrir el documento original (PDF o foto)"><span class="th-label">Doc</span></th>
          {_filter_th("Estado", "pop-estado", _filter_checks("estado", choices["estado"]), "col-estado", col="estado", sort="estado", help="Por revisar, Confirmado o Duplicado (fuera de totales)")}
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <nav class="pager" id="libro-pager" aria-label="Páginas del libro">
    <button type="button" class="ghost" id="libro-prev">Anterior</button>
    <span class="pager-pages" id="libro-pages"></span>
    <span class="pager-label" id="libro-pager-label"></span>
    <button type="button" class="ghost" id="libro-next">Siguiente</button>
  </nav>
  {empty}
</section>
"""


def _estado_action(item: dict) -> str:
    if item["estado"] == "duplicado":
        return (
            '<span class="estado-btn estado-dup" title="Duplicado: no entra en los totales">'
            "Duplicado</span>"
        )
    if item["validado"]:
        return (
            f'<button type="button" class="estado-btn estado-ok" data-reopen="{item["id"]}" '
            'title="Validado. Pulsa para devolver a revisión" '
            f'aria-label="Validado. Devolver asiento {item["id"]} a revisión">Validado</button>'
        )
    return (
        f'<button type="button" class="estado-btn estado-pend" data-validar="{item["id"]}" '
        'title="Pendiente de validar. Pulsa para confirmar" '
        f'aria-label="Por validar. Confirmar asiento {item["id"]}">Por validar</button>'
    )


def _row_html(item: dict) -> str:
    blob = " ".join(
        [
            str(item["id"]),
            item["fecha_label"],
            item["emisor"],
            item["nif"],
            item["numero"],
            item["cuenta"],
            item["cuenta_nombre"],
            item["tipo"],
            item["estado"],
            item["estado_label"],
            item["doc_name"],
        ]
    ).lower()
    doc_cell = "—"
    if item["has_doc"]:
        title = escape(item["doc_name"] or "Factura")
        doc_cell = (
            f'<a class="doc-link" href="/doc/{item["id"]}" target="_blank" '
            f'rel="noopener" title="{title}">Abrir</a>'
        )
    href = f"/asiento/{item['id']}"
    emisor = escape(item["emisor"])
    if item["emisor"] != "—":
        emisor = f'<span class="cell-text" title="{emisor}">{emisor}</span>'
    emisor = f'<a class="row-go" href="{href}">{emisor}</a>'
    numero = escape(item["numero"])
    factura = (
        f'<a class="row-go" href="{href}" title="{numero}">{numero}</a>{_docs_chip(item)}'
    )
    calidad = _quality_cell(item, prefix="libro")
    baja_flag = "1" if item["baja"] else "0"
    emisor_key = item["emisor"] if item["emisor"] != "—" else ""
    nif_val = "" if item["nif"] in {"", "—"} else item["nif"]
    pencil = (
        f'<button type="button" class="row-edit" data-edit="{item["id"]}" '
        f'title="Editar asiento" aria-label="Editar asiento {item["id"]}">{_PENCIL_SVG}</button>'
    )
    accion = f"{pencil}{_estado_action(item)}"
    return (
        f'<tr id="asiento-{item["id"]}" data-href="/asiento/{item["id"]}" data-id="{item["id"]}" '
        f'data-tipo="{escape(item["tipo"])}" '
        f'data-estado="{escape(item["estado"])}" data-baja="{baja_flag}" '
        f'data-fecha="{escape(item["fecha"])}" data-fecha-label="{escape(item["fecha_label"])}" '
        f'data-emisor="{escape(emisor_key)}" '
        f'data-cuenta="{escape(item["cuenta"])}" data-nif="{escape(nif_val)}" '
        f'data-numero="{escape(item["numero"])}" data-validado="'
        f'{"1" if item["validado"] else "0"}" '
        f'data-total="{item["total_num"]:.2f}" '
        f'data-base="{_amount_attr(item["base"])}" '
        f'data-iva="{_amount_attr(item["iva"])}" '
        f'data-estado-label="{escape(item["estado_label"])}" '
        f'data-q="{escape(blob)}">'
        f'<td class="mono col-sticky" data-col="id" data-label="Id">'
        f'<a class="row-go" href="/asiento/{item["id"]}">{item["id"]}</a></td>'
        f'<td class="mono cell-clip" data-col="factura" data-label="Nº factura">{factura}</td>'
        f'<td class="cell-nowrap" data-col="fecha" data-label="Fecha">'
        f'<a class="row-go" href="/asiento/{item["id"]}">{escape(item["fecha_label"])}</a></td>'
        f'<td class="cell-clip" data-col="emisor" data-label="Emisor">{emisor}</td>'
        f'<td class="cell-calidad" data-col="confianza" data-label="Confianza">{calidad}</td>'
        f'<td class="num cell-nowrap" data-col="total" data-label="Total">'
        f'<a class="total-drill" href="/asiento/{item["id"]}" '
        f'title="Ver detalle de la factura" aria-label="Detalle de la factura {item["id"]}">'
        f'<span class="total-amt">{escape(format_euro(item["total"]))}</span>'
        f'<span class="total-caret" aria-hidden="true">▸</span></a></td>'
        f'<td class="num cell-nowrap" data-col="articulos" data-label="Artículos">'
        f'<a class="row-go" href="{href}" title="Artículos de la factura {item["id"]}">'
        f'{item["n_articulos"] if item["n_articulos"] else "—"}</a></td>'
        f'<td class="mono cell-nowrap" data-col="nif" data-label="NIF">{escape(item["nif"])}</td>'
        f'<td class="num cell-nowrap" data-col="base" data-label="Base">{escape(format_euro(item["base"]))}</td>'
        f'<td class="num cell-nowrap" data-col="iva" data-label="IVA">{escape(format_euro(item["iva"]))}</td>'
        f'<td class="cell-doc" data-col="doc" data-label="Doc">{doc_cell}</td>'
        f'<td class="cell-estado" data-col="estado" data-label="Estado"><div class="row-actions">{accion}</div></td>'
        "</tr>"
    )


_CSS = r"""
:root {
  --ink: #1c1814;
  --muted: #6e655c;
  --paper: #efe7d9;
  --sheet: #fbf7ef;
  --line: #ddcfc0;
  --gasto: #9c3d2e;
  --ingreso: #2c5f52;
  --mejora: #7a6236;
  --neto: #243447;
  --warn: #a35b12;
  --link: #1d5f8c;
  --link-hover: #134868;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html { -webkit-text-size-adjust: 100%; }
html, body { margin: 0; background: var(--paper); color: var(--ink); }
html { height: 100%; }
body {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  font: 15px/1.45 "Avenir Next", "Segoe UI", system-ui, sans-serif;
  padding-left: env(safe-area-inset-left);
  padding-right: env(safe-area-inset-right);
  padding-bottom: env(safe-area-inset-bottom);
}
.wrap { width: min(1680px, calc(100% - 24px)); margin-inline: auto; max-width: 100%; }
.mast {
  background: var(--sheet);
  padding: 28px 0 0;
}
.mast-grid { padding-bottom: 22px; }
.eyebrow {
  margin: 0 0 6px;
  letter-spacing: .14em;
  text-transform: uppercase;
  font-size: 11px;
  color: var(--muted);
}
h1 {
  margin: 0;
  font: 600 34px/1.1 "Iowan Old Style", Palatino, "Palatino Linotype", serif;
}
.mast-h1 {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 12px;
}
.mast-h1 #mast-nombre { color: inherit; font: inherit; }
.mast-h1 #mast-kicker { color: var(--muted); font-size: 22px; font-weight: 500; }
.mast-edit { align-self: center; }
h1 span { color: var(--muted); font-size: 22px; font-weight: 500; }
.meta { margin: 8px 0 0; color: var(--muted); }
.mast-strip { margin: 10px 0 0; font-size: 13px; color: var(--muted); }
.panels {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  padding: 18px 0 8px;
}
.panel[hidden] { display: none !important; }
.tabs {
  width: 100%;
  background: var(--sheet);
  border-bottom: 1px solid var(--line);
}
.tabs-row { display: flex; gap: 4px; }
.tab {
  border: 0;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 14px;
  padding: 12px 14px 10px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.tab:hover { color: var(--ink); }
.tab[aria-selected="true"] {
  color: var(--ink);
  font-weight: 600;
  border-bottom-color: var(--ink);
}
.tab:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--neto);
}
.tab-badge {
  display: inline-block;
  min-width: 18px;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--warn);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
}
.tab[aria-selected="true"] .tab-badge { background: var(--ink); }
.panel-lead { margin: 0 0 14px; color: var(--muted); font-size: 13px; max-width: 62ch; }
.panel-head { margin: 0 0 14px; }
.panel-head h2 { margin: 0 0 4px; font: 600 22px/1 Palatino, serif; }
.panel-head p { margin: 0; color: var(--muted); font-size: 13px; max-width: 62ch; }
.review-table-wrap { overflow: auto; border: 1px solid var(--line); background: #fff; }
.review-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.review-table th, .review-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
.review-table th {
  text-align: left;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: var(--muted);
  background: var(--sheet);
}
.review-table .sub { display: block; margin-top: 4px; color: var(--muted); font-size: 12px; }
.review-row.review-baja { background: #fff8f0; }
.q-chip-wrap { position: relative; display: inline-flex; }
.q-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  font: inherit;
  font-size: 12px;
  padding: 4px 8px 4px 6px;
  cursor: pointer;
  white-space: nowrap;
}
.q-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ingreso);
  flex: 0 0 auto;
}
.q-chip.q-warn .q-dot { background: var(--warn); }
.q-chip.q-bad .q-dot { background: var(--gasto); }
.q-i {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid var(--line);
  font-size: 10px;
  font-style: italic;
  font-family: Palatino, serif;
  color: var(--muted);
}
.q-pop {
  inset: unset;
  margin: 0;
  position: fixed;
  z-index: 80;
  width: min(320px, calc(100vw - 24px));
  max-height: min(70vh, 420px);
  overflow: auto;
  padding: 12px 14px;
  background: var(--ink);
  color: var(--sheet);
  font-size: 12px;
  line-height: 1.45;
  border: 0;
  box-shadow: 0 10px 28px rgba(28, 24, 20, .28);
}
.q-pop strong { display: block; margin-bottom: 8px; font-size: 13px; }
.q-pop dl { margin: 0; display: grid; gap: 6px; }
.q-pop dl div { display: flex; justify-content: space-between; gap: 16px; align-items: baseline; }
.q-pop dt { color: #c9c2b6; flex: 0 0 auto; }
.q-pop dd { margin: 0; font-variant-numeric: tabular-nums; text-align: right; }
.q-pop p { margin: 10px 0 0; color: #d8d0c4; white-space: normal; overflow-wrap: anywhere; }
.resumen-kpis { margin-bottom: 12px; }
.empty.ok { color: var(--ingreso); padding: 16px; border: 1px solid var(--line); background: #fff; }
.kpis { padding: 22px 0 8px; }
.kpi-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.kpi, .kpi-btn {
  background: var(--sheet);
  border: 1px solid var(--line);
  border-top-width: 3px;
  padding: 14px 14px 12px;
  text-align: left;
  width: 100%;
  cursor: default;
}
.kpi span, .kpi-btn span { display: block; margin: 0; font-size: 12px; color: var(--muted); }
.kpi strong, .kpi-btn strong {
  display: block;
  margin-top: 8px;
  font: 600 26px/1 "Iowan Old Style", Palatino, serif;
}
.kpi em, .kpi-btn em { display: block; margin-top: 4px; font-style: normal; font-size: 12px; color: var(--muted); }
.kpi-btn:hover { transform: translateY(-1px); box-shadow: 0 2px 0 var(--line); }
.kpi-btn:focus-visible, .ghost:focus-visible, .cmd-btn:focus-visible, .export-btn:focus-visible, .funnel:focus-visible, .filter-search-input:focus-visible, .filter-all:focus-visible, .filter-done:focus-visible {
  outline: 2px solid var(--neto);
  outline-offset: 2px;
}
.kpi-btn[aria-pressed="true"] {
  background: var(--ink);
  color: var(--sheet);
  border-color: var(--ink);
}
.kpi-btn[aria-pressed="true"] span, .kpi-btn[aria-pressed="true"] em { color: #d8d0c4; }
.kpi-gasto { border-top-color: var(--gasto); }
.kpi-ingreso { border-top-color: var(--ingreso); }
.kpi-mejora { border-top-color: var(--mejora); }
.kpi-neto { border-top-color: var(--neto); }
.kpi-count { border-top-color: var(--warn); }
.hint { color: var(--muted); font-size: 13px; margin: 14px auto 0; }
.review {
  background: var(--sheet);
  border: 1px solid var(--line);
  border-left: 4px solid var(--warn);
  padding: 16px 18px;
  margin: 8px 0 20px;
}
.review-head { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: baseline; margin-bottom: 12px; }
.review-head h2 { margin: 0; font: 600 20px/1 Palatino, serif; }
.review-head p { margin: 0; color: var(--muted); font-size: 13px; }
.review ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.action {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  background: #fff;
}
.action-main {
  display: block;
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  color: inherit;
  font: inherit;
  cursor: pointer;
  padding: 0;
}
.action strong { display: block; font-size: 14px; }
.action p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
.cmd-now { margin: 8px 0 0 !important; font-size: 12px !important; }
.cmds { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.cmd-btn {
  border: 1px solid var(--line);
  background: var(--paper);
  color: var(--ink);
  font: inherit;
  font-size: 12px;
  padding: 6px 10px;
  cursor: pointer;
}
.cmd-btn-ok { border-color: var(--ingreso); }
.cmd-btn.copied { background: var(--ingreso); color: #fff; border-color: var(--ingreso); }
.cmd-slot {
  display: block;
  margin: 8px 0 0;
  padding: 8px 10px;
  background: var(--paper);
  border: 1px dashed var(--line);
  font: 12px ui-monospace, "SF Mono", Menlo, monospace;
  white-space: pre-wrap;
}
.cmd-slot[hidden] { display: none; }
.review-toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 12px 0 0; }
.hint-inline { color: var(--muted); font-size: 12px; }
.ghost {
  border: 1px solid var(--line);
  background: transparent;
  color: var(--ink);
  font: inherit;
  font-size: 12px;
  padding: 6px 10px;
  cursor: pointer;
}
.insights, .irpf {
  background: var(--sheet);
  border: 1px solid var(--line);
  padding: 16px 18px;
  margin: 0 0 20px;
}
.insight-block + .insight-block { margin-top: 28px; }
.insight-sub {
  margin: 18px 0 0;
  font-size: 13px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
}
.insight-aviso {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}
.insight-range {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: end;
  margin: 12px 0 4px;
}
.insight-range-year { font-size: 13px; padding-bottom: 8px; }
.insight-range label {
  display: grid;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}
.insight-range input {
  font: inherit;
  color: var(--ink);
  padding: 6px 8px;
  border: 1px solid var(--line);
  background: #fff;
}
.insight-presets { display: flex; flex-wrap: wrap; gap: 6px; width: 100%; }
.insight-preset {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--line);
  background: #fff;
  padding: 4px 8px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.insight-preset.is-on { border-color: var(--ink); background: var(--paper); }
.insight-trims { width: auto; }
.filter-trims { display: flex; gap: 6px; }
.kan-embudo { display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; margin: 0 0 14px; padding: 10px 14px; background: #fff; border: 1px solid var(--line); }
.kan-embudo > div { display: grid; gap: 2px; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.kan-embudo strong { font: 600 20px/1 Palatino, serif; color: var(--ink); }
.kan-progreso { grid-template-columns: auto auto auto; align-items: center; gap: 8px !important; margin-left: auto; }
.kan-barra { width: 120px; height: 6px; background: var(--paper); border: 1px solid var(--line); }
.kan-barra i { display: block; height: 100%; background: var(--ingreso); }
.kan-board { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; align-items: start; }
.kan-col { border: 1px solid var(--line); background: var(--sheet); min-height: 120px; }
.kan-col-cab { display: flex; justify-content: space-between; align-items: baseline; padding: 8px 10px; border-bottom: 1px solid var(--line); font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.kan-num { font: 600 16px/1 Palatino, serif; color: var(--ink); }
.kan-cuerpo { display: grid; gap: 8px; padding: 10px; }
.kan-card { background: #fff; border: 1px solid var(--line); padding: 8px 10px; display: grid; gap: 3px; cursor: grab; }
.kan-card:active { cursor: grabbing; }
.kan-card.dragging { opacity: .5; }
.kan-col.over { outline: 2px dashed var(--ink); outline-offset: -4px; }
.kan-ref { font-weight: 600; font-size: 13px; color: inherit; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kan-ref:hover { text-decoration: underline; }
.kan-datos { font-size: 11.5px; }
.kan-card strong { font: 600 16px/1.1 Palatino, serif; }
.kan-acciones { display: flex; gap: 6px; margin-top: 4px; }
.kan-act { width: 24px; height: 22px; border: 1px solid var(--line); background: #fff; cursor: pointer; font: inherit; font-size: 12px; color: var(--muted); }
.kan-act:hover { border-color: var(--ink); color: var(--ink); }
.kan-vacio { margin: 0; padding: 14px 10px; font-size: 12px; color: var(--muted); }
.rev-vistas { display: flex; gap: 6px; margin: 0 0 10px; }
.rev-vistas .ghost[aria-pressed="true"] { border-color: var(--ink); background: var(--paper); }
.kan-mas { border: 1px dashed var(--line); background: transparent; padding: 6px; font: inherit; font-size: 12px; color: var(--muted); cursor: pointer; }
.rechazo-opciones { display: grid; gap: 6px; margin: 10px 0; }
.rechazo-opciones .filter-opt { align-items: baseline; }
.rev-tabla .kan-celda-act { white-space: nowrap; }
.ficha-dup { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.ficha-dup .hint { margin: 0; }
.dup-par { display: grid; grid-template-columns: 1fr auto 1fr; gap: 14px; align-items: center; }
.dup-lado { display: grid; gap: 2px; }
.dup-lado a { font-weight: 600; }
.dup-rol { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0; }
.dup-emisor { margin: 0; }
.dup-vinclo { color: var(--muted); font-size: 20px; }
.dup-vacio { border: 1px dashed var(--line); background: var(--sheet); padding: 18px; color: var(--muted); }
.dup-tabla { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 13px; }
.dup-tabla th { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); white-space: nowrap; }
.dup-tabla .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.dup-tabla tbody tr { cursor: pointer; }
.dup-tabla tbody tr:hover, .dup-tabla tbody tr:focus { background: var(--paper); outline: none; }
.dup-tabla a, #dup-gestor .dup-ref { color: inherit; text-decoration: none; }
.dup-tabla a:hover, #dup-gestor .dup-ref:hover { text-decoration: underline; }
.dup-abrir { color: var(--muted); text-align: right; width: 24px; }
#dup-gestor .dup-gestor-cuerpo { padding: 20px 20px 4px; }
#dup-gestor h2 { margin: 0 0 2px; font-size: 22px; }
#dup-gestor .dup-gestor-eyebrow { margin: 0 0 4px; font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }
#dup-gestor .dup-motivo-caja {
  border-left: 3px solid var(--warn);
  background: var(--paper);
  padding: 8px 12px;
  margin: 12px 0 14px;
  font-size: 13px;
  color: var(--muted);
}
#dup-gestor .dup-par { gap: 10px; margin: 0; align-items: stretch; }
#dup-gestor .dup-lado {
  border: 1px solid var(--line);
  background: #fff;
  padding: 0 14px 12px;
  gap: 3px;
  display: grid;
}
#dup-gestor .dup-lado-cab {
  display: flex; align-items: center; justify-content: space-between;
  margin: 0 -14px 10px; padding: 7px 14px;
  border-bottom: 1px solid var(--line);
}
#dup-gestor .dup-lado-bueno .dup-lado-cab { background: #eef7f3; border-bottom-color: #9bc4b8; }
#dup-gestor .dup-lado-fuera .dup-lado-cab { background: #f3f0ea; border-bottom-color: var(--line); }
#dup-gestor .dup-lado-revisar .dup-lado-cab { background: #fff6eb; border-bottom-color: #d4a574; }
#dup-gestor .dup-ref { font-weight: 600; font-size: 13px; }
#dup-gestor .dup-datos { font-size: 12px; }
#dup-gestor .dup-importe { font: 600 22px/1.2 Palatino, serif; margin-top: 6px; }
#dup-gestor .dup-vinclo {
  align-self: center; display: grid; place-items: center;
  width: 34px; height: 34px; border-radius: 50%;
  background: var(--sheet); border: 1px solid var(--line);
  color: var(--muted); font-size: 15px;
}
#dup-gestor .dup-gestor-pie {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  border-top: 1px solid var(--line);
  margin: 16px 0 0; padding: 12px 20px;
  background: var(--paper);
}
#dup-gestor .dup-ficha-link { font-size: 13px; color: var(--link); }
#dup-gestor .dup-gestor-acciones { display: flex; gap: 8px; }
#dup-gestor .dup-gestor-acciones .export-btn { margin-top: 0; }
@media (max-width: 640px) {
  .dup-par { grid-template-columns: 1fr; }
  #dup-gestor .dup-vinclo { display: none; }
}
.dup-campo { display: grid; gap: 4px; margin: 10px 0 0; font-size: 13px; color: var(--muted); }
.dup-select, .dup-manual {
  font: inherit; color: var(--ink);
  padding: 6px 8px; border: 1px solid var(--line); background: #fff;
}
.dup-select:disabled, .dup-manual:disabled { opacity: .5; }
.filter-trim {
  border: 1px solid var(--line);
  background: #fff;
  padding: 4px 10px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.filter-trim.is-on { border-color: var(--ink); background: var(--paper); }
.iva-tabla { width: 100%; border-collapse: collapse; background: #fff; }
.iva-tabla th, .iva-tabla td { border: 1px solid var(--line); padding: 6px 10px; font-size: 13px; text-align: left; }
.iva-tabla th { background: var(--paper); font-size: 12px; color: var(--muted); }
.iva-tabla .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.iva-vacia td { color: var(--muted); font-style: italic; }
.insight-frase {
  margin: 14px 0 4px;
  font: 600 22px/1.3 Palatino, "Iowan Old Style", serif;
}
.chart-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.chart-scroll svg { min-width: 640px; }
.irpf-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.irpf-kpis article { border: 1px solid var(--line); padding: 10px 12px; background: #fff; }
.irpf-kpis span { display: block; font-size: 12px; color: var(--muted); }
.irpf-kpis strong { display: block; margin-top: 6px; font: 600 20px/1 Palatino, serif; }
.muted { color: var(--muted); font-size: 12px; }
.foot {
  margin-top: auto;
  padding-top: 40px;
  color: var(--muted);
  font-size: 13px;
}
.site-foot {
  margin-top: auto;
  padding: 24px 0 48px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}
.site-foot p { margin: 0; }
.site-foot p + p { margin-top: 4px; }
.site-foot a { color: var(--link); text-decoration: none; }
.site-foot a:hover { text-decoration: underline; text-underline-offset: 2px; }
.export-btn {
  display: inline-block;
  margin-top: 10px;
  padding: 10px 16px;
  background: var(--neto);
  color: #f4efe6;
  font: 600 14px/1 "Avenir Next", "Segoe UI", system-ui, sans-serif;
  text-decoration: none;
  border: 0;
  border-radius: 2px;
  cursor: pointer;
}
.export-btn:hover { filter: brightness(1.08); }
.export-btn-inline { margin-top: 0; padding: 8px 12px; font-size: 13px; }
.foot-actions { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.export-full { margin-top: 10px; }
.toast {
  position: fixed;
  right: 16px;
  bottom: 16px;
  max-width: min(440px, calc(100% - 32px));
  background: var(--ink);
  color: var(--sheet);
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.4;
  white-space: pre-wrap;
  z-index: 90;
}
tbody tr.flash { background: rgba(163, 91, 18, .12); }
.charts {
  display: grid;
  grid-template-columns: 1.3fr 0.7fr;
  gap: 12px;
  margin: 16px 0 0;
}
figure {
  margin: 0;
  background: #fff;
  border: 1px solid var(--line);
  padding: 14px 14px 8px;
}
figcaption {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  align-items: baseline;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
}
.swatch { color: var(--ink); font-size: 12px; }
.swatch::before {
  content: "";
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-right: 5px;
  vertical-align: 0;
}
.swatch.g::before { background: var(--gasto); }
.swatch.i::before { background: var(--ingreso); }
.swatch.m::before { background: var(--mejora); }
figure svg { width: 100%; height: auto; display: block; }
.grid { stroke: var(--line); stroke-width: 1; }
.tick, .axis, .legend { font: 11px/1 "Avenir Next", system-ui, sans-serif; fill: var(--muted); }
.tick { text-anchor: end; }
.axis { text-anchor: middle; }
.axis.left { text-anchor: start; fill: var(--ink); font-size: 12px; }
.tick.right { text-anchor: start; fill: var(--ink); font-size: 11px; }
.bar-label { font: 10px/1 "Avenir Next", system-ui, sans-serif; fill: var(--ink); text-anchor: middle; }
.bar-g { fill: var(--gasto); }
.bar-i { fill: var(--ingreso); }
.bar-m { fill: var(--mejora); }
.ledger { background: var(--sheet); border: 1px solid var(--line); padding: 16px 16px 8px; margin-bottom: 12px; }
.libro-kpis {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin: 0 0 14px;
}
.libro-kpis > div {
  background: #fff;
  border: 1px solid var(--line);
  padding: 12px 14px 11px;
  min-width: 0;
}
.libro-kpis span {
  display: block;
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
}
.libro-kpis strong {
  display: block;
  margin-top: 6px;
  font: 600 22px/1.15 "Iowan Old Style", Palatino, serif;
  font-variant-numeric: tabular-nums;
}
.libro-kpis em:empty { display: none; }
.libro-kpis em {
  display: block;
  margin-top: 4px;
  font-style: normal;
  font-size: 12px;
  color: var(--muted);
}
.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin: 12px 0 4px;
}
.pager-pages { display: flex; flex-wrap: wrap; gap: 4px; }
.pager-num {
  min-width: 32px;
  height: 32px;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.pager-num.is-on { background: var(--ink); color: var(--sheet); border-color: var(--ink); }
.pager-label {
  min-width: 7em;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.pager .ghost:disabled { opacity: .4; cursor: default; }
.ledger-status { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin: 0 0 10px; }
.ledger-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-left: auto; }
.status { margin: 0; font-size: 13px; color: var(--muted); min-height: 1.2em; }
.status.empty-query { color: var(--warn); }
.table-scroll-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--muted);
}
.table-wrap {
  overflow: auto;
  max-height: min(70vh, 720px);
  border: 1px solid var(--line);
  background: #fff;
  -webkit-overflow-scrolling: touch;
  scrollbar-gutter: stable both-edges;
}
.ledger-table {
  width: 100%;
  min-width: 1080px;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 13px;
}
.col-id { width: 6%; }
.col-factura { width: 11%; }
.col-fecha { width: 10%; }
.col-emisor { width: 14%; }
.col-calidad { width: 10%; }
.col-total { width: 7%; }
.col-articulos { width: 7%; }
.col-nif { width: 9%; }
.col-base, .col-iva { width: 6%; }
.col-doc { width: 4%; }
.col-estado { width: 12%; }
th[data-col="id"], td[data-col="id"] { min-width: 6.4em; }
th[data-col="factura"], td[data-col="factura"] { min-width: 9em; }
th[data-col="fecha"], td[data-col="fecha"] { min-width: 10em; }
th[data-col="emisor"], td[data-col="emisor"] { min-width: 8em; }
th[data-col="confianza"], td[data-col="confianza"] { min-width: 8em; }
th[data-col="estado"], td[data-col="estado"] { min-width: 9.5em; }
th[data-col="total"], td[data-col="total"] { min-width: 5.5em; }
th[data-col="articulos"], td[data-col="articulos"] { min-width: 6.4em; }
th[data-col="nif"], td[data-col="nif"] { min-width: 7em; }
.ledger-table.col-off-factura [data-col="factura"],
.ledger-table.col-off-confianza [data-col="confianza"],
.ledger-table.col-off-nif [data-col="nif"],
.ledger-table.col-off-base [data-col="base"],
.ledger-table.col-off-iva [data-col="iva"],
.ledger-table.col-off-doc [data-col="doc"] { display: none; }
.row-actions { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.row-edit,
.estado-btn {
  box-sizing: border-box;
  height: 28px;
  border: 1px solid var(--line);
  background: #fff;
  cursor: pointer;
  border-radius: 6px;
  font: 600 12px/1 inherit;
}
.row-edit {
  flex: 0 0 28px;
  width: 28px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--ink);
}
.row-edit svg {
  width: 14px;
  height: 14px;
  display: block;
  flex-shrink: 0;
}
.row-edit:hover { border-color: var(--ink); }
.estado-btn {
  flex: 0 0 auto;
  min-width: 7.4em;
  padding: 0 10px;
  text-align: center;
  border-radius: 999px;
  letter-spacing: .02em;
}
.estado-btn.estado-ok {
  background: var(--ingreso);
  border-color: var(--ingreso);
  color: #fff;
}
.estado-btn.estado-ok:hover { filter: brightness(.92); }
.estado-btn.estado-pend {
  background: var(--gasto);
  border-color: var(--gasto);
  color: #fff;
}
.estado-btn.estado-pend:hover { filter: brightness(.92); }
.estado-btn.estado-dup {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f3f0ea;
  color: var(--muted);
  cursor: default;
}
.edit-dialog {
  width: min(560px, calc(100vw - 24px));
  max-height: min(88vh, 720px);
  overflow: auto;
  border: 1px solid var(--line);
  padding: 0;
  background: var(--sheet);
  color: var(--ink);
  box-shadow: 0 16px 40px rgba(28, 24, 20, .22);
}
.edit-dialog::backdrop { background: rgba(28, 24, 20, .42); }
.app-confirm { width: min(420px, calc(100vw - 32px)); }
.app-confirm h2 { font-size: 18px; }
.export-btn.is-warn { background: var(--gasto); }
.edit-dialog form { padding: 18px 18px 16px; }
.edit-dialog h2 { margin: 0 0 8px; font: 600 20px/1.2 Palatino, serif; }
.edit-dialog p { margin: 0 0 12px; color: var(--muted); font-size: 13px; }
.edit-meta { font-size: 13px; }
.edit-dialog label { display: block; margin: 0 0 10px; font-size: 12px; color: var(--muted); }
.edit-dialog label input:not([type=checkbox]) {
  display: block;
  width: 100%;
  margin-top: 4px;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  font: inherit;
  padding: 8px 10px;
}
.edit-check { display: flex !important; align-items: flex-start; gap: 8px; color: var(--ink) !important; font-size: 13px !important; }
.edit-check input { margin-top: 2px; }
.edit-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.edit-actions .export-btn { margin-top: 0; }
.edit-log-title { margin: 14px 0 6px; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
.edit-log { margin: 0; padding-left: 18px; max-height: 120px; overflow: auto; font-size: 12px; color: var(--muted); }
.edit-log li { margin: 0 0 4px; }
.edit-lines-wrap { max-height: 160px; overflow: auto; border: 1px solid var(--line); background: #fff; margin: 0 0 6px; }
.edit-lines { width: 100%; border-collapse: collapse; font-size: 12px; }
.edit-lines th, .edit-lines td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); }
.edit-lines th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
.edit-lines td:last-child, .edit-lines th:last-child { text-align: right; white-space: nowrap; }
.edit-lines td:first-child, .edit-lines th:first-child { width: 2.2em; color: var(--muted); }
.edit-lines td.mono { font-size: 12px; }
.line-totals {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  margin: 18px 0 8px;
  padding: 0;
  background: transparent;
  color: var(--ink);
}
.line-totals .line-total {
  min-width: 128px;
  background: #fff;
  border: 1px solid var(--line);
  padding: 12px 14px;
}
.line-totals span {
  display: block;
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
}
.line-totals strong {
  display: block;
  margin-top: 4px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0;
  color: var(--ink);
}
.line-totals .is-total { border-color: var(--ink); }
.line-totals .is-total strong { font-size: 22px; }
.edit-lines-note { font-size: 12px !important; margin: 0 0 12px !important; }
.edit-lines-note.ok { color: var(--ingreso) !important; }
.total-drill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin: 0;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
  text-decoration: none;
}
.total-drill:hover .total-amt { text-decoration: underline; }
.total-caret { color: var(--muted); font-size: 11px; }
tbody tr[data-href] { cursor: pointer; }
a.row-go { color: inherit; text-decoration: none; }
a.row-go:hover { text-decoration: underline; }
.ficha-page { min-height: 100vh; }
.ficha-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 0 0;
}
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--muted);
  text-decoration: none;
}
.back-link svg { flex-shrink: 0; }
.back-link:hover { color: var(--link); text-decoration: underline; text-underline-offset: 3px; }
.ficha { flex: 1 1 auto; padding: 12px 0 48px; }
.ficha-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px 24px;
  flex-wrap: wrap;
  margin: 0 0 18px;
}
.ficha-kicker { margin: 0 0 4px; font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.ficha h1 { margin: 0 0 8px; font: 600 28px/1.2 Palatino, serif; }
.ficha-sub { margin: 0; }
.doc-open {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  margin-top: 4px;
  color: var(--link);
  font-weight: 600;
  text-decoration: none;
}
.doc-open svg { flex-shrink: 0; }
.doc-open > span:first-of-type {
  text-decoration: underline;
  text-decoration-thickness: 1.5px;
  text-underline-offset: 3px;
}
.doc-open:hover { color: var(--link-hover); }
.doc-open-name {
  color: var(--muted);
  font-weight: 500;
  font-size: 13px;
  text-decoration: none;
  max-width: 18ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kpi-carousel { margin: 0 0 22px; }
.ficha-grid {
  display: flex;
  gap: 10px;
  margin: 0;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  scroll-behavior: smooth;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
  touch-action: pan-x;
  cursor: grab;
}
.ficha-grid.is-dragging {
  cursor: grabbing;
  scroll-behavior: auto;
  scroll-snap-type: none;
  user-select: none;
}
.ficha-grid::-webkit-scrollbar { display: none; }
.ficha-grid > div {
  flex: 0 0 calc((100% - 40px) / 5);
  min-width: 0;
  scroll-snap-align: start;
  background: #fff;
  border: 1px solid var(--line);
  padding: 12px 14px;
}
.ficha-grid dt { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 4px; }
.ficha-grid dd { margin: 0; font-size: 16px; }
.kpi-dots {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
}
.kpi-dot {
  width: 7px;
  height: 7px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: #b7ad9f;
  cursor: pointer;
}
.kpi-dot.is-on { width: 18px; background: var(--ink); }
.ficha h2, .ficha-h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0 10px;
  font: 600 18px/1.2 Palatino, serif;
}
.ficha-h2 svg { color: var(--muted); flex-shrink: 0; }
.ficha-count {
  margin-left: 2px;
  font: 500 13px/1.2 "Avenir Next", "Segoe UI", system-ui, sans-serif;
  color: var(--muted);
  letter-spacing: 0;
  text-transform: none;
}
.ficha-score {
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 12px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid var(--line);
}
.ficha-score .q-chip { cursor: default; }
.q-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
  width: 100%;
}
.q-i-btn {
  align-self: flex-start;
  width: 20px; height: 20px;
  display: inline-grid; place-items: center;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: #fff;
  color: var(--muted);
  font: 600 11px/1 "Avenir Next", "Segoe UI", system-ui, sans-serif;
  cursor: pointer;
  padding: 0;
}
.ficha-score-cab { display: flex; align-items: center; gap: 8px; }
.q-i-btn:hover, .q-i-btn[aria-expanded="true"] { border-color: var(--ink); color: var(--ink); }
.q-solo-fallos { gap: 4px; margin-top: 2px; }
.q-pop-score { width: min(400px, calc(100vw - 24px)); }
.q-pop-list { display: grid; gap: 2px; margin: 0; padding: 0; list-style: none; }
.q-pop-list li { display: grid; gap: 1px; padding: 4px 0; border-bottom: 1px solid rgba(251, 247, 239, .12); }
.q-pop-list li:last-child { border-bottom: 0; }
.q-pop-list li span { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--sheet); }
.q-pop-list li span::before { content: "✓"; color: #9bc4b8; font-size: 11px; }
.q-pop-list li.is-bad span::before { content: "✕"; color: #d98c6a; }
.q-pop-list li em { font-style: normal; font-size: 11px; color: #c9c2b6; }
.q-checks li {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  margin: 0;
  padding: 2px 8px;
  border: 1px solid var(--line);
  font-size: 12px;
  color: var(--muted);
}
.q-checks li.is-ok span::before { content: "· "; color: var(--ingreso); }
.q-checks li.is-bad {
  flex-basis: 100%;
  color: var(--ink);
  border-color: #e4c2b8;
  background: #fbf6f3;
}
.q-checks li.is-bad span { color: var(--gasto); font-weight: 600; }
.q-checks em { font-style: normal; }
.q-score { font-weight: 600; font-variant-numeric: tabular-nums; }
.q-chip.q-muted .q-dot { background: var(--muted); }
.ficha-lines { max-height: min(70vh, 720px); }
.fl-n { width: 4%; }
.fl-id { width: 14%; }
.fl-concepto { width: 32%; }
.fl-uds { width: 6%; }
.fl-money { width: 8%; }
.fl-rate { width: 8%; }
.fl-act { width: 12%; }
.ficha-ledger td.line-actions .row-actions { justify-content: flex-end; }
.ficha-ledger th.line-actions { text-align: right; white-space: nowrap; }
#ficha-lines-editor tr.is-editing td.col-sticky,
#ficha-lines-editor tr.is-editing td.cell-estado { background: #fff6eb; }
#ficha-lines-editor.show-deleted tr.is-deleted td.col-sticky,
#ficha-lines-editor.show-deleted tr.is-deleted td.cell-estado { background: #f3efe8; }
#ficha-lines-editor tr:not(.is-editing) .line-edit { display: none; }
#ficha-lines-editor tr:not(.is-editing) .line-save,
#ficha-lines-editor tr:not(.is-deleted) .line-restore,
#ficha-lines-editor tr.is-deleted .line-edit-btn,
#ficha-lines-editor tr.is-deleted .line-save,
#ficha-lines-editor tr.is-deleted .line-del { display: none; }
#ficha-lines-editor tr.is-deleted { display: none; }
#ficha-lines-editor.show-deleted tr[data-line]:not(.is-deleted) { display: none; }
#ficha-lines-editor.show-deleted tr.is-deleted { display: table-row; background: #f3efe8; }
#ficha-lines-editor tr.is-editing .line-view,
#ficha-lines-editor tr.is-editing .line-edit-btn { display: none; }
#ficha-lines-editor tr.is-editing { background: #fff6eb; }
#ficha-lines-editor tr.is-editing .line-edit {
  width: 100%;
  box-sizing: border-box;
  font: inherit;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  padding: 6px 8px;
}
#ficha-lines-editor tr.is-editing .line-calc {
  border-color: transparent;
  background: transparent;
  color: var(--muted);
}
.ficha-h2 #ficha-lines-eye { margin-left: 8px; }
.ficha-h2 #ficha-lines-eye.is-on { border-color: var(--ink); background: #ece4d6; }
.line-del { color: var(--gasto); }
.ficha-log-dialog { width: min(720px, calc(100vw - 32px)); padding: 18px 18px 16px; }
.ficha-log-dialog h2 {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ficha-log-dialog h2 svg { color: var(--muted); }
.log-table { margin: 0; }
.log-table td, .log-table th { vertical-align: top; }
.edit-diff { width: 100%; border-collapse: collapse; font-size: 13px; margin: 0 0 14px; background: #fff; }
.edit-diff th, .edit-diff td { text-align: left; padding: 8px; border-bottom: 1px solid var(--line); }
.edit-diff th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: #fff;
  box-shadow: 0 1px 0 var(--line);
  vertical-align: middle;
  white-space: nowrap;
  overflow: hidden;
}
thead th.col-sticky {
  left: 0;
  z-index: 4;
}
tbody td.col-sticky {
  position: sticky;
  left: 0;
  z-index: 1;
  background: #fff;
  box-shadow: 1px 0 0 var(--line);
}
tbody tr.is-band td.col-sticky { background: #f6f1e8; }
tbody tr:hover td.col-sticky { background: #faf6ef; }
thead th.col-estado {
  right: 0;
  z-index: 4;
  box-shadow: -8px 0 8px -8px rgba(28, 24, 20, .16);
}
tbody td.cell-estado {
  position: sticky;
  right: 0;
  z-index: 1;
  background: #fff;
  box-shadow: -8px 0 8px -8px rgba(28, 24, 20, .16);
}
tbody tr.is-band td.cell-estado { background: #f6f1e8; }
tbody tr:hover td.cell-estado { background: #faf6ef; }
th, td {
  text-align: left;
  padding: 10px 8px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
thead th {
  padding: 8px 10px;
  vertical-align: middle;
  white-space: nowrap;
}
.th-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: nowrap;
  min-width: 0;
}
.th-label {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
th[data-sort] .th-label { cursor: pointer; }
th.is-sorted .th-label::after { content: " ↑"; }
th.is-sorted.is-desc .th-label::after { content: " ↓"; }
.funnel {
  flex: 0 0 22px;
  width: 22px;
  height: 22px;
  border: 0;
  padding: 0;
  display: grid;
  place-items: center;
  background: transparent;
  color: var(--muted);
  border-radius: 999px;
  cursor: pointer;
}
.funnel:hover, .funnel[aria-expanded="true"] {
  background: #ece4d6;
  color: var(--ink);
}
.funnel.on {
  background: #d7eee6;
  color: var(--ingreso);
}
.funnel svg {
  width: 13px;
  height: 13px;
}
.filter-pop {
  inset: auto;
  margin: 0;
  width: 280px;
  max-height: min(420px, calc(100vh - 24px));
  overflow: auto;
  padding: 12px 12px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  color: var(--ink);
  box-shadow: 0 10px 28px rgba(28, 24, 20, .16);
  text-transform: none;
  letter-spacing: 0;
  font-weight: 400;
}
.filter-pop-title {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--muted);
}
.filter-search {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 7px 10px;
  color: var(--muted);
  background: var(--sheet);
}
.filter-search svg {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}
.filter-search-input {
  flex: 1;
  min-width: 0;
  border: 0;
  background: transparent;
  font: 14px/1.3 "Avenir Next", "Segoe UI", system-ui, sans-serif;
  color: var(--ink);
  outline: none;
}
.filter-all {
  display: block;
  margin: 10px 0 8px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--ingreso);
  font: 600 13px/1.3 inherit;
  cursor: pointer;
}
.filter-opts {
  max-height: 220px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 4px 0;
}
.filter-opt {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 10px;
  font-size: 13px;
  cursor: pointer;
}
.filter-opt:hover { background: var(--sheet); }
.filter-opt[hidden] { display: none; }
.filter-opt input { margin-top: 2px; }
.filter-empty, .filter-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--muted);
}
.filter-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--muted);
}
.filter-field input {
  font: 14px/1.3 "Avenir Next", "Segoe UI", system-ui, sans-serif;
  padding: 7px 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--ink);
}
.filter-field input[type=date] {
  min-height: 34px;
}
.filter-pop-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}
.cols-pop .filter-pop-foot { justify-content: space-between; align-items: center; }
.filter-done {
  border: 0;
  background: none;
  color: var(--muted);
  font: 600 13px/1 inherit;
  cursor: pointer;
  padding: 4px 0;
}
.cell-clip,
.cell-nowrap {
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 0;
}
.cell-clip {
  white-space: nowrap;
}
.cell-clip .row-go,
.cell-clip .cell-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell-rubro { white-space: nowrap; }
.cell-nowrap { white-space: nowrap; }
.cell-calidad { white-space: nowrap; min-width: 0; }
.cell-estado { text-align: left; white-space: nowrap; }
.cell-doc { text-align: center; white-space: nowrap; }
thead th.num, tbody td.num { text-align: right; }
thead th.cell-doc { text-align: center; }
thead th.num .th-head { justify-content: flex-end; }
thead th.col-estado .th-head { justify-content: flex-start; }
thead th.cell-doc .th-head { justify-content: center; }
thead th.col-sticky { text-align: left; }
tbody td.col-sticky { text-align: center; }
tbody tr.is-band { background: #f6f1e8; }
tbody tr:hover { background: #faf6ef; }
#ficha-lines-editor tr.is-editing,
#ficha-lines-editor tr.is-editing td.col-sticky,
#ficha-lines-editor tr.is-editing td.cell-estado { background: #fff6eb; }
#ficha-lines-editor.show-deleted tr.is-deleted,
#ficha-lines-editor.show-deleted tr.is-deleted td.col-sticky,
#ficha-lines-editor.show-deleted tr.is-deleted td.cell-estado { background: #f3efe8; }
th {
  color: var(--muted);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.num { font-variant-numeric: tabular-nums; }
.mono { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; }
.pill {
  display: inline-block;
  padding: 2px 8px;
  border: 1px solid var(--line);
  font-size: 11px;
  letter-spacing: .03em;
  border-radius: 999px;
  background: #fff;
}
.pill.pendiente { color: var(--warn); border-color: #d4a574; background: #fff6eb; }
.pill.confirmado { color: var(--ingreso); border-color: #9bc4b8; background: #eef7f3; }
.pill.duplicado { color: var(--muted); background: #f3f0ea; }
.docs-chip {
  display: inline-block;
  margin-left: 4px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10px;
  font-family: inherit;
  letter-spacing: .02em;
  background: #f3f0ea;
  color: var(--muted);
  vertical-align: 1px;
}
.docs-chip.warn { background: #fff6eb; color: var(--warn); }
.doc-link { font-weight: 600; color: var(--neto); text-decoration: none; border-bottom: 1px solid transparent; }
.doc-link:hover { border-bottom-color: var(--neto); }
.empty { color: var(--muted); padding: 12px; }
@media (max-width: 1100px) {
  .kan-board { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .wrap { width: calc(100% - 20px); }
  .ficha-page .wrap { width: calc(100% - 20px); }
  h1 { font-size: 28px; }
  .mast { padding-top: 20px; }
  .mast-h1 #mast-kicker, h1 span { font-size: 18px; }
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ledger-table th, .ledger-table td { padding: 5px 8px; font-size: 12px; }
  .ledger-table .th-label { font-size: 10px; letter-spacing: .04em; }
  .ledger-table .funnel { width: 22px; height: 22px; }
  .kpi-grid > :last-child { grid-column: 1 / -1; }
  .irpf-kpis, .charts { grid-template-columns: 1fr 1fr; display: grid; }
  .charts figure:last-child { grid-column: auto; }
  .ledger { padding: 12px 12px 8px; }
  .ledger-table { min-width: 980px; font-size: 12px; }
  .table-wrap { max-height: min(68vh, 640px); }
  .edit-dialog { width: min(560px, calc(100vw - 20px)); max-height: min(90dvh, 720px); }
}
@media (max-width: 700px) {
  .kan-board { grid-template-columns: 1fr; }
  .wrap, .ficha-page .wrap { width: calc(100% - 16px); }
  .mast { padding-top: 16px; }
  h1 { font-size: 24px; }
  .mast-h1 { gap: 6px 8px; }
  .mast-h1 #mast-kicker, h1 span { font-size: 16px; }
  .meta, .mast-strip, .panel-lead { font-size: 13px; }
  .ledger-table th, .ledger-table td { padding: 4px 6px; font-size: 11.5px; }
  .ledger-table .th-label { font-size: 9.5px; }
  .kpis { padding: 14px 0 4px; }
  .kpi, .kpi-btn { padding: 12px; }
  .kpi strong, .kpi-btn strong { font-size: 22px; }
  .kpi-grid, .libro-kpis { grid-template-columns: 1fr 1fr; gap: 8px; }
  .irpf-kpis, .charts { grid-template-columns: 1fr; display: grid; }
  .tabs-row { gap: 0; }
  .tab { flex: 1 1 auto; text-align: center; padding: 14px 10px 12px; }
  .ledger-status { gap: 8px; }
  .ledger-actions { margin-left: auto; }
  .foot-actions { flex-direction: column; align-items: stretch; }
  .foot-actions .export-btn, .foot-actions .ghost { width: 100%; text-align: center; }
  .action { align-items: flex-start; }
  body { overflow-x: hidden; }
  .table-scroll-hint { display: block; }
  .ledger .table-wrap {
    max-width: 100%;
    max-height: min(70dvh, 640px);
    overflow-x: auto;
    overflow-y: auto;
    border: 1px solid var(--line);
    -webkit-overflow-scrolling: touch;
    overscroll-behavior-x: contain;
    scrollbar-gutter: stable;
  }
  .ledger .table-wrap::-webkit-scrollbar { height: 8px; }
  .ledger .table-wrap::-webkit-scrollbar-thumb {
    background: #c8bfb2;
    border-radius: 999px;
  }
  .ledger-table {
    min-width: 980px;
    width: max-content;
    font-size: 12px;
  }
  .ledger-table thead th.col-sticky,
  .ledger-table tbody td.col-sticky,
  .ledger-table thead th.col-estado,
  .ledger-table tbody td.cell-estado {
    position: static;
    box-shadow: none;
  }
  .ficha { padding-bottom: 28px; }
  .ficha h1 { font-size: 22px; }
  .ficha-grid > div { flex-basis: calc((100% - 10px) / 2); }
  .ficha-lines input { width: 100%; box-sizing: border-box; font: inherit; }
  .ficha .edit-lines { min-width: 560px; }
  .ficha-score { align-items: flex-start; }
  .doc-open { width: 100%; }
  .site-foot { padding-bottom: calc(40px + env(safe-area-inset-bottom)); }
}
@media (pointer: coarse) {
  .tab, .ghost, .export-btn, .estado-btn, .filter-done, .back-link {
    min-height: 44px;
  }
  .row-edit, .mast-edit {
    width: 36px;
    height: 36px;
    flex-basis: 36px;
  }
  .funnel, .q-chip { min-height: 36px; }
}
@media print {
  body { background: #fff; min-height: 0; display: block; }
  .foot, .site-foot { margin-top: 24px; padding-top: 16px; padding-bottom: 16px; }
  .kpi-btn, .ghost, .cmd-btn, .review, .tabs, .funnel, .filter-pop, .export-btn { display: none; }
  .mast, .kpi, figure, .ledger { break-inside: avoid; }
  .table-wrap { max-height: none; }
}
"""

_JS = r"""
(() => {
  const panels = [...document.querySelectorAll("[role=tabpanel]")];
  const tabs = [...document.querySelectorAll("[role=tab]")];
  const defaultPanel = document.body.dataset.defaultPanel || "libro";
  const kpiButtons = [...document.querySelectorAll(".kpi-btn")];
  const input = document.getElementById("q");
  const status = document.getElementById("status");
  const rows = [...document.querySelectorAll(".ledger-table tbody tr")];
  const fMin = document.getElementById("f-min");
  const fMax = document.getElementById("f-max");
  const fDesde = document.getElementById("f-desde");
  const fHasta = document.getElementById("f-hasta");
  const fClear = document.getElementById("f-clear");

  const showPanel = (name, { focusTab = false } = {}) => {
    for (const panel of panels) {
      panel.hidden = panel.dataset.panel !== name;
    }
    for (const tab of tabs) {
      const active = tab.dataset.panel === name;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
      if (active && focusTab) tab.focus();
    }
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => showPanel(tab.dataset.panel));
    tab.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      event.preventDefault();
      const dir = event.key === "ArrowRight" ? 1 : -1;
      const idx = tabs.indexOf(tab);
      const next = tabs[(idx + dir + tabs.length) % tabs.length];
      showPanel(next.dataset.panel, { focusTab: true });
    });
  });
  showPanel(defaultPanel);

  const formatEuro = (value) =>
    new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(value);

  const parseAmount = (raw) => {
    const text = (raw || "").trim().replace(",", ".");
    if (!text) return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  };

  const toast = (text) => {
    document.querySelector(".toast")?.remove();
    const node = document.createElement("div");
    node.className = "toast";
    node.textContent = text;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), 5000);
  };

  const groupBoxes = (name) => [...document.querySelectorAll(`input[data-fg="${name}"]`)];

  const selectedValues = (name) => {
    const boxes = groupBoxes(name);
    if (!boxes.length) return null;
    const on = boxes.filter((box) => box.checked).map((box) => box.value);
    if (on.length === 0) return new Set();
    if (on.length === boxes.length) return null;
    return new Set(on);
  };

  const setGroup = (name, allowed) => {
    for (const box of groupBoxes(name)) {
      box.checked = !allowed || allowed.has(box.value);
    }
  };

  const matchesGroup = (name, value) => {
    const selected = selectedValues(name);
    if (selected === null) return true;
    return selected.has(value);
  };

  const confianzaKey = (row) => {
    if (row.dataset.validado === "1") return "validado";
    if (row.dataset.baja === "1") return "baja";
    return "ok";
  };

  const dateLabel = (iso) => {
    if (!iso) return "";
    const [year, month, day] = iso.split("-");
    return `${day}/${month}/${year}`;
  };

  const matchesRow = (row) => {
    const q = (input?.value || "").trim().toLowerCase();
    if (q && !(row.dataset.q || "").includes(q)) return false;
    const desde = fDesde?.value || "";
    const hasta = fHasta?.value || "";
    if (desde || hasta) {
      const fecha = row.dataset.fecha || "";
      if (!fecha) return false;
      if (desde && fecha < desde) return false;
      if (hasta && fecha > hasta) return false;
    }
    if (!matchesGroup("emisor", row.dataset.emisor)) return false;
    if (!matchesGroup("nif", row.dataset.nif)) return false;
    if (!matchesGroup("factura", row.dataset.numero)) return false;
    if (!matchesGroup("rubro", row.dataset.cuenta)) return false;
    const estadoSel = selectedValues("estado");
    // Los duplicados viven en su pestaña; solo se ven si se piden a mano
    // desde el embudo de Estado.
    if (row.dataset.estado === "duplicado" && !estadoSel) return false;
    if (estadoSel && !estadoSel.has(row.dataset.tipo) && !estadoSel.has(row.dataset.estado)) return false;
    const confSel = selectedValues("confianza");
    if (confSel && !confSel.has(confianzaKey(row))) return false;
    const total = Number(row.dataset.total || 0);
    const min = parseAmount(fMin?.value);
    const max = parseAmount(fMax?.value);
    if (min !== null && total < min) return false;
    if (max !== null && total > max) return false;
    return true;
  };

  const activeBits = () => {
    const bits = [];
    const q = (input?.value || "").trim();
    if (q) bits.push(`«${q}»`);
    if (fDesde?.value && fHasta?.value) bits.push(`${dateLabel(fDesde.value)} – ${dateLabel(fHasta.value)}`);
    else if (fDesde?.value) bits.push(`desde ${dateLabel(fDesde.value)}`);
    else if (fHasta?.value) bits.push(`hasta ${dateLabel(fHasta.value)}`);
    if (selectedValues("emisor")) bits.push("emisor");
    if (selectedValues("confianza")) bits.push("confianza");
    if (selectedValues("estado")) bits.push("estado");
    if (selectedValues("rubro")) bits.push("rubro");
    if (selectedValues("nif")) bits.push("NIF");
    if (selectedValues("factura")) bits.push("factura");
    if (fMin?.value) bits.push(`mín. ${fMin.value} €`);
    if (fMax?.value) bits.push(`máx. ${fMax.value} €`);
    return bits;
  };

  const syncFunnels = () => {
    for (const th of document.querySelectorAll("th.th-filter")) {
      const btn = th.querySelector(".funnel");
      const pop = th.querySelector(".filter-pop");
      if (!btn || !pop) continue;
      const boxes = [...pop.querySelectorAll("input[data-fg]")];
      const boxDirty = boxes.length > 0 && boxes.some((box) => !box.checked);
      const rangeDirty = [...pop.querySelectorAll("input[type=number], input[type=date], #q")].some((el) => (el.value || "").trim());
      btn.classList.toggle("on", boxDirty || rangeDirty);
    }
  };

  const syncKpiPressed = () => {
    const estadoSel = selectedValues("estado");
    const confSel = selectedValues("confianza");
    for (const button of kpiButtons) {
      const key = button.dataset.filter;
      let active = false;
      if (key === "baja") {
        active = Boolean(confSel && confSel.size === 1 && confSel.has("baja"));
      } else if (key === "all") {
        active = !estadoSel && !confSel;
      } else {
        active = Boolean(!confSel && estadoSel && estadoSel.size === 1 && estadoSel.has(key));
      }
      button.setAttribute("aria-pressed", active ? "true" : "false");
    }
  };

  const applyIrpf = () => {
    const irpfRows = [...document.querySelectorAll("#irpf tbody tr")];
    if (!irpfRows.length) return;
    const min = parseAmount(document.getElementById("f-irpf-min")?.value);
    const max = parseAmount(document.getElementById("f-irpf-max")?.value);
    for (const row of irpfRows) {
      const amount = Number(row.dataset.irpfImporte || 0);
      const show = matchesGroup("irpf-concepto", row.dataset.irpfConcepto || "")
        && matchesGroup("irpf-resta", row.dataset.irpfResta || "")
        && (min === null || amount >= min)
        && (max === null || amount <= max);
      row.hidden = !show;
    }
  };

  const PAGE_SIZE = 15;
  let libroPage = 1;
  const libroPrev = document.getElementById("libro-prev");
  const libroNext = document.getElementById("libro-next");
  const libroPages = document.getElementById("libro-pages");
  const libroPagerLabel = document.getElementById("libro-pager-label");
  const paintLibroPager = (matchedCount) => {
    const pages = Math.max(1, Math.ceil(matchedCount / PAGE_SIZE) || 1);
    libroPage = Math.min(Math.max(1, libroPage), pages);
    if (libroPages) {
      libroPages.replaceChildren();
      for (let i = 1; i <= pages; i += 1) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "pager-num" + (i === libroPage ? " is-on" : "");
        btn.textContent = String(i);
        btn.setAttribute("aria-label", `Página ${i}`);
        if (i === libroPage) btn.setAttribute("aria-current", "page");
        btn.addEventListener("click", () => {
          libroPage = i;
          apply({ keepPage: true });
        });
        libroPages.appendChild(btn);
      }
    }
    if (libroPagerLabel) {
      if (!matchedCount) libroPagerLabel.textContent = "0 de 0";
      else {
        const start = (libroPage - 1) * PAGE_SIZE;
        const end = Math.min(start + PAGE_SIZE, matchedCount);
        libroPagerLabel.textContent = `${start + 1}–${end} de ${matchedCount}`;
      }
    }
    if (libroPrev) libroPrev.disabled = libroPage <= 1 || matchedCount === 0;
    if (libroNext) libroNext.disabled = libroPage >= pages || matchedCount === 0;
    const pager = document.getElementById("libro-pager");
    if (pager) pager.hidden = rows.length === 0;
  };

  const apply = (opts = {}) => {
    const bits = activeBits();
    let visible = 0;
    let totalVisible = 0;
    let baseVisible = 0;
    let ivaVisible = 0;
    let totalLibro = 0;
    const countsInBook = (row) => row.dataset.estado !== "duplicado";
    const matched = [];
    for (const row of rows) {
      const amount = Number(row.dataset.total || 0);
      const base = Number(row.dataset.base || 0);
      const iva = Number(row.dataset.iva || 0);
      if (countsInBook(row)) totalLibro += amount;
      const show = matchesRow(row);
      row.dataset.match = show ? "1" : "0";
      row.classList.remove("is-band");
      if (!show) {
        row.hidden = true;
        continue;
      }
      matched.push(row);
      visible += 1;
      if (countsInBook(row)) {
        totalVisible += amount;
        baseVisible += base;
        ivaVisible += iva;
      }
    }
    const pageCount = Math.max(1, Math.ceil(matched.length / PAGE_SIZE) || 1);
    if (opts.last) libroPage = pageCount;
    else if (!opts.keepPage) libroPage = 1;
    libroPage = Math.min(Math.max(1, libroPage), pageCount);
    const start = (libroPage - 1) * PAGE_SIZE;
    matched.forEach((row, index) => {
      const onPage = index >= start && index < start + PAGE_SIZE;
      row.hidden = !onPage;
      row.classList.toggle("is-band", onPage && (index - start) % 2 === 1);
    });
    paintLibroPager(matched.length);
    syncFunnels();
    syncKpiPressed();
    applyIrpf();
    if (fClear) fClear.hidden = bits.length === 0;
    const libroN = document.getElementById("libro-n");
    const libroNote = document.getElementById("libro-n-note");
    const libroTotal = document.getElementById("libro-total");
    const libroVisible = document.getElementById("libro-visible");
    const libroBase = document.getElementById("libro-base");
    const libroIva = document.getElementById("libro-iva");
    if (libroN) libroN.textContent = String(visible);
    if (libroNote) libroNote.textContent = visible === rows.length ? "" : `de ${rows.length}`;
    if (libroTotal) libroTotal.textContent = formatEuro(totalLibro);
    if (libroVisible) libroVisible.textContent = formatEuro(totalVisible);
    if (libroBase) libroBase.textContent = formatEuro(baseVisible);
    if (libroIva) libroIva.textContent = formatEuro(ivaVisible);
    if (!status) return;
    status.classList.toggle("empty-query", bits.length > 0 && visible === 0);
    if (visible === 0) {
      status.hidden = false;
      status.textContent = bits.length
        ? "Ningún asiento coincide con estos filtros."
        : "No hay asientos en este ejercicio.";
      return;
    }
    status.hidden = true;
    status.textContent = "";
  };

  const clearAdvanced = () => {
    for (const box of document.querySelectorAll("input[data-fg]")) box.checked = true;
    if (fMin) fMin.value = "";
    if (fMax) fMax.value = "";
    if (fDesde) fDesde.value = "";
    if (fHasta) fHasta.value = "";
    for (const button of document.querySelectorAll(".filter-trim")) button.classList.remove("is-on");
    const irpfMin = document.getElementById("f-irpf-min");
    const irpfMax = document.getElementById("f-irpf-max");
    if (irpfMin) irpfMin.value = "";
    if (irpfMax) irpfMax.value = "";
    if (input) input.value = "";
    for (const search of document.querySelectorAll("[data-filter-search]")) {
      search.value = "";
      search.dispatchEvent(new Event("input"));
    }
    apply();
  };

  const setFilter = (next, scrollTarget) => {
    if (next === "baja") {
      setGroup("estado", null);
      setGroup("confianza", new Set(["baja"]));
    } else if (!next || next === "all") {
      setGroup("estado", null);
      setGroup("confianza", null);
    } else {
      setGroup("confianza", null);
      setGroup("estado", new Set([next]));
    }
    apply();
    if (scrollTarget) {
      const node = document.querySelector(scrollTarget);
      if (node) node.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const jumpTo = (id) => {
    showPanel("libro");
    clearAdvanced();
    const anchor = document.getElementById(`asiento-${id}`);
    const row = anchor?.closest("tr");
    if (!row) return;
    const matched = rows.filter((item) => item.dataset.match === "1");
    const index = matched.indexOf(row);
    if (index >= 0) {
      libroPage = Math.floor(index / PAGE_SIZE) + 1;
      apply({ keepPage: true });
    }
    row.classList.add("flash");
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => row.classList.remove("flash"), 1600);
  };

  for (const button of kpiButtons) {
    button.addEventListener("click", () => {
      showPanel("libro");
      setFilter(button.dataset.filter, button.dataset.scroll || "#ledger");
    });
  }
  for (const button of document.querySelectorAll("[data-jump]")) {
    button.addEventListener("click", (event) => {
      if (event.target.closest("[data-copy]")) return;
      jumpTo(button.dataset.jump);
    });
  }
  for (const button of document.querySelectorAll("[data-copy]")) {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const cmd = button.dataset.copy || "";
      try {
        await navigator.clipboard.writeText(cmd);
      } catch {
        /* sigue: mostramos el comando en pantalla */
      }
      button.classList.add("copied");
      toast(`Copiado. Pégalo en la terminal:\n${cmd}\nLuego regenera el dashboard.`);
      const slot = button.closest(".action")?.querySelector(".cmd-slot");
      if (slot) {
        slot.hidden = false;
        slot.textContent = `Pégalo en la terminal:\n${cmd}`;
      }
      setTimeout(() => button.classList.remove("copied"), 2200);
    });
  }
  input?.addEventListener("input", apply);
  fMin?.addEventListener("input", apply);
  fMax?.addEventListener("input", apply);
  const clearTrimMarks = () => {
    for (const button of document.querySelectorAll(".filter-trim")) button.classList.remove("is-on");
  };
  fDesde?.addEventListener("input", () => { clearTrimMarks(); apply(); });
  fDesde?.addEventListener("change", () => { clearTrimMarks(); apply(); });
  fHasta?.addEventListener("input", () => { clearTrimMarks(); apply(); });
  fHasta?.addEventListener("change", () => { clearTrimMarks(); apply(); });
  const trimBounds = {
    1: ["01-01", "03-31"],
    2: ["04-01", "06-30"],
    3: ["07-01", "09-30"],
    4: ["10-01", "12-31"],
  };
  for (const button of document.querySelectorAll(".filter-trim")) {
    button.addEventListener("click", () => {
      const bounds = trimBounds[button.dataset.trim];
      if (!bounds) return;
      const anio = String(document.body.dataset.year || "");
      if (button.classList.contains("is-on")) {
        if (fDesde) fDesde.value = "";
        if (fHasta) fHasta.value = "";
        button.classList.remove("is-on");
      } else {
        if (fDesde) fDesde.value = `${anio}-${bounds[0]}`;
        if (fHasta) fHasta.value = `${anio}-${bounds[1]}`;
        clearTrimMarks();
        button.classList.add("is-on");
      }
      apply();
    });
  }
  document.getElementById("f-irpf-min")?.addEventListener("input", apply);
  document.getElementById("f-irpf-max")?.addEventListener("input", apply);
  fClear?.addEventListener("click", clearAdvanced);
  for (const box of document.querySelectorAll("input[data-fg]")) {
    box.addEventListener("change", apply);
  }
  for (const search of document.querySelectorAll("[data-filter-search]")) {
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      const pop = search.closest(".filter-pop");
      if (!pop) return;
      for (const opt of pop.querySelectorAll(".filter-opt")) {
        opt.hidden = Boolean(q) && !opt.textContent.toLowerCase().includes(q);
      }
    });
  }
  for (const button of document.querySelectorAll("[data-filter-all]")) {
    button.addEventListener("click", () => {
      const name = button.dataset.filterAll;
      const pop = button.closest(".filter-pop");
      const boxes = [...(pop?.querySelectorAll(".filter-opt:not([hidden]) input[data-fg]") || [])];
      const allOn = boxes.length > 0 && boxes.every((box) => box.checked);
      for (const box of boxes) box.checked = !allOn;
      apply();
    });
  }

  const placePop = (chip, pop) => {
    const isFilter = pop.classList.contains("filter-pop");
    const width = Math.min(isFilter ? 300 : 320, window.innerWidth - 24);
    pop.style.inset = "auto";
    pop.style.margin = "0";
    pop.style.width = `${width}px`;
    pop.style.maxHeight = "min(420px, 70vh)";
    pop.style.overflowY = "auto";
    const box = chip.getBoundingClientRect();
    const left = Math.min(Math.max(12, box.left), window.innerWidth - width - 12);
    pop.style.left = `${left}px`;
    pop.style.top = `${box.bottom + 8}px`;
    requestAnimationFrame(() => {
      const height = pop.offsetHeight;
      const below = box.bottom + 8;
      const overflow = below + height > window.innerHeight - 12;
      const top = overflow ? Math.max(12, box.top - height - 8) : below;
      pop.style.top = `${top}px`;
    });
  };
  for (const chip of document.querySelectorAll(".funnel[popovertarget], .q-chip[popovertarget], #cols-toggle")) {
    const pop = document.getElementById(chip.getAttribute("popovertarget"));
    if (!pop) continue;
    pop.addEventListener("toggle", (event) => {
      const open = event.newState === "open";
      chip.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) placePop(chip, pop);
    });
  }

  const csvCell = (value) => {
    const text = String(value ?? "");
    if (/[;"\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
    return text;
  };
  const exportVisible = () => {
    const headers = ["Id","Fecha","Emisor","NIF","Factura","Base","IVA","Total","Rubro","Estado"];
    const lines = [headers.join(";")];
    for (const row of rows) {
      if (row.dataset.match === "0") continue;
      const nif = row.dataset.nif || "";
      const base = row.dataset.base || "";
      const iva = row.dataset.iva || "";
      const total = row.dataset.total || "";
      const fecha = row.querySelector('[data-label="Fecha"]')?.textContent?.trim() || "";
      lines.push([
        row.dataset.id || "",
        fecha,
        row.dataset.emisor || "",
        nif,
        row.dataset.numero || "",
        base,
        iva,
        total,
        row.dataset.cuenta || "",
        row.dataset.estadoLabel || "",
      ].map(csvCell).join(";"));
    }
    const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "libro_filtrado.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };
  document.getElementById("export-visible")?.addEventListener("click", exportVisible);
  document.getElementById("export-visible-top")?.addEventListener("click", exportVisible);

  const kanPost = async (asiento, body) => {
    try {
      const res = await fetch(`/api/asientos/${asiento}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || payload.ok === false) throw new Error(payload.error || String(res.status));
      window.location.reload();
    } catch (err) {
      alert("No se pudo guardar: " + err.message);
    }
  };
  const kanAccion = (accion, id) => {
    if (!id) return;
    if (accion === "validar") {
      if (!window.confirm(`¿Consolidar el asiento #${id}? Revisada y buena.`)) return;
      kanPost(id, { validado: true, confirmado: true });
    } else if (accion === "reabrir" || accion === "recuperar") {
      if (!window.confirm(`¿Devolver el asiento #${id} a revisión?`)) return;
      kanPost(id, { validado: false, confirmado: true });
    } else if (accion === "rechazar") {
      const dialogo = document.getElementById("rechazo-dialog");
      if (!dialogo) return;
      dialogo.dataset.rechazarId = id;
      document.getElementById("rechazo-detalle").value = "";
      dialogo.showModal();
    } else if (accion === "quitar-dup") {
      if (!window.confirm(`¿Quitar el duplicado del asiento #${id}?`)) return;
      kanPost(id, { quitar_duplicado: true, confirmado: true });
    }
  };
  for (const boton of document.querySelectorAll(".kan-act")) {
    boton.addEventListener("click", (event) => {
      event.stopPropagation();
      kanAccion(boton.dataset.kan, boton.dataset.id);
    });
  }
  let kanArrastrada = null;
  for (const card of document.querySelectorAll(".kan-card")) {
    card.addEventListener("dragstart", (event) => {
      kanArrastrada = card;
      card.classList.add("dragging");
      event.dataTransfer.setData("text/plain", card.dataset.id);
      event.dataTransfer.effectAllowed = "move";
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      kanArrastrada = null;
    });
  }
  for (const col of document.querySelectorAll(".kan-col")) {
    col.addEventListener("dragover", (event) => {
      event.preventDefault();
      col.classList.add("over");
    });
    col.addEventListener("dragleave", () => col.classList.remove("over"));
    col.addEventListener("drop", (event) => {
      event.preventDefault();
      col.classList.remove("over");
      const id = event.dataTransfer.getData("text/plain");
      const card = kanArrastrada || document.querySelector(`.kan-card[data-id="${id}"]`);
      if (!card || card.closest(".kan-col") === col) return;
      const destino = col.dataset.col;
      const accion = (col.dataset.soltar || "").split("|")[0];
      if (destino === "duplicado") {
        toast("Para marcar duplicado abre la ficha o la pestaña Duplicados y elige el gemelo.");
        return;
      }
      if (destino === "rechazado") {
        kanAccion("rechazar", id);
        return;
      }
      if (!accion) return;
      kanAccion(accion, id);
    });
  }
  const rechazoDialogo = document.getElementById("rechazo-dialog");
  document.getElementById("rechazo-cancel")?.addEventListener("click", () => rechazoDialogo?.close());
  document.getElementById("rechazo-ok")?.addEventListener("click", () => {
    const id = rechazoDialogo?.dataset.rechazarId;
    if (!id) return;
    const marcado = rechazoDialogo.querySelector("input[name='rechazo-motivo']:checked");
    const detalle = document.getElementById("rechazo-detalle")?.value.trim();
    let motivo = marcado?.value || "Otro";
    if (detalle) motivo = `${motivo} — ${detalle}`;
    kanPost(id, { rechazar: true, motivo_rechazo: motivo, confirmado: true });
  });
  const revTablero = document.getElementById("kan-board");
  const revTabla = document.getElementById("revision-tabla");
  const revVista = (nombre) => {
    const tablero = nombre !== "tabla";
    if (revTablero) revTablero.hidden = !tablero;
    if (revTabla) revTabla.hidden = tablero;
    document.getElementById("rev-vista-tablero")?.setAttribute("aria-pressed", tablero ? "true" : "false");
    document.getElementById("rev-vista-tabla")?.setAttribute("aria-pressed", tablero ? "false" : "true");
    try { localStorage.setItem("aeat-hub-vista-revision", nombre); } catch {}
  };
  document.getElementById("rev-vista-tablero")?.addEventListener("click", () => revVista("tablero"));
  document.getElementById("rev-vista-tabla")?.addEventListener("click", () => revVista("tabla"));
  try { revVista(localStorage.getItem("aeat-hub-vista-revision") || "tablero"); } catch { revVista("tablero"); }
  for (const boton of document.querySelectorAll("[data-kan-mas]")) {
    boton.addEventListener("click", () => {
      const destino = boton.dataset.kanMas;
      if (destino === "tabla") revVista("tabla");
      else showPanel(destino);
    });
  }
  const REV_PAGE = 15;
  let revPagina = 1;
  const revPintar = () => {
    const filas = [...document.querySelectorAll("#rev-tabla-body tr")];
    const total = Math.max(1, Math.ceil(filas.length / REV_PAGE));
    revPagina = Math.min(Math.max(1, revPagina), total);
    filas.forEach((fila, idx) => {
      fila.hidden = idx < (revPagina - 1) * REV_PAGE || idx >= revPagina * REV_PAGE;
    });
    const etiqueta = document.getElementById("rev-paginas");
    if (etiqueta) etiqueta.textContent = filas.length ? `Página ${revPagina} de ${total} · ${filas.length} pendientes` : "";
  };
  document.getElementById("rev-prev")?.addEventListener("click", () => { revPagina -= 1; revPintar(); });
  document.getElementById("rev-next")?.addEventListener("click", () => { revPagina += 1; revPintar(); });
  revPintar();
  document.getElementById("insight-kpi-revisar")?.addEventListener("click", () => showPanel("revision"));
  document.getElementById("insight-kpi-revisar")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); showPanel("revision"); }
  });
  for (const enlace of document.querySelectorAll(".kan-ir-revisar")) {
    enlace.addEventListener("click", (event) => {
      event.preventDefault();
      showPanel("revision");
    });
  }
  const dupPost = async (asiento, body) => {
    try {
      const res = await fetch(`/api/asientos/${asiento}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || payload.ok === false) throw new Error(payload.error || String(res.status));
      window.location.reload();
    } catch (err) {
      alert("No se pudo guardar: " + err.message);
    }
  };
  const gestor = document.getElementById("dup-gestor");
  const gestorAbrir = (fila) => {
    if (!gestor || !fila) return;
    const d = fila.dataset;
    const esc = (v) => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    const lado = (rol, clase, pill, id, emisor, nif, numero, fecha, total) => `
      <div class="dup-lado ${clase}">
        <header class="dup-lado-cab"><span class="dup-rol">${esc(rol)}</span>${pill}</header>
        ${id ? `<a class="dup-ref" href="/asiento/${id}">Asiento #${id}</a>` : '<p class="dup-ref muted">—</p>'}
        <p class="dup-emisor">${esc(emisor) || "—"}</p>
        <p class="muted dup-datos">${esc(numero)} · ${esc(fecha)}${nif ? ` · NIF ${esc(nif)}` : ""}</p>
        <strong class="dup-importe">${esc(total)}</strong>
      </div>`;
    const pillHTML = (clase, texto) => `<span class="pill ${clase}">${texto}</span>`;
    document.getElementById("dup-gestor-par").innerHTML = `
      ${d.estado === "duplicado"
        ? lado("Duplicado", "dup-lado-fuera", pillHTML("duplicado", "Fuera de totales"), d.dupId, d.emisor, d.nif, d.numero, d.fecha, d.total)
        : lado("A revisar", "dup-lado-revisar", pillHTML("pendiente", "Sospechoso"), d.dupId, d.emisor, d.nif, d.numero, d.fecha, d.total)}
      <div class="dup-vinclo" aria-hidden="true"><span>⇄</span></div>
      ${lado(d.estado === "duplicado" ? "Asiento bueno" : "Posible gemelo", "dup-lado-bueno",
          pillHTML("confirmado", d.estado === "duplicado" ? "Cuenta en el libro" : "Candidato"),
          d.gemelo, d.gemeloEmisor, d.gemeloNif, d.gemeloNumero, d.gemeloFecha, d.gemeloTotal)}`;
    document.getElementById("dup-gestor-motivo").textContent = d.motivo || "";
    document.getElementById("dup-gestor-eyebrow").textContent =
      d.estado === "duplicado" ? "Duplicado fusionado" : "Sospechoso pendiente";
    const titulo = document.getElementById("dup-gestor-title");
    titulo.textContent = d.emisor && d.gemeloEmisor && d.emisor !== d.gemeloEmisor
      ? `${d.emisor} / ${d.gemeloEmisor}`
      : (d.emisor || "Gestionar duplicado");
    const btnFusionar = document.getElementById("dup-gestor-fusionar");
    const btnQuitar = document.getElementById("dup-gestor-quitar");
    const ficha = document.getElementById("dup-gestor-ficha");
    btnFusionar.hidden = d.estado !== "sospechoso" || !d.gemelo;
    if (!btnFusionar.hidden) btnFusionar.textContent = `Fusionar con #${d.gemelo}`;
    btnQuitar.hidden = d.estado !== "duplicado";
    ficha.href = `/asiento/${d.dupId}`;
    gestor.dataset.dupId = d.dupId;
    gestor.dataset.gemelo = d.gemelo || "";
    gestor.showModal();
  };
  for (const fila of document.querySelectorAll("#panel-duplicados tr[data-dup-id]")) {
    fila.addEventListener("click", () => gestorAbrir(fila));
    fila.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        gestorAbrir(fila);
      }
    });
  }
  document.getElementById("dup-gestor-cerrar")?.addEventListener("click", () => gestor?.close());
  document.getElementById("dup-gestor-fusionar")?.addEventListener("click", () => {
    const id = gestor?.dataset.dupId;
    const gemelo = gestor?.dataset.gemelo;
    if (!id || !gemelo) return;
    if (!window.confirm(`¿Marcar el asiento #${id} como duplicado de #${gemelo}?`)) return;
    dupPost(id, { duplicado_de: gemelo, confirmado: true });
  });
  document.getElementById("dup-gestor-quitar")?.addEventListener("click", () => {
    const id = gestor?.dataset.dupId;
    if (!id) return;
    if (!window.confirm(`¿Quitar el duplicado del asiento #${id}? Vuelve a Por revisar.`)) return;
    dupPost(id, { quitar_duplicado: true, confirmado: true });
  });

  const table = document.querySelector(".ledger-table");
  const COL_KEY = "aeat-hub-libro-cols";
  const colBoxes = [...document.querySelectorAll("#pop-cols input[data-col-toggle]")];
  const readCols = () => {
    try { return JSON.parse(localStorage.getItem(COL_KEY) || "{}"); }
    catch { return {}; }
  };
  const applyCols = () => {
    const saved = readCols();
    for (const box of colBoxes) {
      const on = saved[box.dataset.colToggle] !== false;
      box.checked = on;
      table?.classList.toggle(`col-off-${box.dataset.colToggle}`, !on);
    }
  };
  for (const box of colBoxes) {
    box.addEventListener("change", () => {
      const saved = readCols();
      saved[box.dataset.colToggle] = box.checked;
      try { localStorage.setItem(COL_KEY, JSON.stringify(saved)); } catch {}
      applyCols();
    });
  }
  document.getElementById("cols-all")?.addEventListener("click", () => {
    try { localStorage.removeItem(COL_KEY); } catch {}
    applyCols();
  });
  applyCols();

  const dialog = document.getElementById("edit-dialog");
  const formPane = document.getElementById("edit-form-pane");
  const confirmPane = document.getElementById("edit-confirm");
  const diffBody = document.getElementById("edit-diff-body");
  const logList = document.getElementById("edit-log");
  const ack = document.getElementById("edit-ack");
  const commitBtn = document.getElementById("edit-commit");
  const labels = {
    emisor: "Emisor",
    nif_emisor: "NIF emisor",
    fecha: "Fecha de compra",
    validado: "Estado",
    rubro: "Rubro",
  };
  let editingRow = null;
  let pendingBody = null;

  const closeDialog = () => {
    dialog?.close();
    editingRow = null;
    pendingBody = null;
  };
  const showForm = () => {
    if (formPane) formPane.hidden = false;
    if (confirmPane) confirmPane.hidden = true;
    if (ack) ack.checked = false;
    if (commitBtn) commitBtn.disabled = true;
  };
  const showConfirm = () => {
    if (formPane) formPane.hidden = true;
    if (confirmPane) confirmPane.hidden = false;
    if (ack) ack.checked = false;
    if (commitBtn) commitBtn.disabled = true;
  };
  const renderLog = (items) => {
    if (!logList) return;
    if (!items || !items.length) {
      logList.innerHTML = "<li>Sin cambios registrados todavía.</li>";
      return;
    }
    logList.innerHTML = items.slice(0, 8).map((item) => {
      const campo = labels[item.campo] || item.campo;
      const cuando = item.cuando ? ` · ${item.cuando}` : "";
      return `<li><strong>${campo}</strong>: ${item.antes || "—"} → ${item.despues || "—"}${cuando}</li>`;
    }).join("");
  };
  const snapshotFromRow = (row) => ({
    emisor: row.dataset.emisor || "",
    nif_emisor: row.dataset.nif || "",
    fecha: row.dataset.fecha || "",
    validado: row.dataset.validado === "1",
    rubro: row.dataset.cuenta || "",
    n_articulos: row.dataset.articulos || "",
  });
  const formatLineEuro = (value) => {
    if (value === "" || value == null) return "—";
    const num = Number(value);
    if (!Number.isFinite(num)) return "—";
    return formatEuro(num);
  };
  const escapeText = (value) => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
  const renderLines = (payload, bodyId = "edit-lines-body", noteId = "edit-lines-note") => {
    const body = document.getElementById(bodyId);
    const note = document.getElementById(noteId);
    if (!body) return;
    const table = body.closest("table");
    const toNum = (value) => {
      if (value === "" || value == null) return null;
      const num = Number(value);
      return Number.isFinite(num) ? num : null;
    };
    const lines = payload?.lineas || [];
    if (!lines.length) {
      body.innerHTML = '<tr><td colspan="6">Sin líneas extraídas. Abre el PDF y contrasta el total a mano.</td></tr>';
      table?.querySelector("tfoot")?.remove();
      const head = table?.querySelector("thead th:nth-child(5)");
      if (head) head.textContent = "IVA";
      if (note) {
        note.textContent = "";
        note.classList.remove("ok");
      }
      return;
    }
    const tipos = [...new Set(lines.map((item) => item.iva_tipo).filter(Boolean))];
    const head = table?.querySelector("thead th:nth-child(5)");
    if (head) {
      if (tipos.length === 1 && Number.isFinite(Number(tipos[0]))) {
        const n = Number(tipos[0]);
        head.textContent = `IVA (${Math.abs(n - Math.round(n)) < 0.001 ? Math.round(n) : n} %)`;
      } else {
        head.textContent = "IVA";
      }
    }
    body.innerHTML = lines.map((item, idx) => (
      `<tr data-line="1"><td class="num">${escapeText(item.posicion || idx + 1)}</td>`
      + `<td><input data-f="codigo" value="${escapeText(item.codigo || "")}" aria-label="Id de línea"></td>`
      + `<td><input data-f="descripcion" value="${escapeText(item.descripcion || "")}" aria-label="Concepto"></td>`
      + `<td><input data-f="base" type="number" min="0" step="0.01" value="${escapeText(item.base || "")}" aria-label="Subtotal"></td>`
      + `<td><input data-f="iva_cuota" type="number" min="0" step="0.01" value="${escapeText(item.iva_cuota || "")}" aria-label="IVA"></td>`
      + `<td><input data-f="importe" type="number" min="0" step="0.01" value="${escapeText(item.importe || "")}" aria-label="Total de línea"></td>`
      + `<td><button type="button" class="ghost line-del">Quitar</button></td></tr>`
    )).join("");
    const sumOf = (key) => lines.reduce((acc, item) => acc + (toNum(item[key]) || 0), 0);
    let foot = table?.querySelector("tfoot");
    if (table && lines.some((item) => item.importe || item.base)) {
      if (!foot) {
        foot = document.createElement("tfoot");
        table.appendChild(foot);
      }
      foot.innerHTML = `<tr><td colspan="3">Suma</td><td>${formatLineEuro(sumOf("base"))}</td>`
        + `<td>${formatLineEuro(sumOf("iva_cuota"))}</td><td>${formatLineEuro(sumOf("importe"))}</td></tr>`;
    } else {
      foot?.remove();
    }
    if (!note) return;
    const hasAmount = lines.some((item) => item.importe || item.base);
    if (!hasAmount) {
      note.classList.remove("ok");
      note.textContent = "El OCR vio estos conceptos, pero no el importe de cada uno. Abre el PDF y contrasta el total.";
      return;
    }
    const sum = toNum(payload.lineas_suma);
    const base = toNum(payload.base);
    const total = toNum(payload.total);
    const sumLabel = formatLineEuro(sum);
    if (payload.lineas_ok) {
      note.classList.add("ok");
      const sumBase = sumOf("base");
      const sumIva = sumOf("iva_cuota");
      if (sumBase && sumIva) {
        note.textContent = `Suma de subtotales ${formatLineEuro(sumBase)} + IVA ${formatLineEuro(sumIva)} = ${sumLabel}.`;
      } else if (base != null && sum != null && Math.abs(sum - base) <= 0.02) {
        note.textContent = `Suma de líneas ${sumLabel} = base.`;
      } else {
        note.textContent = `Suma de líneas ${sumLabel} = total.`;
      }
    } else {
      note.classList.remove("ok");
      note.textContent = `Suma de líneas ${sumLabel}. Contrasta con base ${formatLineEuro(base)} / total ${formatLineEuro(total)}. El OCR no siempre lee todos los rubros.`;
    }
  };
  const fillForm = (snap, row) => {
    const emisor = document.getElementById("edit-emisor");
    const nif = document.getElementById("edit-nif");
    const fecha = document.getElementById("edit-fecha");
    const validar = document.getElementById("edit-validar");
    const rubro = document.getElementById("edit-rubro");
    const meta = document.getElementById("edit-meta");
    const articulos = document.getElementById("edit-articulos");
    if (emisor) emisor.value = snap.emisor || "";
    if (nif) nif.value = snap.nif_emisor;
    if (fecha) fecha.value = snap.fecha || "";
    if (validar) validar.checked = Boolean(snap.validado);
    if (rubro) rubro.value = snap.rubro || "";
    if (articulos) {
      const n = snap.n_articulos;
      articulos.textContent = n && n !== "0"
        ? `Artículos: ${n}. Suma de unidades de la ficha.`
        : "Artículos: ninguno con nombre en la ficha.";
    }
    if (meta) {
      meta.textContent = `#${row.dataset.id} · ${row.dataset.emisor || "—"} · ${row.dataset.fechaLabel || ""}`;
    }
  };
  let linesBefore = [];
  const collectLines = () => [...document.querySelectorAll("#edit-lines-body tr[data-line]")].map((tr, idx) => ({
    posicion: idx + 1,
    codigo: tr.querySelector("[data-f=codigo]")?.value || "",
    descripcion: tr.querySelector("[data-f=descripcion]")?.value || "",
    base: tr.querySelector("[data-f=base]")?.value || "",
    iva_cuota: tr.querySelector("[data-f=iva_cuota]")?.value || "",
    importe: tr.querySelector("[data-f=importe]")?.value || "",
  }));
  const linesKey = (items) => JSON.stringify((items || []).map((item) => ({
    descripcion: item.descripcion || "",
    codigo: item.codigo || "",
    base: item.base || "",
    iva_cuota: item.iva_cuota || "",
    importe: item.importe || "",
  })));
  const proposedFromForm = () => ({
    emisor: (document.getElementById("edit-emisor")?.value || "").trim(),
    nif_emisor: (document.getElementById("edit-nif")?.value || "").trim().toUpperCase(),
    fecha: document.getElementById("edit-fecha")?.value || "",
    validado: Boolean(document.getElementById("edit-validar")?.checked),
    rubro: document.getElementById("edit-rubro")?.value || "",
  });
  const diffsOf = (before, after) => {
    const rows = [];
    const labels = { emisor: "Emisor", nif_emisor: "NIF", fecha: "Fecha", validado: "Estado", rubro: "Rubro" };
    for (const key of ["emisor", "nif_emisor", "fecha", "validado", "rubro"]) {
      const a = key === "validado" ? (before[key] ? "OK" : "Por revisar") : String(before[key] ?? "");
      const b = key === "validado" ? (after[key] ? "OK" : "Por revisar") : String(after[key] ?? "");
      if (a !== b) rows.push({ campo: labels[key] || key, antes: a || "—", despues: b || "—" });
    }
    return rows;
  };
  const openEdit = async (row, { onlyValidate = false, onlyReopen = false } = {}) => {
    editingRow = row;
    linesBefore = [];
    showForm();
    fillForm(snapshotFromRow(row), row);
    renderLog([]);
    renderLines({ lineas: [] });
    dialog?.showModal();
    try {
      const res = await fetch(`/api/asientos/${row.dataset.id}`);
      if (res.ok) {
        const payload = await res.json();
        fillForm({
          emisor: payload.emisor || "",
          nif_emisor: payload.nif_emisor || "",
          fecha: payload.fecha || "",
          validado: Boolean(payload.validado),
          rubro: payload.rubro || "",
          n_articulos: payload.n_articulos || "",
        }, row);
        linesBefore = payload.lineas || [];
        renderLog(payload.cambios || []);
        renderLines(payload);
      }
    } catch { /* historial y líneas opcionales */ }
    if (onlyValidate) {
      const validar = document.getElementById("edit-validar");
      if (validar) validar.checked = true;
      document.getElementById("edit-review")?.click();
    } else if (onlyReopen) {
      const validar = document.getElementById("edit-validar");
      if (validar) validar.checked = false;
      document.getElementById("edit-review")?.click();
    }
  };
  const setRowActions = (row, validado) => {
    const acciones = row.querySelector(".row-actions");
    if (!acciones) return;
    const pencil = acciones.querySelector(".row-edit");
    acciones.innerHTML = "";
    if (pencil) acciones.appendChild(pencil);
    if (row.dataset.estado === "duplicado") {
      const badge = document.createElement("span");
      badge.className = "estado-btn estado-dup";
      badge.title = "Duplicado: no entra en los totales";
      badge.textContent = "Duplicado";
      acciones.appendChild(badge);
      return;
    }
    const btn = document.createElement("button");
    btn.type = "button";
    if (validado) {
      btn.className = "estado-btn estado-ok";
      btn.dataset.reopen = row.dataset.id;
      btn.textContent = "Validado";
      btn.title = "Validado. Pulsa para devolver a revisión";
      btn.setAttribute("aria-label", `Validado. Devolver asiento ${row.dataset.id} a revisión`);
      btn.addEventListener("click", () => openEdit(row, { onlyReopen: true }));
    } else {
      btn.className = "estado-btn estado-pend";
      btn.dataset.validar = row.dataset.id;
      btn.textContent = "Por validar";
      btn.title = "Pendiente de validar. Pulsa para confirmar";
      btn.setAttribute("aria-label", `Por validar. Confirmar asiento ${row.dataset.id}`);
      btn.addEventListener("click", () => openEdit(row, { onlyValidate: true }));
    }
    acciones.appendChild(btn);
  };
  const applyPayload = (row, payload) => {
    row.dataset.validado = payload.validado ? "1" : "0";
    row.dataset.baja = payload.validado ? "0" : row.dataset.baja;
    row.dataset.estado = payload.estado || row.dataset.estado;
    row.dataset.estadoLabel = payload.estado_label || row.dataset.estadoLabel;
    row.dataset.nif = payload.nif_emisor || "";
    if (payload.emisor != null) {
      row.dataset.emisor = payload.emisor;
      const emisorCell = row.querySelector('[data-label="Emisor"] .cell-text')
        || row.querySelector('[data-label="Emisor"] a')
        || row.querySelector('[data-label="Emisor"]');
      if (emisorCell) emisorCell.textContent = payload.emisor || "—";
    }
    if (payload.fecha_label) {
      row.dataset.fecha = payload.fecha || "";
      row.dataset.fechaLabel = payload.fecha_label;
      const fechaCell = row.querySelector('[data-label="Fecha"] a')
        || row.querySelector('[data-label="Fecha"]');
      if (fechaCell) fechaCell.textContent = payload.fecha_label;
    }
    if (payload.n_articulos != null) {
      const art = row.querySelector('[data-label="Artículos"] a')
        || row.querySelector('[data-label="Artículos"]');
      if (art) art.textContent = payload.n_articulos ? String(payload.n_articulos) : "—";
    }
    row.dataset.base = payload.base || "";
    row.dataset.iva = payload.iva_cuota || "";
    row.dataset.total = payload.total || row.dataset.total;
    const setText = (label, text) => {
      const cell = row.querySelector(`[data-label="${label}"]`);
      if (cell) cell.textContent = text;
    };
    setText("NIF", payload.nif_emisor || "—");
    setText("Base", payload.base ? formatEuro(Number(payload.base)) : "—");
    setText("IVA", payload.iva_cuota ? formatEuro(Number(payload.iva_cuota)) : "—");
    if (payload.rubro != null) {
      row.dataset.cuenta = payload.rubro;
      setText("Rubro", payload.rubro || "Sin clasificar");
    }
    const amt = row.querySelector(".total-amt");
    if (amt) amt.textContent = payload.total ? formatEuro(Number(payload.total)) : "—";
    setRowActions(row, Boolean(payload.validado));
    const chip = row.querySelector(".q-chip span");
    if (chip) chip.textContent = payload.validado ? "Validado" : "Revisar";
    row.querySelector(".q-chip")?.classList.toggle("q-warn", !payload.validado);
    row.querySelector(".q-chip")?.classList.toggle("q-ok", Boolean(payload.validado));
  };

  document.getElementById("edit-line-add")?.addEventListener("click", () => {
    const body = document.getElementById("edit-lines-body");
    if (!body) return;
    body.querySelector("tr:not([data-line])")?.remove();
    const tr = document.createElement("tr");
    tr.dataset.line = "1";
    const n = body.querySelectorAll("tr[data-line]").length + 1;
    tr.innerHTML = `<td class="num">${n}</td>`
      + `<td><input data-f="codigo" aria-label="Id de línea"></td>`
      + `<td><input data-f="descripcion" aria-label="Concepto"></td>`
      + `<td><input data-f="base" type="number" min="0" step="0.01" aria-label="Subtotal"></td>`
      + `<td><input data-f="iva_cuota" type="number" min="0" step="0.01" aria-label="IVA"></td>`
      + `<td><input data-f="importe" type="number" min="0" step="0.01" aria-label="Total de línea"></td>`
      + `<td><button type="button" class="ghost line-del">Quitar</button></td>`;
    body.appendChild(tr);
  });
  document.getElementById("edit-lines-body")?.addEventListener("click", (event) => {
    const button = event.target.closest(".line-del");
    if (!button) return;
    button.closest("tr")?.remove();
  });
  document.getElementById("edit-cancel")?.addEventListener("click", closeDialog);
  document.getElementById("edit-back")?.addEventListener("click", showForm);
  ack?.addEventListener("change", () => {
    if (commitBtn) commitBtn.disabled = !ack.checked;
  });
  document.getElementById("edit-review")?.addEventListener("click", () => {
    if (!editingRow) return;
    const before = snapshotFromRow(editingRow);
    const after = proposedFromForm();
    const diffs = diffsOf(before, after);
    if (!diffs.length) {
      toast("No hay cambios que guardar.");
      return;
    }
    pendingBody = { ...after, confirmado: true };
    if (diffBody) {
      diffBody.innerHTML = diffs.map((item) => (
        `<tr><td>${labels[item.campo] || item.campo}</td><td>${item.antes}</td><td>${item.despues}</td></tr>`
      )).join("");
    }
    showConfirm();
  });
  document.getElementById("edit-commit")?.addEventListener("click", async () => {
    if (!editingRow || !pendingBody || !ack?.checked) return;
    try {
      const res = await fetch(`/api/asientos/${editingRow.dataset.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(pendingBody),
      });
      if (!res.ok) throw new Error(String(res.status));
      const payload = await res.json();
      applyPayload(editingRow, payload);
      apply({ keepPage: true });
      closeDialog();
      toast("Cambio guardado. Queda en el log del asiento.");
    } catch {
      toast("No se pudo guardar. Abre el dashboard con `aeat-hub dashboard` (servidor local).");
    }
  });
  for (const row of rows) {
    row.querySelector("[data-edit]")?.addEventListener("click", () => openEdit(row));
    row.querySelector("[data-validar]")?.addEventListener("click", () => openEdit(row, { onlyValidate: true }));
    row.querySelector("[data-reopen]")?.addEventListener("click", () => openEdit(row, { onlyReopen: true }));
    row.addEventListener("click", (event) => {
      if (event.target.closest("a, button, input, label, [popover], .row-actions")) return;
      const href = row.dataset.href;
      if (href) window.location.href = href;
    });
  }

  libroPrev?.addEventListener("click", () => {
    libroPage -= 1;
    apply({ keepPage: true });
  });
  libroNext?.addEventListener("click", () => {
    libroPage += 1;
    apply({ keepPage: true });
  });
  let sortKey = "id";
  let sortDir = 1;
  const libroTable = document.querySelector("#ledger .ledger-table");
  const sortValue = (row, key) => {
    if (key === "id") return Number(row.dataset.id || 0);
    if (key === "total" || key === "base" || key === "iva") return Number(row.dataset[key] || 0);
    if (key === "articulos") {
      const text = (row.querySelector('[data-col="articulos"]')?.textContent || "").replace(",", ".").trim();
      const n = Number(text);
      return Number.isFinite(n) ? n : -1;
    }
    if (key === "confianza") return row.querySelector(".q-chip span")?.textContent?.trim() || "";
    if (key === "doc") return row.querySelector(".doc-link") ? "1" : "0";
    if (key === "estado") return row.dataset.estadoLabel || "";
    if (key === "factura") return row.dataset.numero || "";
    if (key === "fecha") return row.dataset.fecha || "";
    if (key === "emisor") return row.dataset.emisor || "";
    if (key === "nif") return row.dataset.nif || "";
    return "";
  };
  const compareSort = (a, b) => {
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b), "es", { numeric: true, sensitivity: "base" });
  };
  const sortLibro = () => {
    rows.sort((a, b) => sortDir * compareSort(sortValue(a, sortKey), sortValue(b, sortKey)));
    const body = libroTable?.tBodies[0];
    if (body) for (const row of rows) body.appendChild(row);
    libroTable?.querySelectorAll("thead th[data-sort]").forEach((th) => {
      const on = th.dataset.sort === sortKey;
      th.classList.toggle("is-sorted", on);
      th.classList.toggle("is-desc", on && sortDir < 0);
    });
  };
  libroTable?.querySelectorAll("thead th[data-sort]").forEach((th) => {
    th.addEventListener("click", (event) => {
      if (event.target.closest(".funnel, .filter-pop")) return;
      const key = th.dataset.sort;
      if (!key) return;
      if (sortKey === key) sortDir *= -1;
      else { sortKey = key; sortDir = 1; }
      sortLibro();
      apply();
    });
  });
  sortLibro();
  apply();

  const mastDialog = document.getElementById("mast-dialog");
  const mastEdit = document.getElementById("mast-edit");
  const mastNombre = document.getElementById("mast-input-nombre");
  const mastTitular = document.getElementById("mast-input-titular");
  const mastInmueble = document.getElementById("mast-input-inmueble");
  const mastInmuebleField = document.getElementById("mast-inmueble-field");
  const openMast = () => {
    if (mastNombre) mastNombre.value = document.getElementById("mast-nombre")?.textContent?.trim() || "";
    if (mastTitular) mastTitular.value = document.getElementById("mast-titular")?.textContent?.trim() || "";
    if (mastInmueble) mastInmueble.value = document.getElementById("mast-inmueble")?.textContent?.trim() || "";
    if (mastInmuebleField) {
      mastInmuebleField.hidden = mastEdit?.dataset.hasInmueble !== "1";
    }
    mastDialog?.showModal();
  };
  mastEdit?.addEventListener("click", openMast);
  document.getElementById("mast-cancel")?.addEventListener("click", () => mastDialog?.close());
  document.getElementById("mast-save")?.addEventListener("click", async () => {
    const body = {
      nombre: mastNombre?.value || "",
      titular: mastTitular?.value || "",
      confirmado: true,
    };
    if (mastEdit?.dataset.hasInmueble === "1") body.inmueble = mastInmueble?.value || "";
    try {
      const res = await fetch("/api/expediente", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(String(res.status));
      const payload = await res.json();
      const nombreEl = document.getElementById("mast-nombre");
      const titularEl = document.getElementById("mast-titular");
      const wrap = document.getElementById("mast-inmueble-wrap");
      const inmuebleEl = document.getElementById("mast-inmueble");
      if (nombreEl && payload.nombre) nombreEl.textContent = payload.nombre;
      if (titularEl && payload.titular) titularEl.textContent = payload.titular;
      if (inmuebleEl) inmuebleEl.textContent = payload.inmueble || "";
      if (wrap) wrap.hidden = !payload.inmueble;
      mastDialog?.close();
      toast("Títulos guardados. Quedan en SQLite para este expediente.");
    } catch {
      toast("No se pudo guardar. Abre el dashboard con `aeat-hub dashboard` (servidor local).");
    }
  });

  try {
  const insightBox = document.getElementById("insight-rows");
  const insightMonth = document.getElementById("insight-month");
  const insightEmisor = document.getElementById("insight-emisor");
  const insightFrase = document.getElementById("insight-frase");
  if (insightBox && insightMonth && insightEmisor && insightFrase) {
    const source = JSON.parse(insightBox.content?.textContent || insightBox.innerHTML || "[]");
    const month0 = insightMonth.innerHTML;
    const emisor0 = insightEmisor.innerHTML;
    const frase0 = insightFrase.textContent;
    const kpiHint = document.getElementById("insight-kpi-hint");
    const kpiIds = { gasto: "insight-kpi-gastos", ingreso: "insight-kpi-ingresos", mejora: "insight-kpi-mejoras" };
    const kpiEls = {};
    const kpi0 = {};
    Object.entries(kpiIds).forEach(([tipo, id]) => {
      const el = document.getElementById(id);
      if (el) { kpiEls[tipo] = el; kpi0[tipo] = el.textContent; }
    });
    const netoEl = document.getElementById("insight-kpi-neto");
    const neto0 = netoEl ? netoEl.textContent : "";
    const paintKpis = (rows) => {
      const sums = { gasto: 0, ingreso: 0, mejora: 0 };
      for (const row of rows) if (row.tipo in sums) sums[row.tipo] += row.total || 0;
      for (const [tipo, el] of Object.entries(kpiEls)) el.textContent = formatEuro(sums[tipo]);
      if (netoEl) netoEl.textContent = formatEuro(sums.ingreso - sums.gasto);
    };
    const restoreKpis = () => {
      for (const [tipo, el] of Object.entries(kpiEls)) el.textContent = kpi0[tipo];
      if (netoEl) netoEl.textContent = neto0;
    };
    const ivaBody = document.querySelector("#iva-tabla tbody");
    const ivaOrder = ["21", "10", "4", "0", "otros", "sin"];
    const ivaLabels = { "21": "21 %", "10": "10 %", "4": "4 %", "0": "0 %", otros: "Otros tipos", sin: "Sin tipo" };
    const ivaKey = (tipo) => {
      if (tipo === null || tipo === undefined) return "sin";
      const key = String(Math.round(tipo));
      return ["21", "10", "4", "0"].includes(key) ? key : "otros";
    };
    const paintIva = (rows) => {
      if (!ivaBody) return;
      const buckets = new Map();
      for (const row of rows) {
        if (row.tipo !== "gasto" && row.tipo !== "mejora") continue;
        const key = ivaKey(row.iva_tipo);
        const cur = buckets.get(key) || { label: ivaLabels[key], base: 0, cuota: 0, total: 0 };
        cur.base += row.base || 0;
        cur.cuota += row.iva_cuota || 0;
        cur.total += row.total || 0;
        buckets.set(key, cur);
      }
      const keys = ivaOrder.filter((key) => buckets.has(key));
      if (!keys.length) {
        ivaBody.innerHTML = '<tr class="iva-vacia"><td colspan="4">Sin IVA registrado en este rango.</td></tr>';
        return;
      }
      ivaBody.innerHTML = keys.map((key) => {
        const item = buckets.get(key);
        return `<tr><td>${esc(item.label)}</td><td class="num">${esc(formatEuro(item.base))}</td><td class="num">${esc(formatEuro(item.cuota))}</td><td class="num">${esc(formatEuro(item.total))}</td></tr>`;
      }).join("");
    };
    const trimsEl = document.getElementById("insight-trims");
    const anio = String(document.body.dataset.year || "");
    const trims = [["T1", "01-01", "03-31"], ["T2", "04-01", "06-30"], ["T3", "07-01", "09-30"], ["T4", "10-01", "12-31"]];
    const paintTrims = (activeName) => {
      if (!trimsEl) return;
      trimsEl.replaceChildren();
      for (const [name, desde, hasta] of trims) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "insight-preset" + (name === activeName ? " is-on" : "");
        button.textContent = name;
        button.setAttribute("aria-label", `Trimestre ${name.slice(1)} (${desde} → ${hasta})`);
        button.addEventListener("click", () => {
          if (desdeEl) desdeEl.value = `${anio}-${desde}`;
          if (hastaEl) hastaEl.value = `${anio}-${hasta}`;
          applyRange(name);
        });
        trimsEl.appendChild(button);
      }
    };
    const corto = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
    const largo = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
    const desdeEl = document.getElementById("insight-desde");
    const hastaEl = document.getElementById("insight-hasta");
    const nameEl = document.getElementById("insight-range-name");
    const presetsEl = document.getElementById("insight-presets");
    const storeKey = `aeat-hub-rangos:${document.body.dataset.actividad}:${document.body.dataset.year}`;
    const esc = (value) => String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
    const compact = (value) => (
      value >= 1000
        ? `${(value / 1000).toFixed(1).replace(".", ",")}k`
        : formatEuro(value).replace(/\s*€/, "")
    );
    const loadPresets = () => {
      try {
        const parsed = JSON.parse(localStorage.getItem(storeKey) || "[]");
        return Array.isArray(parsed) ? parsed : [];
      } catch {
        return [];
      }
    };
    const savePresets = (items) => localStorage.setItem(storeKey, JSON.stringify(items));
    const inRange = (row, desde, hasta) => {
      if (!desde && !hasta) return true;
      if (!row.fecha) return false;
      if (desde && row.fecha < desde) return false;
      if (hasta && row.fecha > hasta) return false;
      return true;
    };
    const svgMonths = (rows) => {
      const gastos = Array.from({ length: 12 }, () => 0);
      const ingresos = Array.from({ length: 12 }, () => 0);
      for (const row of rows) {
        const month = Number((row.fecha || "").slice(5, 7)) - 1;
        if (month < 0 || month > 11) continue;
        if (row.tipo === "gasto") gastos[month] += row.total;
        if (row.tipo === "ingreso") ingresos[month] += row.total;
      }
      const showIncome = ingresos.some((value) => value > 0);
      const peak = Math.max(1, ...gastos, ...(showIncome ? ingresos : [0]));
      const width = 640;
      const height = 280;
      const padL = 56;
      const padT = 36;
      const innerW = width - padL - 16;
      const innerH = height - padT - 40;
      const slot = innerW / 12;
      const barW = Math.min(slot * (showIncome ? 0.34 : 0.55), 28);
      let body = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Gasto de cada mes del año">`;
      [0, peak / 2, peak].forEach((value, index) => {
        const y = padT + innerH - (value / peak) * innerH;
        body += `<line class="grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${width - 16}" y2="${y.toFixed(1)}"/>`;
        body += `<text class="tick" x="${padL - 8}" y="${(y + 4).toFixed(1)}">${compact(value)}</text>`;
      });
      corto.forEach((label, index) => {
        const pair = barW * (showIncome ? 2 : 1) + (showIncome ? 4 : 0);
        const x0 = padL + slot * index + (slot - pair) / 2;
        const draw = (amount, x, klass, kind) => {
          if (amount <= 0) return;
          const h = (amount / peak) * innerH;
          const y = padT + innerH - h;
          body += `<rect class="${klass}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="3"><title>${esc(largo[index])} ${kind} ${esc(formatEuro(amount))}</title></rect>`;
          body += `<text class="bar-label" x="${(x + barW / 2).toFixed(1)}" y="${Math.max(y - 6, 12).toFixed(1)}">${compact(amount)}</text>`;
        };
        draw(gastos[index], x0, "bar-g", "gastos");
        if (showIncome) draw(ingresos[index], x0 + barW + 4, "bar-i", "ingresos");
        body += `<text class="axis" x="${(padL + slot * index + slot / 2).toFixed(1)}" y="${height - 14}">${label}</text>`;
      });
      body += "</svg>";
      return body;
    };
    const svgEmisores = (rows) => {
      const map = new Map();
      for (const row of rows) {
        if (row.tipo !== "gasto" || row.total <= 0) continue;
        const raw = (row.emisor || "").trim();
        const key = raw.toLocaleLowerCase("es") || "sin emisor";
        const cur = map.get(key) || { label: raw || "Sin emisor", total: 0 };
        cur.total += row.total;
        map.set(key, cur);
      }
      let ranked = [...map.values()].sort((a, b) => b.total - a.total || a.label.localeCompare(b.label, "es"));
      if (!ranked.length) return '<p class="empty">Aún no hay gasto que repartir por emisor.</p>';
      if (ranked.length > 6) {
        const resto = ranked.slice(6).reduce((sum, item) => sum + item.total, 0);
        ranked = ranked.slice(0, 6).concat([{ label: "Resto", total: resto }]);
      }
      const peak = Math.max(...ranked.map((item) => item.total));
      const grand = ranked.reduce((sum, item) => sum + item.total, 0) || 1;
      const width = 640;
      const rowH = 58;
      const height = 16 + rowH * ranked.length;
      let body = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Gasto por emisor">`;
      ranked.forEach((item, index) => {
        const y = 8 + index * rowH;
        const bar = (item.total / peak) * (width - 34);
        const pct = Math.round(100 * item.total / grand);
        const full = item.label;
        const shown = full.length > 32 ? `${full.slice(0, 31)}…` : full;
        body += `<text class="axis left" x="18" y="${y + 14}"><title>${esc(full)}</title>${esc(shown)}</text>`;
        body += `<rect class="bar-g" x="18" y="${y + 22}" width="${Math.max(bar, 8).toFixed(1)}" height="16" rx="4"><title>${esc(full)} ${esc(formatEuro(item.total))} (${pct} %)</title></rect>`;
        body += `<text class="tick right" x="18" y="${y + 52}">${esc(formatEuro(item.total))} · ${pct} %</text>`;
      });
      body += "</svg>";
      return body;
    };
    const fraseDe = (rows) => {
      const gastos = rows.filter((row) => row.tipo === "gasto" && row.total > 0);
      const total = gastos.reduce((sum, row) => sum + row.total, 0);
      if (total <= 0) return "Sin gasto en este rango.";
      const map = new Map();
      for (const row of gastos) {
        const raw = (row.emisor || "").trim();
        const key = raw.toLocaleLowerCase("es") || "sin emisor";
        const cur = map.get(key) || { label: raw || "Sin emisor", total: 0 };
        cur.total += row.total;
        map.set(key, cur);
      }
      const ranked = [...map.values()].sort((a, b) => b.total - a.total || a.label.localeCompare(b.label, "es"));
      const top = ranked[0];
      const share = Math.round(100 * top.total / total);
      const shown = top.label.length > 32 ? `${top.label.slice(0, 31)}…` : top.label;
      if (share >= 50) return `${shown} concentra el ${share} % del gasto (${formatEuro(top.total)}).`;
      const byMonth = Array.from({ length: 12 }, () => 0);
      for (const row of gastos) {
        const month = Number((row.fecha || "").slice(5, 7)) - 1;
        if (month >= 0 && month < 12) byMonth[month] += row.total;
      }
      let peak = 0;
      byMonth.forEach((value, index) => { if (value > byMonth[peak]) peak = index; });
      const monthShare = Math.round(100 * byMonth[peak] / total);
      if (byMonth[peak] > 0 && monthShare >= 40) {
        return `El gasto se concentra en ${largo[peak]}: ${formatEuro(byMonth[peak])}, el ${monthShare} % del año.`;
      }
      let last = 0;
      byMonth.forEach((value, index) => { if (value > 0) last = index; });
      return `Hasta ${largo[last]} van ${formatEuro(total)} en gasto.`;
    };
    const paintPresets = (activeName) => {
      if (!presetsEl) return;
      presetsEl.replaceChildren();
      for (const preset of loadPresets()) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "insight-preset" + (preset.name === activeName ? " is-on" : "");
        button.textContent = preset.name;
        button.addEventListener("click", () => {
          if (desdeEl) desdeEl.value = preset.desde || "";
          if (hastaEl) hastaEl.value = preset.hasta || "";
          applyRange(preset.name);
        });
        const drop = document.createElement("button");
        drop.type = "button";
        drop.className = "insight-preset";
        drop.textContent = "×";
        drop.setAttribute("aria-label", `Quitar rango ${preset.name}`);
        drop.addEventListener("click", (event) => {
          event.stopPropagation();
          savePresets(loadPresets().filter((item) => item.name !== preset.name));
          paintPresets("");
        });
        presetsEl.appendChild(button);
        presetsEl.appendChild(drop);
      }
    };
    const applyRange = (activeName = "") => {
      const desde = desdeEl?.value || "";
      const hasta = hastaEl?.value || "";
      if (desde && hasta && desde > hasta) {
        toast("La fecha desde es posterior a hasta.");
        return;
      }
      if (kpiHint) kpiHint.hidden = !desde && !hasta;
      if (!desde && !hasta) {
        insightMonth.innerHTML = month0;
        insightEmisor.innerHTML = emisor0;
        insightFrase.textContent = frase0;
        insightFrase.hidden = !frase0;
        restoreKpis();
        paintIva(source);
        paintTrims("");
        paintPresets("");
        return;
      }
      const rows = source.filter((row) => inRange(row, desde, hasta));
      insightMonth.innerHTML = svgMonths(rows);
      insightEmisor.innerHTML = svgEmisores(rows);
      insightFrase.hidden = false;
      insightFrase.textContent = fraseDe(rows);
      paintKpis(rows);
      paintIva(rows);
      paintTrims(activeName);
      paintPresets(activeName);
    };
    document.getElementById("insight-range-all")?.addEventListener("click", () => {
      if (desdeEl) desdeEl.value = "";
      if (hastaEl) hastaEl.value = "";
      applyRange();
    });
    desdeEl?.addEventListener("change", () => applyRange());
    hastaEl?.addEventListener("change", () => applyRange());
    desdeEl?.addEventListener("input", () => applyRange());
    hastaEl?.addEventListener("input", () => applyRange());
    document.getElementById("insight-range-save")?.addEventListener("click", () => {
      const name = (nameEl?.value || "").trim();
      const desde = desdeEl?.value || "";
      const hasta = hastaEl?.value || "";
      if (!name) {
        toast("Pon un nombre al rango.");
        return;
      }
      if (!desde && !hasta) {
        toast("Indica desde, hasta, o las dos.");
        return;
      }
      const next = loadPresets().filter((item) => item.name !== name);
      next.push({ name, desde, hasta });
      savePresets(next);
      if (nameEl) nameEl.value = "";
      applyRange(name);
    });
    paintTrims("");
    paintPresets("");
  }
  } catch (err) {
    const frase = document.getElementById("insight-frase");
    if (frase) frase.dataset.error = err.message;
  }
})();
"""
