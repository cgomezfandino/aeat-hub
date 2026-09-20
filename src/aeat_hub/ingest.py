"""Ingesta de inbox: hash, OCR, parseo, duplicados, clasificación, archivo."""

from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.classify import classify
from aeat_hub.dedupe import DuplicateHit, find_duplicate, find_sha_duplicate
from aeat_hub.extract.parser import parse_invoice
from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.media import file_phash, sha256_file
from aeat_hub.models import Actividad, Asiento, Documento, Inmueble
from aeat_hub.ocr.base import OCRProvider, OCRResult
from aeat_hub.ocr.cascade import transcribe
from aeat_hub.paths import DataLayout

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
    warnings: list[str]


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
) -> IngestItem:
    warnings: list[str] = []
    sha = sha256_file(path)
    existing = find_sha_duplicate(session, sha)
    if existing:
        stored = _archive(path, layout.rejected / "hash", sha, move=from_inbox)
        return IngestItem(stored, None, "duplicado", f"mismo fichero SHA-256 que documento {existing.id}", warnings)

    ocr: OCRResult = transcribe(path, prefer=ocr_prefer, warnings=warnings, rapid=rapid)
    extract = parse_invoice(ocr.text, motor=ocr.engine)
    phash = file_phash(path)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    dup = find_duplicate(session, actividad_id=actividad.id, extract=extract, phash=phash)
    stored = _archive(path, layout.processed, sha, move=from_inbox)

    documento = Documento(
        sha256=sha,
        phash=phash,
        nombre_original=path.name,
        ruta_almacenada=str(stored),
        mime=mime,
        motor_ocr=ocr.engine,
        texto_crudo=ocr.text,
        json_extraido=extract.model_dump_json(),
        confianza=extract.confianza,
    )
    session.add(documento)
    session.flush()

    inmueble = session.scalar(select(Inmueble).where(Inmueble.actividad_id == actividad.id))
    classification = classify(session, actividad, extract, ocr.text)
    asiento = Asiento(
        actividad_id=actividad.id,
        inmueble_id=inmueble.id if inmueble else None,
        documento_id=documento.id,
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
    _apply_duplicate_and_state(asiento, dup, classification.confianza)
    session.add(asiento)
    session.flush()
    detalle = classification.cuenta_codigo or "sin cuenta"
    if dup:
        detalle = f"duplicado nivel {dup.nivel} ({dup.motivo}) → asiento {dup.asiento_id}"
    return IngestItem(stored, asiento.id, asiento.estado, detalle, warnings)


def ingest_inbox(
    session: Session,
    layout: DataLayout,
    actividad: Actividad,
    *,
    ocr_prefer: str = "auto",
    rapid: OCRProvider | None = None,
) -> list[IngestItem]:
    results = []
    for path in list_inbox(layout):
        results.append(
            ingest_file(
                session,
                layout,
                path,
                actividad,
                ocr_prefer=ocr_prefer,
                from_inbox=True,
                rapid=rapid,
            )
        )
    return results


def _apply_duplicate_and_state(asiento: Asiento, dup: DuplicateHit | None, confianza) -> None:
    if dup:
        asiento.estado = "duplicado"
        asiento.duplicado_de_id = dup.asiento_id
        asiento.duplicado_nivel = dup.nivel
        return
    if asiento.cuenta_codigo and confianza >= 0.8:
        asiento.estado = "confirmado"
    else:
        asiento.estado = "pendiente"


def _descripcion(extract: InvoiceExtract, path: Path) -> str:
    if extract.emisor and extract.numero:
        return f"{extract.emisor} · {extract.numero}"
    if extract.emisor:
        return extract.emisor
    return path.name


def _archive(src: Path, dest_dir: Path, sha: str, *, move: bool) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{sha[:12]}_{src.name}"
    if dest.exists():
        dest = dest_dir / f"{sha}_{src.name}"
    if move:
        shutil.move(str(src), str(dest))
    else:
        shutil.copy2(src, dest)
    return dest
