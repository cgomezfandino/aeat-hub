"""Qué asientos computan en libros, KPIs, trimestres, IRPF y exportaciones.

Una sola regla para todo el producto: computa lo **validado por una
persona** que no es duplicado ni rechazado. La confianza del clasificador
no basta: acierta el rubro, no garantiza que los importes leídos sean los
del documento. Lo no validado se muestra siempre aparte, como pendiente
de revisar, para que nadie declare con datos sin mirar.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

EXCLUIDOS = ("duplicado", "rechazado")


def _campo(item, nombre: str):
    if isinstance(item, dict):
        return item.get(nombre)
    return getattr(item, nombre, None)


def es_computable(item) -> bool:
    return bool(_campo(item, "validado")) and _campo(item, "estado") not in EXCLUIDOS


def es_por_revisar(item) -> bool:
    return not _campo(item, "validado") and _campo(item, "estado") not in EXCLUIDOS


def computables(items: Iterable) -> list:
    return [item for item in items if es_computable(item)]


def por_revisar(items: Iterable) -> list:
    return [item for item in items if es_por_revisar(item)]


def total(items: Iterable) -> Decimal:
    suma = Decimal("0.00")
    for item in items:
        suma += _campo(item, "total") or Decimal("0.00")
    return suma
