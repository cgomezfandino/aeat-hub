"""Semilla del plan de cuentas y del expediente de alquiler en Valladolid."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.fiscal.accounts import ACCOUNT_DEFS, CODIGO_DEMO_CI, REGIMEN_CI
from aeat_hub.models import Actividad, Cuenta, Inmueble, Titular


def seed_cuentas(session: Session) -> None:
    for item in ACCOUNT_DEFS:
        row = session.get(Cuenta, item.codigo)
        if row is None:
            session.add(
                Cuenta(
                    codigo=item.codigo,
                    nombre=item.nombre,
                    tipo=item.tipo,
                    regimen=item.regimen,
                    notas=item.notas,
                    casilla=item.casilla,
                    sistema=True,
                )
            )
        elif row.sistema:
            row.nombre = item.nombre
            row.notas = item.notas
            row.tipo = item.tipo
            row.casilla = item.casilla
            row.regimen = item.regimen
    session.flush()


def seed_valladolid(
    session: Session,
    *,
    titular_nombre: str = "Titular local",
    titular_nif: str = "00000000T",
) -> Actividad:
    titular = session.scalar(select(Titular).where(Titular.nif == titular_nif))
    if titular is None:
        titular = session.scalar(select(Titular).limit(1))
    if titular is None:
        titular = Titular(nif=titular_nif, nombre=titular_nombre, tipo="fisica")
        session.add(titular)
        session.flush()

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == CODIGO_DEMO_CI))
    if actividad is None:
        actividad = Actividad(
            codigo=CODIGO_DEMO_CI,
            titular_id=titular.id,
            nombre="Alquiler Valladolid",
            regimen=REGIMEN_CI,
        )
        session.add(actividad)
        session.flush()

    inmueble = session.scalar(select(Inmueble).where(Inmueble.actividad_id == actividad.id))
    if inmueble is None:
        session.add(
            Inmueble(
                actividad_id=actividad.id,
                alias="Vivienda Valladolid",
                municipio="Valladolid",
                provincia="Valladolid",
                porcentaje_titularidad=Decimal("100.00"),
                uso="vivienda",
            )
        )
        session.flush()
    return actividad
