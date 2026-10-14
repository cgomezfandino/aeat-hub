"""Cuadres aritméticos del libro: una sola fuente de tolerancias.

Antes había 0,02 y 0,05 repartidos por parser, ingest, ER y dashboard;
aquí viven nombrados y todo el pipeline los importa.
"""

from __future__ import annotations

from decimal import Decimal

# Cabecera: base + cuota debe cuadrar con el total a este centavo.
TOLERANCIA_TOTAL = Decimal("0.02")
# Desglose: la suma de líneas tolera algo más (OCR parte líneas).
TOLERANCIA_LINEAS = Decimal("0.05")

# Tipos de IVA del territorio común (art. 90-91 LIVA).
IVA_TIPOS_CONOCIDOS = (Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0"))
# Tipos coyunturales de las rebajas 2021-2024 (electricidad, alimentos,
# aceite). Fuera de esa ventana un 5 % o un 2 % es sospechoso.
IVA_TIPOS_COYUNTURALES = (Decimal("5"), Decimal("2"))
VENTANA_COYUNTURAL = (2021, 2024)
# Recargo de equivalencia (art. 161 LIVA) y sus tipos rebajados 2023-2024.
RECARGO_TIPOS_CONOCIDOS = (
    Decimal("5.2"),
    Decimal("1.4"),
    Decimal("1.75"),
    Decimal("0.5"),
    Decimal("0.62"),
    Decimal("0.26"),
    Decimal("0"),
)


def cuadra_total(base, iva_cuota, total, *, retencion=None, recargo=None) -> bool | None:
    """¿Base + IVA + recargo − retención IRPF = total? None si faltan datos."""
    if base is None or iva_cuota is None or total is None:
        return None
    esperado = base + iva_cuota + (recargo or Decimal("0")) - (retencion or Decimal("0"))
    return abs(esperado - total) <= TOLERANCIA_TOTAL


def cuadra_lineas(suma, total) -> bool | None:
    """¿La suma de líneas cuadra con el total? None sin datos."""
    if suma is None or total is None:
        return None
    return abs(suma - total) <= TOLERANCIA_LINEAS


def iva_tipo_conocido(iva_tipo, fecha=None) -> bool:
    """Un tipo de IVA español (o None sin dato aún no es 'raro').

    Los coyunturales (5 %, 2 %) solo valen en su ventana; sin fecha se
    aceptan para no avisar de más.
    """
    if iva_tipo is None:
        return True
    tipo = q2_like(iva_tipo)
    if tipo in IVA_TIPOS_CONOCIDOS:
        return True
    if tipo in IVA_TIPOS_COYUNTURALES:
        desde, hasta = VENTANA_COYUNTURAL
        return fecha is None or desde <= fecha.year <= hasta
    return False


def tipo_iva_desde_cuota(base, cuota, fecha=None):
    """El tipo legal que explica base→cuota al céntimo; si ninguno, el cociente.

    Con bases pequeñas el cociente se desvía por el redondeo (0,95 € × 21 %
    = 0,20 € → 21,05 %); el libro debe guardar 21, no 21,05.
    """
    if base is None or cuota is None or base == 0:
        return None
    candidatos = IVA_TIPOS_CONOCIDOS + IVA_TIPOS_COYUNTURALES
    for tipo in candidatos:
        if not iva_tipo_conocido(tipo, fecha):
            continue
        esperada = (abs(base) * tipo / Decimal("100")).quantize(Decimal("0.01"))
        if abs(esperada - abs(cuota)) <= Decimal("0.01"):
            return tipo.quantize(Decimal("0.01"))
    return (cuota / base * 100).quantize(Decimal("0.01"))


def recargo_tipo_conocido(tipo) -> bool:
    if tipo is None:
        return True
    return q2_like(tipo) in RECARGO_TIPOS_CONOCIDOS


def q2_like(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001 - valores ruidosos del OCR
        return Decimal("-1")


def avisos_cuadre(
    *, base, iva_cuota, iva_tipo, total, retencion=None, recargo=None, fecha=None
) -> list[str]:
    """Avisos legibles para el ingest y el doctor."""
    avisos: list[str] = []
    cuadre = cuadra_total(base, iva_cuota, total, retencion=retencion, recargo=recargo)
    if cuadre is False:
        suma = (base or Decimal("0")) + (iva_cuota or Decimal("0")) + (recargo or Decimal("0"))
        partes = "Base+IVA"
        if recargo:
            partes += "+recargo"
        if retencion:
            suma -= retencion
            partes += "−retención"
        avisos.append(
            f"{partes} ({suma:.2f}) no cuadra con el total ({total:.2f}); "
            "revisa la ficha antes de declarar."
        )
    if not iva_tipo_conocido(iva_tipo, fecha):
        avisos.append(
            f"IVA {iva_tipo} % no es un tipo español vigente en esa fecha "
            "(21/10/4/0); probablemente el OCR mezcló importes."
        )
    return avisos
