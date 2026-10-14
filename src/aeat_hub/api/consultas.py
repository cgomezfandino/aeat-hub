"""Consultas de la API sobre el motor: sin lógica fiscal propia.

Todo lo fiscal sale de `fiscal/*` (cómputo, deducibilidad, libros, modelos);
aquí solo se reúne y se da forma de respuesta.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from aeat_hub.api import esquemas as e
from aeat_hub.dedupe import candidatos_duplicado
from aeat_hub.edits import lineas_de_asiento
from aeat_hub.fiscal.accounts import TIPO_INGRESO, TIPO_MEJORA
from aeat_hub.fiscal.computo import EXCLUIDOS, computables, es_computable, por_revisar
from aeat_hub.fiscal.cuadres import avisos_cuadre
from aeat_hub.fiscal.deducibilidad import evaluar
from aeat_hub.fiscal.nif import is_nif_iva_ue, is_placeholder_nif, is_valid_nif
from aeat_hub.fiscal.normativa import para
from aeat_hub.fiscal.perfil import perfil_de
from aeat_hub.models import Actividad, Asiento, Cambio, Cuenta, Titular

CERO = Decimal("0.00")


class NoEncontrado(LookupError):
    pass


def actividad(session: Session, codigo: str) -> Actividad:
    fila = session.scalar(select(Actividad).where(Actividad.codigo == codigo))
    if fila is None:
        raise NoEncontrado(f"No existe la actividad {codigo}.")
    return fila


def _titular_nif(session: Session, act: Actividad) -> str | None:
    titular = session.get(Titular, act.titular_id)
    return titular.nif if titular else None


def _asientos(session: Session, act: Actividad, ejercicio: int | None = None) -> list[Asiento]:
    consulta = (
        select(Asiento)
        .where(Asiento.actividad_id == act.id)
        .options(selectinload(Asiento.desglose_iva), selectinload(Asiento.documento))
        .order_by(Asiento.fecha.desc(), Asiento.id.desc())
    )
    if ejercicio is not None:
        consulta = consulta.where(Asiento.ejercicio == ejercicio)
    return list(session.scalars(consulta))


def listar_actividades(session: Session) -> list[e.Actividad]:
    salida = []
    for act in session.scalars(select(Actividad).order_by(Actividad.codigo)):
        titular = session.get(Titular, act.titular_id)
        perfil = perfil_de(act)
        ejercicios = sorted(
            {a for (a,) in session.execute(
                select(Asiento.ejercicio).where(Asiento.actividad_id == act.id, Asiento.ejercicio.is_not(None)).distinct()
            )},
            reverse=True,
        )
        salida.append(
            e.Actividad(
                codigo=act.codigo, nombre=act.nombre, regimen=act.regimen,
                regimen_irpf=perfil.regimen_irpf, regimen_iva=perfil.regimen_iva,
                titular=titular.nombre if titular else "",
                nif_titular_real=bool(titular and not is_placeholder_nif(titular.nif) and is_valid_nif(titular.nif)),
                ejercicios=ejercicios,
            )
        )
    return salida


def resumen(session: Session, codigo: str, ejercicio: int) -> e.Resumen:
    act = actividad(session, codigo)
    perfil = perfil_de(act)
    normativa = para(ejercicio)
    nif = _titular_nif(session, act)
    filas = _asientos(session, act, ejercicio)
    libro = computables(filas)
    pendientes = por_revisar(filas)
    meses = {m: {"ingresos": CERO, "gastos": CERO, "mejoras": CERO} for m in range(1, 13)}
    ingresos = gastos = mejoras = iva_ded = iva_rep = retenciones = CERO
    for asiento in libro:
        ded = evaluar(asiento, perfil, normativa, titular_nif=nif)
        mes = asiento.fecha.month if asiento.fecha else None
        if asiento.tipo == TIPO_INGRESO:
            ingresos += ded.importe_irpf
            retenciones += asiento.retencion_cuota or CERO
            if perfil.deduce_iva:
                iva_rep += asiento.iva_cuota or CERO
            clave = "ingresos"
            importe = ded.importe_irpf
        elif asiento.tipo == TIPO_MEJORA:
            mejoras += asiento.total or CERO
            clave, importe = "mejoras", asiento.total or CERO
        else:
            gastos += ded.importe_irpf
            clave, importe = "gastos", ded.importe_irpf
        iva_ded += ded.iva_deducible
        if mes:
            meses[mes][clave] += importe
    avisos = list(normativa.avisos) + list(perfil.avisos)
    if nif is None or is_placeholder_nif(nif):
        avisos.insert(0, "Falta el NIF real del titular: no se puede comprobar a nombre de quién están las facturas.")
    return e.Resumen(
        codigo=codigo, ejercicio=ejercicio, ingresos=ingresos, gastos=gastos, mejoras=mejoras,
        resultado=ingresos - gastos, iva_soportado_deducible=iva_ded, iva_repercutido=iva_rep,
        retenciones_soportadas=retenciones, n_computables=len(libro), n_por_revisar=len(pendientes),
        total_por_revisar=sum((a.total or CERO for a in pendientes), CERO),
        n_duplicados=sum(1 for a in filas if a.estado == "duplicado"),
        n_incidencias=len([i for i in incidencias(session, codigo, ejercicio) if i.gravedad != "info"]),
        por_mes=[e.Mes(mes=m, **valores) for m, valores in meses.items()],
        avisos=avisos,
    )


def _rubros(session: Session) -> dict[str, str]:
    return {c.codigo: c.nombre for c in session.scalars(select(Cuenta))}


def _fila(asiento: Asiento, rubros: dict[str, str]) -> e.FilaAsiento:
    return e.FilaAsiento(
        id=asiento.id, fecha=asiento.fecha, emisor=asiento.emisor, nif_emisor=asiento.nif_emisor,
        numero=asiento.numero_factura, tipo=asiento.tipo, rubro=rubros.get(asiento.cuenta_codigo or ""),
        base=asiento.base, iva_cuota=asiento.iva_cuota, total=asiento.total, estado=asiento.estado,
        validado=bool(asiento.validado), computa=es_computable(asiento), tipo_factura=asiento.tipo_factura,
        direccion=asiento.direccion, duplicado_de_id=asiento.duplicado_de_id,
        confianza=asiento.documento.confianza if asiento.documento else None,
        tiene_documento=bool(asiento.documento_id),
    )


def listar_asientos(
    session: Session, codigo: str, ejercicio: int | None, *, vista: str = "todos", q: str | None = None
) -> list[e.FilaAsiento]:
    act = actividad(session, codigo)
    rubros = _rubros(session)
    filas = _asientos(session, act, ejercicio)
    if vista == "por_revisar":
        filas = por_revisar(filas)
    elif vista == "libro":
        filas = computables(filas)
    elif vista == "duplicados":
        filas = [a for a in filas if a.estado == "duplicado"]
    elif vista == "rechazados":
        filas = [a for a in filas if a.estado == "rechazado"]
    if q:
        aguja = q.casefold()
        filas = [
            a for a in filas
            if aguja in " ".join(str(v or "") for v in (a.emisor, a.nif_emisor, a.numero_factura, a.total)).casefold()
        ]
    return [_fila(a, rubros) for a in filas]


def ficha(session: Session, asiento_id: int, *, raiz=None) -> e.Ficha:
    asiento = session.get(Asiento, asiento_id)
    if asiento is None:
        raise NoEncontrado(f"No existe el asiento {asiento_id}.")
    act = session.get(Actividad, asiento.actividad_id)
    rubros = _rubros(session)
    deducibilidad = None
    if asiento.ejercicio and asiento.estado not in EXCLUIDOS:
        ded = evaluar(asiento, perfil_de(act), para(asiento.ejercicio), titular_nif=_titular_nif(session, act))
        deducibilidad = e.Deducibilidad(
            pct_iva=ded.pct_iva, pct_gasto=ded.pct_gasto, iva_deducible=ded.iva_deducible,
            importe_irpf=ded.importe_irpf, es_ingreso=ded.es_ingreso,
            reglas=[e.Regla(codigo=r.codigo, texto=r.texto, cita=r.cita) for r in ded.reglas],
            avisos=ded.avisos,
        )
    cambios = session.scalars(select(Cambio).where(Cambio.asiento_id == asiento.id).order_by(Cambio.id.desc()))
    base = _fila(asiento, rubros).model_dump()
    return e.Ficha(
        **base,
        actividad=act.codigo, serie=asiento.serie, fecha_operacion=asiento.fecha_operacion,
        receptor=asiento.receptor, nif_receptor=asiento.nif_receptor, iva_tipo=asiento.iva_tipo,
        retencion_tipo=asiento.retencion_tipo, retencion_cuota=asiento.retencion_cuota,
        recargo_cuota=asiento.recargo_cuota, moneda=asiento.moneda, mencion_legal=asiento.mencion_legal,
        factura_rectificada=asiento.factura_rectificada, factura_rectificada_id=asiento.factura_rectificada_id,
        afectacion_pct=asiento.afectacion_pct, cuenta_codigo=asiento.cuenta_codigo,
        motivo_rechazo=asiento.motivo_rechazo,
        documento_nombre=asiento.documento.nombre_original if asiento.documento else None,
        documento_disponible=_documento_disponible(asiento, raiz),
        desglose_iva=[
            e.TipoIVA(base=f.base, tipo=f.tipo, cuota=f.cuota, recargo_tipo=f.recargo_tipo, recargo_cuota=f.recargo_cuota)
            for f in asiento.desglose_iva
        ],
        lineas=[e.Linea(**{k: v for k, v in linea.items() if k in e.Linea.model_fields}) for linea in lineas_de_asiento(asiento)],
        deducibilidad=deducibilidad,
        candidatos_duplicado=[
            e.Candidato(
                id=c["id"], emisor=c.get("emisor"), fecha=str(c.get("fecha") or "") or None,
                total=str(c.get("total") or "") or None, motivo=c.get("motivo", ""),
            )
            for c in candidatos_duplicado(session, asiento)
        ],
        cambios=[
            e.Cambio(
                campo=c.campo, antes=c.antes, despues=c.despues, fuente=c.fuente,
                cuando=c.created_at.isoformat() if c.created_at else None,
            )
            for c in cambios
        ],
    )


def incidencias(session: Session, codigo: str, ejercicio: int) -> list[e.Incidencia]:
    """Todo lo que pide criterio humano, con su motivo y su norma."""
    act = actividad(session, codigo)
    perfil = perfil_de(act)
    normativa = para(ejercicio)
    nif_titular = _titular_nif(session, act)
    salida: list[e.Incidencia] = []
    if nif_titular is None or is_placeholder_nif(nif_titular):
        salida.append(e.Incidencia(
            asiento_id=None, tipo="perfil", gravedad="revisar", titulo="Falta el NIF real del titular",
            detalle="Sin él no se comprueba que las facturas estén a tu nombre ni se separan emitidas y recibidas.",
            cita="art. 97 LIVA",
        ))
    if perfil.por_defecto:
        salida.append(e.Incidencia(
            asiento_id=None, tipo="perfil", gravedad="revisar", titulo="Perfil fiscal incompleto",
            detalle="Por defecto: " + ", ".join(perfil.por_defecto) + ".",
        ))
    for asiento in _asientos(session, act, ejercicio):
        if asiento.estado in EXCLUIDOS:
            continue
        nombre = asiento.emisor or f"#{asiento.id}"

        def nueva(tipo, gravedad, titulo, detalle, cita="", relacionado=None):
            salida.append(e.Incidencia(
                asiento_id=asiento.id, tipo=tipo, gravedad=gravedad, titulo=titulo, detalle=detalle,
                cita=cita, relacionado_id=relacionado,
            ))

        if asiento.duplicado_de_id:
            nueva("duplicado", "revisar", f"{nombre}: posible duplicado",
                  f"Se parece a la #{asiento.duplicado_de_id} (nivel {asiento.duplicado_nivel}). Fusiona o descarta.",
                  relacionado=asiento.duplicado_de_id)
        if asiento.tipo_factura == "no_factura":
            nueva("no_factura", "bloquea", f"{nombre}: no es una factura",
                  "Presupuesto, albarán o recibo: no justifica el gasto ni el IVA.", "art. 97 LIVA")
        if (asiento.moneda or "EUR") != "EUR":
            nueva("moneda", "bloquea", f"{nombre}: importes en {asiento.moneda}",
                  "Convierte a euros con el tipo de cambio de la fecha de devengo.")
        if asiento.nif_emisor and not (is_valid_nif(asiento.nif_emisor) or is_nif_iva_ue(asiento.nif_emisor)):
            nueva("nif", "revisar", f"{nombre}: NIF {asiento.nif_emisor} no válido",
                  "La letra o dígito de control no cuadra: probablemente un error de lectura.")
        elif not asiento.nif_emisor and asiento.tipo != TIPO_INGRESO:
            nueva("nif", "revisar", f"{nombre}: sin NIF del emisor", "Sin NIF no hay factura válida ni 347.",
                  "art. 6.1.d RD 1619/2012")
        for aviso in avisos_cuadre(
            base=asiento.base, iva_cuota=asiento.iva_cuota, iva_tipo=asiento.iva_tipo, total=asiento.total,
            retencion=asiento.retencion_cuota, recargo=asiento.recargo_cuota, fecha=asiento.fecha,
        ):
            nueva("cuadre", "revisar", f"{nombre}: importes que no cuadran", aviso)
        if asiento.factura_rectificada and asiento.factura_rectificada_id is None:
            nueva("rectificativa", "info", f"{nombre}: rectifica a {asiento.factura_rectificada}",
                  "La factura original no está en el libro.", "art. 15 RD 1619/2012")
        elif asiento.factura_rectificada_id and (asiento.total or CERO) > 0:
            nueva("rectificativa", "revisar", f"{nombre}: sustituye o corrige a la #{asiento.factura_rectificada_id}",
                  "Si la sustituye, rechaza la original para no contarla dos veces; si es por diferencias, se suman.",
                  "art. 15 RD 1619/2012", asiento.factura_rectificada_id)
        if not asiento.cuenta_codigo:
            nueva("sin_clasificar", "revisar", f"{nombre}: sin rubro", "Sin rubro no computa en ningún modelo.")
    orden = {"bloquea": 0, "revisar": 1, "info": 2}
    return sorted(salida, key=lambda i: (orden[i.gravedad], i.asiento_id or 0))


def borrador(b) -> e.Borrador:
    return e.Borrador(
        modelo=b.modelo, ejercicio=b.ejercicio, periodo=b.periodo, aplica=b.aplica, verificado=b.verificado,
        resultado=b.resultado,
        casillas=[e.Casilla(numero=c.numero, concepto=c.concepto, importe=c.importe, asientos=c.asientos)
                  for c in b.casillas.values()],
        avisos=b.avisos, n_por_revisar=b.n_por_revisar, total_por_revisar=b.total_por_revisar,
    )


def _anotacion(a) -> e.Anotacion:
    return e.Anotacion(
        asiento_id=a.asiento_id, numero_registro=a.numero_registro, fecha_expedicion=a.fecha_expedicion,
        fecha_operacion=a.fecha_operacion, serie=a.serie, numero=a.numero, nif=a.nif, nombre=a.nombre,
        concepto=a.concepto,
        desglose=[e.TipoIVA(base=f.base, tipo=f.tipo, cuota=f.cuota, recargo_tipo=f.recargo_tipo,
                            recargo_cuota=f.recargo_cuota) for f in a.desglose],
        total=a.total, retencion_cuota=a.retencion_cuota, rectificativa=a.rectificativa,
        importe_irpf=a.importe_irpf, iva_deducible=a.iva_deducible,
    )


def libros(lib) -> e.Libros:
    return e.Libros(
        ejercicio=lib.ejercicio, ingresos=[_anotacion(a) for a in lib.ingresos],
        gastos=[_anotacion(a) for a in lib.gastos], bienes_inversion=[_anotacion(a) for a in lib.bienes_inversion],
        n_por_revisar=lib.n_por_revisar, total_por_revisar=lib.total_por_revisar, avisos=lib.avisos,
    )


def _documento_disponible(asiento: Asiento, raiz) -> bool:
    from pathlib import Path

    doc = asiento.documento
    if doc is None or not doc.ruta_almacenada:
        return False
    ruta = Path(doc.ruta_almacenada).resolve()
    return ruta.is_file() and (raiz is None or ruta.is_relative_to(Path(raiz).resolve()))
