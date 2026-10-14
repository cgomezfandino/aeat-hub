"""Servidor local 127.0.0.1: HTML, documentos y correcciones al libro."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import socket
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from sqlalchemy import select

from aeat_hub.dashboard import (
    ESTADO_LABEL,
    REGIMEN_LABEL,
    collect_asiento_ficha,
    collect_dashboard,
    criterios_calidad,
    render_asiento_page,
    render_dashboard,
    write_dashboard,
)
from aeat_hub.db import session_scope
from aeat_hub.edits import AsientoNoEncontrado, articulos_label, lineas_de_asiento, parse_money_field, patch_asiento
from aeat_hub.fiscal.cuadres import TOLERANCIA_TOTAL
from aeat_hub.fiscal.money import q2
from aeat_hub.models import Actividad, Asiento, Cambio, Cuenta, Titular
from aeat_hub.paths import DataLayout
from aeat_hub.services import patch_expediente
from aeat_hub.subidas import nombre_seguro as _safe_upload_name


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
            self._send_asiento_page(int(match.group(1)), parsed.query)
            return
        match = _API_ASIENTO.fullmatch(path)
        if match:
            self._send_asiento(int(match.group(1)))
            return
        match = _STATIC.fullmatch(path)
        if match:
            self._send_static(match.group(1))
            return
        self._send_export(path, parsed.query)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        match = _API_ASIENTO.fullmatch(parsed.path)
        if match:
            self._post_asiento(int(match.group(1)))
            return
        if _API_EXPEDIENTE.fullmatch(parsed.path):
            self._post_expediente()
            return
        if parsed.path == "/api/upload":
            self._post_upload()
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

    def _post_upload(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "JSON inválido"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"ok": False, "error": "Cuerpo inválido"})
            return

        filename = _safe_upload_name(str(payload.get("filename") or "factura.pdf"))
        if filename is None:
            self._send_json(400, {"ok": False, "error": "Nombre o tipo de fichero no admitido"})
            return
        b64_data = payload.get("data") or payload.get("content_base64")
        if not b64_data:
            self._send_json(400, {"ok": False, "error": "Falta el contenido del fichero"})
            return

        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]

        try:
            file_bytes = base64.b64decode(b64_data)
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": f"Base64 inválido: {exc}"})
            return

        codigo, year = _parse_dashboard_name(self.dashboard_name)
        if not codigo:
            self._send_json(400, {"ok": False, "error": "No hay expediente activo en este servidor"})
            return

        inbox_root = self.layout.inbox.resolve()
        inbox_dest = inbox_root / filename
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        counter = 1
        while inbox_dest.exists():
            inbox_dest = inbox_root / f"{stem}_{counter}{suffix}"
            counter += 1
        if inbox_dest.resolve().parent != inbox_root:
            self._send_json(400, {"ok": False, "error": "Ruta de subida no válida"})
            return

        inbox_dest.write_bytes(file_bytes)

        from aeat_hub.ingest import ingest_file

        with session_scope(self.factory) as session:
            actividad = session.scalar(select(Actividad).where(Actividad.codigo == codigo))
            if actividad is None:
                self._send_json(404, {"ok": False, "error": f"Actividad {codigo} no existe"})
                return

            ocr_pref = payload.get("ocr") or (
                "gemini" if os.environ.get("GEMINI_API_KEY") else "auto"
            )
            item = ingest_file(
                session,
                self.layout,
                inbox_dest,
                actividad,
                ocr_prefer=ocr_pref,
                from_inbox=True,
            )
            session.flush()
            session.commit()

            asiento_data = None
            if item.asiento_id is not None:
                asiento = session.get(Asiento, item.asiento_id)
                if asiento is not None:
                    asiento_data = _asiento_json(session, asiento)
                    _regenerar_libro(
                        session,
                        self.layout,
                        actividad,
                        asiento.ejercicio or year or 2026,
                        asiento_data,
                    )

            self._send_json(
                200,
                {
                    "ok": True,
                    "estado": item.estado,
                    "detalle": item.detalle,
                    "asiento_id": item.asiento_id,
                    "asiento": asiento_data,
                    "warnings": item.warnings,
                },
            )

    def _send_asiento(self, asiento_id: int) -> None:
        with session_scope(self.factory) as session:
            asiento = session.get(Asiento, asiento_id)
            if asiento is None:
                self.send_error(404, "Asiento no encontrado")
                return
            body = _asiento_json(session, asiento)
            body["ok"] = True
        self._send_json(200, body)

    def _send_asiento_page(self, asiento_id: int, query: str = "") -> None:
        with session_scope(self.factory) as session:
            asiento = session.get(Asiento, asiento_id)
            if asiento is None:
                self.send_error(404, "Asiento no encontrado")
                return
            data = collect_asiento_ficha(session, asiento, dashboard_name=self.dashboard_name)
            if _quiere_ui2(query):
                data["ui"] = "v2"
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

    def _send_static(self, rel: str) -> None:
        found = _static_file(rel)
        if found is None:
            self.send_error(404, "No encontrado")
            return
        self._send_file(found)

    def _send_export(self, path: str, query: str = "") -> None:
        rel = path.lstrip("/")
        if not rel or ".." in Path(rel).parts:
            self.send_error(404, "No encontrado")
            return
        if _DASHBOARD_NAME.fullmatch(rel) and _quiere_ui2(query):
            self._send_dashboard_live(rel)
            return
        dest = (self.layout.exports / rel).resolve()
        if not _is_under(dest, self.layout.exports) or not dest.is_file():
            self.send_error(404, "No encontrado")
            return
        self._send_file(dest)

    def _send_dashboard_live(self, name: str) -> None:
        """Render fresco del libro (?ui=v2): la v1 sigue saliendo del fichero."""
        codigo, year = _parse_dashboard_name(name)
        with session_scope(self.factory) as session:
            actividad = session.scalar(select(Actividad).where(Actividad.codigo == codigo))
            if actividad is None:
                self.send_error(404, "Expediente no encontrado")
                return
            data = collect_dashboard(session, actividad, year)
            data["ui"] = "v2"
            html = render_dashboard(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

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
_STATIC = re.compile(r"^/static/(.+)$")
_STATIC_ROOT = Path(__file__).resolve().parent / "static"


def _static_file(rel: str, *, root: Path = _STATIC_ROOT) -> Path | None:
    """Fichero estático bajo root, o None si no existe o escapa de la raíz."""
    candidate = (root / rel).resolve()
    if not _is_under(candidate, root) or not candidate.is_file():
        return None
    return candidate
_DASHBOARD_NAME = re.compile(r"^dashboard_(.+)_(\d{4})\.html$")


def _quiere_ui2(query: str) -> bool:
    return any(key == "ui" and value == "v2" for key, value in parse_qsl(query or ""))


def _parse_dashboard_name(name: str) -> tuple[str, int]:
    match = _DASHBOARD_NAME.fullmatch(name or "")
    if not match:
        return "", 0
    return match.group(1), int(match.group(2))
