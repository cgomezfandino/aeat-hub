"""Parser heurístico de facturas españolas a partir de texto OCR o PDF nativo."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from dateutil.parser import parse as parse_date

from aeat_hub.extract.ids import normalize_numero
from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.fiscal.money import last_amount, q2
from aeat_hub.fiscal.nif import find_nifs, is_valid_nif, normalize_nif, pick_emisor_receptor

IVA_RATES = (Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0"))

FACTURA_NUM_RE = re.compile(
    r"(?:n[úu]m(?:ero)?(?:\s+de)?\s+factura|factura\s*(?:n[ºo°\.]|num\.?|#)|n[ºo°]\s*(?:de\s*)?factura|n[úu]mero)\s*[:.\-]?\s*([A-Z0-9][A-Z0-9\-\/\.]{1,40})",
    re.IGNORECASE,
)
FACTURA_ID_RE = re.compile(
    r"(?:factura|rectificativa|ificativa)\s+(\d{3}-\d{4}-[A-Z0-9]{5,})",
    re.IGNORECASE,
)
LER_NUM_RE = re.compile(r"\b(\d{3}-\d{4}-R?\d{5,8})\b", re.IGNORECASE)
TICKET_NFS_RE = re.compile(
    r"\b(\d{3}-\d{6}-\d{3}-\d{4}-NFS)\s*[:.\-]?\s*(\d{5,8})\b",
    re.IGNORECASE,
)
PAG_TICKET_RE = re.compile(
    r"\bP[aá]g(?:ina)?\.?\s*(\d{1,3})\s*/\s*(\d{1,3})\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
IVA_RATE_RE = re.compile(r"\biva\s*(?:al\s*)?(\d{1,2}(?:[.,]\d{1,2})?)\s*%", re.IGNORECASE)
TOTAL_TTI_RE = re.compile(r"total\s*(?:tti|tii|111)\b", re.IGNORECASE)
TOTAL_SI_RE = re.compile(r"total\s*si\b|tot\s*si\b", re.IGNORECASE)
TOTAL_IVA_RE = re.compile(r"total\s*iva\b", re.IGNORECASE)

NUMERO_BASURA = {"NIF", "CIF", "IVA", "EUR", "DE", "LA", "EL", "NUMERO", "NÚMERO"}
COMPANY_HINT = re.compile(
    r"(s\.?\s?a\.?u?|s\.?\s?l\.?|sociedad|comunidad|merlin|iberdrola|endesa|naturgy|obrama|bricoman)",
    re.IGNORECASE,
)
SKIP_EMISOR = re.compile(
    r"^(factura|ticket|recibo|página|page|nif|cif|fecha|total|base|iva|cliente|direcci)",
    re.IGNORECASE,
)


def parse_invoice(text: str, *, motor: str = "") -> InvoiceExtract:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    nifs = find_nifs(text or "")
    nif_emisor, nif_receptor = pick_emisor_receptor(nifs)
    numero = _find_numero(text or "")
    pagina_ticket, paginas_ticket = _find_paginacion_ticket(text or "")
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
        numero_norm=normalize_numero(numero),
        pagina_ticket=pagina_ticket,
        paginas_ticket=paginas_ticket,
        base=base,
        iva_tipo=iva_tipo,
        iva_cuota=iva_cuota,
        total=total,
        motor=motor,
    )
    extract.confianza = _confidence(extract)
    return extract


def _find_numero(text: str) -> str | None:
    nfs = TICKET_NFS_RE.search(text)
    if nfs:
        return f"{nfs.group(1).upper()}:{nfs.group(2)}"
    for match in FACTURA_NUM_RE.finditer(text):
        token = match.group(1).strip().rstrip(".")
        if token.upper() in NUMERO_BASURA:
            continue
        return token
    labeled = FACTURA_ID_RE.search(text)
    if labeled:
        return labeled.group(1).upper()
    loose = LER_NUM_RE.search(text)
    if loose:
        return loose.group(1).upper()
    return None


def _find_paginacion_ticket(text: str) -> tuple[int | None, int | None]:
    match = PAG_TICKET_RE.search(text)
    if not match:
        return None, None
    pagina = int(match.group(1))
    total = int(match.group(2))
    if pagina < 1 or total < 1 or pagina > total:
        return None, None
    return pagina, total


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


def _peek_amount(lines: list[str], idx: int, window: int = 6) -> Decimal | None:
    amount = last_amount(lines[idx])
    if amount is not None:
        return amount
    for nxt in lines[idx + 1 : idx + 1 + window]:
        if re.search(r"\btotal\b", nxt.lower()) and last_amount(nxt) is None:
            continue
        amount = last_amount(nxt)
        if amount is not None:
            return amount
    return None


def _iva_triplet(text: str):
    from aeat_hub.fiscal.money import all_amounts

    amounts = all_amounts(text)
    found: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    unique = set(amounts)
    for total in sorted(unique, reverse=True):
        if total in IVA_RATES and any(amount > total for amount in unique):
            continue
        for base in unique:
            if base <= 0 or base >= total:
                continue
            iva = q2(total - base)
            if iva is None or iva <= 0:
                continue
            if not any(abs(iva - item) <= Decimal("0.01") for item in unique):
                continue
            rate = (iva / base) * Decimal("100")
            matched = next((item for item in IVA_RATES if abs(rate - item) < Decimal("0.8")), None)
            if matched is None:
                continue
            found.append((base, iva, total, matched))
    if not found:
        return None
    found.sort(key=lambda row: row[2], reverse=True)
    return found[0]


def _find_importes(lines: list[str], text: str):
    base = iva_cuota = total = iva_tipo = None
    for idx, line in enumerate(lines):
        low = line.lower()
        if re.search(r"\b(total|base|iva|cuota)\b", low):
            amount = _peek_amount(lines, idx, window=2)
        else:
            amount = last_amount(line)
        if amount is None:
            continue
        if "base imponible" in low or (low.startswith("base") and "impon" in low) or TOTAL_SI_RE.search(low):
            base = amount
        elif (re.search(r"\bcuota\b", low) and "iva" in low) or TOTAL_IVA_RE.search(low):
            iva_cuota = amount
        elif TOTAL_TTI_RE.search(low):
            total = amount
        elif re.search(r"\btotal\b", low) and "base" not in low:
            total = amount
        elif "iva" in low and iva_cuota is None and "nif" not in low:
            iva_cuota = amount
    rate = IVA_RATE_RE.search(text)
    if rate:
        iva_tipo = q2(rate.group(1).replace(",", "."))
    triplet = _iva_triplet(text)
    if triplet:
        t_base, t_iva, t_total, t_rate = triplet
        labeled_ok = (
            total is not None
            and base is not None
            and iva_cuota is not None
            and abs((base + iva_cuota) - total) <= Decimal("0.02")
        )
        if not labeled_ok:
            total = t_total
            base = t_base
            iva_cuota = t_iva
            if iva_tipo is None:
                iva_tipo = t_rate
        elif iva_tipo is None:
            iva_tipo = t_rate
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
                candidates: list[str] = []
                for prev in reversed(lines[:idx]):
                    if len(prev) < 4 or SKIP_EMISOR.match(prev) or DATE_RE.search(prev):
                        continue
                    if COMPANY_HINT.search(prev):
                        return prev[:200]
                    candidates.append(prev)
                if candidates:
                    return candidates[-1][:200]
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
