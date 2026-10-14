"""Modelos SQLAlchemy del libro."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from aeat_hub.types import Money, Quantity, Rate


class Base(DeclarativeBase):
    pass


class Titular(Base):
    __tablename__ = "titulares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nif: Mapped[str] = mapped_column(String(12), unique=True)
    nombre: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(20), default="fisica")
    actividades: Mapped[list[Actividad]] = relationship(back_populates="titular")


class Actividad(Base):
    __tablename__ = "actividades"
    __table_args__ = (UniqueConstraint("codigo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(32))
    titular_id: Mapped[int] = mapped_column(ForeignKey("titulares.id"))
    nombre: Mapped[str] = mapped_column(String(200))
    regimen: Mapped[str] = mapped_column(String(40))
    # --- Perfil fiscal (fiscal/perfil.py) ---
    epigrafe_iae: Mapped[str | None] = mapped_column(String(10), nullable=True)
    regimen_irpf: Mapped[str | None] = mapped_column(String(40), nullable=True)
    regimen_iva: Mapped[str | None] = mapped_column(String(40), nullable=True)
    territorio: Mapped[str] = mapped_column(String(20), default="comun", server_default="comun")
    fecha_alta: Mapped[date | None] = mapped_column(Date, nullable=True)
    # % de la vivienda afecto a la actividad (m² afectos / m² totales)
    afectacion_vivienda_pct: Mapped[Decimal | None] = mapped_column(Rate(), nullable=True)
    # rendimiento neto del ejercicio anterior (minoración casilla 13 del 130)
    rendimiento_anterior: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    titular: Mapped[Titular] = relationship(back_populates="actividades")
    inmuebles: Mapped[list[Inmueble]] = relationship(back_populates="actividad")
    asientos: Mapped[list[Asiento]] = relationship(back_populates="actividad")


class Inmueble(Base):
    __tablename__ = "inmuebles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actividad_id: Mapped[int] = mapped_column(ForeignKey("actividades.id"))
    alias: Mapped[str] = mapped_column(String(200))
    municipio: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provincia: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ref_catastral: Mapped[str | None] = mapped_column(String(40), nullable=True)
    porcentaje_titularidad: Mapped[Decimal] = mapped_column(Rate(), default=Decimal("100.00"))
    uso: Mapped[str] = mapped_column(String(40), default="vivienda")
    actividad: Mapped[Actividad] = relationship(back_populates="inmuebles")


class Cuenta(Base):
    __tablename__ = "cuentas"

    codigo: Mapped[str] = mapped_column(String(32), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(20))
    regimen: Mapped[str] = mapped_column(String(40))
    notas: Mapped[str] = mapped_column(Text, default="")
    casilla: Mapped[str] = mapped_column(String(40), default="")
    sistema: Mapped[bool] = mapped_column(Boolean, default=True)


class ProyectoMejora(Base):
    __tablename__ = "proyectos_mejora"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actividad_id: Mapped[int] = mapped_column(ForeignKey("actividades.id"))
    inmueble_id: Mapped[int | None] = mapped_column(ForeignKey("inmuebles.id"), nullable=True)
    nombre: Mapped[str] = mapped_column(String(200))
    ejercicio_inicio: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Documento(Base):
    __tablename__ = "documentos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    phash: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    nombre_original: Mapped[str] = mapped_column(String(260))
    ruta_almacenada: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(80), default="application/octet-stream")
    motor_ocr: Mapped[str] = mapped_column(String(40), default="")
    texto_crudo: Mapped[str] = mapped_column(Text, default="")
    json_extraido: Mapped[str] = mapped_column(Text, default="{}")
    confianza: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0"))
    paginas: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    asientos: Mapped[list[Asiento]] = relationship(back_populates="documento")
    extracciones: Mapped[list[Extraccion]] = relationship(back_populates="documento")


class Extraccion(Base):
    __tablename__ = "extracciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey("documentos.id"), index=True)
    numero_raw: Mapped[str | None] = mapped_column(String(120), nullable=True)
    numero_norm: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    emisor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    emisor_norm: Mapped[str | None] = mapped_column(String(80), nullable=True)
    nif_emisor: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha: Mapped[date | None] = mapped_column(Date, nullable=True)
    base: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    iva_tipo: Mapped[Decimal | None] = mapped_column(Rate(), nullable=True)
    iva_cuota: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    pagina_ticket: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paginas_ticket: Mapped[int | None] = mapped_column(Integer, nullable=True)
    json_completo: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    documento: Mapped[Documento] = relationship(back_populates="extracciones")


class Factura(Base):
    __tablename__ = "facturas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actividad_id: Mapped[int] = mapped_column(ForeignKey("actividades.id"), index=True)
    nif_emisor: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    emisor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    emisor_norm: Mapped[str | None] = mapped_column(String(80), nullable=True)
    numero_norm: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    numero_visible: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fecha: Mapped[date | None] = mapped_column(Date, nullable=True)
    base: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    iva_tipo: Mapped[Decimal | None] = mapped_column(Rate(), nullable=True)
    iva_cuota: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    estado_er: Mapped[str] = mapped_column(String(20), default="propuesta", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    asientos: Mapped[list[Asiento]] = relationship(back_populates="factura")


class Relacion(Base):
    __tablename__ = "relaciones"
    __table_args__ = (
        Index("ix_rel_destino", "destino_tipo", "destino_id"),
        Index("ix_rel_origen", "origen_tipo", "origen_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origen_tipo: Mapped[str] = mapped_column(String(20))
    origen_id: Mapped[int] = mapped_column(Integer)
    destino_tipo: Mapped[str] = mapped_column(String(20))
    destino_id: Mapped[int] = mapped_column(Integer)
    tipo: Mapped[str] = mapped_column(String(32), index=True)
    confianza: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("1"))
    fuente: Mapped[str] = mapped_column(String(20), default="modelo")
    motivo: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Asiento(Base):
    __tablename__ = "asientos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actividad_id: Mapped[int] = mapped_column(ForeignKey("actividades.id"), index=True)
    inmueble_id: Mapped[int | None] = mapped_column(ForeignKey("inmuebles.id"), nullable=True)
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documentos.id"), nullable=True)
    factura_id: Mapped[int | None] = mapped_column(ForeignKey("facturas.id"), nullable=True, index=True)
    proyecto_mejora_id: Mapped[int | None] = mapped_column(
        ForeignKey("proyectos_mejora.id"), nullable=True
    )
    tipo: Mapped[str] = mapped_column(String(20), default="gasto")
    cuenta_codigo: Mapped[str | None] = mapped_column(ForeignKey("cuentas.codigo"), nullable=True)
    fecha: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    ejercicio: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    emisor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    nif_emisor: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    numero_factura: Mapped[str | None] = mapped_column(String(120), nullable=True)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    base: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    iva_tipo: Mapped[Decimal | None] = mapped_column(Rate(), nullable=True)
    iva_cuota: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", index=True)
    confianza_clasificacion: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0"))
    origen_clasificacion: Mapped[str] = mapped_column(String(20), default="pendiente")
    validado: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo_rechazo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    duplicado_de_id: Mapped[int | None] = mapped_column(ForeignKey("asientos.id"), nullable=True)
    duplicado_nivel: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # --- Campos legales (RD 1619/2012 art. 6, 7 y 15) ---
    # recibida | emitida, respecto al titular del expediente.
    direccion: Mapped[str] = mapped_column(String(10), default="recibida", server_default="recibida")
    # completa | simplificada | rectificativa (los códigos SII F1/F2/R1-R5 se
    # derivan al exportar; la causa de la rectificativa decide el R).
    tipo_factura: Mapped[str | None] = mapped_column(String(20), nullable=True)
    serie: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fecha_operacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    receptor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    nif_receptor: Mapped[str | None] = mapped_column(String(20), nullable=True)
    factura_rectificada: Mapped[str | None] = mapped_column(String(120), nullable=True)
    factura_rectificada_id: Mapped[int | None] = mapped_column(
        ForeignKey("asientos.id"), nullable=True
    )
    causa_rectificacion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    retencion_tipo: Mapped[Decimal | None] = mapped_column(Rate(), nullable=True)
    retencion_cuota: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    recargo_cuota: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    moneda: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    # exenta_art20 | inversion_sujeto_pasivo | criterio_caja | no_sujeta …
    mencion_legal: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # % de afectación a la actividad decidido por la persona (anula la regla)
    afectacion_pct: Mapped[Decimal | None] = mapped_column(Rate(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    actividad: Mapped[Actividad] = relationship(back_populates="asientos")
    documento: Mapped[Documento | None] = relationship(back_populates="asientos")
    factura: Mapped[Factura | None] = relationship(back_populates="asientos")
    cuenta: Mapped[Cuenta | None] = relationship()
    cambios: Mapped[list[Cambio]] = relationship(back_populates="asiento")
    lineas: Mapped[list[Linea]] = relationship(
        back_populates="asiento",
        order_by="Linea.posicion, Linea.id",
        cascade="all, delete-orphan",
    )
    desglose_iva: Mapped[list[AsientoIVA]] = relationship(
        back_populates="asiento",
        order_by="AsientoIVA.id",
        cascade="all, delete-orphan",
    )


class AsientoIVA(Base):
    """Desglose por tipo impositivo (art. 6.1.g RD 1619/2012).

    Una factura con 21 % y 10 % tiene dos filas; la cabecera del asiento
    conserva las sumas. El recargo de equivalencia va en la misma fila.
    """

    __tablename__ = "asiento_iva"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asiento_id: Mapped[int] = mapped_column(ForeignKey("asientos.id"), index=True)
    base: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    tipo: Mapped[Decimal | None] = mapped_column(Rate(), nullable=True)
    cuota: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    recargo_tipo: Mapped[Decimal | None] = mapped_column(Rate(), nullable=True)
    recargo_cuota: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)

    asiento: Mapped[Asiento] = relationship(back_populates="desglose_iva")


class Linea(Base):
    """Línea de desglose actual de un asiento.

    Fuente de verdad editable; `Documento.json_extraido` guarda la salida
    del modelo (OCR+parser) sin retoques humanos y `Extraccion` el histórico.
    """

    __tablename__ = "lineas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asiento_id: Mapped[int] = mapped_column(ForeignKey("asientos.id"), index=True)
    posicion: Mapped[int] = mapped_column(Integer, default=1)
    codigo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    descripcion: Mapped[str] = mapped_column(String(200), default="")
    cantidad: Mapped[Decimal | None] = mapped_column(Quantity(), nullable=True)
    base: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    iva_tipo: Mapped[Decimal | None] = mapped_column(Rate(), nullable=True)
    iva_cuota: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    importe: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    eliminada: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    asiento: Mapped[Asiento] = relationship(back_populates="lineas")


class Cambio(Base):
    __tablename__ = "cambios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asiento_id: Mapped[int] = mapped_column(ForeignKey("asientos.id"), index=True)
    campo: Mapped[str] = mapped_column(String(40))
    antes: Mapped[str] = mapped_column(Text, default="")
    despues: Mapped[str] = mapped_column(Text, default="")
    fuente: Mapped[str] = mapped_column(String(40), default="dashboard")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    asiento: Mapped[Asiento] = relationship(back_populates="cambios")


class ReglaAprendida(Base):
    __tablename__ = "reglas_aprendidas"
    __table_args__ = (
        UniqueConstraint(
            "actividad_id",
            "nif_emisor",
            "patron_descripcion",
            name="uq_regla_actividad_nif_patron",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actividad_id: Mapped[int] = mapped_column(ForeignKey("actividades.id"), index=True)
    nif_emisor: Mapped[str] = mapped_column(String(12), default="")
    patron_descripcion: Mapped[str] = mapped_column(String(200), default="")
    cuenta_codigo: Mapped[str] = mapped_column(ForeignKey("cuentas.codigo"))
    fuente: Mapped[str] = mapped_column(String(20), default="usuario")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
