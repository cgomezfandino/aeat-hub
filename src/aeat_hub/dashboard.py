"""Dashboard HTML local: vista del libro. El maestro sigue siendo SQLite."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from aeat_hub.fiscal.accounts import REGIMEN_CI, TIPO_GASTO, TIPO_INGRESO, TIPO_MEJORA
from aeat_hub.fiscal.irpf import INDEX_CI, RUBRO_CHIPS, casilla_clave, summarize_irpf
from aeat_hub.fiscal.money import format_euro, q2
from aeat_hub.models import Actividad, Asiento, Cuenta, Inmueble, Titular
from aeat_hub.paths import DataLayout

MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
ZERO = Decimal("0.00")

REGIMEN_LABEL = {
    "capital_inmobiliario": "Rendimientos de capital inmobiliario",
    "actividad_economica": "Actividad económica",
}

ESTADO_LABEL = {
    "pendiente": "Por revisar",
    "confirmado": "Confirmado",
    "duplicado": "Duplicado",
}


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
            .order_by(Asiento.fecha, Asiento.id)
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
    vivos = [row for row in rows if row.estado != "duplicado"]
    gastos = _sum_tipo(vivos, TIPO_GASTO)
    ingresos = _sum_tipo(vivos, TIPO_INGRESO)
    mejoras = _sum_tipo(vivos, TIPO_MEJORA)
    pendientes = [row for row in vivos if row.estado == "pendiente"]
    asientos = [_asiento_view(row, nombres, extra_casillas, inmuebles) for row in rows]
    por_mes = _by_month(vivos)
    irpf = (
        summarize_irpf(vivos, extra_casillas) if actividad.regimen == REGIMEN_CI else None
    )
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
        "por_mes_acc": _cumulative(por_mes),
        "por_naturaleza": _by_nature(vivos, extra_casillas),
        "asientos": asientos,
        "pendientes": [item for item in asientos if item["estado"] == "pendiente"],
        "n_baja": sum(1 for item in asientos if item["baja"]),
        "n_validados": sum(1 for item in asientos if item["validado"]),
        "n_sin_validar": sum(
            1 for item in asientos if not item["validado"] and item["estado"] != "duplicado"
        ),
        "cola_revision": _cola_revision(asientos),
        "insights": _insights(asientos, ingresos, gastos, mejoras, actividad.codigo),
        "irpf": irpf,
        "xlsx_name": "",
    }


def render_dashboard(data: dict) -> str:
    default = "revisar" if data["n_baja"] or data["n_pendientes"] else "libro"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>Libro {escape(data['codigo'])} · {data['year']}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n"
        f'<body data-default-panel="{default}">\n'
        f"{_masthead(data)}\n"
        '<main class="wrap panels">\n'
        f"{_panel_revisar(data)}\n"
        f"{_panel_libro(data)}\n"
        f"{_panel_resumen(data)}\n"
        f"{_footer(data)}\n"
        "</main>\n"
        f"<script>{_JS}</script>\n"
        "</body>\n</html>\n"
    )


def _asiento_view(
    asiento: Asiento,
    nombres: dict[str, str],
    extra_casillas: dict[str, str],
    inmuebles: dict[int, str],
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
        "total": total,
        "total_num": float(total) if total is not None else 0.0,
        "cuenta": cuenta_nombre if codigo else "",
        "cuenta_nombre": cuenta_nombre,
        "tipo": asiento.tipo,
        "estado": asiento.estado,
        "estado_label": ESTADO_LABEL.get(asiento.estado, asiento.estado),
        "inmueble": inmuebles.get(asiento.inmueble_id or 0, ""),
        "doc_uri": doc_path,
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
        "cmd_confirmar": (
            f'aeat-hub reclasificar {asiento.id} "{cuenta_nombre}"' if codigo else ""
        ),
        "cmd_validar": f"aeat-hub validar {asiento.id}",
    }


def _conf_pct(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 100))


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


def _cumulative(series: list[dict]) -> list[dict]:
    gastos = ingresos = ZERO
    rows = []
    for item in series:
        gastos += item["gastos"]
        ingresos += item["ingresos"]
        rows.append(
            {
                "mes": item["mes"],
                "gastos": gastos,
                "ingresos": ingresos,
                "neto": ingresos - gastos,
            }
        )
    return rows


def _insights(
    asientos: list[dict],
    ingresos: Decimal,
    gastos: Decimal,
    mejoras: Decimal,
    codigo: str,
) -> list[dict]:
    items: list[dict] = []
    vivos = [item for item in asientos if item["estado"] != "duplicado"]
    gastos_rows = [item for item in vivos if item["tipo"] == TIPO_GASTO]
    top = max(gastos_rows, key=lambda item: item["total"] or ZERO, default=None)
    if top and (top["total"] or ZERO) > ZERO:
        items.append(
            {
                "kind": "kpi",
                "tone": "gasto",
                "titulo": "Mayor gasto",
                "valor": format_euro(top["total"]),
                "detalle": f"{top['emisor']} · {top['fecha_label']}",
            }
        )
    mix: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for item in gastos_rows:
        mix[item["cuenta_nombre"]] += item["total"] or ZERO
    if gastos > ZERO and mix:
        label, amount = max(mix.items(), key=lambda pair: pair[1])
        pct = int(round((amount / gastos) * 100))
        items.append(
            {
                "kind": "kpi",
                "tone": "gasto",
                "titulo": "Mix de gastos",
                "valor": f"{pct} %",
                "detalle": label,
                "pct": pct,
            }
        )
    if ingresos <= ZERO:
        items.append(
            {
                "kind": "alerta",
                "titulo": "Sin rentas en el ejercicio",
                "detalle": f"Suelta el recibo en inbox y: aeat-hub ingest --actividad {codigo}",
            }
        )
    if mejoras > ZERO:
        items.append(
            {
                "kind": "kpi",
                "tone": "mejora",
                "titulo": "Mejoras capitalizadas",
                "valor": format_euro(mejoras),
                "detalle": "No restan del rendimiento de este año.",
            }
        )
    dupes = sum(1 for item in asientos if item["estado"] == "duplicado")
    if dupes:
        items.append(
            {
                "kind": "alerta",
                "titulo": f"{dupes} duplicado(s)",
                "detalle": "No entran en los totales. Revisa antes de declarar.",
            }
        )
    baja = sum(1 for item in asientos if item.get("baja"))
    if baja:
        items.append(
            {
                "kind": "alerta",
                "titulo": f"{baja} asiento(s) con baja confianza",
                "detalle": "El modelo no está seguro. Ábrelos, corrige si hace falta y valida para no reprocesarlos.",
            }
        )
    validados = sum(1 for item in asientos if item.get("validado"))
    if validados:
        items.append(
            {
                "kind": "kpi",
                "tone": "ok",
                "titulo": "Validados por ti",
                "valor": str(validados),
                "detalle": "Bloqueados: reparse/OCR no pisan fecha, emisor, importes ni rubro.",
            }
        )
    return items


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
        {"mes": MESES[idx - 1], "gastos": buckets[idx]["gastos"], "ingresos": buckets[idx]["ingresos"]}
        for idx in range(1, 13)
    ]


def _by_nature(rows: list[Asiento], extra_casillas: dict[str, str]) -> list[dict]:
    buckets: dict[str, Decimal] = defaultdict(lambda: ZERO)
    tipos: dict[str, str] = {}
    for row in rows:
        label = _nature_label(row.cuenta_codigo, extra_casillas)
        buckets[label] += q2(row.total) or ZERO
        tipos.setdefault(label, row.tipo)
    ordered = sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    return [{"label": label, "total": total, "tipo": tipos[label]} for label, total in ordered if total]


def _nature_label(codigo: str | None, extra_casillas: dict[str, str]) -> str:
    if not codigo:
        return "Sin clasificar"
    clave = casilla_clave(codigo, extra_casillas)
    meta = INDEX_CI.get(clave)
    return meta.etiqueta if meta else "Sin clasificar"


def _masthead(data: dict) -> str:
    inmueble = f" · {escape(data['inmueble'])}" if data["inmueble"] else ""
    badge = ""
    if data["cola_revision"]:
        badge = f'<span class="tab-badge">{len(data["cola_revision"])}</span>'
    return f"""
