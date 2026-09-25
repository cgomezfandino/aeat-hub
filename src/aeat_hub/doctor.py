"""Doctor del libro: auditoría de integridad y cuadres.

`Relacion` es polimórfica sin FKs, y SQLite no exige aritmética: este
chequeo recorre el libro y lista lo que no cuadra — relaciones huérfanas,
ficheros perdidos, importes descuadrados e IVAs imposibles.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.fiscal.cuadres import avisos_cuadre, cuadra_lineas
from aeat_hub.models import Actividad, Asiento, Documento, Factura, Relacion
from aeat_hub.paths import DataLayout


@dataclass
class Hallazgo:
    severidad: str  # "error" | "aviso"
    categoria: str
    detalle: str


def revisar(session: Session, layout: DataLayout, actividad: Actividad) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    asientos = session.scalars(
        select(Asiento).where(Asiento.actividad_id == actividad.id).order_by(Asiento.id)
    ).all()

    # 1. Relaciones polimórficas que apuntan a filas inexistentes.
    facturas_ids = set(session.scalars(select(Factura.id)))
    documentos_ids = set(session.scalars(select(Documento.id)))
    for rel in session.scalars(select(Relacion)):
        valido = True
        if rel.destino_tipo == "factura" and rel.destino_id not in facturas_ids:
            valido = False
        if rel.destino_tipo == "documento" and rel.destino_id not in documentos_ids:
            valido = False
        if rel.origen_tipo == "factura" and rel.origen_id not in facturas_ids:
            valido = False
        if rel.origen_tipo == "documento" and rel.origen_id not in documentos_ids:
            valido = False
        if not valido:
            hallazgos.append(
                Hallazgo(
                    "error",
                    "relación huérfana",
                    f"relación {rel.id} ({rel.origen_tipo}#{rel.origen_id} → "
                    f"{rel.destino_tipo}#{rel.destino_id}, {rel.tipo}) apunta a filas que no existen",
                )
            )

    # 2. Asientos cuyo documento apunta a un fichero que ya no está en disco.
    for asiento in asientos:
        documento = asiento.documento
        if documento is None or not documento.ruta_almacenada:
            continue
        if not Path(documento.ruta_almacenada).is_file():
            hallazgos.append(
                Hallazgo(
                    "error",
                    "fichero perdido",
                    f"asiento {asiento.id}: el documento {documento.nombre_original} "
                    f"no está en {documento.ruta_almacenada}",
                )
            )

    # 3. Aritmética: base+IVA=total, y suma de líneas contra total/base.
    from aeat_hub.edits import lineas_de_asiento, parse_money_field

    for asiento in asientos:
        if asiento.estado in ("duplicado", "rechazado"):
            continue
        for aviso in avisos_cuadre(
            base=asiento.base,
            iva_cuota=asiento.iva_cuota,
            iva_tipo=asiento.iva_tipo,
            total=asiento.total,
        ):
            hallazgos.append(Hallazgo("aviso", "cuadre", f"asiento {asiento.id}: {aviso}"))
        lineas = lineas_de_asiento(asiento)
        importes = [
            parse_money_field(item.get("importe"))
            for item in lineas
            if not item.get("eliminada")
        ]
        importes = [v for v in importes if v is not None]
        if importes:
            suma = sum(importes)
            if cuadra_lineas(suma, asiento.total) is False and (
                asiento.base is None or cuadra_lineas(suma, asiento.base) is False
            ):
                hallazgos.append(
                    Hallazgo(
                        "aviso",
                        "cuadre de líneas",
                        f"asiento {asiento.id}: las líneas suman {suma:.2f} "
                        f"y ni total ({asiento.total}) ni base ({asiento.base}) cuadran",
                    )
                )

    # 4. Sin fecha: invisibles en cualquier ejercicio.
    sin_fecha = [a for a in asientos if a.fecha is None and a.estado not in ("duplicado", "rechazado")]
    if sin_fecha:
        ids = ", ".join(str(a.id) for a in sin_fecha[:8])
        hallazgos.append(
            Hallazgo(
                "aviso",
                "sin fecha",
                f"{len(sin_fecha)} asientos sin fecha (fuera de todo ejercicio): {ids}",
            )
        )

    return hallazgos
