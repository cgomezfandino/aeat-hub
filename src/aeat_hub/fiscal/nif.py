"""Validación y normalización de NIF/NIE/CIF españoles."""

from __future__ import annotations

import re

DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
CIF_LETTERS = "JABCDEFGHI"
NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}
CIF_DIGIT_ONLY = set("ABEH")
CIF_LETTER_ONLY = set("PQSNW")
CIF_LETTERS_ORG = set("ABCDEFGHJNPQRSUVW")

_CLEAN = re.compile(r"[\s.\-]")
NIF_TOKEN = re.compile(
    r"\b([XYZ]\d{7}[A-Z]|\d{8}[A-Z]|[ABCDEFGHJNPQRSUVW]-?\d{7}[A-Z0-9])\b",
    re.IGNORECASE,
)


def normalize_nif(value: str | None) -> str:
    if not value:
        return ""
    return _CLEAN.sub("", value).upper()


def is_valid_nif(value: str | None) -> bool:
    nif = normalize_nif(value)
    if len(nif) != 9:
        return False
    if nif[0] in NIE_PREFIX or nif[0].isdigit():
        return _valid_dni_nie(nif)
    if nif[0] in CIF_LETTERS_ORG:
        return _valid_cif(nif)
    return False


def is_placeholder_nif(value: str | None) -> bool:
    nif = normalize_nif(value)
    return nif in {"00000000T", "99999999R"}


def find_nifs(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in NIF_TOKEN.finditer(text or ""):
        nif = normalize_nif(match.group(1))
        if nif not in seen and is_valid_nif(nif):
            seen.add(nif)
            found.append(nif)
    return found


def pick_emisor_receptor(nifs: list[str]) -> tuple[str | None, str | None]:
    """En facturas ES el CIF de empresa suele ser el emisor y el DNI el cliente."""
    org = [nif for nif in nifs if nif[:1] in CIF_LETTERS_ORG]
    person = [nif for nif in nifs if nif[:1].isdigit() or nif[:1] in NIE_PREFIX]
    if org:
        receptor = person[0] if person else (org[1] if len(org) > 1 else None)
        return org[0], receptor
    if not nifs:
        return None, None
    return nifs[0], nifs[1] if len(nifs) > 1 else None


def _valid_dni_nie(nif: str) -> bool:
    body = nif[:8]
    control = nif[8]
    if nif[0] in NIE_PREFIX:
        body = NIE_PREFIX[nif[0]] + nif[1:8]
    if not body.isdigit():
        return False
    return DNI_LETTERS[int(body) % 23] == control


def _valid_cif(nif: str) -> bool:
    letter, digits, control = nif[0], nif[1:8], nif[8]
    if not digits.isdigit():
        return False
    total = 0
    for idx, char in enumerate(digits):
        n = int(char)
        if idx % 2 == 0:
            doubled = n * 2
            total += doubled // 10 + doubled % 10
        else:
            total += n
    digit = (10 - (total % 10)) % 10
    expected_letter = CIF_LETTERS[digit]
    expected_digit = str(digit)
    if letter in CIF_DIGIT_ONLY:
        return control == expected_digit
    if letter in CIF_LETTER_ONLY:
        return control == expected_letter
    return control in {expected_digit, expected_letter}
