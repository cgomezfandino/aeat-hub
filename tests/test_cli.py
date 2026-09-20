from typer.testing import CliRunner

from aeat_hub.cli import app
from aeat_hub.fiscal.accounts import CODIGO_DEMO_CI

runner = CliRunner()


def test_cli_init_ingest_pendientes_export(layout, tmp_path):
    result = runner.invoke(app, ["init", "--data-dir", str(layout.root)])
    assert result.exit_code == 0, result.output
    assert "CI-VA-001" in result.output

    listed = runner.invoke(app, ["actividad", "listar", "--data-dir", str(layout.root)])
    assert listed.exit_code == 0
    assert CODIGO_DEMO_CI in listed.output

    cuentas = runner.invoke(app, ["cuentas", "--data-dir", str(layout.root), "--regimen", "capital_inmobiliario"])
    assert cuentas.exit_code == 0
    assert "Ventanas" in cuentas.output

    empty = runner.invoke(
        app, ["ingest", "--data-dir", str(layout.root), "--actividad", CODIGO_DEMO_CI]
    )
    assert empty.exit_code == 0
    assert "Inbox vacío" in empty.output

    dash = runner.invoke(
        app,
        [
            "dashboard",
            "--data-dir",
            str(layout.root),
            "--actividad",
            CODIGO_DEMO_CI,
            "--year",
            "2026",
            "--no-open",
        ],
    )
    assert dash.exit_code == 0, dash.output
    dest = layout.exports / "dashboard_CI-VA-001_2026.html"
    assert dest.is_file()
    html = dest.read_text(encoding="utf-8")
    assert "Alquiler Valladolid" in html
    assert "libro auxiliar" in html.lower()


def test_cli_actividad_alta_ae(layout):
    runner.invoke(app, ["init", "--data-dir", str(layout.root)])
    result = runner.invoke(
        app,
        [
            "actividad",
            "alta",
            "--data-dir",
            str(layout.root),
            "--nombre",
            "Taller demo",
            "--regimen",
            "actividad_economica",
            "--codigo",
            "AE-TALLER",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "AE-TALLER" in result.output


def test_cli_cuentas_no_enseña_ids_internos(layout):
    runner.invoke(app, ["init", "--data-dir", str(layout.root)])
    cuentas = runner.invoke(
        app, ["cuentas", "--data-dir", str(layout.root), "--regimen", "capital_inmobiliario"]
    )
    assert cuentas.exit_code == 0, cuentas.output
    assert "Hogar" in cuentas.output
    assert "Ventanas" in cuentas.output
    assert "CI.MEJ.PVC" not in cuentas.output
    assert "CI.GAS.HOGAR" not in cuentas.output


def test_cli_cuenta_alta_y_reclasificar_por_nombre(layout):
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import select

    from aeat_hub.db import make_engine, session_factory
    from aeat_hub.models import Actividad, Asiento
    from aeat_hub.services import initialize

    initialize(layout)
    engine = make_engine(layout)
    factory = session_factory(engine)
    with factory() as db:
        actividad = db.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
        asiento = Asiento(
            actividad_id=actividad.id,
            tipo="gasto",
            fecha=date(2026, 9, 5),
            ejercicio=2026,
            emisor="LEROY",
            nif_emisor="B84818442",
            total=Decimal("31.45"),
            estado="pendiente",
        )
        db.add(asiento)
        db.commit()
        asiento_id = asiento.id

    alta = runner.invoke(
        app,
        [
            "cuenta",
            "alta",
            "--data-dir",
            str(layout.root),
            "--nombre",
            "Pintura",
            "--casilla",
            "reparacion",
        ],
    )
    assert alta.exit_code == 0, alta.output
    assert "Pintura" in alta.output
    assert "CI.GAS." not in alta.output

    rec = runner.invoke(
        app,
        ["reclasificar", str(asiento_id), "Pintura", "--data-dir", str(layout.root), "--solo-este"],
    )
    assert rec.exit_code == 0, rec.output
    assert "Pintura" in rec.output
    assert "CI.GAS." not in rec.output
