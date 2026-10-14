"""Migraciones Alembic: esquema idéntico a los modelos y bases antiguas intactas."""

from datetime import date
from decimal import Decimal
import json

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text

from aeat_hub.db import create_schema, make_engine, session_factory
from aeat_hub.ingest import aplicar_campos_fiscales
from aeat_hub.extract.schema import DesgloseIVA, InvoiceExtract
from aeat_hub.migrations.baseline import statements
from aeat_hub.models import Asiento, Base
from aeat_hub.paths import DataLayout


def _head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from aeat_hub.db import MIGRATIONS

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    return ScriptDirectory.from_config(config).get_current_head()


def _layout(tmp_path) -> DataLayout:
    layout = DataLayout(tmp_path / "data")
    layout.ensure()
    return layout


def test_migraciones_dejan_el_esquema_de_los_modelos(tmp_path):
    engine = make_engine(_layout(tmp_path))
    create_schema(engine)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == []


def _base_antigua(engine) -> None:
    """Una base creada por el código anterior: REAL en importes, sin Alembic."""
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        for sentencia in statements():
            conn.execute(text(sentencia))
        conn.execute(text("INSERT INTO titulares (id, nif, nombre, tipo) VALUES (1, '12345678Z', 'Titular', 'fisica')"))
        conn.execute(
            text(
                "INSERT INTO actividades (id, codigo, titular_id, nombre, regimen) "
                "VALUES (1, 'CI-VA-001', 1, 'Piso', 'capital_inmobiliario')"
            )
        )
        extract = {
            "emisor": "ASESORIA LOPEZ",
            "nif_emisor": "B12345674",
            "receptor": "Titular",
            "nif_receptor": "12345678Z",
            "tipo_documento": "factura",
            "base": 100.0,
            "iva_cuota": 21.0,
            "retencion_tipo": 15.0,
            "retencion_cuota": 15.0,
            "total": 106.0,
            "desglose_iva": [{"base": 100.0, "iva_tipo": 21.0, "iva_cuota": 21.0}],
        }
        conn.execute(
            text(
                "INSERT INTO documentos (id, sha256, nombre_original, ruta_almacenada, mime, motor_ocr, "
                "texto_crudo, json_extraido, confianza, paginas) "
                "VALUES (1, :sha, 'a.pdf', '/a.pdf', 'application/pdf', 'gemini', '', :js, 0.98, 1)"
            ),
            {"sha": "a" * 64, "js": json.dumps(extract)},
        )
        for idx, total in enumerate((0.1, 0.2, 106.0), start=1):
            conn.execute(
                text(
                    "INSERT INTO asientos (id, actividad_id, documento_id, tipo, fecha, ejercicio, nif_emisor, "
                    "descripcion, base, iva_tipo, iva_cuota, total, estado, confianza_clasificacion, "
                    "origen_clasificacion, validado) VALUES (:id, 1, :doc, 'gasto', '2026-03-01', 2026, "
                    "'B12345674', '', NULL, 21.0, NULL, :total, 'pendiente', 0, 'pendiente', 0)"
                ),
                {"id": idx, "doc": 1 if idx == 3 else None, "total": total},
            )
        # hijas con FK a asientos: la recreación de la tabla no puede romperlas
        conn.execute(
            text(
                "INSERT INTO lineas (asiento_id, posicion, descripcion, importe, eliminada) "
                "VALUES (3, 1, 'Honorarios', 100.0, 0)"
            )
        )
        conn.execute(
            text("INSERT INTO cambios (asiento_id, campo, antes, despues, fuente) VALUES (3, 'total', '', '106.00', 'cli')")
        )


def test_base_antigua_migra_importes_exactos_y_recupera_campos(tmp_path):
    engine = make_engine(_layout(tmp_path))
    _base_antigua(engine)
    create_schema(engine)

    with engine.connect() as conn:
        assert conn.execute(text("select version_num from alembic_version")).scalar() == _head()
        # el SUM en SQL ya es exacto: céntimos enteros
        assert conn.execute(text("select sum(total) from asientos where id in (1, 2)")).scalar() == 30
        assert conn.execute(text("select typeof(total) from asientos where id = 1")).scalar() == "integer"
        assert conn.execute(text("select importe from lineas")).scalar() == 10000
        assert conn.execute(text("select count(*) from cambios")).scalar() == 1
    assert "asiento_iva" in inspect(engine).get_table_names()

    factory = session_factory(engine)
    with factory() as session:
        uno, dos, tres = session.scalars(select(Asiento).order_by(Asiento.id)).all()
        assert uno.total + dos.total == Decimal("0.30")
        assert tres.total == Decimal("106.00")
        assert tres.iva_tipo == Decimal("21.00")
        # recuperado del JSON guardado, sin volver a leer el documento
        assert tres.nif_receptor == "12345678Z"
        assert tres.retencion_cuota == Decimal("15.00")
        assert tres.tipo_factura == "completa"
        assert [(d.base, d.tipo, d.cuota) for d in tres.desglose_iva] == [
            (Decimal("100.00"), Decimal("21.00"), Decimal("21.00"))
        ]
        assert uno.tipo_factura is None  # sin documento: no hay de dónde sacarlo


def test_create_schema_es_idempotente(tmp_path):
    engine = make_engine(_layout(tmp_path))
    create_schema(engine)
    create_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from alembic_version")).scalar() == 1


def test_aplicar_campos_fiscales_direccion_y_desglose():
    asiento = Asiento(nif_emisor="12345678Z")
    extract = InvoiceExtract(
        nif_emisor="12345678Z",
        nif_receptor="b-12345674",
        tipo_documento="ticket",
        desglose_iva=[
            DesgloseIVA(base=Decimal("100"), iva_tipo=Decimal("21"), iva_cuota=Decimal("21")),
            DesgloseIVA(base=Decimal("50"), iva_tipo=Decimal("10"), iva_cuota=Decimal("5")),
        ],
    )
    aplicar_campos_fiscales(asiento, extract, "12345678Z")
    assert asiento.direccion == "emitida"
    assert asiento.nif_receptor == "B12345674"
    assert asiento.tipo_factura == "simplificada"
    assert len(asiento.desglose_iva) == 2


def test_rectificativa_se_reconoce_por_la_referencia():
    asiento = Asiento(nif_emisor="B12345674")
    aplicar_campos_fiscales(
        asiento, InvoiceExtract(tipo_documento="factura", factura_rectificada="F-100"), "12345678Z"
    )
    assert asiento.tipo_factura == "rectificativa"
    assert asiento.direccion == "recibida"
