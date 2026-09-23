from datetime import date
from decimal import Decimal

from sqlalchemy import select

from aeat_hub.dashboard import (
    _emisores_para_grafico,
    collect_asiento_ficha,
    collect_dashboard,
    render_asiento_page,
    write_dashboard,
)
from aeat_hub.models import Actividad, Asiento


def _seed_asientos(session, actividad):
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            cuenta_codigo="CI.GAS.LUZ",
            fecha=date(2026, 3, 10),
            ejercicio=2026,
            emisor="IBERDROLA DEMO",
            nif_emisor="B12345674",
            numero_factura="F1",
            base=Decimal("40.00"),
            iva_cuota=Decimal("8.40"),
            total=Decimal("48.40"),
            estado="confirmado",
            validado=True,
        )
    )
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="ingreso",
            cuenta_codigo="CI.ING.RENTA",
            fecha=date(2026, 3, 1),
            ejercicio=2026,
            emisor="Inquilino",
            total=Decimal("700.00"),
            estado="confirmado",
        )
    )
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="mejora",
            cuenta_codigo="CI.MEJ.PVC",
            fecha=date(2026, 4, 2),
            ejercicio=2026,
            emisor="Ventanas Demo",
            total=Decimal("1452.00"),
            estado="confirmado",
        )
    )
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            cuenta_codigo="CI.GAS.LUZ",
            fecha=date(2026, 3, 10),
            ejercicio=2026,
            emisor="IBERDROLA DUPLICADA",
            total=Decimal("48.40"),
            estado="duplicado",
        )
    )
    session.add(
        Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            cuenta_codigo="CI.GAS.HOGAR",
            fecha=date(2026, 9, 5),
            ejercicio=2026,
            emisor="LEROY MERLIN ARROYO",
            nif_emisor="B84818442",
            numero_factura="064-0009-R194007",
            base=Decimal("25.99"),
            iva_cuota=Decimal("5.46"),
            total=Decimal("31.45"),
            confianza_clasificacion=Decimal("0.60"),
            estado="pendiente",
        )
    )
    session.commit()


