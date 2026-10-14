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


# --- Art. 23 LIRPF: límite, amortización y reducción --------------------------

from dataclasses import dataclass
from datetime import date


@dataclass
class _Inm:
    valor_catastral: Decimal | None = None
    valor_catastral_construccion: Decimal | None = None
    coste_adquisicion: Decimal | None = None
    mejoras_anteriores: Decimal | None = None
    fecha_adquisicion: date | None = None
    dias_arrendado: int | None = None
    reduccion_pct: Decimal | None = None
    excesos_anteriores: str = "{}"
    porcentaje_titularidad: Decimal = Decimal("100")
    uso: str = "vivienda"


class _Fila(_Row):
    def __init__(self, cuenta, total, fecha=None):
        super().__init__(cuenta, total)
        self.fecha = fecha


def test_limite_art23_con_excesos_y_amortizacion():
    """Calculado a mano.

    Ingresos 6.000. Intereses 4.000 + reparación 2.500 + pequeño mantenimiento 300 = 6.800.
    Exceso de 2024 (1.000) se aplica primero; el de 2021 caducó (más de 4 años).
    Disponible tras el exceso: 5.000 → se aplican 5.000; exceso nuevo 1.800.
    Amortización: max(150.000, 100.000) × 40 % construcción = 60.000 + 5.000 mejoras
    anteriores = 65.000 × 3 % = 1.950; mejora de 1.000 el 2 jul → 1.000 × 3 % × 183/365 = 15,04.
    Otros gastos: IBI 400 + comunidad 600 + seguro 200 = 1.200.
    Gastos = 1.200 + 5.000 + 1.000 + 1.965,04 = 9.165,04 → rendimiento −3.165,04.
    """
    rows = [
        _Fila("CI.ING.RENTA", Decimal("6000")),
        _Fila("CI.GAS.INTERES", Decimal("4000")),
        _Fila("CI.GAS.REPARACION", Decimal("2500")),
        _Fila("CI.GAS.HOGAR", Decimal("300")),
        _Fila("CI.GAS.IBI", Decimal("400")),
        _Fila("CI.GAS.COMUNIDAD", Decimal("600")),
        _Fila("CI.GAS.SEGURO", Decimal("200")),
        _Fila("CI.MEJ.PVC", Decimal("1000"), fecha=date(2026, 7, 2)),
    ]
    inmueble = _Inm(
        valor_catastral=Decimal("100000"), valor_catastral_construccion=Decimal("40000"),
        coste_adquisicion=Decimal("150000"), mejoras_anteriores=Decimal("5000"),
        dias_arrendado=365, excesos_anteriores='{"2021": "500", "2024": "1000"}',
    )
    r = summarize_irpf(rows, inmueble=inmueble, ejercicio=2026)
    assert r["excesos_aplicados"] == Decimal("1000")
    assert r["limitados_aplicados"] == Decimal("5000")
    assert r["exceso_generado"] == Decimal("1800")
    assert r["amortizacion"] == Decimal("1965.04")
    assert r["gastos_deducibles"] == Decimal("9165.04")
    assert r["rendimiento"] == Decimal("-3165.04")
    assert r["reduccion"] == Decimal("0.00")  # solo sobre rendimiento positivo
    assert any("caducado" in a or "ya no se pueden" in a for a in r["avisos"])


def test_reduccion_por_alquiler_de_vivienda_y_cotitularidad():
    rows = [_Fila("CI.ING.RENTA", Decimal("12000")), _Fila("CI.GAS.IBI", Decimal("400"))]
    r = summarize_irpf(
        rows, inmueble=_Inm(reduccion_pct=Decimal("50"), porcentaje_titularidad=Decimal("50")), ejercicio=2026
    )
    # 50 % de titularidad: 5.800 de rendimiento; reducción del 50 %: 2.900
    assert r["rendimiento"] == Decimal("5800.00")
    assert r["reduccion"] == Decimal("2900.00")
    assert r["rendimiento_reducido"] == Decimal("2900.00")
    assert any("valor catastral" in a for a in r["avisos"])


def test_sin_inmueble_se_mantiene_el_resumen_simple():
    r = summarize_irpf([_Fila("CI.ING.RENTA", Decimal("700")), _Fila("CI.GAS.LUZ", Decimal("48.40"))])
    assert r["rendimiento"] == Decimal("651.60")
    assert r["amortizacion"] == Decimal("0.00")


def test_patch_inmueble_valida(session):
    import pytest

    from aeat_hub.services import patch_inmueble

    data = patch_inmueble(
        session, "CI-VA-001",
        {"valor_catastral": "100.000,00", "valor_catastral_construccion": "40000", "reduccion_pct": "60",
         "excesos": {"2024": "1000"}},
    )
    assert data["valor_catastral"] == Decimal("100000.00")
    assert '"2024": "1000.00"' in data["excesos_anteriores"]
    with pytest.raises(ValueError, match="0, 50, 60, 70 o 90"):
        patch_inmueble(session, "CI-VA-001", {"reduccion_pct": "45"})
    with pytest.raises(ValueError, match="no puede superar"):
        patch_inmueble(session, "CI-VA-001", {"valor_catastral_construccion": "200000"})
