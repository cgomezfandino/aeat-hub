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
    assert "CI.MEJ.PVC" in cuentas.output

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
