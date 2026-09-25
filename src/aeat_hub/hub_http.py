"""Servidor local 127.0.0.1: HTML, documentos y correcciones al libro."""

from __future__ import annotations

import json
import mimetypes
import re
import socket
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy import select

from aeat_hub.dashboard import (
    ESTADO_LABEL,
    REGIMEN_LABEL,
    collect_asiento_ficha,
    criterios_calidad,
    render_asiento_page,
    write_dashboard,
)
from aeat_hub.db import session_scope
from aeat_hub.edits import AsientoNoEncontrado, articulos_label, lineas_de_asiento, parse_money_field, patch_asiento
from aeat_hub.fiscal.cuadres import TOLERANCIA_TOTAL
from aeat_hub.fiscal.money import q2
from aeat_hub.models import Actividad, Asiento, Cambio, Cuenta, Titular
from aeat_hub.paths import DataLayout
from aeat_hub.services import patch_expediente


def _regenerar_libro(session, layout: DataLayout, actividad: Actividad, year: int, body: dict) -> None:
    """Regenera el libro tras un cambio ya salvado: nunca puede tumbar la corrección."""
    try:
        write_dashboard(session, layout, actividad, year)
    except Exception as err:  # noqa: BLE001 - p. ej. el XLSX bloqueado por Excel
        body["libro"] = f"no regenerado ({err})"


