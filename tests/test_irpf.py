from decimal import Decimal

from aeat_hub.fiscal.accounts import TIPO_GASTO, TIPO_INGRESO, TIPO_MEJORA
from aeat_hub.fiscal.irpf import casilla_clave, summarize_irpf, tipo_desde_casilla


class _Row:
    def __init__(self, cuenta, total, estado="confirmado"):
        self.cuenta_codigo = cuenta
        self.total = total
        self.estado = estado


def test_casilla_clave_mapea_hogar_luz_y_mejoras():
    assert casilla_clave("CI.GAS.HOGAR") == "otros"
    assert casilla_clave("CI.GAS.LUZ") == "suministros"
    assert casilla_clave("CI.MEJ.PVC") == "mejoras"
    assert casilla_clave(None) == "sin_clasificar"


def test_casilla_clave_respeta_extra_de_usuario():
    extra = {"CI.GAS.PINTURA": "reparacion"}
    assert casilla_clave("CI.GAS.PINTURA", extra) == "reparacion"
    assert casilla_clave("CI.GAS.PINTURA") == "sin_clasificar"


def test_tipo_desde_casilla():
    assert tipo_desde_casilla("ingresos") == TIPO_INGRESO
    assert tipo_desde_casilla("reparacion") == TIPO_GASTO
    assert tipo_desde_casilla("mejoras") == TIPO_MEJORA


def test_summarize_irpf_no_resta_mejoras_ni_duplicados():
    rows = [
        _Row("CI.ING.RENTA", Decimal("700.00")),
        _Row("CI.GAS.LUZ", Decimal("48.40")),
        _Row("CI.GAS.HOGAR", Decimal("31.45")),
        _Row("CI.MEJ.PVC", Decimal("1452.00")),
        _Row("CI.GAS.LUZ", Decimal("48.40"), estado="duplicado"),
    ]
    summary = summarize_irpf(rows)
    assert summary["ingresos"] == Decimal("700.00")
    assert summary["gastos_deducibles"] == Decimal("79.85")
    assert summary["mejoras"] == Decimal("1452.00")
    assert summary["rendimiento"] == Decimal("620.15")
    otros = next(item for item in summary["filas"] if item["clave"] == "otros")
    assert otros["n"] == 1
    assert otros["etiqueta"] == "Otros gastos"
