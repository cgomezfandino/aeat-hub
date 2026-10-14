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
    CasillaIRPF(
        "sin_clasificar",
        "Sin clasificar",
        "gasto",
        False,
        "No se computa hasta asignarle casilla: sin clasificar no es deducible.",
    ),
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


# Intereses y gastos de reparación y conservación: límite conjunto igual al
# rendimiento íntegro (art. 23.1.a.1º LIRPF). El pequeño mantenimiento
# ("otros") es conservación y entra en el mismo límite.
LIMITADOS_ART23 = ("intereses", "reparacion", "otros")


def summarize_irpf(
    asientos,
    extra: dict[str, str] | None = None,
    *,
    inmueble=None,
    ejercicio: int | None = None,
) -> dict:
    """Rendimiento del capital inmobiliario (art. 22-23 LIRPF) para la Renta.

    Ignora duplicados y rechazados. Aplica el límite de intereses +
    conservación con los excesos de los 4 años anteriores, la amortización
    del 3 % sobre la construcción y la reducción por arrendamiento de
    vivienda cuando el inmueble trae esos datos; si faltan, lo avisa.
    No presenta el modelo 100.
    """
    from aeat_hub.fiscal.normativa import para

    normativa = para(ejercicio) if ejercicio else None
    buckets: dict[str, dict] = {
        item.clave: {"meta": item, "n": 0, "total": ZERO} for item in CASILLAS_CI
    }
    mejoras_ano: list[tuple] = []
    for asiento in asientos:
        if getattr(asiento, "estado", None) in ("duplicado", "rechazado"):
            continue
        clave = casilla_clave(getattr(asiento, "cuenta_codigo", None), extra)
        if clave not in buckets:
            clave = "sin_clasificar"
        amount = q2(getattr(asiento, "total", None)) or ZERO
        buckets[clave]["n"] += 1
        buckets[clave]["total"] += amount
        if clave == "mejoras":
            mejoras_ano.append((getattr(asiento, "fecha", None), amount))

    avisos: list[str] = []
    ingresos = buckets["ingresos"]["total"]
    limitados = sum((buckets[c]["total"] for c in LIMITADOS_ART23), ZERO)
    otros_gastos = sum(
        (
            buckets[item.clave]["total"]
            for item in CASILLAS_CI
            if item.resta_del_ano and item.grupo == "gasto" and item.clave not in LIMITADOS_ART23
        ),
        ZERO,
    )

    # Límite art. 23.1.a.1º: primero los excesos pendientes (caducan), luego los del año
    disponible = max(ingresos, ZERO)
    pendientes = _excesos(inmueble, ejercicio, normativa)
    aplicados_anteriores = ZERO
    caducados = ZERO
    for ano, importe in pendientes:
        if ejercicio and normativa and ano < ejercicio - normativa.anos_arrastre_exceso:
            caducados += importe
            continue
        usado = min(importe, disponible)
        aplicados_anteriores += usado
        disponible -= usado
    limitados_aplicados = min(limitados, disponible)
    exceso_generado = limitados - limitados_aplicados
    if exceso_generado > 0:
        avisos.append(
            f"Intereses y conservación superan los ingresos: {exceso_generado} € se deducen en "
            "los 4 años siguientes (art. 23.1.a.1º LIRPF). Guárdalo en el inmueble."
        )
    if caducados > 0:
        avisos.append(f"{caducados} € de excesos de más de 4 años ya no se pueden deducir.")

    amortizacion_manual = buckets["amortizacion"]["total"]
    amortizacion, aviso_amort = _amortizacion(inmueble, ejercicio, normativa, mejoras_ano)
    if amortizacion_manual > 0:
        amortizacion = amortizacion_manual
        aviso_amort = "Amortización tomada de los asientos manuales (no se calcula aparte)."
    if aviso_amort:
        avisos.append(aviso_amort)

    gastos_deducibles = q2(otros_gastos + limitados_aplicados + aplicados_anteriores + amortizacion)
    rendimiento = q2(ingresos - gastos_deducibles)

    titularidad = getattr(inmueble, "porcentaje_titularidad", None) or Decimal("100")
    if titularidad != Decimal("100"):
        factor = titularidad / Decimal("100")
        avisos.append(f"Cotitularidad: importes al {titularidad} % que te corresponde.")
        ingresos, gastos_deducibles, rendimiento = (
            q2(ingresos * factor), q2(gastos_deducibles * factor), q2(rendimiento * factor),
        )

    reduccion_pct = getattr(inmueble, "reduccion_pct", None)
    uso = getattr(inmueble, "uso", "vivienda") or "vivienda"
    reduccion = ZERO
    if rendimiento > 0 and uso == "vivienda":
        if reduccion_pct is None:
            if inmueble is not None:
                avisos.append(
                    "Indica la reducción por alquiler de vivienda habitual (art. 23.2 LIRPF): "
                    "contratos desde 26/05/2023: 50 % general, 60 % rehabilitación reciente, "
                    "70 % joven o primera vez en zona tensionada, 90 % rebaja ≥5 % en zona tensionada; "
                    "contratos anteriores: 60 %."
                )
        else:
            reduccion = q2(rendimiento * reduccion_pct / Decimal("100"))

    filas = []
    for item in CASILLAS_CI:
        row = buckets[item.clave]
        total = row["total"]
        if item.clave == "amortizacion":
            total = amortizacion
        filas.append(
            {
                "clave": item.clave,
                "etiqueta": item.etiqueta,
                "grupo": item.grupo,
                "resta_del_ano": item.resta_del_ano,
                "notas": item.notas,
                "n": row["n"],
                "total": total,
            }
        )
    return {
        "filas": filas,
        "ingresos": ingresos,
        "gastos_deducibles": gastos_deducibles,
        "mejoras": buckets["mejoras"]["total"],
        "rendimiento": rendimiento,
        "limitados": limitados,
        "limitados_aplicados": limitados_aplicados,
        "excesos_aplicados": aplicados_anteriores,
        "exceso_generado": exceso_generado,
        "amortizacion": amortizacion,
        "reduccion_pct": reduccion_pct,
        "reduccion": reduccion,
        "rendimiento_reducido": q2(rendimiento - reduccion),
        "avisos": avisos,
    }


