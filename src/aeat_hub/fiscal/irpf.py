"""Agrupación de cuentas del libro a conceptos de rendimientos de capital inmobiliario.

No presenta el modelo 100. Es un borrador de totales para copiar a la Renta.
Las mejoras no restan del ejercicio: se capitalizan.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aeat_hub.fiscal.accounts import (
    ACCOUNT_DEFS,
    TIPO_AMORT,
    TIPO_GASTO,
    TIPO_INGRESO,
    TIPO_MEJORA,
)
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
        "Ingresos",
        "ingreso",
        False,
        "Lo que cobras del inmueble en el ejercicio.",
    ),
    CasillaIRPF(
        "intereses",
        "Intereses",
        "gasto",
        True,
        "Hipoteca u otros capitales ajenos invertidos en el inmueble.",
    ),
    CasillaIRPF(
        "reparacion",
        "Reparación",
        "gasto",
        True,
        "Art. 23 LIRPF: mantener, no revalorizar.",
    ),
    CasillaIRPF("ibi", "IBI", "gasto", True),
    CasillaIRPF("comunidad", "Comunidad", "gasto", True),
    CasillaIRPF("seguros", "Seguros", "gasto", True),
    CasillaIRPF(
        "suministros",
        "Suministros",
        "gasto",
        True,
        "Luz, agua, internet. No si los paga el inquilino.",
    ),
    CasillaIRPF("admin", "Administración", "gasto", True),
    CasillaIRPF(
        "otros",
        "Otros gastos",
        "gasto",
        True,
        "Consumibles y pequeño mantenimiento. Revisa si no es una mejora.",
    ),
    CasillaIRPF(
        "amortizacion",
        "Amortización",
        "amortizacion",
        True,
        "Normalmente 3 % sobre la construcción. Hoy se asienta a mano.",
    ),
    CasillaIRPF(
        "mejoras",
        "Mejoras",
        "mejora",
        False,
        "Se suman al valor de adquisición y se amortizan.",
    ),
    CasillaIRPF("sin_clasificar", "Sin clasificar", "gasto", True),
)

INDEX_CI = {item.clave: item for item in CASILLAS_CI}

RUBRO_CHIPS: tuple[tuple[str, str, str], ...] = (
    ("Hogar", "Hogar", "Confirmar como pequeño mantenimiento"),
    ("Reparación", "Reparación", "Conservación del año (no revaloriza)"),
    ("Otras mejoras", "Mejora", "Se capitaliza; no resta del rendimiento"),
)


def casillas_catalogo() -> dict[str, str]:
    return {item.codigo: item.casilla for item in ACCOUNT_DEFS if item.casilla}


def casilla_clave(cuenta_codigo: str | None, extra: dict[str, str] | None = None) -> str:
    if not cuenta_codigo:
        return "sin_clasificar"
    lookup = {**casillas_catalogo(), **(extra or {})}
    return lookup.get(cuenta_codigo) or "sin_clasificar"


def tipo_desde_casilla(clave: str) -> str:
    if clave == "ingresos":
        return TIPO_INGRESO
    if clave == "mejoras":
        return TIPO_MEJORA
    if clave == "amortizacion":
        return TIPO_AMORT
    return TIPO_GASTO


def summarize_irpf(asientos, extra: dict[str, str] | None = None) -> dict:
    """Totales por casilla. Ignora duplicados. El rendimiento no resta mejoras."""
    buckets: dict[str, dict] = {
        item.clave: {"meta": item, "n": 0, "total": ZERO} for item in CASILLAS_CI
    }
    for asiento in asientos:
        if getattr(asiento, "estado", None) == "duplicado":
            continue
        clave = casilla_clave(getattr(asiento, "cuenta_codigo", None), extra)
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
