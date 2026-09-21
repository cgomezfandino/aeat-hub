"""Entity resolution: raw → extracción → factura canónica → asiento."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aeat_hub.extract.ids import normalize_emisor, normalize_numero
from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.models import Asiento, Documento, Extraccion, Factura, Relacion

KIND_DOCUMENTO = "documento"
KIND_FACTURA = "factura"

REL_EVIDENCIA = "evidencia"
REL_CONTINUACION = "continuacion"
REL_CONFLICTO = "conflicto"

ER_PROPUESTA = "propuesta"
ER_CONFLICTO = "conflicto"

TOTAL_TOLERANCE = Decimal("0.02")


def save_extraccion(session: Session, documento: Documento, extract: InvoiceExtract) -> Extraccion:
    row = Extraccion(
        documento_id=documento.id,
        numero_raw=extract.numero,
        numero_norm=extract.numero_norm or normalize_numero(extract.numero),
        emisor=extract.emisor,
        emisor_norm=normalize_emisor(extract.emisor),
        nif_emisor=extract.nif_emisor,
        fecha=extract.fecha,
        base=extract.base,
        iva_tipo=extract.iva_tipo,
        iva_cuota=extract.iva_cuota,
        total=extract.total,
        pagina_ticket=extract.pagina_ticket,
        paginas_ticket=extract.paginas_ticket,
        json_completo=extract.model_dump_json(),
    )
    session.add(row)
    session.flush()
    return row


def add_relacion(
    session: Session,
    *,
    origen_tipo: str,
    origen_id: int,
    destino_tipo: str,
    destino_id: int,
    tipo: str,
    motivo: str = "",
    confianza: Decimal = Decimal("1.000"),
    fuente: str = "modelo",
) -> Relacion:
    row = Relacion(
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        destino_tipo=destino_tipo,
        destino_id=destino_id,
        tipo=tipo,
        confianza=confianza,
        fuente=fuente,
        motivo=motivo,
    )
    session.add(row)
    session.flush()
    return row


def count_evidencias(session: Session, factura_id: int) -> int:
    value = session.scalar(
        select(func.count())
        .select_from(Relacion)
        .where(
            Relacion.destino_tipo == KIND_FACTURA,
            Relacion.destino_id == factura_id,
            Relacion.origen_tipo == KIND_DOCUMENTO,
            Relacion.tipo.in_((REL_EVIDENCIA, REL_CONTINUACION)),
        )
    )
    return int(value or 0)


def counts_por_factura(session: Session, factura_ids: list[int]) -> dict[int, int]:
    if not factura_ids:
        return {}
    rows = session.execute(
        select(Relacion.destino_id, func.count())
        .where(
            Relacion.destino_tipo == KIND_FACTURA,
            Relacion.destino_id.in_(factura_ids),
            Relacion.origen_tipo == KIND_DOCUMENTO,
            Relacion.tipo.in_((REL_EVIDENCIA, REL_CONTINUACION)),
        )
        .group_by(Relacion.destino_id)
    ).all()
    return {int(fid): int(n) for fid, n in rows}


def estados_er_por_factura(session: Session, factura_ids: list[int]) -> dict[int, str]:
    if not factura_ids:
        return {}
    rows = session.execute(
        select(Factura.id, Factura.estado_er).where(Factura.id.in_(factura_ids))
    ).all()
    return {int(fid): estado for fid, estado in rows}


def documentos_de_factura(session: Session, factura_id: int) -> list[Documento]:
    ids = session.scalars(
        select(Relacion.origen_id).where(
            Relacion.destino_tipo == KIND_FACTURA,
            Relacion.destino_id == factura_id,
            Relacion.origen_tipo == KIND_DOCUMENTO,
            Relacion.tipo.in_((REL_EVIDENCIA, REL_CONTINUACION)),
        )
    ).all()
    if not ids:
        return []
    docs = session.scalars(select(Documento).where(Documento.id.in_(list(ids)))).all()
    return list(docs)


def totals_compatible(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return True
    return abs(left - right) <= TOTAL_TOLERANCE


def rel_tipo_evidencia(extract: InvoiceExtract) -> str:
    if extract.pagina_ticket and extract.pagina_ticket > 1:
        return REL_CONTINUACION
    return REL_EVIDENCIA


def _candidatos(session: Session, actividad_id: int, extract: InvoiceExtract) -> list[Factura]:
    numero = extract.numero_norm or normalize_numero(extract.numero)
    if not numero:
        return []
    rows = session.scalars(
        select(Factura).where(
            Factura.actividad_id == actividad_id,
            Factura.numero_norm == numero,
        )
    ).all()
    nif = extract.nif_emisor
    emisor = normalize_emisor(extract.emisor)
    hits: list[Factura] = []
    for factura in rows:
        if nif and factura.nif_emisor:
            if factura.nif_emisor == nif:
                hits.append(factura)
            continue
        if emisor and factura.emisor_norm == emisor:
            hits.append(factura)
    return hits


def _factura_desde_extract(
    actividad_id: int,
    extract: InvoiceExtract,
    *,
    estado_er: str = ER_PROPUESTA,
) -> Factura:
    return Factura(
        actividad_id=actividad_id,
        nif_emisor=extract.nif_emisor,
        emisor=extract.emisor,
        emisor_norm=normalize_emisor(extract.emisor),
        numero_norm=extract.numero_norm or normalize_numero(extract.numero),
        numero_visible=extract.numero,
        fecha=extract.fecha,
        base=extract.base,
        iva_tipo=extract.iva_tipo,
        iva_cuota=extract.iva_cuota,
        total=extract.total,
        estado_er=estado_er,
    )


def _enriquecer(factura: Factura, extract: InvoiceExtract) -> None:
    if not factura.nif_emisor and extract.nif_emisor:
        factura.nif_emisor = extract.nif_emisor
    if not factura.emisor and extract.emisor:
        factura.emisor = extract.emisor
        factura.emisor_norm = normalize_emisor(extract.emisor)
    if not factura.numero_visible and extract.numero:
        factura.numero_visible = extract.numero
    if factura.fecha is None and extract.fecha is not None:
        factura.fecha = extract.fecha
    if factura.base is None and extract.base is not None:
        factura.base = extract.base
    if factura.iva_tipo is None and extract.iva_tipo is not None:
        factura.iva_tipo = extract.iva_tipo
    if factura.iva_cuota is None and extract.iva_cuota is not None:
        factura.iva_cuota = extract.iva_cuota
    if factura.total is None and extract.total is not None:
        factura.total = extract.total


def _enriquecer_asiento(asiento: Asiento, extract: InvoiceExtract) -> None:
    if asiento.validado:
        return
    if not asiento.nif_emisor and extract.nif_emisor:
        asiento.nif_emisor = extract.nif_emisor
    if not asiento.emisor and extract.emisor:
        asiento.emisor = extract.emisor
    if not asiento.numero_factura and extract.numero:
        asiento.numero_factura = extract.numero
    if asiento.fecha is None and extract.fecha is not None:
        asiento.fecha = extract.fecha
        asiento.ejercicio = extract.fecha.year
    if asiento.base is None and extract.base is not None:
        asiento.base = extract.base
    if asiento.iva_tipo is None and extract.iva_tipo is not None:
        asiento.iva_tipo = extract.iva_tipo
    if asiento.iva_cuota is None and extract.iva_cuota is not None:
        asiento.iva_cuota = extract.iva_cuota
    if asiento.total is None and extract.total is not None:
        asiento.total = extract.total


def _asiento_de_factura(session: Session, factura: Factura) -> Asiento | None:
    vivo = session.scalar(
        select(Asiento).where(
            Asiento.factura_id == factura.id,
            Asiento.estado != "duplicado",
        ).limit(1)
    )
    if vivo is not None:
        return vivo
    return session.scalar(select(Asiento).where(Asiento.factura_id == factura.id).limit(1))


def attach_documento(
    session: Session,
    *,
    documento: Documento,
    extract: InvoiceExtract,
    factura: Factura,
    rel_tipo: str,
    motivo: str = "",
) -> None:
    add_relacion(
        session,
        origen_tipo=KIND_DOCUMENTO,
        origen_id=documento.id,
        destino_tipo=KIND_FACTURA,
        destino_id=factura.id,
        tipo=rel_tipo,
        motivo=motivo or rel_tipo,
    )


def cluster_documento(
    session: Session,
    *,
    actividad_id: int,
    documento: Documento,
    extract: InvoiceExtract,
) -> tuple[Factura, Asiento | None, str, bool]:
    """Agrupa el raw en una factura.

    Devuelve (factura, asiento_existente_o_None, rel_tipo, conflicto_nuevo).
    Si asiento es None hay que crear uno. Si conflicto_nuevo, marcar revisión.
    """
    rel_tipo = rel_tipo_evidencia(extract)
    candidatos = _candidatos(session, actividad_id, extract)
    compatibles = [item for item in candidatos if totals_compatible(item.total, extract.total)]
    if compatibles:
        propuesta = [item for item in compatibles if item.estado_er != ER_CONFLICTO]
        factura = (propuesta or compatibles)[0]
        _enriquecer(factura, extract)
        asiento = _asiento_de_factura(session, factura)
        if asiento is not None:
            _enriquecer_asiento(asiento, extract)
        attach_documento(
            session,
            documento=documento,
            extract=extract,
            factura=factura,
            rel_tipo=rel_tipo,
            motivo="mismo emisor+número",
        )
        return factura, asiento, rel_tipo, False

    if candidatos:
        rival = candidatos[0]
        rival.estado_er = ER_CONFLICTO
        factura = _factura_desde_extract(actividad_id, extract, estado_er=ER_CONFLICTO)
        session.add(factura)
        session.flush()
        attach_documento(
            session,
            documento=documento,
            extract=extract,
            factura=factura,
            rel_tipo=rel_tipo,
            motivo="mismo ID, total distinto",
        )
        add_relacion(
            session,
            origen_tipo=KIND_FACTURA,
            origen_id=factura.id,
            destino_tipo=KIND_FACTURA,
            destino_id=rival.id,
            tipo=REL_CONFLICTO,
            motivo="total distinto con el mismo número",
        )
        return factura, None, REL_CONFLICTO, True

    factura = _factura_desde_extract(actividad_id, extract)
    session.add(factura)
    session.flush()
    attach_documento(
        session,
        documento=documento,
        extract=extract,
        factura=factura,
        rel_tipo=rel_tipo,
        motivo="alta",
    )
    return factura, None, rel_tipo, False


def backfill_asientos(session: Session) -> int:
    """Crea factura + extracción + evidencia para asientos sin factura_id."""
    rows = session.scalars(select(Asiento).where(Asiento.factura_id.is_(None))).all()
    updated = 0
    for asiento in rows:
        extract = InvoiceExtract(
            emisor=asiento.emisor,
            nif_emisor=asiento.nif_emisor,
            fecha=asiento.fecha,
            numero=asiento.numero_factura,
            numero_norm=normalize_numero(asiento.numero_factura),
            base=asiento.base,
            iva_tipo=asiento.iva_tipo,
            iva_cuota=asiento.iva_cuota,
            total=asiento.total,
        )
        factura = _factura_desde_extract(asiento.actividad_id, extract)
        session.add(factura)
        session.flush()
        asiento.factura_id = factura.id
        documento = asiento.documento
        if documento is not None:
            if not session.scalar(
                select(Extraccion.id).where(Extraccion.documento_id == documento.id).limit(1)
            ):
                save_extraccion(session, documento, extract)
            attach_documento(
                session,
                documento=documento,
                extract=extract,
                factura=factura,
                rel_tipo=REL_EVIDENCIA,
                motivo="backfill",
            )
        updated += 1
    return updated


@dataclass
class CorreccionNumero:
    asiento: Asiento
    numero: str
    unido_a: Asiento | None = None
    conflicto_con: Asiento | None = None


def _extract_desde_asiento(asiento: Asiento, numero: str) -> InvoiceExtract:
    return InvoiceExtract(
        emisor=asiento.emisor,
        nif_emisor=asiento.nif_emisor,
        fecha=asiento.fecha,
        numero=numero,
        numero_norm=normalize_numero(numero),
        base=asiento.base,
        iva_tipo=asiento.iva_tipo,
        iva_cuota=asiento.iva_cuota,
        total=asiento.total,
    )


def _mover_evidencias(session: Session, desde_factura_id: int, hacia_factura_id: int) -> None:
    if desde_factura_id == hacia_factura_id:
        return
    filas = session.scalars(
        select(Relacion).where(
            Relacion.destino_tipo == KIND_FACTURA,
            Relacion.destino_id == desde_factura_id,
            Relacion.origen_tipo == KIND_DOCUMENTO,
            Relacion.tipo.in_((REL_EVIDENCIA, REL_CONTINUACION)),
        )
    ).all()
    for fila in filas:
        fila.destino_id = hacia_factura_id


def _fusionar_en(
    session: Session,
    *,
    origen_asiento: Asiento,
    origen_factura: Factura,
    destino_asiento: Asiento,
    destino_factura: Factura,
) -> None:
    extract = _extract_desde_asiento(origen_asiento, destino_factura.numero_visible or origen_asiento.numero_factura or "")
    _enriquecer(destino_factura, extract)
    _mover_evidencias(session, origen_factura.id, destino_factura.id)
    origen_asiento.estado = "duplicado"
    origen_asiento.duplicado_de_id = destino_asiento.id
    origen_asiento.duplicado_nivel = 2
    origen_asiento.factura_id = destino_factura.id
    origen_asiento.numero_factura = destino_factura.numero_visible
    destino_factura.estado_er = ER_PROPUESTA


def corregir_numero(session: Session, asiento: Asiento, numero: str) -> CorreccionNumero:
    """El usuario fija el número visible y se vuelve a agrupar."""
    visible = (numero or "").strip()
    norm = normalize_numero(visible)
    if not norm:
        raise ValueError("Indica un número de factura (no puede estar vacío).")

    if asiento.factura_id is None:
        backfill_asientos(session)

    factura = asiento.factura
    if factura is None:
        extract = _extract_desde_asiento(asiento, visible)
        factura = _factura_desde_extract(asiento.actividad_id, extract)
        session.add(factura)
        session.flush()
        asiento.factura_id = factura.id
        if asiento.documento is not None:
            attach_documento(
                session,
                documento=asiento.documento,
                extract=extract,
                factura=factura,
                rel_tipo=REL_EVIDENCIA,
                motivo="corrección humana",
            )

    asiento.numero_factura = visible
    factura.numero_visible = visible
    factura.numero_norm = norm
    extract = _extract_desde_asiento(asiento, visible)
    if asiento.documento is not None:
        save_extraccion(session, asiento.documento, extract)

    otros = [item for item in _candidatos(session, asiento.actividad_id, extract) if item.id != factura.id]
    if not otros:
        if factura.estado_er == ER_CONFLICTO:
            factura.estado_er = ER_PROPUESTA
        return CorreccionNumero(asiento=asiento, numero=visible)

    compatibles = [item for item in otros if totals_compatible(item.total, asiento.total)]
    if compatibles:
        rival = compatibles[0]
        destino = _asiento_de_factura(session, rival)
        if destino is None or destino.id == asiento.id:
            return CorreccionNumero(asiento=asiento, numero=visible)
        _fusionar_en(
            session,
            origen_asiento=asiento,
            origen_factura=factura,
            destino_asiento=destino,
            destino_factura=rival,
        )
        add_relacion(
            session,
            origen_tipo=KIND_FACTURA,
            origen_id=factura.id,
            destino_tipo=KIND_FACTURA,
            destino_id=rival.id,
            tipo="misma_factura",
            motivo="corrección humana del número",
            fuente="usuario",
        )
        return CorreccionNumero(asiento=asiento, numero=visible, unido_a=destino)

    rival = otros[0]
    factura.estado_er = ER_CONFLICTO
    rival.estado_er = ER_CONFLICTO
    add_relacion(
        session,
        origen_tipo=KIND_FACTURA,
        origen_id=factura.id,
        destino_tipo=KIND_FACTURA,
        destino_id=rival.id,
        tipo=REL_CONFLICTO,
        motivo="corrección humana: mismo número, total distinto",
        fuente="usuario",
    )
    rival_asiento = _asiento_de_factura(session, rival)
    if asiento.estado != "duplicado" and not asiento.validado:
        asiento.estado = "pendiente"
    return CorreccionNumero(asiento=asiento, numero=visible, conflicto_con=rival_asiento)