<header class="mast">
  <div class="wrap mast-grid">
    <div>
      <p class="eyebrow">AEAT Hub · libro auxiliar</p>
      <h1>{escape(data["nombre"])} <span>{escape(data["codigo"])} · {data["year"]}</span></h1>
      <p class="meta">{escape(data["titular"])} · {escape(data["regimen_label"])}{inmueble}</p>
      <p class="mast-strip">
        {data["n_pendientes"]} por revisar · {data["n_sin_validar"]} sin validar ·
        neto {escape(format_euro(data["resultado"]))}
      </p>
    </div>
    <aside class="stamp">
      <strong>No es software oficial de la AEAT</strong>
      <span>Generado {escape(data["generated"])} desde SQLite. Revisa antes de declarar.</span>
    </aside>
  </div>
  <nav class="tabs" role="tablist" aria-label="Secciones del libro">
    <div class="wrap tabs-row">
      <button type="button" class="tab" role="tab" id="tab-revisar" data-panel="revisar"
        aria-controls="panel-revisar" aria-selected="false" tabindex="-1">
        Revisar calidad {badge}
      </button>
      <button type="button" class="tab" role="tab" id="tab-libro" data-panel="libro"
        aria-controls="panel-libro" aria-selected="false" tabindex="-1">Libro</button>
      <button type="button" class="tab" role="tab" id="tab-resumen" data-panel="resumen"
        aria-controls="panel-resumen" aria-selected="false" tabindex="-1">Resumen</button>
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
    {_kpi_btn("Gastos del ejercicio", data["gastos"], "gasto", "gasto")}
    {_kpi_btn("Ingresos", data["ingresos"], "ingreso", "ingreso")}
    {_kpi_btn("Mejoras (inversión)", data["mejoras"], "mejora", "mejora")}
    {_kpi_btn("Rendimiento neto", data["resultado"], "neto", "all", scroll="#charts")}
    {_kpi_btn_count("Por revisar", data["n_pendientes"], data["n_asientos"], "pendiente")}
  </div>
  {mejora_note}
</section>
"""


def _kpi_btn(label: str, value: Decimal, kind: str, filter_key: str, *, scroll: str = "#ledger") -> str:
    return (
        f'<button type="button" class="kpi kpi-{kind} kpi-btn" data-filter="{filter_key}" '
        f'data-scroll="{scroll}" aria-pressed="false">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(format_euro(value))}</strong></button>"
    )


def _kpi_btn_count(label: str, pendientes: int, total: int, filter_key: str) -> str:
    return (
        f'<button type="button" class="kpi kpi-count kpi-btn" data-filter="{filter_key}" '
        f'data-scroll="#ledger" aria-pressed="false">'
        f"<span>{escape(label)}</span>"
        f"<strong>{pendientes}</strong>"
        f"<em>de {total} asientos</em></button>"
    )


def _panel_revisar(data: dict) -> str:
    cola = data["cola_revision"]
    if not cola:
        return """
<section class="panel" role="tabpanel" id="panel-revisar" data-panel="revisar"
  aria-labelledby="tab-revisar">
  <p class="panel-lead">Todos los asientos están validados o son duplicados. El modelo no los volverá a pisar.</p>
  <p class="empty ok">Nada pendiente de revisión humana.</p>
