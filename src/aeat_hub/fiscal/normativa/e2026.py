"""Ejercicio 2026. Verificado el 14 oct 2026 (instrucciones 303 de 2026)."""

from dataclasses import replace

from aeat_hub.fiscal.normativa import e2025

NORMATIVA = replace(
    e2025.NORMATIVA,
    ejercicio=2026,
    fuentes=e2025.NORMATIVA.fuentes
    + ("AEAT, instrucciones modelo 303 2026 (sede): misma tabla de tipos y recargo que 2025.",),
)
