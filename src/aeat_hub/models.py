"""Modelos SQLAlchemy del libro."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    porcentaje_titularidad: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("100.00"))
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    asientos: Mapped[list[Asiento]] = relationship(back_populates="documento")


class Asiento(Base):
    __tablename__ = "asientos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actividad_id: Mapped[int] = mapped_column(ForeignKey("actividades.id"), index=True)
    inmueble_id: Mapped[int | None] = mapped_column(ForeignKey("inmuebles.id"), nullable=True)
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documentos.id"), nullable=True)
    proyecto_mejora_id: Mapped[int | None] = mapped_column(
        ForeignKey("proyectos_mejora.id"), nullable=True
    )
    tipo: Mapped[str] = mapped_column(String(20), default="gasto")
    cuenta_codigo: Mapped[str | None] = mapped_column(ForeignKey("cuentas.codigo"), nullable=True)
    fecha: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    ejercicio: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    emisor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    nif_emisor: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    numero_factura: Mapped[str | None] = mapped_column(String(80), nullable=True)
    descripcion: Mapped[str] = mapped_column(Text, default="")
    base: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    iva_tipo: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    iva_cuota: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", index=True)
    confianza_clasificacion: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0"))
    origen_clasificacion: Mapped[str] = mapped_column(String(20), default="pendiente")
    validado: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicado_de_id: Mapped[int | None] = mapped_column(ForeignKey("asientos.id"), nullable=True)
    duplicado_nivel: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    actividad: Mapped[Actividad] = relationship(back_populates="asientos")
    documento: Mapped[Documento | None] = relationship(back_populates="asientos")
    cuenta: Mapped[Cuenta | None] = relationship()


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
