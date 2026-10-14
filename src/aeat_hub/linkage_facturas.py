"""Detección de duplicados factura-contra-factura con Splink.

Modelo Fellegi-Sunter sobre los campos que ya tiene cada asiento:
NIF emisor, número normalizado, fecha, importe exacto (céntimos) y nombre
limpio. Devuelve pares con P(misma factura) y su desglose de pesos para
mencionarlos como sospechosos — la decisión sigue siendo humana.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from aeat_hub.extract.ids import normalize_numero
from aeat_hub.extract.nombres import _plano, limpiar_nombre
from aeat_hub.models import Actividad, Asiento

UMBRAL_MENCION = 0.90

# m/u fijadas por nivel (priors calibrados a mano, jugables como las del emisor).
#
# u es la probabilidad de coincidir entre DOS FACTURAS CUALESQUIERA DEL MISMO
# LIBRO, no entre dos personas al azar: en un libro de gastos el mismo
# proveedor se repite (alquiler, luz, cuotas), así que "mismo NIF" ocurre en
# ~5 % de pares (u=0.05), no en 4e-6. Con u=4e-6 toda factura recurrente del
# mismo importe salía como duplicada (P≈0,96). Números distintos sí son
# habituales en la misma compra (ticket canjeado por factura): m=0.10.
_PRIOR = 1 / 2048
_PESOS: dict[str, list[tuple[float, float]]] = {
    "nif": [(0.99, 0.05), (0.01, 0.95)],
    "numero": [(0.97, 1e-5), (0.10, 0.9999)],
    "fecha": [(0.75, 0.01), (0.10, 0.06), (0.02, 0.95)],
    "importe": [(0.95, 0.02), (0.00005, 0.999)],
    "nombre": [(0.90, 0.05), (0.50, 0.10), (0.02, 0.95)],
    "skus": [(0.90, 0.0005), (0.08, 0.01), (0.02, 0.9895)],
}
_ETIQUETAS: dict[str, list[str]] = {
    "nif": ["igual", "distinto"],
    "numero": ["igual", "distinto"],
    "fecha": ["igual", "misma semana", "distinta"],
    "importe": ["igual", "distinto"],
    "nombre": ["JW≥0.95", "JW≥0.85", "distinto"],
    "skus": ["≥2 coincidentes", "1 coincidente", "sin coincidencia"],
}


@dataclass
class SospechosoFactura:
    id_a: int
    id_b: int
    probabilidad: float
    peso_bits: float
    desglose: list[tuple[str, float]] = field(default_factory=list)


def _semana(fecha: date | None) -> str:
    if fecha is None:
        return ""
    iso = fecha.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _df_filas(asientos: list[Asiento]) -> list[dict]:
    out = []
    for a in asientos:
        skus = [l.codigo for l in a.lineas if l.codigo and not l.eliminada]
        out.append(
            {
                "unique_id": a.id,
                "nif": a.nif_emisor or None,
                "numero": normalize_numero(a.numero_factura),
                "fecha": a.fecha.isoformat() if a.fecha else None,
                "semana": _semana(a.fecha) or None,
                "importe": int(round(float(a.total) * 100)) if a.total is not None else None,
                "nombre": _plano(limpiar_nombre(a.emisor)) or None,
                "skus": skus if skus else None,
            }
        )
    return out


def _construir_linker(frame, *, blocking_rules: list[str] | None = None):
    import splink.comparison_library as cl
    import splink.comparison_level_library as cll
    from splink import SettingsCreator
    from splink.backends.duckdb import DuckDBAPI
    from splink.internals.linker import Linker

    def _fijo(nivel, m, u):
        return nivel.configure(
            m_probability=m, u_probability=u, fix_m_probability=True, fix_u_probability=True
        )

    def _exacto(campo: str):
        return [
            cll.NullLevel(campo),
            _fijo(cll.ExactMatchLevel(campo), *_PESOS[campo][0]),
            _fijo(cll.ElseLevel(), *_PESOS[campo][1]),
        ]

    comparaciones = [
        cl.CustomComparison(output_column_name="nif", comparison_levels=_exacto("nif")),
        cl.CustomComparison(output_column_name="numero", comparison_levels=_exacto("numero")),
        cl.CustomComparison(
            output_column_name="fecha",
            comparison_levels=[
                cll.NullLevel("fecha"),
                _fijo(cll.ExactMatchLevel("fecha"), *_PESOS["fecha"][0]),
                _fijo(cll.ExactMatchLevel("semana"), *_PESOS["fecha"][1]),
                _fijo(cll.ElseLevel(), *_PESOS["fecha"][2]),
            ],
        ),
        cl.CustomComparison(output_column_name="importe", comparison_levels=_exacto("importe")),
        cl.CustomComparison(
            output_column_name="nombre",
            comparison_levels=[
                cll.NullLevel("nombre"),
                _fijo(
                    cll.JaroWinklerLevel("nombre", distance_threshold=0.95),
                    *_PESOS["nombre"][0],
                ),
                _fijo(
                    cll.JaroWinklerLevel("nombre", distance_threshold=0.85),
                    *_PESOS["nombre"][1],
                ),
                _fijo(cll.ElseLevel(), *_PESOS["nombre"][2]),
            ],
        ),
        cl.CustomComparison(
            output_column_name="skus",
            comparison_levels=[
                cll.NullLevel("skus"),
                _fijo(
                    cll.CustomLevel(
                        "len(list_intersect(try_cast(skus_l as VARCHAR[]), try_cast(skus_r as VARCHAR[]))) >= 2",
                        "≥2 coincidentes",
                    ),
                    *_PESOS["skus"][0],
                ),
                _fijo(
                    cll.CustomLevel(
                        "len(list_intersect(try_cast(skus_l as VARCHAR[]), try_cast(skus_r as VARCHAR[]))) >= 1",
                        "1 coincidente",
                    ),
                    *_PESOS["skus"][1],
                ),
                _fijo(cll.ElseLevel(), *_PESOS["skus"][2]),
            ],
        ),
    ]
    rules = blocking_rules or [
        "l.nif = r.nif",
        "l.numero = r.numero and l.numero != ''",
        "l.importe = r.importe",
    ]
    settings = SettingsCreator(
        link_type="dedupe_only",
        probability_two_random_records_match=_PRIOR,
        comparisons=comparaciones,
        blocking_rules_to_generate_predictions=rules,
    )
    return Linker(frame, settings, DuckDBAPI())


def escanear_duplicados(
    session: Session,
    actividad: Actividad,
    *,
    umbral: float | None = None,
) -> list[SospechosoFactura]:
    """Pares de asientos con P(misma factura) ≥ umbral, para mencionar."""
    if umbral is None:
        umbral = UMBRAL_MENCION
    vivos = session.scalars(
        select(Asiento)
        .where(Asiento.actividad_id == actividad.id, Asiento.estado.notin_(("duplicado", "rechazado")))
        .options(joinedload(Asiento.lineas))
        .order_by(Asiento.id)
    ).unique().all()
    if len(vivos) < 2:
        return []
    por_id = {a.id: a for a in vivos}
    try:
        import pandas as pd

        linker = _construir_linker(pd.DataFrame(_df_filas(vivos)))
        pred = linker.inference.predict().as_pandas_dataframe()
    except Exception:  # noqa: BLE001 - Splink es una mejora, no un requisito
        return []
    out: list[SospechosoFactura] = []
    for fila in pred.itertuples(index=False):
        ida, idb = int(fila.unique_id_l), int(fila.unique_id_r)
        if ida >= idb:
            continue
        a, b = por_id.get(ida), por_id.get(idb)
        if a is None or b is None:
            continue
        if a.factura_id and a.factura_id == b.factura_id:
            continue
        if a.duplicado_de_id == b.id or b.duplicado_de_id == a.id:
            continue
        probabilidad = float(fila.match_probability)
        if probabilidad < umbral:
            continue
        peso = float(fila.match_weight)
        desglose: list[tuple[str, float]] = []
        for campo in ("nif", "numero", "fecha", "importe", "nombre", "skus"):
            gamma = getattr(fila, f"gamma_{campo}", None)
            niveles = len(_PESOS[campo])
            if gamma is None or int(gamma) < 0:
                desglose.append((f"{campo} ausente", 0.0))
                continue
            # splink numera gamma del nivel más genérico (else=0) al más
            # específico, sin contar el nivel nulo.
            indice = niveles - 1 - int(gamma)
            if indice < 0 or indice >= niveles:
                desglose.append((f"{campo} ausente", 0.0))
                continue
            m, u = _PESOS[campo][indice]
            desglose.append((f"{campo} {_ETIQUETAS[campo][indice]}", math.log2(m / u)))
        base = peso - sum(bits for _c, bits in desglose)
        desglose.insert(0, ("base (prior)", base))
        out.append(
            SospechosoFactura(
                id_a=ida, id_b=idb, probabilidad=probabilidad, peso_bits=peso, desglose=desglose
            )
        )
    out.sort(key=lambda s: -s.probabilidad)
    return out


def score_par_splink(
    asiento_a: Asiento,
    asiento_b: Asiento,
) -> tuple[float, float, list[tuple[str, float]]] | None:
    """Calcula P(misma factura), peso total en bits y desglose para un par concreto usando Splink."""
    try:
        import pandas as pd

        rows = _df_filas([asiento_a, asiento_b])
        linker = _construir_linker(pd.DataFrame(rows), blocking_rules=["l.unique_id < r.unique_id"])
        pred = linker.inference.predict().as_pandas_dataframe()
        for fila in pred.itertuples(index=False):
            ida, idb = int(fila.unique_id_l), int(fila.unique_id_r)
            if {ida, idb} == {asiento_a.id, asiento_b.id}:
                probabilidad = float(fila.match_probability)
                peso = float(fila.match_weight)
                desglose: list[tuple[str, float]] = []
                for campo in ("nif", "numero", "fecha", "importe", "nombre", "skus"):
                    gamma = getattr(fila, f"gamma_{campo}", None)
                    niveles = len(_PESOS[campo])
                    if gamma is None or int(gamma) < 0:
                        desglose.append((f"{campo} ausente", 0.0))
                        continue
                    indice = niveles - 1 - int(gamma)
                    if indice < 0 or indice >= niveles:
                        desglose.append((f"{campo} ausente", 0.0))
                        continue
                    m, u = _PESOS[campo][indice]
                    desglose.append((f"{campo} {_ETIQUETAS[campo][indice]}", math.log2(m / u)))
                base = peso - sum(bits for _c, bits in desglose)
                desglose.insert(0, ("base (prior)", base))
                return probabilidad, peso, desglose
    except Exception:
        return None
    return None
