"""Libros registro del IRPF y del IVA (Orden HAC/773/2019, art. 62-64 RIVA).

Construye las filas como datos; la exportación (Excel, CSV, API) es aparte.
Solo entra lo computable (validado, sin duplicados ni rechazados): un libro
registro no puede llevar datos sin revisar. Las rectificativas se anotan
separadas, como exigen los art. 2.e y 3.f de la Orden.

- Ventas e ingresos / facturas expedidas: por fecha de expedición y número.
- Compras y gastos / facturas recibidas: por orden de recepción (alta en el
  sistema), con número de recepción correlativo (art. 64.2 RIVA) e importe
  que computa como gasto en IRPF (art. 3.1.e de la Orden).
- Bienes de inversión: compras que se amortizan (art. 4 de la Orden).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from aeat_hub.fiscal.accounts import TIPO_AMORT, TIPO_INGRESO, TIPO_MEJORA
from aeat_hub.fiscal.computo import computables, por_revisar
from aeat_hub.fiscal.deducibilidad import evaluar
from aeat_hub.fiscal.normativa import para
from aeat_hub.fiscal.perfil import perfil_de

CERO = Decimal("0.00")


@dataclass
class FilaIVA:
    base: Decimal | None
    tipo: Decimal | None
    cuota: Decimal | None
    recargo_tipo: Decimal | None = None
    recargo_cuota: Decimal | None = None


@dataclass
class Anotacion:
    asiento_id: int
    numero_registro: int
    fecha_expedicion: date | None
    fecha_operacion: date | None
    serie: str | None
    numero: str | None
    nif: str | None
    nombre: str | None
    concepto: str
    desglose: list[FilaIVA]
    total: Decimal | None
    retencion_tipo: Decimal | None
    retencion_cuota: Decimal | None
    rectificativa: bool
    factura_rectificada: str | None
    # IRPF: ingreso computable o gasto deducible (art. 2.d y 3.e de la Orden)
    importe_irpf: Decimal
    iva_deducible: Decimal = CERO
    reglas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


@dataclass
class Libros:
    ejercicio: int
    ingresos: list[Anotacion]
    gastos: list[Anotacion]
    bienes_inversion: list[Anotacion]
    n_por_revisar: int
    total_por_revisar: Decimal
    avisos: list[str]


def _trimestre(fecha: date | None) -> int | None:
    return (fecha.month - 1) // 3 + 1 if fecha else None


def desglose_de(asiento) -> list[FilaIVA]:
    filas = [
        FilaIVA(f.base, f.tipo, f.cuota, f.recargo_tipo, f.recargo_cuota)
        for f in getattr(asiento, "desglose_iva", []) or []
    ]
    if filas:
        return filas
    if asiento.base is None and asiento.iva_cuota is None:
        return []
    return [FilaIVA(asiento.base, asiento.iva_tipo, asiento.iva_cuota, None, asiento.recargo_cuota)]


def construir(
    asientos, actividad, ejercicio: int, *, titular_nif: str | None, nombres_cuenta: dict[str, str],
    trimestre: int | None = None,
) -> Libros:
    perfil = perfil_de(actividad)
    normativa = para(ejercicio)
    avisos = list(normativa.avisos) + list(perfil.avisos)
    if perfil.por_defecto:
        avisos.append("Perfil fiscal incompleto (" + ", ".join(perfil.por_defecto) + "): revisa `aeat-hub actividad perfil`.")

    del_periodo = [
        a for a in asientos
        if a.ejercicio == ejercicio and (trimestre is None or _trimestre(a.fecha) == trimestre)
    ]
    libro = computables(del_periodo)
    pendientes = por_revisar(del_periodo)

    def anotar(asiento, numero: int) -> Anotacion:
        ded = evaluar(asiento, perfil, normativa, titular_nif=titular_nif)
        ingreso = asiento.tipo == TIPO_INGRESO
        return Anotacion(
            asiento_id=asiento.id,
            numero_registro=numero,
            fecha_expedicion=asiento.fecha,
            fecha_operacion=asiento.fecha_operacion,
            serie=asiento.serie,
            numero=asiento.numero_factura,
            # ventas: destinatario; compras: emisor (art. 2.c y 3.c)
            nif=asiento.nif_receptor if ingreso else asiento.nif_emisor,
            nombre=asiento.receptor if ingreso else asiento.emisor,
            concepto=nombres_cuenta.get(asiento.cuenta_codigo or "", "") or "Sin clasificar",
            desglose=desglose_de(asiento),
            total=asiento.total,
            retencion_tipo=asiento.retencion_tipo,
            retencion_cuota=asiento.retencion_cuota,
            rectificativa=asiento.tipo_factura == "rectificativa",
            factura_rectificada=asiento.factura_rectificada,
            importe_irpf=ded.importe_irpf,
            iva_deducible=ded.iva_deducible,
            reglas=[f"{r.texto} ({r.cita})" if r.cita else r.texto for r in ded.reglas],
            avisos=list(ded.avisos),
        )

    def orden_expedicion(a):
        # rectificativas al final, separadas (art. 2.e de la Orden)
        return (a.tipo_factura == "rectificativa", a.fecha or date.max, a.serie or "", a.numero_factura or "", a.id)

    def orden_recepcion(a):
        return (a.tipo_factura == "rectificativa", a.created_at or datetime.max, a.id)

    ingresos_src = sorted((a for a in libro if a.tipo == TIPO_INGRESO), key=orden_expedicion)
    gastos_src = sorted((a for a in libro if a.tipo != TIPO_INGRESO), key=orden_recepcion)
    ingresos = [anotar(a, i) for i, a in enumerate(ingresos_src, start=1)]
    gastos = [anotar(a, i) for i, a in enumerate(gastos_src, start=1)]
    inversion_ids = {a.id for a in gastos_src if a.tipo in (TIPO_MEJORA, TIPO_AMORT)}
    bienes = [fila for fila in gastos if fila.asiento_id in inversion_ids]

    return Libros(
        ejercicio=ejercicio,
        ingresos=ingresos,
        gastos=gastos,
        bienes_inversion=bienes,
        n_por_revisar=len(pendientes),
        total_por_revisar=sum((a.total or CERO for a in pendientes), CERO),
        avisos=avisos,
    )
