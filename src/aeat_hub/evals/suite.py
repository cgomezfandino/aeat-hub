"""Suite de EVALS: oro real (data-dir) + facturas sintéticas sin PII."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from aeat_hub.evals.gold import GoldCase, GoldFields, load_gold
from aeat_hub.paths import DataLayout

SYNTHETIC_LUZ = """\
IBERDROLA CLIENTES DEMO S.A.
NIF: B12345674
Factura nº: F2026-000123
Fecha: 10/03/2026
Cliente: 12345678Z
Base imponible: 40,00 €
IVA 21%: 8,40 €
Total factura: 48,40 €
"""

SYNTHETIC_ID_PDF = "synthetic-luz-digital"
SYNTHETIC_ID_PNG = "synthetic-luz-raster"


def evals_dir(layout: DataLayout) -> Path:
    return layout.root / "evals"


def gold_path(layout: DataLayout) -> Path:
    return evals_dir(layout) / "gold.json"


def make_synthetic_cases(dest: Path) -> list[GoldCase]:
    dest.mkdir(parents=True, exist_ok=True)
    pdf = _write_pdf(dest / "luz-digital.pdf", SYNTHETIC_LUZ)
    png = dest / "luz-raster.png"
    _pdf_to_png(pdf, png)
    fields = GoldFields(
        emisor_contains=["IBERDROLA"],
        nif_emisor="B12345674",
        nif_receptor="12345678Z",
        numero="F2026-000123",
        fecha=date(2026, 3, 10),
        base=Decimal("40.00"),
        iva_cuota=Decimal("8.40"),
        total=Decimal("48.40"),
        iva_tipo=Decimal("21"),
    )
    tokens = [
        "IBERDROLA",
        "B12345674",
        "F2026-000123",
        "10/03/2026",
        "40,00",
        "8,40",
        "48,40",
        "12345678Z",
    ]
    return [
        GoldCase(
            id=SYNTHETIC_ID_PDF,
            path=pdf,
            kind="digital-pdf",
            fields=fields,
            must_tokens=tokens,
            notes="PDF vectorial sintético: pdf-native debe acertar todo.",
        ),
        GoldCase(
            id=SYNTHETIC_ID_PNG,
            path=png,
            kind="raster",
            fields=fields,
            must_tokens=tokens,
            notes="Misma factura rasterizada a PNG (sin capa de texto).",
        ),
    ]


def load_suite(layout: DataLayout, *, include_synthetic: bool = True) -> list[GoldCase]:
    cases: list[GoldCase] = []
    path = gold_path(layout)
    if path.is_file():
        cases.extend(load_gold(path, root=layout.root))
    if include_synthetic:
        cases.extend(make_synthetic_cases(evals_dir(layout) / "synthetic"))
    return cases


def _write_pdf(path: Path, text: str) -> Path:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()
    return path


def _pdf_to_png(pdf: Path, png: Path, dpi: int = 150) -> Path:
    import pymupdf

    doc = pymupdf.open(pdf)
    try:
        page = doc[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False)
        png.write_bytes(pix.tobytes("png"))
    finally:
        doc.close()
    return png
