"""Esquema de partida (14 oct 2026).

Crea las tablas tal como estaban antes de las migraciones. Las bases ya
existentes no lo ejecutan: `db.create_schema` las sella en esta revisión.
"""

from __future__ import annotations

from alembic import op

from aeat_hub.migrations.baseline import statements

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in statements():
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("No se deshace el esquema base.")
