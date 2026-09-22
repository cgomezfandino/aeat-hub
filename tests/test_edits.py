import json
from datetime import date
from decimal import Decimal
from threading import Thread

from sqlalchemy import select

from aeat_hub.db import make_engine, session_factory
from aeat_hub.edits import lineas_de_asiento, patch_asiento
from aeat_hub.hub_http import bind_server
from aeat_hub.models import Actividad, Asiento, Cambio, Documento


def _asiento(session, actividad, **kwargs):
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
        **kwargs,
    )
    session.add(row)
    session.commit()
    return row


def test_patch_asiento_corrige_nif_iva_y_valida(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    row = _asiento(session, actividad)
    patched = patch_asiento(
        session,
        row.id,
        {
            "nif_emisor": "b-12345674",
            "base": "20,00",
            "iva_cuota": "4,20",
            "total": "24,20",
            "validado": True,
        },
    )
    session.commit()
    assert patched.nif_emisor == "B12345674"
    assert patched.base == Decimal("20.00")
    assert patched.iva_cuota == Decimal("4.20")
    assert patched.total == Decimal("24.20")
    assert patched.iva_tipo == Decimal("21.00")
    assert patched.validado is True
    assert patched.estado == "confirmado"
    assert patched.origen_clasificacion == "usuario"
    logs = list(session.scalars(select(Cambio).where(Cambio.asiento_id == row.id).order_by(Cambio.id)))
    campos = {item.campo: item for item in logs}
    assert campos["nif_emisor"].antes == "B84818442"
    assert campos["nif_emisor"].despues == "B12345674"
    assert campos["base"].antes == "25.99"
    assert campos["base"].despues == "20.00"
    assert campos["iva_cuota"].antes == "5.46"
    assert campos["iva_cuota"].despues == "4.20"
    assert campos["total"].antes == "31.45"
    assert campos["total"].despues == "24.20"
    assert campos["validado"].antes == "false"
    assert campos["validado"].despues == "true"


def test_patch_desde_libro_cambia_emisor_y_fecha_sin_tocar_importes(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    row = _asiento(session, actividad)
    patched = patch_asiento(
        session,
        row.id,
        {"emisor": "  Obramat  ", "fecha": "2026-08-15"},
    )
    assert patched.emisor == "Obramat"
    assert patched.fecha == date(2026, 8, 15)
    assert patched.ejercicio == 2026
    assert patched.base == Decimal("25.99")
    assert patched.total == Decimal("31.45")


def test_patch_quita_linea_de_direccion_y_cambia_rubro(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    row = _asiento(session, actividad)
    row.cuenta_codigo = "CI.MEJ.PVC"
    row.tipo = "mejora"
    doc = Documento(
        sha256="b" * 64,
        nombre_original="ticket.pdf",
        ruta_almacenada="/tmp/ticket.pdf",
        texto_crudo="OBRAMAT",
        json_extraido=json.dumps(
            {
                "lineas": [
                    {"descripcion": "MAYORAZGO DE CUARTE 25 5-A", "importe": None},
                    {"descripcion": "BROCA MADERA", "importe": "1.99"},
                ]
            }
        ),
    )
    session.add(doc)
    session.flush()
    row.documento_id = doc.id
    session.commit()
    patched = patch_asiento(
        session,
        row.id,
        {
            "rubro": "Hogar",
            "total": "21.44",
            "lineas": [{"descripcion": "BROCA MADERA", "importe": "1.99"}],
            "confirmado": True,
        },
    )
    session.commit()
    assert patched.cuenta_codigo == "CI.GAS.HOGAR"
    assert patched.total == Decimal("21.44")
    nombres = [item["descripcion"] for item in lineas_de_asiento(patched)]
    assert nombres == ["BROCA MADERA"]


def test_patch_asiento_vuelve_a_revision(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    row = _asiento(session, actividad)
    patch_asiento(session, row.id, {"validado": True})
    session.commit()
    patched = patch_asiento(session, row.id, {"validado": False})
    session.commit()
    assert patched.validado is False
    assert patched.estado == "pendiente"
    logs = list(session.scalars(select(Cambio).where(Cambio.asiento_id == row.id)))
    assert any(item.campo == "validado" and item.antes == "true" and item.despues == "false" for item in logs)


def test_lineas_de_asiento_desde_texto_ocr(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    doc = Documento(
        sha256="b" * 64,
        nombre_original="ticket.txt",
        ruta_almacenada="/tmp/ticket.txt",
        mime="text/plain",
        json_extraido="{}",
        texto_crudo="""
LEROY MERLIN ARROYO
B-84818442
Fecha de venta 18/09/2026
FACTURA 064-0009-720394
Tornillo DIN 4x40          2,50
Pintura plástica 4L        8,95
Total SI (EUR)
11,45
Total IVA
2,41
Total TII (EUR)
13,86
""",
    )
    session.add(doc)
    session.flush()
    row = _asiento(session, actividad, documento_id=doc.id)
    items = lineas_de_asiento(row)
    descripciones = [item["descripcion"] for item in items]
    assert "Tornillo DIN 4x40" in descripciones
    assert "Pintura plástica 4L" in descripciones
    bases = {item["base"] for item in items}
    assert "2.50" in bases
    assert "8.95" in bases
    assert items[0]["iva_tipo"] == "21.00"


def test_hub_rechaza_cambio_sin_confirmar(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    row = _asiento(session, actividad)
    factory = session_factory(make_engine(layout))
    httpd, port = bind_server(layout, factory, "dashboard_CI-VA-001_2026.html", port=18766)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/asientos/{row.id}",
            data=b'{"nif_emisor":"B12345674","validado":true}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req)
            raise AssertionError("debía exigir confirmación")
        except urllib.error.HTTPError as err:
            assert err.code == 400
        session.expire_all()
        fresh = session.get(Asiento, row.id)
        assert fresh.nif_emisor == "B84818442"
        assert not session.scalars(select(Cambio).where(Cambio.asiento_id == row.id)).all()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hub_sirve_documento_y_guarda_asiento(session, layout):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    pdf = layout.archivo / "ticket.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 demo")
    doc = Documento(
        sha256="a" * 64,
        nombre_original="ticket.pdf",
        ruta_almacenada=str(pdf),
        mime="application/pdf",
    )
    session.add(doc)
    session.flush()
    row = _asiento(session, actividad, documento_id=doc.id)
    factory = session_factory(make_engine(layout))
    httpd, port = bind_server(layout, factory, "dashboard_CI-VA-001_2026.html", port=18765)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/asiento/{row.id}") as resp:
            assert resp.status == 200
            page = resp.read().decode("utf-8")
        assert "Volver al libro" in page
        assert "Líneas de la factura" in page
        assert "Qué se compró" not in page
        assert 'class="doc-open"' in page
        assert "Abrir documento" in page
        assert 'aria-label="Filtrar Id"' in page
        assert "Subtotal" in page
        assert "LEROY DEMO" in page
        assert f'href="/doc/{row.id}"' in page
        assert f'href="/dashboard_CI-VA-001_2026.html#asiento-{row.id}"' in page
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/doc/{row.id}") as resp:
            assert resp.status == 200
            assert resp.read().startswith(b"%PDF")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/asientos/{row.id}") as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["ok"] is True
        assert payload["nif_emisor"] == "B84818442"
        assert "lineas" in payload
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/asientos/{row.id}",
            data=b'{"nif_emisor":"B12345674","validado":true,"confirmado":true}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
        assert '"ok": true' in body or '"ok":true' in body
        session.expire_all()
        fresh = session.get(Asiento, row.id)
        assert fresh.nif_emisor == "B12345674"
        assert fresh.validado is True
        logs = list(session.scalars(select(Cambio).where(Cambio.asiento_id == row.id)))
        assert any(item.campo == "nif_emisor" and item.despues == "B12345674" for item in logs)
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_hub_personaliza_titulos_del_libro(session, layout):
    factory = session_factory(make_engine(layout))
    httpd, port = bind_server(layout, factory, "dashboard_CI-VA-001_2026.html", port=18764)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/expediente",
            data=json.dumps(
                {
                    "nombre": "Alquiler piso Centro",
                    "titular": "Ana Demo",
                    "inmueble": "Piso VA",
                    "confirmado": True,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["ok"] is True
        assert payload["nombre"] == "Alquiler piso Centro"
        assert payload["titular"] == "Ana Demo"
        assert payload["inmueble"] == "Piso VA"
        session.expire_all()
        actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
        assert actividad.nombre == "Alquiler piso Centro"
    finally:
        httpd.shutdown()
        httpd.server_close()
