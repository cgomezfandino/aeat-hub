from __future__ import annotations

from pathlib import Path

import pymupdf

FACTURA_LUZ = """\
IBERDROLA CLIENTES DEMO S.A.
NIF: B12345674
Factura nº: F2026-000123
Fecha: 10/03/2026
Cliente: 12345678Z
Base imponible: 40,00 €
IVA 21%: 8,40 €
Total factura: 48,40 €
"""

FACTURA_PVC = """\
CARPINTERIA VALLADOLID S.L.
NIF: B12345674
Factura nº: 2026/88
Fecha: 02/02/2026
Suministro e instalación de ventanas PVC
Base imponible: 1.200,00 €
IVA 21%: 252,00 €
Total factura: 1.452,00 €
"""


def write_pdf(path: Path, text: str) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()
    return path
