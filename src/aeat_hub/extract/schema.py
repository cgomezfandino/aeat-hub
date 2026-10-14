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
    precio_unitario: Decimal | None = None
    base: Decimal | None = None
    iva_cuota: Decimal | None = None
    iva_tipo: Decimal | None = None
    eliminada: bool = False


class DesgloseIVA(BaseModel):
    base: Decimal | None = None
    iva_tipo: Decimal | None = None
    iva_cuota: Decimal | None = None
    recargo_tipo: Decimal | None = None
    recargo_cuota: Decimal | None = None


class InvoiceExtract(BaseModel):
    emisor: str | None = None
    nif_emisor: str | None = None
    nif_emisor_valido: bool = False
    receptor: str | None = None
    nif_receptor: str | None = None
    fecha: date | None = None
    numero: str | None = None
    numero_norm: str | None = None
    tipo_documento: str | None = None
    factura_rectificada: str | None = None
    # sustitucion | diferencias (art. 15 RD 1619/2012); decide si suma o reemplaza
    metodo_rectificacion: str | None = None
    causa_rectificacion: str | None = None
    serie: str | None = None
    fecha_operacion: date | None = None
    moneda: str | None = None
    # exenta_art20 | inversion_sujeto_pasivo | criterio_caja | no_sujeta | regimen_especial
    mencion_legal: str | None = None
    # campos que el modelo declara ilegibles o dudosos en el documento
    campos_dudosos: list[str] = Field(default_factory=list)
    pagina_ticket: int | None = None
    paginas_ticket: int | None = None
    base: Decimal | None = None
    iva_tipo: Decimal | None = None
    iva_cuota: Decimal | None = None
    desglose_iva: list[DesgloseIVA] = Field(default_factory=list)
    retencion_tipo: Decimal | None = None
    retencion_cuota: Decimal | None = None
    total: Decimal | None = None
    lineas: list[InvoiceLine] = Field(default_factory=list)
    confianza: float = 0.0
    motor: str = ""

    def fiscal_complete(self) -> bool:
        return bool(self.nif_emisor and self.numero and self.fecha and self.total is not None)

