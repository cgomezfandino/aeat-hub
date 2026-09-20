"""Bake-off de motores OCR: cada motor por separado, sin cascada."""

from __future__ import annotations

import platform
import statistics
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from aeat_hub.evals.gold import GoldCase
from aeat_hub.evals.metrics import score_emisor, score_fields, score_tokens
from aeat_hub.extract.parser import parse_invoice
from aeat_hub.ocr.apple_vision import AppleVisionProvider
from aeat_hub.ocr.base import OCRProvider, ProviderUnavailable
from aeat_hub.ocr.ollama_deepseek import OllamaOCRProvider
from aeat_hub.ocr.paddle_vl import PaddleVLProvider
from aeat_hub.ocr.pdf_native import PdfNativeProvider
from aeat_hub.ocr.rapid import RapidOCRProvider
from aeat_hub.ocr.tesseract import TesseractProvider
from aeat_hub.ocr.unlimited import UnlimitedOCRProvider

ENGINE_ORDER = ("native", "rapid", "vision", "deepseek", "tesseract", "unlimited", "paddle")

PROVIDERS: dict[str, Callable[[], OCRProvider]] = {
    "native": PdfNativeProvider,
    "rapid": RapidOCRProvider,
    "vision": AppleVisionProvider,
    "deepseek": OllamaOCRProvider,
    "tesseract": TesseractProvider,
    "unlimited": UnlimitedOCRProvider,
    "paddle": PaddleVLProvider,
}

IMAGE_KINDS = {"photo", "raster"}


@dataclass
class EngineRun:
    engine: str
    case_id: str
    status: str
    reason: str = ""
    latency_ms: int = 0
    chars: int = 0
    token_recall: float | None = None
    ocr_field_recall: float | None = None
    parser_accuracy: float | None = None
    emisor_ok: bool | None = None
    tokens: dict = field(default_factory=dict)
    fields: dict = field(default_factory=dict)
    preview: str = ""


@dataclass
class EngineSummary:
    engine: str
    available: bool
    reason: str
    applicable: int = 0
    skipped: int = 0
    errors: int = 0
    token_recall: float | None = None
    ocr_field_recall: float | None = None
    parser_accuracy: float | None = None
    median_latency_ms: int | None = None
    mean_latency_ms: int | None = None


@dataclass
class EvalReport:
    started_at: str
    hardware: str
    gold_path: str
    cases: list[str]
    engines: list[str]
    runs: list[EngineRun]
    summaries: list[EngineSummary]
    ranking: list[str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "hardware": self.hardware,
            "gold_path": self.gold_path,
            "cases": self.cases,
            "engines": self.engines,
            "runs": [asdict(item) for item in self.runs],
            "summaries": [asdict(item) for item in self.summaries],
            "ranking": self.ranking,
            "notes": self.notes,
        }


def list_engine_status() -> list[tuple[str, bool, str]]:
    rows = []
    for name in ENGINE_ORDER:
        ok, reason = PROVIDERS[name]().available()
        rows.append((name, ok, reason))
    return rows


def run_eval(
    cases: list[GoldCase],
    *,
    engines: list[str] | None = None,
    gold_path: str = "",
    providers: dict[str, OCRProvider] | None = None,
) -> EvalReport:
    selected = _normalize_engines(engines)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hardware = f"{platform.system()} {platform.machine()} {platform.processor()}".strip()
    notes: list[str] = []
    if not cases:
        notes.append("No hay casos de oro.")
    instances: dict[str, OCRProvider] = dict(providers or {})
    runs: list[EngineRun] = []
    for engine in selected:
        provider = instances.get(engine)
        if provider is None:
            provider = PROVIDERS[engine]()
            instances[engine] = provider
        ok, reason = provider.available()
        for case in cases:
            if not ok:
                runs.append(
                    EngineRun(
                        engine=engine,
                        case_id=case.id,
                        status="unavailable",
                        reason=reason,
                    )
                )
                continue
            if engine == "native" and (
                case.path.suffix.lower() != ".pdf" or case.kind in IMAGE_KINDS
            ):
                runs.append(
                    EngineRun(
                        engine=engine,
                        case_id=case.id,
                        status="skipped",
                        reason="pdf-native solo aplica a PDF con capa de texto",
                    )
                )
                continue
            if not case.path.is_file():
                runs.append(
                    EngineRun(
                        engine=engine,
                        case_id=case.id,
                        status="error",
                        reason=f"no existe {case.path}",
                    )
                )
                continue
            runs.append(_run_one(provider, engine, case))
    summaries = _summarize(selected, instances, runs)
    ranking = _rank(summaries)
    if len(cases) < 8:
        notes.append(
            f"n={len(cases)} documentos: útil para esta muestra (tickets Leroy + sintético), "
            "no para generalizar a todo tipo de factura."
        )
    notes.append(
        "Dos capas: recall de tokens / campos en el texto OCR (calidad del motor) "
        "y exactitud del parser (calidad del extracto fiscal). Un fallo de parser "
        "con OCR correcto no se atribuye al modelo."
    )
    return EvalReport(
        started_at=started,
        hardware=hardware,
        gold_path=gold_path,
        cases=[case.id for case in cases],
        engines=selected,
        runs=runs,
        summaries=summaries,
        ranking=ranking,
        notes=notes,
    )


