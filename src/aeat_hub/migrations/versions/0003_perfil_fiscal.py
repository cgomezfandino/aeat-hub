"""Perfil fiscal de la actividad y afectación por asiento."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _fixed(escala: int, precision: int):
    return sa.BigInteger() if op.get_bind().dialect.name == "sqlite" else sa.Numeric(precision, escala)


def upgrade() -> None:
    with op.batch_alter_table("actividades") as batch:
        batch.add_column(sa.Column("epigrafe_iae", sa.String(10), nullable=True))
        batch.add_column(sa.Column("regimen_irpf", sa.String(40), nullable=True))
        batch.add_column(sa.Column("regimen_iva", sa.String(40), nullable=True))
        batch.add_column(sa.Column("territorio", sa.String(20), nullable=False, server_default="comun"))
        batch.add_column(sa.Column("fecha_alta", sa.Date(), nullable=True))
        batch.add_column(sa.Column("afectacion_vivienda_pct", _fixed(2, 6), nullable=True))
        batch.add_column(sa.Column("rendimiento_anterior", _fixed(2, 14), nullable=True))
    with op.batch_alter_table("asientos") as batch:
        batch.add_column(sa.Column("afectacion_pct", _fixed(2, 6), nullable=True))


def downgrade() -> None:
    raise NotImplementedError
