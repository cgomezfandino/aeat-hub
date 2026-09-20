"""Importes en formato español y Decimal cuantizado."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TWOPLACES = Decimal("0.01")
AMOUNT_RE = re.compile(
    r"(?<![\d.,])("
    r"\d{1,3}(?:\.\d{3})+,\d{2}"
    r"|\d+,\d{2}"
    r"|\d{1,3}(?:,\d{3})+\.\d{2}"
    r"|\d+\.\d{2}"
    r")(?![\d.,])"
)


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
    if raw is None:
        return None
    text = raw.strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not text:
        return None
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", text):
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d{2}", text):
        text = text.replace(",", "")
    elif re.fullmatch(r"\d+,\d{1,2}", text):
        text = text.replace(",", ".")
    try:
        return q2(Decimal(text))
    except InvalidOperation:
        return None


def last_amount(line: str) -> Decimal | None:
    matches = AMOUNT_RE.findall(line.replace("€", " "))
    if not matches:
        return None
    return parse_amount(matches[-1])


def all_amounts(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for token in AMOUNT_RE.findall(text.replace("€", " ")):
        parsed = parse_amount(token)
        if parsed is not None:
            values.append(parsed)
    return values
