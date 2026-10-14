"""API HTTP del motor fiscal (FastAPI).

Seguridad (también en local):
- **Token siempre obligatorio** (`Authorization: Bearer`), salvo /api/salud.
  Si no hay `AEAT_HUB_API_TOKEN`, se genera uno y se guarda en
  `<data-dir>/api-token` (0600). Un navegador no puede añadir esa cabecera
  a una petición de otro origen sin preflight, y no hay CORS: sin CSRF.
- **Host permitido** (`AEAT_HUB_API_HOSTS`): frena el DNS rebinding.
- **Sin cabecera Origin**: la web llama servidor a servidor; cualquier
  petición que traiga Origin viene de un navegador y se rechaza.
"""

from __future__ import annotations

import hmac
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from aeat_hub.api import consultas
from aeat_hub.api import esquemas as e
from aeat_hub.db import create_schema, make_engine, session_factory, session_scope
from aeat_hub.paths import DataLayout, resolve_layout

ENV_TOKEN = "AEAT_HUB_API_TOKEN"
ENV_HOSTS = "AEAT_HUB_API_HOSTS"
HOSTS_POR_DEFECTO = ("127.0.0.1", "localhost", "::1", "[::1]", "api", "testserver")
FICHERO_TOKEN = "api-token"


def token_local(layout: DataLayout) -> str:
    """Token del data-dir; se crea con permisos 0600 si no existe."""
    import secrets

    ruta = layout.root / FICHERO_TOKEN
    if ruta.is_file():
        guardado = ruta.read_text(encoding="utf-8").strip()
        if guardado:
            return guardado
    nuevo = secrets.token_urlsafe(32)
    layout.root.mkdir(parents=True, exist_ok=True)
    ruta.touch(mode=0o600, exist_ok=True)
    ruta.chmod(0o600)
    ruta.write_text(nuevo + "\n", encoding="utf-8")
    return nuevo
Modelo = Literal["303", "130", "111", "115", "349", "347", "390"]


class PatchAsiento(BaseModel):
    """Correcciones de la ficha; mismos campos que `edits.patch_asiento`."""

    nif_emisor: str | None = None
    emisor: str | None = None
    numero: str | None = None
    fecha: date | None = None
    base: Decimal | str | None = None
    iva_cuota: Decimal | str | None = None
    total: Decimal | str | None = None
    rubro: str | None = None
    afectacion_pct: Decimal | str | None = None
    validado: bool | None = None
    mantener_estado: bool | None = None
    rechazar: bool | None = None
    motivo_rechazo: str | None = None
    duplicado_de: int | None = None
    quitar_duplicado: bool | None = None
    lineas: list[dict] | None = None
    recalcular_total: bool | None = None


class PatchPerfil(BaseModel):
    nif_titular: str | None = None
    regimen_irpf: str | None = None
    regimen_iva: str | None = None
    epigrafe_iae: str | None = None
    territorio: str | None = None
    fecha_alta: date | None = None
    afectacion_vivienda_pct: Decimal | str | None = None
    rendimiento_anterior: Decimal | str | None = None


