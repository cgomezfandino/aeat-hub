"""Resultado y contrato de un proveedor OCR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class OCRResult:
    text: str
    engine: str
    confidence: float
    pages: int = 1


class ProviderUnavailable(Exception):
    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"{name}: {reason}")
        self.name = name
        self.reason = reason


class OCRProvider(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def transcribe(self, path: Path) -> OCRResult: ...
