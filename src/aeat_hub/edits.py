"""Correcciones humanas de NIF, importes, líneas de factura y validación."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from aeat_hub.classify import _apply_cuenta, reabrir_asiento, validar_asiento
from aeat_hub.er import _fusionar_en, add_relacion, backfill_asientos
from aeat_hub.extract.ids import normalize_emisor
from aeat_hub.extract.parser import parse_invoice
from aeat_hub.extract.schema import InvoiceExtract, InvoiceLine
from aeat_hub.fiscal.money import parse_amount, q2
from aeat_hub.fiscal.nif import normalize_nif
from aeat_hub.models import Actividad, Asiento, Cambio, Cuenta, Factura, Linea
from aeat_hub.services import get_cuenta_por_nombre

ZERO = Decimal("0.00")
CAMPOS_IMPORTE = ("base", "iva_cuota", "total")


class AsientoNoEncontrado(LookupError):
    pass


def marcar_duplicado(session: Session, origen_id: int, destino_id: int) -> Asiento:
    """Fusión manual evidente: origen queda duplicado de destino.

    Mueve las evidencias a la factura del destino, marca el origen
    (nivel 2, decisión humana) y deja la relación `misma_factura`.
    """
    if origen_id == destino_id:
        raise ValueError("Un asiento no puede ser duplicado de sí mismo.")
    origen = session.get(Asiento, origen_id)
    destino = session.get(Asiento, destino_id)
    if origen is None or destino is None:
        raise AsientoNoEncontrado(origen_id if origen is None else destino_id)
    if origen.actividad_id != destino.actividad_id:
        raise ValueError("Los dos asientos no son del mismo expediente.")
    if origen.estado == "duplicado":
        raise ValueError(f"El asiento {origen.id} ya está marcado como duplicado.")
    if destino.estado == "duplicado":
        raise ValueError(
            f"El asiento {destino.id} ya es un duplicado: marca el duplicado del asiento bueno."
        )

    if origen.factura_id is None or destino.factura_id is None:
        backfill_asientos(session)
    factura_origen = origen.factura
    factura_destino = destino.factura
    if factura_origen is None or factura_destino is None:
        raise RuntimeError("Faltan factura canónica tras el backfill.")

    _fusionar_en(
        session,
        origen_asiento=origen,
        origen_factura=factura_origen,
        destino_asiento=destino,
        destino_factura=factura_destino,
    )
    add_relacion(
        session,
        origen_tipo="factura",
        origen_id=factura_origen.id,
        destino_tipo="factura",
        destino_id=factura_destino.id,
        tipo="misma_factura",
        motivo="fusión manual de duplicado evidente",
        fuente="usuario",
    )
    _registrar(session, origen, "estado", "pendiente", "duplicado")
    _registrar(session, origen, "duplicado_de_id", "", str(destino.id))
    if destino.duplicado_de_id == origen.id:
        _registrar(session, destino, "duplicado_de_id", str(origen.id), "")
        destino.duplicado_de_id = None
        destino.duplicado_nivel = None
    session.flush()
    return origen


def desmarcar_duplicado(session: Session, asiento_id: int) -> Asiento:
    """Deshace un duplicado: vuelve a pendiente, sin enlace ni nivel."""
    asiento = session.get(Asiento, asiento_id)
    if asiento is None:
        raise AsientoNoEncontrado(asiento_id)
    if asiento.estado != "duplicado":
        raise ValueError(f"El asiento {asiento_id} no está marcado como duplicado.")
    _registrar(session, asiento, "estado", "duplicado", "pendiente")
    _registrar(
        session,
        asiento,
        "duplicado_de_id",
        str(asiento.duplicado_de_id or ""),
        "",
    )
    asiento.estado = "pendiente"
    asiento.duplicado_de_id = None
    asiento.duplicado_nivel = None
    session.flush()
    return asiento


def parse_money_field(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return q2(value)
    text = str(value).strip()
    if text in {"", "—", "-"}:
        return None
    return parse_amount(text)


def log_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        quantized = q2(value)
        return "" if quantized is None else f"{quantized:.2f}"
    return str(value)


def _registrar(session: Session, asiento: Asiento, campo: str, antes: object, despues: object) -> None:
    before = log_value(antes)
    after = log_value(despues)
    if before == after:
        return
    session.add(
        Cambio(
            asiento_id=asiento.id,
            campo=campo,
            antes=before,
            despues=after,
            fuente="dashboard",
        )
    )


def patch_asiento(session: Session, asiento_id: int, payload: dict) -> Asiento:
    asiento = session.get(Asiento, asiento_id)
    if asiento is None:
        raise AsientoNoEncontrado(asiento_id)

    if "duplicado_de" in payload:
        raw = str(payload.get("duplicado_de") or "").strip()
        if not raw.isdigit():
            raise ValueError("Indica el id del asiento bueno (el duplicado apunta a él).")
        return marcar_duplicado(session, asiento_id, int(raw))
    if payload.get("quitar_duplicado"):
        return desmarcar_duplicado(session, asiento_id)
    if payload.get("rechazar"):
        from aeat_hub.classify import rechazar_asiento

        rechazar_asiento(asiento)
        session.flush()
        return asiento

    dirty = False
    if "nif_emisor" in payload and payload["nif_emisor"] is not None:
        raw = str(payload["nif_emisor"]).strip()
        nif = normalize_nif(raw) if raw else None
        if not nif and raw:
            nif = raw.upper()[:12]
        nif = nif or None
        if nif != asiento.nif_emisor:
            _registrar(session, asiento, "nif_emisor", asiento.nif_emisor, nif)
            asiento.nif_emisor = nif
            dirty = True

    if "emisor" in payload and payload["emisor"] is not None:
        nombre = " ".join(str(payload["emisor"]).split())[:200] or None
        if nombre != asiento.emisor:
            _registrar(session, asiento, "emisor", asiento.emisor, nombre or "")
            asiento.emisor = nombre
            dirty = True

    if "fecha" in payload:
        nueva = _parse_fecha(payload.get("fecha"))
        if nueva != asiento.fecha:
            antes = asiento.fecha.isoformat() if asiento.fecha else ""
            despues = nueva.isoformat() if nueva else ""
            _registrar(session, asiento, "fecha", antes, despues)
            asiento.fecha = nueva
            if nueva is not None:
                asiento.ejercicio = nueva.year
            dirty = True

    for field in CAMPOS_IMPORTE:
        if field not in payload:
            continue
        parsed = parse_money_field(payload[field])
        current = getattr(asiento, field)
        if parsed != current:
            _registrar(session, asiento, field, current, parsed)
            setattr(asiento, field, parsed)
            dirty = True

    if asiento.base is not None and asiento.iva_cuota is not None and asiento.base != ZERO:
        asiento.iva_tipo = q2((asiento.iva_cuota / asiento.base) * 100)

    if asiento.factura_id:
        factura = session.get(Factura, asiento.factura_id)
        if factura is not None:
            if "nif_emisor" in payload:
                factura.nif_emisor = asiento.nif_emisor
            if "emisor" in payload:
                factura.emisor = asiento.emisor
                factura.emisor_norm = normalize_emisor(asiento.emisor)
            if "fecha" in payload:
                factura.fecha = asiento.fecha
            if "base" in payload:
                factura.base = asiento.base
            if "iva_cuota" in payload:
                factura.iva_cuota = asiento.iva_cuota
            if ("base" in payload or "iva_cuota" in payload) and asiento.iva_tipo is not None:
                factura.iva_tipo = asiento.iva_tipo
            if "total" in payload:
                factura.total = asiento.total

    if "rubro" in payload and _aplicar_rubro(session, asiento, payload.get("rubro")):
        dirty = True

    if "lineas" in payload and isinstance(payload["lineas"], list):
        if _guardar_lineas(session, asiento, payload["lineas"]):
            dirty = True
        if payload.get("recalcular_total"):
            _totales_desde_lineas(session, asiento)
            dirty = True

    if "validado" in payload:
        want = bool(payload["validado"])
        if want:
            if not asiento.validado:
                _registrar(session, asiento, "validado", False, True)
            validar_asiento(asiento)
        else:
            if asiento.validado:
                _registrar(session, asiento, "validado", True, False)
            reabrir_asiento(asiento)
    elif dirty and not payload.get("mantener_estado"):
        if not asiento.validado:
            _registrar(session, asiento, "validado", False, True)
        validar_asiento(asiento)
    return asiento


def _parse_fecha(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as err:
        raise ValueError("La fecha de compra no es válida.") from err


def _aplicar_rubro(session: Session, asiento: Asiento, raw: object) -> bool:
    nombre = str(raw or "").strip()
    actividad = session.get(Actividad, asiento.actividad_id)
    actual = ""
    if asiento.cuenta_codigo:
        cuenta_actual = session.get(Cuenta, asiento.cuenta_codigo)
        actual = cuenta_actual.nombre if cuenta_actual is not None else ""
    if not nombre:
        if not asiento.cuenta_codigo:
            return False
        _registrar(session, asiento, "rubro", actual or asiento.cuenta_codigo, "")
        asiento.cuenta_codigo = None
        return True
    if actividad is None:
        raise RuntimeError("El asiento no tiene expediente.")
    cuenta = get_cuenta_por_nombre(session, nombre, regimen=actividad.regimen)
    if cuenta.codigo == asiento.cuenta_codigo:
        return False
    _registrar(session, asiento, "rubro", actual or "—", cuenta.nombre)
    _apply_cuenta(asiento, cuenta, origen="usuario", confianza=Decimal("1.000"))
    return True


def _guardar_lineas(session: Session, asiento: Asiento, payload: list) -> bool:
    nuevas: list[InvoiceLine] = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        desc = str(item.get("descripcion") or "").strip()
        importe = parse_money_field(item.get("importe"))
        if not desc and importe is None:
            continue
        cantidad = parse_money_field(item.get("cantidad"))
        if desc and cantidad is None:
            cantidad = Decimal("1")
        nuevas.append(
            InvoiceLine(
                descripcion=desc[:200],
                codigo=(str(item.get("codigo") or "").strip() or None),
                posicion=idx,
                cantidad=cantidad,
                eliminada=bool(item.get("eliminada")),
                base=parse_money_field(item.get("base")),
                iva_tipo=parse_money_field(item.get("iva_tipo")),
                iva_cuota=parse_money_field(item.get("iva_cuota")),
                importe=importe,
            )
        )
    antes = lineas_de_asiento(asiento)
    despues = _serialize_lineas(nuevas)
    if antes == despues:
        return False
    _registrar(
        session,
        asiento,
        "lineas",
        f"{len(antes)} líneas",
        f"{len(despues)} líneas",
    )
    replace_lineas(session, asiento, nuevas)
    return True


def replace_lineas(session: Session, asiento: Asiento, lineas: list[InvoiceLine]) -> None:
    """Escribe las líneas del asiento en la tabla `lineas` (la fuente de verdad).

    El JSON del documento no se toca: guarda la salida del modelo tal cual.
    """
    asiento.lineas.clear()
    for idx, linea in enumerate(lineas, start=1):
        desc = (linea.descripcion or "").strip()
        codigo = (linea.codigo or "").strip() or None
        importe = q2(linea.importe) if linea.importe is not None else None
        if not desc and not codigo and importe is None:
            continue
        asiento.lineas.append(
            Linea(
                posicion=linea.posicion or idx,
                codigo=codigo,
                descripcion=desc[:200],
                cantidad=linea.cantidad,
                base=q2(linea.base) if linea.base is not None else None,
                iva_tipo=q2(linea.iva_tipo) if linea.iva_tipo is not None else None,
                iva_cuota=q2(linea.iva_cuota) if linea.iva_cuota is not None else None,
                importe=importe,
                eliminada=bool(linea.eliminada),
            )
        )
    session.flush()


def backfill_lineas(session: Session) -> int:
    """Migra a la tabla `lineas` los desgloses que vivían en el JSON del documento."""
    rows = session.scalars(
        select(Asiento).where(Asiento.documento_id.is_not(None))
    ).all()
    if not rows:
        return 0
    tienen = set(
        session.scalars(
            select(Linea.asiento_id).where(Linea.asiento_id.in_([row.id for row in rows]))
        )
    )
    created = 0
    for asiento in rows:
        if asiento.id in tienen:
            continue
        documento = asiento.documento
        if documento is None:
            continue
        lineas = _lineas_de_documento(documento)
        if not lineas:
            continue
        replace_lineas(session, asiento, lineas)
        created += 1
    return created


def _totales_desde_lineas(session: Session, asiento: Asiento) -> None:
    lineas = lineas_de_asiento(asiento)
    activas = [item for item in lineas if not item.get("eliminada")]
    def _suma(key: str) -> Decimal | None:
        valores = [parse_money_field(item.get(key)) for item in activas]
        numeros = [valor for valor in valores if valor is not None]
        if not numeros:
            return None
        return q2(sum(numeros, ZERO))

    cambios = (("base", _suma("base")), ("iva_cuota", _suma("iva_cuota")), ("total", _suma("importe")))
    factura = session.get(Factura, asiento.factura_id) if asiento.factura_id else None
    for campo, nuevo in cambios:
        if nuevo is None:
            continue
        actual = getattr(asiento, campo)
        if actual == nuevo:
            continue
        _registrar(session, asiento, campo, actual, nuevo)
        setattr(asiento, campo, nuevo)
        if factura is not None:
            setattr(factura, campo, nuevo)
    if asiento.base is not None and asiento.iva_cuota is not None and asiento.base != ZERO:
        asiento.iva_tipo = q2((asiento.iva_cuota / asiento.base) * 100)
        if factura is not None:
            factura.iva_tipo = asiento.iva_tipo


def cantidad_de_linea(item: dict) -> Decimal:
    """Unidades de una línea con nombre. Si no hay cantidad guardada, cuenta 1."""
    if item.get("eliminada"):
        return ZERO
    if not (item.get("descripcion") or "").strip():
        return ZERO
    parsed = parse_money_field(item.get("cantidad"))
    if parsed is None or parsed < 0:
        return Decimal("1")
    return parsed


def suma_articulos(lineas: list[dict]) -> Decimal:
    return sum((cantidad_de_linea(item) for item in lineas), ZERO)


def articulos_label(lineas: list[dict]) -> str:
    total = suma_articulos(lineas)
    if total <= 0:
        return "0"
    if total == total.to_integral_value():
        return str(int(total))
    text = f"{total.quantize(Decimal('0.001')):.3f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _fmt_cantidad(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = f"{value.quantize(Decimal('0.001')):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def lineas_de_asiento(asiento: Asiento) -> list[dict]:
    """Líneas actuales del asiento.

    La tabla `lineas` manda; si aún no tiene filas (datos previos a la tabla),
    se leen del documento como legado: JSON del extracto o heurística OCR.
    """
    rows = list(asiento.lineas)
    if rows:
        return [_linea_row_to_dict(row) for row in rows]
    documento = asiento.documento
    if documento is None:
        return []
    return _serialize_lineas(_lineas_de_documento(documento))


def _lineas_de_documento(documento) -> list[InvoiceLine]:
    try:
        extract = InvoiceExtract.model_validate_json(documento.json_extraido or "{}")
        if extract.lineas:
            return extract.lineas
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    text = (documento.texto_crudo or "").strip()
    if not text:
        return []
    return parse_invoice(text).lineas


def _linea_row_to_dict(row: Linea) -> dict:
    importe = q2(row.importe) if row.importe is not None else None
    base = q2(row.base) if row.base is not None else None
    iva = q2(row.iva_cuota) if row.iva_cuota is not None else None
    tipo = q2(row.iva_tipo) if row.iva_tipo is not None else None
    cantidad = None if row.cantidad is None else _fmt_cantidad(row.cantidad)
    return {
        "descripcion": (row.descripcion or "").strip()[:200],
        "codigo": (row.codigo or "").strip() or None,
        "posicion": row.posicion,
        "cantidad": cantidad,
        "importe": None if importe is None else f"{importe:.2f}",
        "base": None if base is None else f"{base:.2f}",
        "iva_cuota": None if iva is None else f"{iva:.2f}",
        "iva_tipo": None if tipo is None else f"{tipo:.2f}",
        "eliminada": bool(row.eliminada),
    }


def _serialize_lineas(lineas: list[InvoiceLine]) -> list[dict]:
    out: list[dict] = []
    for idx, linea in enumerate(lineas, start=1):
        desc = (linea.descripcion or "").strip()
        codigo = (linea.codigo or "").strip() or None
        importe = q2(linea.importe) if linea.importe is not None else None
        if not desc and not codigo and importe is None:
            continue
        base = q2(linea.base) if linea.base is not None else None
        iva = q2(linea.iva_cuota) if linea.iva_cuota is not None else None
        tipo = q2(linea.iva_tipo) if linea.iva_tipo is not None else None
        cantidad = None if linea.cantidad is None else _fmt_cantidad(linea.cantidad)
        item: dict = {
            "descripcion": desc[:200],
            "codigo": codigo,
            "posicion": linea.posicion or idx,
            "cantidad": cantidad,
            "importe": None if importe is None else f"{importe:.2f}",
            "base": None if base is None else f"{base:.2f}",
            "iva_cuota": None if iva is None else f"{iva:.2f}",
            "iva_tipo": None if tipo is None else f"{tipo:.2f}",
            "eliminada": bool(linea.eliminada),
        }
        out.append(item)
    return out
