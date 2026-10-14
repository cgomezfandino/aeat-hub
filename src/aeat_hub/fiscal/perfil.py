"""Perfil fiscal de una actividad: regímenes de IRPF e IVA y datos de cálculo.

Lo que la persona no ha rellenado se completa con un valor por defecto
razonable para su régimen, pero **queda anotado** en `por_defecto` para que
la interfaz y los borradores avisen de que el perfil está incompleto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from aeat_hub.fiscal.accounts import REGIMEN_CI

# IRPF (art. 28-31 LIRPF; capital inmobiliario art. 22-23)
IRPF_ED_NORMAL = "estimacion_directa_normal"
IRPF_ED_SIMPLIFICADA = "estimacion_directa_simplificada"
IRPF_EO = "estimacion_objetiva"
IRPF_CAPITAL_INMOBILIARIO = "capital_inmobiliario"
REGIMENES_IRPF = (IRPF_ED_NORMAL, IRPF_ED_SIMPLIFICADA, IRPF_EO, IRPF_CAPITAL_INMOBILIARIO)

# IVA (LIVA)
IVA_GENERAL = "general"
IVA_RECARGO = "recargo_equivalencia"  # art. 148-163 LIVA
IVA_SIMPLIFICADO = "simplificado"  # art. 122-123 LIVA
IVA_EXENTO = "exento"  # art. 20 LIVA (vivienda, sanidad, enseñanza…)
IVA_CRITERIO_CAJA = "criterio_caja"  # art. 163 decies LIVA
IVA_REAGYP = "reagyp"  # art. 124-134 LIVA
REGIMENES_IVA = (IVA_GENERAL, IVA_RECARGO, IVA_SIMPLIFICADO, IVA_EXENTO, IVA_CRITERIO_CAJA, IVA_REAGYP)

TERRITORIOS = ("comun", "canarias", "ceuta_melilla", "foral")


@dataclass(frozen=True)
class Perfil:
    regimen_irpf: str
    regimen_iva: str
    territorio: str
    epigrafe_iae: str | None
    fecha_alta: date | None
    afectacion_vivienda_pct: Decimal | None
    rendimiento_anterior: Decimal | None
    por_defecto: tuple[str, ...] = field(default_factory=tuple)
    avisos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def deduce_iva(self) -> bool:
        """¿Liquida IVA y deduce el soportado? (no en exento, RE ni capital inmobiliario de vivienda)."""
        return self.regimen_iva in (IVA_GENERAL, IVA_SIMPLIFICADO, IVA_CRITERIO_CAJA)

    @property
    def presenta_303(self) -> bool:
        return self.regimen_iva in (IVA_GENERAL, IVA_SIMPLIFICADO, IVA_CRITERIO_CAJA)

    @property
    def presenta_130(self) -> bool:
        return self.regimen_irpf in (IRPF_ED_NORMAL, IRPF_ED_SIMPLIFICADA)


def perfil_de(actividad) -> Perfil:
    por_defecto: list[str] = []
    avisos: list[str] = []

    regimen_irpf = getattr(actividad, "regimen_irpf", None)
    if not regimen_irpf:
        if actividad.regimen == REGIMEN_CI:
            regimen_irpf = IRPF_CAPITAL_INMOBILIARIO
        else:
            regimen_irpf = IRPF_ED_SIMPLIFICADA
            por_defecto.append("regimen_irpf")

    regimen_iva = getattr(actividad, "regimen_iva", None)
    if not regimen_iva:
        if regimen_irpf == IRPF_CAPITAL_INMOBILIARIO:
            usos = {getattr(item, "uso", "vivienda") for item in getattr(actividad, "inmuebles", []) or []}
            if usos and usos != {"vivienda"}:
                # el alquiler de locales está sujeto y no exento (art. 20.Uno.23 LIVA solo exime vivienda)
                regimen_iva = IVA_GENERAL
                avisos.append("Hay inmuebles que no son vivienda: su alquiler lleva IVA (21 %) y retención.")
            else:
                regimen_iva = IVA_EXENTO
        else:
            regimen_iva = IVA_GENERAL
        por_defecto.append("regimen_iva")

    if regimen_irpf in (IRPF_ED_NORMAL, IRPF_ED_SIMPLIFICADA, IRPF_EO) and not getattr(
        actividad, "epigrafe_iae", None
    ):
        por_defecto.append("epigrafe_iae")
    if regimen_irpf == IRPF_EO:
        avisos.append(
            "Estimación objetiva (módulos): el rendimiento no sale de los gastos; "
            "los borradores de IRPF no aplican."
        )
    territorio = getattr(actividad, "territorio", None) or "comun"
    if territorio == "foral":
        avisos.append("Territorio foral (País Vasco, Navarra): normativa propia no soportada.")
    elif territorio != "comun":
        avisos.append(f"Territorio {territorio}: IGIC/IPSI en lugar de IVA; el borrador 303 no aplica.")

    return Perfil(
        regimen_irpf=regimen_irpf,
        regimen_iva=regimen_iva,
        territorio=territorio,
        epigrafe_iae=getattr(actividad, "epigrafe_iae", None),
        fecha_alta=getattr(actividad, "fecha_alta", None),
        afectacion_vivienda_pct=getattr(actividad, "afectacion_vivienda_pct", None),
        rendimiento_anterior=getattr(actividad, "rendimiento_anterior", None),
        por_defecto=tuple(por_defecto),
        avisos=tuple(avisos),
    )
