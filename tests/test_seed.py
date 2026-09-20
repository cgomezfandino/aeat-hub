from sqlalchemy import select

from aeat_hub.models import Actividad, Cuenta, Inmueble, Titular


def test_seed_valladolid_y_cuentas(session):
    titular = session.scalar(select(Titular))
    assert titular is not None
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    assert actividad.regimen == "capital_inmobiliario"
    inmueble = session.scalar(select(Inmueble))
    assert inmueble.municipio == "Valladolid"
    codigos = {row.codigo for row in session.scalars(select(Cuenta))}
    assert "CI.GAS.LUZ" in codigos
    assert "CI.MEJ.PVC" in codigos
    assert "AE.ING.VENTAS" in codigos