class HubHandler(BaseHTTPRequestHandler):
    layout: DataLayout
    factory = None
    dashboard_name = ""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"/", "/index.html"} and self.dashboard_name:
            self.send_response(302)
            self.send_header("Location", f"/{self.dashboard_name}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        match = _DOC_PATH.fullmatch(path)
        if match:
            self._send_doc(int(match.group(1)))
            return
        match = _ASIENTO_PAGE.fullmatch(path)
        if match:
            self._send_asiento_page(int(match.group(1)))
            return
        match = _API_ASIENTO.fullmatch(path)
        if match:
            self._send_asiento(int(match.group(1)))
            return
        self._send_export(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        match = _API_ASIENTO.fullmatch(parsed.path)
        if match:
            self._post_asiento(int(match.group(1)))
            return
        if _API_EXPEDIENTE.fullmatch(parsed.path):
            self._post_expediente()
            return
        self.send_error(404, "No encontrado")

    def _read_json_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "JSON inválido"})
            return None
        if not isinstance(payload, dict):
            self._send_json(400, {"ok": False, "error": "Cuerpo inválido"})
            return None
        if not payload.get("confirmado"):
            self._send_json(400, {"ok": False, "error": "Confirma el cambio"})
            return None
        return payload

    def _post_asiento(self, asiento_id: int) -> None:
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            with session_scope(self.factory) as session:
                asiento = patch_asiento(session, asiento_id, payload)
                session.flush()
                session.commit()
                body = _asiento_json(session, asiento)
                body["ok"] = True
                actividad = session.get(Actividad, asiento.actividad_id)
                if actividad is not None and asiento.ejercicio:
                    _regenerar_libro(session, self.layout, actividad, asiento.ejercicio, body)
        except AsientoNoEncontrado:
            self.send_error(404, "Asiento no encontrado")
            return
        except (ValueError, RuntimeError) as err:
            self._send_json(400, {"ok": False, "error": str(err)})
            return
        self._send_json(200, body)

    def _post_expediente(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            return
        codigo, year = _parse_dashboard_name(self.dashboard_name)
        if not codigo:
            self._send_json(400, {"ok": False, "error": "No hay expediente en este servidor"})
            return
        try:
            with session_scope(self.factory) as session:
                body = patch_expediente(session, codigo, payload)
                session.flush()
                session.commit()
                actividad = session.scalar(select(Actividad).where(Actividad.codigo == codigo))
                body["ok"] = True
                body["regimen_label"] = REGIMEN_LABEL.get(body.get("regimen", ""), body.get("regimen", ""))
                if actividad is not None and year:
                    _regenerar_libro(session, self.layout, actividad, year, body)
        except (RuntimeError, ValueError) as err:
            self._send_json(400, {"ok": False, "error": str(err)})
            return
        self._send_json(200, body)

    def _send_asiento(self, asiento_id: int) -> None:
        with session_scope(self.factory) as session:
            asiento = session.get(Asiento, asiento_id)
            if asiento is None:
                self.send_error(404, "Asiento no encontrado")
                return
            body = _asiento_json(session, asiento)
            body["ok"] = True
        self._send_json(200, body)

    def _send_asiento_page(self, asiento_id: int) -> None:
        with session_scope(self.factory) as session:
            asiento = session.get(Asiento, asiento_id)
            if asiento is None:
                self.send_error(404, "Asiento no encontrado")
                return
            data = collect_asiento_ficha(session, asiento, dashboard_name=self.dashboard_name)
        html = render_asiento_page(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _send_doc(self, asiento_id: int) -> None:
        with session_scope(self.factory) as session:
            asiento = session.get(Asiento, asiento_id)
            documento = asiento.documento if asiento is not None else None
            if documento is None or not documento.ruta_almacenada:
                self.send_error(404, "Sin documento")
                return
            stored = Path(documento.ruta_almacenada)
            name = documento.nombre_original or stored.name
        if not stored.is_file():
            self.send_error(404, "Fichero no encontrado")
            return
        if not _is_under(stored, self.layout.root):
            self.send_error(403, "Fuera del directorio de datos")
            return
        self._send_file(stored, download_name=name)

    def _send_export(self, path: str) -> None:
        rel = path.lstrip("/")
        if not rel or ".." in Path(rel).parts:
            self.send_error(404, "No encontrado")
            return
        dest = (self.layout.exports / rel).resolve()
        if not _is_under(dest, self.layout.exports) or not dest.is_file():
            self.send_error(404, "No encontrado")
            return
        self._send_file(dest)

    def _send_file(self, path: Path, *, download_name: str | None = None) -> None:
        mime, _ = mimetypes.guess_type(str(path))
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        if download_name:
            self.send_header("Content-Disposition", f'inline; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def bind_server(
    layout: DataLayout,
    factory,
    dashboard_name: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> tuple[ThreadingHTTPServer, int]:
    HubHandler.layout = layout
    HubHandler.factory = factory
    HubHandler.dashboard_name = dashboard_name
    chosen = _free_port(host, port)
    httpd = ThreadingHTTPServer((host, chosen), HubHandler)
    return httpd, chosen


def _free_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 12):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No hay puerto libre a partir de {preferred}")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _asiento_json(session, asiento: Asiento) -> dict:
    logs = session.scalars(
        select(Cambio).where(Cambio.asiento_id == asiento.id).order_by(Cambio.id.desc())
    ).all()
    lineas = lineas_de_asiento(asiento)
    actividad = session.get(Actividad, asiento.actividad_id)
    titular = session.get(Titular, actividad.titular_id) if actividad is not None else None
    rubro = _rubro_nombre(session, asiento)
    calidad = criterios_calidad(
        numero=asiento.numero_factura,
        fecha=asiento.fecha.strftime("%d/%m/%Y") if asiento.fecha else "",
        emisor=asiento.emisor,
        nif=asiento.nif_emisor,
        base=asiento.base,
        iva=asiento.iva_cuota,
        total=asiento.total,
        rubro=rubro if asiento.cuenta_codigo else "",
        lineas=lineas,
        titular_nif=titular.nif if titular else "",
    )
    suma = None
    if lineas:
        acc = Decimal("0.00")
        for item in lineas:
            parsed = parse_money_field(item.get("importe"))
            if parsed is not None:
                acc += parsed
        suma = q2(acc)
    return {
        "id": asiento.id,
        "nif_emisor": asiento.nif_emisor or "",
        "emisor": asiento.emisor or "",
        "numero": asiento.numero_factura or "—",
        "fecha": asiento.fecha.isoformat() if asiento.fecha else "",
        "fecha_label": asiento.fecha.strftime("%d/%m/%Y") if asiento.fecha else "",
        "n_articulos": articulos_label(lineas),
        "base": _dec(asiento.base),
        "iva_cuota": _dec(asiento.iva_cuota),
        "total": _dec(asiento.total),
        "validado": bool(asiento.validado),
        "calidad": [
            {"id": item["id"], "label": item["label"], "ok": item["ok"], "detail": item["detail"]}
            for item in calidad
        ],
        "estado": asiento.estado,
        "estado_label": ESTADO_LABEL.get(asiento.estado, asiento.estado),
        "lineas": lineas,
        "lineas_suma": _dec(suma),
        "lineas_ok": _lineas_cuadran(asiento, suma),
        "rubro": _rubro_nombre(session, asiento),
        "cambios": [
            {
                "campo": item.campo,
                "antes": item.antes,
                "despues": item.despues,
                "cuando": item.created_at.strftime("%d/%m/%Y %H:%M") if item.created_at else "",
            }
            for item in logs
        ],
    }


def _rubro_nombre(session, asiento: Asiento) -> str:
    if not asiento.cuenta_codigo:
        return ""
    cuenta = session.get(Cuenta, asiento.cuenta_codigo)
    return cuenta.nombre if cuenta is not None else ""


def _lineas_cuadran(asiento: Asiento, suma) -> bool:
    if suma is None:
        return False
    tol = TOLERANCIA_TOTAL
    for target in (asiento.base, asiento.total):
        if target is not None and abs(suma - target) <= tol:
            return True
    return False


def _dec(value: object) -> str:
    return "" if value is None else f"{value:.2f}"


_DOC_PATH = re.compile(r"^/doc/(\d+)$")
_ASIENTO_PAGE = re.compile(r"^/asiento/(\d+)$")
_API_ASIENTO = re.compile(r"^/api/asientos/(\d+)$")
_API_EXPEDIENTE = re.compile(r"^/api/expediente$")
_DASHBOARD_NAME = re.compile(r"^dashboard_(.+)_(\d{4})\.html$")


def _parse_dashboard_name(name: str) -> tuple[str, int]:
    match = _DASHBOARD_NAME.fullmatch(name or "")
    if not match:
        return "", 0
    return match.group(1), int(match.group(2))
