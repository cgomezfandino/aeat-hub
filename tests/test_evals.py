from datetime import date
from decimal import Decimal
from pathlib import Path

from aeat_hub.evals.gold import GoldCase, GoldFields, dump_gold, load_gold
from aeat_hub.evals.metrics import field_in_ocr, score_tokens, token_in_text
from aeat_hub.evals.runner import run_eval
from aeat_hub.evals.suite import SYNTHETIC_LUZ, make_synthetic_cases
from aeat_hub.extract.parser import parse_invoice
from aeat_hub.ocr.base import OCRResult
from aeat_hub.paths import DataLayout
from typer.testing import CliRunner

from aeat_hub.cli import app

runner = CliRunner()


def test_token_hyphen_nif_and_spanish_amount():
    text = "N.I.F. B-84818442  Total TTI 13,86 EUR"
    exact, fuzzy = token_in_text("B84818442", text)
    assert exact and not fuzzy
    exact, fuzzy = token_in_text("13.86", text)
    assert exact
    scored = score_tokens(["B84818442", "13,86", "NO-ESTA"], text)
    assert scored["hits"] == 2
    assert scored["recall"] == 2 / 3


def test_field_in_ocr_fecha_and_total():
    text = "Fecha de venta 18/09/2026\nTotal TTI (EUR) 13,86"
    assert field_in_ocr("fecha", "2026-09-18", text)
    assert field_in_ocr("total", "13.86", text)
    assert field_in_ocr("nif_emisor", "B84818442", "CIF B-84818442")


def test_load_gold_resolves_against_data_root(tmp_path: Path):
    layout_root = tmp_path / "data"
    rel = Path("archivo/doc.pdf")
    target = layout_root / rel
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF")
    gold = tmp_path / "evals" / "gold.json"
    case = GoldCase(
        id="x",
        path=rel,
        kind="digital-pdf",
        fields=GoldFields(total=Decimal("1.00")),
        must_tokens=["A"],
    )
    dump_gold(gold, [case], root=layout_root)
    loaded = load_gold(gold, root=layout_root)
    assert loaded[0].path == target.resolve()


class _FakeNative:
    name = "pdf-native"

    def available(self):
        return True, "fake"

    def transcribe(self, path: Path) -> OCRResult:
        return OCRResult(text=SYNTHETIC_LUZ, engine=self.name, confidence=0.9)


def test_runner_scores_synthetic_native(tmp_path: Path):
    cases = make_synthetic_cases(tmp_path / "syn")
    report = run_eval(
        cases,
        engines=["native"],
        gold_path="memory",
        providers={"native": _FakeNative()},
    )
    by_id = {run.case_id: run for run in report.runs}
    digital = by_id["synthetic-luz-digital"]
    raster = by_id["synthetic-luz-raster"]
    assert digital.status == "ok"
    assert digital.token_recall == 1.0
    assert digital.ocr_field_recall == 1.0
    assert raster.status == "skipped"
    assert report.ranking == ["native"]


def test_cli_eval_synthetic_native(layout: DataLayout):
    result = runner.invoke(
        app,
        ["eval", "--data-dir", str(layout.root), "--engines", "native", "--synthetic"],
    )
    assert result.exit_code == 0, result.output
    assert "synthetic-luz-digital" in result.output
    assert "EVALS" in result.output
    jsons = list((layout.root / "evals").glob("eval-*.json"))
    assert jsons, "debe escribir el informe JSON en el data-dir"


def test_parser_on_synthetic_luz_is_complete():
    extract = parse_invoice(SYNTHETIC_LUZ, motor="test")
    assert extract.nif_emisor == "B12345674"
    assert extract.numero == "F2026-000123"
    assert extract.fecha == date(2026, 3, 10)
    assert extract.total == Decimal("48.40")
