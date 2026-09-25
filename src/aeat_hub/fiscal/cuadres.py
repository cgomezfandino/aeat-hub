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

IVA_TIPOS_CONOCIDOS = (Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0"))


def cuadra_total(base, iva_cuota, total) -> bool | None:
    """¿Base + cuota = total? None si faltan datos para juzgar."""
    if base is None or iva_cuota is None or total is None:
        return None
    return abs((base + iva_cuota) - total) <= TOLERANCIA_TOTAL


def cuadra_lineas(suma, total) -> bool | None:
    """¿La suma de líneas cuadra con el total? None sin datos."""
    if suma is None or total is None:
        return None
    return abs(suma - total) <= TOLERANCIA_LINEAS


def iva_tipo_conocido(iva_tipo) -> bool:
    """Un tipo de IVA español (o None sin dato aún no es 'raro')."""
    if iva_tipo is None:
        return True
    return any(q2_like(iva_tipo) == conocido for conocido in IVA_TIPOS_CONOCIDOS)


def q2_like(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001 - valores ruidosos del OCR
        return Decimal("-1")


def avisos_cuadre(*, base, iva_cuota, iva_tipo, total) -> list[str]:
    """Avisos legibles para el ingest y el doctor."""
    avisos: list[str] = []
    cuadre = cuadra_total(base, iva_cuota, total)
    if cuadre is False:
        suma = (base or Decimal("0")) + (iva_cuota or Decimal("0"))
        avisos.append(
            f"Base+IVA ({suma:.2f}) no cuadra con el total ({total:.2f}); "
            "revisa la ficha antes de declarar."
        )
    if not iva_tipo_conocido(iva_tipo):
        avisos.append(
            f"IVA {iva_tipo} % no es un tipo español (21/10/4/0); "
            "probablemente el OCR mezcló importes."
        )
    return avisos
