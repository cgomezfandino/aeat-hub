"""Normalización de IDs de factura para entity resolution."""

from __future__ import annotations

import re

_EMISOR_SPACE = re.compile(r"\s+")


def normalize_numero(numero: str | None) -> str | None:
    if not numero:
        return None
    token = "".join(ch for ch in numero.upper() if ch.isalnum())
    return token or None


def normalize_emisor(emisor: str | None) -> str | None:
    text = _EMISOR_SPACE.sub(" ", (emisor or "").upper()).strip()
    if len(text) < 6:
        return None
    return text[:80]
