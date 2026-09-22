"""Esquema Pydantic de una factura española extraída."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class InvoiceLine(BaseModel):
    descripcion: str | None = None
    importe: Decimal | None = None
    codigo: str | None = None
    posicion: int | None = None
    cantidad: Decimal | None = None
    base: Decimal | None = None
    iva_cuota: Decimal | None = None
    iva_tipo: Decimal | None = None
    eliminada: bool = False


class InvoiceExtract(BaseModel):
    emisor: str | None = None
    nif_emisor: str | None = None
    nif_emisor_valido: bool = False
    receptor: str | None = None
    nif_receptor: str | None = None
    fecha: date | None = None
    numero: str | None = None
    numero_norm: str | None = None
    pagina_ticket: int | None = None
    paginas_ticket: int | None = None
    base: Decimal | None = None
    iva_tipo: Decimal | None = None
    iva_cuota: Decimal | None = None
    total: Decimal | None = None
    lineas: list[InvoiceLine] = Field(default_factory=list)
    confianza: float = 0.0
    motor: str = ""

    def fiscal_complete(self) -> bool:
        return bool(self.nif_emisor and self.numero and self.fecha and self.total is not None)
