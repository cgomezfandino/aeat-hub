"""Plan de cuentas: capital inmobiliario (Valladolid) y stubs de actividad económica."""

from __future__ import annotations

import unicodedata
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
    # Actividad económica: la `casilla` es la partida de gastos/ingresos de la
    # estimación directa (modelo 100, rendimientos de actividades).
    AccountDef("AE.ING.VENTAS", "Ingresos de explotación", TIPO_INGRESO, REGIMEN_AE, casilla="ingresos_explotacion"),
    AccountDef("AE.ING.OTROS", "Otros ingresos", TIPO_INGRESO, REGIMEN_AE, casilla="otros_ingresos"),
    AccountDef("AE.ING.SUBVENCION", "Subvenciones", TIPO_INGRESO, REGIMEN_AE, casilla="otros_ingresos"),
    AccountDef("AE.GAS.COMPRAS", "Compras y consumos", TIPO_GASTO, REGIMEN_AE, "Mercaderías, materias primas y materiales.", "consumos"),
    AccountDef("AE.GAS.SUELDOS", "Sueldos y salarios", TIPO_GASTO, REGIMEN_AE, casilla="sueldos"),
    AccountDef("AE.GAS.SSEMPRESA", "Seguridad social a cargo de la empresa", TIPO_GASTO, REGIMEN_AE, casilla="ss_empresa"),
    AccountDef("AE.GAS.SS", "Seguridad social del autónomo", TIPO_GASTO, REGIMEN_AE, "Cuota RETA del titular.", "ss_titular"),
    AccountDef("AE.GAS.ALQUILER", "Arrendamientos y cánones", TIPO_GASTO, REGIMEN_AE, "Alquiler de local: retención del 19 % (modelo 115).", "arrendamientos"),
    AccountDef("AE.GAS.REPARACION", "Reparaciones y conservación", TIPO_GASTO, REGIMEN_AE, casilla="reparaciones"),
    AccountDef("AE.GAS.SUMINISTROS", "Suministros del local", TIPO_GASTO, REGIMEN_AE, casilla="suministros"),
    AccountDef("AE.GAS.SUMVIVIENDA", "Suministros de la vivienda afecta", TIPO_GASTO, REGIMEN_AE, "Art. 30.2.5ª LIRPF: 30 % × % afecto.", "suministros"),
    AccountDef("AE.GAS.PROFESIONALES", "Servicios de profesionales independientes", TIPO_GASTO, REGIMEN_AE, "Asesoría, abogados… con retención (modelo 111).", "servicios_profesionales"),
    AccountDef("AE.GAS.SERVICIOS", "Otros servicios exteriores", TIPO_GASTO, REGIMEN_AE, "Software, telefonía, publicidad, transporte.", "otros_servicios"),
    AccountDef("AE.GAS.SEGUROS", "Primas de seguros", TIPO_GASTO, REGIMEN_AE, casilla="otros_servicios"),
    AccountDef("AE.GAS.VEHICULO", "Vehículo", TIPO_GASTO, REGIMEN_AE, "IVA 50 % presunto; IRPF solo con afectación exclusiva.", "otros_servicios"),
    AccountDef("AE.GAS.MANUTENCION", "Manutención", TIPO_GASTO, REGIMEN_AE, "Pago electrónico y límites del art. 9 RIRPF.", "otros_gastos"),
    AccountDef("AE.GAS.TRIBUTOS", "Tributos deducibles", TIPO_GASTO, REGIMEN_AE, "IAE, IBI del local, tasas. No el IRPF.", "tributos"),
    AccountDef("AE.GAS.FINANCIEROS", "Gastos financieros", TIPO_GASTO, REGIMEN_AE, casilla="financieros"),
    AccountDef("AE.GAS.OTROS", "Otros gastos deducibles", TIPO_GASTO, REGIMEN_AE, casilla="otros_gastos"),
    AccountDef("AE.GAS.NODEDUCIBLE", "No deducible", TIPO_GASTO, REGIMEN_AE, "Multas, sanciones, donativos, gastos personales.", "no_deducible"),
    AccountDef("AE.INV.BIENES", "Bienes de inversión", TIPO_MEJORA, REGIMEN_AE, "Se amortizan; IVA en casillas 30-31.", "bienes_inversion"),
    AccountDef("AE.AMO.INMOVILIZADO", "Amortización", TIPO_AMORT, REGIMEN_AE, "Tabla de coeficientes de la estimación directa.", "amortizacion"),
)

CODIGO_DEMO_CI = "CI-VA-001"


def cuentas_por_regimen(regimen: str) -> tuple[AccountDef, ...]:
    return tuple(item for item in ACCOUNT_DEFS if item.regimen == regimen)


def slug_cuenta(nombre: str) -> str:
    decomposed = unicodedata.normalize("NFKD", nombre)
    ascii_name = decomposed.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_name.upper() if ch.isalnum())


def prefijo_codigo(tipo: str, regimen: str) -> str:
    if regimen == REGIMEN_AE:
        return {"ingreso": "AE.ING", "gasto": "AE.GAS", "mejora": "AE.INV", "amortizacion": "AE.AMO"}.get(
            tipo, "AE.GAS"
        )
    return {
        "ingreso": "CI.ING",
        "gasto": "CI.GAS",
        "mejora": "CI.MEJ",
        "amortizacion": "CI.AMO",
    }[tipo]


def codigo_interno(nombre: str, tipo: str, regimen: str, ocupados: set[str]) -> str:
    prefix = prefijo_codigo(tipo, regimen)
    slug = slug_cuenta(nombre) or "RUBRO"
    base = f"{prefix}.{slug}"[:32]
    if base not in ocupados:
        return base
    for n in range(2, 1000):
        suffix = str(n)
        stem = base[: 32 - len(suffix)]
        candidate = f"{stem}{suffix}"
        if candidate not in ocupados:
            return candidate
    raise RuntimeError("No hay identificador interno libre para ese rubro.")
