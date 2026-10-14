"""Borradores de retenciones (111, 115), declaraciones informativas (347, 349)
y resumen anual del IVA (base del 390).

Mismas reglas que `modelos.py`: solo lo computable, cada casilla con sus
asientos y los límites del borrador en `avisos`.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from aeat_hub.fiscal.accounts import TIPO_INGRESO
from aeat_hub.fiscal.modelos import CERO, Borrador, Casilla, _comunes, _trimestre, _unicos, borrador_303
from aeat_hub.fiscal.nif import is_nif_iva_ue, normalize_nif
from aeat_hub.fiscal.perfil import IRPF_CAPITAL_INMOBILIARIO, IVA_EXENTO

CUENTA_ALQUILER = "AE.GAS.ALQUILER"
# Pagos que no son operaciones con terceros a efectos del 347 (cotizaciones,
# nóminas, tributos) o que ya se informan en otro modelo.
SIN_347 = {"AE.GAS.SS", "AE.GAS.SSEMPRESA", "AE.GAS.SUELDOS", "AE.GAS.TRIBUTOS", "CI.GAS.IBI"}
SERVICIOS_349 = {"AE.GAS.SERVICIOS", "AE.GAS.PROFESIONALES", "AE.GAS.SEGUROS", "AE.ING.VENTAS"}
BIENES_349 = {"AE.GAS.COMPRAS", "AE.INV.BIENES"}


def _retenedor(perfil) -> bool:
    """Solo retiene quien ejerce una actividad económica (art. 76 RIRPF)."""
    return perfil.regimen_irpf != IRPF_CAPITAL_INMOBILIARIO


def _retenciones(asientos, actividad, ejercicio, trimestre, *, alquiler: bool, modelo: str,
                 casillas: tuple[str, str, str], titular_nif) -> Borrador:
    perfil, normativa, libro, avisos, _ = _comunes(asientos, actividad, ejercicio)
    if not _retenedor(perfil):
        return Borrador(
            modelo, ejercicio, f"{trimestre}T", False, {}, CERO, normativa.verificado,
            avisos + ["Sin actividad económica no hay obligación de retener (art. 76 RIRPF)."],
        )
    perceptores = Casilla(casillas[0], "Número de perceptores")
    base = Casilla(casillas[1], "Importe de las percepciones" if not alquiler else "Base de las retenciones")
    retenciones = Casilla(casillas[2], "Retenciones")
    nifs: set[str] = set()
    for asiento in libro:
        if asiento.tipo == TIPO_INGRESO or _trimestre(asiento.fecha) != trimestre:
            continue
        if not asiento.retencion_cuota:
            continue
        if (asiento.cuenta_codigo == CUENTA_ALQUILER) != alquiler:
            continue
        base.sumar(asiento.base, asiento.id)
        retenciones.sumar(asiento.retencion_cuota, asiento.id)
        if asiento.nif_emisor:
            nifs.add(normalize_nif(asiento.nif_emisor))
        else:
            avisos.append(f"#{asiento.id}: retención sin NIF del perceptor; el modelo lo exige.")
    perceptores.importe = Decimal(len(nifs))
    perceptores.asientos = list(base.asientos)
    if alquiler:
        avisos.append("Retención del alquiler de local: 19 % sobre la renta sin IVA.")
    else:
        avisos.append(
            "Solo retenciones que constan en la factura del profesional; si un profesional no te "
            "retuvo y debía, la obligación de ingresarla es tuya."
        )
    return Borrador(
        modelo, ejercicio, f"{trimestre}T", True,
        {c.numero: c for c in (perceptores, base, retenciones)},
        retenciones.importe, normativa.verificado, _unicos(avisos),
    )


def borrador_111(asientos, actividad, ejercicio: int, trimestre: int, *, titular_nif=None) -> Borrador:
    return _retenciones(asientos, actividad, ejercicio, trimestre, alquiler=False, modelo="111",
                        casillas=("07", "08", "09"), titular_nif=titular_nif)


def borrador_115(asientos, actividad, ejercicio: int, trimestre: int, *, titular_nif=None) -> Borrador:
    return _retenciones(asientos, actividad, ejercicio, trimestre, alquiler=True, modelo="115",
                        casillas=("01", "02", "03"), titular_nif=titular_nif)


def borrador_347(asientos, actividad, ejercicio: int, *, titular_nif=None) -> Borrador:
    """Operaciones con terceros de más de 3.005,06 € al año, IVA incluido.

    Clave A: adquisiciones (compras); clave B: entregas (ventas). Fuera lo
    que ya va en otros modelos: con retención (190/180), intracomunitario
    (349), y lo que no es operación con un tercero (cotizaciones, tributos).
    """
    perfil, normativa, libro, avisos, _ = _comunes(asientos, actividad, ejercicio)
    acumulado: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"total": CERO, "trimestres": defaultdict(lambda: CERO), "asientos": [], "nombre": ""}
    )
    exentas_vivienda = perfil.regimen_irpf == IRPF_CAPITAL_INMOBILIARIO and perfil.regimen_iva == IVA_EXENTO
    for asiento in libro:
        ingreso = asiento.tipo == TIPO_INGRESO
        nif = asiento.nif_receptor if ingreso else asiento.nif_emisor
        if asiento.retencion_cuota or asiento.cuenta_codigo in SIN_347:
            continue
        if asiento.tipo_factura == "no_factura":
            continue
        if ingreso and exentas_vivienda:
            continue
        if not nif:
            if (asiento.total or CERO) > 0:
                avisos.append(f"#{asiento.id}: sin NIF de la contraparte; no se puede imputar en el 347.")
            continue
        if is_nif_iva_ue(nif):
            continue
        clave = ("B" if ingreso else "A", normalize_nif(nif))
        slot = acumulado[clave]
        slot["total"] += asiento.total or CERO
        slot["trimestres"][_trimestre(asiento.fecha) or 4] += asiento.total or CERO
        slot["asientos"].append(asiento.id)
        slot["nombre"] = slot["nombre"] or ((asiento.receptor if ingreso else asiento.emisor) or "")
    casillas: dict[str, Casilla] = {}
    for (clave, nif), slot in sorted(acumulado.items()):
        if slot["total"] <= normativa.umbral_347:
            continue
        trimestres = " · ".join(f"{t}T {slot['trimestres'][t]}" for t in (1, 2, 3, 4) if slot["trimestres"][t])
        casilla = Casilla(f"{clave}-{nif}", f"{slot['nombre']} · clave {clave} · {trimestres}", slot["total"])
        casilla.asientos = slot["asientos"]
        casillas[casilla.numero] = casilla
    if exentas_vivienda:
        avisos.append(
            "Rentas de vivienda exentas sin obligación de factura: no se incluyen (art. 33.2.a RGAT). "
            "Si emitiste facturas por ellas, inclúyelas."
        )
    avisos.append("No incluye cobros en metálico de más de 6.000 €: el libro no guarda la forma de pago.")
    total = sum((c.importe for c in casillas.values()), CERO)
    return Borrador("347", ejercicio, "anual", True, casillas, total, normativa.verificado, _unicos(avisos))


def borrador_349(asientos, actividad, ejercicio: int, trimestre: int, *, titular_nif=None) -> Borrador:
    """Operaciones intracomunitarias por NIF-IVA y clave (A, E, I, S)."""
    perfil, normativa, libro, avisos, _ = _comunes(asientos, actividad, ejercicio)
    casillas: dict[str, Casilla] = {}
    for asiento in libro:
        if _trimestre(asiento.fecha) != trimestre:
            continue
        ingreso = asiento.tipo == TIPO_INGRESO
        nif = asiento.nif_receptor if ingreso else asiento.nif_emisor
        if not nif or not is_nif_iva_ue(nif):
            continue
        if asiento.cuenta_codigo in BIENES_349:
            clave = "E" if ingreso else "A"
        else:
            clave = "S" if ingreso else "I"
            if asiento.cuenta_codigo not in SERVICIOS_349:
                avisos.append(f"#{asiento.id}: se declara como servicio (clave {clave}); cámbialo si fueron bienes.")
        numero = f"{clave}-{normalize_nif(nif)}"
        if numero not in casillas:
            nombre = (asiento.receptor if ingreso else asiento.emisor) or ""
            casillas[numero] = Casilla(numero, f"{nombre} · clave {clave}")
        casillas[numero].sumar(asiento.base, asiento.id)
    if casillas:
        avisos.append("Comprueba en VIES que cada NIF-IVA está dado de alta en el ROI.")
    total = sum((c.importe for c in casillas.values()), CERO)
    return Borrador("349", ejercicio, f"{trimestre}T", bool(casillas), casillas, total, normativa.verificado,
                    _unicos(avisos))


def resumen_iva_anual(asientos, actividad, ejercicio: int, *, titular_nif=None) -> Borrador:
    """Suma de los cuatro 303 por casilla del 303: base para preparar el 390."""
    trimestrales = [borrador_303(asientos, actividad, ejercicio, t, titular_nif=titular_nif) for t in (1, 2, 3, 4)]
    if not trimestrales[0].aplica:
        return Borrador("390", ejercicio, "anual", False, {}, CERO, trimestrales[0].verificado,
                        list(trimestrales[0].avisos))
    casillas: dict[str, Casilla] = {}
    avisos: list[str] = [
        "Resumen anual con la numeración del 303. El 390 tiene casillas propias: trasládalas por concepto."
    ]
    for borrador in trimestrales:
        for numero, casilla in borrador.casillas.items():
            if casilla.concepto == "Tipo":
                casillas.setdefault(numero, Casilla(numero, "Tipo", casilla.importe))
                continue
            destino = casillas.setdefault(numero, Casilla(numero, casilla.concepto))
            destino.sumar(casilla.importe)
            destino.asientos.extend(i for i in casilla.asientos if i not in destino.asientos)
        avisos.extend(borrador.avisos)
    resultado = sum((b.resultado for b in trimestrales), CERO)
    return Borrador("390", ejercicio, "anual", True, casillas, resultado, trimestrales[0].verificado, _unicos(avisos))
