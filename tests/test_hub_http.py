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
        assert "numero" in ids_calidad and "suma" in ids_calidad
        assert all({"id", "label", "ok", "detail"} <= set(c) for c in payload["calidad"])
    finally:
        httpd.shutdown()
        httpd.server_close()