def _normalize_engines(engines: list[str] | None) -> list[str]:
    if not engines:
        return list(ENGINE_ORDER)
    aliases = {
        "pdf-native": "native",
        "rapidocr": "rapid",
        "apple-vision": "vision",
        "apple": "vision",
        "deepseek": "deepseek",
        "deepseek-ocr": "deepseek",
        "ollama": "deepseek",
        "unlimited-ocr": "unlimited",
        "paddleocr-vl": "paddle",
        "paddleocr": "paddle",
    }
    selected: list[str] = []
    for raw in engines:
        name = aliases.get(raw.strip().lower(), raw.strip().lower())
        if name not in PROVIDERS:
            raise ValueError(f"Motor desconocido: {raw}. Válidos: {', '.join(ENGINE_ORDER)}")
        if name not in selected:
            selected.append(name)
    return selected


def _run_one(provider: OCRProvider, engine: str, case: GoldCase) -> EngineRun:
    t0 = time.perf_counter()
    try:
        result = provider.transcribe(case.path)
    except ProviderUnavailable as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        return EngineRun(
            engine=engine,
            case_id=case.id,
            status="unavailable",
            reason=str(exc),
            latency_ms=ms,
        )
    except Exception as exc:  # noqa: BLE001
        ms = int((time.perf_counter() - t0) * 1000)
        return EngineRun(
            engine=engine,
            case_id=case.id,
            status="error",
            reason=f"{type(exc).__name__}: {exc}",
            latency_ms=ms,
            preview=traceback.format_exc()[-400:],
        )
    ms = int((time.perf_counter() - t0) * 1000)
    text = result.text or ""
    extract = parse_invoice(text, motor=result.engine)
    tokens = score_tokens(case.must_tokens, text)
    fields = score_fields(case.scored_fields(), extract, text)
    emisor_ok = score_emisor(case.fields.emisor_contains, extract, text)
    fields["emisor_ok"] = emisor_ok
    preview = " ".join(text.split())[:240]
    return EngineRun(
        engine=engine,
        case_id=case.id,
        status="ok",
        latency_ms=ms,
        chars=len(text),
        token_recall=tokens["recall"],
        ocr_field_recall=fields["ocr_recall"],
        parser_accuracy=fields["parser_accuracy"],
        emisor_ok=emisor_ok,
        tokens=tokens,
        fields=fields,
        preview=preview,
    )


def _summarize(
    engines: list[str],
    instances: dict[str, OCRProvider],
    runs: list[EngineRun],
) -> list[EngineSummary]:
    summaries: list[EngineSummary] = []
    for engine in engines:
        ok, reason = instances[engine].available()
        subset = [item for item in runs if item.engine == engine]
        applicable = [item for item in subset if item.status == "ok"]
        skipped = sum(1 for item in subset if item.status == "skipped")
        errors = sum(1 for item in subset if item.status == "error")
        latencies = [item.latency_ms for item in applicable]
        zeros = [0.0] * errors
        summary = EngineSummary(
            engine=engine,
            available=ok,
            reason=reason,
            applicable=len(applicable),
            skipped=skipped,
            errors=errors,
            token_recall=_mean([item.token_recall for item in applicable] + zeros),
            ocr_field_recall=_mean([item.ocr_field_recall for item in applicable] + zeros),
            parser_accuracy=_mean([item.parser_accuracy for item in applicable] + zeros),
            median_latency_ms=int(statistics.median(latencies)) if latencies else None,
            mean_latency_ms=int(statistics.mean(latencies)) if latencies else None,
        )
        summaries.append(summary)
    return summaries


def _mean(values: list[float | None]) -> float | None:
    present = [item for item in values if item is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 4)


def _rank(summaries: list[EngineSummary]) -> list[str]:
    scored = [
        item
        for item in summaries
        if item.available and item.applicable and item.ocr_field_recall is not None
    ]
    scored.sort(
        key=lambda item: (
            item.ocr_field_recall or 0.0,
            item.token_recall or 0.0,
            item.parser_accuracy or 0.0,
            -(item.median_latency_ms or 10**9),
        ),
        reverse=True,
    )
    return [item.engine for item in scored]
