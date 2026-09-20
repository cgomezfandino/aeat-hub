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
    casilla: str = ""


ACCOUNT_DEFS: tuple[AccountDef, ...] = (
    AccountDef("CI.ING.RENTA", "Alquiler", TIPO_INGRESO, REGIMEN_CI, casilla="ingresos"),
    AccountDef("CI.ING.INDEMN", "Indemnización", TIPO_INGRESO, REGIMEN_CI, casilla="ingresos"),
    AccountDef("CI.GAS.LUZ", "Luz", TIPO_GASTO, REGIMEN_CI, "Si lo paga el arrendador.", "suministros"),
    AccountDef("CI.GAS.AGUA", "Agua", TIPO_GASTO, REGIMEN_CI, "Si lo paga el arrendador.", "suministros"),
    AccountDef("CI.GAS.INTERNET", "Internet", TIPO_GASTO, REGIMEN_CI, "Si lo paga el arrendador.", "suministros"),
    AccountDef("CI.GAS.COMUNIDAD", "Comunidad", TIPO_GASTO, REGIMEN_CI, casilla="comunidad"),
    AccountDef("CI.GAS.SEGURO", "Seguro", TIPO_GASTO, REGIMEN_CI, casilla="seguros"),
    AccountDef("CI.GAS.IBI", "IBI", TIPO_GASTO, REGIMEN_CI, casilla="ibi"),
    AccountDef("CI.GAS.HOGAR", "Hogar", TIPO_GASTO, REGIMEN_CI, "Pequeño mantenimiento. Revisa si es mejora.", "otros"),
    AccountDef("CI.GAS.REPARACION", "Reparación", TIPO_GASTO, REGIMEN_CI, "Art. 23 LIRPF: mantener, no revalorizar.", "reparacion"),
    AccountDef("CI.GAS.INTERES", "Intereses", TIPO_GASTO, REGIMEN_CI, casilla="intereses"),
    AccountDef("CI.GAS.ADMIN", "Administración", TIPO_GASTO, REGIMEN_CI, casilla="admin"),
    AccountDef("CI.MEJ.PVC", "Ventanas", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.MEJ.SOLADO", "Suelo", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.MEJ.REVEST", "Revestimientos", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.MEJ.MO", "Mano de obra", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.MEJ.OTROS", "Otras mejoras", TIPO_MEJORA, REGIMEN_CI, "Se capitaliza. No es gasto del ejercicio.", "mejoras"),
    AccountDef("CI.AMO.INMUEBLE", "Amortización", TIPO_AMORT, REGIMEN_CI, "Normalmente 3 % sobre la construcción.", "amortizacion"),
    AccountDef("AE.ING.VENTAS", "Ingresos de explotación", TIPO_INGRESO, REGIMEN_AE),
    AccountDef("AE.GAS.COMPRAS", "Compras y servicios", TIPO_GASTO, REGIMEN_AE),
    AccountDef("AE.GAS.SUMINISTROS", "Suministros de la actividad", TIPO_GASTO, REGIMEN_AE),
    AccountDef("AE.GAS.SS", "Seguridad social del autónomo", TIPO_GASTO, REGIMEN_AE),
    AccountDef("AE.INV.BIENES", "Bienes de inversión", TIPO_MEJORA, REGIMEN_AE),
)

CODIGO_DEMO_CI = "CI-VA-001"


def cuentas_por_regimen(regimen: str) -> tuple[AccountDef, ...]:
    return tuple(item for item in ACCOUNT_DEFS if item.regimen == regimen)
