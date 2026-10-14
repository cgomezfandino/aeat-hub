-- Esquema congelado a 14 oct 2026 (antes de Fixed y campos legales).
-- No editar: es el punto de partida de las migraciones.

CREATE TABLE cuentas (
	codigo VARCHAR(32) NOT NULL, 
	nombre VARCHAR(200) NOT NULL, 
	tipo VARCHAR(20) NOT NULL, 
	regimen VARCHAR(40) NOT NULL, 
	notas TEXT NOT NULL, 
	casilla VARCHAR(40) NOT NULL, 
	sistema BOOLEAN NOT NULL, 
	PRIMARY KEY (codigo)
);

CREATE TABLE documentos (
	id INTEGER NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	phash VARCHAR(80), 
	nombre_original VARCHAR(260) NOT NULL, 
	ruta_almacenada TEXT NOT NULL, 
	mime VARCHAR(80) NOT NULL, 
	motor_ocr VARCHAR(40) NOT NULL, 
	texto_crudo TEXT NOT NULL, 
	json_extraido TEXT NOT NULL, 
	confianza NUMERIC(4, 3) NOT NULL, 
	paginas INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_documentos_phash ON documentos (phash);

CREATE UNIQUE INDEX ix_documentos_sha256 ON documentos (sha256);

CREATE TABLE relaciones (
	id INTEGER NOT NULL, 
	origen_tipo VARCHAR(20) NOT NULL, 
	origen_id INTEGER NOT NULL, 
	destino_tipo VARCHAR(20) NOT NULL, 
	destino_id INTEGER NOT NULL, 
	tipo VARCHAR(32) NOT NULL, 
	confianza NUMERIC(4, 3) NOT NULL, 
	fuente VARCHAR(20) NOT NULL, 
	motivo TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_rel_destino ON relaciones (destino_tipo, destino_id);

CREATE INDEX ix_rel_origen ON relaciones (origen_tipo, origen_id);

CREATE INDEX ix_relaciones_tipo ON relaciones (tipo);

CREATE TABLE titulares (
	id INTEGER NOT NULL, 
	nif VARCHAR(12) NOT NULL, 
	nombre VARCHAR(200) NOT NULL, 
	tipo VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (nif)
);

CREATE TABLE actividades (
	id INTEGER NOT NULL, 
	codigo VARCHAR(32) NOT NULL, 
	titular_id INTEGER NOT NULL, 
	nombre VARCHAR(200) NOT NULL, 
	regimen VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (codigo), 
	FOREIGN KEY(titular_id) REFERENCES titulares (id)
);

CREATE TABLE extracciones (
	id INTEGER NOT NULL, 
	documento_id INTEGER NOT NULL, 
	numero_raw VARCHAR(120), 
	numero_norm VARCHAR(120), 
	emisor VARCHAR(200), 
	emisor_norm VARCHAR(80), 
	nif_emisor VARCHAR(12), 
	fecha DATE, 
	base NUMERIC(12, 2), 
	iva_tipo NUMERIC(5, 2), 
	iva_cuota NUMERIC(12, 2), 
	total NUMERIC(12, 2), 
	pagina_ticket INTEGER, 
	paginas_ticket INTEGER, 
	json_completo TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(documento_id) REFERENCES documentos (id)
);

CREATE INDEX ix_extracciones_documento_id ON extracciones (documento_id);

CREATE INDEX ix_extracciones_numero_norm ON extracciones (numero_norm);

CREATE TABLE facturas (
	id INTEGER NOT NULL, 
	actividad_id INTEGER NOT NULL, 
	nif_emisor VARCHAR(12), 
	emisor VARCHAR(200), 
	emisor_norm VARCHAR(80), 
	numero_norm VARCHAR(120), 
	numero_visible VARCHAR(120), 
	fecha DATE, 
	base NUMERIC(12, 2), 
	iva_tipo NUMERIC(5, 2), 
	iva_cuota NUMERIC(12, 2), 
	total NUMERIC(12, 2), 
	estado_er VARCHAR(20) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actividad_id) REFERENCES actividades (id)
);

CREATE INDEX ix_facturas_actividad_id ON facturas (actividad_id);

CREATE INDEX ix_facturas_estado_er ON facturas (estado_er);

CREATE INDEX ix_facturas_nif_emisor ON facturas (nif_emisor);

CREATE INDEX ix_facturas_numero_norm ON facturas (numero_norm);

CREATE TABLE inmuebles (
	id INTEGER NOT NULL, 
	actividad_id INTEGER NOT NULL, 
	alias VARCHAR(200) NOT NULL, 
	municipio VARCHAR(120), 
	provincia VARCHAR(80), 
	ref_catastral VARCHAR(40), 
	porcentaje_titularidad NUMERIC(5, 2) NOT NULL, 
	uso VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actividad_id) REFERENCES actividades (id)
);

