"""Importes exactos (Fixed) y campos legales de factura.

- SQLite: importes y tipos pasan de REAL a enteros escalados (céntimos);
  los valores existentes se convierten con redondeo al céntimo.
- Otros motores: NUMERIC con la precisión nueva.
- Asiento gana los campos de los art. 6, 7 y 15 RD 1619/2012 y la tabla
  `asiento_iva` guarda el desglose por tipo.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# tabla -> [(columna, escala, precisión)]
FIXED = {
    "asientos": [("base", 2, 14), ("iva_tipo", 2, 6), ("iva_cuota", 2, 14), ("total", 2, 14)],
    "facturas": [("base", 2, 14), ("iva_tipo", 2, 6), ("iva_cuota", 2, 14), ("total", 2, 14)],
    "extracciones": [("base", 2, 14), ("iva_tipo", 2, 6), ("iva_cuota", 2, 14), ("total", 2, 14)],
    "lineas": [
        ("cantidad", 3, 14),
        ("base", 2, 14),
        ("iva_tipo", 2, 6),
        ("iva_cuota", 2, 14),
        ("importe", 2, 14),
    ],
    "inmuebles": [("porcentaje_titularidad", 2, 6)],
}
NIF_ANCHO = {"asientos": "nif_emisor", "facturas": "nif_emisor", "extracciones": "nif_emisor"}


def _tipo(escala: int, precision: int, sqlite: bool):
    return sa.BigInteger() if sqlite else sa.Numeric(precision, escala)


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"

    for tabla, columnas in FIXED.items():
        if sqlite:
            for columna, escala, _ in columnas:
                op.execute(
                    f"UPDATE {tabla} SET {columna} = CAST(ROUND({columna} * {10 ** escala}) AS INTEGER) "
                    f"WHERE {columna} IS NOT NULL"
                )
        with op.batch_alter_table(tabla) as batch:
            for columna, escala, precision in columnas:
                batch.alter_column(columna, type_=_tipo(escala, precision, sqlite))
            if tabla in NIF_ANCHO:
                batch.alter_column(NIF_ANCHO[tabla], type_=sa.String(20))
            if tabla == "asientos":
                batch.add_column(
                    sa.Column("direccion", sa.String(10), nullable=False, server_default="recibida")
                )
                batch.add_column(sa.Column("tipo_factura", sa.String(20), nullable=True))
                batch.add_column(sa.Column("serie", sa.String(40), nullable=True))
                batch.add_column(sa.Column("fecha_operacion", sa.Date(), nullable=True))
                batch.add_column(sa.Column("receptor", sa.String(200), nullable=True))
                batch.add_column(sa.Column("nif_receptor", sa.String(20), nullable=True))
                batch.add_column(sa.Column("factura_rectificada", sa.String(120), nullable=True))
                batch.add_column(sa.Column("factura_rectificada_id", sa.Integer(), nullable=True))
                batch.create_foreign_key(
                    "fk_asientos_factura_rectificada_id_asientos",
                    "asientos",
                    ["factura_rectificada_id"],
                    ["id"],
                )
                batch.add_column(sa.Column("causa_rectificacion", sa.String(200), nullable=True))
                batch.add_column(sa.Column("retencion_tipo", _tipo(2, 6, sqlite), nullable=True))
                batch.add_column(sa.Column("retencion_cuota", _tipo(2, 14, sqlite), nullable=True))
                batch.add_column(sa.Column("recargo_cuota", _tipo(2, 14, sqlite), nullable=True))
                batch.add_column(
                    sa.Column("moneda", sa.String(3), nullable=False, server_default="EUR")
                )
                batch.add_column(sa.Column("mencion_legal", sa.String(40), nullable=True))

    op.create_table(
        "asiento_iva",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asiento_id", sa.Integer(), sa.ForeignKey("asientos.id"), nullable=False),
        sa.Column("base", _tipo(2, 14, sqlite), nullable=True),
        sa.Column("tipo", _tipo(2, 6, sqlite), nullable=True),
        sa.Column("cuota", _tipo(2, 14, sqlite), nullable=True),
        sa.Column("recargo_tipo", _tipo(2, 6, sqlite), nullable=True),
        sa.Column("recargo_cuota", _tipo(2, 14, sqlite), nullable=True),
    )
    op.create_index("ix_asiento_iva_asiento_id", "asiento_iva", ["asiento_id"])


def downgrade() -> None:
    raise NotImplementedError("Migración de datos: restaura la copia de seguridad.")