def create_app(layout: DataLayout | None = None, *, token: str | None = None) -> FastAPI:
    layout = layout or resolve_layout()
    token = (token if token is not None else os.environ.get(ENV_TOKEN, "")).strip() or token_local(layout)
    hosts = {
        h.strip().lower()
        for h in (os.environ.get(ENV_HOSTS) or ",".join(HOSTS_POR_DEFECTO)).split(",")
        if h.strip()
    }
    engine = make_engine(layout)
    # Como la CLI: la base queda en la última migración antes de atender peticiones.
    create_schema(engine)
    factory = session_factory(engine)

    app = FastAPI(
        title="AEAT Hub",
        version="0.2.0",
        description="Motor fiscal de AEAT Hub. No es software oficial de la AEAT; nada se presenta.",
        responses={401: {"model": e.Error}, 404: {"model": e.Error}, 400: {"model": e.Error}},
    )

    @app.middleware("http")
    async def autenticacion(request: Request, call_next):
        host = (request.headers.get("host") or "").lower()
        nombre_host = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        if nombre_host not in hosts:
            return JSONResponse({"detail": "Host no permitido"}, status_code=403)
        if request.headers.get("origin"):
            return JSONResponse({"detail": "La API no atiende a navegadores"}, status_code=403)
        if request.url.path == "/api/salud":
            return await call_next(request)
        cabecera = request.headers.get("authorization", "")
        recibido = cabecera.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(recibido.encode(), token.encode()):
            return JSONResponse({"detail": "No autorizado"}, status_code=401)
        return await call_next(request)

    def sesion():
        with factory() as session:
            yield session

    def escritura():
        with session_scope(factory) as session:
            yield session

    def _error(err: Exception):
        if isinstance(err, consultas.NoEncontrado):
            raise HTTPException(404, str(err)) from err
        if isinstance(err, (ValueError, RuntimeError)):
            raise HTTPException(400, str(err)) from err
        raise err

    @app.get("/api/salud")
    def salud() -> dict:
        return {"ok": True}

    @app.get("/api/actividades", response_model=list[e.Actividad])
    def actividades(session: Session = Depends(sesion)):
        return consultas.listar_actividades(session)

    @app.get("/api/actividades/{codigo}/resumen", response_model=e.Resumen)
    def resumen(codigo: str, ejercicio: int, session: Session = Depends(sesion)):
        try:
            return consultas.resumen(session, codigo, ejercicio)
        except Exception as err:  # noqa: BLE001
            _error(err)

    @app.get("/api/actividades/{codigo}/asientos", response_model=list[e.FilaAsiento])
    def asientos(
        codigo: str,
        ejercicio: int | None = None,
        vista: Literal["todos", "por_revisar", "libro", "duplicados", "rechazados"] = "todos",
        q: str | None = None,
        session: Session = Depends(sesion),
    ):
        try:
            return consultas.listar_asientos(session, codigo, ejercicio, vista=vista, q=q)
        except Exception as err:  # noqa: BLE001
            _error(err)

    @app.get("/api/actividades/{codigo}/incidencias", response_model=list[e.Incidencia])
    def incidencias(codigo: str, ejercicio: int, session: Session = Depends(sesion)):
        try:
            return consultas.incidencias(session, codigo, ejercicio)
        except Exception as err:  # noqa: BLE001
            _error(err)

    @app.get("/api/asientos/{asiento_id}", response_model=e.Ficha)
    def ficha(asiento_id: int, session: Session = Depends(sesion)):
        try:
            return consultas.ficha(session, asiento_id, raiz=layout.root)
        except Exception as err:  # noqa: BLE001
            _error(err)

    @app.patch("/api/asientos/{asiento_id}", response_model=e.Ficha)
    def corregir(asiento_id: int, cambios: PatchAsiento, session: Session = Depends(escritura)):
        from aeat_hub.edits import AsientoNoEncontrado, patch_asiento

        payload = cambios.model_dump(exclude_unset=True, mode="json")
        try:
            patch_asiento(session, asiento_id, payload)
            session.flush()
            return consultas.ficha(session, asiento_id, raiz=layout.root)
        except AsientoNoEncontrado as err:
            raise HTTPException(404, f"No existe el asiento {asiento_id}.") from err
        except Exception as err:  # noqa: BLE001
            _error(err)

    @app.get("/api/asientos/{asiento_id}/documento", response_class=FileResponse)
    def documento(asiento_id: int, session: Session = Depends(sesion)):
        from aeat_hub.models import Asiento

        asiento = session.get(Asiento, asiento_id)
        doc = asiento.documento if asiento is not None else None
        if doc is None or not doc.ruta_almacenada:
            raise HTTPException(404, "Sin documento.")
        ruta = Path(doc.ruta_almacenada).resolve()
        if not ruta.is_file() or not ruta.is_relative_to(layout.root.resolve()):
            raise HTTPException(404, "Fichero no disponible.")
        return FileResponse(ruta, filename=doc.nombre_original or ruta.name, content_disposition_type="inline")

    @app.post("/api/actividades/{codigo}/documentos", response_model=list[e.ResultadoSubida])
    async def subir(codigo: str, ficheros: list[UploadFile] = File(...)):
        from aeat_hub.ingest import ingest_file
        from aeat_hub.subidas import TAMANO_MAXIMO, destino_libre, nombre_seguro

        resultados: list[e.ResultadoSubida] = []
        ocr = "gemini" if (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")) else "auto"
        for fichero in ficheros:
            nombre = nombre_seguro(fichero.filename or "")
            if nombre is None:
                resultados.append(e.ResultadoSubida(
                    nombre=fichero.filename or "", asiento_id=None, estado="error",
                    detalle="Tipo de fichero no admitido (PDF o imagen).", avisos=[],
                ))
                continue
            contenido = await fichero.read(TAMANO_MAXIMO + 1)
            if len(contenido) > TAMANO_MAXIMO:
                resultados.append(e.ResultadoSubida(
                    nombre=nombre, asiento_id=None, estado="error", detalle="Más de 25 MB.", avisos=[],
                ))
                continue
            layout.inbox.mkdir(parents=True, exist_ok=True)
            destino = destino_libre(layout.inbox, nombre)
            destino.write_bytes(contenido)
            with session_scope(factory) as session:
                try:
                    act = consultas.actividad(session, codigo)
                except consultas.NoEncontrado as err:
                    destino.unlink(missing_ok=True)
                    raise HTTPException(404, str(err)) from err
                item = ingest_file(session, layout, destino, act, ocr_prefer=ocr, from_inbox=True)
            resultados.append(e.ResultadoSubida(
                nombre=nombre, asiento_id=item.asiento_id, estado=item.estado, detalle=item.detalle,
                avisos=item.warnings,
            ))
        return resultados

    @app.get("/api/actividades/{codigo}/libros", response_model=e.Libros)
    def libros(codigo: str, ejercicio: int, trimestre: int | None = Query(None, ge=1, le=4),
               session: Session = Depends(sesion)):
        from aeat_hub.export_fiscal import datos
        from aeat_hub.fiscal.libros import construir

        try:
            act, nif, filas, nombres = datos(session, codigo)
        except RuntimeError as err:
            raise HTTPException(404, str(err)) from err
        return consultas.libros(
            construir(filas, act, ejercicio, titular_nif=nif, nombres_cuenta=nombres, trimestre=trimestre)
        )

    @app.get("/api/actividades/{codigo}/modelos/{modelo}", response_model=e.Borrador)
    def modelo(codigo: str, modelo: Modelo, ejercicio: int, trimestre: int | None = Query(None, ge=1, le=4),
               session: Session = Depends(sesion)):
        from aeat_hub.export_fiscal import ANUALES, TRIMESTRALES, datos

        try:
            act, nif, filas, _ = datos(session, codigo)
        except RuntimeError as err:
            raise HTTPException(404, str(err)) from err
        if modelo in TRIMESTRALES:
            if trimestre is None:
                raise HTTPException(400, f"El modelo {modelo} es trimestral: indica el trimestre.")
            b = TRIMESTRALES[modelo](filas, act, ejercicio, trimestre, titular_nif=nif)
        else:
            b = ANUALES[modelo](filas, act, ejercicio, titular_nif=nif)
        return consultas.borrador(b)

    @app.get("/api/actividades/{codigo}/exportar/{que}", response_class=FileResponse)
    def exportar(codigo: str, que: Literal["libros", "303", "130", "111", "115", "349", "347", "390"],
                 ejercicio: int, trimestre: int | None = Query(None, ge=1, le=4),
                 session: Session = Depends(sesion)):
        from aeat_hub.export_fiscal import borrador_de, libros_de

        try:
            if que == "libros":
                _, ruta = libros_de(session, layout, codigo, ejercicio, trimestre)
            else:
                _, ruta = borrador_de(session, layout, que, codigo, ejercicio, trimestre)
        except RuntimeError as err:
            raise HTTPException(400, str(err)) from err
        return FileResponse(ruta, filename=ruta.name)

    @app.get("/api/actividades/{codigo}/perfil", response_model=e.Perfil)
    def perfil(codigo: str, session: Session = Depends(escritura)):
        from aeat_hub.services import patch_perfil

        try:
            return patch_perfil(session, codigo, {})
        except Exception as err:  # noqa: BLE001
            _error(err)

    @app.patch("/api/actividades/{codigo}/perfil", response_model=e.Perfil)
    def cambiar_perfil(codigo: str, cambios: PatchPerfil, session: Session = Depends(escritura)):
        from aeat_hub.services import patch_perfil

        try:
            return patch_perfil(session, codigo, cambios.model_dump(exclude_unset=True, mode="json"))
        except Exception as err:  # noqa: BLE001
            _error(err)

    return app