CREATE TABLE reglas_aprendidas (
	id INTEGER NOT NULL, 
	actividad_id INTEGER NOT NULL, 
	nif_emisor VARCHAR(12) NOT NULL, 
	patron_descripcion VARCHAR(200) NOT NULL, 
	cuenta_codigo VARCHAR(32) NOT NULL, 
	fuente VARCHAR(20) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_regla_actividad_nif_patron UNIQUE (actividad_id, nif_emisor, patron_descripcion), 
	FOREIGN KEY(actividad_id) REFERENCES actividades (id), 
	FOREIGN KEY(cuenta_codigo) REFERENCES cuentas (codigo)
);

CREATE INDEX ix_reglas_aprendidas_actividad_id ON reglas_aprendidas (actividad_id);

CREATE TABLE proyectos_mejora (
	id INTEGER NOT NULL, 
	actividad_id INTEGER NOT NULL, 
	inmueble_id INTEGER, 
	nombre VARCHAR(200) NOT NULL, 
	ejercicio_inicio INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actividad_id) REFERENCES actividades (id), 
	FOREIGN KEY(inmueble_id) REFERENCES inmuebles (id)
);

CREATE TABLE asientos (
	id INTEGER NOT NULL, 
	actividad_id INTEGER NOT NULL, 
	inmueble_id INTEGER, 
	documento_id INTEGER, 
	factura_id INTEGER, 
	proyecto_mejora_id INTEGER, 
	tipo VARCHAR(20) NOT NULL, 
	cuenta_codigo VARCHAR(32), 
	fecha DATE, 
	ejercicio INTEGER, 
	emisor VARCHAR(200), 
	nif_emisor VARCHAR(12), 
	numero_factura VARCHAR(120), 
	descripcion TEXT NOT NULL, 
	base NUMERIC(12, 2), 
	iva_tipo NUMERIC(5, 2), 
	iva_cuota NUMERIC(12, 2), 
	total NUMERIC(12, 2), 
	estado VARCHAR(20) NOT NULL, 
	confianza_clasificacion NUMERIC(4, 3) NOT NULL, 
	origen_clasificacion VARCHAR(20) NOT NULL, 
	validado BOOLEAN NOT NULL, 
	motivo_rechazo VARCHAR(200), 
	duplicado_de_id INTEGER, 
	duplicado_nivel INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actividad_id) REFERENCES actividades (id), 
	FOREIGN KEY(inmueble_id) REFERENCES inmuebles (id), 
	FOREIGN KEY(documento_id) REFERENCES documentos (id), 
	FOREIGN KEY(factura_id) REFERENCES facturas (id), 
	FOREIGN KEY(proyecto_mejora_id) REFERENCES proyectos_mejora (id), 
	FOREIGN KEY(cuenta_codigo) REFERENCES cuentas (codigo), 
	FOREIGN KEY(duplicado_de_id) REFERENCES asientos (id)
);

CREATE INDEX ix_asientos_actividad_id ON asientos (actividad_id);

CREATE INDEX ix_asientos_ejercicio ON asientos (ejercicio);

CREATE INDEX ix_asientos_estado ON asientos (estado);

CREATE INDEX ix_asientos_factura_id ON asientos (factura_id);

CREATE INDEX ix_asientos_fecha ON asientos (fecha);

CREATE INDEX ix_asientos_nif_emisor ON asientos (nif_emisor);

CREATE TABLE cambios (
	id INTEGER NOT NULL, 
	asiento_id INTEGER NOT NULL, 
	campo VARCHAR(40) NOT NULL, 
	antes TEXT NOT NULL, 
	despues TEXT NOT NULL, 
	fuente VARCHAR(40) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asiento_id) REFERENCES asientos (id)
);

CREATE INDEX ix_cambios_asiento_id ON cambios (asiento_id);

CREATE TABLE lineas (
	id INTEGER NOT NULL, 
	asiento_id INTEGER NOT NULL, 
	posicion INTEGER NOT NULL, 
	codigo VARCHAR(80), 
	descripcion VARCHAR(200) NOT NULL, 
	cantidad NUMERIC(12, 3), 
	base NUMERIC(12, 2), 
	iva_tipo NUMERIC(5, 2), 
	iva_cuota NUMERIC(12, 2), 
	importe NUMERIC(12, 2), 
	eliminada BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asiento_id) REFERENCES asientos (id)
);

CREATE INDEX ix_lineas_asiento_id ON lineas (asiento_id);