</section>
"""
    rows = "\n".join(_review_row(item) for item in cola)
    return f"""
<section class="panel" role="tabpanel" id="panel-revisar" data-panel="revisar"
  aria-labelledby="tab-revisar">
  <p class="panel-lead">{len(cola)} asiento(s) sin validar, ordenados por peor confianza primero.
     Abre el PDF, comprueba emisor/importe/rubro y copia el comando en la terminal.</p>
  <div class="review-table-wrap">
    <table class="review-table">
      <thead>
        <tr>
          <th>Factura</th>
          <th>Rubro propuesto</th>
          <th>Confianza</th>
          <th>Doc</th>
          <th>Acción</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <p class="hint">Tras validar o reclasificar:
    <code>aeat-hub dashboard --actividad {escape(data["codigo"])} --year {data["year"]}</code></p>
</section>
"""


def _quality_pct_label(pct: int | None) -> str:
    return "—" if pct is None else f"{pct} %"


def _quality_cell(item: dict, *, prefix: str) -> str:
    if item["validado"]:
        tone = "ok"
        label = "Validado"
        hint = "Bloqueado: reparse y OCR no pisan fecha, emisor, importes ni rubro."
    elif item["baja"]:
        tone = "warn"
        label = "Revisar"
        hint = "El modelo no está seguro. Abre el PDF, corrige si hace falta y valida."
    else:
        tone = "ok"
        label = "Aceptable"
        hint = "Confianza ≥ 80 %. Revisa si algo no cuadra y valida para bloquearlo."
    ocr = _quality_pct_label(item["conf_ocr_pct"])
    rubro = _quality_pct_label(item["conf_class_pct"])
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
        f"<div><dt>Rubro</dt><dd>{escape(rubro)}</dd></div>"
        f"<div><dt>Casilla</dt><dd>{escape(casilla)}</dd></div></dl>"
        f"<p>{escape(hint)}</p>"
        f"</div></div>"
    )


def _review_actions(item: dict) -> str:
    cmds = [
        f'<button type="button" class="cmd-btn cmd-btn-ok" data-copy="{escape(item["cmd_validar"])}" '
        'title="Rubro correcto; bloquea reparse">Validar</button>'
    ]
    for nombre, label, title in RUBRO_CHIPS:
        if nombre == item["cuenta_nombre"]:
            continue
        cmd = f'aeat-hub reclasificar {item["id"]} "{nombre}"'
        cmds.append(
            f'<button type="button" class="cmd-btn" data-copy="{escape(cmd)}" '
            f'title="{escape(title)}">{escape(label)}</button>'
        )
    return f'<div class="cmds">{"".join(cmds)}</div>'


def _review_row(item: dict) -> str:
    doc_cell = "—"
    if item["doc_uri"]:
        title = escape(item["doc_name"] or "Factura")
        doc_cell = f'<a class="doc-link" href="{escape(item["doc_uri"])}" title="{title}">PDF</a>'
    rubro = escape(item["cuenta_nombre"])
    row_class = "review-row review-baja" if item["baja"] else "review-row"
    return (
        f'<tr class="{row_class}" id="review-asiento-{item["id"]}">'
        f"<td>"
        f"<strong>{escape(item['emisor'])}</strong>"
        f'<span class="sub">{escape(item["fecha_label"])} · '
        f"{escape(format_euro(item['total']))} · {escape(item['numero'])}</span></td>"
        f"<td>{rubro}</td>"
        f"<td>{_quality_cell(item, prefix='review')}</td>"
        f'<td class="cell-doc">{doc_cell}</td>'
        f"<td>{_review_actions(item)}</td>"
        "</tr>"
    )


def _panel_libro(data: dict) -> str:
    body = _ledger(data)
    return (
        '<div class="panel" role="tabpanel" id="panel-libro" data-panel="libro" '
        f'aria-labelledby="tab-libro">{body}</div>'
    )


def _panel_resumen(data: dict) -> str:
    mejora_note = ""
    if data["regimen"] == REGIMEN_CI:
        mejora_note = (
            '<p class="hint">En capital inmobiliario las <strong>mejoras no restan</strong> '
            "del rendimiento del año: se capitalizan y se amortizan.</p>"
        )
    return f"""
<section class="panel" role="tabpanel" id="panel-resumen" data-panel="resumen"
  aria-labelledby="tab-resumen">
  <div class="kpi-grid resumen-kpis">
    {_kpi_btn("Gastos", data["gastos"], "gasto", "gasto")}
    {_kpi_btn("Ingresos", data["ingresos"], "ingreso", "ingreso")}
    {_kpi_btn("Mejoras", data["mejoras"], "mejora", "mejora")}
    {_kpi_btn("Neto", data["resultado"], "neto", "all", scroll="#charts")}
    {_kpi_btn_count("Por revisar", data["n_pendientes"], data["n_asientos"], "pendiente")}
  </div>
  {mejora_note}
  {_insights_html(data)}
  {_irpf_html(data)}
</section>
"""


def _insights_html(data: dict) -> str:
    kpis = [item for item in data["insights"] if item["kind"] == "kpi"]
    alerts = [item for item in data["insights"] if item["kind"] == "alerta"]
    last = data["por_mes_acc"][-1] if data["por_mes_acc"] else {
        "neto": ZERO,
        "ingresos": ZERO,
        "gastos": ZERO,
    }
    sats = "".join(_evo_kpi(item) for item in kpis)
    board_class = "evo-board" if sats else "evo-board evo-board-solo"
    alert_bits = [
        f'<aside class="evo-alert">'
        f"<strong>{escape(item['titulo'])}</strong>"
        f"<p>{escape(item['detalle'])}</p></aside>"
        for item in alerts
    ]
    alerts_html = f'<div class="evo-alerts">{"".join(alert_bits)}</div>' if alert_bits else ""
    sats_wrap = f'<div class="evo-sats">{sats}</div>' if sats else ""
    return f"""
