"""Agrupación de cuentas del libro a conceptos de rendimientos de capital inmobiliario.

No presenta el modelo 100. Es un borrador de totales para copiar a la Renta.
Las mejoras no restan del ejercicio: se capitalizan.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aeat_hub.fiscal.money import q2

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class CasillaIRPF:
    clave: str
    etiqueta: str
    grupo: str
    resta_del_ano: bool
    notas: str = ""


CASILLAS_CI: tuple[CasillaIRPF, ...] = (
    CasillaIRPF(
        "ingresos",
        "Ingresos íntegros (rentas e indemnizaciones)",
        "ingreso",
        False,
        "Lo que cobras del inmueble en el ejercicio.",
    ),
    CasillaIRPF(
        "intereses",
        "Intereses y gastos de financiación",
        "gasto",
        True,
        "Hipoteca u otros capitales ajenos invertidos en el inmueble.",
    ),
    CasillaIRPF(
        "reparacion",
        "Conservación y reparación",
        "gasto",
        True,
        "Art. 23 LIRPF: mantener, no revalorizar.",
    ),
    CasillaIRPF("ibi", "IBI y tasas municipales", "gasto", True),
    CasillaIRPF("comunidad", "Comunidad de propietarios", "gasto", True),
    CasillaIRPF("seguros", "Seguros del inmueble / impago", "gasto", True),
    CasillaIRPF(
        "suministros",
        "Suministros (si los paga el arrendador)",
        "gasto",
        True,
        "Luz, agua, internet. No si los paga el inquilino.",
    ),
    CasillaIRPF("admin", "Administración, publicidad y defensa jurídica", "gasto", True),
    CasillaIRPF(
        "otros",
        "Otros gastos necesarios (hogar / mantenimiento)",
        "gasto",
        True,
        "Consumibles y pequeño mantenimiento. Revisa si no es una mejora.",
    ),
    CasillaIRPF(
        "amortizacion",
        "Amortización del inmueble",
        "amortizacion",
        True,
        "Normalmente 3 % sobre la construcción. Hoy se asienta a mano.",
    ),
    CasillaIRPF(
        "mejoras",
        "Mejoras (no restan del ejercicio)",
        "mejora",
        False,
        "Se suman al valor de adquisición y se amortizan.",
    ),
    CasillaIRPF("sin_clasificar", "Sin clasificar / pendiente de rubro", "gasto", True),
)

CUENTA_A_CASILLA: dict[str, str] = {
    "CI.ING.RENTA": "ingresos",
    "CI.ING.INDEMN": "ingresos",
    "CI.GAS.INTERES": "intereses",
    "CI.GAS.REPARACION": "reparacion",
    "CI.GAS.IBI": "ibi",
    "CI.GAS.COMUNIDAD": "comunidad",
    "CI.GAS.SEGURO": "seguros",
    "CI.GAS.LUZ": "suministros",
    "CI.GAS.AGUA": "suministros",
    "CI.GAS.INTERNET": "suministros",
    "CI.GAS.ADMIN": "admin",
    "CI.GAS.HOGAR": "otros",
    "CI.AMO.INMUEBLE": "amortizacion",
}

INDEX_CI = {item.clave: item for item in CASILLAS_CI}

RUBRO_CHIPS: tuple[tuple[str, str, str], ...] = (
    ("CI.GAS.HOGAR", "Hogar", "Confirmar como pequeño mantenimiento"),
    ("CI.GAS.REPARACION", "Reparación", "Conservación del año (no revaloriza)"),
    ("CI.MEJ.OTROS", "Mejora", "Se capitaliza; no resta del rendimiento"),
)


def casilla_clave(cuenta_codigo: str | None) -> str:
    if not cuenta_codigo:
        return "sin_clasificar"
    if cuenta_codigo.startswith("CI.MEJ."):
        return "mejoras"
    return CUENTA_A_CASILLA.get(cuenta_codigo, "sin_clasificar")


def summarize_irpf(asientos) -> dict:
    """Totales por casilla. Ignora duplicados. El rendimiento no resta mejoras."""
    buckets: dict[str, dict] = {
        item.clave: {"meta": item, "n": 0, "total": ZERO} for item in CASILLAS_CI
    }
    for asiento in asientos:
        if getattr(asiento, "estado", None) == "duplicado":
            continue
        clave = casilla_clave(getattr(asiento, "cuenta_codigo", None))
        if clave not in buckets:
            clave = "sin_clasificar"
        amount = q2(getattr(asiento, "total", None)) or ZERO
        buckets[clave]["n"] += 1
        buckets[clave]["total"] += amount

    filas = []
    ingresos = buckets["ingresos"]["total"]
    gastos_deducibles = ZERO
    for item in CASILLAS_CI:
        row = buckets[item.clave]
        if item.resta_del_ano and item.grupo != "ingreso":
            gastos_deducibles += row["total"]
        filas.append(
            {
                "clave": item.clave,
                "etiqueta": item.etiqueta,
                "grupo": item.grupo,
                "resta_del_ano": item.resta_del_ano,
                "notas": item.notas,
                "n": row["n"],
                "total": row["total"],
            }
        )
    rendimiento = ingresos - gastos_deducibles
    return {
        "filas": filas,
        "ingresos": ingresos,
        "gastos_deducibles": gastos_deducibles,
        "mejoras": buckets["mejoras"]["total"],
        "rendimiento": rendimiento,
    }
