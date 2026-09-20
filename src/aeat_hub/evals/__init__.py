"""Evaluación rigurosa de motores OCR + parser de factura española."""

from aeat_hub.evals.gold import GoldCase, GoldFields
from aeat_hub.evals.runner import EvalReport, run_eval

__all__ = ["EvalReport", "GoldCase", "GoldFields", "run_eval"]
