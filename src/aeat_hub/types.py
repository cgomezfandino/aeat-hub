"""Tipos de columna exactos para importes, tipos impositivos y cantidades.

SQLite no tiene decimal: `Numeric` se guarda como REAL (binario) y
`0.1 + 0.2` deja de ser `0.3` en cualquier SUM o comparación en SQL.
`Fixed(escala)` guarda en SQLite un entero escalado (céntimos con escala 2)
y en el resto de motores un NUMERIC nativo. La aplicación ve siempre
`Decimal` cuantizado.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import BigInteger, Numeric
from sqlalchemy.types import TypeDecorator


class Fixed(TypeDecorator):
    impl = Numeric
    cache_ok = True

    def __init__(self, scale: int = 2, precision: int = 14) -> None:
        super().__init__()
        self.scale = scale
        self.precision = precision
        self._quantum = Decimal(1).scaleb(-scale)
        self._factor = Decimal(10) ** scale

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(BigInteger())
        return dialect.type_descriptor(Numeric(self.precision, self.scale, asdecimal=True))

    def _quantize(self, value) -> Decimal:
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return value.quantize(self._quantum, rounding=ROUND_HALF_UP)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = self._quantize(value)
        if dialect.name == "sqlite":
            return int(value * self._factor)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "sqlite":
            return self._quantize(Decimal(int(round(value))) / self._factor)
        return self._quantize(value)

    @property
    def python_type(self):
        return Decimal


def Money() -> Fixed:  # noqa: N802 - se usa como tipo de columna
    return Fixed(2)


def Rate() -> Fixed:  # noqa: N802
    """Tipo impositivo en % (21.00, 5.20)."""
    return Fixed(2, precision=6)


def Quantity() -> Fixed:  # noqa: N802
    return Fixed(3)
