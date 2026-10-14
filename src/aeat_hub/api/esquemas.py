"""Modelos de respuesta de la API.

Los importes son `Decimal` y viajan como cadena JSON ("1362.73"): un float
en el navegador reintroduciría el error binario que la base ya no tiene.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class Actividad(BaseModel):
    codigo: str
    nombre: str
    regimen: str
    regimen_irpf: str
    regimen_iva: str
    titular: str
    nif_titular_real: bool
    ejercicios: list[int]


class Mes(BaseModel):
    mes: int
    ingresos: Decimal
    gastos: Decimal
    mejoras: Decimal


class Resumen(BaseModel):
    codigo: str
    ejercicio: int
    ingresos: Decimal
    gastos: Decimal
    mejoras: Decimal
    resultado: Decimal
    iva_soportado_deducible: Decimal
    iva_repercutido: Decimal
    retenciones_soportadas: Decimal
    n_computables: int
    n_por_revisar: int
    total_por_revisar: Decimal
    n_duplicados: int
    n_incidencias: int
    por_mes: list[Mes]
    avisos: list[str]


class FilaAsiento(BaseModel):
    id: int
    fecha: date | None
    emisor: str | None
    nif_emisor: str | None
    numero: str | None
    tipo: str
    rubro: str | None
    base: Decimal | None
    iva_cuota: Decimal | None
    total: Decimal | None
    estado: str
    validado: bool
    computa: bool
    tipo_factura: str | None
    direccion: str
    duplicado_de_id: int | None
    confianza: Decimal | None
    tiene_documento: bool


class Linea(BaseModel):
    id: int | None = None
    codigo: str | None = None
    descripcion: str | None = None
    cantidad: Decimal | None = None
    base: Decimal | None = None
    iva_tipo: Decimal | None = None
    iva_cuota: Decimal | None = None
    importe: Decimal | None = None


class TipoIVA(BaseModel):
    base: Decimal | None
    tipo: Decimal | None
    cuota: Decimal | None
    recargo_tipo: Decimal | None = None
    recargo_cuota: Decimal | None = None


class Regla(BaseModel):
    codigo: str
    texto: str
    cita: str


class Deducibilidad(BaseModel):
    pct_iva: Decimal
    pct_gasto: Decimal
    iva_deducible: Decimal
    importe_irpf: Decimal
    es_ingreso: bool
    reglas: list[Regla]
    avisos: list[str]


class Cambio(BaseModel):
    campo: str
    antes: str
    despues: str
    fuente: str
    cuando: str | None


class Candidato(BaseModel):
    id: int
    emisor: str | None = None
    fecha: str | None = None
    total: str | None = None
    motivo: str


class Ficha(FilaAsiento):
    actividad: str
    serie: str | None
    fecha_operacion: date | None
    receptor: str | None
    nif_receptor: str | None
    iva_tipo: Decimal | None
    retencion_tipo: Decimal | None
    retencion_cuota: Decimal | None
    recargo_cuota: Decimal | None
    moneda: str
    mencion_legal: str | None
    factura_rectificada: str | None
    factura_rectificada_id: int | None
    afectacion_pct: Decimal | None
    cuenta_codigo: str | None
    motivo_rechazo: str | None
    documento_nombre: str | None
    documento_disponible: bool
    desglose_iva: list[TipoIVA]
    lineas: list[Linea]
    deducibilidad: Deducibilidad | None
    candidatos_duplicado: list[Candidato]
    cambios: list[Cambio]


class Incidencia(BaseModel):
    asiento_id: int | None
    tipo: str = Field(description="duplicado | cuadre | nif | no_factura | moneda | rectificativa | sin_clasificar | perfil")
    gravedad: str = Field(description="bloquea | revisar | info")
    titulo: str
    detalle: str
    cita: str = ""
    relacionado_id: int | None = None


class Casilla(BaseModel):
    numero: str
    concepto: str
    importe: Decimal
    asientos: list[int]


class Borrador(BaseModel):
    modelo: str
    ejercicio: int
    periodo: str
    aplica: bool
    verificado: bool
    resultado: Decimal
    casillas: list[Casilla]
    avisos: list[str]
    n_por_revisar: int
    total_por_revisar: Decimal


class Anotacion(BaseModel):
    asiento_id: int
    numero_registro: int
    fecha_expedicion: date | None
    fecha_operacion: date | None
    serie: str | None
    numero: str | None
    nif: str | None
    nombre: str | None
    concepto: str
    desglose: list[TipoIVA]
    total: Decimal | None
    retencion_cuota: Decimal | None
    rectificativa: bool
    importe_irpf: Decimal
    iva_deducible: Decimal


class Libros(BaseModel):
    ejercicio: int
    ingresos: list[Anotacion]
    gastos: list[Anotacion]
    bienes_inversion: list[Anotacion]
    n_por_revisar: int
    total_por_revisar: Decimal
    avisos: list[str]


class Perfil(BaseModel):
    codigo: str
    nif_titular: str
    regimen_irpf: str
    regimen_iva: str
    territorio: str
    epigrafe_iae: str | None
    fecha_alta: str | None
    afectacion_vivienda_pct: Decimal | None
    rendimiento_anterior: Decimal | None
    por_defecto: list[str]
    avisos: list[str]


class ResultadoSubida(BaseModel):
    nombre: str
    asiento_id: int | None
    estado: str
    detalle: str
    avisos: list[str]


class Error(BaseModel):
    detail: str
