"""Detección de duplicados a tres niveles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from aeat_hub.extract.ids import normalize_emisor, normalize_numero
from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.fiscal.money import q2
from aeat_hub.fiscal.nif import normalize_nif
from aeat_hub.media import hamming_distance
from aeat_hub.models import Asiento, Documento

PHASH_THRESHOLD = 10


@dataclass
class DuplicateHit:
    nivel: int
    asiento_id: int | None
    documento_id: int | None
    motivo: str


def fiscal_key(nif: str | None, numero: str | None, fecha, total: Decimal | None) -> str | None:
    if not nif or not numero or fecha is None or total is None:
        return None
    nif_n = normalize_nif(nif)
    num_n = normalize_numero(numero) or ""
    cents = int(total * 100)
    return f"{nif_n}|{num_n}|{fecha.isoformat()}|{cents}"


def find_sha_duplicate(session: Session, sha256: str) -> Documento | None:
    return session.scalar(select(Documento).where(Documento.sha256 == sha256))


def find_duplicate(
    session: Session,
    *,
    actividad_id: int,
    extract: InvoiceExtract,
    phash: str | None,
    exclude_asiento_id: int | None = None,
) -> DuplicateHit | None:
    fiscal = _fiscal_match(session, actividad_id, extract, exclude_asiento_id)
    if fiscal:
        return fiscal
    by_number = _numero_fecha_total_match(session, actividad_id, extract, exclude_asiento_id)
    if by_number:
        return by_number
    by_sku = _sku_match(session, actividad_id, extract, exclude_asiento_id)
    if by_sku:
        return by_sku
    suspicious = _suspicious_match(session, actividad_id, extract, exclude_asiento_id)
    if suspicious:
        return suspicious
    by_emisor = _emisor_fecha_total_match(session, actividad_id, extract, exclude_asiento_id)
    if by_emisor:
        return by_emisor
    if phash:
        hashed = _phash_match(session, phash, exclude_asiento_id)
        if hashed:
            return hashed
    return None


def _fiscal_match(
    session: Session,
    actividad_id: int,
    extract: InvoiceExtract,
    exclude_asiento_id: int | None,
) -> DuplicateHit | None:
    key = fiscal_key(extract.nif_emisor, extract.numero, extract.fecha, extract.total)
    if not key:
        return None
    rows = session.scalars(
        select(Asiento).where(Asiento.actividad_id == actividad_id, Asiento.estado != "rechazado")
    ).all()
    for row in rows:
        if exclude_asiento_id and row.id == exclude_asiento_id:
            continue
        other = fiscal_key(row.nif_emisor, row.numero_factura, row.fecha, row.total)
        if other and other == key:
            return DuplicateHit(2, row.id, row.documento_id, "NIF+número+fecha+total")
    return None


def _suspicious_match(
    session: Session,
    actividad_id: int,
    extract: InvoiceExtract,
    exclude_asiento_id: int | None,
) -> DuplicateHit | None:
    if not extract.nif_emisor or extract.total is None or extract.fecha is None:
        return None
    nif = normalize_nif(extract.nif_emisor)
    start = extract.fecha - timedelta(days=3)
    end = extract.fecha + timedelta(days=3)
    rows = session.scalars(
        select(Asiento).where(
            Asiento.actividad_id == actividad_id,
            Asiento.nif_emisor == nif,
            Asiento.total == extract.total,
            Asiento.fecha.is_not(None),
        )
    ).all()
    for row in rows:
        if exclude_asiento_id and row.id == exclude_asiento_id:
            continue
        if row.fecha and start <= row.fecha <= end:
            return DuplicateHit(3, row.id, row.documento_id, "mismo NIF+importe±3 días")
    return None


def _numero_key(numero: str | None, fecha, total: Decimal | None) -> str | None:
    if not numero or fecha is None or total is None:
        return None
    num_n = normalize_numero(numero) or ""
    if len(num_n) < 4:
        return None
    cents = int(total * 100)
    return f"{num_n}|{fecha.isoformat()}|{cents}"


def _numero_fecha_total_match(
    session: Session,
    actividad_id: int,
    extract: InvoiceExtract,
    exclude_asiento_id: int | None,
) -> DuplicateHit | None:
    key = _numero_key(extract.numero, extract.fecha, extract.total)
    if not key:
        return None
    rows = session.scalars(
        select(Asiento).where(Asiento.actividad_id == actividad_id, Asiento.estado != "rechazado")
    ).all()
    for row in rows:
        if exclude_asiento_id and row.id == exclude_asiento_id:
            continue
        other = _numero_key(row.numero_factura, row.fecha, row.total)
        if other and other == key:
            return DuplicateHit(2, row.id, row.documento_id, "número+fecha+total")
    return None


def _emisor_fecha_total_match(
    session: Session,
    actividad_id: int,
    extract: InvoiceExtract,
    exclude_asiento_id: int | None,
) -> DuplicateHit | None:
    emisor = normalize_emisor(extract.emisor)
    if emisor is None or extract.total is None or extract.fecha is None:
        return None
    start = extract.fecha - timedelta(days=3)
    end = extract.fecha + timedelta(days=3)
    rows = session.scalars(
        select(Asiento).where(
            Asiento.actividad_id == actividad_id,
            Asiento.total == extract.total,
            Asiento.fecha.is_not(None),
        )
    ).all()
    for row in rows:
        if exclude_asiento_id and row.id == exclude_asiento_id:
            continue
        if normalize_emisor(row.emisor) != emisor:
            continue
        if row.fecha and start <= row.fecha <= end:
            return DuplicateHit(3, row.id, row.documento_id, "mismo emisor+importe±3 días")
    return None


def _sku_match(
    session: Session,
    actividad_id: int,
    extract: InvoiceExtract,
    exclude_asiento_id: int | None,
) -> DuplicateHit | None:
    if extract.total is None or not extract.lineas:
        return None
    codigos_extract = {l.codigo for l in extract.lineas if l.codigo}
    if not codigos_extract:
        return None
    rows = session.scalars(
        select(Asiento)
        .where(
            Asiento.actividad_id == actividad_id,
            Asiento.total == extract.total,
            Asiento.estado != "rechazado",
        )
        .options(joinedload(Asiento.lineas))
    ).unique().all()
    for row in rows:
        if exclude_asiento_id and row.id == exclude_asiento_id:
            continue
        codigos_row = {l.codigo for l in row.lineas if l.codigo and not l.eliminada}
        if codigos_row:
            comunes = codigos_extract.intersection(codigos_row)
            ratio = len(comunes) / min(len(codigos_extract), len(codigos_row))
            if ratio >= 0.6:
                return DuplicateHit(
                    3,
                    row.id,
                    row.documento_id,
                    f"mismo importe + {len(comunes)} artículos coincidentes",
                )
    return None


def _phash_match(session: Session, phash: str, exclude_asiento_id: int | None) -> DuplicateHit | None:
    docs = session.scalars(select(Documento).where(Documento.phash.is_not(None))).all()
    for doc in docs:
        if not doc.phash:
            continue
        if hamming_distance(phash, doc.phash) <= PHASH_THRESHOLD:
            asiento = session.scalar(select(Asiento).where(Asiento.documento_id == doc.id))
            if asiento and exclude_asiento_id and asiento.id == exclude_asiento_id:
                continue
            return DuplicateHit(
                3,
                asiento.id if asiento else None,
                doc.id,
                "imagen casi idéntica (phash)",
            )
    return None


def candidatos_duplicado(session: Session, asiento: Asiento) -> list[dict]:
    """Gemelos evidentes de un asiento para la fusión manual.

    Mismo NIF o mismo emisor + mismo importe con fecha ±3 días, o documento
    casi idéntico por phash. Excluye duplicados confirmados y a sí mismo.
    """
    if asiento.estado == "duplicado":
        return []
    phash = asiento.documento.phash if asiento.documento else None
    rows = session.scalars(
        select(Asiento)
        .where(
            Asiento.actividad_id == asiento.actividad_id,
            Asiento.id != asiento.id,
            Asiento.estado != "duplicado",
        )
        .options(joinedload(Asiento.documento), joinedload(Asiento.lineas))
        .order_by(Asiento.id)
    ).unique().all()
    out: list[dict] = []
    for row in rows:
        motivo = _motivo_gemelo(asiento, row, phash)
        if motivo:
            splink_meta = {}
            try:
                from aeat_hub.linkage_facturas import score_par_splink

                splink_res = score_par_splink(asiento, row)
                if splink_res:
                    prob, peso, desglose = splink_res
                    splink_meta = {
                        "splink_prob": prob,
                        "splink_peso": peso,
                        "splink_desglose": desglose,
                    }
                    if prob >= 0.80:
                        motivo = f"{motivo} · Splink {int(round(prob * 100))} %"
            except Exception:
                pass
            out.append(
                {
                    "id": row.id,
                    "emisor": row.emisor or "sin emisor",
                    "numero": row.numero_factura or "—",
                    "fecha": row.fecha.isoformat() if row.fecha else "—",
                    "total": row.total,
                    "motivo": motivo,
                    **splink_meta,
                }
            )
    _PRIORIDAD = {
        "mismo NIF + importe ±3 días": 0,
        "mismo emisor + importe ±3 días": 1,
        "mismo NIF + importe (ventana 60 días)": 2,
        "mismo emisor + importe (ventana 60 días)": 3,
        "imagen casi idéntica (phash)": 4,
    }

    def _rank(item: dict) -> int:
        if "artículos coincidentes" in item["motivo"]:
            return -1
        return _PRIORIDAD.get(item["motivo"], 5)

    out.sort(key=lambda item: (_rank(item), item["id"]))
    return out


def _motivo_gemelo(asiento: Asiento, row: Asiento, phash: str | None) -> str | None:
    gemelo_phash = bool(
        phash
        and row.documento
        and row.documento.phash
        and hamming_distance(phash, row.documento.phash) <= PHASH_THRESHOLD
    )
    importes_iguales = (
        asiento.total is not None
        and row.total is not None
        and q2(asiento.total) == q2(row.total)
    )
    if gemelo_phash:
        return "imagen casi idéntica (phash)"
    if not importes_iguales:
        return None

    # Coincidencia por artículos / SKU:
    # Si coinciden en importe y comparten >= 60% de los códigos de artículo (SKUs),
    # son gemelos evidentes aunque la fecha de emisión de la factura formal sea posterior al ticket
    codigos_a = {l.codigo for l in asiento.lineas if l.codigo and not l.eliminada}
    codigos_b = {l.codigo for l in row.lineas if l.codigo and not l.eliminada}
    if codigos_a and codigos_b:
        comunes = codigos_a.intersection(codigos_b)
        ratio = len(comunes) / min(len(codigos_a), len(codigos_b))
        if ratio >= 0.6:
            return f"mismo importe + {len(comunes)} artículos coincidentes"

    nif = bool(asiento.nif_emisor and row.nif_emisor == asiento.nif_emisor)
    emisor = bool(
        normalize_emisor(asiento.emisor)
        and normalize_emisor(asiento.emisor) == normalize_emisor(row.emisor)
    )

    ventana = (
        asiento.fecha is not None
        and row.fecha is not None
        and abs((asiento.fecha - row.fecha).days) <= 3
    )
    if ventana:
        if nif:
            return "mismo NIF + importe ±3 días"
        if emisor:
            return "mismo emisor + importe ±3 días"

    ventana_ext = (
        asiento.fecha is not None
        and row.fecha is not None
        and abs((asiento.fecha - row.fecha).days) <= 60
    )
    if ventana_ext:
        if nif:
            return "mismo NIF + importe (ventana 60 días)"
        if emisor:
            return "mismo emisor + importe (ventana 60 días)"

    return None
