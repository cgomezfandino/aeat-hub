"""Métricas de EVALS: recall de tokens, presencia en OCR, exactitud del parser."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.fiscal.nif import normalize_nif

_ALNUM = re.compile(r"[^A-Z0-9]+")
_WS = re.compile(r"\s+")


def strip_accents(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in nfkd if not unicodedata.combining(char))


def normalize_text(value: str) -> str:
    folded = strip_accents(value or "").upper()
    return _WS.sub(" ", folded).strip()


def compact_alnum(value: str) -> str:
    return _ALNUM.sub("", normalize_text(value))


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for j, rch in enumerate(right, start=1):
        current = [j]
        for i, lch in enumerate(left, start=1):
            ins = current[i - 1] + 1
            delete = previous[i] + 1
            sub = previous[i - 1] + (lch != rch)
            current.append(min(ins, delete, sub))
        previous = current
    return previous[-1]


def similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    dist = levenshtein(left, right)
    return 1.0 - (dist / max(len(left), len(right), 1))


_DATE_ES = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def token_variants(token: str) -> list[str]:
    raw = normalize_text(token)
    variants = {raw, compact_alnum(token)}
    if re.search(r"\d", token) and re.search(r"[,.]", token):
        flipped = token.replace(",", "¤").replace(".", ",").replace("¤", ".")
        variants.add(normalize_text(flipped))
        variants.add(compact_alnum(flipped))
        variants.add(normalize_text(token.replace(",", ".")))
        variants.add(normalize_text(token.replace(".", ",")))
    variants.update(_date_variants(token))
    return [item for item in variants if item]


def _date_variants(token: str) -> set[str]:
    """Una fecha oro en formato español también vale en ISO y al revés.

    Sin esto, el JSON estructurado (siempre ISO) pierde el token de fecha
    aunque el campo sea correcto.
    """
    found: set[str] = set()
    es = _DATE_ES.match(token.strip())
    if es and _valid_day_month(int(es.group(1)), int(es.group(2))):
        day, month, year = es.group(1).zfill(2), es.group(2).zfill(2), es.group(3)
        found.add(f"{year}-{month}-{day}")
        found.add(f"{year}{month}{day}")
    iso = _DATE_ISO.match(token.strip())
    if iso and _valid_day_month(int(iso.group(3)), int(iso.group(2))):
        year, month, day = iso.group(1), iso.group(2).zfill(2), iso.group(3).zfill(2)
        found.add(f"{day}/{month}/{year}")
        found.add(f"{day}{month}{year}")
    return found


def _valid_day_month(day: int, month: int) -> bool:
    return 1 <= day <= 31 and 1 <= month <= 12


def token_in_text(token: str, text: str, *, fuzzy: float = 0.86) -> tuple[bool, bool]:
    hay_norm = normalize_text(text)
    hay_alnum = compact_alnum(text)
    for variant in token_variants(token):
        if variant and (variant in hay_norm or variant in hay_alnum):
            return True, False
    needle = compact_alnum(token)
    if len(needle) >= 6:
        window = max(len(needle), 1)
        best = 0.0
        for idx in range(0, max(len(hay_alnum) - window + 1, 0), max(window // 4, 1)):
            best = max(best, similarity(needle, hay_alnum[idx : idx + window]))
            if best >= fuzzy:
                return True, True
    return False, False


def score_tokens(must_tokens: list[str], text: str) -> dict:
    hits = 0
    fuzzy_hits = 0
    detail: list[dict] = []
    for token in must_tokens:
        exact, fuzzy = token_in_text(token, text)
        if exact and not fuzzy:
            hits += 1
            kind = "exact"
        elif exact:
            hits += 1
            fuzzy_hits += 1
            kind = "fuzzy"
        else:
            kind = "miss"
        detail.append({"token": token, "result": kind})
    total = len(must_tokens)
    return {
        "total": total,
        "hits": hits,
        "fuzzy_hits": fuzzy_hits,
        "recall": (hits / total) if total else 1.0,
        "exact_recall": ((hits - fuzzy_hits) / total) if total else 1.0,
        "detail": detail,
    }


def _money_equal(gold: str, predicted: Decimal | None) -> bool:
    if predicted is None:
        return False
    try:
        expected = Decimal(gold)
    except InvalidOperation:
        return False
    return abs(expected - predicted) <= Decimal("0.01")


def _numero_equal(gold: str, predicted: str | None) -> bool:
    if not predicted:
        return False
    g = compact_alnum(gold)
    p = compact_alnum(predicted)
    if not g or not p:
        return False
    # Igualdad exacta (sin separadores): aceptar subcadenas daba por buena
    # una lectura truncada ("123" frente a "F-2026-0123").
    return g == p


def _fecha_equal(gold: str, predicted) -> bool:
    if predicted is None:
        return False
    return predicted.isoformat() == gold


def _nif_equal(gold: str, predicted: str | None) -> bool:
    return bool(predicted) and normalize_nif(gold) == normalize_nif(predicted)


def field_in_ocr(name: str, gold: str, text: str) -> bool:
    if name.startswith("nif_"):
        return compact_alnum(gold) in compact_alnum(text)
    if name == "numero":
        return compact_alnum(gold) in compact_alnum(text)
    if name == "fecha":
        year, month, day = gold.split("-")
        candidates = (
            f"{day}/{month}/{year}",
            f"{int(day)}/{int(month)}/{year}",
            f"{day}-{month}-{year}",
            f"{day}.{month}.{year}",
            gold,
        )
        return any(token_in_text(item, text)[0] for item in candidates)
    if name == "tipo_documento":
        return True  # es una clasificación, no un texto que deba aparecer
    if name in {"base", "iva_tipo", "iva_cuota", "retencion_cuota", "total"}:
        comma = gold.replace(".", ",")
        dot = gold.replace(",", ".")
        return token_in_text(comma, text)[0] or token_in_text(dot, text)[0]
    return token_in_text(gold, text)[0]


def score_fields(gold_fields: dict[str, str], extract: InvoiceExtract, text: str) -> dict:
    rows: list[dict] = []
    ocr_hits = 0
    parser_hits = 0
    for name, expected in gold_fields.items():
        predicted = getattr(extract, name, None)
        if name.startswith("nif_"):
            parser_hit = _nif_equal(expected, predicted)
            predicted_s = predicted or ""
        elif name == "numero":
            parser_hit = _numero_equal(expected, predicted)
            predicted_s = predicted or ""
        elif name == "fecha":
            parser_hit = _fecha_equal(expected, predicted)
            predicted_s = predicted.isoformat() if predicted else ""
        elif name in {"base", "iva_tipo", "iva_cuota", "retencion_cuota", "total"}:
            parser_hit = _money_equal(expected, predicted)
            predicted_s = "" if predicted is None else f"{predicted:.2f}"
        elif name == "tipo_documento":
            from aeat_hub.ingest import tipo_factura_de

            predicted_s = tipo_factura_de(extract)
            parser_hit = predicted_s == expected
        else:
            parser_hit = bool(predicted) and compact_alnum(expected) in compact_alnum(str(predicted))
            predicted_s = str(predicted or "")
        ocr_hit = field_in_ocr(name, expected, text)
        if ocr_hit:
            ocr_hits += 1
        if parser_hit:
            parser_hits += 1
        rows.append(
            {
                "field": name,
                "gold": expected,
                "predicted": predicted_s,
                "ocr": ocr_hit,
                "parser": parser_hit,
            }
        )
    n = len(gold_fields)
    emisor_ok = None
    return {
        "total": n,
        "ocr_hits": ocr_hits,
        "parser_hits": parser_hits,
        "ocr_recall": (ocr_hits / n) if n else 1.0,
        "parser_accuracy": (parser_hits / n) if n else 1.0,
        "emisor_ok": emisor_ok,
        "detail": rows,
    }


def score_emisor(needles: list[str], extract: InvoiceExtract, text: str) -> bool | None:
    if not needles:
        return None
    blob = f"{extract.emisor or ''}\n{text}"
    return all(token_in_text(item, blob)[0] for item in needles)
