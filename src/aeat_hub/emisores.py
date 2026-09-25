"""Nombres canónicos de emisor, agrupados por NIF.

Un mismo NIF puede llegar del OCR con varias grafías del nombre. Aquí se
comparan (limpiadas de formas societarias) y, si la similitud supera el
umbral, se adopta un nombre canónico. El NIF es la clave: nunca se mezclan
emisores distintos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.extract.ids import normalize_emisor
from aeat_hub.extract.nombres import UMBRAL_NOMBRE, nombre_canonico, similitud_nombre
from aeat_hub.models import Actividad, Asiento, Cambio


@dataclass
class PropuestaNombre:
    nif: str
    antes: str
    canonico: str
    similitud: float
    asientos: list[int] = field(default_factory=list)
    aplica: bool = True
    motivo: str = ""


def unificar_emisores(
    session: Session,
    actividad_id: int,
    *,
    umbral: float | None = None,
    aplicar: bool = False,
) -> list[PropuestaNombre]:
    """Detecta variantes del mismo emisor por NIF y, opcionalmente, unifica.

    Sin `aplicar` es un dry-run: devuelve propuestas sin tocar nada.
    """
    if umbral is None:
        umbral = UMBRAL_NOMBRE
    rows = session.scalars(
        select(Asiento).where(
            Asiento.actividad_id == actividad_id,
            Asiento.nif_emisor.is_not(None),
        )
    ).all()
    grupos: dict[str, list[Asiento]] = {}
    for row in rows:
        grupos.setdefault(row.nif_emisor or "", []).append(row)

    propuestas: list[PropuestaNombre] = []
    for nif, grupo in sorted(grupos.items()):
        variantes: dict[str, list[Asiento]] = {}
        for row in grupo:
            variantes.setdefault(row.emisor or "", []).append(row)
        if len(variantes) < 2:
            continue
        canonico = nombre_canonico(list(variantes))
        if not canonico:
            continue
        for antes, filas in variantes.items():
            if antes == canonico:
                continue
            sim = similitud_nombre(antes, canonico)
            propuesta = PropuestaNombre(
                nif=nif,
                antes=antes,
                canonico=canonico,
                similitud=round(sim, 3),
                asientos=[fila.id for fila in filas],
            )
            if sim >= umbral:
                if aplicar:
                    _aplicar(session, filas, canonico)
                propuesta.motivo = "supera el umbral"
            else:
                propuesta.aplica = False
                propuesta.motivo = "por debajo del umbral"
            propuestas.append(propuesta)
        if aplicar:
            _sincronizar_facturas(session, grupo, canonico, nif=nif, umbral=umbral)
    if aplicar:
        session.flush()
    return propuestas


def _aplicar(session: Session, filas: list[Asiento], canonico: str) -> None:
    for fila in filas:
        session.add(
            Cambio(
                asiento_id=fila.id,
                campo="emisor",
                antes=fila.emisor or "",
                despues=canonico,
                fuente="modelo",
            )
        )
        fila.emisor = canonico


def _sincronizar_facturas(
    session: Session,
    grupo: list[Asiento],
    canonico: str,
    *,
    nif: str,
    umbral: float,
) -> None:
    """La factura canónica del NIF también estrena el nombre canónico."""
    for fila in grupo:
        factura = fila.factura
        if (
            factura is not None
            and factura.emisor != canonico
            and (factura.nif_emisor or "") == nif
            and (
                not factura.emisor
                or similitud_nombre(factura.emisor, canonico) >= umbral
            )
        ):
            factura.emisor = canonico
            factura.emisor_norm = normalize_emisor(canonico)


def nombre_canonico_para(
    session: Session,
    actividad_id: int,
    nif: str | None,
    variante: str | None,
) -> str | None:
    """El nombre canónico ya conocido de ese NIF, si la variante casa.

    Lo usa el ingest para que una grafía nueva no fragmente el emisor.
    """
    if not nif or not variante:
        return None
    conocidas = session.scalars(
        select(Asiento.emisor).where(
            Asiento.actividad_id == actividad_id,
            Asiento.nif_emisor == nif,
        )
    ).all()
    conocidas = [v for v in conocidas if v]
    if not conocidas:
        return None
    canonico = nombre_canonico([*conocidas, variante])
    if not canonico or canonico == variante:
        return None
    if similitud_nombre(variante, canonico) < UMBRAL_NOMBRE:
        return None
    return canonico
