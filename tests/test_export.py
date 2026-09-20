from datetime import date
from decimal import Decimal

from openpyxl import load_workbook
from sqlalchemy import select

from aeat_hub.export import export_xlsx
from aeat_hub.models import Actividad, Asiento


def test_export_xlsx_crea_hojas(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
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
    session.commit()
    dest = export_xlsx(session, layout, actividad, 2026)
    assert dest.is_file()
    wb = load_workbook(dest)
    assert set(wb.sheetnames) >= {
        "Gastos",
        "Ingresos",
        "Mejoras",
        "Duplicados",
        "Reclasificar",
        "Resumen_rubro",
        "Resumen_inmueble",
    }
    gastos = list(wb["Gastos"].iter_rows(min_row=2, values_only=True))
    assert any(row[6] == "CI.GAS.LUZ" for row in gastos)
    ingresos = list(wb["Ingresos"].iter_rows(min_row=2, values_only=True))
    assert any(row[6] == "CI.ING.RENTA" for row in ingresos)