<section class="insights" id="insights" aria-label="Evolución e insights">
  <div class="review-head">
    <h2>Evolución</h2>
    <p>El neto del año está en la tarjeta. Aquí, el mes y el rubro.</p>
  </div>
  <div class="{board_class}">
    {_evo_hero(last, data["por_mes_acc"])}
    {sats_wrap}
  </div>
  {alerts_html}
  {_charts(data)}
</section>
"""


def _evo_hero(last: dict, series: list[dict]) -> str:
    ingresos = last["ingresos"]
    gastos = last["gastos"]
    neto = last["neto"]
    total = ingresos + gastos
    w_i = float(ingresos / total * 100) if total > 0 else 0.0
    w_g = float(gastos / total * 100) if total > 0 else 0.0
    ratio = ""
    if ingresos > ZERO:
        pct = int(round(float(gastos / ingresos * 100)))
        ratio = f"<em>Los gastos son el {pct} % de las rentas.</em>"
    elif gastos > ZERO:
        ratio = "<em>Hay gastos y aún no hay rentas en el ejercicio.</em>"
    return f"""
<article class="evo-hero">
  <div class="evo-hero-top">
    <span class="evo-label">Acumulado del año</span>
    <strong>{escape(format_euro(neto))}</strong>
    <span class="evo-sub">Rendimiento neto · ingresos − gastos</span>
  </div>
  {_spark_neto(series)}
  <div class="evo-track evo-track-split" role="img"
       aria-label="Ingresos {format_euro(ingresos)}, gastos {format_euro(gastos)}">
    <i class="ing" style="width:{w_i:.2f}%"></i>
    <i class="gas" style="width:{w_g:.2f}%"></i>
  </div>
  <dl class="evo-hero-stats">
    <div>
      <dt>Ingresos</dt>
      <dd class="ing">{escape(format_euro(ingresos))}</dd>
    </div>
    <div>
      <dt>Gastos</dt>
      <dd class="gas">{escape(format_euro(gastos))}</dd>
    </div>
  </dl>
  {ratio}
</article>
"""


def _evo_kpi(item: dict) -> str:
    tone = escape(item.get("tone") or "neto")
    bar = ""
    pct = item.get("pct")
    if pct is not None:
        bar = (
            f'<div class="evo-track" aria-hidden="true">'
            f'<i class="gas" style="width:{int(pct)}%"></i></div>'
        )
    return (
        f'<article class="evo-kpi evo-kpi-{tone}">'
        f'<span class="evo-label">{escape(item["titulo"])}</span>'
        f"<strong>{escape(item['valor'])}</strong>"
        f'<div class="evo-kpi-foot">{bar}<p>{escape(item["detalle"])}</p></div>'
        "</article>"
    )


def _spark_neto(series: list[dict]) -> str:
    if len(series) < 2:
        return ""
    width, height, pad = 280, 48, 3
    values = [float(item["neto"]) for item in series]
    hi = max(values + [0.0])
    lo = min(values + [0.0])
    span = hi - lo or 1.0
    inner_w = width - pad * 2
    inner_h = height - pad * 2
    pts = []
    for idx, value in enumerate(values):
        x = pad + inner_w * idx / (len(values) - 1)
        y = pad + inner_h * (hi - value) / span
        pts.append(f"{x:.1f},{y:.1f}")
    zero_y = pad + inner_h * (hi - 0.0) / span
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" aria-hidden="true">'
        f'<line class="spark-zero" x1="0" y1="{zero_y:.1f}" x2="{width}" y2="{zero_y:.1f}"/>'
        f'<polyline class="spark-line" fill="none" points="{" ".join(pts)}"/></svg>'
    )


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
            "<tr>"
            f"<td>{escape(item['etiqueta'])}</td>"
            f'<td class="num">{item["n"]}</td>'
            f'<td class="num">{escape(format_euro(item["total"]))}</td>'
            f"<td>{mark}</td>"
            f'<td class="muted">{escape(item["notas"])}</td>'
            "</tr>"
        )
    return f"""
<section class="irpf" id="irpf" aria-label="Borrador para la Renta">
  <div class="review-head">
    <h2>Como iría en la Renta</h2>
    <p>Totales para el anexo de inmueble (IRPF). Hacienda no recibe este Excel: copias los importes a la declaración.</p>
  </div>
  <div class="irpf-kpis">
    <article><span>Ingresos íntegros</span><strong>{escape(format_euro(irpf["ingresos"]))}</strong></article>
    <article><span>Gastos deducibles</span><strong>{escape(format_euro(irpf["gastos_deducibles"]))}</strong></article>
    <article><span>Rendimiento neto</span><strong>{escape(format_euro(irpf["rendimiento"]))}</strong></article>
    <article><span>Mejoras (fuera del año)</span><strong>{escape(format_euro(irpf["mejoras"]))}</strong></article>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Concepto</th>
          <th class="num">Asientos</th>
          <th class="num">Importe</th>
          <th>Resta del año</th>
          <th>Nota</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</section>
"""


def _footer(data: dict) -> str:
    xlsx = data.get("xlsx_name") or f"libro_{data['codigo']}_{data['year']}.xlsx"
    return f"""
<footer class="foot">
  <p>Para el gestor o para copiar importes a Hacienda. No es presentación telemática.</p>
  <a class="export-btn" href="{escape(xlsx)}" download="{escape(xlsx)}">Exportar Excel</a>
</footer>
"""


def _charts(data: dict) -> str:
    return f"""