def _excesos(inmueble, ejercicio, normativa) -> list[tuple[int, Decimal]]:
    import json

    if inmueble is None or not ejercicio:
        return []
    try:
        datos = json.loads(getattr(inmueble, "excesos_anteriores", None) or "{}")
    except ValueError:
        return []
    filas = []
    for ano, importe in datos.items():
        try:
            filas.append((int(ano), q2(Decimal(str(importe)))))
        except (ValueError, ArithmeticError):
            continue
    return sorted((a, i) for a, i in filas if a < ejercicio and i and i > 0)


def _amortizacion(inmueble, ejercicio, normativa, mejoras_ano) -> tuple[Decimal, str | None]:
    """3 % sobre el mayor de coste o valor catastral, sin suelo (art. 14.2.a RIRPF)."""
    from datetime import date

    if inmueble is None or not ejercicio or normativa is None:
        return ZERO, None
    vc = getattr(inmueble, "valor_catastral", None)
    vcc = getattr(inmueble, "valor_catastral_construccion", None)
    if not vc or not vcc:
        return ZERO, (
            "Sin amortización: faltan el valor catastral y el de la construcción (recibo del IBI). "
            "Es un gasto deducible del 3 % anual sobre la construcción."
        )
    pct = normativa.amortizacion_inmueble_pct / Decimal("100")
    dias_ano = 366 if date(ejercicio, 12, 31).timetuple().tm_yday == 366 else 365
    dias = getattr(inmueble, "dias_arrendado", None) or dias_ano
    adquisicion = getattr(inmueble, "fecha_adquisicion", None)
    if adquisicion and adquisicion.year == ejercicio:
        dias = min(dias, (date(ejercicio, 12, 31) - adquisicion).days + 1)
    proporcion = vcc / vc
    coste = getattr(inmueble, "coste_adquisicion", None)
    base = max(coste or ZERO, vc) * proporcion + (getattr(inmueble, "mejoras_anteriores", None) or ZERO)
    importe = base * pct * Decimal(dias) / Decimal(dias_ano)
    for fecha, mejora in mejoras_ano:
        if fecha is None:
            continue
        dias_mejora = min(dias, (date(ejercicio, 12, 31) - fecha).days + 1)
        importe += mejora * pct * Decimal(dias_mejora) / Decimal(dias_ano)
    aviso = None
    if not coste:
        aviso = "Amortización sobre el valor catastral: indica el coste de adquisición si fue mayor."
    elif getattr(inmueble, "dias_arrendado", None) is None:
        aviso = "Amortización por el año completo: indica los días arrendados si no lo estuvo todo el año."
    return q2(importe), aviso
