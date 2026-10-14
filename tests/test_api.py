"""API HTTP: autenticación, importes exactos, fichas, correcciones y borradores."""

from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aeat_hub.api.app import create_app
from aeat_hub.models import Actividad, Asiento
from tests.samples import FACTURA_LUZ, write_pdf


@pytest.fixture
def datos(session):
    actividad = session.scalar(select(Actividad).where(Actividad.codigo == "CI-VA-001"))
    filas = [
        Asiento(actividad_id=actividad.id, tipo="ingreso", cuenta_codigo="CI.ING.RENTA", fecha=date(2026, 3, 1),
                ejercicio=2026, total=D("700.10"), estado="confirmado", validado=True),
        Asiento(actividad_id=actividad.id, tipo="gasto", cuenta_codigo="CI.GAS.LUZ", fecha=date(2026, 3, 9),
                ejercicio=2026, emisor="IBERDROLA", nif_emisor="B12345674", base=D("40.00"), iva_tipo=D("21"),
                iva_cuota=D("8.40"), total=D("48.40"), estado="confirmado", validado=True),
        Asiento(actividad_id=actividad.id, tipo="gasto", fecha=date(2026, 4, 2), ejercicio=2026,
                emisor="SIN NIF SL", total=D("0.20"), estado="pendiente"),
    ]
    session.add_all(filas)
    session.commit()
    return [f.id for f in filas]


TOKEN = "secreto-de-prueba"


@pytest.fixture
def cliente(layout, datos):
    return TestClient(create_app(layout, token=TOKEN), headers={"Authorization": f"Bearer {TOKEN}"})


def test_token_obligatorio(layout, datos):
    api = TestClient(create_app(layout, token=TOKEN))
    assert api.get("/api/salud").status_code == 200
    assert api.get("/api/actividades").status_code == 401
    assert api.get("/api/actividades", headers={"Authorization": "Bearer otro"}).status_code == 401
    assert api.get("/api/actividades", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_sin_token_configurado_se_genera_uno_privado(layout, datos):
    """Local sin configurar nada: también exige token (sin CSRF desde el navegador)."""
    import stat

    api = TestClient(create_app(layout, token=""))
    assert api.get("/api/actividades").status_code == 401
    ruta = layout.root / "api-token"
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600
    generado = ruta.read_text().strip()
    assert api.get("/api/actividades", headers={"Authorization": f"Bearer {generado}"}).status_code == 200


def test_dns_rebinding_y_peticiones_de_navegador(cliente):
    assert cliente.get("/api/actividades", headers={"Host": "evil.example"}).status_code == 403
    assert cliente.get("/api/actividades", headers={"Host": "127.0.0.1:8000"}).status_code == 200
    # una web ajena que intenta subir un fichero desde el navegador
    r = cliente.post("/api/actividades/CI-VA-001/documentos", headers={"Origin": "https://evil.example"},
                     files=[("ficheros", ("a.pdf", b"%PDF", "application/pdf"))])
    assert r.status_code == 403


def test_resumen_con_importes_exactos_en_cadena(cliente):
    r = cliente.get("/api/actividades/CI-VA-001/resumen", params={"ejercicio": 2026}).json()
    assert r["ingresos"] == "700.10"
    assert r["gastos"] == "48.40"  # exento: el IVA es mayor gasto
    assert r["resultado"] == "651.70"
    assert r["n_por_revisar"] == 1 and r["total_por_revisar"] == "0.20"
    assert r["por_mes"][2]["ingresos"] == "700.10"


def test_listado_por_vistas(cliente, datos):
    todos = cliente.get("/api/actividades/CI-VA-001/asientos", params={"ejercicio": 2026}).json()
    assert len(todos) == 3
    libro = cliente.get("/api/actividades/CI-VA-001/asientos", params={"ejercicio": 2026, "vista": "libro"}).json()
    assert {f["id"] for f in libro} == set(datos[:2])
    assert all(f["computa"] for f in libro)
    busqueda = cliente.get("/api/actividades/CI-VA-001/asientos", params={"q": "iberdrola"}).json()
    assert [f["id"] for f in busqueda] == [datos[1]]


def test_ficha_con_deducibilidad_y_correccion(cliente, datos):
    ficha = cliente.get(f"/api/asientos/{datos[1]}").json()
    assert ficha["deducibilidad"]["importe_irpf"] == "48.40"
    assert any("art. 94" in r["cita"] for r in ficha["deducibilidad"]["reglas"])
    r = cliente.patch(f"/api/asientos/{datos[1]}", json={"total": "48,41", "mantener_estado": True})
    assert r.status_code == 200 and r.json()["total"] == "48.41"
    assert any(c["campo"] == "total" for c in r.json()["cambios"])
    malo = cliente.patch(f"/api/asientos/{datos[1]}", json={"nif_emisor": "B12345675"})
    assert malo.status_code == 400 and "no es válido" in malo.json()["detail"]
    assert cliente.get("/api/asientos/999999").status_code == 404


def test_incidencias(cliente, datos):
    tipos = {(i["tipo"], i["asiento_id"]) for i in cliente.get(
        "/api/actividades/CI-VA-001/incidencias", params={"ejercicio": 2026}).json()}
    assert ("perfil", None) in tipos  # NIF de ejemplo
    assert ("nif", datos[2]) in tipos and ("sin_clasificar", datos[2]) in tipos


def test_borradores_y_libros(cliente):
    b = cliente.get("/api/actividades/CI-VA-001/modelos/303", params={"ejercicio": 2026, "trimestre": 1}).json()
    assert b["aplica"] is False
    assert cliente.get("/api/actividades/CI-VA-001/modelos/303", params={"ejercicio": 2026}).status_code == 400
    libros = cliente.get("/api/actividades/CI-VA-001/libros", params={"ejercicio": 2026}).json()
    assert len(libros["ingresos"]) == 1 and len(libros["gastos"]) == 1
    xlsx = cliente.get("/api/actividades/CI-VA-001/exportar/libros", params={"ejercicio": 2026})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_perfil_valida(cliente):
    assert cliente.patch("/api/actividades/CI-VA-001/perfil", json={"regimen_iva": "inventado"}).status_code == 400
    ok = cliente.patch("/api/actividades/CI-VA-001/perfil", json={"nif_titular": "12345678Z"}).json()
    assert ok["nif_titular"] == "12345678Z"


def test_subida_rechaza_extensiones_y_procesa_pdf(cliente, layout, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from aeat_hub.ocr import cascade
    from aeat_hub.ocr.pdf_native import PdfNativeProvider

    monkeypatch.setattr(cascade, "_scan", lambda path, **kw: PdfNativeProvider().transcribe(path))
    pdf = write_pdf(layout.root / "luz.pdf", FACTURA_LUZ)
    r = cliente.post(
        "/api/actividades/CI-VA-001/documentos",
        files=[("ficheros", ("../../luz.pdf", pdf.read_bytes(), "application/pdf")),
               ("ficheros", ("malo.exe", b"MZ", "application/octet-stream"))],
    ).json()
    assert r[0]["nombre"] == "luz.pdf" and r[0]["asiento_id"] is not None
    assert r[1]["estado"] == "error"
    doc = cliente.get(f"/api/asientos/{r[0]['asiento_id']}/documento")
    assert doc.status_code == 200 and doc.content[:4] == b"%PDF"
