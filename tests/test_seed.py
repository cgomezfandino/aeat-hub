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


def test_seed_nombres_cortos_y_casilla(session):
    hogar = session.get(Cuenta, "CI.GAS.HOGAR")
    assert hogar.nombre == "Hogar"
    assert hogar.casilla == "otros"
    assert hogar.sistema is True
    luz = session.get(Cuenta, "CI.GAS.LUZ")
    assert luz.nombre == "Luz"
    assert luz.casilla == "suministros"


def test_seed_no_pisa_cuenta_de_usuario(session):
    hogar = session.get(Cuenta, "CI.GAS.HOGAR")
    hogar.sistema = False
    hogar.nombre = "Bricolaje"
    session.commit()
    from aeat_hub.seed import seed_cuentas

    seed_cuentas(session)
    session.commit()
    assert session.get(Cuenta, "CI.GAS.HOGAR").nombre == "Bricolaje"


def test_seed_actualiza_nombre_largo_de_sistema(session):
    hogar = session.get(Cuenta, "CI.GAS.HOGAR")
    hogar.nombre = "Consumibles y pequeño mantenimiento del hogar"
    session.commit()
    from aeat_hub.seed import seed_cuentas

    seed_cuentas(session)
    session.commit()
    assert session.get(Cuenta, "CI.GAS.HOGAR").nombre == "Hogar"
