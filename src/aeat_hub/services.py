"""Servicios de inicialización y consulta de actividades."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.db import create_schema, make_engine, session_factory
from aeat_hub.fiscal.accounts import REGIMEN_AE, REGIMEN_CI, codigo_interno
from aeat_hub.fiscal.irpf import INDEX_CI, tipo_desde_casilla
from aeat_hub.models import Actividad, Asiento, Cuenta, Inmueble, Titular
from aeat_hub.paths import DataLayout
from aeat_hub.seed import seed_cuentas, seed_valladolid


def initialize(
    layout: DataLayout,
    *,
    titular_nombre: str = "Titular local",
    titular_nif: str = "00000000T",
) -> None:
    layout.ensure()
    engine = make_engine(layout)
    create_schema(engine)
    factory = session_factory(engine)
    with factory() as session:
        seed_cuentas(session)
        seed_valladolid(session, titular_nombre=titular_nombre, titular_nif=titular_nif)
        session.commit()
    layout.write_config({"default_actividad": "CI-VA-001"})


def require_layout(layout: DataLayout) -> None:
    if not layout.is_initialized():
        raise RuntimeError(
            f"No hay libro en {layout.root}. Ejecuta: aeat-hub init --data-dir {layout.root}"
        )
    engine = make_engine(layout)
    create_schema(engine)
    factory = session_factory(engine)
    with factory() as session:
        seed_cuentas(session)
        session.commit()


def get_actividad(session: Session, codigo: str) -> Actividad:
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == codigo))
    if actividad is None:
        raise RuntimeError(f"No existe la actividad '{codigo}'.")
    return actividad


def alta_actividad(
    session: Session,
    *,
    nombre: str,
    regimen: str,
    codigo: str | None = None,
) -> Actividad:
    if regimen not in {REGIMEN_CI, REGIMEN_AE}:
        raise RuntimeError(f"Régimen no válido: {regimen}")
    titular = session.scalar(select(Titular).limit(1))
    if titular is None:
        raise RuntimeError("No hay titular. Ejecuta aeat-hub init.")
    if not codigo:
        prefix = "CI" if regimen == REGIMEN_CI else "AE"
        existing = session.scalars(select(Actividad.codigo)).all()
        n = 1 + sum(1 for item in existing if item.startswith(prefix))
        codigo = f"{prefix}-{n:03d}"
    if session.scalar(select(Actividad).where(Actividad.codigo == codigo)):
        raise RuntimeError(f"Ya existe la actividad {codigo}")
    actividad = Actividad(
        codigo=codigo,
        titular_id=titular.id,
        nombre=nombre,
        regimen=regimen,
    )
    session.add(actividad)
    session.flush()
    return actividad


def get_cuenta(session: Session, codigo: str) -> Cuenta:
    cuenta = session.get(Cuenta, codigo)
    if cuenta is None:
        raise RuntimeError(f"Cuenta desconocida: {codigo}")
    return cuenta


def get_cuenta_por_nombre(session: Session, nombre: str, *, regimen: str) -> Cuenta:
    needle = nombre.strip().casefold()
    matches = [
        row
        for row in session.scalars(select(Cuenta).where(Cuenta.regimen == regimen))
        if row.nombre.casefold() == needle
    ]
    if not matches:
        raise RuntimeError(f"Rubro desconocido: {nombre}")
    if len(matches) > 1:
        raise RuntimeError(f"Hay varios rubros llamados {nombre}")
    return matches[0]


def alta_cuenta(
    session: Session,
    *,
    nombre: str,
    casilla: str,
    regimen: str = REGIMEN_CI,
) -> Cuenta:
    if regimen != REGIMEN_CI:
        raise RuntimeError("En esta versión solo se dan de alta rubros de capital inmobiliario.")
    if casilla not in INDEX_CI or casilla == "sin_clasificar":
        raise RuntimeError(f"Casilla desconocida: {casilla}")
    nombre = nombre.strip()
    if not nombre:
        raise RuntimeError("El nombre del rubro no puede estar vacío.")
    existentes = list(session.scalars(select(Cuenta).where(Cuenta.regimen == regimen)))
    if any(row.nombre.casefold() == nombre.casefold() for row in existentes):
        raise RuntimeError(f"Ya existe el rubro {nombre}")
    tipo = tipo_desde_casilla(casilla)
    ocupados = {row.codigo for row in session.scalars(select(Cuenta))}
    cuenta = Cuenta(
        codigo=codigo_interno(nombre, tipo, regimen, ocupados),
        nombre=nombre,
        tipo=tipo,
        regimen=regimen,
        casilla=casilla,
        sistema=False,
    )
    session.add(cuenta)
    session.flush()
    return cuenta


def _titulo_limpio(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:200]


def patch_expediente(session: Session, codigo: str, payload: dict) -> dict:
    """Cambia los títulos visibles: expediente, titular e inmueble."""
    actividad = get_actividad(session, codigo)
    titular = session.get(Titular, actividad.titular_id)
    inmueble = session.scalar(
        select(Inmueble).where(Inmueble.actividad_id == actividad.id).order_by(Inmueble.id)
    )
    nombre = _titulo_limpio(payload.get("nombre"))
    titular_nombre = _titulo_limpio(payload.get("titular"))
    inmueble_alias = _titulo_limpio(payload.get("inmueble"))
    changed = False
    if nombre:
        actividad.nombre = nombre
        changed = True
    if titular is not None and titular_nombre:
        titular.nombre = titular_nombre
        changed = True
    if inmueble_alias:
        if inmueble is not None:
            inmueble.alias = inmueble_alias
            changed = True
        elif actividad.regimen == REGIMEN_CI:
            inmueble = Inmueble(
                actividad_id=actividad.id,
                alias=inmueble_alias,
                porcentaje_titularidad=Decimal("100.00"),
                uso="vivienda",
            )
            session.add(inmueble)
            changed = True
    if not changed:
        raise RuntimeError("Indica un título de expediente, titular o inmueble.")
    session.flush()
    return {
        "nombre": actividad.nombre,
        "codigo": actividad.codigo,
        "titular": titular.nombre if titular else "",
        "inmueble": inmueble.alias if inmueble is not None else "",
        "regimen": actividad.regimen,
    }


def patch_perfil(session: Session, codigo: str, payload: dict) -> dict:
    """Perfil fiscal de la actividad y NIF del titular, validados.

    Cambiar el NIF del titular recalcula la dirección (emitida/recibida)
    de todos sus asientos: decide qué es ingreso propio y qué IVA se deduce.
    """
    from datetime import date as _date

    from aeat_hub.fiscal.money import parse_amount
    from aeat_hub.fiscal.nif import is_valid_nif, normalize_nif
    from aeat_hub.fiscal.perfil import REGIMENES_IRPF, REGIMENES_IVA, TERRITORIOS, perfil_de

    actividad = get_actividad(session, codigo)
    titular = session.get(Titular, actividad.titular_id)

    def _elegir(clave: str, permitidos: tuple[str, ...]) -> None:
        if clave not in payload or payload[clave] is None:
            return
        valor = str(payload[clave]).strip().lower()
        if valor not in permitidos:
            raise ValueError(f"{clave}: «{valor}» no es válido. Opciones: {', '.join(permitidos)}.")
        setattr(actividad, clave, valor)

    _elegir("regimen_irpf", REGIMENES_IRPF)
    _elegir("regimen_iva", REGIMENES_IVA)
    _elegir("territorio", TERRITORIOS)
    if payload.get("epigrafe_iae") is not None:
        epigrafe = str(payload["epigrafe_iae"]).strip()
        if not epigrafe.replace(".", "").isdigit():
            raise ValueError("El epígrafe IAE son dígitos (p. ej. 763 o 861.1).")
        actividad.epigrafe_iae = epigrafe
    if payload.get("fecha_alta") is not None:
        try:
            actividad.fecha_alta = _date.fromisoformat(str(payload["fecha_alta"]))
        except ValueError as err:
            raise ValueError("La fecha de alta va en formato AAAA-MM-DD.") from err
    if payload.get("afectacion_vivienda_pct") is not None:
        pct = parse_amount(str(payload["afectacion_vivienda_pct"]))
        if pct is None or not (Decimal("0") <= pct <= Decimal("100")):
            raise ValueError("La afectación de la vivienda es un porcentaje entre 0 y 100.")
        actividad.afectacion_vivienda_pct = pct
    if payload.get("rendimiento_anterior") is not None:
        importe = parse_amount(str(payload["rendimiento_anterior"]))
        if importe is None:
            raise ValueError("El rendimiento neto del año anterior no es un importe válido.")
        actividad.rendimiento_anterior = importe

    if payload.get("nif_titular") is not None and titular is not None:
        nif = normalize_nif(str(payload["nif_titular"]))
        if not is_valid_nif(nif):
            raise ValueError(f"El NIF {payload['nif_titular']} no es válido (revisa la letra de control).")
        titular.nif = nif
        session.flush()
        for row in session.scalars(
            select(Asiento).join(Actividad).where(Actividad.titular_id == titular.id)
        ):
            emisor = normalize_nif(row.nif_emisor) if row.nif_emisor else ""
            row.direccion = "emitida" if emisor == nif else "recibida"

    session.flush()
    perfil = perfil_de(actividad)
    avisos = list(perfil.avisos)
    from aeat_hub.fiscal.nif import is_placeholder_nif

    if titular is None or is_placeholder_nif(titular.nif):
        avisos.insert(
            0,
            "El NIF del titular es de ejemplo: indica el real con --nif-titular. Sin él no se puede "
            "comprobar que las facturas estén a tu nombre (art. 97 LIVA) ni separar emitidas de recibidas.",
        )
    return {
        "codigo": actividad.codigo,
        "nif_titular": titular.nif if titular else "",
        "regimen_irpf": perfil.regimen_irpf,
        "regimen_iva": perfil.regimen_iva,
        "territorio": perfil.territorio,
        "epigrafe_iae": perfil.epigrafe_iae,
        "fecha_alta": perfil.fecha_alta.isoformat() if perfil.fecha_alta else None,
        "afectacion_vivienda_pct": perfil.afectacion_vivienda_pct,
        "rendimiento_anterior": perfil.rendimiento_anterior,
        "por_defecto": list(perfil.por_defecto),
        "avisos": avisos,
    }


def patch_inmueble(session: Session, codigo: str, payload: dict) -> dict:
    """Datos del inmueble para amortización, límite del art. 23 y reducción."""
    import json
    from datetime import date as _date

    from aeat_hub.fiscal.money import parse_amount

    actividad = get_actividad(session, codigo)
    inmueble = session.scalar(
        select(Inmueble).where(Inmueble.actividad_id == actividad.id).order_by(Inmueble.id)
    )
    if inmueble is None:
        raise RuntimeError("El expediente no tiene inmueble; créalo con `aeat-hub actividad titulo --inmueble`.")

    def importe(clave: str) -> None:
        if payload.get(clave) is None:
            return
        valor = parse_amount(str(payload[clave]))
        if valor is None or valor < 0:
            raise ValueError(f"{clave}: importe no válido.")
        setattr(inmueble, clave, valor)

    for clave in ("valor_catastral", "valor_catastral_construccion", "coste_adquisicion", "mejoras_anteriores"):
        importe(clave)
    if (
        inmueble.valor_catastral is not None
        and inmueble.valor_catastral_construccion is not None
        and inmueble.valor_catastral_construccion > inmueble.valor_catastral
    ):
        raise ValueError("El valor catastral de la construcción no puede superar el valor catastral total.")
    if payload.get("fecha_adquisicion") is not None:
        try:
            inmueble.fecha_adquisicion = _date.fromisoformat(str(payload["fecha_adquisicion"]))
        except ValueError as err:
            raise ValueError("La fecha de adquisición va en formato AAAA-MM-DD.") from err
    if payload.get("dias_arrendado") is not None:
        dias = int(payload["dias_arrendado"])
        if not 0 <= dias <= 366:
            raise ValueError("Los días arrendados van de 0 a 366.")
        inmueble.dias_arrendado = dias
    if payload.get("reduccion_pct") is not None:
        pct = parse_amount(str(payload["reduccion_pct"]))
        if pct not in (Decimal("0"), Decimal("50"), Decimal("60"), Decimal("70"), Decimal("90")):
            raise ValueError("La reducción por alquiler de vivienda es 0, 50, 60, 70 o 90 (art. 23.2 LIRPF).")
        inmueble.reduccion_pct = pct
    if payload.get("excesos"):
        excesos = json.loads(inmueble.excesos_anteriores or "{}")
        for ano, valor in payload["excesos"].items():
            cantidad = parse_amount(str(valor))
            if not str(ano).isdigit() or cantidad is None:
                raise ValueError("Los excesos van como AÑO=IMPORTE (p. ej. 2024=1000).")
            excesos[str(ano)] = str(cantidad)
        inmueble.excesos_anteriores = json.dumps(excesos, sort_keys=True)
    session.flush()
    return {
        "alias": inmueble.alias,
        "valor_catastral": inmueble.valor_catastral,
        "valor_catastral_construccion": inmueble.valor_catastral_construccion,
        "coste_adquisicion": inmueble.coste_adquisicion,
        "mejoras_anteriores": inmueble.mejoras_anteriores,
        "fecha_adquisicion": inmueble.fecha_adquisicion.isoformat() if inmueble.fecha_adquisicion else None,
        "dias_arrendado": inmueble.dias_arrendado,
        "reduccion_pct": inmueble.reduccion_pct,
        "excesos_anteriores": inmueble.excesos_anteriores,
    }
