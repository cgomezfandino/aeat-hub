from datetime import date
from decimal import Decimal

from sqlalchemy import select

from aeat_hub.dashboard import collect_dashboard, write_dashboard
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
    assert "Revisar calidad" in html
    assert html.count("<h2>Revisar calidad</h2>") == 0
    assert 'role="tablist"' in html
    assert 'role="tab"' in html
    assert 'aria-selected=' in html
    assert 'id="panel-revisar"' in html
    assert 'id="panel-libro"' in html
    assert 'id="panel-resumen"' in html
    assert ">Libro</button>" in html
    assert ">Resumen</button>" in html
    assert 'data-default-panel="revisar"' in html
    assert "dash-nav" not in html
    assert 'class="review-table"' in html
    assert "q-chip" in html
    assert "q-dot" in html
    assert "popovertarget=" in html
    assert "Confianza" in html
    assert "Como iría en la Renta" in html
    assert "Por mes" in html
    assert "Por rubro" in html
    assert "Acumulado del ejercicio" not in html
    assert "evo-hero" in html
    assert "data-copy=" in html
    assert "aeat-hub validar" in html
    assert "aeat-hub reclasificar" in html
    assert "aeat-hub reclasificar" in html and "Hogar" in html
    assert 'class="ledger-table"' in html
    assert "Desliza horizontalmente" in html
    assert 'class="funnel"' in html
    assert "Filtrar: Emisor" in html
    assert "Seleccionar todo" in html
    assert 'data-fg="emisor"' in html
    assert 'data-fg="estado"' in html
    assert 'data-fecha=' in html
    assert "Más filtros: emisor" not in html
    assert 'class="th-input"' not in html
    assert "Hogar" in html
    assert "rubro-code" not in html
    assert "CI.GAS." not in html
    assert "CI.MEJ." not in html
    assert "CI.ING." not in html
    assert "Exportar Excel" in html
    assert "download=" in html
    assert "aeat-hub export --actividad" not in html
    assert "reclasificar" in html
    assert "<script" in html.lower() or "IBERDROLA DEMO" in html
    assert "script src=" not in html
    assert "cdn." not in html
    assert html.count("<script") == 1


def test_dashboard_pop_confianza_cita_casilla(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    _seed_asientos(session, actividad)
    html = write_dashboard(session, layout, actividad, 2026).read_text(encoding="utf-8")
    assert "Otros gastos" in html or "casilla" in html.lower()
