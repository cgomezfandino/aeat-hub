"""Consenso Vision + RapidOCR: mismos campos, dos lecturas, discrepancias explícitas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from aeat_hub.evals.metrics import compact_alnum, similarity
from aeat_hub.extract.parser import parse_invoice
from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.fiscal.nif import is_valid_nif, normalize_nif
from aeat_hub.ocr.apple_vision import AppleVisionProvider
from aeat_hub.ocr.base import OCRProvider, OCRResult, ProviderUnavailable
from aeat_hub.ocr.rapid import RapidOCRProvider

COMPARE_FIELDS = (
    "emisor",
    "nif_emisor",
    "nif_receptor",
    "numero",
    "fecha",
    "base",
    "iva_cuota",
    "total",
)

STATUS_ACUERDO = "acuerdo"
STATUS_SOLO_A = "solo_vision"
STATUS_SOLO_B = "solo_rapid"
STATUS_CONFLICTO = "conflicto"
STATUS_VACIO = "vacio"


@dataclass
class FieldVote:
    campo: str
    vision: str
    rapid: str
    consenso: str
    estado: str
    regla: str


@dataclass
class EngineRead:
    engine: str
    available: bool
    reason: str = ""
    latency_ms: int = 0
    chars: int = 0
    text: str = ""
    extract: InvoiceExtract | None = None


@dataclass
class DualDocument:
    path: Path
    case_id: str
    vision: EngineRead
    rapid: EngineRead
    votes: list[FieldVote]
    recomendacion: str
    acuerdos: int = 0
    conflictos: int = 0
    huecos: int = 0


def fmt_value(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value).strip()


def values_match(campo: str, left: str, right: str) -> bool:
    if not left and not right:
        return True
    if not left or not right:
        return False
    if campo.startswith("nif_"):
        return normalize_nif(left) == normalize_nif(right)
    if campo == "numero":
        a, b = compact_alnum(left), compact_alnum(right)
        return bool(a and b) and (a == b or a in b or b in a)
    if campo in {"base", "iva_cuota", "total"}:
        try:
            return abs(Decimal(left) - Decimal(right)) <= Decimal("0.01")
        except Exception:  # noqa: BLE001
            return left == right
    if campo == "emisor":
        return similarity(compact_alnum(left), compact_alnum(right)) >= 0.72
    if campo == "fecha":
        return left == right
    return compact_alnum(left) == compact_alnum(right)


def vote_field(campo: str, vision: str, rapid: str, *, text_a: str, text_b: str) -> FieldVote:
    v, r = vision.strip(), rapid.strip()
    if not v and not r:
        return FieldVote(campo, v, r, "", STATUS_VACIO, "ningún motor sacó el campo")
    if v and r and values_match(campo, v, r):
        return FieldVote(campo, v, r, v if len(v) >= len(r) else r, STATUS_ACUERDO, "ambos coinciden")
    if v and not r:
        return FieldVote(campo, v, r, v, STATUS_SOLO_A, "solo Vision; RapidOCR vacío")
    if r and not v:
        return FieldVote(campo, v, r, r, STATUS_SOLO_B, "solo RapidOCR; Vision vacío")
    consenso, regla = _break_tie(campo, v, r, text_a, text_b)
    return FieldVote(campo, v, r, consenso, STATUS_CONFLICTO, regla)


def _break_tie(campo: str, vision: str, rapid: str, text_a: str, text_b: str) -> tuple[str, str]:
    if campo.startswith("nif_"):
        v_ok, r_ok = is_valid_nif(vision), is_valid_nif(rapid)
        if v_ok and not r_ok:
            return vision, "conflicto: se queda el NIF con dígito de control válido (Vision)"
        if r_ok and not v_ok:
            return rapid, "conflicto: se queda el NIF con dígito de control válido (RapidOCR)"
        return "", "conflicto: dos NIF distintos; hay que revisar"
    if campo in {"base", "iva_cuota", "total"}:
        in_both_v = _amount_in_both_texts(vision, text_a, text_b)
        in_both_r = _amount_in_both_texts(rapid, text_a, text_b)
        if in_both_v and not in_both_r:
            return vision, "conflicto: el importe de Vision aparece en ambos textos"
        if in_both_r and not in_both_v:
            return rapid, "conflicto: el importe de RapidOCR aparece en ambos textos"
        return "", "conflicto: importes distintos; no se promedian"
    if campo == "numero":
        # El más largo suele ser el número completo (064-0009-720394 vs 064).
        chosen = vision if len(compact_alnum(vision)) >= len(compact_alnum(rapid)) else rapid
        return chosen, "conflicto: se propone el número más completo; revisar"
    return "", "conflicto: valores distintos; hay que revisar"


def _amount_in_both_texts(amount: str, text_a: str, text_b: str) -> bool:
    from aeat_hub.evals.metrics import field_in_ocr

    return field_in_ocr("total", amount, text_a) and field_in_ocr("total", amount, text_b)


def recommend(votes: list[FieldVote]) -> str:
    criticos = {"nif_emisor", "numero", "fecha", "total"}
    if any(item.estado == STATUS_CONFLICTO and item.campo in criticos for item in votes):
        return "revisar"
    if any(item.estado == STATUS_VACIO and item.campo in {"nif_emisor", "total"} for item in votes):
        return "revisar"
    if any(item.estado == STATUS_CONFLICTO for item in votes):
        return "revisar_menor"
    if all(item.estado in {STATUS_ACUERDO, STATUS_SOLO_A, STATUS_SOLO_B} for item in votes if item.campo in criticos):
        return "consenso"
    return "revisar"


def compare_extracts(
    extract_a: InvoiceExtract,
    extract_b: InvoiceExtract,
    *,
    text_a: str,
    text_b: str,
) -> list[FieldVote]:
    votes = []
    for campo in COMPARE_FIELDS:
        votes.append(
            vote_field(
                campo,
                fmt_value(getattr(extract_a, campo, None)),
                fmt_value(getattr(extract_b, campo, None)),
                text_a=text_a,
                text_b=text_b,
            )
        )
    return votes


def run_dual(
    path: Path,
    *,
    case_id: str | None = None,
    vision: OCRProvider | None = None,
    rapid: OCRProvider | None = None,
) -> DualDocument:
    path = Path(path)
    vis_read = _read(vision or AppleVisionProvider(), path)
    rapid_read = _read(rapid or RapidOCRProvider(), path)
    extract_a = vis_read.extract or InvoiceExtract(motor="apple-vision")
    extract_b = rapid_read.extract or InvoiceExtract(motor="rapidocr")
    votes = compare_extracts(extract_a, extract_b, text_a=vis_read.text, text_b=rapid_read.text)
    rec = recommend(votes)
    return DualDocument(
        path=path,
        case_id=case_id or path.stem,
        vision=vis_read,
        rapid=rapid_read,
        votes=votes,
        recomendacion=rec,
        acuerdos=sum(1 for item in votes if item.estado == STATUS_ACUERDO),
        conflictos=sum(1 for item in votes if item.estado == STATUS_CONFLICTO),
        huecos=sum(1 for item in votes if item.estado in {STATUS_VACIO, STATUS_SOLO_A, STATUS_SOLO_B}),
    )


def _read(provider: OCRProvider, path: Path) -> EngineRead:
    import time

    ok, reason = provider.available()
    if not ok:
        return EngineRead(engine=provider.name, available=False, reason=reason)
    t0 = time.perf_counter()
    try:
        result = provider.transcribe(path)
    except ProviderUnavailable as exc:
        return EngineRead(
            engine=provider.name,
            available=False,
            reason=str(exc),
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
    ms = int((time.perf_counter() - t0) * 1000)
    extract = parse_invoice(result.text or "", motor=result.engine)
    return EngineRead(
        engine=result.engine,
        available=True,
        latency_ms=ms,
        chars=len(result.text or ""),
        text=result.text or "",
        extract=extract,
    )
