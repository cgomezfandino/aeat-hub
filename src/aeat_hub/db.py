"""Motor SQLite y sesiones."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from aeat_hub.paths import DataLayout


def make_engine(layout: DataLayout) -> Engine:
    layout.ensure()
    engine = create_engine(f"sqlite:///{layout.db_path}", future=True)

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL + busy_timeout para que el CLI y el servidor local convivan
        # sin "database is locked".
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


MIGRATIONS = Path(__file__).resolve().parent / "migrations"
REVISION_BASE = "0001"


def create_schema(engine: Engine) -> None:
    """Deja la base en la última revisión y completa los backfills.

    Una base anterior a Alembic (tablas sin `alembic_version`) pasa primero
    por los ALTER históricos, se sella en la revisión base y sigue migrando.
    """
    tables = set(inspect(engine).get_table_names())
    if tables and "alembic_version" not in tables:
        _migrate_legacy(engine)
        _alembic(engine, "stamp", REVISION_BASE)
    _alembic(engine, "upgrade", "head")
    _backfill_er(engine)
    _backfill_lineas(engine)
    _backfill_campos_fiscales(engine)


def _alembic(engine: Engine, accion: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # Recrear una tabla (batch de SQLite) rompe las FK de sus hijas
            # mientras dura el cambio. Se desactivan solo aquí y se verifica
            # la integridad completa antes de confirmar.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        try:
            with connection.begin():
                config.attributes["connection"] = connection
                getattr(command, accion)(config, revision)
                if sqlite:
                    rotas = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                    if rotas:
                        raise RuntimeError(f"La migración deja claves ajenas rotas: {rotas[:5]}")
        finally:
            if sqlite:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()


def _migrate_legacy(engine: Engine) -> None:
    """ALTER históricos previos a Alembic, congelados: no añadir nada aquí."""
    from aeat_hub.migrations.baseline import por_tabla

    inspector = inspect(engine)
    existentes = set(inspector.get_table_names())
    with engine.begin() as conn:
        for tabla, sentencias in por_tabla().items():
            if tabla not in existentes:
                for sentencia in sentencias:
                    conn.execute(text(sentencia))
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "asientos" in table_names:
        columns = {item["name"] for item in inspector.get_columns("asientos")}
        with engine.begin() as conn:
            if "validado" not in columns:
                conn.execute(text("ALTER TABLE asientos ADD COLUMN validado BOOLEAN NOT NULL DEFAULT 0"))
            if "factura_id" not in columns:
                conn.execute(text("ALTER TABLE asientos ADD COLUMN factura_id INTEGER"))
            if "motivo_rechazo" not in columns:
                conn.execute(text("ALTER TABLE asientos ADD COLUMN motivo_rechazo VARCHAR(200)"))
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


def _backfill_er(engine: Engine) -> None:
    from sqlalchemy.orm import Session

    from aeat_hub.er import backfill_asientos

    with Session(engine) as session:
        if backfill_asientos(session):
            session.commit()


def _backfill_lineas(engine: Engine) -> None:
    from sqlalchemy.orm import Session

    from aeat_hub.edits import backfill_lineas

    with Session(engine) as session:
        if backfill_lineas(session):
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


def _backfill_campos_fiscales(engine: Engine) -> None:
    from sqlalchemy.orm import Session

    from aeat_hub.ingest import backfill_campos_fiscales

    with Session(engine) as session:
        if backfill_campos_fiscales(session):
            session.commit()
