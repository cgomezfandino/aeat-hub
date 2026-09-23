"""Parser heurístico de facturas españolas a partir de texto OCR o PDF nativo."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from dateutil.parser import parse as parse_date

from aeat_hub.extract.ids import normalize_numero
from aeat_hub.extract.schema import InvoiceExtract, InvoiceLine
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
    r"(?<![A-Za-zÁÉÍÓÚÜÑáéíóúüñ])(?:"
    r"s\.?\s?a\.?(?:\s?u\.?)?"
    r"|s\.?\s?l\.?(?:\s?u\.?)?"
    r"|sociedad|comunidad|merlin|iberdrola|endesa|naturgy|obrama|bricoman"
    r")(?![A-Za-zÁÉÍÓÚÜÑáéíóúüñ])",
    re.IGNORECASE,
)
SKIP_EMISOR = re.compile(
    r"^(factura|ticket|recibo|página|page|nif|cif|fecha|total|base|iva|cliente|direcci)",
    re.IGNORECASE,
)
SKIP_LINEA = re.compile(
    r"\b(total|base|iva|igic|ipsi|nif|cif|fecha|factura|cliente|direcci|"
    r"p[aá]g(?:ina)?|original|ticket|emisor|receptor|cuota|tti|tii|cambio|"
    r"visa|mastercard|efectivo|importe|duplicado|ejemplar|observacion|"
    r"condiciones|tarjeta|telefono|teléfono|registro mercantil)\b",
    re.IGNORECASE,
)
SKIP_CONTEXTO = re.compile(
    r"(^c/|^calle |^avda|^avenida |^plaza |^tlf|^fax|www\.|https?://|"
    r"registro de productor|mencionados sobre|designaci[oó]n|"
    r"modos de pago|consulta el estado|leroymerlin|"
    r"arroyo de la|alcobendas|valladolid|rio shopping|mayorazgo|"
    r"folio|inscripci[oó]n|secci[oó]n|hoja m-|tarj\.|"
    r"raz[oó]n social|"
    r"numero de cuenta|numero de tarjeta)",
    re.IGNORECASE,
)
TRAILING_AMOUNT = re.compile(r"[\d.,]+\s*€?\s*$")
ONLY_NUM = re.compile(r"^[\d.\s/:-]+$")
HAS_LETTER = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")
HEADER_LINE = re.compile(
    r"^(precio|unidad|cantidad|venta|observaciones|españa|unid\.?|uid\.?|"
    r"eur|\(eur\)|m\(eur\)|totsi|prec|descu\.?|jardiner[íi]a|"
    r"decoraci[oó]n|construcci[oó]n|bricolaje|original|duplicado|"
    r"uni\.?si|unid\.?\s*si|ivai?|igic|ipsi|tasa|n['´].*mbro)$",
    re.IGNORECASE,
)
DESIGNACION_RE = re.compile(r"designaci[oó]n|referencia\s+artic", re.IGNORECASE)
INDEX_LINE = re.compile(r"^\d{1,2}$")
REF_STANDALONE = re.compile(r"^\d{7,8}$")
CODIGO_LINEA_RE = re.compile(r"^(?:\d{1,2}\.\s*)?(\d{7,8})$")


def _codigo_de_token(token: str) -> str | None:
    """Código de artículo. El OCR a veces deja un punto detrás (10110884.)."""
    match = CODIGO_LINEA_RE.fullmatch(token.strip().rstrip(".,;:"))
    return match.group(1) if match else None
REF_TOKEN = re.compile(r"^[A-Za-z0-9]{5,14}$")


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
        lineas=_find_lineas(lines, total=total, base=base, iva_tipo=iva_tipo),
        motor=motor,
    )
    extract.confianza = _confidence(extract)
    return extract


def _find_numero(text: str) -> str | None:
    labeled = FACTURA_ID_RE.search(text)
    if labeled:
        return labeled.group(1).upper()
    for match in FACTURA_NUM_RE.finditer(text):
        token = match.group(1).strip().rstrip(".")
        if token.upper() in NUMERO_BASURA:
            continue
        return token
    nfs = TICKET_NFS_RE.search(text)
    if nfs:
        return f"{nfs.group(1).upper()}:{nfs.group(2)}"
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


def _region_articulos(lines: list[str]) -> list[str]:
    for idx, line in enumerate(lines):
        if DESIGNACION_RE.search(line):
            return lines[idx + 1 :]
    return lines


def _is_amount_only(line: str) -> bool:
    if last_amount(line) is None:
        return False
    stripped = re.sub(r"(?i)EUR|€", "", line)
    return not HAS_LETTER.search(stripped)


def _is_ref_articulo(line: str) -> bool:
    token = line.strip()
    if not REF_TOKEN.fullmatch(token):
        return False
    digits = sum(ch.isdigit() for ch in token)
    if digits < 2:
        return False
    if DATE_RE.search(token) or find_nifs(token):
        return False
    return True


def _skip_linea_contexto(line: str) -> bool:
    if SKIP_LINEA.search(line) or SKIP_CONTEXTO.search(line):
        return True
    if DATE_RE.search(line) or LER_NUM_RE.search(line) or TICKET_NFS_RE.search(line):
        return True
    if re.search(
        r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|octubre|noviembre|diciembre)\b",
        line,
        re.IGNORECASE,
    ):
        return True
    if find_nifs(line) and len(re.sub(r"[\s\-]", "", line)) <= 14:
        return True
    return False


def _importes_tti(lines: list[str]) -> list[Decimal]:
    """Columna «Importe TTI»: total de cada línea (cantidad × precio con IVA)."""
    found: list[Decimal] = []
    index = 0
    while index < len(lines):
        window = " ".join(lines[index : index + 3]).lower()
        if "importe" in window and re.search(r"\btti\b", window):
            cursor = index
            while cursor < min(len(lines), index + 5) and not _is_amount_only(lines[cursor]):
                cursor += 1
            run: list[Decimal] = []
            while cursor < len(lines) and _is_amount_only(lines[cursor]):
                amount = last_amount(lines[cursor])
                if amount is not None and amount not in IVA_RATES:
                    run.append(amount)
                cursor += 1
            if len(run) >= 2:
                found.extend(_totales_de_columna(run))
            index = max(cursor, index + 1)
            continue
        index += 1
    return found


def _totales_de_columna(run: list[Decimal]) -> list[Decimal]:
    """Si la columna viene a pares (precio unitario, importe de línea), se queda el importe."""
    if len(run) < 4 or len(run) % 2:
        return run
    pares = list(zip(run[0::2], run[1::2], strict=True))
    for unit, line in pares:
        if unit <= 0 or line + Decimal("0.02") < unit:
            return run
        qty = line / unit
        nearest = round(qty)
        if nearest < 1 or nearest > 40 or abs(qty - Decimal(nearest)) > Decimal("0.03"):
            return run
    return [line for _unit, line in pares]


def _importes_columna(
    lines: list[str],
    total: Decimal | None,
    base: Decimal | None,
    *,
    want: int | None = None,
) -> list[Decimal]:
    runs: list[list[Decimal]] = []
    current: list[Decimal] = []
    for line in lines:
        if _is_amount_only(line):
            amount = last_amount(line)
            if amount is not None:
                current.append(amount)
                continue
        if current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    ranked: list[tuple[int, int, list[Decimal]]] = []
    for run in runs:
        body = list(run)
        while body and total is not None and body[-1] == total:
            body.pop()
        while body and base is not None and body[-1] == base:
            body.pop()
        filtered = [item for item in body if item not in IVA_RATES]
        if len(filtered) < 2:
            continue
        acc = sum(filtered, Decimal("0.00"))
        if total is not None and abs(acc - total) <= Decimal("0.05"):
            ranked.append((0, -len(filtered), filtered))
        elif base is not None and abs(acc - base) <= Decimal("0.05"):
            ranked.append((1, -len(filtered), filtered))
    if not ranked:
        return []
    if want:
        matching = [item for item in ranked if len(item[2]) == want]
        if matching:
            ranked = matching
    ranked.sort(key=lambda row: (row[0], row[1]))
    return ranked[0][2]


def _tasas_por_linea(lines: list[str], n: int) -> list[Decimal] | None:
    if n < 2:
        return None
    run: list[Decimal] = []
    found: list[Decimal] | None = None
    for line in lines:
        if _is_amount_only(line):
            amount = last_amount(line)
            if amount in IVA_RATES:
                run.append(amount)
                continue
        if len(run) == n:
            found = list(run)
        run = []
    if len(run) == n:
        found = list(run)
    return found


def _tipo_iva_implicito(
    base: Decimal | None,
    total: Decimal | None,
    iva_tipo: Decimal | None,
) -> Decimal | None:
    if iva_tipo is not None:
        return iva_tipo
    if base is None or total is None or base <= 0 or total <= base:
        return None
    implied = (total - base) / base * Decimal("100")
    return next((rate for rate in IVA_RATES if abs(implied - rate) < Decimal("0.8")), None)


def _completar_desglose(
    items: list[InvoiceLine],
    *,
    total: Decimal | None,
    base: Decimal | None,
    iva_tipo: Decimal | None,
    lines: list[str],
) -> list[InvoiceLine]:
    if not items or any(item.importe is None for item in items):
        return items
    n = len(items)
    default_rate = _tipo_iva_implicito(base, total, iva_tipo)
    rates = _tasas_por_linea(lines, n)
    if rates is None:
        if default_rate is None:
            return items
        rates = [default_rate] * n
    suma = sum((item.importe for item in items), Decimal("0.00"))
    as_ti = total is not None and abs(suma - total) <= Decimal("0.05")
    as_si = base is not None and abs(suma - base) <= Decimal("0.05")
    if not as_ti and not as_si:
        return items
    for item, rate in zip(items, rates, strict=True):
        item.iva_tipo = q2(rate)
        factor = Decimal("1") + (rate / Decimal("100"))
        if as_ti:
            item.base = q2(item.importe / factor)
            item.iva_cuota = q2(item.importe - item.base) if item.base is not None else None
        else:
            item.base = q2(item.importe)
            item.iva_cuota = q2(item.base * rate / Decimal("100")) if item.base is not None else None
            if item.base is not None and item.iva_cuota is not None:
                item.importe = q2(item.base + item.iva_cuota)
    if base is not None:
        acc = sum((item.base for item in items if item.base is not None), Decimal("0.00"))
        delta = q2(base - acc)
        last = items[-1]
        if (
            delta is not None
            and last.base is not None
            and last.importe is not None
            and abs(delta) <= Decimal("0.05")
        ):
            last.base = q2(last.base + delta)
            last.iva_cuota = q2(last.importe - last.base)
    return items


def _lineas_numeradas(lines: list[str]) -> list[InvoiceLine]:
    found: list[InvoiceLine] = []
    idx = 0
    while idx < len(lines):
        if INDEX_LINE.fullmatch(lines[idx]) and 1 <= int(lines[idx]) <= 40:
            pos = int(lines[idx])
            if idx + 1 < len(lines) and _es_nombre_producto(lines[idx + 1]):
                desc = re.sub(r"\s{2,}", " ", lines[idx + 1].strip(" :-·"))
                codigo = None
                consumed = 2
                if idx + 2 < len(lines) and _is_ref_articulo(lines[idx + 2]):
                    codigo = lines[idx + 2].strip()
                    consumed = 3
                found.append(
                    InvoiceLine(descripcion=desc[:200], codigo=codigo, posicion=pos)
                )
                idx += consumed
                continue
        idx += 1
    return found


def _es_nombre_producto(line: str) -> bool:
    if _skip_linea_contexto(line) or COMPANY_HINT.search(line):
        return False
    desc = re.sub(r"\s{2,}", " ", line.strip(" :-·"))
    if HEADER_LINE.match(desc.lstrip(" .")):
        return False
    if INDEX_LINE.fullmatch(desc) or REF_STANDALONE.fullmatch(desc) or _is_ref_articulo(desc):
        return False
    if re.match(r"^(sr|sra|dña|d\.|dn)\b", desc, re.IGNORECASE):
        return False
    letters = len(HAS_LETTER.findall(desc))
    return len(desc) >= 10 and letters >= 8 and len(desc.split()) >= 2


def _lineas_heuristica(lines: list[str]) -> list[InvoiceLine]:
    found: list[InvoiceLine] = []
    seen: set[tuple[str, str]] = set()
    for idx, line in enumerate(lines):
        if _skip_linea_contexto(line):
            continue
        amount = last_amount(line)
        desc = TRAILING_AMOUNT.sub("", line).strip(" :-·") if amount is not None else line.strip(" :-·")
        desc = re.sub(r"\s{2,}", " ", desc)
        desc_norm = desc.lstrip(" .")
        if HEADER_LINE.match(desc_norm):
            continue
        if INDEX_LINE.fullmatch(desc) or REF_STANDALONE.fullmatch(desc) or _is_ref_articulo(desc):
            continue
        if re.match(r"^\d{5}\b", desc):
            continue
        if amount is None:
            if COMPANY_HINT.search(line):
                continue
            if re.match(r"^(sr|sra|dña|d\.|dn)\b", desc, re.IGNORECASE):
                continue
            if not _es_nombre_producto(line):
                continue
            nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
            if nxt and _is_amount_only(nxt):
                peeked = last_amount(nxt)
                if peeked is not None and peeked not in IVA_RATES:
                    amount = peeked
        if len(desc) < 4 or not HAS_LETTER.search(desc) or ONLY_NUM.match(desc):
            continue
        if amount is not None and amount <= 0:
            continue
        key = (desc.lower(), "" if amount is None else str(amount))
        if key in seen:
            continue
        seen.add(key)
        found.append(InvoiceLine(descripcion=desc[:200], importe=amount))
        if len(found) >= 40:
            break
    return found


def _sin_pie_de_totales(
    amounts: list[Decimal],
    *,
    base: Decimal | None,
    total: Decimal | None,
) -> list[Decimal]:
    """Base, IVA y total del pie no son precios de artículo."""
    if not amounts or total is None:
        return amounts
    iva = q2(total - base) if base is not None else None
    pie = {q2(value) for value in (base, iva, total) if value is not None}
    if pie and all(q2(amount) in pie for amount in amounts):
        return []
    return amounts


def _precios_en_bloque(lines: list[str], items: list[InvoiceLine]) -> list[Decimal | None]:
    """En un ticket seguido, el último importe tras el código es el total de la línea con IVA."""
    if not items:
        return []
    anchors: list[int | None] = []
    for item in items:
        found = None
        codigo = (item.codigo or "").strip()
        if codigo:
            for idx, line in enumerate(lines):
                if line.strip() == codigo or _codigo_de_token(line) == codigo:
                    found = idx
                    break
        if found is None and item.descripcion:
            for idx, line in enumerate(lines):
                if line.strip() == item.descripcion.strip():
                    found = idx
                    break
        anchors.append(found)
    prices: list[Decimal | None] = []
    for pos, start in enumerate(anchors):
        if start is None:
            prices.append(None)
            continue
        end = len(lines)
        for nxt in anchors[pos + 1 :]:
            if nxt is not None and nxt > start:
                end = nxt
                break
        captured: list[Decimal] = []
        for line in lines[start + 1 : end]:
            if re.search(
                r"modos de pago|total\s+(?:si|tti|tii|til|iva)\s*(?:\(|/)",
                line,
                re.IGNORECASE,
            ):
                break
            if not _is_amount_only(line):
                continue
            amount = last_amount(line)
            if amount is not None and amount not in IVA_RATES and amount > 0:
                captured.append(amount)
        prices.append(captured[-1] if captured else None)
    return prices


def _codigo_tras_nombre(lines: list[str], idx: int) -> str | None:
    """El código de artículo va justo después del nombre, a veces con el nº de línea delante."""
    for look in lines[idx + 1 : idx + 4]:
        token = look.strip()
        codigo = _codigo_de_token(token)
        if codigo:
            return codigo
        if re.fullmatch(r"\d{1,2}\.?", token):
            continue
        return None
    return None


def _lineas_con_referencia(lines: list[str]) -> list[InvoiceLine]:
    """Nombre + código de artículo, en el orden del ticket. Ignora notas sin referencia."""
    found: list[InvoiceLine] = []
    seen: set[str] = set()
    for idx, line in enumerate(lines):
        if not _es_nombre_producto(line):
            continue
        codigo = _codigo_tras_nombre(lines, idx)
        if codigo is None or codigo in seen:
            continue
        seen.add(codigo)
        desc = re.sub(r"\s{2,}", " ", line.strip(" :-·"))
        found.append(InvoiceLine(descripcion=desc[:200], codigo=codigo))
    return found


def _emparejar_por_referencia(
    lines: list[str],
    *,
    total: Decimal | None,
    base: Decimal | None,
) -> list[InvoiceLine] | None:
    """Si hay tantos artículos con código como importes TTI, se asignan en el mismo orden."""
    items = _lineas_con_referencia(_region_articulos(lines))
    if len(items) < 2:
        return None
    amounts = _sin_pie_de_totales(_importes_tti(lines), base=base, total=total)
    if len(amounts) != len(items):
        return None
    if total is not None and abs(sum(amounts, Decimal("0.00")) - total) > Decimal("0.05"):
        return None
    for item, amount in zip(items, amounts, strict=True):
        item.importe = amount
    return items


def _find_lineas(
    lines: list[str],
    *,
    total: Decimal | None = None,
    base: Decimal | None = None,
    iva_tipo: Decimal | None = None,
) -> list[InvoiceLine]:
    emparejadas = _emparejar_por_referencia(lines, total=total, base=base)
    if not emparejadas:
        emparejadas = _lineas_con_referencia(_region_articulos(lines))
        if emparejadas:
            bloque = _precios_en_bloque(lines, emparejadas)
            cuadra = (
                bloque
                and len(bloque) == len(emparejadas)
                and all(price is not None for price in bloque)
                and total is not None
                and abs(sum(bloque, Decimal("0.00")) - total) <= Decimal("0.05")
            )
            if cuadra:
                for item, price in zip(emparejadas, bloque, strict=True):
                    item.importe = price
            else:
                emparejadas = None
    if emparejadas:
        for idx, item in enumerate(emparejadas, start=1):
            item.posicion = idx
        return _completar_desglose(
            emparejadas[:40],
            total=total,
            base=base,
            iva_tipo=iva_tipo,
            lines=lines,
        )
    region = _region_articulos(lines)
    numbered = _lineas_numeradas(region)
    items = numbered if len(numbered) >= 2 else _lineas_heuristica(region)
    refs = [line.strip() for line in region if REF_STANDALONE.fullmatch(line.strip())]
    amounts = _importes_columna(lines, total, base, want=len(items) or None)
    if not amounts and (refs or items):
        amounts = _importes_columna(
            lines, total, base, want=len(refs) or None
        )
    if not amounts:
        amounts = _importes_tti(lines)
    amounts = _sin_pie_de_totales(amounts, base=base, total=total)
    bloque = _precios_en_bloque(lines, items)
    if bloque and len(bloque) == len(items) and all(price is not None for price in bloque):
        for item, price in zip(items, bloque, strict=True):
            if item.importe is None:
                item.importe = price
        amounts = []

    if not items and amounts:
        items = [
            InvoiceLine(
                posicion=idx + 1,
                codigo=refs[idx] if idx < len(refs) else None,
                importe=amount,
            )
            for idx, amount in enumerate(amounts)
        ]
    elif amounts and len(amounts) == len(items):
        for item, amount in zip(items, amounts, strict=True):
            if item.importe is None:
                item.importe = amount
    elif amounts and len(amounts) > len(items) and len(refs) == len(amounts):
        for idx, amount in enumerate(amounts):
            if idx < len(items):
                if items[idx].importe is None:
                    items[idx].importe = amount
                if not items[idx].codigo:
                    items[idx].codigo = refs[idx]
            else:
                items.append(
                    InvoiceLine(posicion=idx + 1, codigo=refs[idx], importe=amount)
                )
    elif (
        amounts
        and items
        and all(item.importe is None for item in items)
        and total is not None
        and abs(sum(amounts, Decimal("0.00")) - total) <= Decimal("0.05")
    ):
        for amount in amounts:
            items.append(InvoiceLine(posicion=len(items) + 1, importe=amount))

    if items and refs and all(not item.codigo for item in items) and len(refs) == len(items):
        for item, ref in zip(items, refs, strict=True):
            item.codigo = ref

    for idx, item in enumerate(items):
        if item.posicion is None:
            item.posicion = idx + 1
    return _completar_desglose(
        items[:40],
        total=total,
        base=base,
        iva_tipo=iva_tipo,
        lines=lines,
    )


def _find_emisor(lines: list[str], nif_emisor: str | None) -> str | None:
    header: list[str] = []
    for line in lines[:12]:
        if SKIP_EMISOR.match(line) or DATE_RE.search(line):
            continue
        if COMPANY_HINT.search(line) and len(line.strip()) >= 4:
            header.append(line.strip()[:200])
    if header:
        return max(header, key=len)
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
