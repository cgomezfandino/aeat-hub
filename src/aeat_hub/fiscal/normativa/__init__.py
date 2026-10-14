"""Parámetros fiscales por ejercicio, versionados y con su fuente.

La lógica nunca lleva tipos, límites ni números de casilla escritos a mano:
los pide aquí con `para(ejercicio)`. Cada ejercicio vive en su módulo
(`e2025.py`…) y declara si sus datos están verificados contra la fuente
oficial. Un ejercicio sin módulo usa el último anterior y lo dice
(`verificado=False`), para que ningún borrador parezca más seguro de lo que es.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class Casillas303:
    """Casillas (base, tipo, cuota) del IVA devengado por tipo impositivo."""

    devengado: dict[Decimal, tuple[str, str, str]]
    recargo: dict[Decimal, tuple[str, str, str]]
    adq_intracomunitarias: tuple[str, str] = ("10", "11")
    isp_otras: tuple[str, str] = ("12", "13")
    modificacion: tuple[str, str] = ("14", "15")
    total_devengado: str = "27"
    deducible_corrientes: tuple[str, str] = ("28", "29")
    deducible_inversion: tuple[str, str] = ("30", "31")
    deducible_intracom_corrientes: tuple[str, str] = ("36", "37")
    deducible_intracom_inversion: tuple[str, str] = ("38", "39")
    rectificacion_deducciones: tuple[str, str] = ("40", "41")
    total_deducir: str = "45"
    resultado_general: str = "46"
    entregas_intracomunitarias: str = "59"
    exportaciones: str = "60"
    no_sujetas_localizacion: str = "120"
    isp_emitidas: str = "122"


@dataclass(frozen=True)
class Normativa:
    ejercicio: int
    verificado: bool
    fuentes: tuple[str, ...]
    # IVA
    tipos_iva: tuple[Decimal, ...]
    tipos_recargo: dict[Decimal, Decimal]  # tipo IVA -> tipo RE
    casillas_303: Casillas303
    umbral_bien_inversion: Decimal  # art. 108 LIVA
    presuncion_vehiculo_iva: Decimal  # art. 95.Tres.2ª LIVA
    # IRPF actividades
    pago_fraccionado_130: Decimal  # art. 110.1.a RIRPF
    minoracion_130: tuple[tuple[Decimal, Decimal], ...]  # (rendimiento anterior hasta, € por trimestre)
    dificil_justificacion_pct: Decimal  # art. 30.2.4ª RIRPF
    dificil_justificacion_limite: Decimal
    suministros_vivienda_pct: Decimal  # art. 30.2.5ª.b LIRPF
    manutencion_espana: Decimal  # art. 9 RIRPF, sin pernocta
    manutencion_extranjero: Decimal
    # Declaraciones informativas
    umbral_347: Decimal
    retencion_profesional: Decimal
    retencion_profesional_inicio: Decimal
    retencion_arrendamiento: Decimal
    avisos: tuple[str, ...] = field(default_factory=tuple)
    # Capital inmobiliario
    amortizacion_inmueble_pct: Decimal = Decimal("3")  # art. 14.2.a RIRPF
    anos_arrastre_exceso: int = 4  # art. 23.1.a.1º LIRPF


def para(ejercicio: int) -> Normativa:
    from aeat_hub.fiscal.normativa import e2024, e2025, e2026

    disponibles = {item.NORMATIVA.ejercicio: item.NORMATIVA for item in (e2024, e2025, e2026)}
    if ejercicio in disponibles:
        return disponibles[ejercicio]
    anteriores = [year for year in disponibles if year < ejercicio]
    base = disponibles[max(anteriores)] if anteriores else disponibles[min(disponibles)]
    return replace(
        base,
        ejercicio=ejercicio,
        verificado=False,
        avisos=base.avisos
        + (
            f"Parámetros de {ejercicio} no verificados: se usan los de {base.ejercicio}. "
            "Revisa tipos, límites y casillas antes de presentar.",
        ),
    )
