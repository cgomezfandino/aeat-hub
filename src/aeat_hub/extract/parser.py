"""Parser heurístico de facturas españolas a partir de texto OCR o PDF nativo."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from dateutil.parser import parse as parse_date

from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.fiscal.money import last_amount, q2
from aeat_hub.fiscal.nif import find_nifs, is_valid_nif, normalize_nif

IVA_RATES = (Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0"))

FACTURA_NUM_RE = re.compile(
    r"(?:n[úu]m(?:ero)?(?:\s+de)?\s+factura|factura\s*(?:n[ºo°\.]|num\.?|#)|n[ºo°]\s*(?:de\s*)?factura|n[úu]mero)\s*[:.\-]?\s*([A-Z0-9][A-Z0-9\-\/\.]{1,40})",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
IVA_RATE_RE = re.compile(r"\biva\s*(?:al\s*)?(\d{1,2}(?:[.,]\d{1,2})?)\s*%", re.IGNORECASE)

SKIP_EMISOR = re.compile(
    r"^(factura|ticket|recibo|página|page|nif|cif|fecha|total|base|iva|cliente|direcci)",
    re.IGNORECASE,
)


def parse_invoice(text: str, *, motor: str = "") -> InvoiceExtract:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    nifs = find_nifs(text or "")
    nif_emisor = nifs[0] if nifs else None
    nif_receptor = nifs[1] if len(nifs) > 1 else None
    numero = _find_numero(text or "")
    fecha = _find_fecha(text or "", lines)
    base, iva_cuota, total, iva_tipo = _find_importes(lines, text or "")
    emisor = _find_emisor(lines, nif_emisor)
    extract = InvoiceExtract(
        emisor=emisor,
        nif_emisor=nif_emisor,
        nif_emisor_valido=bool(nif_emisor and is_valid_nif(nif_emisor)),
        nif_receptor=nif_receptor,
        fecha=fecha,
        numero=numero,
        base=base,
        iva_tipo=iva_tipo,
        iva_cuota=iva_cuota,
        total=total,
        motor=motor,
    )
    extract.confianza = _confidence(extract)
    return extract


def _find_numero(text: str) -> str | None:
    match = FACTURA_NUM_RE.search(text)
    if not match:
        return None
    return match.group(1).strip().rstrip(".")


def _parse_date_token(token: str) -> date | None:
    try:
        parsed = parse_date(token, dayfirst=True, yearfirst=False)
    except (ValueError, OverflowError, TypeError):
        return None
    if parsed.year < 1990 or parsed.year > 2100:
        return None
    return parsed.date()


def _find_fecha(text: str, lines: list[str]) -> date | None:
    for line in lines:
        if "fecha" in line.lower():
            match = DATE_RE.search(line)
            if match:
                parsed = _parse_date_token(match.group(1))
                if parsed:
                    return parsed
    match = DATE_RE.search(text)
    if match:
        return _parse_date_token(match.group(1))
    return None


def _find_importes(lines: list[str], text: str):
    base = iva_cuota = total = iva_tipo = None
    for line in lines:
        low = line.lower()
        amount = last_amount(line)
        if amount is None:
            continue
        if "base imponible" in low or (low.startswith("base") and "impon" in low):
            base = amount
        elif re.search(r"\bcuota\b", low) and "iva" in low:
            iva_cuota = amount
        elif re.search(r"\btotal\b", low) and "base" not in low:
            total = amount
        elif "iva" in low and iva_cuota is None and "nif" not in low:
            iva_cuota = amount
    rate = IVA_RATE_RE.search(text)
    if rate:
        iva_tipo = q2(rate.group(1).replace(",", "."))
    if total is None and base is not None and iva_cuota is not None:
        total = q2(base + iva_cuota)
    if base is None and total is not None and iva_cuota is not None:
        base = q2(total - iva_cuota)
    if iva_tipo is None and base and iva_cuota and base != 0:
        approx = (iva_cuota / base) * Decimal("100")
        for candidate in IVA_RATES:
            if abs(approx - candidate) < Decimal("0.6"):
                iva_tipo = candidate
                break
    return base, iva_cuota, total, iva_tipo


def _find_emisor(lines: list[str], nif_emisor: str | None) -> str | None:
    if nif_emisor:
        needle = normalize_nif(nif_emisor)
        for idx, line in enumerate(lines):
            if needle in normalize_nif(line):
                for prev in reversed(lines[:idx]):
                    if len(prev) >= 4 and not SKIP_EMISOR.match(prev) and not DATE_RE.search(prev):
                        return prev[:200]
                break
    for line in lines[:8]:
        if SKIP_EMISOR.match(line):
            continue
        if len(line) >= 4 and not DATE_RE.fullmatch(line):
            return line[:200]
    return None


def _confidence(extract: InvoiceExtract) -> float:
    score = 0.0
    if extract.nif_emisor_valido:
        score += 0.25
    if extract.fecha:
        score += 0.2
    if extract.numero:
        score += 0.15
    if extract.total is not None:
        score += 0.25
    if extract.base is not None:
        score += 0.1
    if extract.emisor:
        score += 0.05
    return round(min(score, 0.99), 3)
