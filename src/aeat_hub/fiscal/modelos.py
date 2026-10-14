"""Borradores de los modelos 303 (IVA) y 130 (pago fraccionado IRPF).

Son borradores para revisar, no presentaciones: cada casilla lleva los
asientos de los que sale (trazabilidad) y el borrador declara sus límites
en `avisos`. Los números de casilla salen de `fiscal/normativa`, nunca de
aquí. Solo cuenta lo computable (validado, sin duplicados ni rechazados).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from aeat_hub.fiscal.accounts import TIPO_AMORT, TIPO_INGRESO, TIPO_MEJORA
from aeat_hub.fiscal.computo import computables, por_revisar
from aeat_hub.fiscal.deducibilidad import evaluar
from aeat_hub.fiscal.libros import desglose_de
from aeat_hub.fiscal.money import q2
from aeat_hub.fiscal.nif import is_nif_iva_ue, normalize_nif
from aeat_hub.fiscal.normativa import Normativa, para
from aeat_hub.fiscal.perfil import IRPF_ED_SIMPLIFICADA, IVA_CRITERIO_CAJA, IVA_SIMPLIFICADO, perfil_de

CERO = Decimal("0.00")
CIEN = Decimal("100")


@dataclass
class Casilla:
    numero: str
    concepto: str
    importe: Decimal = CERO
    asientos: list[int] = field(default_factory=list)

    def sumar(self, importe: Decimal | None, asiento_id: int | None = None) -> None:
        if importe is None:
            return
        self.importe = q2(self.importe + importe)
        if asiento_id is not None and asiento_id not in self.asientos:
            self.asientos.append(asiento_id)


@dataclass
class Borrador:
    modelo: str
    ejercicio: int
    periodo: str
    aplica: bool
    casillas: dict[str, Casilla]
    resultado: Decimal
    verificado: bool
    avisos: list[str] = field(default_factory=list)
    n_por_revisar: int = 0
    total_por_revisar: Decimal = CERO

    def importe(self, numero: str) -> Decimal:
        casilla = self.casillas.get(numero)
        return casilla.importe if casilla else CERO


def _trimestre(fecha: date | None) -> int | None:
    return (fecha.month - 1) // 3 + 1 if fecha else None


def _fecha_devengo(asiento) -> date | None:
    return asiento.fecha_operacion or asiento.fecha


def _extranjero_ue(nif: str | None) -> bool:
    return bool(nif) and is_nif_iva_ue(nif)


def _comunes(asientos, actividad, ejercicio: int):
    perfil = perfil_de(actividad)
    normativa = para(ejercicio)
    del_ano = [a for a in asientos if a.ejercicio == ejercicio]
    avisos = list(normativa.avisos) + list(perfil.avisos)
    if perfil.por_defecto:
        avisos.append(
            "Perfil fiscal incompleto (" + ", ".join(perfil.por_defecto) + "): el borrador usa valores por defecto."
        )
    pendientes = por_revisar(del_ano)
    if pendientes:
        avisos.append(
            f"{len(pendientes)} facturas del ejercicio siguen por revisar y no están en este borrador."
        )
    return perfil, normativa, computables(del_ano), avisos, pendientes


# --- Modelo 303 --------------------------------------------------------------


def borrador_303(
    asientos, actividad, ejercicio: int, trimestre: int, *, titular_nif: str | None
) -> Borrador:
    perfil, normativa, libro, avisos, pendientes = _comunes(asientos, actividad, ejercicio)
    c = normativa.casillas_303
    casillas: dict[str, Casilla] = {}

    def cas(numero: str, concepto: str) -> Casilla:
        if numero not in casillas:
            casillas[numero] = Casilla(numero, concepto)
        return casillas[numero]

    pendientes_periodo = [a for a in pendientes if _trimestre(_fecha_devengo(a)) == trimestre]
    if not perfil.presenta_303:
        return Borrador(
            "303", ejercicio, f"{trimestre}T", False, {}, CERO, normativa.verificado,
            avisos + [f"Régimen de IVA «{perfil.regimen_iva}»: no presenta el modelo 303."],
        )
    if perfil.regimen_iva == IVA_SIMPLIFICADO:
        avisos.append("Régimen simplificado de IVA (módulos): las cuotas devengadas por módulos no se calculan aquí.")
    if perfil.regimen_iva == IVA_CRITERIO_CAJA:
        avisos.append(
            "Criterio de caja: el IVA se devenga al cobrar y se deduce al pagar; sin fechas de cobro/pago "
            "este borrador usa la fecha de la factura."
        )

    periodo = [a for a in libro if _trimestre(_fecha_devengo(a)) == trimestre]
    tipo_general = max(normativa.tipos_iva)

    for asiento in periodo:
        ded = evaluar(asiento, perfil, normativa, titular_nif=titular_nif)
        avisos.extend(f"#{asiento.id}: {aviso}" for aviso in ded.avisos)

        if asiento.tipo == TIPO_INGRESO:
            # IVA devengado (repercutido)
            if _extranjero_ue(asiento.nif_receptor):
                cas(c.entregas_intracomunitarias, "Entregas intracomunitarias exentas").sumar(asiento.base, asiento.id)
                continue
            if asiento.mencion_legal == "inversion_sujeto_pasivo":
                cas(c.isp_emitidas, "Operaciones con inversión del sujeto pasivo").sumar(asiento.base, asiento.id)
                continue
            if asiento.mencion_legal in ("exenta_art20", "no_sujeta"):
                continue
            rectificativa = asiento.tipo_factura == "rectificativa"
            for fila in desglose_de(asiento):
                if rectificativa:
                    base_n, cuota_n = c.modificacion
                    cas(base_n, "Modificación de bases").sumar(fila.base, asiento.id)
                    cas(cuota_n, "Modificación de cuotas").sumar(fila.cuota, asiento.id)
                    continue
                tipo = _tipo(fila.tipo)
                numeros = c.devengado.get(Decimal(tipo))
                if numeros is None:
                    avisos.append(f"#{asiento.id}: tipo de IVA {fila.tipo} % sin casilla en {ejercicio}; no se incluye.")
                    continue
                base_n, tipo_n, cuota_n = numeros
                cas(base_n, f"Base imponible al {tipo} %").sumar(fila.base, asiento.id)
                casillas.setdefault(tipo_n, Casilla(tipo_n, "Tipo", Decimal(tipo)))
                cas(cuota_n, f"Cuota al {tipo} %").sumar(fila.cuota, asiento.id)
                if fila.recargo_cuota:
                    re_tipo = _tipo(fila.recargo_tipo)
                    re_numeros = c.recargo.get(Decimal(re_tipo))
                    if re_numeros is None:
                        avisos.append(f"#{asiento.id}: recargo {re_tipo} % sin casilla verificada.")
                    else:
                        cas(re_numeros[0], f"Base recargo {re_tipo} %").sumar(fila.base, asiento.id)
                        cas(re_numeros[2], f"Cuota recargo {re_tipo} %").sumar(fila.recargo_cuota, asiento.id)
            continue

        # Recibidas: autoliquidación (adquisiciones intracomunitarias / ISP)
        intracom = _extranjero_ue(asiento.nif_emisor)
        isp = asiento.mencion_legal == "inversion_sujeto_pasivo"
        inversion = asiento.tipo in (TIPO_MEJORA, TIPO_AMORT) and (asiento.base or CERO) > normativa.umbral_bien_inversion
        if (intracom or isp) and asiento.base is not None and not asiento.iva_cuota:
            cuota = q2(asiento.base * tipo_general / CIEN)
            avisos.append(
                f"#{asiento.id}: autoliquidación al {tipo_general} % (tipo general); comprueba el tipo aplicable."
            )
            dev = c.adq_intracomunitarias if intracom else c.isp_otras
            cas(dev[0], "Adquisiciones intracomunitarias" if intracom else "Inversión del sujeto pasivo").sumar(
                asiento.base, asiento.id
            )
            cas(dev[1], "Cuota autoliquidada").sumar(cuota, asiento.id)
            if ded.pct_iva > 0 or perfil.deduce_iva:
                if intracom:
                    ded_n = c.deducible_intracom_inversion if inversion else c.deducible_intracom_corrientes
                else:
                    ded_n = c.deducible_inversion if inversion else c.deducible_corrientes
                cas(ded_n[0], "Base deducible").sumar(asiento.base, asiento.id)
                cas(ded_n[1], "Cuota deducible").sumar(cuota, asiento.id)
            continue

        if ded.iva_deducible == 0:
            continue
        base_deducible = q2((asiento.base or CERO) * ded.pct_iva / CIEN)
        if asiento.tipo_factura == "rectificativa":
            numeros = c.rectificacion_deducciones
            concepto = "Rectificación de deducciones"
        elif inversion:
            numeros = c.deducible_inversion
            concepto = "Bienes de inversión"
        else:
            numeros = c.deducible_corrientes
            concepto = "Operaciones interiores corrientes"
        cas(numeros[0], f"Base · {concepto}").sumar(base_deducible, asiento.id)
        cas(numeros[1], f"Cuota deducible · {concepto}").sumar(ded.iva_deducible, asiento.id)

    # Totales
    no_cuota = {num for nums in c.devengado.values() for num in nums[:2]}
    no_cuota |= {num for nums in c.recargo.values() for num in nums[:2]}
    no_cuota |= {c.adq_intracomunitarias[0], c.isp_otras[0], c.modificacion[0]}
    informativas = {c.entregas_intracomunitarias, c.exportaciones, c.no_sujetas_localizacion, c.isp_emitidas}
    deducibles = {
        c.deducible_corrientes, c.deducible_inversion, c.deducible_intracom_corrientes,
        c.deducible_intracom_inversion, c.rectificacion_deducciones,
    }
    num_deducibles = {n for pareja in deducibles for n in pareja}
    devengado = sum(
        (cas_.importe for num, cas_ in casillas.items()
         if num not in no_cuota and num not in informativas and num not in num_deducibles),
        CERO,
    )
    deducir = sum((casillas[p[1]].importe for p in deducibles if p[1] in casillas), CERO)
    total_dev = cas(c.total_devengado, "Total cuota devengada")
    total_dev.importe = q2(devengado)
    total_ded = cas(c.total_deducir, "Total a deducir")
    total_ded.importe = q2(deducir)
    resultado = cas(c.resultado_general, "Resultado régimen general")
    resultado.importe = q2(devengado - deducir)
    avisos.append(
        "Resultado antes de compensar cuotas de periodos anteriores (casilla 78) y de "
        "la regularización anual; réstalas si las tienes."
    )
    if resultado.importe < 0 and trimestre < 4:
        avisos.append("Resultado negativo: en 1T-3T solo se puede compensar en periodos siguientes.")
    return Borrador(
        "303", ejercicio, f"{trimestre}T", True, dict(sorted(casillas.items(), key=lambda kv: _orden(kv[0]))),
        resultado.importe, normativa.verificado, _unicos(avisos),
        len(pendientes_periodo), sum((a.total or CERO for a in pendientes_periodo), CERO),
    )


# --- Modelo 130 --------------------------------------------------------------


def _acumulado_130(perfil, normativa: Normativa, libro, trimestre: int, titular_nif):
    """Casillas 01-04 y 06 acumuladas desde el 1 de enero hasta el fin del trimestre."""
    c01, c02, c06 = Casilla("01", "Ingresos computables"), Casilla("02", "Gastos fiscalmente deducibles"), Casilla(
        "06", "Retenciones e ingresos a cuenta"
    )
    avisos: list[str] = []
    for asiento in libro:
        t = _trimestre(asiento.fecha)
        if t is None or t > trimestre:
            continue
        ded = evaluar(asiento, perfil, normativa, titular_nif=titular_nif)
        if asiento.tipo == TIPO_INGRESO:
            c01.sumar(ded.importe_irpf, asiento.id)
            c06.sumar(asiento.retencion_cuota, asiento.id)
        else:
            c02.sumar(ded.importe_irpf, asiento.id)
            avisos.extend(f"#{asiento.id}: {aviso}" for aviso in ded.avisos)
    if perfil.regimen_irpf == IRPF_ED_SIMPLIFICADA:
        previo = c01.importe - c02.importe
        if previo > 0:
            dificil = min(
                q2(previo * normativa.dificil_justificacion_pct / CIEN), normativa.dificil_justificacion_limite
            )
            c02.sumar(dificil)
            avisos.append(
                f"Incluye {dificil} € de provisiones y gastos de difícil justificación "
                f"({normativa.dificil_justificacion_pct} %, máx. {normativa.dificil_justificacion_limite} €)."
            )
    avisos.append("Sin amortizaciones del inmovilizado (pendientes de la tabla de coeficientes).")
    return c01, c02, c06, avisos


def borrador_130(
    asientos, actividad, ejercicio: int, trimestre: int, *, titular_nif: str | None
) -> Borrador:
    perfil, normativa, libro, avisos, pendientes = _comunes(asientos, actividad, ejercicio)
    if not perfil.presenta_130:
        return Borrador(
            "130", ejercicio, f"{trimestre}T", False, {}, CERO, normativa.verificado,
            avisos + [f"Régimen de IRPF «{perfil.regimen_irpf}»: no presenta el modelo 130."],
        )

    # Trimestres anteriores: casilla 07 positiva (05) y resultados negativos (15)
    pagado = CERO
    negativos = CERO
    for t in range(1, trimestre):
        p01, p02, p06, _ = _acumulado_130(perfil, normativa, libro, t, titular_nif)
        p03 = p01.importe - p02.importe
        p04 = q2(p03 * normativa.pago_fraccionado_130 / CIEN) if p03 > 0 else CERO
        p07 = p04 - pagado - p06.importe
        p14 = max(p07, CERO) - _minoracion(perfil, normativa)
        compensa = min(negativos, p14) if p14 > 0 else CERO
        negativos -= compensa
        p19 = p14 - compensa
        if p19 < 0:
            negativos += -p19
        if p07 > 0:
            pagado += p07

    c01, c02, c06, avisos_acum = _acumulado_130(perfil, normativa, libro, trimestre, titular_nif)
    avisos.extend(avisos_acum)
    c03 = Casilla("03", "Rendimiento neto", q2(c01.importe - c02.importe))
    c04 = Casilla(
        "04", f"{normativa.pago_fraccionado_130} % del rendimiento positivo",
        q2(c03.importe * normativa.pago_fraccionado_130 / CIEN) if c03.importe > 0 else CERO,
    )
    c05 = Casilla("05", "Pagos fraccionados de trimestres anteriores", q2(pagado))
    c07 = Casilla("07", "Pago fraccionado previo", q2(c04.importe - c05.importe - c06.importe))
    c12 = Casilla("12", "Total liquidación", max(c07.importe, CERO))
    minoracion = _minoracion(perfil, normativa)
    if perfil.rendimiento_anterior is None:
        avisos.append("Falta el rendimiento neto del año anterior: no se aplica la minoración de la casilla 13.")
    c13 = Casilla("13", "Minoración art. 110.3.c RIRPF", minoracion)
    c14 = Casilla("14", "Diferencia", q2(c12.importe - c13.importe))
    c15 = Casilla(
        "15", "Resultados negativos de trimestres anteriores",
        q2(min(negativos, c14.importe)) if c14.importe > 0 else CERO,
    )
    c16 = Casilla("16", "Deducción por vivienda habitual", CERO)
    c17 = Casilla("17", "Total", q2(c14.importe - c15.importe - c16.importe))
    c19 = Casilla("19", "Resultado", c17.importe)
    avisos.append(
        "Casilla 05 calculada con los borradores anteriores; si presentaste importes distintos, usa los presentados."
    )
    con_retencion = sum((a.total or CERO for a in libro if a.tipo == TIPO_INGRESO and a.retencion_cuota), CERO)
    total_ingresos = sum((a.total or CERO for a in libro if a.tipo == TIPO_INGRESO), CERO)
    if total_ingresos > 0 and con_retencion / total_ingresos >= Decimal("0.7"):
        avisos.append(
            "Al menos el 70 % de los ingresos llevan retención: si también ocurrió el año anterior, "
            "no estás obligado a presentar el 130 (art. 109.1 RIRPF)."
        )
    casillas = {item.numero: item for item in (c01, c02, c03, c04, c05, c06, c07, c12, c13, c14, c15, c16, c17, c19)}
    pend = [a for a in pendientes if (_trimestre(a.fecha) or 9) <= trimestre]
    return Borrador(
        "130", ejercicio, f"{trimestre}T", True, casillas, c19.importe, normativa.verificado, _unicos(avisos),
        len(pend), sum((a.total or CERO for a in pend), CERO),
    )


def _minoracion(perfil, normativa: Normativa) -> Decimal:
    anterior = perfil.rendimiento_anterior
    if anterior is None:
        return CERO
    for hasta, importe in normativa.minoracion_130:
        if anterior <= hasta:
            return importe
    return CERO


def _tipo(valor: Decimal | None) -> str:
    """'21.00' → '21', '5.20' → '5.2' (sin notación científica)."""
    return f"{(valor or CERO).normalize():f}"


def _orden(numero: str) -> tuple[int, str]:
    return (int(numero) if numero.isdigit() else 999, numero)


def _unicos(items: list[str]) -> list[str]:
    vistos: dict[str, None] = {}
    for item in items:
        vistos.setdefault(item, None)
    return list(vistos)


def resumen_por_asiento(borrador: Borrador) -> dict[int, list[str]]:
    """Para la interfaz: qué casillas alimenta cada asiento."""
    mapa: dict[int, list[str]] = defaultdict(list)
    for numero, casilla in borrador.casillas.items():
        for asiento_id in casilla.asientos:
            mapa[asiento_id].append(numero)
    return dict(mapa)
