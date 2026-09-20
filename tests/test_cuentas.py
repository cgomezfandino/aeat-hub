import pytest
from sqlalchemy import select

from aeat_hub.fiscal.accounts import REGIMEN_AE, REGIMEN_CI, slug_cuenta
from aeat_hub.models import Cuenta
from aeat_hub.services import alta_cuenta, get_cuenta_por_nombre


def test_slug_cuenta_quita_acentos():
    assert slug_cuenta("Reparación") == "REPARACION"
    assert slug_cuenta("Pintura") == "PINTURA"


def test_alta_pintura_reparacion(session):
    cuenta = alta_cuenta(session, nombre="Pintura", casilla="reparacion")
    session.commit()
    assert cuenta.nombre == "Pintura"
    assert cuenta.casilla == "reparacion"
    assert cuenta.tipo == "gasto"
    assert cuenta.sistema is False
    assert cuenta.regimen == REGIMEN_CI
    assert get_cuenta_por_nombre(session, "pintura", regimen=REGIMEN_CI).codigo == cuenta.codigo


def test_alta_rechaza_casilla_inventada(session):
    with pytest.raises(RuntimeError, match="Casilla"):
        alta_cuenta(session, nombre="X", casilla="inventada")


def test_alta_rechaza_nombre_duplicado(session):
    with pytest.raises(RuntimeError, match="Ya existe"):
        alta_cuenta(session, nombre="Hogar", casilla="otros")


def test_alta_rechaza_actividad_economica(session):
    with pytest.raises(RuntimeError, match="capital inmobiliario"):
        alta_cuenta(session, nombre="Compras extra", casilla="otros", regimen=REGIMEN_AE)
