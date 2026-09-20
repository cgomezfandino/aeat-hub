"""Plan de cuentas: capital inmobiliario (Valladolid) y stubs de actividad económica."""

from __future__ import annotations

from dataclasses import dataclass

REGIMEN_CI = "capital_inmobiliario"
REGIMEN_AE = "actividad_economica"
TIPO_INGRESO = "ingreso"
TIPO_GASTO = "gasto"
TIPO_MEJORA = "mejora"
TIPO_AMORT = "amortizacion"


@dataclass(frozen=True)
class AccountDef:
    codigo: str
    nombre: str
    tipo: str
    regimen: str
    notas: str = ""


ACCOUNT_DEFS: tuple[AccountDef, ...] = (
    AccountDef("CI.ING.RENTA", "Rentas de alquiler", TIPO_INGRESO, REGIMEN_CI),
    AccountDef(
        "CI.ING.INDEMN",
        "Indemnizaciones (resolución, daños repercutidos)",
        TIPO_INGRESO,
        REGIMEN_CI,
    ),
    AccountDef(
        "CI.GAS.LUZ",
        "Suministro eléctrico (si lo paga el arrendador)",
        TIPO_GASTO,
        REGIMEN_CI,
    ),
    AccountDef("CI.GAS.AGUA", "Suministro de agua (si lo paga el arrendador)", TIPO_GASTO, REGIMEN_CI),
    AccountDef(
        "CI.GAS.INTERNET",
        "Internet / telecomunicaciones (si lo paga el arrendador)",
        TIPO_GASTO,
        REGIMEN_CI,
    ),
    AccountDef("CI.GAS.COMUNIDAD", "Comunidad de propietarios", TIPO_GASTO, REGIMEN_CI),
    AccountDef("CI.GAS.SEGURO", "Seguros del inmueble / impago", TIPO_GASTO, REGIMEN_CI),
    AccountDef("CI.GAS.IBI", "IBI y tasas municipales", TIPO_GASTO, REGIMEN_CI),
    AccountDef(
        "CI.GAS.HOGAR",
        "Consumibles y pequeño mantenimiento del hogar",
        TIPO_GASTO,
        REGIMEN_CI,
    ),
    AccountDef(
        "CI.GAS.REPARACION",
        "Conservación y reparación (no mejora)",
        TIPO_GASTO,
        REGIMEN_CI,
        "Art. 23 LIRPF: mantener, no revalorizar.",
    ),
    AccountDef("CI.GAS.INTERES", "Intereses de financiación", TIPO_GASTO, REGIMEN_CI),
    AccountDef("CI.GAS.ADMIN", "Administración, publicidad, defensa jurídica", TIPO_GASTO, REGIMEN_CI),
    AccountDef(
        "CI.MEJ.PVC",
        "Mejora: carpintería / ventanas PVC",
        TIPO_MEJORA,
        REGIMEN_CI,
        "Se capitaliza y se amortiza. No es gasto del ejercicio.",
    ),
    AccountDef("CI.MEJ.SOLADO", "Mejora: solado / tarima / pavimento", TIPO_MEJORA, REGIMEN_CI),
    AccountDef("CI.MEJ.REVEST", "Mejora: revestimientos", TIPO_MEJORA, REGIMEN_CI),
    AccountDef("CI.MEJ.MO", "Mejora: mano de obra asociada", TIPO_MEJORA, REGIMEN_CI),
    AccountDef("CI.MEJ.OTROS", "Mejora: otras inversiones en el inmueble", TIPO_MEJORA, REGIMEN_CI),
    AccountDef(
        "CI.AMO.INMUEBLE",
        "Amortización del inmueble",
        TIPO_AMORT,
        REGIMEN_CI,
        "Normalmente 3 % sobre la construcción.",
    ),
    AccountDef("AE.ING.VENTAS", "Ingresos de explotación", TIPO_INGRESO, REGIMEN_AE),
    AccountDef("AE.GAS.COMPRAS", "Compras y servicios", TIPO_GASTO, REGIMEN_AE),
    AccountDef("AE.GAS.SUMINISTROS", "Suministros de la actividad", TIPO_GASTO, REGIMEN_AE),
    AccountDef("AE.GAS.SS", "Seguridad social del autónomo", TIPO_GASTO, REGIMEN_AE),
    AccountDef("AE.INV.BIENES", "Bienes de inversión", TIPO_MEJORA, REGIMEN_AE),
)

CODIGO_DEMO_CI = "CI-VA-001"


def cuentas_por_regimen(regimen: str) -> tuple[AccountDef, ...]:
    return tuple(item for item in ACCOUNT_DEFS if item.regimen == regimen)
