"""Clasificación por reglas de proveedor, palabras clave y aprendizaje del usuario."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.extract.schema import InvoiceExtract
from aeat_hub.fiscal.accounts import REGIMEN_AE, REGIMEN_CI, TIPO_MEJORA
from aeat_hub.fiscal.nif import normalize_nif
from aeat_hub.models import Actividad, Asiento, Cuenta, ReglaAprendida
from aeat_hub.paths import DataLayout

KEYWORD_ACCOUNTS: tuple[tuple[tuple[str, ...], str, float], ...] = (
    (("iberdrola", "endesa", "naturgy", "holaluz", "curenerg", "i-de redes"), "CI.GAS.LUZ", 0.9),
    (("aquavall", "aquona", "aqualia", "aguas de", "canal de isabel"), "CI.GAS.AGUA", 0.9),
    (
        ("movistar", "telefonica", "telefónica", "orange", "vodafone", "digi ", "masmovil", "másmóvil", "yoigo", "pepephone", "lowi"),
        "CI.GAS.INTERNET",
        0.88,
    ),
    (("comunidad de propietarios", "comunidad propietarios", "administrador de fincas"), "CI.GAS.COMUNIDAD", 0.92),
    (("mapfre", "allianz", "mutua madrileña", "línea directa", "linea directa", "zurich", "reale", "pelayo"), "CI.GAS.SEGURO", 0.85),
    ((" impuesto sobre bienes", " recibo ibi", "ibi ", "tasa de basura", "gerencia territorial"), "CI.GAS.IBI", 0.86),
    (("indemnizacion", "indemnización"), "CI.ING.INDEMN", 0.8),
    (("arrendamiento", "renta de alquiler", "recibo de alquiler"), "CI.ING.RENTA", 0.8),
    (("ventana", "ventanas", "climalit", "carpinteria", "carpintería"), "CI.MEJ.PVC", 0.72),
    (("tarima", "parquet", "solado", "suelo laminado", "porcelanico", "porcelánico"), "CI.MEJ.SOLADO", 0.72),
    (("revestimiento", "alicatado"), "CI.MEJ.REVEST", 0.7),
    (("leroy merlin", "bricomart", "bauhaus", "obramat", "bricoman"), "CI.GAS.HOGAR", 0.6),
)

BRICOLAJE = ("leroy merlin", "bricomart", "bauhaus", "obramat", "bricoman")
OBRA_CLARA = (
    "ventana",
    "ventanas",
    "climalit",
    "carpinteria",
    "carpintería",
    "tarima",
    "parquet",
    "solado",
    "suelo laminado",
    "revestimiento",
    "alicatado",
)

MEJORA_HINTS = ("mejora", "reforma", "instalaci", "obra")
REPARACION_HINTS = ("reparaci", "avería", "averia", "desatasco", "fontaner", "caldera")
MANO_OBRA = ("mano de obra", "albañil", "albanil")


@dataclass
class Classification:
    cuenta_codigo: str | None
    origen: str
    confianza: Decimal
    tipo: str


def classify(
    session: Session,
    actividad: Actividad,
    extract: InvoiceExtract,
    raw_text: str,
) -> Classification:
    blob = _blob(extract, raw_text)
    learned = _from_learned(session, actividad.id, extract, blob)
    if learned:
        return learned
    if actividad.regimen == REGIMEN_CI:
        keyword = _from_keywords(blob)
        if keyword:
            return keyword
        repair = _mejora_vs_reparacion(blob)
        if repair:
            return repair
    elif actividad.regimen == REGIMEN_AE:
        ae = _ae_default(blob)
        if ae:
            return ae
    return Classification(None, "pendiente", Decimal("0"), "gasto")


def reclassify(
    session: Session,
    asiento: Asiento,
    cuenta: Cuenta,
    *,
    aplicar_similares: bool = True,
    layout: DataLayout | None = None,
) -> int:
    _apply_cuenta(asiento, cuenta, origen="usuario", confianza=Decimal("1.000"))
    asiento.validado = True
    nif = normalize_nif(asiento.nif_emisor) if asiento.nif_emisor else ""
    patron = ""
    existing = session.scalar(
        select(ReglaAprendida).where(
            ReglaAprendida.actividad_id == asiento.actividad_id,
            ReglaAprendida.nif_emisor == nif,
            ReglaAprendida.patron_descripcion == patron,
        )
    )
    if existing:
        existing.cuenta_codigo = cuenta.codigo
        existing.fuente = "usuario"
    else:
        session.add(
            ReglaAprendida(
                actividad_id=asiento.actividad_id,
                nif_emisor=nif,
                patron_descripcion=patron,
                cuenta_codigo=cuenta.codigo,
                fuente="usuario",
            )
        )
    updated = 1
    touched = [asiento]
    if aplicar_similares and nif:
        similares = session.scalars(
            select(Asiento).where(
                Asiento.actividad_id == asiento.actividad_id,
                Asiento.nif_emisor == nif,
                Asiento.id != asiento.id,
                Asiento.estado == "pendiente",
            )
        ).all()
        for other in similares:
            _apply_cuenta(other, cuenta, origen="aprendida", confianza=Decimal("0.900"))
            touched.append(other)
            updated += 1
    if layout is not None:
        from aeat_hub.filing import relocate_asiento

        for row in touched:
            relocate_asiento(session, layout, row, move=True)
    return updated


def validar_asiento(asiento: Asiento) -> None:
    """Marca el asiento como revisado por el usuario. No cambia el rubro ni relanza OCR."""
    asiento.validado = True
    asiento.origen_clasificacion = "usuario"
    asiento.confianza_clasificacion = Decimal("1.000")
    if asiento.estado != "duplicado":
        asiento.estado = "confirmado"


def reabrir_asiento(asiento: Asiento) -> None:
    """Devuelve un asiento validado a revisión humana."""
    asiento.validado = False
    asiento.origen_clasificacion = "usuario"
    if asiento.estado != "duplicado":
        asiento.estado = "pendiente"


def _apply_cuenta(asiento: Asiento, cuenta: Cuenta, *, origen: str, confianza: Decimal) -> None:
    asiento.cuenta_codigo = cuenta.codigo
    asiento.tipo = cuenta.tipo
    asiento.origen_clasificacion = origen
    asiento.confianza_clasificacion = confianza
    if asiento.estado == "duplicado":
        return
    asiento.estado = "confirmado" if confianza >= Decimal("0.800") else "pendiente"


def _from_learned(
    session: Session,
    actividad_id: int,
    extract: InvoiceExtract,
    blob: str,
) -> Classification | None:
    nif = normalize_nif(extract.nif_emisor) if extract.nif_emisor else ""
    if nif:
        rule = session.scalar(
            select(ReglaAprendida).where(
                ReglaAprendida.actividad_id == actividad_id,
                ReglaAprendida.nif_emisor == nif,
            )
        )
        if rule:
            cuenta = session.get(Cuenta, rule.cuenta_codigo)
            if cuenta:
                return Classification(cuenta.codigo, "aprendida", Decimal("0.950"), cuenta.tipo)
    rules = session.scalars(
        select(ReglaAprendida).where(
            ReglaAprendida.actividad_id == actividad_id,
            ReglaAprendida.patron_descripcion != "",
        )
    ).all()
    for rule in rules:
        if rule.patron_descripcion and rule.patron_descripcion in blob:
            cuenta = session.get(Cuenta, rule.cuenta_codigo)
            if cuenta:
                return Classification(cuenta.codigo, "aprendida", Decimal("0.850"), cuenta.tipo)
    return None


def _from_keywords(blob: str) -> Classification | None:
    if any(token in blob for token in BRICOLAJE) and not any(token in blob for token in OBRA_CLARA):
        return Classification("CI.GAS.HOGAR", "regla", Decimal("0.72"), "gasto")
    for needles, codigo, conf in KEYWORD_ACCOUNTS:
        if any(needle in blob for needle in needles):
            tipo = TIPO_MEJORA if codigo.startswith("CI.MEJ") else (
                "ingreso" if codigo.startswith("CI.ING") else "gasto"
            )
            return Classification(codigo, "regla", Decimal(str(conf)), tipo)
    return None


def _mejora_vs_reparacion(blob: str) -> Classification | None:
    if any(token in blob for token in MANO_OBRA):
        if any(token in blob for token in ("pvc", "ventana", "tarima", "solado", "revest")):
            return Classification("CI.MEJ.MO", "regla", Decimal("0.700"), TIPO_MEJORA)
        return Classification(None, "pendiente", Decimal("0.200"), "gasto")
    if any(token in blob for token in REPARACION_HINTS) and not any(
        token in blob for token in MEJORA_HINTS
    ):
        return Classification("CI.GAS.REPARACION", "regla", Decimal("0.650"), "gasto")
    return None


def _ae_default(blob: str) -> Classification | None:
    if "seguridad social" in blob or "reta" in blob:
        return Classification("AE.GAS.SS", "regla", Decimal("0.8"), "gasto")
    return None


def _blob(extract: InvoiceExtract, raw_text: str) -> str:
    parts = [extract.emisor or "", extract.numero or "", raw_text or ""]
    return " ".join(parts).lower()
