"""Importes en formato español y Decimal cuantizado."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TWOPLACES = Decimal("0.01")
_NUM = (
    r"\d{1,3}(?:\.\d{3})+,\d{2}"
    r"|\d{1,3}(?:[\u00a0\u202f]\d{3})+,\d{2}"
    r"|\d+,\d{2}"
    r"|\d{1,3}(?:,\d{3})+\.\d{2}"
    r"|\d+\.\d{2}"
)
# Importe con signo en texto libre: -12,50 · −12,50 · 12,50- · (12,50).
# El espacio normal NO separa miles aquí: en tickets "2 345,50" suele ser
# cantidad 2 × 345,50. Solo NBSP / espacio fino (salida de software).
AMOUNT_RE = re.compile(
    r"(?<![\d.,])"
    r"(?:(?P<paren>\()\s?)?"
    r"(?P<neg>[-\u2212]\s?)?"
    r"(?P<num>" + _NUM + r")"
    r"(?P<trail>-(?![\d]))?"
    r"(?(paren)\s?\))"
    r"(?![\d.,])"
)
_SPACES = re.compile(r"[\s\u00a0\u202f]+")

def q2(value: Decimal | int | str | float | None) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def format_euro(value: Decimal | int | str | float | None, *, empty: str = "—") -> str:
    quantized = q2(value)
    if quantized is None:
        return empty
    sign = "-" if quantized < 0 else ""
    quantized = abs(quantized)
    ints, frac = f"{quantized:.2f}".split(".")
    groups: list[str] = []
    while ints:
        groups.append(ints[-3:])
        ints = ints[:-3]
    grouped = ".".join(reversed(groups))
    return f"{sign}{grouped},{frac} €"


def parse_amount(raw: str | None) -> Decimal | None:
    """Un importe escrito por una persona o un modelo, en formato español o inglés.

    Admite signo (-x, x-, (x)), miles con punto, coma o espacio y 1-2
    decimales. "1.234" es mil doscientos treinta y cuatro (convención
    española); nunca 1,23. Ante algo que no es un importe, None.
    """
    if raw is None:
        return None
    text = _SPACES.sub("", str(raw)).replace("€", "").replace("EUR", "").replace("\u2212", "-")
    if not text:
        return None
    negativo = False
    if text.startswith("(") and text.endswith(")"):
        negativo, text = True, text[1:-1]
    if text.startswith("-"):
        negativo, text = True, text[1:]
    elif text.endswith("-"):
        negativo, text = True, text[:-1]
    elif text.startswith("+"):
        text = text[1:]
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", text):
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d{1,2}", text):
        text = text.replace(",", "")
    elif re.fullmatch(r"[1-9]\d{0,2}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    elif re.fullmatch(r"\d+,\d{1,2}", text):
        text = text.replace(",", ".")
    elif not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    try:
        value = q2(Decimal(text))
    except InvalidOperation:
        return None
    return -value if negativo and value else value


def _signed(match: re.Match) -> Decimal | None:
    value = parse_amount(match.group("num"))
    if value is None:
        return None
    if match.group("paren") or match.group("neg") or match.group("trail"):
        return -value
    return value


def last_amount(line: str) -> Decimal | None:
    matches = list(AMOUNT_RE.finditer(line.replace("€", " ")))
    if not matches:
        return None
    return _signed(matches[-1])


def all_amounts(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for match in AMOUNT_RE.finditer(text.replace("€", " ")):
        parsed = _signed(match)
        if parsed is not None:
            values.append(parsed)
    return values
