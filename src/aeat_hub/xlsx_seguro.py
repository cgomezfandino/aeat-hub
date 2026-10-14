"""Guardado de Excel sin inyección de fórmulas.

Los textos (emisor, número, concepto…) vienen de documentos ajenos vía OCR
o LLM. openpyxl convierte en fórmula cualquier cadena que empiece por «=»,
así que una factura con emisor `=HYPERLINK(...)` acabaría ejecutándose al
abrir el libro. Nuestras exportaciones no escriben fórmulas: todo texto se
fuerza a tipo cadena antes de guardar.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook


def guardar(wb: Workbook, destino: Path) -> Path:
    for ws in wb.worksheets:
        for fila in ws.iter_rows():
            for celda in fila:
                if isinstance(celda.value, str):
                    celda.data_type = "s"
    wb.save(destino)
    return destino
