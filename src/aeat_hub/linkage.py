"""Scoring de emparejamiento de emisores con Splink (Fellegi-Sunter).

Usa la librería Splink con backend DuckDB (en memoria; el backend SQLite de
Splink tiene las UDF de similitud rotas) y **m/u fijados a mano** con los
priors calibrados del libro: en facturación española el NIF identifica a la
empresa y el nombre es el double check. Sin entrenamiento: determinista y
auditable. Cuando haya datos de sobra, Splink permite entrenar m/u por EM.

Si Splink/DuckDB no están disponibles o algo falla, cae en el scorer a mano
de `extract/nombres.py` (mismo modelo, mismos pesos).
"""

from __future__ import annotations

import math

from aeat_hub.extract.nombres import (
    ScoreEmisor,
    _plano,
    limpiar_nombre,
    probabilidad_mismo_emisor,
    similitud_nombre,
)

# m/u fijados por nivel de comparación (los mismos priors del scorer a mano).
_PESOS: dict[str, list[tuple[float, float]]] = {
    "nif": [(0.99, 4e-6), (4e-6, 0.99)],
    "nombre": [(0.90, 1e-3), (0.06, 2e-3), (0.02, 8e-3), (0.006, 0.989)],
}
_ETIQUETAS: dict[str, list[str]] = {
    "nif": ["igual", "distinto"],
    "nombre": ["JW≥0.95", "JW≥0.85", "JW≥0.70", "else"],
}
_LAMBDA = 1 / 256  # prior: 1 de cada ~256 pares al azar es la misma empresa

_linker_cache = None


def _construir_linker():
    import pandas as pd
    import splink.comparison_library as cl
    import splink.comparison_level_library as cll
    from splink import SettingsCreator
    from splink.backends.duckdb import DuckDBAPI
    from splink.internals.linker import Linker

    def _fijo(nivel, m, u):
        return nivel.configure(
            m_probability=m,
            u_probability=u,
            fix_m_probability=True,
            fix_u_probability=True,
        )

    nif = cl.CustomComparison(
        output_column_name="nif",
        comparison_levels=[
            cll.NullLevel("nif"),
            _fijo(cll.ExactMatchLevel("nif"), *_PESOS["nif"][0]),
            _fijo(cll.ElseLevel(), *_PESOS["nif"][1]),
        ],
    )
    nombre = cl.CustomComparison(
        output_column_name="nombre",
        comparison_levels=[
            cll.NullLevel("nombre"),
            *(
                _fijo(
                    cll.JaroWinklerLevel("nombre", distance_threshold=techo),
                    m,
                    u,
                )
                for techo, (m, u) in zip((0.95, 0.85, 0.70), _PESOS["nombre"][:3])
            ),
            _fijo(cll.ElseLevel(), *_PESOS["nombre"][3]),
        ],
    )
    settings = SettingsCreator(
        link_type="dedupe_only",
        probability_two_random_records_match=_LAMBDA,
        comparisons=[nif, nombre],
        blocking_rules_to_generate_predictions=["l.nif = r.nif", "l.nombre = r.nombre"],
    )
    # semilla mínima: el linker solo se usa con compare_two_records
    semilla = pd.DataFrame([{"unique_id": 0, "nif": None, "nombre": ""}])
    return Linker(semilla, settings, DuckDBAPI())


def _linker():
    global _linker_cache
    if _linker_cache is None:
        _linker_cache = _construir_linker()
    return _linker_cache


def _etiqueta_bf(campo: str, bf: float) -> str:
    for (m, u), etiqueta in zip(_PESOS[campo], _ETIQUETAS[campo]):
        esperado = m / u
        if esperado and abs(bf - esperado) / esperado < 0.01:
            return etiqueta
    return "?"


def score_emisor(
    nif_a: str | None,
    nif_b: str | None,
    nombre_a: str | None,
    nombre_b: str | None,
) -> ScoreEmisor:
    """P(misma empresa) según Splink, con desglose de pesos por comparación.

    El nombre entra limpio y plano para que el Jaro-Winkler compare grafías
    («IKEA IBÉRICA S.A., A28812618,» y «IKEA Ibérica S.A.» → «ikea iberica»).
    """
    try:
        fila = (
            _linker()
            .inference.compare_two_records(
                {"nif": nif_a, "nombre": _plano(limpiar_nombre(nombre_a))},
                {"nif": nif_b, "nombre": _plano(limpiar_nombre(nombre_b))},
            )
            .as_pandas_dataframe()
            .iloc[0]
        )
        peso = float(fila["match_weight"])
        probabilidad = float(fila["match_probability"])
        desglose: list[tuple[str, float]] = []
        for campo in ("nif", "nombre"):
            bf = fila.get(f"bf_{campo}")
            if bf is None or math.isnan(float(bf)):
                desglose.append((f"{campo} ausente", 0.0))
                continue
            bits = math.log2(float(bf))
            if abs(bits) < 0.01:
                desglose.append((f"{campo} ausente", 0.0))
                continue
            desglose.append((f"{campo} {_etiqueta_bf(campo, float(bf))}", bits))
        base = peso - sum(bits for _concepto, bits in desglose)
        desglose.insert(0, ("base (prior)", base))
        return ScoreEmisor(
            probabilidad=probabilidad,
            peso_bits=peso,
            similitud=similitud_nombre(nombre_a, nombre_b),
            desglose=desglose,
        )
    except Exception:  # noqa: BLE001 - Splink es una mejora, no un requisito
        return probabilidad_mismo_emisor(nif_a, nif_b, nombre_a, nombre_b)
