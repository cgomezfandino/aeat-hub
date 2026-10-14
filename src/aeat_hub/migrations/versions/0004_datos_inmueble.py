"""Datos del inmueble para amortización, límite y reducción (art. 23 LIRPF)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _fixed(escala: int, precision: int):
    return sa.BigInteger() if op.get_bind().dialect.name == "sqlite" else sa.Numeric(precision, escala)


def upgrade() -> None:
    with op.batch_alter_table("inmuebles") as batch:
        batch.add_column(sa.Column("valor_catastral", _fixed(2, 14), nullable=True))
        batch.add_column(sa.Column("valor_catastral_construccion", _fixed(2, 14), nullable=True))
        batch.add_column(sa.Column("coste_adquisicion", _fixed(2, 14), nullable=True))
        batch.add_column(sa.Column("mejoras_anteriores", _fixed(2, 14), nullable=True))
        batch.add_column(sa.Column("fecha_adquisicion", sa.Date(), nullable=True))
        batch.add_column(sa.Column("dias_arrendado", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reduccion_pct", _fixed(2, 6), nullable=True))
        batch.add_column(sa.Column("excesos_anteriores", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    raise NotImplementedError
