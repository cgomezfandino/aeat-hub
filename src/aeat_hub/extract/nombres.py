"""Nombres de emisor: limpieza de formas societarias y similitud.

Un mismo emisor llega del OCR con variantes («IKEA IBÉRICA S.A., A28812618,»,
«IKEA Ibérica S.A.»). La clave fiscal es el NIF: dentro de un mismo NIF,
las variantes se comparan y se adopta un nombre canónico si la similitud
supera el umbral. La limpieza de formas societarias usa cleanco (base
internacional) más un diccionario español.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from cleanco import prepare_default_terms
from cleanco.clean import custom_basename

# Formas societarias españolas que la base internacional de cleanco no
# trae, ya normalizadas (minúsculas, sin puntos ni acentos). Formato de
# cleanco: una tupla (n_palabras, [palabra, ...]) por término.
_TERMINOS_ES: list[tuple[int, list[str]]] = [
    (1, [t]) for t in ("sa", "sl", "sau", "slu", "sc", "scp", "scl", "unipersonal", "eirl", "srl")
] + [
    (2, ["s", "a"]),
    (2, ["s", "l"]),
    (2, ["sociedad", "anonima"]),
    (2, ["sociedad", "limitada"]),
    (2, ["sociedad", "cooperativa"]),
    (3, ["s", "a", "u"]),
    (3, ["s", "l", "u"]),
    (3, ["sociedad", "anonima", "laboral"]),
    (3, ["sociedad", "anonima", "unipersonal"]),
    (3, ["sociedad", "limitada", "laboral"]),
    (3, ["sociedad", "limitada", "unipersonal"]),
]

_TERMINOS = sorted(
    [*prepare_default_terms(), *_TERMINOS_ES],
    key=lambda par: (-par[0], par[1]),
)

# Token de NIF pegado al nombre («... S.A., A28812618,»).
_NIF_TOKEN = re.compile(r"\b[AB]\d{8}\b", re.IGNORECASE)
# Coma/semicolon pegados a la forma societaria («BRICOMAN,S.L.U.»).
_PUNCT_PEGADA = re.compile(r"(?<=[,;])(?=\S)")
_SPACES = re.compile(r"\s+")
_PUNCT_BORDE = re.compile(r"^[\s,;:.\-·]+|[\s,;:.\-·]+$")

UMBRAL_NOMBRE = 0.85


def limpiar_nombre(nombre: str | None) -> str:
    """Quita formas societarias y ruido para comparar («según el país»)."""
    if not nombre:
        return ""
    texto = _NIF_TOKEN.sub(" ", nombre)
    texto = _PUNCT_PEGADA.sub(" ", texto)
    texto = _PUNCT_BORDE.sub(" ", texto)
    # dos pasadas para sufijos apilados (S.A.U. → S.A. → limpio)
    for _ in range(2):
        siguiente = custom_basename(texto, terms=_TERMINOS)
        if siguiente == texto:
            break
        texto = siguiente
    return _SPACES.sub(" ", texto).strip(" ,;:.-·")


def _plano(texto: str) -> str:
    """Minúsculas sin acentos: el OCR pierde tildes con frecuencia."""
    sin_acentos = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(ch for ch in sin_acentos if not unicodedata.combining(ch))
    return sin_acentos.casefold().strip()


def similitud_nombre(a: str | None, b: str | None) -> float:
    """Similitud 0–1 entre dos nombres de emisor ya limpios.

    Máximo entre la secuencia completa y la secuencia con tokens ordenados,
    para tolerar reordenaciones del OCR.
    """
    plano_a = _plano(limpiar_nombre(a))
    plano_b = _plano(limpiar_nombre(b))
    if not plano_a or not plano_b:
        return 0.0
    directo = SequenceMatcher(None, plano_a, plano_b).ratio()
    ordenado_a = " ".join(sorted(plano_a.split()))
    ordenado_b = " ".join(sorted(plano_b.split()))
    por_tokens = SequenceMatcher(None, ordenado_a, ordenado_b).ratio()
    return max(directo, por_tokens)


def nombre_canonico(variantes: list[str]) -> str | None:
    """Elige el nombre de presentación del grupo de variantes de un NIF.

    Gana la versión limpia más frecuente; a igualdad, la que mejor pinta
    tiene como nombre (con minúsculas, no TODO mayúsculas del OCR) y la más
    corta (sin direcciones ni NIF pegado).
    """
    vivas = [v.strip() for v in variantes if v and v.strip()]
    if not vivas:
        return None
    grupos: dict[str, list[str]] = {}
    for original in vivas:
        grupos.setdefault(_plano(limpiar_nombre(original)), []).append(original)
    mejor_grupo = max(grupos.values(), key=lambda grupo: len(grupo))
    return max(
        mejor_grupo,
        key=lambda v: (sum(1 for ch in v if ch.islower()), -len(v)),
    )


# ---------------------------------------------------------------------------
# Modelo de puntuación Fellegi-Sunter (como Splink) para identidad de emisor.
#
# Peso de cada nivel de comparación = log2(m/u): m = P(nivel | misma empresa),
# u = P(nivel | empresas distintas). Se suman al intercepto (prior en
# log-odds) y la probabilidad sale con P = 1 / (1 + 2^-peso).
# En facturación española el NIF identifica a la empresa: su acuerdo domina.
# Los pesos son priors calibrados a mano y jugables desde aquí.
INTERCEPTO_BITS = -8.0  # prior: 1 de cada ~256 pares al azar es la misma empresa
NIF_IGUAL_BITS = 18.0   # m=0.99, u≈4e-6
NIF_DISTINTO_BITS = -18.0  # m≈1e-6, u=0.99
NIF_AUSENTE_BITS = 0.0  # sin información
NOMBRE_TRAMOS_BITS: list[tuple[float, float]] = [
    (0.95, 10.0),  # m=0.90, u≈1e-3
    (0.85, 8.0),  # m=0.60, u≈2e-3
    (0.70, 5.0),  # m=0.25, u≈8e-3
    (0.00, -8.0),  # desacuerdo fuerte: evidencia en contra
]


@dataclass
class ScoreEmisor:
    probabilidad: float
    peso_bits: float
    similitud: float
    desglose: list[tuple[str, float]] = field(default_factory=list)

    @property
    def banda(self) -> str:
        if self.probabilidad >= 0.90:
            return "auto"
        if self.probabilidad >= 0.50:
            return "revisar"
        return "rechazar"


def probabilidad_mismo_emisor(
    nif_a: str | None,
    nif_b: str | None,
    nombre_a: str | None,
    nombre_b: str | None,
) -> ScoreEmisor:
    """P(misma empresa) al estilo Splink, con desglose de pesos para elegir."""
    peso = INTERCEPTO_BITS
    desglose = [("base (prior)", INTERCEPTO_BITS)]
    if nif_a and nif_b:
        if nif_a == nif_b:
            peso += NIF_IGUAL_BITS
            desglose.append(("NIF igual", NIF_IGUAL_BITS))
        else:
            peso += NIF_DISTINTO_BITS
            desglose.append(("NIF distinto", NIF_DISTINTO_BITS))
    else:
        peso += NIF_AUSENTE_BITS
        desglose.append(("NIF ausente", NIF_AUSENTE_BITS))
    sim = similitud_nombre(nombre_a, nombre_b)
    for techo, bits in NOMBRE_TRAMOS_BITS:
        if sim >= techo:
            peso += bits
            desglose.append((f"nombre sim {sim:.2f}", bits))
            break
    probabilidad = 1.0 / (1.0 + 2.0 ** -peso)
    return ScoreEmisor(
        probabilidad=probabilidad, peso_bits=peso, similitud=sim, desglose=desglose
    )
