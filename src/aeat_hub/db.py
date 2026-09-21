"""Motor SQLite y sesiones."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from aeat_hub.models import Base
from aeat_hub.paths import DataLayout


def make_engine(layout: DataLayout) -> Engine:
    layout.ensure()
    engine = create_engine(f"sqlite:///{layout.db_path}", future=True)

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _migrate(engine)


def _migrate(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "asientos" in table_names:
        columns = {item["name"] for item in inspector.get_columns("asientos")}
        with engine.begin() as conn:
            if "validado" not in columns:
                conn.execute(text("ALTER TABLE asientos ADD COLUMN validado BOOLEAN NOT NULL DEFAULT 0"))
            if "factura_id" not in columns:
                conn.execute(text("ALTER TABLE asientos ADD COLUMN factura_id INTEGER"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_asientos_factura_id ON asientos (factura_id)"))
    if "cuentas" in table_names:
        columns = {item["name"] for item in inspector.get_columns("cuentas")}
        with engine.begin() as conn:
            if "casilla" not in columns:
                conn.execute(
                    text("ALTER TABLE cuentas ADD COLUMN casilla VARCHAR(40) NOT NULL DEFAULT ''")
                )
            if "sistema" not in columns:
                conn.execute(
                    text("ALTER TABLE cuentas ADD COLUMN sistema BOOLEAN NOT NULL DEFAULT 1")
                )
    if "documentos" in table_names:
        columns = {item["name"] for item in inspector.get_columns("documentos")}
        if "paginas" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE documentos ADD COLUMN paginas INTEGER NOT NULL DEFAULT 1"))
    _backfill_er(engine)


def _backfill_er(engine: Engine) -> None:
    from sqlalchemy.orm import Session

    from aeat_hub.er import backfill_asientos

    with Session(engine) as session:
        if backfill_asientos(session):
            session.commit()


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
