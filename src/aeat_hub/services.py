"""Servicios de inicialización y consulta de actividades."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.db import create_schema, make_engine, session_factory
from aeat_hub.fiscal.accounts import REGIMEN_AE, REGIMEN_CI, codigo_interno
from aeat_hub.fiscal.irpf import INDEX_CI, tipo_desde_casilla
from aeat_hub.models import Actividad, Cuenta, Titular
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