<section class="charts" id="charts" aria-label="Gráficos">
  <figure>
    <figcaption>Por mes
      <span class="swatch g">gastos</span>
      <span class="swatch i">ingresos</span>
    </figcaption>
    {_svg_months(data["por_mes"])}
  </figure>
  <figure>
    <figcaption>Por rubro
      <span class="swatch g">gasto</span>
      <span class="swatch i">ingreso</span>
      <span class="swatch m">mejora</span>
    </figcaption>
    {_svg_nature(data["por_naturaleza"])}
  </figure>
</section>
"""


def _svg_months(series: list[dict]) -> str:
    if not series:
        return '<p class="empty">Sin movimientos mensuales todavía.</p>'
    width, height = 640, 220
    pad_l, pad_r, pad_t, pad_b = 44, 12, 16, 36
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    peak = max(
        (max(item["gastos"], item["ingresos"]) for item in series),
        default=ZERO,
    )
    peak = peak if peak > 0 else Decimal("1")
    slot = inner_w / max(len(series), 1)
    bar_w = min(slot * 0.32, 22)
    ticks = [
        (ZERO, pad_t + inner_h),
        (peak / 2, pad_t + inner_h / 2),
        (peak, pad_t),
    ]
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Gastos e ingresos de cada mes del ejercicio">'
    ]
    for value, y in ticks:
        parts.append(
            f'<line class="grid" x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}"/>'
            f'<text class="tick" x="{pad_l - 6}" y="{y + 4:.1f}">{escape(_compact(value))}</text>'
        )
    for idx, item in enumerate(series):
        x0 = pad_l + slot * idx + slot * 0.18
        h_g = float(item["gastos"] / peak) * inner_h
        h_i = float(item["ingresos"] / peak) * inner_h
        y_g = pad_t + inner_h - h_g
        y_i = pad_t + inner_h - h_i
        if h_g >= 0.5:
            parts.append(
                f'<rect class="bar-g" x="{x0:.1f}" y="{y_g:.1f}" width="{bar_w:.1f}" height="{h_g:.1f}" rx="1">'
                f'<title>{item["mes"]} gastos {format_euro(item["gastos"])}</title></rect>'
            )
        if h_i >= 0.5:
            parts.append(
                f'<rect class="bar-i" x="{x0 + bar_w + 2:.1f}" y="{y_i:.1f}" width="{bar_w:.1f}" height="{h_i:.1f}" rx="1">'
                f'<title>{item["mes"]} ingresos {format_euro(item["ingresos"])}</title></rect>'
            )
        parts.append(
            f'<text class="axis" x="{x0 + bar_w:.1f}" y="{height - 12}">{item["mes"]}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _svg_nature(series: list[dict]) -> str:
    if not series:
        return '<p class="empty">Aún no hay importes que agrupar.</p>'
    width = 640
    row_h = 52
    pad_l, pad_r = 16, 140
    height = 12 + row_h * len(series)
    peak = max((item["total"] for item in series), default=Decimal("1"))
    grand = sum((item["total"] for item in series), ZERO) or Decimal("1")
    inner_w = width - pad_l - pad_r
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Importes por rubro">'
    ]
    for idx, item in enumerate(series):
        y = 6 + idx * row_h
        bar = float(item["total"] / peak) * inner_w if peak else 0
        kind = {"gasto": "bar-g", "ingreso": "bar-i", "mejora": "bar-m"}.get(item["tipo"], "bar-g")
        pct = int(round(float(item["total"] / grand * 100)))
        parts.append(
            f'<text class="axis left" x="{pad_l}" y="{y + 12}">{escape(item["label"])}</text>'
            f'<rect class="{kind}" x="{pad_l}" y="{y + 18}" width="{max(bar, 2):.1f}" height="12" rx="2">'
            f'<title>{escape(item["label"])} {format_euro(item["total"])} ({pct} %)</title></rect>'
            f'<text class="tick right" x="{pad_l + max(bar, 2) + 8:.1f}" y="{y + 28}">'
            f'{escape(format_euro(item["total"]))} · {pct} %</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


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


def _filter_th(label: str, pop_id: str, inner: str, extra: str = "") -> str:
    cls = f" {extra}" if extra else ""
    return (
        f'<th class="th-filter{cls}">'
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


def _ledger_filter_choices(data: dict) -> dict[str, list[tuple[str, str]]]:
    asientos = data["asientos"]
    fechas = sorted(
        {(item["fecha"], item["fecha_label"]) for item in asientos if item["fecha"]},
        key=lambda pair: pair[0],
    )
    emisores = sorted({item["emisor"] for item in asientos if item["emisor"] != "—"})
    nifs = sorted({item["nif"] for item in asientos if item["nif"] != "—"})
    numeros = sorted({item["numero"] for item in asientos if item["numero"] != "—"})
    rubros = sorted(
        {item["cuenta_nombre"] for item in asientos if item["cuenta"]},
    )
    return {
        "fecha": list(fechas),
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
            ("pendiente", "Por revisar"),
            ("confirmado", "Confirmado"),
            ("duplicado", "Duplicados"),
        ],
    }


def _ledger(data: dict) -> str:
    rows = "\n".join(_row_html(item) for item in data["asientos"])
    empty = ""
    if not data["asientos"]:
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
    return f"""