def test_dashboard_kpis_excluyen_duplicados_y_mejoras(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    _seed_asientos(session, actividad)
    data = collect_dashboard(session, actividad, 2026)
    assert data["gastos"] == Decimal("79.85")
    assert data["ingresos"] == Decimal("700.00")
    assert data["mejoras"] == Decimal("1452.00")
    assert data["resultado"] == Decimal("620.15")
    assert data["n_duplicados"] == 1
    assert data["n_pendientes"] == 1
    assert len(data["pendientes"]) == 1
    assert len(data["cola_revision"]) >= 1
    assert data["cola_revision"][0]["emisor"] == "LEROY MERLIN ARROYO"
    assert data["irpf"]["rendimiento"] == Decimal("620.15")
    assert data["irpf"]["mejoras"] == Decimal("1452.00")
    labels = {item["label"] for item in data["por_naturaleza"]}
    assert "Suministros" in labels
    assert "Mejoras" in labels
    assert "Otros gastos" in labels
    assert "Ingresos" in labels
    assert "Hogar / mantenimiento" not in labels
    assert "Rentas" not in labels


def test_dashboard_html_tiene_emisor_y_fecha(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    _seed_asientos(session, actividad)
    dest = write_dashboard(session, layout, actividad, 2026)
    assert dest.is_file()
    html = dest.read_text(encoding="utf-8")
    assert "Fecha compra" in html
    assert "LEROY MERLIN ARROYO" in html
    assert "05/09/2026" in html
    assert "B84818442" in html
    assert "31,45 €" in html
    assert "Libro" in html
    assert html.count("<h2>Revisar calidad</h2>") == 0
    assert "Revisar calidad" not in html
    assert 'role="tablist"' in html
    assert 'role="tab"' in html
    assert 'aria-selected=' in html
    assert 'id="panel-revisar"' not in html
    assert 'id="panel-libro"' in html
    assert 'id="panel-insights"' in html
    assert 'id="panel-resumen"' not in html
    assert ">Libro" in html
    assert ">Insights</button>" in html
    assert ">Resumen</button>" not in html
    assert 'data-default-panel="libro"' in html
    assert "dash-nav" not in html
    assert 'class="review-table"' not in html
    assert "q-chip" in html
    assert "q-dot" in html
    assert "popovertarget=" in html
    assert "Confianza" in html
    assert "Como iría en la Renta" in html
    assert 'aria-label="Filtrar Concepto"' in html
    assert 'aria-label="Filtrar Resta del año"' in html
    assert ">Operativo</h2>" in html
    assert ">Renta</h2>" in html
    assert "concentra el" in html
    assert "IBERDROLA DEMO concentra el 61 % del gasto" in html
    assert 'id="insight-desde"' in html
    assert 'id="insight-hasta"' in html
    assert 'id="insight-range-save"' in html
    assert "Año completo" in html
    assert 'id="insight-rows"' in html
    assert 'class="evo-alert"' not in html
    assert "chart-scroll" in html
    assert "Gasto por mes" in html
    assert "Por emisor" in html
    assert "Por rubro" not in html
    assert "Destacados" not in html
    assert 'aria-label="Gasto de cada mes del año"' in html
    meses = html.split('aria-label="Gasto de cada mes del año"', 1)[1].split("</svg>", 1)[0]
    assert ">ene</text>" in meses
    assert ">dic</text>" in meses
    emisores = html.split('aria-label="Gasto por emisor"', 1)[1].split("</svg>", 1)[0]
    assert emisores.index("IBERDROLA DEMO") < emisores.index("LEROY MERLIN ARROYO")
    assert "IBERDROLA DUPLICADA" not in emisores
    assert "Acumulado del año" not in html
    assert "evo-hero" not in html
    assert 'href="/doc/' not in html or "Abrir" in html
    assert 'data-validar="' in html
    assert "Por validar" in html
    assert 'class="estado-btn estado-pend"' in html
    assert 'class="estado-btn estado-ok"' in html
    assert 'data-col-toggle="estado"' not in html
    assert "Acción queda fija" not in html
    assert 'data-edit="' in html
    assert 'id="edit-dialog"' in html
    assert "Seguro que quieres modificar" in html
    assert 'class="cell-input"' not in html
    assert 'id="edit-nif"' in html
    assert 'id="edit-emisor"' in html
    assert 'id="edit-fecha"' in html
    assert 'id="edit-base"' not in html
    assert 'id="edit-iva"' not in html
    assert 'id="edit-total"' not in html
    assert 'id="edit-lines-body"' not in html
    assert "Base, IVA y total no se editan aquí" in html
    assert 'id="lines-dialog"' not in html
    assert 'href="/asiento/' in html
    assert "data-href=" in html
    assert "Volver al libro" not in html
    assert "total-drill" in html
    assert 'class="row-edit"' in html
    assert ".row-edit svg" in html
    assert "figure svg" in html
    assert "ok-mark" not in html
    assert "A revisión" not in html
    assert ">Validado</button>" in html
    assert "Exportar visible" in html
    assert "Libro completo (xlsx)" in html
    assert 'class="ledger-table"' in html
    assert "Desliza horizontalmente para ver todas las columnas." not in html
    assert "oculta columnas" not in html.lower()
    assert "Pulsa una fila" not in html
    assert 'id="libro-kpis"' in html
    assert 'id="libro-n"' in html
    assert 'id="libro-total"' in html
    assert 'id="libro-pager"' in html
    assert 'id="libro-prev"' in html
    assert 'id="libro-next"' in html
    assert "const PAGE_SIZE = 15" in html
    assert 'class="funnel"' in html
    assert "Filtrar: Emisor" in html
    assert "Seleccionar todo" in html
    assert 'data-fg="emisor"' in html
    assert 'data-fg="estado"' in html
    assert 'data-fg="fecha"' not in html
    assert 'id="f-desde"' in html
    assert 'id="f-hasta"' in html
    assert 'type="date"' in html
    assert "Desde" in html
    assert "Hasta" in html
    assert 'data-fecha=' in html
    assert "Más filtros: emisor" not in html
    assert 'class="th-input"' not in html
    assert "Hogar" in html
    assert "rubro-code" not in html
    assert "CI.GAS." not in html
    assert "CI.MEJ." not in html
    assert "CI.ING." not in html
    assert "Exportar visible" in html
    assert "download=" in html
    assert "aeat-hub export --actividad" not in html
    assert "<script" in html.lower() or "IBERDROLA DEMO" in html
    assert "script src=" not in html
    assert "cdn." not in html
    assert html.count("<script") == 1
    assert 'id="mast-nombre"' in html
    assert 'id="mast-edit"' in html
    assert 'id="mast-dialog"' in html
    assert html.count("const inmuebleEl") == 1
    assert 'class="row-go"' in html
    assert "Títulos del libro" in html
    assert "Alquiler Valladolid" in html
    assert "Titular local" in html
    assert "Vivienda Valladolid" in html
    thead = html.split("<thead>", 1)[1].split("</thead>", 1)[0]
    assert thead.index("Nº factura") < thead.index("Fecha compra")
    assert 'id="solo-revisar"' not in html
    assert "Solo por revisar" not in html
    assert 'id="cols-toggle"' in html
    assert 'class="ledger-actions"' in html
    assert html.index('id="libro-kpis"') < html.index('id="status"')
    assert html.index('id="status"') < html.index('class="ledger-actions"')
    assert 'id="export-visible-top"' not in html
    assert 'id="pop-cols"' in html
    assert 'data-col="factura"' in html
    assert 'data-col-toggle="base"' in html
    assert thead.index("Doc") < thead.index("Estado")
    assert "Rubro" not in thead.split("</thead>", 1)[0]
    assert ">Artículos</span>" in html
    assert 'data-col="articulos"' in html
    assert 'data-col="rubro"' not in html
    assert "Acción" not in thead
    assert "table-layout: fixed" in html
    assert ".col-emisor { width: 14%; }" in html
    assert ".col-emisor { width: auto; }" not in html
    assert "viewport-fit=cover" in html
    assert "@media (max-width: 1100px)" in html
    assert "@media (max-width: 700px)" in html
    assert "@media (pointer: coarse)" in html
    mobile = html.split("@media (max-width: 700px)", 1)[1].split("@media", 1)[0]
    assert "overflow-x: auto" in mobile
    assert "tbody td::before" not in mobile
    assert "position: static" in mobile
    assert ".ledger-table tbody tr {\n    display: block" not in html
    assert "@media (max-width: 900px)" not in html
    assert "No es software oficial de la AEAT" not in html
    assert 'class="stamp"' not in html
    assert 'class="site-foot"' in html
    assert "min-height: 100dvh" in html
    assert ".foot {\n  margin-top: auto;" in html
    assert "cgomezfandino@gmail.com" in html
    assert "github.com/cgomezfandino/aeat-hub" in html
    assert "mejorar el modelo" in html


def test_ficha_asiento_tiene_volver_y_compra(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    _seed_asientos(session, actividad)
    row = session.scalar(select(Asiento).where(Asiento.emisor == "LEROY MERLIN ARROYO"))
    html = render_asiento_page(
        collect_asiento_ficha(session, row, dashboard_name="dashboard_CI-VA-001_2026.html")
    )
    assert "Volver al libro" in html
    assert f'href="/dashboard_CI-VA-001_2026.html#asiento-{row.id}"' in html
    assert "Líneas de la factura" in html
    assert 'id="ficha-kpis"' in html
    assert 'class="kpi-dots"' in html
    assert 'id="ficha-lines-save"' in html
    assert 'aria-label="Editar línea 1"' not in html
    assert 'id="ficha-line-tools" hidden' in html
    assert "cambios sin guardar" in html
    assert "Qué se compró" not in html
    assert 'class="th-label">Id</span>' in html
    assert 'aria-label="Filtrar Id"' in html
    assert 'aria-label="Filtrar Concepto"' in html
    assert 'aria-label="Filtrar Total"' in html
    assert "Subtotal" in html
    assert "LEROY MERLIN ARROYO" in html
    assert "Historial de cambios" in html
    assert 'id="ficha-log"' in html
    assert 'id="ficha-log-dialog"' in html
    assert "<th>Antes</th><th>Después</th>" in html
    assert "Sin líneas extraídas" in html
    assert "0 elementos" in html
    assert '<dt>Elementos</dt><dd id="kpi-elementos">0</dd>' in html
    assert 'data-check="ids" data-ok="0"' in html
    assert "No hay líneas, así que no hay ids de artículo." in html
    assert "total del libro" in html
    assert "No es software oficial de la AEAT" not in html
    assert 'class="site-foot"' in html
    assert "cgomezfandino@gmail.com" in html
    assert "github.com/cgomezfandino/aeat-hub" in html


def test_dashboard_pop_confianza_cita_casilla(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    _seed_asientos(session, actividad)
    html = write_dashboard(session, layout, actividad, 2026).read_text(encoding="utf-8")
    assert "<dt>OCR</dt>" in html
    assert "<dt>Clasificación</dt><dd>60 %</dd>" in html
    assert "<dt>Rubro</dt><dd>Hogar</dd>" in html
    assert "<dt>Casilla</dt><dd>Otros gastos</dd>" in html


def test_dashboard_actividad_economica_agrupa_por_nombre_de_rubro(session):
    titular_id = session.scalar(
        select(Actividad.titular_id).where(Actividad.codigo == "CI-VA-001")
    )
    actividad = Actividad(
        codigo="AE-TEST-001",
        titular_id=titular_id,
        nombre="Actividad de prueba",
        regimen="actividad_economica",
    )
    session.add(actividad)
    session.flush()
    session.add_all(
        [
            Asiento(
                actividad_id=actividad.id,
                tipo="gasto",
                cuenta_codigo="AE.GAS.SS",
                fecha=date(2026, 5, 1),
                ejercicio=2026,
                emisor="Seguridad Social",
                total=Decimal("320.00"),
                estado="confirmado",
            ),
            Asiento(
                actividad_id=actividad.id,
                tipo="ingreso",
                cuenta_codigo="AE.ING.VENTAS",
                fecha=date(2026, 5, 2),
                ejercicio=2026,
                emisor="Cliente",
                total=Decimal("900.00"),
                estado="confirmado",
            ),
        ]
    )
    session.commit()

    labels = {
        item["label"]
        for item in collect_dashboard(session, actividad, 2026)["por_naturaleza"]
    }

    assert labels == {"Seguridad social del autónomo", "Ingresos de explotación"}
    assert "Sin clasificar" not in labels


def _ficha_payload(**over) -> dict:
    data = {
        "lineas": [],
        "n_lineas": 0,
        "lineas_ok": False,
        "lineas_suma": None,
        "base": Decimal("10.00"),
        "iva": Decimal("2.10"),
        "total": Decimal("12.10"),
        "cambios": [],
        "has_doc": False,
        "id": 9,
        "dashboard_href": "/#asiento-9",
        "actividad_codigo": "CI-VA-001",
        "year": 2026,
        "emisor": "Demo",
        "numero": "F-9",
        "fecha_label": "01/01/2026",
        "estado": "pendiente",
        "estado_label": "Por revisar",
        "nif": "B12345674",
        "cuenta_nombre": "Hogar",
        "casilla_etiqueta": "Otros gastos",
    }
    data.update(over)
    return data


def test_ficha_desglose_cuadra_con_total_del_libro():
    lineas = [
        {
            "posicion": 1,
            "codigo": "111",
            "descripcion": "Tornillo",
            "base": Decimal("10.00"),
            "iva_cuota": Decimal("2.10"),
            "importe": Decimal("12.10"),
        },
        {
            "posicion": 2,
            "codigo": "222",
            "descripcion": "Tuerca",
            "base": Decimal("5.00"),
            "iva_cuota": Decimal("1.05"),
            "importe": Decimal("6.05"),
        },
    ]
    html = render_asiento_page(
        _ficha_payload(
            lineas=lineas,
            n_lineas=2,
            lineas_suma=Decimal("18.15"),
            lineas_ok=True,
            base=Decimal("15.00"),
            iva=Decimal("3.15"),
            total=Decimal("18.15"),
        )
    )
    assert "2 elementos" in html
    assert '<dt>Elementos</dt><dd id="kpi-elementos">2</dd>' in html
    assert "Lista" in html
    assert "100 %" in html
    assert "total del libro" in html
    assert 'data-check="ids"' in html
    assert 'data-check="nif"' in html
    assert 'class="line-view"' in html
    assert 'class="line-edit" disabled' in html
    assert 'aria-label="Editar línea 1"' in html
    assert "cambios sin guardar" in html
    assert 'id="app-confirm"' in html
    assert 'id="ficha-pager"' in html
    assert 'id="ficha-prev"' in html
    assert 'id="ficha-next"' in html
    assert '>Acciones</span>' in html
    assert 'id="kpi-total"' in html
    assert 'aria-label="IVA %"' in html
    assert "line-calc" in html
    assert 'class="line-totals"' not in html
    assert "18,15 €" in html
    assert "No cuadra" not in html


def test_ficha_desglose_no_cuadra_con_total_del_libro():
    lineas = [
        {
            "posicion": 1,
            "codigo": "1",
            "descripcion": "A",
            "base": Decimal("10.00"),
            "iva_cuota": Decimal("2.10"),
            "importe": Decimal("12.10"),
        }
    ]
    html = render_asiento_page(
        _ficha_payload(
            lineas=lineas,
            n_lineas=1,
            lineas_suma=Decimal("12.10"),
            lineas_ok=False,
            total=Decimal("31.45"),
        )
    )
    assert "1 elemento" in html
    assert "Revisar" in html
    assert "diferencia" in html
    assert "Puede faltar un artículo" in html
    assert "31,45 €" in html
    assert 'data-check="suma" data-ok="0"' in html


def test_ficha_senala_el_id_que_falta():
    lineas = [
        {
            "posicion": 1,
            "codigo": "",
            "descripcion": "Sierra",
            "base": Decimal("10.00"),
            "iva_cuota": Decimal("2.10"),
            "importe": Decimal("12.10"),
        }
    ]
    html = render_asiento_page(
        _ficha_payload(
            lineas=lineas,
            n_lineas=1,
            lineas_suma=Decimal("12.10"),
            total=Decimal("12.10"),
        )
    )
    assert 'data-check="ids" data-ok="0"' in html
    assert "Falta el id en Sierra" in html
    assert 'id="ficha-score-label">Revisar' in html


def test_emisores_de_gasto_dejan_el_resto_al_final():
    rows = [
        {
            "estado": "confirmado",
            "tipo": "gasto",
            "emisor": f"Casa {idx}",
            "total": Decimal(20 - idx),
        }
        for idx in range(7)
    ]
    chart = _emisores_para_grafico(rows)
    assert [item["label"] for item in chart[:-1]] == [f"Casa {idx}" for idx in range(6)]
    assert chart[-1]["label"] == "Resto"
    assert chart[-1]["total"] == Decimal("14")
