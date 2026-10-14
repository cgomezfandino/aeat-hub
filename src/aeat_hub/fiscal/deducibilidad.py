"""Cuánto IVA se deduce y cuánto gasto computa en IRPF, factura a factura.

IVA e IRPF van por separado porque la ley los trata distinto: un vehículo
deduce el 50 % del IVA por presunción (art. 95 LIVA) y, sin afectación
exclusiva, nada de gasto en IRPF (art. 22.2 RIRPF). El IVA que no se deduce
pero corresponde a un gasto afecto es mayor gasto en IRPF.

Cada decisión deja una `Regla` con su cita: los borradores de modelos
explican de dónde sale cada importe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from aeat_hub.fiscal.accounts import TIPO_AMORT, TIPO_INGRESO, TIPO_MEJORA
from aeat_hub.fiscal.money import q2
from aeat_hub.fiscal.nif import is_placeholder_nif, normalize_nif
from aeat_hub.fiscal.normativa import Normativa
from aeat_hub.fiscal.perfil import IRPF_EO, Perfil

CIEN = Decimal("100")
CERO = Decimal("0.00")

CUENTA_VEHICULO = "AE.GAS.VEHICULO"
CUENTA_SUM_VIVIENDA = "AE.GAS.SUMVIVIENDA"
CUENTA_MANUTENCION = "AE.GAS.MANUTENCION"
CUENTA_NO_DEDUCIBLE = "AE.GAS.NODEDUCIBLE"


@dataclass(frozen=True)
class Regla:
    codigo: str
    texto: str
    cita: str = ""


@dataclass
class Deducibilidad:
    pct_iva: Decimal
    pct_gasto: Decimal
    iva_soportado: Decimal
    iva_deducible: Decimal
    importe_irpf: Decimal  # gasto deducible o ingreso computable
    es_ingreso: bool
    reglas: list[Regla] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _campo(item, nombre):
    return item.get(nombre) if isinstance(item, dict) else getattr(item, nombre, None)


def _cuota_iva(asiento) -> Decimal:
    if _campo(asiento, "iva_cuota") is not None:
        return _campo(asiento, "iva_cuota")
    filas = _campo(asiento, "desglose_iva") or []
    return sum((_campo(f, "cuota") or CERO for f in filas), CERO)


def evaluar(asiento, perfil: Perfil, normativa: Normativa, *, titular_nif: str | None) -> Deducibilidad:
    tipo = _campo(asiento, "tipo")
    cuenta = _campo(asiento, "cuenta_codigo")
    base = _campo(asiento, "base")
    iva = _cuota_iva(asiento)
    recargo = _campo(asiento, "recargo_cuota") or CERO
    total = _campo(asiento, "total") or CERO
    retencion = _campo(asiento, "retencion_cuota") or CERO
    reglas: list[Regla] = []
    avisos: list[str] = []

    if base is None:
        # sin base no se puede separar el IVA: se trabaja con el bruto
        base = total + retencion - iva - recargo
        avisos.append("Sin base imponible leída: se toma el total como base; revisa la factura.")

    if tipo == TIPO_INGRESO:
        if perfil.deduce_iva:
            importe = base
            reglas.append(Regla("ingreso_base", "Computa la base: el IVA repercutido no es ingreso.", "art. 28 LIRPF"))
        else:
            importe = base + iva
            reglas.append(
                Regla(
                    "ingreso_bruto",
                    "Sin liquidación de IVA (exento, recargo o capital inmobiliario): computa el importe cobrado.",
                    "art. 23 y 28 LIRPF",
                )
            )
        return Deducibilidad(CERO, CIEN, iva, CERO, q2(importe), True, reglas, avisos)

    pct_iva = CIEN if perfil.deduce_iva else CERO
    pct_gasto = CIEN
    if not perfil.deduce_iva and iva:
        reglas.append(
            Regla(
                "iva_no_deducible_regimen",
                f"Régimen de IVA «{perfil.regimen_iva}»: el IVA soportado no se deduce y es mayor gasto.",
                "art. 94 y 154 LIVA",
            )
        )

    if tipo in (TIPO_MEJORA, TIPO_AMORT):
        pct_gasto = CERO
        reglas.append(
            Regla("inversion", "Inversión: no es gasto del año, se amortiza.", "art. 28 LIRPF y art. 23.1.b LIRPF")
        )

    # 1) regla de la cuenta
    afectacion = _campo(asiento, "afectacion_pct")
    if cuenta == CUENTA_VEHICULO and afectacion is None:
        pct_iva = min(pct_iva, normativa.presuncion_vehiculo_iva)
        pct_gasto = CERO
        reglas.append(
            Regla(
                "vehiculo",
                f"Vehículo: IVA deducible al {normativa.presuncion_vehiculo_iva} % por presunción; "
                "en IRPF solo con afectación exclusiva.",
                "art. 95.Tres.2ª LIVA y art. 22.2 RIRPF",
            )
        )
    elif cuenta == CUENTA_SUM_VIVIENDA and afectacion is None:
        vivienda = perfil.afectacion_vivienda_pct
        if vivienda is None:
            pct_iva = pct_gasto = CERO
            avisos.append("Falta el % de la vivienda afecto a la actividad en el perfil: no computa.")
        else:
            pct_iva = min(pct_iva, vivienda)
            pct_gasto = q2(normativa.suministros_vivienda_pct * vivienda / CIEN)
            reglas.append(
                Regla(
                    "suministros_vivienda",
                    f"Suministros de la vivienda: {normativa.suministros_vivienda_pct} % × {vivienda} % afecto "
                    f"en IRPF; IVA en proporción a la afectación ({vivienda} %).",
                    "art. 30.2.5ª.b LIRPF",
                )
            )
    elif cuenta == CUENTA_MANUTENCION:
        bruto = base + iva + recargo
        limite = normativa.manutencion_espana
        if bruto > limite:
            factor = q2(limite / bruto * CIEN)
            pct_gasto = min(pct_gasto, factor)
            pct_iva = min(pct_iva, factor)
            avisos.append(
                f"Manutención por encima del límite diario ({limite} € en España sin pernocta): "
                "computa hasta el límite. Si hubo pernocta o fue en el extranjero, ajusta la afectación."
            )
        reglas.append(
            Regla(
                "manutencion",
                "Manutención: solo con pago electrónico, en establecimientos de hostelería y dentro de los límites.",
                "art. 30.2.5ª.c LIRPF, art. 9 RIRPF y art. 96.Uno.5º LIVA",
            )
        )
    elif cuenta == CUENTA_NO_DEDUCIBLE:
        pct_iva = pct_gasto = CERO
        reglas.append(Regla("no_deducible", "Gasto no deducible.", "art. 15 LIS por remisión del art. 28 LIRPF"))

    # 2) decisión humana sobre la afectación (anula la regla de la cuenta)
    if afectacion is not None:
        if tipo not in (TIPO_MEJORA, TIPO_AMORT):
            pct_gasto = afectacion
        if perfil.deduce_iva:
            pct_iva = afectacion
        reglas.append(Regla("afectacion_manual", f"Afectación fijada a mano: {afectacion} %.", "decisión del titular"))

    # 3) bloqueos legales: ganan siempre, también a la decisión manual
    if perfil.regimen_irpf == IRPF_EO:
        pct_gasto = CERO
        reglas.append(Regla("modulos", "Estimación objetiva: el gasto no determina el rendimiento.", "art. 31 LIRPF"))
    if not cuenta and tipo not in (TIPO_MEJORA, TIPO_AMORT):
        pct_gasto = CERO
        pct_iva = CERO
        avisos.append("Sin clasificar: no computa hasta asignarle rubro.")

    tipo_factura = _campo(asiento, "tipo_factura")
    if tipo_factura == "no_factura":
        pct_iva = pct_gasto = CERO
        reglas.append(
            Regla(
                "no_factura",
                "No es una factura: no justifica el gasto ni el IVA.",
                "art. 97 LIVA y art. 106.4 LGT",
            )
        )

    moneda = _campo(asiento, "moneda") or "EUR"
    if moneda != "EUR":
        pct_iva = pct_gasto = CERO
        avisos.append(f"Importes en {moneda}: no computa hasta convertirlos a euros.")

    if pct_iva > 0:
        nif_receptor = _campo(asiento, "nif_receptor")
        titular = normalize_nif(titular_nif) if titular_nif else ""
        if tipo_factura == "simplificada" and not nif_receptor:
            pct_iva = CERO
            reglas.append(
                Regla(
                    "simplificada_sin_destinatario",
                    "Factura simplificada sin NIF del destinatario: el IVA no se deduce; es mayor gasto.",
                    "art. 97.Uno LIVA y art. 7.2 RD 1619/2012",
                )
            )
        elif not titular or is_placeholder_nif(titular):
            avisos.append("Sin NIF real del titular: no se puede comprobar que la factura esté a su nombre.")
        elif nif_receptor and normalize_nif(nif_receptor) != titular:
            pct_iva = CERO
            reglas.append(
                Regla(
                    "destinatario_distinto",
                    f"La factura está a nombre de {nif_receptor}, no del titular: el IVA no se deduce.",
                    "art. 97.Uno LIVA",
                )
            )

    iva_deducible = q2(iva * pct_iva / CIEN)
    gasto = base * pct_gasto / CIEN + recargo * pct_gasto / CIEN
    # IVA no deducido de la parte afecta: mayor gasto (mismo signo que la cuota)
    exceso = iva * pct_gasto / CIEN - iva_deducible
    if exceso * (1 if iva >= 0 else -1) > 0:
        gasto += exceso
    return Deducibilidad(pct_iva, pct_gasto, iva, iva_deducible, q2(gasto), False, reglas, avisos)
