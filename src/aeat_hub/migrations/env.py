"""Entorno Alembic: siempre recibe la conexión desde `aeat_hub.db`."""

from __future__ import annotations

from alembic import context

from aeat_hub.models import Base

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=True,  # SQLite: ALTER se hace recreando la tabla
)
with context.begin_transaction():
    context.run_migrations()
