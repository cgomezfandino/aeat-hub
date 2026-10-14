"""Regresión del servidor local: la corrección humana nunca se pierde."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from threading import Thread
from urllib import error, request

from sqlalchemy import select

from aeat_hub.db import make_engine, session_factory
from aeat_hub.hub_http import bind_server
from aeat_hub.models import Actividad, Asiento, Cambio


def _asiento(session, actividad):
    row = Asiento(
        actividad_id=actividad.id,
        tipo="gasto",
        cuenta_codigo="CI.GAS.HOGAR",
        fecha=date(2026, 9, 5),
        ejercicio=2026,
        emisor="LEROY DEMO",
        nif_emisor="B84818442",
        numero_factura="F-1",
        base=Decimal("25.99"),
        iva_cuota=Decimal("5.46"),
        total=Decimal("31.45"),
        estado="pendiente",
    )
    session.add(row)
    session.commit()
    return row


def _post(port: int, asiento_id: int, payload: dict) -> tuple[int, dict]:
    req = request.Request(
        f"http://127.0.0.1:{port}/api/asientos/{asiento_id}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def test_hub_fecha_invalida_devuelve_400(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    row = _asiento(session, actividad)
    factory = session_factory(make_engine(layout))
    httpd, port = bind_server(layout, factory, "dashboard_CI-VA-001_2026.html", port=18763)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(port, row.id, {"fecha": "31/02/2026", "confirmado": True})
        assert status == 400
        assert body["ok"] is False
        assert "no es válida" in body["error"]
        session.expire_all()
        fresh = session.get(Asiento, row.id)
        assert fresh.fecha == date(2026, 9, 5)
        assert not session.scalars(select(Cambio).where(Cambio.asiento_id == row.id)).all()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hub_correccion_sobrevive_fallo_de_regeneracion(session, layout, monkeypatch):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    row = _asiento(session, actividad)

    def _libro_bloqueado(*args, **kwargs):
        raise PermissionError("libro.xlsx está abierto en Excel")

    monkeypatch.setattr("aeat_hub.hub_http.write_dashboard", _libro_bloqueado)
    factory = session_factory(make_engine(layout))
    httpd, port = bind_server(layout, factory, "dashboard_CI-VA-001_2026.html", port=18762)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            port, row.id, {"nif_emisor": "B12345674", "validado": True, "confirmado": True}
        )
        assert status == 200
        assert body["ok"] is True
        assert body["libro"].startswith("no regenerado")
        session.expire_all()
        fresh = session.get(Asiento, row.id)
        assert fresh.nif_emisor == "B12345674"
        assert fresh.validado is True
        logs = list(session.scalars(select(Cambio).where(Cambio.asiento_id == row.id)))
        assert any(item.campo == "nif_emisor" for item in logs)
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_api_asiento_devuelve_calidad_y_numero(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    row = _asiento(session, actividad)
    factory = session_factory(make_engine(layout))
    httpd, port = bind_server(layout, factory, "dashboard_CI-VA-001_2026.html", port=18761)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/asientos/{row.id}") as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["numero"] == "F-1"
        ids_calidad = [c["id"] for c in payload["calidad"]]
        assert "numero" in ids_calidad and "lineas" in ids_calidad
        assert all({"id", "label", "ok", "detail"} <= set(c) for c in payload["calidad"])
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_api_upload_procesa_factura_y_crea_asiento(session, layout, tmp_path):
    import base64
    from tests.samples import FACTURA_LUZ, write_pdf

    sample_pdf = write_pdf(tmp_path / "upload_sample.pdf", FACTURA_LUZ)
    b64_pdf = base64.b64encode(sample_pdf.read_bytes()).decode("ascii")

    factory = session_factory(make_engine(layout))
    httpd, port = bind_server(layout, factory, "dashboard_CI-VA-001_2026.html", port=18764)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = request.Request(
            f"http://127.0.0.1:{port}/api/upload",
            data=json.dumps({
                "filename": "luz_subida.pdf",
                "data": b64_pdf,
                "ocr": "native"
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8"))

        assert status == 200
        assert body["ok"] is True
        assert body["asiento_id"] is not None
        session.expire_all()
        nuevo_asiento = session.get(Asiento, body["asiento_id"])
        assert nuevo_asiento is not None
        assert "IBERDROLA" in nuevo_asiento.emisor.upper()
        assert nuevo_asiento.total is not None
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_static_sirve_fichero_bajo_la_raiz(tmp_path):
    from aeat_hub.hub_http import _static_file

    css = tmp_path / "tokens.css"
    css.write_text(":root{}", encoding="utf-8")
    assert _static_file("tokens.css", root=tmp_path) == css.resolve()


def test_static_bloquea_ausentes_y_escape_de_raiz(tmp_path):
    from aeat_hub.hub_http import _static_file

    assert _static_file("no-existe.css", root=tmp_path) is None
    assert _static_file("../fuera.css", root=tmp_path) is None


def test_quiere_ui2_detecta_bandera():
    from aeat_hub.hub_http import _quiere_ui2

    assert _quiere_ui2("ui=v2")
    assert _quiere_ui2("a=1&ui=v2")
    assert not _quiere_ui2("")
    assert not _quiere_ui2("ui=v1")
    assert not _quiere_ui2("uiv2")



def test_servidor_local_rechaza_csrf_y_dns_rebinding(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    row = _asiento(session, actividad)
    factory = session_factory(make_engine(layout))
    httpd, port = bind_server(layout, factory, "dashboard_CI-VA-001_2026.html", port=18771)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def enviar(headers: dict, data=b'{"confirmado": true, "total": "1"}') -> int:
        req = request.Request(
            f"http://127.0.0.1:{port}/api/asientos/{row.id}", data=data, headers=headers, method="POST"
        )
        try:
            with request.urlopen(req) as resp:
                return resp.status
        except error.HTTPError as err:
            return err.code

    try:
        # formulario o fetch "simple" desde otra web: text/plain sin preflight
        assert enviar({"Content-Type": "text/plain", "Origin": "https://evil.example"}) == 403
        assert enviar({"Content-Type": "text/plain"}) == 415
        # DNS rebinding: el navegador manda el Host del dominio atacante
        assert enviar({"Content-Type": "application/json", "Host": "evil.example"}) == 403
        # la propia página (mismo origen) sigue funcionando
        assert enviar({"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"}) == 200
    finally:
        httpd.shutdown()
