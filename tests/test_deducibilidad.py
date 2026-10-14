"""Motor de deducibilidad: IVA deducible y gasto IRPF, regla a regla.

Importes calculados a mano: base 100, IVA 21, total 121 salvo que se diga.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal as D

import pytest

from aeat_hub.fiscal.deducibilidad import evaluar
from aeat_hub.fiscal.normativa import para
from aeat_hub.fiscal.perfil import (
    IRPF_CAPITAL_INMOBILIARIO,
    IRPF_ED_SIMPLIFICADA,
    IRPF_EO,
    IVA_EXENTO,
    IVA_GENERAL,
    IVA_RECARGO,
    perfil_de,
)

TITULAR = "12345678Z"
N = para(2026)


@dataclass
class _Act:
    regimen: str = "actividad_economica"
    regimen_irpf: str | None = IRPF_ED_SIMPLIFICADA
    regimen_iva: str | None = IVA_GENERAL
    epigrafe_iae: str | None = "763"
    territorio: str = "comun"
    fecha_alta: date | None = None
    afectacion_vivienda_pct: D | None = None
    rendimiento_anterior: D | None = None
    inmuebles: list = field(default_factory=list)


def _gasto(**kw):
    data = {
        "tipo": "gasto",
        "cuenta_codigo": "AE.GAS.SERVICIOS",
        "base": D("100.00"),
        "iva_cuota": D("21.00"),
        "total": D("121.00"),
        "tipo_factura": "completa",
        "nif_receptor": TITULAR,
        "moneda": "EUR",
    }
    data.update(kw)
    return data


def _eval(asiento, **perfil):
    return evaluar(asiento, perfil_de(_Act(**perfil)), N, titular_nif=TITULAR)


def test_factura_completa_general_deduce_todo():
    r = _eval(_gasto())
    assert (r.iva_deducible, r.importe_irpf) == (D("21.00"), D("100.00"))


def test_ticket_sin_nif_iva_no_deducible_y_mayor_gasto():
    r = _eval(_gasto(tipo_factura="simplificada", nif_receptor=None))
    assert (r.iva_deducible, r.importe_irpf) == (D("0.00"), D("121.00"))
    assert any("art. 7.2 RD 1619/2012" in regla.cita for regla in r.reglas)


def test_factura_a_nombre_de_otro_no_deduce_iva():
    r = _eval(_gasto(nif_receptor="B12345674"))
    assert r.iva_deducible == D("0.00")


def test_vehiculo_iva_50_y_sin_gasto_irpf():
    r = _eval(_gasto(cuenta_codigo="AE.GAS.VEHICULO"))
    assert (r.iva_deducible, r.importe_irpf) == (D("10.50"), D("0.00"))


def test_vehiculo_con_afectacion_exclusiva_declarada():
    r = _eval(_gasto(cuenta_codigo="AE.GAS.VEHICULO", afectacion_pct=D("100")))
    assert (r.iva_deducible, r.importe_irpf) == (D("21.00"), D("100.00"))


def test_suministros_vivienda_30_por_ciento_de_la_afectacion():
    # 20 % de la vivienda afecto: IRPF 30 % × 20 % = 6 % de la base; IVA 20 %
    r = _eval(_gasto(cuenta_codigo="AE.GAS.SUMVIVIENDA"), afectacion_vivienda_pct=D("20"))
    assert r.iva_deducible == D("4.20")
    assert r.importe_irpf == D("6.00")


def test_suministros_vivienda_sin_porcentaje_no_computa():
    r = _eval(_gasto(cuenta_codigo="AE.GAS.SUMVIVIENDA"))
    assert r.importe_irpf == D("0.00")
    assert any("% de la vivienda" in aviso for aviso in r.avisos)


def test_manutencion_por_encima_del_limite_diario():
    r = _eval(_gasto(cuenta_codigo="AE.GAS.MANUTENCION", base=D("50.00"), iva_cuota=D("5.00"), total=D("55.00")))
    # límite 26,67 € sobre bruto 55 → 48,49 %
    assert r.pct_gasto == D("48.49")
    assert r.importe_irpf < D("27.00")


def test_regimen_exento_iva_es_mayor_gasto():
    r = _eval(_gasto(), regimen_iva=IVA_EXENTO)
    assert (r.iva_deducible, r.importe_irpf) == (D("0.00"), D("121.00"))


def test_recargo_de_equivalencia_todo_es_gasto():
    r = _eval(_gasto(recargo_cuota=D("5.20"), total=D("126.20")), regimen_iva=IVA_RECARGO)
    assert (r.iva_deducible, r.importe_irpf) == (D("0.00"), D("126.20"))


def test_capital_inmobiliario_vivienda_gasto_con_iva():
    r = _eval(_gasto(cuenta_codigo="CI.GAS.REPARACION"), regimen="capital_inmobiliario",
              regimen_irpf=None, regimen_iva=None)
    assert (r.iva_deducible, r.importe_irpf) == (D("0.00"), D("121.00"))


def test_bien_de_inversion_deduce_iva_pero_no_es_gasto_del_ano():
    r = _eval(_gasto(tipo="mejora", cuenta_codigo="AE.INV.BIENES", base=D("4000.00"),
                     iva_cuota=D("840.00"), total=D("4840.00")))
    assert (r.iva_deducible, r.importe_irpf) == (D("840.00"), D("0.00"))


def test_no_factura_bloquea_aunque_se_fuerce_la_afectacion():
    r = _eval(_gasto(tipo_factura="no_factura", afectacion_pct=D("100")))
    assert (r.iva_deducible, r.importe_irpf) == (D("0.00"), D("0.00"))


def test_modulos_bloquea_el_gasto_irpf():
    r = _eval(_gasto(afectacion_pct=D("100")), regimen_irpf=IRPF_EO)
    assert r.importe_irpf == D("0.00")


def test_abono_de_ticket_resta_el_bruto():
    r = _eval(_gasto(tipo_factura="simplificada", nif_receptor=None, base=D("-100.00"),
                     iva_cuota=D("-21.00"), total=D("-121.00")))
    assert r.importe_irpf == D("-121.00")


def test_sin_clasificar_no_computa():
    r = _eval(_gasto(cuenta_codigo=None))
    assert (r.iva_deducible, r.importe_irpf) == (D("0.00"), D("0.00"))


def test_moneda_extranjera_no_computa():
    r = _eval(_gasto(moneda="USD"))
    assert r.importe_irpf == D("0.00")


def test_titular_sin_nif_real_avisa():
    perfil = perfil_de(_Act())
    r = evaluar(_gasto(), perfil, N, titular_nif="00000000T")
    assert r.iva_deducible == D("21.00")
    assert any("NIF real del titular" in aviso for aviso in r.avisos)


@pytest.mark.parametrize(
    "regimen_iva, esperado", [(IVA_GENERAL, D("100.00")), (IVA_EXENTO, D("121.00"))]
)
def test_ingreso_computa_base_o_bruto_segun_iva(regimen_iva, esperado):
    r = _eval(_gasto(tipo="ingreso", cuenta_codigo="AE.ING.VENTAS"), regimen_iva=regimen_iva)
    assert r.es_ingreso and r.importe_irpf == esperado


def test_perfil_incompleto_se_declara():
    perfil = perfil_de(_Act(regimen_irpf=None, regimen_iva=None, epigrafe_iae=None))
    assert set(perfil.por_defecto) == {"regimen_irpf", "regimen_iva", "epigrafe_iae"}


def test_capital_inmobiliario_de_local_lleva_iva():
    @dataclass
    class _Inm:
        uso: str

    perfil = perfil_de(_Act(regimen="capital_inmobiliario", regimen_irpf=None, regimen_iva=None,
                            inmuebles=[_Inm("local")]))
    assert perfil.regimen_irpf == IRPF_CAPITAL_INMOBILIARIO
    assert perfil.regimen_iva == IVA_GENERAL


def test_normativa_de_ejercicio_sin_verificar_avisa():
    assert para(2026).verificado
    futura = para(2030)
    assert not futura.verificado and "2030" in futura.avisos[-1]


# --- Perfil desde la CLI / servicio ------------------------------------------


def test_patch_perfil_valida_y_recalcula_direccion(session):
    from sqlalchemy import select

    from aeat_hub.models import Actividad, Asiento
    from aeat_hub.services import patch_perfil

    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    emitida = Asiento(actividad_id=actividad.id, tipo="ingreso", nif_emisor="12345678Z", total=D("700"))
    recibida = Asiento(actividad_id=actividad.id, tipo="gasto", nif_emisor="B12345674", total=D("50"))
    session.add_all([emitida, recibida])
    session.flush()

    data = patch_perfil(session, "CI-VA-001", {"nif_titular": "12345678-z", "afectacion_vivienda_pct": "25"})
    assert data["nif_titular"] == "12345678Z"
    assert data["regimen_irpf"] == "capital_inmobiliario"
    assert (emitida.direccion, recibida.direccion) == ("emitida", "recibida")

    with pytest.raises(ValueError, match="letra de control"):
        patch_perfil(session, "CI-VA-001", {"nif_titular": "12345678A"})
    with pytest.raises(ValueError, match="Opciones"):
        patch_perfil(session, "CI-VA-001", {"regimen_iva": "inventado"})
    with pytest.raises(ValueError, match="entre 0 y 100"):
        patch_perfil(session, "CI-VA-001", {"afectacion_vivienda_pct": "150"})