<section class="ledger" id="ledger">
  <p class="panel-lead">Detalle fiscal de cada asiento. El embudo de cada columna abre el filtro.</p>
  <div class="ledger-status">
    <p class="status" id="status" aria-live="polite"></p>
    <button type="button" class="ghost" id="f-clear" hidden>Limpiar filtros</button>
  </div>
  {dup_note}
  <p class="table-scroll-hint">Desliza horizontalmente para ver todas las columnas.</p>
  <div class="table-wrap" tabindex="0" aria-label="Tabla de asientos con desplazamiento horizontal">
    <table class="ledger-table">
      <colgroup>
        <col class="col-id">
        <col class="col-fecha">
        <col class="col-emisor">
        <col class="col-calidad">
        <col class="col-estado">
        <col class="col-total">
        <col class="col-rubro">
        <col class="col-nif">
        <col class="col-factura">
        <col class="col-base">
        <col class="col-iva">
        <col class="col-doc">
      </colgroup>
      <thead>
        <tr>
          {_filter_th("Id", "pop-q", id_inner, "col-sticky")}
          {_filter_th("Fecha compra", "pop-fecha", _filter_checks("fecha", choices["fecha"]))}
          {_filter_th("Emisor", "pop-emisor", _filter_checks("emisor", choices["emisor"]))}
          {_filter_th("Confianza", "pop-confianza", _filter_checks("confianza", choices["confianza"]))}
          {_filter_th("Estado", "pop-estado", _filter_checks("estado", choices["estado"]), "cell-estado")}
          {_filter_th("Total", "pop-total", total_inner, "num")}
          {_filter_th("Rubro", "pop-rubro", _filter_checks("rubro", choices["rubro"]))}
          {_filter_th("NIF emisor", "pop-nif", _filter_checks("nif", choices["nif"]))}
          {_filter_th("Nº factura", "pop-factura", _filter_checks("factura", choices["factura"]))}
          <th class="num th-plain"><span class="th-label">Base</span></th>
          <th class="num th-plain"><span class="th-label">IVA</span></th>
          <th class="cell-doc th-plain"><span class="th-label">Doc</span></th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  {empty}
