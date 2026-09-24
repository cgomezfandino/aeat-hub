"""Ingesta de inbox: hash, OCR, parseo, duplicados, clasificación, archivo."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.classify import classify
from aeat_hub.dedupe import DuplicateHit, find_duplicate, find_sha_duplicate
from aeat_hub.edits import replace_lineas
from aeat_hub.er import cluster_documento, save_extraccion
from aeat_hub.extract.ids import normalize_emisor
from aeat_hub.extract.parser import parse_invoice
from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.filing import place_file, relocate_asiento, relocate_documento
from aeat_hub.media import file_phash, sha256_file
from aeat_hub.models import Actividad, Asiento, Documento, Inmueble
from aeat_hub.ocr.base import OCRProvider, OCRResult
from aeat_hub.ocr.cascade import transcribe
from aeat_hub.paths import DataLayout
from aeat_hub.pipeline import etapa, log_detalle

INGEST_SUFFIXES = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}


@dataclass
class IngestItem:
    path: Path
    asiento_id: int | None
    estado: str
    detalle: str
    warnings: list[str] = field(default_factory=list)
    etapa_error: str | None = None


def _descuadre_lineas(extract: InvoiceExtract) -> Decimal | None:
    """Cuánto se aleja la suma de las líneas con importe del total de la factura."""
    if extract.total is None:
        return None
    importes = [
        linea.importe
        for linea in extract.lineas
        if linea.importe is not None and (linea.descripcion or linea.codigo)
    ]
    if not importes:
        return extract.total
    return abs(sum(importes, Decimal("0.00")) - extract.total)


def _reintentar_si_no_cuadra(
    path: Path,
    ocr: OCRResult,
    extract: InvoiceExtract,
    notes: list[str],
    *,
    rapid: OCRProvider | None,
) -> tuple[OCRResult, InvoiceExtract]:
    """Si las líneas no suman el total, prueba el otro motor de imagen una vez."""
    gap = _descuadre_lineas(extract)
    if gap is None or gap <= Decimal("0.05") or rapid is not None:
        return ocr, extract
    alt_prefer = "rapid" if ocr.engine == "apple-vision" else "vision"
    notes.append("La suma de las líneas no coincide con el total. Se reintenta la lectura.")
    try:
        alt = transcribe(path, prefer=alt_prefer, warnings=notes)
    except Exception:
        return ocr, extract
    if not alt.text.strip() or alt.engine == ocr.engine:
        notes.append("La segunda lectura no aporta otro texto.")
        return ocr, extract
    alt_extract = parse_invoice(alt.text, motor=alt.engine)
    alt_gap = _descuadre_lineas(alt_extract)
    if alt_gap is not None and alt_gap < gap:
        notes.append(f"La segunda lectura ({alt.engine}) encaja mejor.")
        return alt, alt_extract
    notes.append("La segunda lectura no mejora el desglose. Se queda la primera.")
    return ocr, extract


def list_inbox(layout: DataLayout) -> list[Path]:
    files = [
        path
        for path in sorted(layout.inbox.iterdir())
        if path.is_file() and path.suffix.lower() in INGEST_SUFFIXES and not path.name.startswith(".")
    ]
    return files


def ingest_file(
    session: Session,
    layout: DataLayout,
    path: Path,
    actividad: Actividad,
    *,
    ocr_prefer: str = "auto",
    from_inbox: bool = True,
    rapid: OCRProvider | None = None,
    probe: dict[str, str] | None = None,
) -> IngestItem:
    name = path.name
    warnings: list[str] = []

    with etapa("recibir", name):
        log_detalle("recibir", "%s (%s bytes)", name, path.stat().st_size)

    with etapa("hash", name):
        sha = sha256_file(path)
        if probe is not None:
            probe["sha"] = sha
        log_detalle("hash", "sha256=%s", sha)

    with etapa("duplicado-fichero", name):
        existing = find_sha_duplicate(session, sha)
        if existing:
            dest = layout.rejected / "hash" / f"{sha[:12]}_{path.name}"
            stored = place_file(path, dest, move=from_inbox)
            log_detalle(
                "duplicado-fichero",
                "mismo SHA que documento id=%s → %s",
                existing.id,
                stored,
            )
            return IngestItem(
                stored,
                None,
                "duplicado",
                f"mismo fichero SHA-256 que documento {existing.id}",
                warnings,
            )
        log_detalle("duplicado-fichero", "no hay duplicado de fichero")

    with etapa("ocr", name):
        ocr: OCRResult = transcribe(path, prefer=ocr_prefer, warnings=warnings, rapid=rapid)
        log_detalle(
            "ocr",
            "motor=%s confianza=%.3f paginas=%s chars=%s avisos=%s",
            ocr.engine,
            ocr.confidence,
            ocr.pages,
            len(ocr.text),
            warnings or "-",
        )

    with etapa("parsear", name):
        extract = parse_invoice(ocr.text, motor=ocr.engine)
        ocr, extract = _reintentar_si_no_cuadra(path, ocr, extract, warnings, rapid=rapid)
        log_detalle(
            "parsear",
            "emisor=%s nif=%s numero=%s fecha=%s total=%s confianza=%.3f",
            extract.emisor,
            extract.nif_emisor,
            extract.numero,
            extract.fecha,
            extract.total,
            extract.confianza,
        )

    with etapa("duplicado-fiscal", name):
        phash = file_phash(path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        dup = find_duplicate(session, actividad_id=actividad.id, extract=extract, phash=phash)
        if dup:
            log_detalle(
                "duplicado-fiscal",
                "nivel=%s motivo=%s asiento=%s",
                dup.nivel,
                dup.motivo,
                dup.asiento_id,
            )
        else:
            log_detalle("duplicado-fiscal", "no hay duplicado fiscal/sospechoso")

    with etapa("clasificar", name):
        classification = classify(session, actividad, extract, ocr.text)
        log_detalle(
            "clasificar",
            "cuenta=%s tipo=%s origen=%s confianza=%s",
            classification.cuenta_codigo,
            classification.tipo,
            classification.origen,
            classification.confianza,
        )

    with etapa("guardar", name):
        documento = Documento(
            sha256=sha,
            phash=phash,
            nombre_original=path.name,
            ruta_almacenada=str(path.resolve()),
            mime=mime,
            motor_ocr=ocr.engine,
            texto_crudo=ocr.text,
            json_extraido=extract.model_dump_json(),
            confianza=extract.confianza,
            paginas=max(ocr.pages, 1),
        )
        session.add(documento)
        session.flush()
        save_extraccion(session, documento, extract)
        factura, asiento_existente, rel_tipo, conflicto = cluster_documento(
            session,
            actividad_id=actividad.id,
            documento=documento,
            extract=extract,
        )
        inmueble = session.scalar(
            select(Inmueble).where(Inmueble.actividad_id == actividad.id).order_by(Inmueble.id)
        )
        if asiento_existente is not None:
            stored = relocate_documento(
                session, layout, asiento_existente, documento, move=from_inbox
            ) or Path(documento.ruta_almacenada)
            log_detalle(
                "guardar",
                "evidencia documento=%s factura=%s asiento=%s rel=%s",
                documento.id,
                factura.id,
                asiento_existente.id,
                rel_tipo,
            )
            return IngestItem(
                stored,
                asiento_existente.id,
                asiento_existente.estado,
                f"{rel_tipo} factura {factura.id} → asiento {asiento_existente.id}",
                warnings,
            )
        asiento = Asiento(
            actividad_id=actividad.id,
            inmueble_id=inmueble.id if inmueble else None,
            documento_id=documento.id,
            factura_id=factura.id,
            tipo=classification.tipo,
            cuenta_codigo=classification.cuenta_codigo,
            fecha=extract.fecha,
            ejercicio=extract.fecha.year if extract.fecha else None,
            emisor=extract.emisor,
            nif_emisor=extract.nif_emisor,
            numero_factura=extract.numero,
            descripcion=_descripcion(extract, path),
            base=extract.base,
            iva_tipo=extract.iva_tipo,
            iva_cuota=extract.iva_cuota,
            total=extract.total,
            confianza_clasificacion=classification.confianza,
            origen_clasificacion=classification.origen,
            estado="pendiente",
        )
        if conflicto:
            asiento.estado = "pendiente"
        else:
            _apply_duplicate_and_state(
                asiento,
                dup,
                classification.confianza,
                con_numero=bool(extract.numero_norm or extract.numero),
            )
        session.add(asiento)
        session.flush()
        replace_lineas(session, asiento, extract.lineas)
        log_detalle("guardar", "documento=%s asiento=%s factura=%s estado=%s", documento.id, asiento.id, factura.id, asiento.estado)

    with etapa("archivar", name):
        stored = relocate_asiento(session, layout, asiento, move=from_inbox) or Path(
            documento.ruta_almacenada
        )
        log_detalle("archivar", "destino=%s", stored)

    detalle = classification.cuenta_codigo or "sin cuenta"
    if conflicto:
        detalle = f"conflicto factura {factura.id} (mismo número, total distinto)"
    elif dup:
        etiqueta = "duplicado" if asiento.estado == "duplicado" else "sospechoso"
        detalle = f"{etiqueta} nivel {dup.nivel} ({dup.motivo}) → asiento {dup.asiento_id}"
    return IngestItem(stored, asiento.id, asiento.estado, detalle, warnings)


def ingest_inbox(
    session: Session,
    layout: DataLayout,
    actividad: Actividad,
    *,
    ocr_prefer: str = "auto",
    rapid: OCRProvider | None = None,
) -> list[IngestItem]:
    results: list[IngestItem] = []
    files = list_inbox(layout)
    log_detalle("lote", "inbox=%s ficheros=%s", layout.inbox, [p.name for p in files])
    for path in files:
        probe: dict[str, str] = {}
        try:
            item = ingest_file(
                session,
                layout,
                path,
                actividad,
                ocr_prefer=ocr_prefer,
                from_inbox=True,
                rapid=rapid,
                probe=probe,
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            ya_movido = not path.exists()
            stored = _quarantine(layout, path, probe.get("sha", ""))
            if ya_movido:
                log_detalle(
                    "lote",
                    "error tras archivar %s: fichero rescatado de archivo/ a %s",
                    path.name,
                    stored,
                )
            results.append(
                IngestItem(
                    stored,
                    None,
                    "error",
                    str(exc),
                    etapa_error=_etapa_from_exc(exc),
                )
            )
            log_detalle("lote", "sigue con el siguiente fichero tras error en %s", path.name)
        else:
            # El asiento solo cuenta como éxito cuando el commit ha persistido.
            results.append(item)
    return results


def _quarantine(layout: DataLayout, path: Path, sha: str = "") -> Path:
    dest = layout.rejected / "error" / path.name
    if path.exists():
        return place_file(path, dest, move=True)
    if sha:
        # El lote falló después de mover el fichero a archivo/ y el rollback
        # no devuelve ficheros: hay que rescatarlo para que no quede huérfano.
        for moved in sorted(layout.archivo.rglob(f"{sha[:12]}_*")):
            if moved.is_file():
                return place_file(moved, dest, move=True)
    return dest


def _etapa_from_exc(exc: BaseException) -> str:
    text = str(exc)
    return text[:80] if text else exc.__class__.__name__


def _apply_duplicate_and_state(
    asiento: Asiento,
    dup: DuplicateHit | None,
    confianza,
    *,
    con_numero: bool = False,
) -> None:
    if dup:
        asiento.duplicado_de_id = dup.asiento_id
        asiento.duplicado_nivel = dup.nivel
        if not con_numero or dup.nivel <= 2:
            asiento.estado = "duplicado"
        else:
            # Con número distinto no se marca duplicado sin más: la misma
            # compra puede aparecer con número de factura y de servicio.
            # Queda pendiente como sospechoso para revisión humana.
            asiento.estado = "pendiente"
        return
    if asiento.cuenta_codigo and confianza >= 0.8:
        asiento.estado = "confirmado"
    else:
        asiento.estado = "pendiente"


def reparse_asientos(session: Session, actividad: Actividad) -> int:
    """Vuelve a extraer emisor/fecha/importes desde el texto OCR ya guardado.

    No toca asientos validados por el usuario: el libro humano gana al modelo.
    """
    updated = 0
    rows = session.scalars(select(Asiento).where(Asiento.actividad_id == actividad.id)).all()
    for asiento in rows:
        if asiento.validado:
            continue
        if asiento.documento_id is None:
            continue
        documento = session.get(Documento, asiento.documento_id)
        if documento is None or not (documento.texto_crudo or "").strip():
            continue
        extract = parse_invoice(documento.texto_crudo, motor=documento.motor_ocr)
        factura = asiento.factura
        divergencia = _divergencias_con_factura(asiento, factura)
        asiento.emisor = extract.emisor
        asiento.nif_emisor = extract.nif_emisor
        asiento.fecha = extract.fecha
        asiento.ejercicio = extract.fecha.year if extract.fecha else asiento.ejercicio
        asiento.numero_factura = extract.numero
        asiento.base = extract.base
        asiento.iva_tipo = extract.iva_tipo
        asiento.iva_cuota = extract.iva_cuota
        asiento.total = extract.total
        asiento.descripcion = _descripcion(extract, Path(documento.nombre_original))
        _sync_factura_reparse(factura, extract, divergencia)
        documento.json_extraido = extract.model_dump_json()
        documento.confianza = extract.confianza
        replace_lineas(session, asiento, extract.lineas)
        if asiento.estado != "duplicado":
            classification = classify(session, actividad, extract, documento.texto_crudo)
            asiento.cuenta_codigo = classification.cuenta_codigo
            asiento.tipo = classification.tipo
            asiento.origen_clasificacion = classification.origen
            asiento.confianza_clasificacion = classification.confianza
            _apply_duplicate_and_state(asiento, None, classification.confianza)
        updated += 1
    return updated


_CAMPOS_REPARSE = ("emisor", "nif_emisor", "fecha", "base", "iva_tipo", "iva_cuota", "total")


def _divergencias_con_factura(asiento: Asiento, factura) -> set[str]:
    """Campos donde asiento y factura ya no coinciden: corrección humana."""
    if factura is None:
        return set()
    return {
        campo
        for campo in _CAMPOS_REPARSE
        if getattr(asiento, campo) != getattr(factura, campo)
    }


def _sync_factura_reparse(factura, extract: InvoiceExtract, divergencia: set[str]) -> None:
    """Refresca la factura canónica con el reparse para que ER no compare contra
    importes caducados. El número no se toca: la identidad de la factura la
    gestiona `aeat-hub factura numero`, y los campos divergentes se respetan."""
    if factura is None:
        return
    for campo in _CAMPOS_REPARSE:
        if campo in divergencia:
            continue
        setattr(factura, campo, getattr(extract, campo))
    factura.emisor_norm = normalize_emisor(factura.emisor)


def _descripcion(extract: InvoiceExtract, path: Path) -> str:
    if extract.emisor and extract.numero:
        return f"{extract.emisor} · {extract.numero}"
    if extract.emisor:
        return extract.emisor
    return path.name