</section>
"""


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
    if item["doc_uri"]:
        title = escape(item["doc_name"] or "Factura")
        doc_cell = f'<a class="doc-link" href="{escape(item["doc_uri"])}" title="{title}">Abrir</a>'
    rubro = escape(item["cuenta_nombre"])
    emisor = escape(item["emisor"])
    if item["emisor"] != "—":
        emisor = f'<span class="cell-text" title="{emisor}">{emisor}</span>'
    calidad = _quality_cell(item, prefix="libro")
    baja_flag = "1" if item["baja"] else "0"
    emisor_key = item["emisor"] if item["emisor"] != "—" else ""
    return (
        f'<tr data-id="{item["id"]}" data-tipo="{escape(item["tipo"])}" '
        f'data-estado="{escape(item["estado"])}" data-baja="{baja_flag}" '
        f'data-fecha="{escape(item["fecha"])}" data-emisor="{escape(emisor_key)}" '
        f'data-cuenta="{escape(item["cuenta"])}" data-nif="{escape(item["nif"])}" '
        f'data-numero="{escape(item["numero"])}" data-validado="'
        f'{"1" if item["validado"] else "0"}" '
        f'data-total="{item["total_num"]:.2f}" data-q="{escape(blob)}">'
        f'<td class="mono col-sticky" data-label="Id">'
        f'<a href="#asiento-{item["id"]}" id="asiento-{item["id"]}">{item["id"]}</a></td>'
        f'<td class="cell-nowrap" data-label="Fecha">{escape(item["fecha_label"])}</td>'
        f'<td class="cell-clip" data-label="Emisor">{emisor}</td>'
        f'<td class="cell-calidad" data-label="Confianza">{calidad}</td>'
        f'<td class="cell-estado" data-label="Estado"><span class="pill {escape(item["estado"])}">'
        f'{escape(item["estado_label"])}</span></td>'
        f'<td class="num cell-nowrap" data-label="Total">{escape(format_euro(item["total"]))}</td>'
        f'<td class="cell-rubro" data-label="Rubro">{rubro}</td>'
        f'<td class="mono cell-nowrap" data-label="NIF">{escape(item["nif"])}</td>'
        f'<td class="mono cell-clip" data-label="Factura">{escape(item["numero"])}</td>'
        f'<td class="num cell-nowrap" data-label="Base">{escape(format_euro(item["base"]))}</td>'
        f'<td class="num cell-nowrap" data-label="IVA">{escape(format_euro(item["iva"]))}</td>'
        f'<td class="cell-doc" data-label="Doc">{doc_cell}</td>'
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
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--paper); color: var(--ink); }
body {
  font: 15px/1.45 "Avenir Next", "Segoe UI", system-ui, sans-serif;
}
.wrap { width: min(1360px, calc(100% - 32px)); margin-inline: auto; }
.mast {
  background: var(--sheet);
  padding: 28px 0 0;
}
.mast-grid { display: flex; justify-content: space-between; gap: 24px; align-items: end; padding-bottom: 22px; }
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
h1 span { color: var(--muted); font-size: 22px; font-weight: 500; }
.meta { margin: 8px 0 0; color: var(--muted); }
.mast-strip { margin: 10px 0 0; font-size: 13px; color: var(--muted); }
.stamp {
  max-width: 280px;
  border: 1px solid var(--line);
  padding: 10px 12px;
  font-size: 12px;
  color: var(--muted);
}
.stamp strong { display: block; color: var(--gasto); font-size: 12px; margin-bottom: 4px; }
.panels { padding: 18px 0 48px; }
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
  z-index: 20;
  width: 220px;
  padding: 10px 12px;
  background: var(--ink);
  color: var(--sheet);
  font-size: 12px;
  line-height: 1.4;
  border: 0;
  box-shadow: 0 8px 20px rgba(28, 24, 20, .18);
}
.q-pop strong { display: block; margin-bottom: 8px; font-size: 13px; }
.q-pop dl { margin: 0; display: grid; gap: 4px; }
.q-pop dl div { display: flex; justify-content: space-between; gap: 12px; }
.q-pop dt { color: #c9c2b6; }
.q-pop dd { margin: 0; font-variant-numeric: tabular-nums; }
.q-pop p { margin: 8px 0 0; color: #d8d0c4; }
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
  cursor: pointer;
  transition: transform .12s ease, box-shadow .12s ease;
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
.evo-board {
  display: grid;
  grid-template-columns: minmax(240px, 1.35fr) minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
}
.evo-board-solo { grid-template-columns: 1fr; }
.evo-sats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.evo-label {
  display: block;
  margin: 0;
  font-size: 11px;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--muted);
}
.evo-hero {
  background: var(--neto);
  color: #f4efe6;
  padding: 18px 18px 16px;
  display: flex;
  flex-direction: column;
  min-height: 100%;
}
.evo-hero .evo-label { color: #c9c2b6; }
.evo-hero strong {
  display: block;
  margin: 8px 0 4px;
  font: 600 36px/1 "Iowan Old Style", Palatino, serif;
  font-variant-numeric: tabular-nums;
  color: #fff;
}
.evo-sub { display: block; font-size: 12px; color: #c9c2b6; }
.evo-hero em {
  display: block;
  margin-top: 10px;
  font-style: normal;
  font-size: 12px;
  color: #d8d0c4;
}
.evo-hero-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin: 12px 0 0;
}
.evo-hero-stats dt {
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: #c9c2b6;
}
.evo-hero-stats dd {
  margin: 4px 0 0;
  font: 600 16px/1 Palatino, serif;
  font-variant-numeric: tabular-nums;
}
.evo-hero-stats dd.ing { color: #b7d4cb; }
.evo-hero-stats dd.gas { color: #e3b4ab; }
.evo-kpi {
  border: 1px solid var(--line);
  border-top-width: 3px;
  padding: 14px 14px 12px;
  background: #fff;
  display: flex;
  flex-direction: column;
}
.evo-kpi strong {
  display: block;
  margin-top: 8px;
  font: 600 26px/1 "Iowan Old Style", Palatino, serif;
  font-variant-numeric: tabular-nums;
}
.evo-kpi p { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
.evo-kpi-foot { margin-top: auto; padding-top: 12px; }
.evo-kpi-gasto { border-top-color: var(--gasto); }
.evo-kpi-mejora { border-top-color: var(--mejora); }
.evo-kpi-ok { border-top-color: var(--ingreso); }
.evo-kpi-neto { border-top-color: var(--neto); }
.evo-track {
  height: 8px;
  background: var(--paper);
  margin-top: 12px;
  overflow: hidden;
}
.evo-track i { display: block; height: 100%; }
.evo-track i.ing { background: var(--ingreso); }
.evo-track i.gas { background: var(--gasto); }
.evo-track-split {
  display: flex;
  background: rgba(251, 247, 239, .14);
  margin-top: auto;
  padding: 0;
}
.evo-track-split i { flex: 0 0 auto; }
.evo-alerts { display: grid; gap: 8px; margin-top: 12px; }
.evo-alert {
  border: 1px solid var(--line);
  border-left: 4px solid var(--warn);
  background: #fff;
  padding: 10px 12px;
}
.evo-alert strong { display: block; font-size: 13px; }
.evo-alert p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.spark { width: 100%; height: 48px; margin: 16px 0 14px; display: block; }
.spark-line { stroke: #f4efe6; stroke-width: 1.8; }
.spark-zero { stroke: rgba(251, 247, 239, .28); stroke-dasharray: 3 3; }
.irpf-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.irpf-kpis article { border: 1px solid var(--line); padding: 10px 12px; background: #fff; }
.irpf-kpis span { display: block; font-size: 12px; color: var(--muted); }
.irpf-kpis strong { display: block; margin-top: 6px; font: 600 20px/1 Palatino, serif; }
.muted { color: var(--muted); font-size: 12px; }
.foot {
  margin: 0 0 48px;
  color: var(--muted);
  font-size: 13px;
}
.export-btn {
  display: inline-block;
  margin-top: 10px;
  padding: 10px 16px;
  background: var(--neto);
  color: #f4efe6;
  font: 600 14px/1 "Avenir Next", "Segoe UI", system-ui, sans-serif;
  text-decoration: none;
  border-radius: 2px;
}
.export-btn:hover { filter: brightness(1.08); }
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
  z-index: 5;
}
tbody tr.flash { background: rgba(163, 91, 18, .12); }
.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
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
  gap: 6px 12px;
  align-items: baseline;
  font-size: 13px;
  color: var(--muted);
  margin-bottom: 8px;
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
svg { width: 100%; height: auto; display: block; }
.grid { stroke: var(--line); stroke-width: 1; }
.tick, .axis, .legend { font: 11px/1 "Avenir Next", system-ui, sans-serif; fill: var(--muted); }
.tick { text-anchor: end; }
.axis { text-anchor: middle; }
.axis.left { text-anchor: start; fill: var(--ink); font-size: 12px; }
.tick.right { text-anchor: start; fill: var(--ink); font-size: 11px; }
.bar-g { fill: var(--gasto); }
.bar-i { fill: var(--ingreso); }
.bar-m { fill: var(--mejora); }
.ledger { background: var(--sheet); border: 1px solid var(--line); padding: 16px 16px 8px; margin-bottom: 48px; }
.ledger-status { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin: 0 0 10px; }
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
  width: max(100%, 1180px);
  min-width: 1180px;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 13px;
}
.col-id { width: 56px; }
.col-fecha { width: 118px; }
.col-emisor { width: 150px; }
.col-calidad { width: 110px; }
.col-estado { width: 112px; }
.col-total { width: 84px; }
.col-rubro { width: 168px; }
.col-nif { width: 104px; }
.col-factura { width: 118px; }
.col-base, .col-iva { width: 72px; }
.col-doc { width: 52px; }
thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: #fff;
  box-shadow: 0 1px 0 var(--line);
  vertical-align: middle;
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
tbody tr:hover td.col-sticky { background: #faf6ef; }
tbody tr:target td.col-sticky { background: #fff6eb; }
th, td {
  text-align: left;
  padding: 10px 8px;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
thead th {
  padding: 8px 10px;
  vertical-align: middle;
}
.th-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
}
.th-label { display: block; }
.funnel {
  flex: 0 0 auto;
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
.filter-pop-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}
.filter-done {
  border: 0;
  background: none;
  color: var(--muted);
  font: 600 13px/1 inherit;
  cursor: pointer;
  padding: 4px 0;
}
.cell-clip, .cell-rubro {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell-nowrap { white-space: nowrap; }
.cell-calidad { white-space: nowrap; min-width: 0; }
.cell-estado, .cell-doc { text-align: center; white-space: nowrap; }
thead th.num, tbody td.num { text-align: right; }
thead th.cell-estado, thead th.cell-doc { text-align: center; }
thead th.num .th-head, thead th.cell-estado .th-head, thead th.cell-doc .th-head { justify-content: space-between; }
thead th.col-sticky { text-align: left; }
tbody td.col-sticky { text-align: center; }
tbody tr:hover { background: rgba(28, 24, 20, .03); }
tbody tr:target { background: rgba(163, 91, 18, .08); }
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
.doc-link { font-weight: 600; color: var(--neto); text-decoration: none; border-bottom: 1px solid transparent; }
.doc-link:hover { border-bottom-color: var(--neto); }
.empty { color: var(--muted); padding: 12px; }
@media (max-width: 900px) {
  .kpi-grid, .mast-grid, .irpf-kpis, .evo-board, .evo-sats, .charts { grid-template-columns: 1fr; display: grid; }
  .charts figure:last-child { grid-column: auto; }
  .action { align-items: flex-start; }
  .table-wrap { max-height: none; border: 0; }
  .table-scroll-hint { display: none; }
  .ledger-table { min-width: 0; width: 100%; table-layout: auto; }
  thead { display: block; margin-bottom: 10px; border: 1px solid var(--line); background: #fff; }
  thead tr { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px; }
  thead th {
    display: flex;
    flex-direction: column;
    position: static;
    box-shadow: none;
    flex: 1 1 140px;
    min-width: 140px;
    padding: 4px 8px;
    border: 0;
    text-align: left;
  }
  thead th.th-plain { display: none; }
  thead th.col-sticky, tbody td.col-sticky {
    position: static;
    box-shadow: none;
    background: transparent;
  }
  tbody tr { display: block; border: 1px solid var(--line); margin-bottom: 10px; padding: 8px; background: #fff; }
  tbody td { display: grid; grid-template-columns: 110px 1fr; gap: 8px; border: 0; padding: 4px 0; }
  tbody td::before {
    content: attr(data-label);
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .04em;
  }
  tbody td.num { text-align: left; }
}
@media print {
  body { background: #fff; }
  .kpi-btn, .ghost, .cmd-btn, .review, .tabs, .funnel, .filter-pop, .export-btn { display: none; }
  .mast, .kpi, .evo-hero, .evo-kpi, figure, .ledger { break-inside: avoid; }
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

  const matchesRow = (row) => {
    const q = (input?.value || "").trim().toLowerCase();
    if (q && !(row.dataset.q || "").includes(q)) return false;
    if (!matchesGroup("fecha", row.dataset.fecha)) return false;
    if (!matchesGroup("emisor", row.dataset.emisor)) return false;
    if (!matchesGroup("nif", row.dataset.nif)) return false;
    if (!matchesGroup("factura", row.dataset.numero)) return false;
    if (!matchesGroup("rubro", row.dataset.cuenta)) return false;
    const estadoSel = selectedValues("estado");
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
    if (selectedValues("fecha")) bits.push("fecha");
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
      const rangeDirty = [...pop.querySelectorAll("input[type=number], #q")].some((el) => (el.value || "").trim());
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

  const apply = () => {
    const bits = activeBits();
    let visible = 0;
    let totalVisible = 0;
    for (const row of rows) {
      const show = matchesRow(row);
      row.hidden = !show;
      if (show) {
        visible += 1;
        totalVisible += Number(row.dataset.total || 0);
      }
    }
    syncFunnels();
    syncKpiPressed();
    if (fClear) fClear.hidden = bits.length === 0;
    if (!status) return;
    status.classList.toggle("empty-query", bits.length > 0 && visible === 0);
    if (visible === 0) {
      status.textContent = bits.length
        ? "Ningún asiento coincide con estos filtros."
        : "No hay asientos en este ejercicio.";
      return;
    }
    let line = `Mostrando ${visible} de ${rows.length}`;
    if (bits.length) line += ` · ${bits.join(" · ")}`;
    if (totalVisible) line += ` · Total visible: ${formatEuro(totalVisible)}`;
    status.textContent = line;
  };

  const clearAdvanced = () => {
    for (const box of document.querySelectorAll("input[data-fg]")) box.checked = true;
    if (fMin) fMin.value = "";
    if (fMax) fMax.value = "";
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
    row.hidden = false;
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
    const box = chip.getBoundingClientRect();
    const width = pop.classList.contains("filter-pop") ? Math.min(300, window.innerWidth - 24) : 220;
    const left = Math.min(box.left, window.innerWidth - width - 12);
    pop.style.inset = "auto";
    pop.style.margin = "0";
    pop.style.width = pop.classList.contains("filter-pop") ? `${width}px` : "";
    pop.style.left = `${Math.max(12, left)}px`;
    pop.style.top = `${box.bottom + 6}px`;
  };
  for (const chip of document.querySelectorAll(".funnel[popovertarget], .q-chip[popovertarget]")) {
    const pop = document.getElementById(chip.getAttribute("popovertarget"));
    if (!pop) continue;
    pop.addEventListener("toggle", (event) => {
      const open = event.newState === "open";
      chip.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) placePop(chip, pop);
    });
  }

  apply();
})();
"""
